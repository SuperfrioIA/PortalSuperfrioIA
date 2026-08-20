"""Job diário de Processos Abertos: busca os relatórios no FTP do
Pentaho/SLIN/JDA, processa e grava no histórico do dashboard — substitui o
upload manual (oculto na tela enquanto isso estiver ativo).

Fluxo de uma tentativa (`_tentar`):
  1. conecta no FTP (`backend/core/ftp_reader.py`, só leitura)
  2. confere se os 2 arquivos são de HOJE — se não forem, aborta sem processar
     (o job do Pentaho pode ainda não ter rodado, ou ter falhado)
  3. baixa os 2 arquivos
  4. calcula o resumo da semana (`processing.montar_semana`)
  5. grava no histórico compartilhado (mesma função do botão manual)
  6. registra o resultado em `status.py`, pra tela mostrar

Agendado 2x por dia (`backend/main.py`): 08:05 (tentativa principal) e 08:30
(retentativa, só roda se a de 08:05 não tiver dado certo hoje). Se as duas
falharem, não existe alerta externo — o indicador na tela é a única fonte de
aviso; ver docs/... sobre por que essa foi a opção escolhida.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from backend.processos_abertos import processing
from backend.processos_abertos.router import salvar_semana_no_historico
from backend.processos_abertos.status import escrever_status, ler_status
from backend.core.ftp_reader import FtpReadOnlyClient

logger = logging.getLogger("backend.processos_abertos.jobs")

DIRETORIO_FTP = "/prod/diversos/operacional/reports/processos-abertos"
ARQUIVO_SLIN = "rpt_slin_processos_abertos_v01.xlsx"
ARQUIVO_JDA = "rpt_jda_processos_abertos_v01.xlsx"


def _cliente_ftp() -> FtpReadOnlyClient:
    return FtpReadOnlyClient(
        host=os.environ.get("FTP_HOST", "ftp-sf.superfrio.com.br"),
        port=int(os.environ.get("FTP_PORT", "21")),
        user=os.environ["FTP_USER"],
        password=os.environ["FTP_PASSWORD"],
        diretorio=DIRETORIO_FTP,
    )


def _hoje() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _validar_arquivos_de_hoje(cliente: FtpReadOnlyClient) -> None:
    hoje = datetime.now().date()
    for nome in (ARQUIVO_SLIN, ARQUIVO_JDA):
        modificado_em = cliente.data_modificacao(nome)
        if modificado_em.date() != hoje:
            raise RuntimeError(
                f"'{nome}' no FTP é de {modificado_em.date():%d/%m/%Y}, não de hoje "
                f"({hoje:%d/%m/%Y}) — o job do Pentaho pode não ter rodado ainda"
            )


def _tentar(*, rotulo: str) -> bool:
    logger.info("iniciando busca no FTP (%s)", rotulo)
    try:
        cliente = _cliente_ftp()
        _validar_arquivos_de_hoje(cliente)
        slin_bytes = cliente.baixar(ARQUIVO_SLIN)
        jda_bytes = cliente.baixar(ARQUIVO_JDA)
        semana = processing.montar_semana(slin_bytes, jda_bytes)
        salvar_semana_no_historico(semana)
    except Exception as exc:  # job de background: nunca deixa a exceção subir e derrubar o processo
        logger.exception("falha na integração de Processos Abertos (%s)", rotulo)
        escrever_status(ok=False, mensagem=str(exc), tentativa=rotulo)
        return False

    logger.info("Processos Abertos: semana %s gravada com sucesso (%s)", semana["date"], rotulo)
    escrever_status(
        ok=True,
        mensagem=f"semana {semana['date']} atualizada",
        tentativa=rotulo,
        data_sucesso=_hoje(),
    )
    return True


def executar_as_0805() -> None:
    _tentar(rotulo="08:05")


def executar_as_0830_retry() -> None:
    """Só tenta de novo se a rodada de 08:05 não tiver dado certo hoje."""
    status = ler_status()
    if status.get("ultima_data_sucesso") == _hoje():
        logger.info("08:30: já tinha dado certo às 08:05, não tenta de novo")
        return
    _tentar(rotulo="08:30 (retentativa)")


if __name__ == "__main__":
    # Disparo manual, sem esperar o horário — pra validar local:
    #   .\.venv\Scripts\python.exe -m backend.processos_abertos.jobs
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ok = _tentar(rotulo="manual")
    raise SystemExit(0 if ok else 1)
