"""A camada de decisões, lendo o DW direto: sigla exibida, tipo de estoque e
razão social canonizada — em memória do processo, sem tabela e sem job.

Lote C2 do plano revisado (`docs/PLANO_VOLUMETRIA_DW_DIRETO.md`, 06/set/2026).

## O que este arquivo substitui

No desenho com Postgres intermediário, as três decisões viviam em tabelas
(`cat_unidades`, `cat_tipos_estoque`, `cat_clientes`), recalculadas pela carga
da nuvem-ia 2x/dia e juntadas ao fato por `LEFT JOIN` na leitura. Lendo o DW
direto não há carga, não há tabela nossa do lado de lá, e o `LEFT JOIN` some do
SQL. As decisões passam a acontecer **em Python, nas duas pontas**:

    filtro entrando:   a pessoa escolhe "RMSPIV" ou "CONGELADO"
                       -> traduz para o que o DW conhece: NK_WMS_FILIAL IN ('RMSPV'),
                          NOME_ESTOQUE IN ('CONG FLV (CUCINARE)', ...)
    resultado saindo:  o DW devolve NK_WMS_FILIAL, NK_CLIENTE, NOME_ESTOQUE crus
                       -> a tela recebe "RMSPIV", "CONVIDA", "CONGELADO"

## Decisão A da Maria (06/set/2026): o nome do cliente não muda para quem usa

A razão social continua sendo escolhida pela **grafia de maior peso somado no
histórico** — a mesma regra de `nuvem-ia catering/dominio/clientes.py`, portada
sem alteração. O que muda é ONDE ela é calculada: não numa tabela alimentada por
job (o D2 do plano original, descartado), mas na **mesma varredura que monta as
caixas de seleção do `/opcoes`**, cacheada por processo com TTL de 1 h. Sem
migration, sem APScheduler, e ninguém vê nome de cliente mudar na tela.

O custo honesto: o de-para vive na memória do processo. Reiniciar o Hub zera o
cache, e a primeira abertura de tela paga a varredura (medida em 06/set: da
ordem de segundos). Cliente novo no DW aparece com o nome cru até o TTL vencer
ou alguém apertar "atualizar agora" (`/dimensoes/atualizar`, só admin).

## As três regras, portadas — não reinventadas

- **sigla**: `RMSPV` -> `RMSPIV` (Maria, 21/ago/2026). A única exceção, e ela
  continua necessária: a query nº 6 do D0, cronometrada em 06/set, devolve
  `RMSPV` no dado de 2026;
- **tipo de estoque**: palavra-chave (`CONG`, `RESFRIADO`, `HORT`, ...) com
  `NAO_CLASSIFICADO` como sentinela visível e ambiguidade real virando
  sentinela, nunca chute (Maria, 24/ago/2026);
- **cliente**: raiz de CNPJ com a grafia de maior peso; empate por ordem
  alfabética, grafia vazia por último. Nenhuma raiz é unida a outra — a
  **união de clientes (CUCINARE + FLV) segue adiada** por decisão da Maria, e
  a tela continua batendo com o Power BI.

## O mapeamento sabe SOMAR, desde o primeiro dia

`siglas_fonte("RMSPIV")` devolve uma LISTA, e a Matriz acumula por chave
exibida — então duas siglas da fonte que caiam na mesma sigla exibida somam
numa linha só. Hoje o de-para é 1:1 e isso não faz diferença; mas a união de
clientes é exatamente N:1, e se o mecanismo nascer só renomeando ela custa uma
reescrita depois. Nasce somando; custa nada agora.

## Por que duas varreduras por tabela, e não seis

O `/opcoes` do Postgres fazia cinco `SELECT DISTINCT`/`MIN`/`MAX` sobre as duas
tabelas. No DW cada varredura completa custa segundos (o transporte mediu 9,4 s
para nove), então aqui são **duas agregações por tabela**: uma sobre
(unidade, nome de estoque, operação) e uma sobre (cliente, grafia) que traz junto
o peso, o período e o frescor. Quatro idas ao DW, uma vez por hora.
"""

import logging
import threading
import time
import unicodedata
from datetime import date, datetime, timezone

from backend.volumetria_catering import contrato

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ unidade
# sigla que o DW manda -> sigla que a tela mostra. Porte de
# `nuvem-ia catering/dominio/unidades.py` (decisão da Maria, 21/ago/2026).
SIGLA_EXIBIDA = {
    "RMSPV": "RMSPIV",
}


def sigla_exibida(sigla_fonte) -> str:
    """Sigla exibida. Identidade para toda unidade sem exceção registrada —
    unidade nova entra sozinha, com a sigla que o DW mandou."""
    s = (sigla_fonte or "").strip()
    return SIGLA_EXIBIDA.get(s, s)


def siglas_fonte(exibida) -> list[str]:
    """As siglas da FONTE que a tela mostra como `exibida` — o caminho de volta,
    para o filtro.

    Lista, não valor: é o que deixa o mapeamento ser N:1. Uma sigla que é
    renomeada (`RMSPV`) não representa a si mesma na tela, então pedir por ela
    devolve vazio — e vazio vira `1=0` no recorte, que é o que o Postgres fazia
    quando `COALESCE(u.sigla, ...) = 'RMSPV'` não casava com linha nenhuma."""
    e = (exibida or "").strip()
    fontes = {f for f, x in SIGLA_EXIBIDA.items() if x == e}
    if e not in SIGLA_EXIBIDA:
        fontes.add(e)
    return sorted(fontes)


# ---------------------------------------------------------- tipo de estoque
# Porte de `nuvem-ia catering/dominio/tipo_estoque.py`, regra de 24/ago/2026.
NAO_CLASSIFICADO = "NAO_CLASSIFICADO"

_PALAVRAS_CHAVE = {
    "CONGELADO": "CONGELADO",
    # `CONG FLV (CUCINARE)` é congelado. `CONG` não colide com nenhum outro
    # tipo (`CONSOLIDADOR` tem CONS, não CONG).
    "CONG": "CONGELADO",
    # classe de temperatura NOVA em 24/ago: `RESFRIADO - PR` cairia na
    # sentinela sem ela.
    "RESFRIADO": "RESFRIADO",
    "HORT": "HORTIFRUTI",
    "UTENSILIOS": "UTENSILIOS",
    "SECO": "SECO",
}

# De-para por nome EXATO (normalizado), para nome que não tem palavra-chave
# usável. `AGUA` como palavra-chave pegaria coisa demais.
_POR_NOME = {
    "AGUA / CARVAO": "SECO",
}

TIPOS_VALIDOS = frozenset({
    "CONGELADO", "SECO", "HORTIFRUTI", "UTENSILIOS", "RESFRIADO", NAO_CLASSIFICADO,
})


def _normalizar(valor) -> str:
    texto = str(valor if valor is not None else "").strip().upper()
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def classificar(valor) -> str:
    """Tipo de estoque: de-para por nome exato primeiro (é a decisão mais
    específica), depois palavra-chave. `NAO_CLASSIFICADO` quando o valor é
    vazio, quando nada casa, ou quando casa mais de um tipo — ambiguidade real
    do dado vira sentinela, nunca chute silencioso."""
    texto = _normalizar(valor)
    if not texto:
        return NAO_CLASSIFICADO
    if texto in _POR_NOME:
        return _POR_NOME[texto]
    casadas = {tipo for chave, tipo in _PALAVRAS_CHAVE.items() if chave in texto}
    if len(casadas) == 1:
        return casadas.pop()
    return NAO_CLASSIFICADO


# ------------------------------------------------------------------ cliente
def _lim(valor) -> str:
    return str(valor if valor is not None else "").strip()


def canonizar(observacoes):
    """Escolhe a razão social de cada raiz de CNPJ. Porte de
    `nuvem-ia catering/dominio/clientes.py`.

    `observacoes`: iterável de `(raiz, razao_social, peso)`. Pesos da mesma
    raiz e grafia se acumulam. Devolve `(escolhida, grafias)`:
      - `escolhida`: `{raiz: razao_social}` — o rótulo da tela;
      - `grafias`: `{raiz: [(razao_social, peso), ...]}` por peso decrescente
        e, no empate, alfabética — para a tela poder declarar quais grafias
        foram absorvidas em vez de escondê-las.

    Raiz vazia é ignorada. Grafia vazia não vence de uma preenchida."""
    peso_por_grafia = {}
    for raiz, razao, peso in observacoes:
        r = _lim(raiz)
        if not r:
            continue
        g = _lim(razao)
        chave = (r, g)
        peso_por_grafia[chave] = peso_por_grafia.get(chave, 0.0) + (peso or 0.0)

    grafias = {}
    for (raiz, razao), peso in peso_por_grafia.items():
        grafias.setdefault(raiz, []).append((razao, peso))

    escolhida = {}
    for raiz, lista in grafias.items():
        lista.sort(key=lambda x: (-x[1], x[0] == "", x[0]))
        escolhida[raiz] = lista[0][0]

    return escolhida, grafias


# ------------------------------------------------------- o retrato do dado
def como_date(valor):
    """O `DATE` do Oracle chega como `datetime` com hora zero; a tela e a
    comparação com o Postgres falam em `date`."""
    if isinstance(valor, datetime):
        return valor.date()
    return valor


class Dimensoes:
    """O que a tela precisa saber ANTES de a pessoa filtrar qualquer coisa, mais
    os de-paras que a leitura aplica depois. Construído por `varrer()` a partir
    do DW, ou direto pelos testes."""

    def __init__(self, *, unidades_fonte, nomes_estoque, operacoes, clientes_rotulo,
                 clientes_grafias, periodo, atualizado_em, calculado_em=None):
        self.unidades_fonte = sorted(set(unidades_fonte))
        self.nomes_estoque = sorted(set(nomes_estoque))
        # {"rec": [...], "exp": [...]} — a lista de operação é POR MOVIMENTO
        self.operacoes = {m: sorted(set(operacoes.get(m, ()))) for m in contrato.MOVIMENTOS}
        self.clientes_rotulo = dict(clientes_rotulo)
        self.clientes_grafias = dict(clientes_grafias)
        # (primeiro dia, último dia) com dado nas duas tabelas juntas
        self.periodo = tuple(como_date(d) for d in periodo)
        # {"rec": MAX(DW_DATA_ALTERACAO), "exp": ...} — o frescor da FONTE
        self.atualizado_em = dict(atualizado_em)
        self.calculado_em = calculado_em or datetime.now(timezone.utc)

    # unidade
    def unidades_exibidas(self) -> list[str]:
        return sorted({sigla_exibida(s) for s in self.unidades_fonte})

    # tipo de estoque
    def tipos(self) -> list[str]:
        return sorted({classificar(n) for n in self.nomes_estoque})

    def nomes_estoque_do_tipo(self, tipo) -> list[str]:
        """Os nomes de estoque que a regra classifica como `tipo` — é o que o
        filtro de tipo vira no `WHERE`. Vazio = tipo que nenhum nome conhecido
        produz, e o recorte trata como `1=0`."""
        return [n for n in self.nomes_estoque if classificar(n) == tipo]

    # cliente
    def rotulo_cliente(self, raiz, queda=None) -> str:
        """A razão social canonizada, com queda para a grafia da própria linha
        e, por fim, para a raiz — a mesma ordem do
        `COALESCE(c.razao_social, f.raz_social)` do Postgres."""
        return self.clientes_rotulo.get(_lim(raiz)) or _lim(queda) or _lim(raiz)

    def clientes(self) -> list[dict]:
        """`[{chave, rotulo}]` ordenado pelo rótulo, como o `/opcoes` sempre
        devolveu."""
        return sorted(
            ({"chave": r, "rotulo": self.rotulo_cliente(r)} for r in self.clientes_rotulo),
            key=lambda c: (c["rotulo"], c["chave"]),
        )

    def divergentes(self) -> dict:
        """Raízes com mais de uma grafia — o que a tela declara em "Fontes &
        método", e o que o diagnóstico mostra."""
        return {r: g for r, g in self.clientes_grafias.items() if len(g) > 1}

    def como_dict(self) -> dict:
        return {
            "unidades": self.unidades_exibidas(),
            "nomes_estoque": len(self.nomes_estoque),
            "tipos": self.tipos(),
            "clientes": len(self.clientes_rotulo),
            "clientes_com_mais_de_uma_grafia": sorted(self.divergentes()),
            "periodo": [d.isoformat() if d else None for d in self.periodo],
            "atualizado_em": {
                m: (v.isoformat() if v else None) for m, v in self.atualizado_em.items()
            },
            "calculado_em": self.calculado_em.isoformat(),
        }


# A medida que decide a grafia do cliente: peso líquido — `qtde_peso2` no
# recebimento e `qtde_peso_solicitado` na expedição (a faixa padrão da tela).
# Critério de desempate, não número publicado: mudar aqui não muda nenhum
# valor exibido.
_PESO_DO_CLIENTE = {"rec": "qtde_peso2", "exp": "qtde_peso_solicitado"}


def sql_listas(movimento: str) -> str:
    """Uma agregação por (unidade, nome de estoque, operação): as três listas
    de filtro de uma vez, numa varredura só."""
    c = lambda nome: contrato.coluna_dw(nome, movimento)  # noqa: E731
    grupos = f"{c('nk_wms_filial')}, {c('nome_estoque')}, {c('descr_oper_wms')}"
    return f"SELECT {grupos} FROM {contrato.tabela(movimento)} GROUP BY {grupos}"


def sql_clientes(movimento: str) -> str:
    """Uma agregação por (cliente, grafia) com o peso — a query nº 2 do D0 —
    trazendo junto, de graça, o período e o frescor da tabela."""
    c = lambda nome: contrato.coluna_dw(nome, movimento)  # noqa: E731
    grupos = f"{c('nk_cliente')}, {c('raz_social')}"
    return (
        f"SELECT {grupos}, SUM(COALESCE({c(_PESO_DO_CLIENTE[movimento])}, 0)), "
        f"MIN({c('nk_calendario')}), MAX({c('nk_calendario')}), "
        f"MAX({c('dw_data_alteracao')}) "
        f"FROM {contrato.tabela(movimento)} GROUP BY {grupos}"
    )


def varrer(cur) -> Dimensoes:
    """Lê as duas tabelas e monta o retrato. Quatro idas ao DW, sem filtro —
    é a parte cara, e é por isso que o resultado é cacheado (`obter`)."""
    unidades, nomes, operacoes = set(), set(), {m: set() for m in contrato.MOVIMENTOS}
    observacoes = []
    primeiro, ultimo = None, None
    atualizado_em = {}

    for movimento in contrato.MOVIMENTOS:
        cur.execute(sql_listas(movimento))
        for sigla, nome, operacao in cur.fetchall():
            if sigla is not None:
                unidades.add(str(sigla))
            if nome is not None:
                nomes.add(str(nome))
            if operacao is not None:
                operacoes[movimento].add(str(operacao))

        cur.execute(sql_clientes(movimento))
        alterado = None
        for raiz, razao, peso, dmin, dmax, alt in cur.fetchall():
            # float de propósito, como na nuvem-ia: aqui o peso é critério de
            # desempate entre grafias, não número publicado.
            observacoes.append((raiz, razao, float(peso or 0)))
            dmin, dmax = como_date(dmin), como_date(dmax)
            if dmin is not None and (primeiro is None or dmin < primeiro):
                primeiro = dmin
            if dmax is not None and (ultimo is None or dmax > ultimo):
                ultimo = dmax
            if alt is not None and (alterado is None or alt > alterado):
                alterado = alt
        atualizado_em[movimento] = alterado

    escolhida, grafias = canonizar(observacoes)
    dim = Dimensoes(
        unidades_fonte=unidades, nomes_estoque=nomes, operacoes=operacoes,
        clientes_rotulo=escolhida, clientes_grafias=grafias,
        periodo=(primeiro, ultimo), atualizado_em=atualizado_em,
    )
    nao_classificados = dim.nomes_estoque_do_tipo(NAO_CLASSIFICADO)
    if nao_classificados:
        # Sentinela visível na tela e no log — é o alarme de nome de estoque
        # novo, e substitui a tabela de pendência que a V2 tinha.
        logger.warning(
            "volumetria/DW: %d nome(s) de estoque em %s: %s",
            len(nao_classificados), NAO_CLASSIFICADO, nao_classificados,
        )
    if dim.divergentes():
        logger.info(
            "volumetria/DW: %d cliente(s) com mais de uma grafia, canonizados: %s",
            len(dim.divergentes()), sorted(dim.divergentes()),
        )
    return dim


# ------------------------------------------------------------------- cache
# Uma hora, como no transporte (combinado com a Maria em 03/set): cliente ou
# unidade nova é raro; só o "atualizado até" muda todo dia, e uma hora de
# atraso nele é aceitável. Quem não quer esperar tem o "atualizar agora".
TTL_SEGUNDOS = 60 * 60

_lock = threading.Lock()
_cache: dict = {"expira_em": 0.0, "dados": None}


def obter(cur) -> Dimensoes:
    """O retrato em cache, ou uma varredura nova se ele venceu. O lock cobre só
    a leitura e a escrita do cache, não a varredura: dois requests frios ao
    mesmo tempo varrem duas vezes, e isso é mais barato que fazer o segundo
    esperar segurando o lock."""
    agora = time.monotonic()
    with _lock:
        if _cache["dados"] is not None and agora < _cache["expira_em"]:
            return _cache["dados"]
    dados = varrer(cur)
    with _lock:
        _cache["dados"] = dados
        _cache["expira_em"] = agora + TTL_SEGUNDOS
    return dados


def atualizar(cur) -> Dimensoes:
    """Varre agora e substitui o cache — o "atualizar agora" do admin."""
    invalidar()
    return obter(cur)


def invalidar() -> None:
    with _lock:
        _cache["dados"] = None
        _cache["expira_em"] = 0.0


def em_cache() -> Dimensoes | None:
    """O que está no cache, sem tocar no DW. Para o diagnóstico."""
    with _lock:
        return _cache["dados"]


def hoje_no_fuso() -> date:
    """"Hoje" pelo relógio do processo, no fuso de exibição — não por um
    `SELECT SYSDATE` no DW. O DW é fonte de dado, não de hora, e a mesma
    decisão já vale no transporte e no estoque."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(contrato.fuso_exibicao())).date()
