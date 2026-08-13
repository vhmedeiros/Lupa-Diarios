"""Modelos ORM: Publication e SeenHash (ver PLANO.md secao 2)."""

import datetime as dt

from sqlalchemy import Date, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Publication(Base):
    """Publicação coletada de um portal — buffer operacional (não histórico)."""

    __tablename__ = "publications"

    id: Mapped[int] = mapped_column(primary_key=True)
    portal_code: Mapped[str]
    portal_name: Mapped[str]
    title: Mapped[str]
    published_at: Mapped[dt.date] = mapped_column(Date)
    page_url: Mapped[str]
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    files: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    content_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_publications_portal_code_published_at", "portal_code", "published_at"),
        Index("ix_publications_sent_at", "sent_at"),
    )


class SeenHash(Base):
    """Memória de dedupe — nunca apagada pelo job de retenção."""

    __tablename__ = "seen_hashes"

    content_hash: Mapped[str] = mapped_column(primary_key=True)
    first_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
