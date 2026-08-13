"""Scheduler do serviço (ver PLANO.md Fase 16).

Registra dois jobs no APScheduler:

1. "scan": roda `app.pipeline.run_cycle` para TODOS os portais
   habilitados, disparado pelo cron `SCAN_CRON` (padrão
   "0 8-20 * * 1-5"), na timezone `TZ` (padrão America/Sao_Paulo).
2. "retention": roda `app.retention.run_retention` uma vez por dia, às
   03:00 (America/Sao_Paulo) — horário de baixo tráfego, escolhido por
   ficar fora da janela do scan (que só começa às 8h) e não concorrer
   com o horário comercial.

Cada disparo de job abre sua PRÓPRIA sessão de banco (`app.db.async_session`),
igual ao padrão já usado em `app/routers.py` para os endpoints `/run` —
jobs do scheduler rodam fora do ciclo de vida de uma requisição HTTP, então
nunca reaproveitam uma sessão global entre execuções.

`start()` é chamado uma única vez, no `lifespan` de `app/main.py`.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import async_session
from app.pipeline import run_cycle
from app.retention import run_retention

logger = logging.getLogger(__name__)

# Horário de baixo tráfego para a retenção: madrugada, antes do primeiro
# scan do dia (SCAN_CRON padrão só começa às 8h).
RETENTION_HOUR = 3
RETENTION_MINUTE = 0

scheduler = AsyncIOScheduler(timezone=settings.TZ)


async def _run_scan_job() -> None:
    """Executa um ciclo completo de coleta (todos os portais habilitados)."""
    async with async_session() as session:
        try:
            count = await run_cycle(session)
            await session.commit()
            logger.info("Scheduler: ciclo de scan concluído, %d publicações enviadas", count)
        except Exception:
            await session.rollback()
            logger.exception("Scheduler: ciclo de scan falhou")


async def _run_retention_job() -> None:
    """Executa o job diário de retenção."""
    async with async_session() as session:
        try:
            count = await run_retention(session)
            await session.commit()
            logger.info("Scheduler: retenção concluída, %d publicações apagadas", count)
        except Exception:
            await session.rollback()
            logger.exception("Scheduler: job de retenção falhou")


def start() -> AsyncIOScheduler:
    """Registra os jobs de scan e retenção e inicia o scheduler.

    Idempotente (`replace_existing=True`): pode ser chamada mais de uma
    vez sem duplicar jobs. Loga os próximos horários agendados de cada
    job — é essa linha que confirma o agendamento na subida da aplicação.
    """
    scheduler.add_job(
        _run_scan_job,
        trigger=CronTrigger.from_crontab(settings.SCAN_CRON, timezone=settings.TZ),
        id="scan",
        name="scan",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_retention_job,
        trigger=CronTrigger(hour=RETENTION_HOUR, minute=RETENTION_MINUTE, timezone=settings.TZ),
        id="retention",
        name="retention",
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()

    for job in scheduler.get_jobs():
        logger.info(
            "Scheduler: job '%s' agendado — próxima execução em %s", job.id, job.next_run_time
        )

    return scheduler
