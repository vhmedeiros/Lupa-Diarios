"""Testes dos endpoints de app/routers.py — PLANO.md Fases 14 e 17.

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

Os testes de /portals e /publications seguem o mesmo padrão de sessão
falsa (mesmo motivo: evitar o engine real sob dois loops distintos) para
checar a rota HTTP (status, formato da resposta). A lógica de consulta em
si (ordenação por `created_at` desc e o `limit`) é testada à parte, contra
o banco real de teste via a fixture `db_session` (mesmo padrão de
tests/test_pipeline.py e tests/test_retention.py), chamando
`routers.fetch_recent_publications` diretamente — sem passar pelo
TestClient, então sem o problema dos dois loops.
"""

import datetime as dt
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app import routers
from app.dedupe import compute_hash
from app.main import app
from app.models import Publication as PublicationORM
from app.registry import Portal


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


class _FakeQueryResult:
    """Fake do retorno de `session.execute(...)`: serve tanto para o group-by
    de /portals (via `.all()`) quanto para a lista de ORM de /publications
    (via `.scalars().all()`), já que ambos os usos aqui só precisam devolver
    uma lista pronta, sem interpretar a query de verdade."""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows

    def scalars(self) -> "_FakeQueryResult":
        return self


def _fake_session_with_result(rows: list) -> type:
    class _Session(_FakeSession):
        async def execute(self, _stmt: object) -> _FakeQueryResult:
            return _FakeQueryResult(rows)

    @asynccontextmanager
    async def _fake_session_ctx():
        yield _Session()

    return _fake_session_ctx


def test_get_portals_lista_portals_yaml_com_enabled_e_ultima_execucao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_portals = [
        Portal(
            code="TCU",
            name="Diário do TCU",
            url="https://portal.tcu.gov.br/btcu",
            adapter="tcu",
            engine="http",
            enabled=True,
        ),
        Portal(
            code="JFDFDJN",
            name="Diário da Justiça Federal do DF",
            url="https://trf1.jus.br/trf1/biblioteca/diarios-da-justica",
            adapter="trf1_biblioteca",
            engine="playwright",
            enabled=False,
        ),
    ]
    monkeypatch.setattr(routers, "load_portals", lambda: fake_portals)
    last_run = dt.datetime(2026, 8, 13, 10, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(routers, "async_session", _fake_session_with_result([("TCU", last_run)]))

    client = TestClient(app)
    response = client.get("/portals")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["code"] == "TCU"
    assert body[0]["enabled"] is True
    assert body[0]["last_run_at"] == "2026-08-13T10:00:00Z"
    assert body[1]["code"] == "JFDFDJN"
    assert body[1]["enabled"] is False
    assert body[1]["last_run_at"] is None


def test_get_publications_retorna_publicacoes_serializadas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub = PublicationORM(
        id=1,
        portal_code="TCU",
        portal_name="Diário do TCU",
        title="Publicação de teste",
        published_at=dt.date(2026, 8, 13),
        page_url="https://portal.tcu.gov.br/btcu/1",
        summary=None,
        files=[],
        content_hash="fake-hash-1",
        created_at=dt.datetime(2026, 8, 13, 12, 0, tzinfo=dt.UTC),
        sent_at=None,
    )
    monkeypatch.setattr(routers, "async_session", _fake_session_with_result([pub]))

    client = TestClient(app)
    response = client.get("/publications?limit=10")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["portal_code"] == "TCU"
    assert body[0]["title"] == "Publicação de teste"
    assert body[0]["sent_at"] is None


async def test_fetch_recent_publications_ordena_por_created_at_desc_e_respeita_limit(
    db_session: AsyncSession,
) -> None:
    """Verifica a query real (ordenação + limit) contra o banco de teste.

    Usa `created_at` no ano 2099 para garantir que as 3 publicações
    inseridas aqui fiquem à frente de qualquer outra linha já existente no
    banco de dev compartilhado (ver aviso em tests/test_retention.py), sem
    precisar filtrar/limpar a tabela inteira.
    """
    portal_code = "FASE17TEST"
    far_future = dt.datetime(2099, 1, 1, tzinfo=dt.UTC)

    def _pub(ref: str, created_at: dt.datetime) -> PublicationORM:
        page_url = f"https://exemplo.gov.br/fase17/{ref}"
        return PublicationORM(
            portal_code=portal_code,
            portal_name="Portal de teste Fase 17",
            title=f"Publicação {ref}",
            published_at=dt.date(2026, 8, 13),
            page_url=page_url,
            summary=None,
            files=[],
            content_hash=compute_hash(portal_code, page_url, dt.date(2026, 8, 13)),
            created_at=created_at,
        )

    pubs = [
        _pub("1", far_future),
        _pub("2", far_future + dt.timedelta(minutes=1)),
        _pub("3", far_future + dt.timedelta(minutes=2)),
    ]
    db_session.add_all(pubs)
    await db_session.flush()

    result = await routers.fetch_recent_publications(db_session, limit=2)

    assert [p.title for p in result[:2]] == ["Publicação 3", "Publicação 2"]
