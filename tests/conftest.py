"""Fixtures pytest: sessão de banco de teste (usa o serviço `db` do compose).

Cada teste roda dentro de uma transação aberta numa conexão dedicada e
revertida (rollback) no teardown, para não sujar o banco entre testes.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# Garante que os modelos estejam registrados em Base.metadata antes do create_all.
from app import models  # noqa: F401
from app.db import Base, engine


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_schema() -> AsyncGenerator[None]:
    """Cria as tabelas uma vez para a sessão de testes."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession]:
    """Sessão de banco isolada por teste, revertida ao final."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
