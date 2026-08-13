"""Testes do adapter TCU (HTML estático via SSR) — sem rede, usa fixture."""

import datetime as dt
from pathlib import Path

from app.scrapers.tcu import TcuScraper

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tcu.html"


def test_parse_page_returns_publications() -> None:
    html_text = FIXTURE_PATH.read_text(encoding="utf-8")
    scraper = TcuScraper(url="https://portal.tcu.gov.br/btcu")

    publications = scraper._parse(html_text)

    assert len(publications) == 50

    first = publications[0]
    assert first.portal_code == "TCU"
    assert first.portal_name == "Diário do TCU"
    assert first.title == "Administrativo - Edição 147/2026"
    assert first.published_at == dt.date(2026, 8, 12)
    assert first.page_url == "http://btcu.apps.tcu.gov.br/api/obterDocumentoPdf/80869284"
    assert first.summary == "Matérias administrativas e de gestão"
    assert first.file_urls == ["http://btcu.apps.tcu.gov.br/api/obterDocumentoPdf/80869284"]


def test_publications_are_ordered_most_recent_first() -> None:
    html_text = FIXTURE_PATH.read_text(encoding="utf-8")
    scraper = TcuScraper(url="https://portal.tcu.gov.br/btcu")

    publications = scraper._parse(html_text)

    dates = [pub.published_at for pub in publications]
    assert dates == sorted(dates, reverse=True)
