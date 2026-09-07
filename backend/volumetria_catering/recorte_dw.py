"""O recorte no dialeto do Oracle — a mesma definição de filtro, outro `WHERE`.

Lote C2 do plano revisado (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`).

## O que é reaproveitado e o que é traduzido

Tudo o que em `recorte.py` é **definição** — `Filtros` e sua validação, a
semântica de período e de dia do mês, os rótulos de mês parcial, as medidas por
lente e faixa, a visão conjunta — é importado daqui **sem cópia**: a tela do
Postgres e a do DW têm que aceitar e recusar exatamente os mesmos filtros, e um
segundo `Filtros` divergiria em silêncio.

O que é traduzido é só a montagem do `WHERE`:

| Postgres (`recorte.py`) | Oracle (aqui) |
|---|---|
| `%(x)s` | `:x` |
| `coluna = ANY(%(lista)s)` | `coluna IN (:p0, :p1, ...)` — um bind por item |
| `EXTRACT(DAY FROM f.nk_calendario)` | igual — é SQL padrão e o Oracle aceita |
| `LEFT JOIN cat_unidades` + `COALESCE(u.sigla, ...)` | **some**: a sigla exibida vira sigla da fonte em Python, antes do `WHERE` |
| `LEFT JOIN cat_tipos_estoque` + `COALESCE(t.tipo, ...)` | **some**: o tipo vira a lista de nomes de estoque que a regra classifica nele |

A tradução dos dois filtros de decisão (unidade e tipo) é o coração do lote —
ver `dimensoes_dw.py`. Um tipo que nenhum nome conhecido produz, ou uma sigla
que a tela não exibe, vira `1=0`: **zero linha, nunca "sem filtro"**. Cair em
"sem filtro" devolveria a tabela inteira com o painel dizendo que filtrou — a
tela mentindo, que é o pior desfecho.

## Limitação conhecida e não tratada

O Oracle recusa mais de 1000 itens num `IN`. Nenhuma dimensão chega perto (a
maior lista de filtro é a de cliente, com 14; a de nome de estoque, 40). Se um
dia chegar, isto passa a exigir quebrar em blocos de `OR`.
"""

from backend.volumetria_catering import contrato, dimensoes_dw
from backend.volumetria_catering.recorte import (  # noqa: F401 — reexportados de propósito
    CONJUNTA,
    MOVIMENTOS_DA_TELA,
    ROTULO_FAIXA,
    FiltroInvalido,
    Filtros,
    aviso_dos_dias,
    data_do_recorte,
    dias_do_filtro,
    medida,
    medidas_da_lente,
    meses_do_periodo,
    movimentos_do_recorte,
    rotulo_dos_dias,
    rotulo_faixa,
    rotulos_dos_meses,
)

# A cláusula que não casa com linha nenhuma. Existe para um filtro que não
# traduz para nada (ver docstring) responder zero, e não tudo.
NADA = "1=0"


def coluna(nome: str, movimento: str) -> str:
    """`f.COLUNA_NO_DW` — sempre por `contrato.coluna_dw()`, nunca
    `f"f.{nome}"` cru: foi o `f.pk_dw` cru que levou `ORA-00904` em produção
    no transporte (04/set)."""
    return f"f.{contrato.coluna_dw(nome, movimento)}"


def _lista(expressao: str, valores, params: dict, prefixo: str) -> str:
    """`expressao IN (:p0, :p1, ...)`, um bind numerado por valor — o oracledb
    não aceita lista Python como bind direto de `IN`."""
    nomes = []
    for i, valor in enumerate(valores):
        chave = f"{prefixo}{i}"
        params[chave] = valor
        nomes.append(f":{chave}")
    return f"{expressao} IN ({', '.join(nomes)})"


def _traduzir_unidades(exibidas) -> list[str]:
    """Da sigla que a tela mostra para a(s) que o DW conhece."""
    fontes: set[str] = set()
    for exibida in exibidas:
        fontes.update(dimensoes_dw.siglas_fonte(exibida))
    return sorted(fontes)


def _traduzir_tipos(tipos, dim: dimensoes_dw.Dimensoes) -> list[str]:
    """Do tipo classificado para os nomes de estoque que a regra põe nele."""
    nomes: set[str] = set()
    for tipo in tipos:
        nomes.update(dim.nomes_estoque_do_tipo(tipo))
    return sorted(nomes)


def onde(filtros: Filtros, movimento: str, dim: dimensoes_dw.Dimensoes):
    """`(clausulas, params)` do recorte. **A única definição de filtro** do lado
    Oracle — Matriz, planilha e download passam por aqui."""
    cal = coluna("nk_calendario", movimento)
    clausulas = [f"{cal} >= :de", f"{cal} <= :ate"]
    params = {
        "de": data_do_recorte(filtros.de, "de"),
        "ate": data_do_recorte(filtros.ate, "ate"),
    }
    if filtros.dias:
        clausulas.append(_lista(f"EXTRACT(DAY FROM {cal})", list(filtros.dias), params, "dia"))
    if filtros.unidades:
        fontes = _traduzir_unidades(filtros.unidades)
        clausulas.append(
            _lista(coluna("nk_wms_filial", movimento), fontes, params, "uni") if fontes else NADA
        )
    if filtros.clientes:
        clausulas.append(
            _lista(coluna("nk_cliente", movimento), list(filtros.clientes), params, "cli")
        )
    if filtros.tipos_estoque:
        nomes = _traduzir_tipos(filtros.tipos_estoque, dim)
        clausulas.append(
            _lista(coluna("nome_estoque", movimento), nomes, params, "tip") if nomes else NADA
        )
    if filtros.operacoes:
        clausulas.append(
            _lista(coluna("descr_oper_wms", movimento), list(filtros.operacoes), params, "ope")
        )
    return clausulas, params


def de_para_where(filtros: Filtros, movimento=None, *, dim: dimensoes_dw.Dimensoes):
    """`(sql_from_where, params)` — o pedaço comum das três consultas.

    A mesma trava do `recorte.py`: `movimento=amb` sem movimento explícito
    **levanta** em vez de escolher uma tabela em silêncio."""
    escolhido = movimento or filtros.movimento
    if escolhido == CONJUNTA:
        raise FiltroInvalido(
            "recorte de dois movimentos: esta consulta le uma tabela por vez"
        )
    clausulas, params = onde(filtros, escolhido, dim)
    sql = f"FROM {contrato.tabela(escolhido)} f\nWHERE {' AND '.join(clausulas)}"
    return sql, params
