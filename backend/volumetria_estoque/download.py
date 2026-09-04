"""Download do recorte: CSV em streaming e xlsx sob teto.

Cópia de `backend/volumetria_transporte/download.py`. `camara` sai `NULL`
cru do `SELECT` (mesma razão do `planilha.py`: evitar literal acentuado no
texto do SQL) e é normalizada para `contrato.CAMARA_ROTULO_VAZIA` na hora de
formatar a célula (`_para_csv`/`gerar_xlsx`), não na consulta.
"""

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal

from backend.volumetria_estoque import auditoria, conexao_dw, contrato, recorte

logger = logging.getLogger(__name__)

TETO_XLSX = 150_000
TETO_CONFIRMACAO = 150_000
BOM = "﻿"  # U+FEFF como escape


class DownloadGrandeDemais(Exception):
    """Recorte acima do teto do formato pedido."""


_ROTULO = {
    "pk_dw": "ID do DW (procedência)",
    "nk_filial": "CNPJ da filial",
    "nk_slin_empresa": "Empresa (SLIN)",
    "nk_slin_filial": "Filial (SLIN)",
    "nome_und": "Unidade (nome na fonte)",
    "cnpj_cpf_cli": "CNPJ/CPF do cliente",
    "nk_calendario": "Dia (da foto)",
    "nk_wms_filial": "Unidade",
    "nk_cliente": "Cliente (código)",
    "raz_social": "Cliente",
    "camara": "Câmara",
    "status_lote": "Status do lote",
    "qtde_sku": "SKUs (contagem do dia)",
    "qtde_pallet": "Pallets (UA)",
    "qtde_vol": "Volumes (cx)",
    "qtde_peso": "Peso líquido (kg)",
    "qtde_pbrt": "Peso bruto (kg)",
    "qtde_vlr": "Valor (R$)",
}


def colunas():
    """`[(apelido, sql, rotulo)]` — `contrato.COLUNAS_ARQUIVO`, na ordem."""
    return [
        (nome, f"f.{nome}", _ROTULO.get(nome, nome))
        for nome in contrato.COLUNAS_ARQUIVO
    ]


def _indice_camara(nomes):
    for i, (apelido, _s, _r) in enumerate(nomes):
        if apelido == "camara":
            return i
    return None


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
    return f"volumetria_estoque_{filtros.de}_a_{filtros.ate}{dias}.{extensao}"


def _para_csv(valor, indice=None, indice_camara=None):
    if indice is not None and indice == indice_camara and valor is None:
        return contrato.CAMARA_ROTULO_VAZIA
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
    tampao = io.StringIO()
    escritor = csv.writer(tampao, delimiter=";", lineterminator="\r\n")

    def despejar():
        conteudo = tampao.getvalue()
        tampao.seek(0)
        tampao.truncate(0)
        return conteudo

    nomes = colunas()
    indice_camara = _indice_camara(nomes)
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
                escritor.writerow([_para_csv(v, i, indice_camara) for i, v in enumerate(linha)])
                enviadas += 1
                if enviadas % conexao_dw.LOTE_LEITURA == 0:
                    yield despejar()
            resto = despejar()
            if resto:
                yield resto
        if registro is not None:
            auditoria.fechar(registro, enviadas)
        logger.info("volumetria-estoque: download csv concluído: %d linha(s)", enviadas)
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
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    nomes = colunas()
    indice_camara = _indice_camara(nomes)
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
            aba = livro.create_sheet("volumetria-estoque")
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
                    if i == indice_camara and valor is None:
                        valor = contrato.CAMARA_ROTULO_VAZIA
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
        logger.info("volumetria-estoque: download xlsx concluído: %d linha(s)", enviadas)
        return fluxo.getvalue()
    except Exception as erro:
        if registro is not None:
            auditoria.falhar(registro, erro)
        raise
    finally:
        if conn is not None:
            conn.close()
