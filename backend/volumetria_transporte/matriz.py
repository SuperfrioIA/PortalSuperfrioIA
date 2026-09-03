"""A Matriz: unidade › cliente › tipo de movimento, mês nas colunas.

Diferença deliberada em relação a `volumetria_catering/matriz.py`: aqui a
hierarquia é FIXA (`contrato.HIERARQUIA`) — não há faixa, não há visão
conjunta, não há paginação de unidades por página (o T0 mediu 6 unidades no
total). Por isso o backend devolve **linhas achatadas**
(`{unidade, cliente, tipo_movimento, mes, valor, linhas}`), e é o `app.js` que
monta a árvore para exibir — mais simples dos dois lados do que replicar a
árvore pré-montada do catering, e não muda nenhum número.
"""

from backend.volumetria_transporte import contrato, recorte


def _sql(filtros: recorte.Filtros):
    coluna_medida = recorte.medida(filtros.lente)
    de_para_where, params = recorte.de_para_where(filtros)
    selecoes = (
        "f.nk_wms_filial AS unidade",
        "f.nk_cliente AS cliente_chave",
        "f.raz_social AS cliente_rotulo",
        "f.tipo_movimento AS tipo_movimento",
        "TO_CHAR(f.nk_calendario, 'YYYY-MM') AS mes",
        f"SUM(f.{coluna_medida}) AS medida",
        "COUNT(*) AS linhas",
    )
    sql = "\n".join((
        f"SELECT {', '.join(selecoes)}",
        de_para_where,
        "GROUP BY f.nk_wms_filial, f.nk_cliente, f.raz_social, f.tipo_movimento, "
        "TO_CHAR(f.nk_calendario, 'YYYY-MM')",
    ))
    return sql, params


def consultar(cur, filtros: recorte.Filtros) -> dict:
    """`{linhas: [...], meses: {mes: rotulo}, aviso_dias: str|None}`.

    Cada item de `linhas` é uma célula da árvore: uma combinação
    unidade/cliente/tipo_movimento/mês com a medida somada. `total_linhas` é
    a soma de `linhas` de cada célula — tem que bater com o total da
    planilha no mesmo recorte (é o teste de invariante)."""
    sql, params = _sql(filtros)
    cur.execute(sql, params)
    colunas = [d[0].lower() for d in cur.description]
    linhas = []
    total_linhas = 0
    for bruta in cur.fetchall():
        registro = dict(zip(colunas, bruta))
        total_linhas += int(registro["linhas"])
        linhas.append({
            "unidade": registro["unidade"],
            "cliente": registro["cliente_chave"],
            "cliente_rotulo": registro["cliente_rotulo"] or registro["cliente_chave"],
            "tipo_movimento": registro["tipo_movimento"],
            "mes": registro["mes"],
            "valor": registro["medida"],
            "linhas": int(registro["linhas"]),
        })
    return {
        "linhas": linhas,
        "total_linhas": total_linhas,
        "meses": recorte.rotulos_dos_meses(filtros.de, filtros.ate),
        "aviso_dias": recorte.aviso_dos_dias(filtros.dias),
        "lente": contrato.LENTES[filtros.lente],
        "hierarquia": list(contrato.HIERARQUIA),
    }
