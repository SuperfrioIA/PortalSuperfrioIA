"""Download do recorte: CSV em streaming e xlsx sob teto.

Adaptado de `backend/volumetria_catering/download.py` para Oracle: sem cursor
nomeado (o oracledb não tem esse conceito) — `preparar_cursor()`
(`arraysize`/`prefetchrows`, ver `conexao_dw.py`) já faz o driver entregar em
blocos, e iterar `for linha in cur` nunca segura o resultado inteiro na
memória. O gerador continua **dono da própria conexão**, pelo mesmo motivo do
catering: o corpo roda depois de a resposta HTTP começar.

## Colunas: tela + arquivo, não a linha inteira

Diferença deliberada do catering (que leva TODAS as colunas do contrato,
`SK_*` incluído): aqui o arquivo leva `contrato.COLUNAS_ARQUIVO` — a regra de
exclusão decidida em 03/set. `SK_*`, `DW_PROCESSO` etc. nunca saem daqui.
"""

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal

from backend.volumetria_transporte import auditoria, conexao_dw, contrato, recorte

logger = logging.getLogger(__name__)

TETO_XLSX = 150_000
TETO_CONFIRMACAO = 150_000
BOM = "﻿"  # U+FEFF como escape


class DownloadGrandeDemais(Exception):
    """Recorte acima do teto do formato pedido."""


_EXPRESSAO = {"placa": recorte.PLACA_ROTULO}
_ROTULO = {
    "pk_dw": "ID do DW (procedência)",
    "nk_filial": "CNPJ da filial",
    "ano_entrega": "Ano de entrega",
    "empresa_entrega": "Empresa de entrega",
    "filial_entrega": "Filial de entrega",
    "cnpj_filial_entrega": "CNPJ da filial de entrega",
    "nome_und": "Unidade (nome na fonte)",
    "cnpj_cpf_cli": "CNPJ/CPF do cliente",
    "nk_slin_empresa": "Empresa (SLIN)",
    "nk_slin_filial": "Filial (SLIN)",
    "nk_calendario": "Dia",
    "nk_wms_filial": "Unidade",
    "nk_cliente": "Cliente (código)",
    "raz_social": "Cliente",
    "nome_estoque": "Tipo de estoque",
    "tipo_viagem": "Tipo de viagem",
    "tipo_movimento": "Tipo de movimento",
    "status_viagem": "Status da viagem",
    "status_wms": "Status WMS",
    "status_baixa": "Status de baixa",
    "num_gem": "Guia (GEM)",
    "num_pedido": "Pedido",
    "num_nf": "Nota fiscal",
    "placa": "Placa",
    "data_programacao": "Data de programação",
    "qtde_peso": "Peso líquido (kg)",
    "qtde_pbrt": "Peso bruto (kg)",
    "qtde_vlr": "Valor (R$)",
}


def colunas():
    """`[(apelido, sql, rotulo)]` — `contrato.COLUNAS_ARQUIVO`, na ordem."""
    return [
        (nome, _EXPRESSAO.get(nome, f"f.{nome}"), _ROTULO.get(nome, nome))
        for nome in contrato.COLUNAS_ARQUIVO
    ]


def _sql(filtros: recorte.Filtros):
    de_para_where, params = recorte.de_para_where(filtros)
    nomes = colunas()
    selecoes = [f"{sql} AS {apelido}" for apelido, sql, _r in nomes]
    ordem = "f.nk_calendario, " + ", ".join(f"f.{c}" for c in contrato.CHAVE_NATURAL)
    return "\n".join((f"SELECT {', '.join(selecoes)}", de_para_where, f"ORDER BY {ordem}")), params


def contar(cur, filtros: recorte.Filtros) -> int:
    de_para_where, params = recorte.de_para_where(filtros)
    cur.execute(f"SELECT COUNT(*) {de_para_where}", params)
    return cur.fetchone()[0]


def nome_do_arquivo(filtros: recorte.Filtros, extensao: str) -> str:
    dias = "_dias" if filtros.dias else ""
    return f"volumetria_transporte_{filtros.de}_a_{filtros.ate}{dias}.{extensao}"


def _para_csv(valor):
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


def gerar_csv(filtros: recorte.Filtros, registro=None):
    """Gera o CSV linha a linha. **Dono da própria conexão** — ver docstring."""
    tampao = io.StringIO()
    escritor = csv.writer(tampao, delimiter=";", lineterminator="\r\n")

    def despejar():
        conteudo = tampao.getvalue()
        tampao.seek(0)
        tampao.truncate(0)
        return conteudo

    nomes = colunas()
    sql, params = _sql(filtros)
    enviadas = 0
    conn = None
    try:
        conn = conexao_dw.conectar()
        with conn.cursor() as cur:
            conexao_dw.preparar_cursor(cur)
            cur.execute(sql, params)
            escritor.writerow([rotulo for _a, _s, rotulo in nomes])
            yield BOM + despejar()
            for linha in cur:
                escritor.writerow([_para_csv(v) for v in linha])
                enviadas += 1
                if enviadas % conexao_dw.LOTE_LEITURA == 0:
                    yield despejar()
            resto = despejar()
            if resto:
                yield resto
        if registro is not None:
            auditoria.fechar(registro, enviadas)
        logger.info("volumetria-transporte: download csv concluído: %d linha(s)", enviadas)
    except GeneratorExit:
        if registro is not None:
            auditoria.falhar(registro, f"interrompido pelo cliente após {enviadas} linha(s)")
        raise
    except Exception as erro:
        if registro is not None:
            auditoria.falhar(registro, erro)
        raise
    finally:
        if conn is not None:
            conn.close()


def gerar_xlsx(filtros: recorte.Filtros, registro=None) -> bytes:
    """xlsx com identificador como TEXTO. Recusa acima do teto."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    nomes = colunas()
    sql, params = _sql(filtros)
    conn = None
    try:
        conn = conexao_dw.conectar()
        with conn.cursor() as cur:
            conexao_dw.preparar_cursor(cur)
            total = contar(cur, filtros)
            if total > TETO_XLSX:
                raise DownloadGrandeDemais(
                    f"{total:,} linhas passam do teto de {TETO_XLSX:,} do xlsx. "
                    "Baixe em CSV, que sai em streaming sem teto.".replace(",", ".")
                )

            livro = Workbook(write_only=True)
            aba = livro.create_sheet("volumetria-transporte")
            aba.append([rotulo for _a, _s, rotulo in nomes])

            como_texto = {
                i for i, (apelido, _s, _r) in enumerate(nomes)
                if apelido in contrato.IDENTIFICADORES_TEXTO
            }

            enviadas = 0
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
        logger.info("volumetria-transporte: download xlsx concluído: %d linha(s)", enviadas)
        return fluxo.getvalue()
    except Exception as erro:
        if registro is not None:
            auditoria.falhar(registro, erro)
        raise
    finally:
        if conn is not None:
            conn.close()
