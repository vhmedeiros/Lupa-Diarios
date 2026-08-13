"""Testes do adapter TCDF (API JSON escondida) — sem rede, usa fixtures."""

import datetime as dt
from pathlib import Path

from app.scrapers.tcdf import TcdfScraper

LISTAGEM_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tcdf_diarios.json"
DETALHE_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tcdf_diario_detalhe.json"


def test_parse_listing_returns_most_recent_edition() -> None:
    json_text = LISTAGEM_FIXTURE_PATH.read_text(encoding="utf-8")
    scraper = TcdfScraper(url="https://doe.tc.df.gov.br")

    latest = scraper._parse_listing(json_text)

    assert latest is not None
    assert latest["id"] == "1f196cba-5a21-6c5a-894a-e36c5aa40d74"
    assert latest["published_at"] == dt.date(2026, 8, 13)


def test_parse_detail_returns_publications() -> None:
    json_text = DETALHE_FIXTURE_PATH.read_text(encoding="utf-8")
    scraper = TcdfScraper(url="https://doe.tc.df.gov.br")

    publications = scraper._parse_detail(json_text, published_at=dt.date(2026, 8, 13))

    # A edição da fixture tem quantidadePublicacoes=13 na listagem.
    assert len(publications) == 13

    first = publications[0]
    assert first.portal_code == "TCDF"
    assert first.portal_name == "Diário do TCDF"
    assert first.title == "DESPACHO DO SECRETÁRIO-GERAL DE ADMINISTRAÇÃO"
    assert first.published_at == dt.date(2026, 8, 13)
    assert (
        first.page_url
        == "https://doe.tc.df.gov.br/O/2026/105/despacho-do-secretario-geral-de-administracao-10"
    )
    assert first.summary is not None
    assert "Reconhecimento de d" in first.summary
    assert first.file_urls == []


def test_all_publications_share_the_edition_date() -> None:
    json_text = DETALHE_FIXTURE_PATH.read_text(encoding="utf-8")
    scraper = TcdfScraper(url="https://doe.tc.df.gov.br")

    publications = scraper._parse_detail(json_text, published_at=dt.date(2026, 8, 13))

    assert all(pub.published_at == dt.date(2026, 8, 13) for pub in publications)
