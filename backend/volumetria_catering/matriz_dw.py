"""A Matriz lida do DW Oracle: só a consulta muda; a árvore é a mesma.

Lote C2 do plano revisado (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`).

## O que vem do `matriz.py` e o que é daqui

`matriz.montar()` monta a hierarquia, acumula por mês, ordena, pagina e escreve
os avisos — nada disso depende do banco, e nada disso é copiado. O que este
módulo fornece é o `consultar()` de um movimento no dialeto do Oracle, e é isso
que `montar()` recebe.

## O SQL, traduzido

| Postgres | Oracle |
|---|---|
| `to_char(date_trunc('month', f.nk_calendario), 'YYYY-MM')` | `TO_CHAR(f.NK_CALENDARIO, 'YYYY-MM')` |
| `GROUP BY 1, 2, 3` (ordinal) | `GROUP BY <as expressões>` — no Oracle, `GROUP BY 1` agrupa pela CONSTANTE 1, e a consulta compila e devolve número errado |
| `COALESCE(u.sigla, f.nk_wms_filial)` (JOIN) | `f.NK_WMS_FILIAL` cru; a sigla exibida entra em Python |
| `COALESCE(c.razao_social, f.raz_social)` (JOIN) | `MAX(f.RAZ_SOCIAL)` como queda; o rótulo canônico entra em Python |
| `count(*)` -> `int` | `COUNT(*)` -> `Decimal` (fetch_decimals); convertido com `int()` |

## A inversão que faz o de-para somar

O Oracle devolve uma linha por (`NK_WMS_FILIAL`, ...). Antes de a linha entrar
na árvore, a sigla da fonte é trocada pela exibida (`RMSPV` -> `RMSPIV`). Como a
árvore acumula por chave (`_descer` + `_acumular`), duas siglas da fonte que
caiam na mesma exibida **somam** numa linha só — sem código a mais. É o
mecanismo que a união de clientes vai usar quando a Maria decidir por ela.

## `MAX(f.RAZ_SOCIAL)` não decide o nome; é só a queda

O nome canônico vem de `dimensoes_dw` (grafia de maior peso, decisão A). O
`MAX()` existe para o caso de uma raiz que o cache ainda não conhece — cliente
que apareceu depois da última varredura — não sair sem rótulo. É a mesma
ordem de queda do `COALESCE(c.razao_social, f.raz_social)` do Postgres.
"""

from backend.volumetria_catering import contrato, dimensoes_dw, recorte, recorte_dw
from backend.volumetria_catering.matriz import (
    FORA_DO_SQL,
    MOVIMENTO,
    ROTULO_MOVIMENTO,
    montar,
)

# O nível da árvore -> a coluna do contrato que o identifica, e a coluna cuja
# grafia serve de queda para o rótulo (só o cliente tem uma).
NIVEL = {
    "unidade": {"chave": "nk_wms_filial", "queda_rotulo": None},
    "cliente": {"chave": "nk_cliente", "queda_rotulo": "raz_social"},
    "operacao": {"chave": "descr_oper_wms", "queda_rotulo": None},
}


def _sql(movimento, niveis, medidas, filtros, dim):
    """Monta a consulta de UM movimento. Identificador vem do contrato; valor
    vai por bind. O `FROM`/`WHERE` é o de `recorte_dw.de_para_where()` — o mesmo
    pedaço que a planilha e o download usam."""
    concretos = [n for n in niveis if n not in FORA_DO_SQL]
    grupos, selecoes = [], []
    for i, nome in enumerate(concretos):
        chave = recorte_dw.coluna(NIVEL[nome]["chave"], movimento)
        grupos.append(chave)
        selecoes.append(f"{chave} AS chave_{i}")
        queda = NIVEL[nome]["queda_rotulo"]
        if queda:
            selecoes.append(f"MAX({recorte_dw.coluna(queda, movimento)}) AS rotulo_{i}")
    mes = f"TO_CHAR({recorte_dw.coluna('nk_calendario', movimento)}, 'YYYY-MM')"
    grupos.append(mes)
    selecoes.append(f"{mes} AS mes")

    for apelido, coluna in medidas.items():
        selecoes.append(
            f"SUM({recorte_dw.coluna(coluna, movimento)}) AS medida_{apelido or 'unica'}"
        )
    selecoes.append("COUNT(*) AS linhas")

    de_para_where, params = recorte_dw.de_para_where(filtros, movimento, dim=dim)
    sql = "\n".join((
        f"SELECT {', '.join(selecoes)}",
        de_para_where,
        f"GROUP BY {', '.join(grupos)}",
    ))
    return sql, params


def _consultar_com(dim):
    """O `consultar()` que `matriz.montar()` recebe, fechado sobre o retrato
    das dimensões — é dele que saem sigla exibida e rótulo do cliente."""

    def consultar(cur, filtros, movimento, niveis, medidas):
        sql, params = _sql(movimento, niveis, medidas, filtros, dim)
        cur.execute(sql, params)
        # O Oracle devolve o nome das colunas em MAIÚSCULAS.
        colunas = [d[0].lower() for d in cur.description]
        concretos = [n for n in niveis if n not in FORA_DO_SQL]

        linhas = []
        total_linhas = 0
        for bruta in cur.fetchall():
            registro = dict(zip(colunas, bruta))
            total_linhas += int(registro["linhas"])
            chaves, rotulos = [], []
            for i, nome in enumerate(concretos):
                chave = registro[f"chave_{i}"]
                queda = registro.get(f"rotulo_{i}")
                if nome == "unidade":
                    # o de-para de sigla, ANTES de entrar na árvore: é o que
                    # faz siglas que colidem somarem numa linha só
                    chave = dimensoes_dw.sigla_exibida(chave)
                    rotulo = chave
                elif nome == "cliente":
                    rotulo = dim.rotulo_cliente(chave, queda)
                else:
                    rotulo = queda or chave
                chaves.append(chave)
                rotulos.append(rotulo)
            if MOVIMENTO in niveis:
                chaves.append(movimento)
                rotulos.append(ROTULO_MOVIMENTO[movimento])
            linhas.append({
                "chaves": chaves,
                "rotulos": rotulos,
                "mes": registro["mes"],
                "medidas": {
                    apelido: registro[f"medida_{apelido or 'unica'}"]
                    for apelido in medidas
                },
            })
        return linhas, total_linhas

    return consultar


def matriz(cur, filtros: recorte.Filtros, dim: dimensoes_dw.Dimensoes) -> dict:
    """A Matriz do recorte, lida do DW. Valor cru, na unidade da fonte."""
    return montar(cur, filtros, _consultar_com(dim))
