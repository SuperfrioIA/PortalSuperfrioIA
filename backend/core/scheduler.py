"""Agendador de tarefas em processo — padrão pra jobs recorrentes do Hub.

Roda dentro do mesmo processo do FastAPI (`BackgroundScheduler` do
APScheduler). Não precisa de infraestrutura extra — sem cron do sistema
operacional, sem serviço separado — correto pro volume de hoje (poucos jobs,
1x por dia cada). Se esse número crescer muito (dezenas de jobs com
dependência entre si), reconsiderar uma ferramenta dedicada; pra 1-2 jobs
diários isso seria over-engineering.

Uso (registrar um job novo, de qualquer módulo):

    from backend.core.scheduler import agendar_diario

    agendar_diario(minha_funcao, hora=8, minuto=5, job_id="meu-job")

Registre a chamada em `backend/main.py`, dentro do `lifespan`, junto dos
outros jobs — mesmo padrão de `app.include_router(...)`.
"""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("backend.core.scheduler")

_FUSO = ZoneInfo("America/Sao_Paulo")
_scheduler: BackgroundScheduler | None = None


def iniciar() -> BackgroundScheduler:
    """Cria e inicia o agendador global do processo. Idempotente."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone=_FUSO)
    _scheduler.start()
    logger.info("agendador iniciado (fuso %s)", _FUSO)
    return _scheduler


def parar() -> None:
    """Encerra o agendador. Chamar no shutdown do app."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("agendador encerrado")


def agendar_diario(func, *, hora: int, minuto: int, job_id: str) -> None:
    """Registra `func` pra rodar todo dia às `hora:minuto` (fuso America/Sao_Paulo).

    `misfire_grace_time` dá 10 minutos de tolerância: se o processo estava
    reiniciando (deploy) bem no horário, o job ainda dispara ao voltar, em vez
    de só ser pulado silenciosamente até o dia seguinte.
    """
    scheduler = iniciar()
    scheduler.add_job(
        func,
        trigger=CronTrigger(hour=hora, minute=minuto, timezone=_FUSO),
        id=job_id,
        replace_existing=True,
        misfire_grace_time=600,
    )
    logger.info("job '%s' agendado para %02d:%02d", job_id, hora, minuto)
