"""Testes de app/cli.py: flag --force do comando `run` (fora do PLANO.md
original, feature pontual aprovada em sessão — reenvio manual de
publicações já vistas sem DELETE direto no Postgres).

Padrão de mock reaproveitado de tests/test_pipeline.py (build_scraper,
download_publication_files e send_email monkeypatchados — nada de rede
real nem e-mail real) e de tests/test_routers.py (`app.cli.async_session`
substituído por uma sessão fake que só repassa `db_session`, para tudo
rodar dentro da mesma transação/loop do teste, revertida ao final).
"""

import datetime as dt
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app import cli, pipeline
from app.models import Publication as PublicationORM
from app.models import SeenHash
from app.registry import Portal
from app.scrapers.base import Publication as ScrapedPublication


def _portal(code: str) -> Portal:
    return Portal(
        code=code,
        name=f"Portal {code}",
        url="https://exemplo.gov.br",
        adapter="fake",
        engine="http",
        enabled=True,
    )


def _scraped(code: str, ref: str) -> ScrapedPublication:
    return ScrapedPublication(
        portal_code=code,
        portal_name=f"Portal {code}",
        title=f"Publicação {ref}",
        published_at=dt.date(2026, 8, 13),
        page_url=f"https://exemplo.gov.br/{code}/{ref}",
        summary=None,
        file_urls=[],
    )


class _FakeScraper:
    def __init__(self, publications: list[ScrapedPublication]) -> None:
        self._publications = publications

    async def fetch(self) -> list[ScrapedPublication]:
        return self._publications


def _patch_session(monkeypatch: pytest.MonkeyPatch, db_session) -> None:
    """Faz `app.cli.async_session()` devolver a sessão de teste (mesmo loop,
    mesma transação revertida ao final), em vez de abrir uma conexão real
    fora do controle da fixture."""

    @asynccontextmanager
    async def _fake_async_session():
        yield db_session

    monkeypatch.setattr(cli, "async_session", _fake_async_session)


def _patch_no_download(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_download(publication, *args: object, **kwargs: object):
        return []

    monkeypatch.setattr(pipeline, "download_publication_files", fake_download)


def _patch_send_email(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    sent: list[dict] = []

    async def fake_send_email(subject: str, html_body: str, attachments: list | None = None):
        sent.append({"subject": subject, "html_body": html_body})

    monkeypatch.setattr(pipeline, "send_email", fake_send_email)
    return sent


def test_force_sem_portal_sai_com_erro_claro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["prog", "run", "--force"])

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert "--portal" in str(exc_info.value)


async def test_force_clear_seen_remove_apenas_o_hash_do_portal_pedido(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    portal_a = _portal("A")
    scraped_a = [_scraped("A", "1")]
    scraped_b = [_scraped("B", "1")]

    # Semeia o estado "já visto" dos dois portais, como se um ciclo anterior
    # já tivesse processado ambos.
    monkeypatch.setattr(pipeline, "get_enabled_portals", lambda: [portal_a, _portal("B")])
    monkeypatch.setattr(
        pipeline,
        "build_scraper",
        lambda p: _FakeScraper(scraped_a if p.code == "A" else scraped_b),
    )
    _patch_no_download(monkeypatch)
    _patch_send_email(monkeypatch)
    await pipeline.run_cycle(db_session)

    hash_a = pipeline.compute_hash("A", scraped_a[0].page_url, scraped_a[0].published_at)
    hash_b = pipeline.compute_hash("B", scraped_b[0].page_url, scraped_b[0].published_at)
    assert await db_session.get(SeenHash, hash_a) is not None
    assert await db_session.get(SeenHash, hash_b) is not None

    monkeypatch.setattr(cli, "_find_portal", lambda code: portal_a)
    monkeypatch.setattr(cli, "_build_scraper", lambda portal: _FakeScraper(scraped_a))

    await cli._force_clear_seen(db_session, "A")

    # Hash do portal A liberado; hash do portal B (outro portal) intacto —
    # é justamente o risco que motivou apagar por hash, não por portal_code.
    assert await db_session.get(SeenHash, hash_a) is None
    assert await db_session.get(SeenHash, hash_b) is not None

    rows_a = (
        (await db_session.execute(select(PublicationORM).where(PublicationORM.portal_code == "A")))
        .scalars()
        .all()
    )
    rows_b = (
        (await db_session.execute(select(PublicationORM).where(PublicationORM.portal_code == "B")))
        .scalars()
        .all()
    )
    assert rows_a == []
    assert len(rows_b) == 1


async def test_run_pipeline_com_force_reenvia_publicacao_ja_vista(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integração completa: --force libera o hash e o pipeline normal trata a
    publicação como nova de novo, reenviando por e-mail."""
    portal = _portal("A")
    scraped = [_scraped("A", "1")]

    monkeypatch.setattr(pipeline, "get_enabled_portals", lambda: [portal])
    monkeypatch.setattr(pipeline, "build_scraper", lambda p: _FakeScraper(scraped))
    _patch_no_download(monkeypatch)
    sent = _patch_send_email(monkeypatch)
    _patch_session(monkeypatch, db_session)

    # Primeiro ciclo "normal": publicação processada e marcada como vista.
    primeiro = await pipeline.run_cycle(db_session)
    await db_session.flush()
    assert primeiro == 1

    # Sem --force, uma segunda chamada não reenviaria (já visto).
    segundo_sem_force = await pipeline.run_cycle(db_session)
    assert segundo_sem_force == 0

    # Com --force, o CLI limpa o hash antes de rodar o ciclo, então a mesma
    # publicação volta a ser tratada como nova.
    monkeypatch.setattr(cli, "_find_portal", lambda code: portal)
    monkeypatch.setattr(cli, "_build_scraper", lambda p: _FakeScraper(scraped))
    # run_cycle("A", ...) resolve o portal por app.pipeline.find_portal (não
    # get_enabled_portals) quando um portal_code é informado.
    monkeypatch.setattr(pipeline, "find_portal", lambda code: portal)

    await cli._run_pipeline("A", force=True)

    assert len(sent) == 2  # primeiro ciclo + reenvio forçado

    rows = (
        (await db_session.execute(select(PublicationORM).where(PublicationORM.portal_code == "A")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].sent_at is not None
