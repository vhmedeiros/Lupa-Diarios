"""Modelo intermediário do scraper e contrato BaseScraper (ver PLANO.md fase 5).

`Publication` aqui é um modelo Pydantic — a saída de `BaseScraper.fetch()`,
antes de virar linha do banco. Não confundir com `app.models.Publication`
(ORM/SQLAlchemy, ver app/models.py): são propositalmente dois modelos com
o mesmo nome em módulos diferentes; quem precisar dos dois num mesmo
arquivo deve importar com alias (ex.: `from app.models import Publication
as PublicationORM`).
"""

import datetime as dt
from abc import ABC, abstractmethod

from pydantic import BaseModel


class Publication(BaseModel):
    """Publicação coletada de um portal, antes do dedupe e da gravação."""

    portal_code: str
    portal_name: str
    title: str
    published_at: dt.date
    page_url: str
    summary: str | None = None
    file_urls: list[str] = []


class BaseScraper(ABC):
    """Contrato que todo adapter de portal deve implementar."""

    @abstractmethod
    async def fetch(self) -> list[Publication]:
        """Coleta as publicações disponíveis no portal."""
        raise NotImplementedError
