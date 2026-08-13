"""Testes de app/dedupe.py: hash determinístico e dedupe via seen_hashes."""

import datetime as dt

from sqlalchemy import select

from app.dedupe import clear_hashes, compute_hash, filter_new
from app.models import Publication as PublicationORM
from app.models import SeenHash
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


async def test_clear_hashes_remove_apenas_os_hashes_informados(db_session) -> None:
    """--force: clear_hashes apaga só as linhas pedidas, nunca a tabela toda.

    Este é o teste que valida o risco que motivou pedir precisão por hash em
    vez de um DELETE genérico por portal_code: publicações de outro portal
    (ou outro hash do mesmo fetch) não podem ser afetadas.
    """
    publicacao_alvo = _publicacao(portal_code="A", page_url="https://example.com/a/1")
    publicacao_outro_portal = _publicacao(portal_code="B", page_url="https://example.com/b/1")
    await filter_new(db_session, [publicacao_alvo, publicacao_outro_portal])

    hash_alvo = compute_hash("A", "https://example.com/a/1", dt.date(2026, 8, 13))
    hash_outro = compute_hash("B", "https://example.com/b/1", dt.date(2026, 8, 13))

    removidos = await clear_hashes(db_session, [hash_alvo])

    assert removidos == 1
    assert await db_session.get(SeenHash, hash_alvo) is None
    assert await db_session.get(SeenHash, hash_outro) is not None

    rows = (
        (await db_session.execute(select(PublicationORM).where(PublicationORM.portal_code == "A")))
        .scalars()
        .all()
    )
    assert rows == []

    rows_outro_portal = (
        (await db_session.execute(select(PublicationORM).where(PublicationORM.portal_code == "B")))
        .scalars()
        .all()
    )
    assert len(rows_outro_portal) == 1


async def test_clear_hashes_com_lista_vazia_nao_apaga_nada(db_session) -> None:
    publicacao = _publicacao()
    await filter_new(db_session, [publicacao])

    removidos = await clear_hashes(db_session, [])

    assert removidos == 0
    hash_existente = compute_hash("TST", "https://example.com/publicacao/1", dt.date(2026, 8, 13))
    assert await db_session.get(SeenHash, hash_existente) is not None


async def test_publicacao_forcada_pode_ser_recoletada_apos_clear_hashes(db_session) -> None:
    """Depois de clear_hashes, filter_new volta a tratar a publicação como nova."""
    publicacao = _publicacao()

    primeira = await filter_new(db_session, [publicacao])
    assert primeira == [publicacao]

    hash_publicacao = compute_hash("TST", "https://example.com/publicacao/1", dt.date(2026, 8, 13))
    await clear_hashes(db_session, [hash_publicacao])

    segunda = await filter_new(db_session, [publicacao])
    assert segunda == [publicacao]
