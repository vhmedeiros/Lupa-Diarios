"""Testes de app/retention.py: apaga publications+arquivos velhos, nunca seen_hashes.

Roda contra o mesmo banco de dev usado pelos demais testes (via
tests/conftest.py), dentro de uma transação revertida ao final — mas
esse banco pode já ter linhas reais de outros portais. Por isso as
asserções sempre filtram pelo `content_hash` da publicação de teste, em
vez de olhar a tabela `publications` inteira.
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dedupe import compute_hash
from app.models import Publication as PublicationORM
from app.models import SeenHash
from app.retention import run_retention

RETENTION_DAYS = 3


def _publicacao_orm(
    *,
    portal_code: str = "TST",
    page_url: str = "https://example.com/publicacao/1",
    published_at: dt.date = dt.date(2026, 8, 1),
    sent_at: dt.datetime | None,
    files: list[dict] | None = None,
) -> PublicationORM:
    return PublicationORM(
        portal_code=portal_code,
        portal_name="Tribunal Superior do Trabalho",
        title="Publicação de teste",
        published_at=published_at,
        page_url=page_url,
        summary=None,
        files=files or [],
        content_hash=compute_hash(portal_code, page_url, published_at),
        sent_at=sent_at,
    )


async def _existe_por_hash(session: AsyncSession, content_hash: str) -> bool:
    result = await session.execute(
        select(PublicationORM).where(PublicationORM.content_hash == content_hash)
    )
    return result.scalar_one_or_none() is not None


async def test_publicacao_com_sent_at_antigo_e_apagada_mas_seen_hash_permanece(db_session) -> None:
    """O teste-chave da fase: publications some, seen_hashes continua lá intacta."""
    sent_at_antigo = dt.datetime.now(dt.UTC) - dt.timedelta(days=RETENTION_DAYS + 1)
    publicacao = _publicacao_orm(
        page_url="https://example.com/publicacao/antiga", sent_at=sent_at_antigo
    )
    content_hash = publicacao.content_hash

    db_session.add(publicacao)
    db_session.add(SeenHash(content_hash=content_hash))
    await db_session.flush()

    assert await _existe_por_hash(db_session, content_hash) is True

    await run_retention(db_session, retention_days=RETENTION_DAYS)

    assert await _existe_por_hash(db_session, content_hash) is False

    seen_hash = await db_session.get(SeenHash, content_hash)
    assert seen_hash is not None, "seen_hashes NUNCA deve ser apagada pelo job de retenção"


async def test_publicacao_com_sent_at_recente_nao_e_apagada(db_session) -> None:
    sent_at_recente = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    publicacao = _publicacao_orm(
        page_url="https://example.com/publicacao/recente", sent_at=sent_at_recente
    )
    content_hash = publicacao.content_hash
    db_session.add(publicacao)
    await db_session.flush()

    await run_retention(db_session, retention_days=RETENTION_DAYS)

    assert await _existe_por_hash(db_session, content_hash) is True


async def test_publicacao_com_sent_at_nulo_nao_e_apagada(db_session) -> None:
    publicacao = _publicacao_orm(
        page_url="https://example.com/publicacao/nunca-enviada", sent_at=None
    )
    content_hash = publicacao.content_hash
    db_session.add(publicacao)
    await db_session.flush()

    await run_retention(db_session, retention_days=RETENTION_DAYS)

    assert await _existe_por_hash(db_session, content_hash) is True


async def test_retencao_apaga_arquivo_fisico_correspondente(db_session, tmp_path) -> None:
    arquivo = tmp_path / "diario.pdf"
    arquivo.write_bytes(b"conteudo de teste")
    assert arquivo.exists()

    sent_at_antigo = dt.datetime.now(dt.UTC) - dt.timedelta(days=RETENTION_DAYS + 1)
    publicacao = _publicacao_orm(
        page_url="https://example.com/publicacao/com-arquivo",
        sent_at=sent_at_antigo,
        files=[{"url": "https://example.com/diario.pdf", "path": str(arquivo), "size_bytes": 18}],
    )
    db_session.add(publicacao)
    await db_session.flush()

    await run_retention(db_session, retention_days=RETENTION_DAYS)

    assert not arquivo.exists()


async def test_retencao_nao_quebra_se_arquivo_ja_nao_existe_em_disco(db_session, tmp_path) -> None:
    arquivo_inexistente = tmp_path / "ja-apagado.pdf"

    sent_at_antigo = dt.datetime.now(dt.UTC) - dt.timedelta(days=RETENTION_DAYS + 1)
    publicacao = _publicacao_orm(
        page_url="https://example.com/publicacao/arquivo-sumido",
        sent_at=sent_at_antigo,
        files=[{"url": "https://example.com/x.pdf", "path": str(arquivo_inexistente)}],
    )
    content_hash = publicacao.content_hash
    db_session.add(publicacao)
    await db_session.flush()

    await run_retention(db_session, retention_days=RETENTION_DAYS)

    assert await _existe_por_hash(db_session, content_hash) is False
