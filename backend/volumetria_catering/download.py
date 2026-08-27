"""Download do recorte: CSV em streaming e xlsx sob teto.

Porte de `catering/consulta/download.py` da nuvem-ia (main, 27/ago/2026). Duas
mudancas alem dos imports: psycopg2 -> psycopg (v3, o driver do Hub), e a
conexao vem de `conexao.py` (somente leitura, `VOLUMETRIA_DB_URL`). A auditoria
grava na tabela do Hub (`auditoria.py` daqui), nao na `cat_auditoria`.

## Streaming de verdade, nos DOIS lados

`StreamingResponse` no FastAPI resolve metade do problema. A outra metade e o
banco: com um cursor comum o driver traz **todas** as linhas para a memoria do
processo antes de a primeira sair. Por isso a leitura usa **cursor nomeado**
(server-side), com `itersize` -- o Postgres entrega em blocos e o processo nunca
segura o resultado inteiro.

Consequencia de desenho: o gerador **e dono da conexao**. Ele nao pode receber
uma conexao de fora, porque o corpo do gerador roda depois de a resposta HTTP
comecar, quando qualquer `with` do chamador ja fechou.

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

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal

from backend.volumetria_catering import auditoria, conexao, contrato, recorte

logger = logging.getLogger(__name__)

TETO_XLSX = 150_000

# Acima disto a TELA pergunta antes de comecar o download. Nao e recusa: o CSV
# sai em streaming, sem teto. Constante propria, e nao um apelido de
# `TETO_XLSX`: hoje valem o mesmo numero por decisao, nao por dependencia.
TETO_CONFIRMACAO = 150_000
BLOCO = 2_000
BOM = "﻿"  # U+FEFF como escape: um BOM literal no fonte some do editor


class DownloadGrandeDemais(Exception):
    """Recorte acima do teto do formato pedido. Erro do chamador."""


# Colunas derivadas -- as nossas decisoes, para o arquivo ser legivel sem o banco
DERIVADAS = (
    ("dia", "f.nk_calendario", "Dia"),
    ("unidade", recorte.SIGLA, "Unidade"),
    ("cliente", recorte.CLIENTE_ROTULO, "Cliente"),
    ("tipo_estoque", recorte.TIPO_ESTOQUE, "Tipo de estoque"),
)


def colunas(movimento):
    """`[(apelido, sql, rotulo)]` -- derivadas primeiro, depois o contrato cru."""
    do_contrato = [
        (nome, f"f.{nome}", nome)
        for nome, _tipo, _nulo in contrato.colunas(movimento)
    ]
    return list(DERIVADAS) + do_contrato


def _sql(filtros):
    de_para_where, params = recorte.de_para_where(filtros)
    selecoes = [f"{sql} AS {apelido}" for apelido, sql, _r in colunas(filtros.movimento)]
    ordem = "f.nk_calendario, " + ", ".join(
        f"f.{coluna}" for coluna in contrato.CHAVE_NATURAL
    )
    return "\n".join((
        f"SELECT {', '.join(selecoes)}",
        de_para_where,
        f"ORDER BY {ordem}",
    )), params


def contar(cur, filtros) -> int:
    de_para_where, params = recorte.de_para_where(filtros)
    cur.execute(f"SELECT count(*) {de_para_where}", params)
    return cur.fetchone()[0]


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


def gerar_csv(filtros, registro=None):
    """Gera o CSV linha a linha. **Dono da propria conexao** -- ver docstring.

    `registro` e o id da auditoria: fechado com a contagem real de linhas, ou
    marcado como falha se o stream morrer no meio."""
    tampao = io.StringIO()
    escritor = csv.writer(tampao, delimiter=";", lineterminator="\r\n")

    def despejar():
        conteudo = tampao.getvalue()
        tampao.seek(0)
        tampao.truncate(0)
        return conteudo

    nomes = colunas(filtros.movimento)
    sql, params = _sql(filtros)
    enviadas = 0
    conn = None
    try:
        conn = conexao.conectar()
        # cursor NOMEADO: o Postgres entrega em blocos e o processo nunca segura
        # o resultado inteiro
        with conn.cursor(name="cat_download") as cur:
            cur.itersize = BLOCO
            cur.execute(sql, params)
            escritor.writerow([rotulo for _a, _s, rotulo in nomes])
            yield BOM + despejar()
            for linha in cur:
                escritor.writerow([_para_csv(v) for v in linha])
                enviadas += 1
                if enviadas % BLOCO == 0:
                    yield despejar()
            resto = despejar()
            if resto:
                yield resto
        if registro is not None:
            auditoria.fechar(registro, enviadas)
        logger.info("download csv concluido: %d linha(s)", enviadas)
    except GeneratorExit:
        # O cliente fechou a aba no meio: o Starlette descarta o gerador e isto
        # NAO e `Exception`. Sem este ramo a linha ficaria `rodando` para sempre
        # -- e "interrompido" e justamente o que a trilha precisa dizer.
        if registro is not None:
            auditoria.falhar(registro, f"interrompido pelo cliente apos {enviadas} linha(s)")
        raise
    except Exception as erro:
        if registro is not None:
            auditoria.falhar(registro, erro)
        raise
    finally:
        if conn is not None:
            conn.close()


def gerar_xlsx(filtros, registro=None) -> bytes:
    """xlsx com identificador como TEXTO. Recusa acima do teto.

    Nao streama, e o teto existe por isso -- ver docstring."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    nomes = colunas(filtros.movimento)
    sql, params = _sql(filtros)
    conn = None
    try:
        conn = conexao.conectar()
        with conn.cursor() as cur:
            total = contar(cur, filtros)
            if total > TETO_XLSX:
                raise DownloadGrandeDemais(
                    f"{total:,} linhas passam do teto de {TETO_XLSX:,} do xlsx. "
                    "Baixe em CSV, que sai em streaming sem teto."
                    .replace(",", ".")
                )

        livro = Workbook(write_only=True)
        aba = livro.create_sheet("volumetria")
        aba.append([rotulo for _a, _s, rotulo in nomes])

        # as colunas que TEM que sair como texto, para o zero a esquerda
        # sobreviver. A lista sai do contrato, nao da memoria de ninguem.
        como_texto = {
            i for i, (apelido, _s, _r) in enumerate(nomes)
            if apelido in contrato.IDENTIFICADORES_TEXTO
        }

        enviadas = 0
        with conn.cursor(name="cat_download_xlsx") as cur:
            cur.itersize = BLOCO
            cur.execute(sql, params)
            for linha in cur:
                celulas = []
                for i, valor in enumerate(linha):
                    if i in como_texto:
                        celula = WriteOnlyCell(aba, value="" if valor is None else str(valor))
                        celula.number_format = "@"
                        celulas.append(celula)
                    else:
                        celulas.append(valor)
                aba.append(celulas)
                enviadas += 1

        fluxo = io.BytesIO()
        livro.save(fluxo)
        if registro is not None:
            auditoria.fechar(registro, enviadas)
        logger.info("download xlsx concluido: %d linha(s)", enviadas)
        return fluxo.getvalue()
    except Exception as erro:
        if registro is not None:
            auditoria.falhar(registro, erro)
        raise
    finally:
        if conn is not None:
            conn.close()
