"""Aplicação FastAPI do Lupa Diários."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

# Garante que os modelos estejam registrados em Base.metadata antes do create_all.
from app import models  # noqa: F401
from app import scheduler as scheduler_module
from app.db import Base, engine
from app.routers import router

# uvicorn não configura o logger raiz (só os próprios loggers "uvicorn.*"),
# então sem isso os logger.info(...) dos módulos da aplicação (scheduler,
# pipeline, routers, retention) ficam abaixo do nível padrão (WARNING) e
# nunca aparecem em `docker compose logs app`.
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cria as tabelas no banco e inicia o scheduler (scan + retenção) na subida."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    scheduler_module.start()
    yield
    scheduler_module.scheduler.shutdown()


app = FastAPI(title="Lupa Diários", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, object]:
    """Healthcheck com verificação real de conexão ao banco."""
    db_ok = False
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        db_ok = result.scalar_one() == 1
    return {"status": "ok", "db": db_ok, "last_run_at": None}
