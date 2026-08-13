"""Testes do adapter TST (feed Atom do JusLaboris) — sem rede, usa fixture."""

import datetime as dt
from pathlib import Path

from app.scrapers.tst_juslaboris import TstJuslaborisScraper

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tst_juslaboris_feed.xml"


def test_parse_feed_returns_publications() -> None:
    xml_text = FIXTURE_PATH.read_text(encoding="utf-8")
    scraper = TstJuslaborisScraper(url="https://juslaboris.tst.jus.br/feed/atom_1.0/site")

    publications = scraper._parse(xml_text)

    assert len(publications) > 0

    first = publications[0]
    assert first.portal_code == "TST"
    assert first.portal_name == "Diário do TST (JusLaboris)"
    assert first.title
    assert first.page_url.startswith("http")
    assert isinstance(first.published_at, dt.date)
    assert first.summary is None
    assert first.file_urls == []
