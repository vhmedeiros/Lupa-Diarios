"""Endpoints HTTP para disparar o pipeline manualmente (ver PLANO.md Fase 14).

`POST /run` e `POST /run/{portal_code}` disparam o pipeline
(`app.pipeline.run_cycle`) de forma assíncrona via `BackgroundTasks` do
FastAPI: a rota responde imediatamente com `{"status": "started"}` e o
ciclo roda em segundo plano, numa sessão de banco própria. O resultado
do ciclo só vai para o log — não há endpoint de status nesta fase.
"""

import logging

from fastapi import APIRouter, BackgroundTasks

from app.db import async_session
from app.pipeline import run_cycle

logger = logging.getLogger(__name__)

router = APIRouter()


async def _run_and_log(portal_code: str | None) -> None:
    async with async_session() as session:
        try:
            count = await run_cycle(session, portal_code)
            await session.commit()
            logger.info("Pipeline concluído via /run: %d publicações enviadas", count)
        except Exception:
            await session.rollback()
            logger.exception("Pipeline disparado via /run falhou")


@router.post("/run")
async def run_all(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Dispara o pipeline para todos os portais habilitados."""
    background_tasks.add_task(_run_and_log, None)
    return {"status": "started"}


@router.post("/run/{portal_code}")
async def run_portal(portal_code: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Dispara o pipeline apenas para o portal informado."""
    background_tasks.add_task(_run_and_log, portal_code)
    return {"status": "started", "portal": portal_code}
