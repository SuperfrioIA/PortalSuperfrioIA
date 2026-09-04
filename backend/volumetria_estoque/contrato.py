"""Contrato de colunas de `DM_VOLUMETRIA.FATO_VOL_EST_CAT_V01`, medido pela
Maria no DBeaver em 03-04/set/2026 (T0 de
`docs/PLANO_VOLUMETRIA_TRANSPORTE_ESTOQUE.md`).

## O que este contrato herda do transporte, e o que muda

Mesmas quatro fontes de informação (cabeçalho+amostra, `ALL_TAB_COLUMNS`) e o
mesmo desenho de quatro destinos por coluna — ver
`backend/volumetria_transporte/contrato.py` para o raciocínio completo.

O que é diferente aqui:

- **quase toda coluna é `NULLABLE`** no Oracle — só a PK é `NOT NULL`. Igual
  ao transporte, isto não vira trava no código;
- **`DW_DATA_ALTERACAO` chega nulo de verdade** (visto na amostra do T0, não
  só permitido pelo schema) — o frescor deste módulo é
  `MAX(COALESCE(DW_DATA_ALTERACAO, DW_DATA_INCLUSAO))`, por isso
  `dw_data_inclusao` também é `interno` aqui (no transporte era `fora`);
  `dw_data_alteracao` continua `interno`;
- **`CAMARA` aceita nulo de verdade** — é dimensão e nível da hierarquia, e
  precisa de um rótulo para "sem câmara" tratado à parte (ver `recorte.py`);
- **`QTDE_SKU` não é lente** — é contagem (uma linha já é o total de SKUs
  daquele dia), então soma-la entre câmaras ou entre dias do mês conta
  errado. Fica só na planilha/arquivo, nunca nos botões de medida;
- **sem sufixo `2`** nos nomes de medida (`QTDE_VOL`, não `QTDE_VOL2`) —
  diferente do recebimento do catering, que tem o sufixo.
"""

import os
import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ORIGEM = "T0 do plano transporte+estoque, medido 03-04/set/2026"

TABELA_PADRAO = "DM_VOLUMETRIA.FATO_VOL_EST_CAT_V01"
ENV_TABELA = "DW_TABELA_EST"
PK_DW = "PK_FATO_VOL_EST_CAT"
PROCESSO_DW = "catering_to_dw_volumetry_v01"

_NOME_VALIDO = re.compile(r"^[A-Z][A-Z0-9_$#]*(\.[A-Z][A-Z0-9_$#]*)?$")


class TabelaInvalida(ValueError):
    """Nome de objeto que não pode entrar num SQL."""


def tabela() -> str:
    nome = (os.environ.get(ENV_TABELA) or TABELA_PADRAO).strip()
    if not _NOME_VALIDO.match(nome):
        raise TabelaInvalida(
            f"{ENV_TABELA}={nome!r} não é nome de objeto Oracle válido "
            "(esperado SCHEMA.TABELA em maiúsculas)"
        )
    return nome


# (nome, tipo, nulável, destino) — mesma leitura de
# `volumetria_transporte/contrato.py`.
COLUNAS = (
    ("pk_dw", "INTEGER", False, "arquivo"),
    ("dw_processo", "TEXT", True, "fora"),
    ("dw_data_inclusao", "TIMESTAMP", True, "interno"),  # fallback do frescor
    ("dw_data_alteracao", "TIMESTAMP", True, "interno"),  # chega nulo (visto no T0)
    ("sk_calendario", "INTEGER", True, "fora"),
    ("sk_instancia", "INTEGER", True, "fora"),
    ("sk_empresa", "INTEGER", True, "fora"),
    ("sk_filial", "INTEGER", True, "fora"),
    ("sk_cliente", "INTEGER", True, "fora"),
    ("nk_calendario", "DATE", True, "tela"),  # o dia da FOTO
    ("nk_instancia", "TEXT", True, "interno"),
    ("nk_empresa", "TEXT", True, "interno"),
    ("nk_filial", "TEXT", True, "arquivo"),
    ("nk_wms_filial", "TEXT", True, "tela"),
    ("nk_qls_filial", "TEXT", True, "fora"),
    ("nk_slin_empresa", "TEXT", True, "arquivo"),
    ("nk_slin_filial", "TEXT", True, "arquivo"),
    ("nk_cliente", "TEXT", True, "tela"),  # interno (chave/filtro) + arquivo
    ("nk_wms_cliente", "TEXT", True, "fora"),
    ("nome_und", "TEXT", True, "arquivo"),
    ("cnpj_cpf_cli", "TEXT", True, "arquivo"),
    ("raz_social", "TEXT", True, "tela"),
    ("camara", "TEXT", True, "tela"),  # aceita nulo de verdade
    ("status_lote", "TEXT", True, "tela"),
    ("qtde_sku", "INTEGER", True, "tela"),  # contagem — fora das lentes
    ("qtde_pallet", "INTEGER", True, "tela"),
    ("qtde_vol", "INTEGER", True, "tela"),
    ("qtde_peso", "NUMERIC", True, "tela"),
    ("qtde_pbrt", "NUMERIC", True, "tela"),
    ("qtde_vlr", "NUMERIC", True, "tela"),
)

FORA = frozenset(nome for nome, _t, _n, destino in COLUNAS if destino == "fora")
COLUNAS_SELECT = tuple((n, t, nu) for n, t, nu, d in COLUNAS if d != "fora")
COLUNAS_TELA = tuple(n for n, _t, _nu, d in COLUNAS if d == "tela")
COLUNAS_ARQUIVO = tuple(n for n, _t, _nu, d in COLUNAS if d in ("tela", "arquivo"))

# Grão medido no T0: uma linha por (dia, instância, filial, cliente, câmara,
# status do lote) — não há documento (guia/lote/nota) na tabela.
CHAVE_NATURAL = (
    "nk_instancia",
    "nk_wms_filial",
    "nk_cliente",
    "camara",
    "status_lote",
)

IDENTIFICADORES_TEXTO = frozenset({
    "nk_filial",
    "nk_cliente",
    "cnpj_cpf_cli",
    "nk_slin_empresa",
    "nk_slin_filial",
})

CAMARA_SENTINELA_SQL = "SEM_CAMARA"  # só para agrupar/juntar no SQL — nunca exibido
CAMARA_ROTULO_VAZIA = "sem câmara"

# 5 lentes — QTDE_SKU fica de fora (é contagem, ver docstring).
# "unidade" é só rótulo (o `fmt()` do frontend não converte nada, ao
# contrário do catering) — o DW manda peso em kg, então o rótulo é "kg".
# Corrigido em 04/set/2026: dizia "t" sem nenhuma conversão por trás, e o
# número na tela era o kg cru mostrado como se já fosse tonelada.
LENTES = {
    "liq": {"nome": "Peso líquido", "unidade": "kg", "coluna": "qtde_peso"},
    "bru": {"nome": "Peso bruto", "unidade": "kg", "coluna": "qtde_pbrt"},
    "pal": {"nome": "Pallets", "unidade": "UA", "coluna": "qtde_pallet"},
    "vol": {"nome": "Volumes", "unidade": "cx", "coluna": "qtde_vol"},
    "val": {"nome": "Valor", "unidade": "R$", "coluna": "qtde_vlr"},
}

HIERARQUIA = ("unidade", "cliente", "camara")

# Modo de agregação da Matriz — declarado aqui porque é propriedade do DADO
# (posição × fluxo), não da tela. Ver `matriz.py`.
MODO_AGREGACAO = "posicao"


def coluna_dw(nossa: str) -> str:
    if nossa == "pk_dw":
        return PK_DW
    return nossa.upper()


def colunas_dw() -> list[str]:
    return [coluna_dw(nome) for nome, _t, _n in COLUNAS_SELECT]


# --------------------------------------------------------- abertura da tela
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


# A carga do estoque só tem dado desde 25/08/2026 (confirmado pela Maria em
# 04/set) — bem mais curto que o transporte. A abertura da tela ainda é
# "ano corrente" por padrão (a mesma regra dos outros módulos); quem quiser
# pode configurar uma abertura mais estreita.
ABERTURA_ANO_CORRENTE = "ano-corrente"
ENV_ABERTURA_DE = "VOLUMETRIA_EST_ABERTURA_DE"
_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AberturaInvalida(ValueError):
    """Valor de `VOLUMETRIA_EST_ABERTURA_DE` que não é nem o rolante nem uma data."""


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
