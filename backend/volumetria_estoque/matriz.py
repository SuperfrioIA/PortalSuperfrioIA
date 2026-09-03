"""A Matriz do estoque: unidade › cliente › câmara, mês nas colunas — em
modo **posição**, não soma.

## Por que este arquivo é diferente do irmão em `volumetria_transporte`

O T0 mediu (04/set/2026): a contagem de linhas por dia em
`FATO_VOL_EST_CAT_V01` fica estável entre 561 e 577 — é **foto diária**
(saldo), não fluxo. Somar 30 fotos de um mês de um estoque que nunca passou
de 100 t daria 3.000 t. A opção escolhida (A, recomendada em
`docs/PLANO_VOLUMETRIA_TRANSPORTE_ESTOQUE.md`, seção "Estoque é saldo"):
a célula do mês mostra a **posição do último dia com dado** daquele mês,
dentro do recorte.

## A consulta, em três blocos (CTEs)

1. `base`: soma a medida por dia (pode haver mais de uma linha por
   unidade/cliente/câmara no mesmo dia — ex.: dois `status_lote` diferentes —
   e elas SOMAM dentro do mesmo dia, porque são a mesma posição vista em dois
   lotes);
2. `maximo`: o último dia COM DADO de cada grupo, dentro do recorte —
   **não** é o último dia do calendário; é o último dia que a consulta
   encontrou. Um período com furo de dado no fim do mês pega o dia anterior,
   e é isso que "posição do último dia com dado" quer dizer;
3. a consulta final junta os dois e devolve só a linha do dia escolhido —
   uma linha por (unidade, cliente, câmara, mês), nunca mais de uma.

## Câmara nula não pode entrar em `GROUP BY`/`JOIN` como está

`NULL = NULL` é falso em SQL — juntar por `camara` faria a foto de uma câmara
nula em `base` nunca encontrar sua própria linha em `maximo`. Por isso o
agrupamento usa `NVL(f.camara, :camara_sentinela)` (uma marca ASCII interna,
nunca exibida — ver `contrato.CAMARA_SENTINELA_SQL`), e o rótulo de verdade
(`MAX(f.camara)`, que fica `NULL` quando for o caso) viaja à parte só para
exibição. `recorte.py` faz o mesmo truque no filtro.

## A invariante do catering NÃO vale aqui, de propósito

No catering (e no transporte), "a soma da planilha bate com o total da
Matriz no mesmo recorte" é o teste de aceite. Aqui **não pode valer**: a
planilha mostra linhas cruas (todo dia do recorte), e a Matriz em modo
posição usa só o último dia de cada mês — comparar os dois totais daria
número diferente por desenho, não por bug. O `linhas` de cada célula conta
só as linhas do DIA ESCOLHIDO, e o rótulo do campo evita "total_linhas"
para não sugerir a invariante que não existe aqui.
"""

from backend.volumetria_estoque import contrato, recorte


def _sql(filtros: recorte.Filtros):
    coluna_medida = recorte.medida(filtros.lente)
    de_para_where, params = recorte.de_para_where(filtros)
    params["camara_sentinela"] = contrato.CAMARA_SENTINELA_SQL

    base = "\n".join((
        "SELECT f.nk_wms_filial AS unidade, f.nk_cliente AS cliente_chave,",
        "       MAX(f.raz_social) AS cliente_rotulo,",
        "       NVL(f.camara, :camara_sentinela) AS camara_chave,",
        "       MAX(f.camara) AS camara_rotulo,",
        "       TO_CHAR(f.nk_calendario, 'YYYY-MM') AS mes,",
        "       f.nk_calendario AS dia,",
        f"       SUM(f.{coluna_medida}) AS medida_dia, COUNT(*) AS linhas_dia",
        de_para_where,
        "GROUP BY f.nk_wms_filial, f.nk_cliente, NVL(f.camara, :camara_sentinela),",
        "         TO_CHAR(f.nk_calendario, 'YYYY-MM'), f.nk_calendario",
    ))
    maximo = (
        "SELECT unidade, cliente_chave, camara_chave, mes, MAX(dia) AS dia_max\n"
        "FROM base GROUP BY unidade, cliente_chave, camara_chave, mes"
    )
    final = "\n".join((
        "SELECT b.unidade, b.cliente_chave, b.cliente_rotulo, b.camara_rotulo,",
        "       b.mes, b.dia, b.medida_dia AS medida, b.linhas_dia AS linhas",
        "FROM base b",
        "JOIN maximo m",
        "  ON m.unidade = b.unidade AND m.cliente_chave = b.cliente_chave",
        " AND m.camara_chave = b.camara_chave AND m.mes = b.mes AND m.dia_max = b.dia",
    ))
    sql = f"WITH base AS (\n{base}\n),\nmaximo AS (\n{maximo}\n)\n{final}"
    return sql, params


def consultar(cur, filtros: recorte.Filtros) -> dict:
    """`{linhas: [...], meses, aviso_dias, lente, hierarquia, modo}`.

    Cada item de `linhas` já é a posição de fim de mês da célula — nada para
    somar de novo no cliente. `dia` é a data da foto (para a tela poder
    mostrar "posição de 25/08", em vez de fingir que é o mês inteiro)."""
    sql, params = _sql(filtros)
    cur.execute(sql, params)
    colunas = [d[0].lower() for d in cur.description]
    linhas = []
    for bruta in cur.fetchall():
        registro = dict(zip(colunas, bruta))
        linhas.append({
            "unidade": registro["unidade"],
            "cliente": registro["cliente_chave"],
            "cliente_rotulo": registro["cliente_rotulo"] or registro["cliente_chave"],
            "camara": registro["camara_rotulo"] or contrato.CAMARA_ROTULO_VAZIA,
            "mes": registro["mes"],
            "dia": registro["dia"].isoformat() if hasattr(registro["dia"], "isoformat") else registro["dia"],
            "valor": registro["medida"],
            "linhas": int(registro["linhas"]),
        })
    return {
        "linhas": linhas,
        "meses": recorte.rotulos_dos_meses(filtros.de, filtros.ate),
        "aviso_dias": recorte.aviso_dos_dias(filtros.dias),
        "lente": contrato.LENTES[filtros.lente],
        "hierarquia": list(contrato.HIERARQUIA),
        "modo": contrato.MODO_AGREGACAO,
    }
