"""Endpoints HTTP de operação (ver PLANO.md Fases 14 e 17).

`POST /run` e `POST /run/{portal_code}` disparam o pipeline
(`app.pipeline.run_cycle`) de forma assíncrona via `BackgroundTasks` do
FastAPI: a rota responde imediatamente com `{"status": "started"}` e o
ciclo roda em segundo plano, numa sessão de banco própria. O resultado
do ciclo só vai para o log — não há endpoint de status nesta fase.

`GET /portals` e `GET /publications` são consultas simples de leitura
(ver `app/schemas.py` para a explicação de `last_run_at`).
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Query
from sqlalchemy import func, select

from app.db import async_session
from app.models import Publication as PublicationORM
from app.pipeline import run_cycle
from app.registry import load_portals
from app.schemas import PortalOut, PublicationOut

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


@router.get("/portals", response_model=list[PortalOut])
async def list_portals() -> list[PortalOut]:
    """Lista os portais de portals.yaml com `enabled` e a última execução conhecida."""
    portals = load_portals()
    async with async_session() as session:
        result = await session.execute(
            select(PublicationORM.portal_code, func.max(PublicationORM.sent_at)).group_by(
                PublicationORM.portal_code
            )
        )
        last_run_by_portal = dict(result.all())

    return [
        PortalOut(
            code=portal.code,
            name=portal.name,
            url=portal.url,
            adapter=portal.adapter,
            engine=portal.engine,
            enabled=portal.enabled,
            last_run_at=last_run_by_portal.get(portal.code),
        )
        for portal in portals
    ]


async def fetch_recent_publications(session: object, limit: int) -> list[PublicationORM]:
    """Busca as `limit` publicações mais recentes do buffer, mais novas primeiro."""
    result = await session.execute(
        select(PublicationORM)
        .order_by(PublicationORM.created_at.desc(), PublicationORM.id.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/publications", response_model=list[PublicationOut])
async def list_publications(
    limit: int = Query(default=50, ge=1, le=500),
) -> list[PublicationOut]:
    """Retorna as últimas publicações do buffer, ordenadas por `created_at` desc."""
    async with async_session() as session:
        publications = await fetch_recent_publications(session, limit)
    return [PublicationOut.model_validate(p) for p in publications]
