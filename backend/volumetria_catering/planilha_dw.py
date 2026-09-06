"""A planilha aberta, lida do DW Oracle: linhas cruas do recorte, paginadas.

Lote C2 do plano revisado (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`).

## Mesmas colunas, mesmo recorte, outro banco

As colunas que a tela mostra e seus rótulos vêm de `planilha.py` (`colunas()`,
`_colunas_de_medida()`), sem cópia — a planilha do DW e a do Postgres têm que
ter o MESMO cabeçalho. O recorte vem de `recorte_dw.de_para_where()`, o mesmo
`FROM`/`WHERE` da Matriz do DW: somando as páginas tem que dar o total da
Matriz, e isso é estrutura, não disciplina.

## O que muda no SQL

- `LIMIT %(limite)s OFFSET %(salto)s` -> `OFFSET n ROWS FETCH NEXT m ROWS ONLY`
  (Oracle 12c+; o DW é 12.2). Os dois números são inteiros calculados aqui, não
  entrada do usuário — `pagina` já passou por `Filtros.validar()`;
- as três colunas de decisão (unidade exibida, cliente canonizado, tipo de
  estoque) saem do SQL como as colunas CRUAS do DW e são resolvidas em Python,
  linha a linha, pelo retrato de `dimensoes_dw` — sem `LEFT JOIN`;
- `nk_calendario` é `DATE` no contrato, e o Oracle o entrega como `datetime` com
  hora zero. Sai daqui como `date`, senão a tela mostra `05T00:00:00/01/2026`.
"""

from backend.volumetria_catering import contrato, dimensoes_dw, recorte_dw
from backend.volumetria_catering.planilha import LINHAS_POR_PAGINA, _colunas_de_medida, colunas

# As colunas CRUAS que o SQL lê para a tela poder montar o contexto. A ordem é
# a da leitura, não a da exibição — `colunas()` (de `planilha.py`) é quem diz a
# ordem e o rótulo que a pessoa vê.
_CRUAS = ("nk_calendario", "nk_wms_filial", "nk_cliente", "raz_social",
          "num_gem", "descr_oper_wms", "nome_estoque")


def _ordem(movimento):
    """Determinismo total: data desc, depois a chave natural — sem isto a
    página 2 pode repetir linha da página 1 em empate."""
    return f"{recorte_dw.coluna('nk_calendario', movimento)} DESC, " + ", ".join(
        recorte_dw.coluna(c, movimento) for c in contrato.CHAVE_NATURAL
    )


def _sql(filtros, medidas, dim):
    movimento = filtros.movimento
    de_para_where, params = recorte_dw.de_para_where(filtros, dim=dim)
    selecoes = [f"{recorte_dw.coluna(c, movimento)} AS {c}" for c in _CRUAS]
    selecoes += [
        f"{recorte_dw.coluna(coluna, movimento)} AS {apelido}" for apelido, coluna, _r in medidas
    ]
    salto = (filtros.pagina - 1) * LINHAS_POR_PAGINA
    sql = "\n".join((
        f"SELECT {', '.join(selecoes)}",
        de_para_where,
        f"ORDER BY {_ordem(movimento)}",
        f"OFFSET {salto} ROWS FETCH NEXT {LINHAS_POR_PAGINA} ROWS ONLY",
    ))
    return sql, params


def contar(cur, filtros, dim) -> int:
    de_para_where, params = recorte_dw.de_para_where(filtros, dim=dim)
    cur.execute(f"SELECT COUNT(*) {de_para_where}", params)
    return int(cur.fetchone()[0])


def _linha_da_tela(registro: dict, medidas, dim: dimensoes_dw.Dimensoes) -> dict:
    """Da linha crua do DW para a linha que a tela conhece — as MESMAS chaves
    do `planilha.py`, com as decisões aplicadas em Python."""
    linha = {
        "dia": dimensoes_dw.como_date(registro["nk_calendario"]),
        "unidade": dimensoes_dw.sigla_exibida(registro["nk_wms_filial"]),
        "cliente": dim.rotulo_cliente(registro["nk_cliente"], registro["raz_social"]),
        "guia": registro["num_gem"],
        "operacao": registro["descr_oper_wms"],
        "tipo_estoque": dimensoes_dw.classificar(registro["nome_estoque"]),
    }
    for apelido, _coluna, _rotulo in medidas:
        linha[apelido] = registro[apelido]
    return linha


def planilha(cur, filtros, dim: dimensoes_dw.Dimensoes) -> dict:
    """Uma página de linhas cruas do recorte, mais o total de linhas. Mesmo
    formato de resposta do `planilha.planilha()` do Postgres."""
    filtros.validar()
    medidas = _colunas_de_medida(filtros)
    total = contar(cur, filtros, dim)

    sql, params = _sql(filtros, medidas, dim)
    cur.execute(sql, params)
    nomes = [d[0].lower() for d in cur.description]
    linhas = [_linha_da_tela(dict(zip(nomes, bruta)), medidas, dim) for bruta in cur.fetchall()]

    paginas = max(1, -(-total // LINHAS_POR_PAGINA))
    return {
        "filtros": filtros.como_dict(),
        "colunas": colunas(filtros),
        "linhas": linhas,
        "lente": {
            "chave": filtros.lente,
            "nome": contrato.LENTES[filtros.lente]["nome"],
            "unidade": contrato.LENTES[filtros.lente]["unidade"],
        },
        "paginacao": {
            "pagina": filtros.pagina,
            "por_pagina": LINHAS_POR_PAGINA,
            "total_linhas": total,
            "paginas": paginas,
        },
        "avisos": [
            aviso for aviso in (
                None if filtros.pagina <= paginas else
                f"A página {filtros.pagina} está além do fim: são {paginas} página(s).",
                recorte_dw.aviso_dos_dias(filtros.dias),
            ) if aviso
        ],
    }
