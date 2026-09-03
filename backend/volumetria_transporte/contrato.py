"""Contrato de colunas de `DM_VOLUMETRIA.FATO_VOL_TRN_CAT_V01`, medido pela
Maria no DBeaver em 03-04/set/2026 (T0 de
`docs/PLANO_VOLUMETRIA_TRANSPORTE_ESTOQUE.md`).

## De onde cada fato vem

- **nomes, ordem e amostra**: cabeçalho + 1 linha exportados do DBeaver
  (03/set) — dá nome, papel e um valor de exemplo por coluna;
- **tipo e nulabilidade real**: `ALL_TAB_COLUMNS` (04/set) — corrige a hipótese
  do T0 original: quase nada nesta tabela é `NOT NULL` de fato. Só a PK,
  `SK_CALENDARIO`, e a maioria dos campos de negócio (mas NÃO
  `NK_INSTANCIA`/`NK_WMS_FILIAL`/`NK_CLIENTE`, que são peças da chave natural e
  o Oracle permite nulas). `contrato.py` não impõe `NOT NULL` nenhum por conta
  disso — se um dia uma linha real chegar com uma dessas em branco, é o
  `recorte.py`/`planilha.py` que decide o que mostrar, não uma trava aqui.

## Quatro destinos por coluna (decisão da Maria, 03/set)

`tela` (Matriz/filtro/planilha), `arquivo` (só no download), `interno` (usado
pelo código, nunca mostrado) ou `fora` (nem entra no `SELECT`). As `SK_*`,
`DW_PROCESSO`, `NK_QLS_FILIAL` (repete `NK_WMS_FILIAL`) e `NK_WMS_CLIENTE`
(razão social truncada em 20) ficam `fora` — **isto diverge do catering**, cujo
download leva a linha inteira. Ver a seção "Resultado do T0" do plano para a
tabela completa com a justificativa coluna a coluna.

## Chave natural — P1 é hipótese, não medição

`ano_entrega` entra na chave por analogia com `ano_solic` do catering
(`num_gem` recicla por ano) — mas isto é a pendência **P1** do T0, não
confirmada com o Luciano. Se `num_gem` não reciclar por ano no transporte, a
chave fica maior do que precisa (inofensivo) — o risco seria o contrário
(reciclar sem `ano_entrega` na chave), que este contrato já evita.

## A sentinela da placa

`PLACA = '>>> SEM PLACA <<<'` no lugar de nulo (T0). Não é tratada aqui — quem
lê a coluna (planilha, download) decide como mostrar; o contrato só registra
que ela é `NOT NULL` (é, mesmo sem placa real).
"""

import os
import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ORIGEM = "T0 do plano transporte+estoque, medido 03-04/set/2026"

# "Hoje" para abrir a tela vem do RELÓGIO DO PROCESSO, convertido para este
# fuso — não de um `SELECT SYSDATE` no DW. Diferença deliberada do catering
# (que pergunta ao Postgres): aqui não há round trip supérfluo só para saber
# que dia é hoje, e o DW não é fonte de hora, é fonte de dado.
FUSO_EXIBICAO_PADRAO = "America/Sao_Paulo"
ENV_FUSO_EXIBICAO = "VOLUMETRIA_FUSO_EXIBICAO"


class FusoInvalido(ValueError):
    """Valor de `VOLUMETRIA_FUSO_EXIBICAO` que o sistema não conhece."""


def fuso_exibicao() -> str:
    nome = (os.environ.get(ENV_FUSO_EXIBICAO) or "").strip()
    if not nome:
        return FUSO_EXIBICAO_PADRAO
    try:
        ZoneInfo(nome)
    except (ZoneInfoNotFoundError, ValueError):
        raise FusoInvalido(
            f"{ENV_FUSO_EXIBICAO}={nome!r} não é um fuso conhecido "
            f"(esperado no formato de {FUSO_EXIBICAO_PADRAO!r})"
        ) from None
    return nome


ABERTURA_ANO_CORRENTE = "ano-corrente"
ENV_ABERTURA_DE = "VOLUMETRIA_TRN_ABERTURA_DE"
_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AberturaInvalida(ValueError):
    """Valor de `VOLUMETRIA_TRN_ABERTURA_DE` que não é nem o rolante nem uma data."""


def abertura_de(hoje: date) -> date:
    bruto = (os.environ.get(ENV_ABERTURA_DE) or "").strip()
    if not bruto or bruto == ABERTURA_ANO_CORRENTE:
        return date(hoje.year, 1, 1)
    if not _DATA_ISO.match(bruto):
        raise AberturaInvalida(
            f"{ENV_ABERTURA_DE}={bruto!r} não é {ABERTURA_ANO_CORRENTE!r} nem uma "
            "data AAAA-MM-DD"
        )
    try:
        return date.fromisoformat(bruto)
    except ValueError:
        raise AberturaInvalida(f"{ENV_ABERTURA_DE}={bruto!r} não é uma data que existe") from None

TABELA_PADRAO = "DM_VOLUMETRIA.FATO_VOL_TRN_CAT_V01"
ENV_TABELA = "DW_TABELA_TRN"
PK_DW = "PK_FATO_VOL_TRN_CAT"
PROCESSO_DW = "catering_to_dw_volumetry_v01"

_NOME_VALIDO = re.compile(r"^[A-Z][A-Z0-9_$#]*(\.[A-Z][A-Z0-9_$#]*)?$")


class TabelaInvalida(ValueError):
    """Nome de objeto que não pode entrar num SQL."""


def tabela() -> str:
    """O nome qualificado do objeto no DW, com a configuração tendo a
    palavra final — mesmo mecanismo do catering (`TABELA_REC`/`TABELA_EXP`)."""
    nome = (os.environ.get(ENV_TABELA) or TABELA_PADRAO).strip()
    if not _NOME_VALIDO.match(nome):
        raise TabelaInvalida(
            f"{ENV_TABELA}={nome!r} não é nome de objeto Oracle válido "
            "(esperado SCHEMA.TABELA em maiúsculas)"
        )
    return nome


# (nome, tipo, nulável, destino) — tipo e nulável de `ALL_TAB_COLUMNS`
# (04/set); destino da regra de exclusão (03/set). `nulável` não é imposto em
# lugar nenhum do código — é só documentação do que o Oracle declara.
COLUNAS = (
    ("pk_dw", "INTEGER", False, "arquivo"),
    ("dw_processo", "TEXT", True, "fora"),
    ("dw_data_inclusao", "TIMESTAMP", True, "fora"),
    ("dw_data_alteracao", "TIMESTAMP", True, "interno"),
    ("sk_calendario", "INTEGER", False, "fora"),
    ("sk_instancia", "INTEGER", True, "fora"),
    ("sk_empresa", "INTEGER", True, "fora"),
    ("sk_filial", "INTEGER", True, "fora"),
    ("sk_cliente", "INTEGER", True, "fora"),
    ("nk_calendario", "DATE", True, "tela"),
    ("nk_instancia", "TEXT", True, "interno"),
    ("nk_empresa", "TEXT", True, "interno"),
    ("nk_filial", "TEXT", True, "arquivo"),
    ("nk_wms_filial", "TEXT", True, "tela"),
    ("nk_qls_filial", "TEXT", True, "fora"),
    ("nk_slin_empresa", "TEXT", True, "arquivo"),
    ("nk_slin_filial", "TEXT", True, "arquivo"),
    ("nk_cliente", "TEXT", True, "tela"),  # interno (chave/filtro) + arquivo
    ("nk_wms_cliente", "TEXT", True, "fora"),
    ("data_programacao", "DATE", False, "tela"),
    ("ano_entrega", "INTEGER", False, "arquivo"),
    ("empresa_entrega", "TEXT", False, "arquivo"),
    ("filial_entrega", "TEXT", False, "arquivo"),
    ("cnpj_filial_entrega", "TEXT", False, "arquivo"),
    ("nome_und", "TEXT", False, "arquivo"),
    ("cnpj_cpf_cli", "TEXT", False, "arquivo"),
    ("raz_social", "TEXT", False, "tela"),
    ("nome_estoque", "TEXT", False, "tela"),
    ("tipo_viagem", "TEXT", False, "tela"),
    ("tipo_movimento", "TEXT", False, "tela"),
    ("status_viagem", "TEXT", False, "tela"),
    ("status_wms", "TEXT", False, "tela"),
    ("status_baixa", "TEXT", False, "tela"),
    ("num_gem", "TEXT", False, "tela"),
    ("num_pedido", "TEXT", False, "tela"),
    ("num_nf", "TEXT", False, "tela"),
    ("placa", "TEXT", False, "tela"),
    ("qtde_peso", "NUMERIC", True, "tela"),
    ("qtde_pbrt", "NUMERIC", True, "tela"),
    ("qtde_vlr", "NUMERIC", True, "tela"),
)

FORA = frozenset(nome for nome, _t, _n, destino in COLUNAS if destino == "fora")
# O que o SELECT leva: tudo que não é `fora`.
COLUNAS_SELECT = tuple((n, t, nu) for n, t, nu, d in COLUNAS if d != "fora")
# O que a planilha mostra na tela.
COLUNAS_TELA = tuple(n for n, _t, _nu, d in COLUNAS if d == "tela")
# O que o download leva a mais que a tela.
COLUNAS_ARQUIVO_EXTRA = tuple(n for n, _t, _nu, d in COLUNAS if d == "arquivo")
# O que o ARQUIVO mostra: tela + arquivo, na ordem do contrato. `interno`
# fica de fora do arquivo também — chave/frescor não são coisa que a pessoa
# baixando precisa ver.
COLUNAS_ARQUIVO = tuple(n for n, _t, _nu, d in COLUNAS if d in ("tela", "arquivo"))

CHAVE_NATURAL = (
    "nk_instancia",
    "nk_wms_filial",
    "num_gem",
    "ano_entrega",  # P1: hipótese, ver docstring
    "nome_estoque",
    "tipo_movimento",
    "nk_cliente",
)

IDENTIFICADORES_TEXTO = frozenset({
    "num_gem",
    "num_pedido",
    "num_nf",
    "nk_filial",
    "nk_cliente",
    "cnpj_cpf_cli",
    "nk_slin_empresa",
    "nk_slin_filial",
    "empresa_entrega",
    "filial_entrega",
    "cnpj_filial_entrega",
})

PLACA_SENTINELA = ">>> SEM PLACA <<<"
PLACA_ROTULO_VAZIA = "sem placa"

LENTES = {
    "liq": {"nome": "Peso líquido", "unidade": "t", "coluna": "qtde_peso"},
    "bru": {"nome": "Peso bruto", "unidade": "t", "coluna": "qtde_pbrt"},
    "val": {"nome": "Valor", "unidade": "R$", "coluna": "qtde_vlr"},
}

HIERARQUIA = ("unidade", "cliente", "tipo_movimento")


def coluna_dw(nossa: str) -> str:
    """Nome no DW: o nosso, em maiúsculas — sem de-para (`PK_DW` é exceção,
    tratada por fora porque `pk_dw` -> `PK_FATO_VOL_TRN_CAT` não é upper())."""
    if nossa == "pk_dw":
        return PK_DW
    return nossa.upper()


def colunas_dw() -> list[str]:
    """Nomes das colunas no DW, na ordem do `SELECT`. Coluna renomeada ou
    removida lá dá `ORA-00904` nomeando a coluna, no primeiro `execute`."""
    return [coluna_dw(nome) for nome, _t, _n in COLUNAS_SELECT]
