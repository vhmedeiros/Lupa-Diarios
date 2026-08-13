"""Testes de app/pipeline.py: orquestração fetch->dedupe->download->e-mail
(ver PLANO.md Fase 14 / SPEC.md §11 R4, R5).

Não toca rede real nem envia e-mail real: `build_scraper`,
`download_publication_files` e `send_email` são monkeypatchados dentro
do módulo `app.pipeline`. O banco é o real de teste (via `db_session`,
ver tests/conftest.py), revertido ao final de cada teste.
"""

import datetime as dt

import pytest
from sqlalchemy import select

from app import pipeline
from app.models import Publication as PublicationORM
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


def _scraped(
    code: str,
    ref: str,
    published_at: dt.date = dt.date(2026, 8, 13),
    file_urls: list[str] | None = None,
) -> ScrapedPublication:
    return ScrapedPublication(
        portal_code=code,
        portal_name=f"Portal {code}",
        title=f"Publicação {ref}",
        published_at=published_at,
        page_url=f"https://exemplo.gov.br/{code}/{ref}",
        summary=None,
        file_urls=file_urls or [],
    )


class _FakeScraper:
    """Scraper falso: devolve uma lista fixa de publicações ou levanta um erro."""

    def __init__(
        self,
        publications: list[ScrapedPublication] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._publications = publications or []
        self._error = error

    async def fetch(self) -> list[ScrapedPublication]:
        if self._error is not None:
            raise self._error
        return self._publications


def _patch_no_download(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Substitui o downloader real por um fake que não toca rede."""
    calls: dict = {"count": 0}

    async def fake_download(publication: ScrapedPublication, *args: object, **kwargs: object):
        calls["count"] += 1
        return []

    monkeypatch.setattr(pipeline, "download_publication_files", fake_download)
    return calls


def _patch_send_email(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Substitui o envio real de e-mail por um fake que só registra a chamada."""
    sent: list[dict] = []

    async def fake_send_email(subject: str, html_body: str, attachments: list | None = None):
        sent.append({"subject": subject, "html_body": html_body, "attachments": attachments})

    monkeypatch.setattr(pipeline, "send_email", fake_send_email)
    return sent


async def test_ciclo_com_publicacoes_novas_envia_email_e_grava_sent_at(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    portal = _portal("A")
    scraped = [_scraped("A", "1")]

    monkeypatch.setattr(pipeline, "get_enabled_portals", lambda: [portal])
    monkeypatch.setattr(pipeline, "build_scraper", lambda p: _FakeScraper(scraped))
    _patch_no_download(monkeypatch)
    sent = _patch_send_email(monkeypatch)

    count = await pipeline.run_cycle(db_session)

    assert count == 1
    assert len(sent) == 1
    assert "Publicação 1" in sent[0]["html_body"]

    rows = (
        (await db_session.execute(select(PublicationORM).where(PublicationORM.portal_code == "A")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].sent_at is not None


async def test_ciclo_sem_publicacoes_novas_nao_envia_email(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    portal = _portal("B")

    monkeypatch.setattr(pipeline, "get_enabled_portals", lambda: [portal])
    monkeypatch.setattr(pipeline, "build_scraper", lambda p: _FakeScraper([]))
    _patch_no_download(monkeypatch)
    sent = _patch_send_email(monkeypatch)

    count = await pipeline.run_cycle(db_session)

    assert count == 0
    assert sent == []


async def test_erro_em_um_portal_nao_impede_os_demais(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    portal_a = _portal("C")
    portal_b = _portal("D")
    scraped_b = [_scraped("D", "1")]

    scrapers_by_code = {
        "C": _FakeScraper(error=RuntimeError("portal C fora do ar")),
        "D": _FakeScraper(scraped_b),
    }

    monkeypatch.setattr(pipeline, "get_enabled_portals", lambda: [portal_a, portal_b])
    monkeypatch.setattr(pipeline, "build_scraper", lambda p: scrapers_by_code[p.code])
    _patch_no_download(monkeypatch)
    sent = _patch_send_email(monkeypatch)

    count = await pipeline.run_cycle(db_session)

    assert count == 1
    assert len(sent) == 1

    rows = (
        (
            await db_session.execute(
                select(PublicationORM).where(PublicationORM.portal_code.in_(["C", "D"]))
            )
        )
        .scalars()
        .all()
    )
    assert [r.portal_code for r in rows] == ["D"]


async def test_segunda_chamada_com_mesmas_publicacoes_nao_reenvia(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    portal = _portal("E")
    scraped = [_scraped("E", "1")]

    monkeypatch.setattr(pipeline, "get_enabled_portals", lambda: [portal])
    monkeypatch.setattr(pipeline, "build_scraper", lambda p: _FakeScraper(scraped))
    _patch_no_download(monkeypatch)
    sent = _patch_send_email(monkeypatch)

    primeira = await pipeline.run_cycle(db_session)
    segunda = await pipeline.run_cycle(db_session)

    assert primeira == 1
    assert segunda == 0
    assert len(sent) == 1  # só a primeira chamada enviou e-mail
