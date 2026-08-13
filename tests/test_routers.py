"""Testes dos endpoints /run (app/routers.py) — ver PLANO.md Fase 14.

`app.pipeline.run_cycle` é monkeypatchado por um fake: nada de rede real,
banco real ou e-mail real. `app.routers.async_session` também é
substituído por uma sessão falsa — o `TestClient` roda a app num event
loop próprio (thread separada via anyio), diferente do loop da suíte de
testes (pytest-asyncio), e a `engine` real do SQLAlchemy/asyncpg não
suporta ser usada a partir de dois loops distintos; como o pipeline já
está mockado, a sessão real não faz falta aqui.

Usa `fastapi.testclient.TestClient` sem entrar no `lifespan` (sem `with`)
— o schema já foi criado pela fixture de sessão em tests/conftest.py, e
as `BackgroundTasks` da resposta rodam antes de `client.post(...)`
devolver o controle ao teste, então dá para checar a chamada de forma
síncrona, sem sleep.
"""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app import routers
from app.main import app


class _FakeSession:
    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass


@asynccontextmanager
async def _fake_async_session():
    yield _FakeSession()


def _fake_run_cycle(calls: list) -> callable:
    async def fake(session: object, portal_code: str | None = None) -> int:
        calls.append(portal_code)
        return 1

    return fake


def test_post_run_dispara_pipeline_para_todos_os_portais(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    monkeypatch.setattr(routers, "run_cycle", _fake_run_cycle(calls))
    monkeypatch.setattr(routers, "async_session", _fake_async_session)

    client = TestClient(app)
    response = client.post("/run")

    assert response.status_code == 200
    assert response.json() == {"status": "started"}
    assert calls == [None]


def test_post_run_portal_dispara_pipeline_apenas_para_o_portal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    monkeypatch.setattr(routers, "run_cycle", _fake_run_cycle(calls))
    monkeypatch.setattr(routers, "async_session", _fake_async_session)

    client = TestClient(app)
    response = client.post("/run/TCU")

    assert response.status_code == 200
    assert response.json() == {"status": "started", "portal": "TCU"}
    assert calls == ["TCU"]
