"""A planilha aberta: linhas cruas do recorte, paginadas no servidor.

Mesmo recorte da Matriz (`recorte.de_para_where`), por construção — nunca um
segundo `WHERE`. As colunas mostradas são exatamente `contrato.COLUNAS_TELA`
(a regra de destino decidida em 03/set); o download leva mais colunas
(`download.py`).
"""

from backend.volumetria_transporte import contrato, recorte

LINHAS_POR_PAGINA = 100

# (apelido, expressão SQL, rótulo). A placa usa a expressão com sentinela
# normalizada (`recorte.PLACA_ROTULO`) — nunca o valor cru do DW.
_EXPRESSAO = {
    "placa": recorte.PLACA_ROTULO,
}

_ROTULO = {
    "nk_calendario": "Dia",
    "nk_wms_filial": "Unidade",
    "nk_cliente": "Cliente (código)",
    "raz_social": "Cliente",
    "nome_estoque": "Tipo de estoque",
    "tipo_viagem": "Tipo de viagem",
    "tipo_movimento": "Tipo de movimento",
    "status_viagem": "Status da viagem",
    "status_wms": "Status WMS",
    "status_baixa": "Status de baixa",
    "num_gem": "Guia (GEM)",
    "num_pedido": "Pedido",
    "num_nf": "Nota fiscal",
    "placa": "Placa",
    "data_programacao": "Data de programação",
}


def _expressao(nome: str) -> str:
    return _EXPRESSAO.get(nome, f"f.{nome}")


def colunas():
    """`[(apelido, sql, rotulo)]` das colunas de contexto — sem a lente."""
    return [
        (nome, _expressao(nome), _ROTULO.get(nome, nome))
        for nome in contrato.COLUNAS_TELA
        if nome not in ("qtde_peso", "qtde_pbrt", "qtde_vlr")
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
    return {
        "colunas": [{"chave": a, "rotulo": r} for a, _s, r in nomes],
        "linhas": linhas,
        "total_linhas": total,
        "total_paginas": max(1, -(-total // LINHAS_POR_PAGINA)),
        "pagina": filtros.pagina,
    }
