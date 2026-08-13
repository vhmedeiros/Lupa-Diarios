"""Testes de app/dedupe.py: hash determinístico e dedupe via seen_hashes."""

import datetime as dt

from app.dedupe import compute_hash, filter_new
from app.scrapers.base import Publication


def _publicacao(**overrides: object) -> Publication:
    dados = {
        "portal_code": "TST",
        "portal_name": "Tribunal Superior do Trabalho",
        "title": "Publicação de teste",
        "published_at": dt.date(2026, 8, 13),
        "page_url": "https://example.com/publicacao/1",
        "summary": None,
        "file_urls": [],
    }
    dados.update(overrides)
    return Publication(**dados)


def test_hash_e_deterministico() -> None:
    entrada = ("TST", "https://example.com/publicacao/1", dt.date(2026, 8, 13))
    assert compute_hash(*entrada) == compute_hash(*entrada)


async def test_publicacao_repetida_nao_e_nova_na_segunda_chamada(db_session) -> None:
    publicacao = _publicacao()

    primeira_chamada = await filter_new(db_session, [publicacao])
    segunda_chamada = await filter_new(db_session, [publicacao])

    assert primeira_chamada == [publicacao]
    assert segunda_chamada == []
