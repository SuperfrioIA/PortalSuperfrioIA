"""A planilha aberta: linhas cruas do recorte, paginadas no servidor.

Porte de `catering/consulta/planilha.py` da nuvem-ia (main, 27/ago/2026), so
com os imports trocados.

## Mesmo recorte da Matriz, por construcao

Usa `recorte.de_para_where()` -- o mesmo `FROM`/`WHERE` da Matriz. Nao e
disciplina, e estrutura: nao existe um segundo lugar onde o filtro possa
divergir. O teste mede isso: somando todas as paginas da planilha, o total tem
que dar **exatamente** o que a Matriz agrega no mesmo recorte.

## Estreita na tela, completa no arquivo

A tela mostra dia, unidade, cliente, guia, operacao, tipo de estoque e a
**lente escolhida** (na saida, as tres faixas dela). O **download** leva a
linha inteira (`download.py`).

## Ordenacao deterministica, senao a paginacao mente

`ORDER BY nk_calendario DESC` sozinho **nao** basta: em empate o Postgres nao
promete ordem estavel entre execucoes, e a pagina 2 poderia repetir linha da
pagina 1 e omitir outra sem erro nenhum. Por isso a ordenacao completa termina
na **chave natural**, que e unica por construcao.

## `guia` aparece aqui, e nao na Matriz

O contrato tira a guia da Matriz porque contagem distinta nao soma por linha.
Na planilha ela e coluna de uma linha, nao agregado -- entao entra.
"""

from backend.volumetria_catering import contrato, recorte

LINHAS_POR_PAGINA = 100

# As colunas de contexto da tela, na ordem. `(apelido, expressao SQL, rotulo)`.
CONTEXTO = (
    ("dia", "f.nk_calendario", "Dia"),
    ("unidade", recorte.SIGLA, "Unidade"),
    ("cliente", recorte.CLIENTE_ROTULO, "Cliente"),
    ("guia", "f.num_gem", "Guia"),
    ("operacao", "f.descr_oper_wms", "Operação"),
    ("tipo_estoque", recorte.TIPO_ESTOQUE, "Tipo de estoque"),
)


def _colunas_de_medida(filtros):
    """`[(apelido, coluna, rotulo)]` da lente escolhida.

    Vazio quando a lente nao existe no movimento (pallet na expedicao) -- a
    planilha continua mostrando o contexto, so sem coluna de numero."""
    medidas = recorte.medidas_da_lente(filtros.movimento, filtros.lente)
    nome = contrato.LENTES[filtros.lente]["nome"]
    if not medidas:
        return []
    if list(medidas) == [""]:
        return [("valor", medidas[""], nome)]
    return [
        (faixa, coluna, f"{nome} — {recorte.rotulo_faixa(faixa)}")
        for faixa, coluna in medidas.items()
    ]


def colunas(filtros):
    """As colunas da planilha, na ordem, com rotulo de tela."""
    return [
        {"chave": apelido, "rotulo": rotulo}
        for apelido, _sql, rotulo in CONTEXTO
    ] + [
        {"chave": apelido, "rotulo": rotulo}
        for apelido, _sql, rotulo in _colunas_de_medida(filtros)
    ]


def _ordem():
    """Determinismo total: data desc, depois a chave natural. Ver docstring."""
    return "f.nk_calendario DESC, " + ", ".join(
        f"f.{coluna}" for coluna in contrato.CHAVE_NATURAL
    )


def planilha(cur, filtros) -> dict:
    """Uma pagina de linhas cruas do recorte, mais o total de linhas."""
    filtros.validar()
    medidas = _colunas_de_medida(filtros)
    de_para_where, params = recorte.de_para_where(filtros)

    cur.execute(f"SELECT count(*) {de_para_where}", params)
    total = cur.fetchone()[0]

    selecoes = [f"{sql} AS {apelido}" for apelido, sql, _r in CONTEXTO]
    selecoes += [f"f.{coluna} AS {apelido}" for apelido, coluna, _r in medidas]

    params = dict(params)
    params["limite"] = LINHAS_POR_PAGINA
    params["salto"] = (filtros.pagina - 1) * LINHAS_POR_PAGINA
    cur.execute(
        "\n".join((
            f"SELECT {', '.join(selecoes)}",
            de_para_where,
            f"ORDER BY {_ordem()}",
            "LIMIT %(limite)s OFFSET %(salto)s",
        )),
        params,
    )
    nomes = [d[0] for d in cur.description]
    linhas = [dict(zip(nomes, bruta)) for bruta in cur.fetchall()]

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
        # `pagina` acima do fim nao e erro: e o usuario navegando depois de
        # apertar o filtro. Devolve vazio e diz onde ele esta.
        "avisos": [
            aviso for aviso in (
                None if filtros.pagina <= paginas else
                f"A página {filtros.pagina} está além do fim: são {paginas} página(s).",
                recorte.aviso_dos_dias(filtros.dias),
            ) if aviso
        ],
    }
