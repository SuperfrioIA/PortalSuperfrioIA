"""A planilha aberta: linhas cruas do recorte, paginadas no servidor.

Cópia de `backend/volumetria_transporte/planilha.py`. **Aqui a planilha
mostra TODO dia do recorte**, não só a posição de fim de mês — é a Matriz que
agrega em modo posição (`matriz.py`); a planilha continua sendo "o dado cru",
como em todos os outros módulos. Por isso o total da planilha e o total da
Matriz **não batem** aqui, de propósito — ver a docstring de `matriz.py`.

`camara` vem `NULL` cru do banco (nunca normalizada em SQL, ao contrário da
placa do transporte): "câmara" tem acento, e um literal acentuado dentro do
texto do SQL é risco de mojibake que não vale a pena correr por uma coluna.
`consultar()` troca `None` por `contrato.CAMARA_ROTULO_VAZIA` depois do
fetch, em Python.
"""

from backend.volumetria_estoque import contrato, recorte

LINHAS_POR_PAGINA = 100

_ROTULO = {
    "nk_calendario": "Dia (da foto)",
    "nk_wms_filial": "Unidade",
    "nk_cliente": "Cliente (código)",
    "raz_social": "Cliente",
    "camara": "Câmara",
    "status_lote": "Status do lote",
    "qtde_sku": "SKUs (contagem do dia)",
}


def _expressao(nome: str) -> str:
    return f"f.{nome}"


def colunas():
    return [
        (nome, _expressao(nome), _ROTULO.get(nome, nome))
        for nome in contrato.COLUNAS_TELA
        if nome not in ("qtde_pallet", "qtde_vol", "qtde_peso", "qtde_pbrt", "qtde_vlr")
    ]


def colunas_com_medida(filtros: recorte.Filtros):
    lente = contrato.LENTES[filtros.lente]
    return colunas() + [("medida", f"f.{lente['coluna']}", lente["nome"])]


def _sql(filtros: recorte.Filtros, pagina: int):
    de_para_where, params = recorte.de_para_where(filtros)
    nomes = colunas_com_medida(filtros)
    selecoes = [f"{sql} AS {apelido}" for apelido, sql, _r in nomes]
    ordem = "f.nk_calendario DESC, " + ", ".join(
        f"f.{coluna}" for coluna in contrato.CHAVE_NATURAL
    )
    offset = (pagina - 1) * LINHAS_POR_PAGINA
    sql = "\n".join((
        f"SELECT {', '.join(selecoes)}",
        de_para_where,
        f"ORDER BY {ordem}",
        f"OFFSET {offset} ROWS FETCH NEXT {LINHAS_POR_PAGINA} ROWS ONLY",
    ))
    return sql, params


def contar(cur, filtros: recorte.Filtros) -> int:
    de_para_where, params = recorte.de_para_where(filtros)
    cur.execute(f"SELECT COUNT(*) {de_para_where}", params)
    return cur.fetchone()[0]


def consultar(cur, filtros: recorte.Filtros) -> dict:
    total = contar(cur, filtros)
    sql, params = _sql(filtros, filtros.pagina)
    cur.execute(sql, params)
    nomes = colunas_com_medida(filtros)
    linhas = [dict(zip((a for a, _s, _r in nomes), bruta)) for bruta in cur.fetchall()]
    if "camara" in {a for a, _s, _r in nomes}:
        for linha in linhas:
            if linha.get("camara") is None:
                linha["camara"] = contrato.CAMARA_ROTULO_VAZIA
    return {
        "colunas": [{"chave": a, "rotulo": r} for a, _s, r in nomes],
        "linhas": linhas,
        "total_linhas": total,
        "total_paginas": max(1, -(-total // LINHAS_POR_PAGINA)),
        "pagina": filtros.pagina,
    }
