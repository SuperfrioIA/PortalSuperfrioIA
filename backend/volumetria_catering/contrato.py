"""Contrato de colunas das duas tabelas de fato — CÓPIA do `catering/contrato.py`
da nuvem-ia, na forma em que estava em 27/ago/2026 (depois da migration 0024).

## Por que existe uma cópia

A planilha e o download precisam saber quais colunas a linha tem (36 no
recebimento, 46 na expedição), e a Matriz precisa saber de qual coluna cada
lente sai. Esse conhecimento é o contrato — e o schema que ele descreve é
governado pelas migrations da nuvem-ia, não daqui.

Duas defesas obrigatórias, decididas em 27/ago/2026:

1. **mudança de schema é sempre duas PRs coordenadas** — migration lá, esta
   cópia aqui (regra a registrar nos dois CLAUDE.md no lote H4);
2. `schema.py` compara este contrato com as colunas reais do banco
   (`information_schema`) e **falha nomeando a coluna** quando divergirem.

## O que ficou de fora, de propósito

Tudo o que pertence à carga: nomes de objeto no DW Oracle (`tabela()`,
`TABELA_REC`, `PK_DW`, `coluna_dw()`), o piso da carga (`ano_minimo()`,
`piso_do_periodo()`) e o prefixo de instância. O Hub nunca conecta no DW.

## O que a medição da nuvem-ia decidiu, e este módulo herda

- **Identidade é a chave natural**, não a PK do DW (`pk_dw` é procedência). A
  chave inclui `ano_solic` porque `num_gem` se recicla por ano (migration 0023).
- **Identificador com zero à esquerda é TEXTO** (`num_gem` = `'0000000001'`,
  `nk_filial` = `'02060862000569'`). Ver `IDENTIFICADORES_TEXTO` — é o que
  decide quais colunas o xlsx escreve como texto.
- **Obrigatória é a coluna sem a qual a linha não pode ser identificada nem
  colocada na tela.** `sk_cliente` e `nk_wms_cliente` aceitam nulo desde a
  migration 0024 (uma linha de acerto de estoque sem cliente).
"""

import os
import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Versão do contrato copiado. Ao atualizar a cópia, atualize aqui também: é o que
# permite responder "esta cópia é de quando?" sem arqueologia no git.
ORIGEM = "nuvem-ia catering/contrato.py @ main 27/08/2026 (após migration 0024)"

MOVIMENTOS = ("rec", "exp")

# --------------------------------------------------------- fuso de exibição
# `cat_cargas.terminada_em` é `timestamptz` (UTC). O `to_char` renderiza no fuso
# da SESSÃO do Postgres, que no container é UTC — sem isto uma carga das 09h45
# aparece como 12h45. Configurável para haver UM lugar para mexer.
FUSO_EXIBICAO_PADRAO = "America/Sao_Paulo"
ENV_FUSO_EXIBICAO = "VOLUMETRIA_FUSO_EXIBICAO"


class FusoInvalido(ValueError):
    """Valor de `VOLUMETRIA_FUSO_EXIBICAO` que o sistema não conhece."""


def fuso_exibicao() -> str:
    """O fuso em que data e hora aparecem na tela, do ambiente ou do padrão.

    Valida na LEITURA: fuso escrito errado (`America/SaoPaulo`, `BRT`) falha
    nomeando a variável, em vez de o Postgres estourar no meio de uma consulta."""
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


# ---------------------------------------------------- abertura da tela
# O piso da CARGA (2023, na nuvem-ia) e a abertura da TELA são decisões
# diferentes. A tela abre em janeiro do ano corrente e vai até hoje; quem quiser
# 2023 filtra para trás. `ano-corrente` é rolante; pinar é escrever a data.
#
# `hoje` entra como argumento: o relógio do container é UTC, e quem chama pega o
# dia no fuso de exibição pelo Postgres.
ABERTURA_ANO_CORRENTE = "ano-corrente"
ABERTURA_PADRAO = ABERTURA_ANO_CORRENTE
ENV_ABERTURA_DE = "VOLUMETRIA_ABERTURA_DE"

_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AberturaInvalida(ValueError):
    """Valor de `VOLUMETRIA_ABERTURA_DE` que não é nem o rolante nem uma data."""


def abertura_de(hoje: date) -> date:
    """O primeiro dia do recorte com que a tela abre.

    `ano-corrente` (o padrão) -> 1º de janeiro do ano de `hoje`. Uma data
    `AAAA-MM-DD` -> ela mesma. Qualquer outra coisa falha nomeando a variável."""
    bruto = (os.environ.get(ENV_ABERTURA_DE) or "").strip()
    if not bruto or bruto == ABERTURA_ANO_CORRENTE:
        return date(hoje.year, 1, 1)
    if not _DATA_ISO.match(bruto):
        raise AberturaInvalida(
            f"{ENV_ABERTURA_DE}={bruto!r} não é {ABERTURA_ANO_CORRENTE!r} "
            "nem uma data AAAA-MM-DD"
        )
    try:
        return date.fromisoformat(bruto)
    except ValueError:
        raise AberturaInvalida(
            f"{ENV_ABERTURA_DE}={bruto!r} não é uma data que existe"
        ) from None


# ------------------------------------------------------------ identidade
# `ano_solic` fica depois do `num_gem` porque ele qualifica o número da guia: a
# chave se lê como "o GEM é único dentro do ano do pedido".
CHAVE_NATURAL = (
    "nk_instancia",
    "nk_wms_filial",
    "num_gem",
    "ano_solic",
    "nome_estoque",
    "descr_oper_wms",
    "nk_cliente",
)

# Identificador: texto sempre, porque tem zero à esquerda significativo.
IDENTIFICADORES_TEXTO = frozenset({
    "num_gem",
    "nk_filial",
    "nk_cliente",
    "cnpj_cpf_cli",
    "nk_slin_empresa",
    "nk_slin_filial",
})

# --------------------------------------------------------------- colunas
# (nome, tipo SQL, aceita nulo). Tipo medido no dado, não inferido do nome.
PROCEDENCIA = (
    ("pk_dw", "INTEGER", False),            # PK_FATO_VOL_*_CAT: procedência, não identidade
    ("dw_processo", "TEXT", False),
    ("dw_data_inclusao", "TIMESTAMP", False),
    ("dw_data_alteracao", "TIMESTAMP", False),
    ("sk_calendario", "INTEGER", False),
    ("sk_instancia", "INTEGER", False),
    ("sk_empresa", "INTEGER", False),
    ("sk_filial", "INTEGER", False),
    # Nulável desde o V3.8.1 (migration 0024): 1 linha em 232.089 na expedição.
    ("sk_cliente", "INTEGER", True),
)

DIMENSOES = (
    ("nk_calendario", "DATE", False),
    ("nk_instancia", "TEXT", False),
    ("nk_empresa", "TEXT", False),
    ("nk_filial", "TEXT", False),
    ("nk_wms_filial", "TEXT", False),
    ("nk_qls_filial", "TEXT", False),
    ("nk_slin_empresa", "TEXT", False),
    ("nk_slin_filial", "TEXT", False),
    ("nk_cliente", "TEXT", False),
    # Nulável desde o V3.8.1, pela MESMA linha que soltou o `sk_cliente`.
    ("nk_wms_cliente", "TEXT", True),
    ("data_solic", "DATE", False),
    ("ano_solic", "SMALLINT", False),
    # Guia de recebimento cancelada não tem confirmação.
    ("dthr_confirm", "TIMESTAMP", True),
    ("nome_und", "TEXT", False),
    ("num_gem", "TEXT", False),
    ("cnpj_cpf_cli", "TEXT", False),
    ("raz_social", "TEXT", False),
    ("descr_oper_wms", "TEXT", False),
    ("nome_estoque", "TEXT", False),
    ("status_processo", "TEXT", False),
    ("flg_interface", "TEXT", False),
)

# NUMERIC(18,3) em toda medida de peso e valor.
_PESO = "NUMERIC(18,3)"

MEDIDAS_REC = (
    ("qtde_sku", "INTEGER", True),
    ("qtde_pallet", "INTEGER", True),
    ("qtde_vol2", "INTEGER", True),
    ("qtde_peso2", _PESO, True),
    ("qtde_pbrt2", _PESO, True),
    ("qtde_vlr", _PESO, True),
)

MEDIDAS_EXP = (
    ("qtde_pedido", "INTEGER", True),
    ("qtde_sku_solicitado", "INTEGER", True),
    ("qtde_vol_solicitado", "INTEGER", True),
    ("qtde_peso_solicitado", _PESO, True),
    ("qtde_pbrt_solicitado", _PESO, True),
    ("qtde_vlr_solicitado", _PESO, True),
    ("qtde_sku_atendido", "INTEGER", True),
    ("qtde_vol_atendido", "INTEGER", True),
    ("qtde_peso_atendido", _PESO, True),
    ("qtde_pbrt_atendido", _PESO, True),
    ("qtde_vlr_atendido", _PESO, True),
    ("qtde_sku_separado", "INTEGER", True),
    ("qtde_vol_separado", "INTEGER", True),
    ("qtde_peso_separado", _PESO, True),
    ("qtde_pbrt_separado", _PESO, True),
    ("qtde_vlr_separado", _PESO, True),
)

COLUNAS_REC = PROCEDENCIA + DIMENSOES + MEDIDAS_REC
COLUNAS_EXP = PROCEDENCIA + DIMENSOES + MEDIDAS_EXP

# ------------------------------------------------------- leitura da tela
# As 5 lentes. `pallet` só existe na ENTRADA — nenhuma das três faixas da
# expedição tem medida de pallet. Não é defeito, é a fonte.
LENTES = {
    "liq": {"nome": "Peso líquido", "unidade": "t", "rec": "qtde_peso2", "exp": "peso"},
    "bru": {"nome": "Peso bruto", "unidade": "t", "rec": "qtde_pbrt2", "exp": "pbrt"},
    "pal": {"nome": "Pallets", "unidade": "UA", "rec": "qtde_pallet", "exp": None},
    "vol": {"nome": "Volumes", "unidade": "cx", "rec": "qtde_vol2", "exp": "vol"},
    "val": {"nome": "Valor", "unidade": "R$", "rec": "qtde_vlr", "exp": "vlr"},
}

# As 3 faixas da expedição. Cancelada tem peso no SOLICITADO e 0,0 nas outras.
FAIXAS = ("solicitado", "atendido", "separado")


def coluna_exp(lente: str, faixa: str):
    """Nome da coluna da expedição para uma lente numa faixa. None quando a
    medida não existe naquele lado (o caso do pallet)."""
    if lente not in LENTES:
        raise KeyError(lente)
    if faixa not in FAIXAS:
        raise KeyError(faixa)
    sufixo = LENTES[lente]["exp"]
    return None if sufixo is None else f"qtde_{sufixo}_{faixa}"


def colunas(movimento: str):
    """Colunas do fato de um movimento, na ordem do schema."""
    if movimento == "rec":
        return COLUNAS_REC
    if movimento == "exp":
        return COLUNAS_EXP
    raise KeyError(movimento)
