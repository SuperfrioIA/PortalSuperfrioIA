"""O que o download do recorte tem de comum, seja qual for a fonte: tetos, formato
Excel-first, nome do arquivo e as colunas que o arquivo leva.

Os geradores (CSV em streaming e xlsx sob teto) moram em `download_dw.py`, que
le o DW Oracle. Este modulo ficou so com a parte que nao e de banco nenhum.

## A linha inteira, com procedencia

O arquivo leva as colunas derivadas (dia, unidade exibida, cliente canonizado,
tipo de estoque) **e** todas as colunas do contrato, cruas. E o que permite
conferir "o DW diz `RMSPV`, a tela mostra `RMSPIV`" sem abrir o banco.

## Formato pensado para o Excel

Delimitador `;`, **UTF-8 com BOM**, decimal com virgula e data `DD/MM/AAAA`.

### O zero a esquerda, que o CSV nao consegue proteger

`num_gem` e `0000000609`; `nk_filial` e `02060862000569`. O Excel **come o zero
a esquerda** ao abrir CSV. A politica proibe exportacao que deforme
identificador, entao: o **CSV** leva o valor correto (a tela avisa), e o
**xlsx** escreve essas colunas como **texto** (`number_format='@'`). As colunas
protegidas saem de `contrato.IDENTIFICADORES_TEXTO`.

## Teto do xlsx

xlsx nao streama. O teto e **150.000 linhas**; acima disso, so CSV -- e a
mensagem diz isso, em vez de o servidor morrer sem explicacao.
"""

from datetime import date, datetime
from decimal import Decimal

from backend.volumetria_catering import contrato

TETO_XLSX = 150_000

# Acima disto a TELA pergunta antes de comecar o download. Nao e recusa: o CSV
# sai em streaming, sem teto. Constante propria, e nao um apelido de
# `TETO_XLSX`: hoje valem o mesmo numero por decisao, nao por dependencia.
TETO_CONFIRMACAO = 150_000
BLOCO = 2_000
BOM = "﻿"  # U+FEFF como escape: um BOM literal no fonte some do editor


class DownloadGrandeDemais(Exception):
    """Recorte acima do teto do formato pedido. Erro do chamador."""


# Colunas derivadas -- as nossas decisoes, para o arquivo ser legivel sem o banco.
# `(apelido, rotulo)`; quem as calcula e `download_dw._linha_do_arquivo`.
DERIVADAS = (
    ("dia", "Dia"),
    ("unidade", "Unidade"),
    ("cliente", "Cliente"),
    ("tipo_estoque", "Tipo de estoque"),
)


def colunas(movimento):
    """`[(apelido, rotulo)]` -- derivadas primeiro, depois o contrato cru."""
    do_contrato = [
        (nome, nome)
        for nome, _tipo, _nulo in contrato.colunas(movimento)
    ]
    return list(DERIVADAS) + do_contrato


def nome_do_arquivo(filtros, extensao):
    """Nome do arquivo baixado, com o periodo dentro dele.

    O sufixo `_dias` aparece quando o filtro de dia do mes esta ativo. Sem ele o
    nome prometeria meses inteiros num arquivo que pode ter apenas alguns dias de
    cada mes. Quais dias sairam nao entra no nome: quem precisa da resposta
    exata tem o recorte inteiro na auditoria."""
    movimento = "entrada" if filtros.movimento == "rec" else "saida"
    dias = "_dias" if filtros.dias else ""
    return f"catering_{movimento}_{filtros.de}_a_{filtros.ate}{dias}.{extensao}"


# ------------------------------------------------------------- formatacao
def _para_csv(valor):
    """Excel-first: decimal com virgula, data DD/MM/AAAA. Ver docstring."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "1" if valor else "0"
    if isinstance(valor, Decimal):
        return str(valor).replace(".", ",")
    if isinstance(valor, float):
        return repr(valor).replace(".", ",")
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    return str(valor)
