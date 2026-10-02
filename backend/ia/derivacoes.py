"""Derivações do Hub — a **única** aritmética que existe entre o DW e a resposta.

O modelo nunca soma, divide, ordena nem converte unidade (DD-9, DD-11). Tudo que
é conta ou ordem sobre o número que a Matriz devolveu mora aqui, em funções
**puras**: recebem a Matriz pronta (ou pedaços dela), usam `Decimal` e **não abrem
cursor nem conhecem o serviço da volumetria**. É o que torna cada uma testável
sozinha e é o que o teste AST de `test_ia_derivacoes.py` garante.

| Função | Decisão | O que faz |
|---|---|---|
| `exibir` | DD-18, DD-28 | kg -> t e as casas da exibição, guardando o valor original |
| `total_do_periodo` | DD-22 | soma dos meses de um recorte, com a marca de mês parcial |
| `ranking` | DD-20, DD-28 | ordena nós já lidos e devolve o top N pronto |
| `variacao_percentual` | DD-11 | (atual - base) / base x 100, com base zero e mês parcial |

## O que NÃO se afirma aqui

`exibir` usa as mesmas casas da tela (`frontend/volumetria-catering/app.js:95-101`:
peso em t com 1 casa; R$, UA e cx com 0), mas arredonda em `Decimal` com meio para
cima, e a tela arredonda no `float` do JavaScript. **Não se afirma que os dois
dão sempre o mesmo resultado** (DD-28): empates são testados e o alinhamento é
item do Lote 4.
"""
import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# Casas da exibição por unidade (a `unidade` de `contrato.LENTES`).
CASAS = {"t": 1, "R$": 0, "UA": 0, "cx": 0}

# O dado de peso chega em kg; a tela e a IA mostram em t.
_UNIDADE_ORIGINAL = {"t": "kg"}

_CEM = Decimal(100)


# ------------------------------------------------------------------ exibição
def _formatar_pt_br(valor: Decimal, casas: int) -> str:
    """`1234.5` -> `1.234,5`. Milhar com ponto, decimal com vírgula, sem passar
    por `float`."""
    americano = f"{valor:,.{casas}f}"
    return americano.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def exibir(valor: Decimal | None, unidade: str) -> dict:
    """Valor na unidade de exibição, **junto do original**.

    `unidade` é a de exibição da lente (`t`, `R$`, `UA`, `cx`). Para `t` o original
    é o valor em **kg**, dividido por mil sem arredondar (`scaleb`) e só então
    arredondado para a exibição.

    Devolve sempre as duas pontas, para a resposta poder mostrar uma e a
    auditoria conferir a outra:

    - `original` / `unidade_original`: o que o DW devolveu, como texto;
    - `exibido` / `unidade_exibida`: o texto pt-BR para o usuário (`1.234,6`);
    - `numero_exibido`: o mesmo valor arredondado, como texto sem separadores.
    """
    original_unidade = _UNIDADE_ORIGINAL.get(unidade, unidade)
    if valor is None:
        return {"original": None, "unidade_original": original_unidade,
                "exibido": None, "numero_exibido": None, "unidade_exibida": unidade}
    casas = CASAS[unidade]
    na_unidade = valor.scaleb(-3) if unidade == "t" else valor
    quantizado = na_unidade.quantize(Decimal(1).scaleb(-casas), rounding=ROUND_HALF_UP)
    if quantizado == 0:
        quantizado = abs(quantizado)  # nunca "-0,0"
    return {
        "original": str(valor),
        "unidade_original": original_unidade,
        "exibido": _formatar_pt_br(quantizado, casas),
        "numero_exibido": str(quantizado),
        "unidade_exibida": unidade,
    }


# ----------------------------------------------------------- meses e parcial
def _ultimo_dia(mes: str) -> date:
    ano, numero = (int(p) for p in mes.split("-"))
    return date(ano, numero, calendar.monthrange(ano, numero)[1])


def meses_parciais(meses: list[str], atualizado_ate: date | None, hoje: date) -> dict[str, int | None]:
    """Quais meses ainda não têm todos os dias, e até que dia há dado (DD-11).

    Um mês é parcial quando é o **mês corrente** ou quando o dado só vai até uma
    data **dentro dele** (`atualizado_ate` anterior ao último dia do mês).
    Devolve `{mes: dia}`; `dia` é até onde há dado (0 = nenhum dia do mês) ou
    `None` quando não dá para saber (sem `atualizado_ate` e mês que não é o
    corrente).
    """
    saida: dict[str, int | None] = {}
    for mes in meses:
        ultimo = _ultimo_dia(mes)
        corrente = (ultimo.year, ultimo.month) == (hoje.year, hoje.month)
        cortado = atualizado_ate is not None and atualizado_ate < ultimo
        if not (corrente or cortado):
            continue
        limite = ultimo
        if atualizado_ate is not None:
            limite = min(limite, atualizado_ate)
        if corrente:
            limite = min(limite, hoje)
        saida[mes] = limite.day if (limite.year, limite.month) == (ultimo.year, ultimo.month) else 0
    return saida


# --------------------------------------------------------- total do período
def total_do_periodo(valores: dict[str, Decimal | None], meses: list[str]) -> dict:
    """Soma, em `Decimal`, o valor de cada mês do período (DD-22).

    `valores` é o `{mes: valor}` de um nó (ou o `total` da Matriz). Mês ausente
    ou `None` não entra na soma e é contado em `meses_sem_dado`, para a resposta
    poder dizer que "março não teve registro" em vez de esconder. Sem nenhum mês
    com valor, o total é `None` (não zero: não houve dado).
    """
    somados = [valores[m] for m in meses if valores.get(m) is not None]
    return {
        "total": sum(somados, Decimal(0)) if somados else None,
        "meses_com_dado": len(somados),
        "meses_sem_dado": [m for m in meses if valores.get(m) is None],
    }


# ------------------------------------------------------------------ ranking
def _total_para_ordenar(no: dict, meses: list[str]) -> Decimal:
    total = total_do_periodo(no.get("valores", {}), meses)["total"]
    return total if total is not None else Decimal(0)


def ranking(nos: list[dict], *, meses: list[str], n: int, teto: int) -> dict:
    """Ordena `nos` pelo total do período e devolve o **top N pronto** (DD-20).

    `nos` são nós irmãos **já lidos por inteiro** (todas as páginas de unidades,
    antes de qualquer corte). Só ordena e corta: não muda nenhum valor. Critério:
    total do período decrescente; **empate desempata pelo rótulo, crescente**, para
    a ordem ser determinística. `n` acima de `teto` é erro, não corte silencioso.

    **Nunca devolve a `chave` do nó**: em cliente ela é a raiz do CNPJ (DD-17).
    """
    if not 1 <= n <= teto:
        raise ValueError(f"n deve estar entre 1 e {teto}, veio {n}")
    ordenados = sorted(
        nos,
        key=lambda no: (-_total_para_ordenar(no, meses), str(no.get("rotulo") or "").casefold()),
    )
    itens = []
    for posicao, no in enumerate(ordenados[:n], start=1):
        itens.append({
            "posicao": posicao,
            "rotulo": no.get("rotulo"),
            "valores": dict(no.get("valores", {})),
            "total": total_do_periodo(no.get("valores", {}), meses)["total"],
        })
    return {"itens": itens, "total_itens": len(nos), "truncado": len(nos) > n}


# -------------------------------------------------------- variação percentual
def variacao_percentual(
    valor_base: Decimal | None, valor_atual: Decimal | None
) -> dict:
    """`(atual - base) / base x 100` em `Decimal`, sem `float` (DD-11).

    Valor ausente (`None`: o nó não existe naquele mês) é tratado como zero, e a
    resposta diz isso. Base zero não tem percentual:

    - base 0 e atual > 0 -> `sem_base` ("o mês base teve zero");
    - base 0 e atual 0 -> `sem_movimento`.

    O valor exato fica em `percentual_exato`; `percentual` é o texto da exibição
    (1 casa, meio para cima, pt-BR).
    """
    ausente_base, ausente_atual = valor_base is None, valor_atual is None
    base = valor_base if valor_base is not None else Decimal(0)
    atual = valor_atual if valor_atual is not None else Decimal(0)
    comum = {"ausente_base": ausente_base, "ausente_atual": ausente_atual}

    if base == 0:
        if atual > 0:
            return {"situacao": "sem_base", "percentual": None, "percentual_exato": None,
                    "mensagem": "não há base para variação percentual: o mês base teve zero",
                    **comum}
        return {"situacao": "sem_movimento", "percentual": None, "percentual_exato": None,
                "mensagem": "sem movimento nos dois meses", **comum}

    exato = (atual - base) / base * _CEM
    arredondado = exato.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if arredondado == 0:
        arredondado = abs(arredondado)
    sentido = "alta" if exato > 0 else ("queda" if exato < 0 else "igual")
    return {"situacao": "ok", "sentido": sentido, "percentual_exato": str(exato),
            "percentual": _formatar_pt_br(arredondado, 1), **comum}


OPCOES_DE_BASE = ("mes_incompleto_vs_inteiro", "mesmos_dias", "so_meses_completos")

_DESCRICAO_DA_BASE = {
    "mes_incompleto_vs_inteiro": "o mês incompleto contra o outro mês inteiro",
    "mesmos_dias": "os mesmos dias nos dois meses",
    "so_meses_completos": "somente meses completos",
}


def escolha_de_base(
    mes_base: str, mes_atual: str, parciais: dict[str, int | None], base: str | None
) -> dict | None:
    """Trava da DD-11: com mês parcial e **sem base explícita**, não existe número.

    Devolve `None` quando pode calcular (nenhum mês parcial, ou base escolhida).
    Caso contrário devolve `requer_escolha`, com as opções e até que dia há dado.
    A IA não consegue pular o passo: sem `base`, a função que calcula nem é
    chamada.
    """
    if base is not None and base not in OPCOES_DE_BASE:
        raise ValueError(f"base inválida: {base!r} (use {', '.join(OPCOES_DE_BASE)})")
    envolvidos = {m: d for m, d in parciais.items() if m in (mes_base, mes_atual)}
    if not envolvidos or base is not None:
        return None
    return {
        "situacao": "requer_escolha",
        "meses_parciais": envolvidos,
        "opcoes": [{"base": b, "descricao": _DESCRICAO_DA_BASE[b]} for b in OPCOES_DE_BASE],
        "mensagem": ("há mês incompleto na comparação: pergunte ao usuário qual base usar "
                     "e repita a consulta com o parâmetro `base`"),
    }
