"""Testes do adapter comunica_pje (API JSON do DJEN) — sem rede, usa fixture."""

import datetime as dt
from pathlib import Path

from app.scrapers.comunica_pje import ComunicaPjeScraper

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "comunica_pje_stj.json"
FIXTURE_PATH_TRF1 = Path(__file__).parent / "fixtures" / "comunica_pje_trf1.json"
FIXTURE_PATH_TST = Path(__file__).parent / "fixtures" / "comunica_pje_tst.json"


def test_parse_page_returns_publications() -> None:
    json_text = FIXTURE_PATH.read_text(encoding="utf-8")
    scraper = ComunicaPjeScraper(
        url="https://comunica.pje.jus.br/consulta?siglaTribunal=STJ&meio=D",
        portal_code="STJDJN",
        portal_name="STJ no DJEN (Comunica PJe)",
        params={"sigla_tribunal": "STJ"},
    )

    publications = scraper._parse(json_text)

    assert len(publications) > 0

    first = publications[0]
    assert first.portal_code == "STJDJN"
    assert first.portal_name == "STJ no DJEN (Comunica PJe)"
    assert first.title
    assert first.page_url.startswith("https://comunicaapi.pje.jus.br/api/v1/comunicacao/")
    assert isinstance(first.published_at, dt.date)
    assert first.summary
    assert first.file_urls == []


def test_parse_page_returns_publications_trf1() -> None:
    json_text = FIXTURE_PATH_TRF1.read_text(encoding="utf-8")
    scraper = ComunicaPjeScraper(
        url="https://comunica.pje.jus.br/consulta?siglaTribunal=TRF1&meio=D",
        portal_code="TRFDJN",
        portal_name="TRF 1ª Região no DJEN (Comunica PJe)",
        params={"sigla_tribunal": "TRF1"},
    )

    publications = scraper._parse(json_text)

    assert len(publications) > 0

    first = publications[0]
    assert first.portal_code == "TRFDJN"
    assert first.portal_name == "TRF 1ª Região no DJEN (Comunica PJe)"
    assert first.title
    assert first.page_url.startswith("https://comunicaapi.pje.jus.br/api/v1/comunicacao/")
    assert isinstance(first.published_at, dt.date)
    assert first.summary
    assert first.file_urls == []


def test_parse_page_returns_publications_tst() -> None:
    json_text = FIXTURE_PATH_TST.read_text(encoding="utf-8")
    scraper = ComunicaPjeScraper(
        url="https://comunica.pje.jus.br/consulta?siglaTribunal=TST&meio=D",
        portal_code="TSTDJN",
        portal_name="TST no DJEN (Comunica PJe)",
        params={"sigla_tribunal": "TST"},
    )

    publications = scraper._parse(json_text)

    assert len(publications) > 0

    first = publications[0]
    assert first.portal_code == "TSTDJN"
    assert first.portal_name == "TST no DJEN (Comunica PJe)"
    assert first.title
    assert first.page_url.startswith("https://comunicaapi.pje.jus.br/api/v1/comunicacao/")
    assert isinstance(first.published_at, dt.date)
    assert first.summary
    assert first.file_urls == []


def test_missing_sigla_tribunal_raises() -> None:
    try:
        ComunicaPjeScraper(
            url="https://comunica.pje.jus.br/consulta?siglaTribunal=STJ&meio=D",
            portal_code="STJDJN",
            portal_name="STJ no DJEN (Comunica PJe)",
            params={},
        )
    except ValueError:
        return
    raise AssertionError("esperava ValueError quando params.sigla_tribunal está ausente")
