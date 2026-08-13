"""Dedupe de publicações via seen_hashes (ver PLANO.md fase 5).

content_hash = sha256(portal_code + page_url + published_at ISO), conforme
SPEC.md §4. `filter_new` consulta `seen_hashes`, grava as publicações
novas em `seen_hashes` e `publications`, e retorna somente as que eram
novas — quem já existia é descartado (não reenviado).
"""

import datetime as dt
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Publication as PublicationORM
from app.models import SeenHash
from app.scrapers.base import Publication


def compute_hash(portal_code: str, page_url: str, published_at: dt.date) -> str:
    """Hash determinístico de dedupe de uma publicação."""
    raw = f"{portal_code}{page_url}{published_at.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def filter_new(session: AsyncSession, publications: list[Publication]) -> list[Publication]:
    """Filtra publicações ainda não vistas, gravando-as em seen_hashes e publications."""
    new_publications: list[Publication] = []

    for pub in publications:
        content_hash = compute_hash(pub.portal_code, pub.page_url, pub.published_at)
        seen = await session.get(SeenHash, content_hash)
        if seen is not None:
            continue

        session.add(SeenHash(content_hash=content_hash))
        session.add(
            PublicationORM(
                portal_code=pub.portal_code,
                portal_name=pub.portal_name,
                title=pub.title,
                published_at=pub.published_at,
                page_url=pub.page_url,
                summary=pub.summary,
                content_hash=content_hash,
            )
        )
        new_publications.append(pub)

    await session.flush()
    return new_publications
