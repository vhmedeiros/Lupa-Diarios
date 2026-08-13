"""Adapter do portal TST — feed Atom do JusLaboris (ver PLANO.md Fase 6).

Estratégia de maior preferência confirmada com `scripts/inspect.py`: feed
Atom público (`https://juslaboris.tst.jus.br/feed/atom_1.0/site`), sem JS
nem autenticação — parse com `xml.etree.ElementTree` (biblioteca padrão).

Cada `<entry>` do feed linka para uma página de detalhe (hdl.handle.net)
que não é raspada nesta fase: o XML não traz resumo/corpo nem arquivo
anexado diretamente, então `summary` e `file_urls` ficam vazios/None.
"""

import asyncio
import datetime as dt
import logging
import xml.etree.ElementTree as ET

import httpx

from app.scrapers.base import BaseScraper, Publication

logger = logging.getLogger(__name__)

ATOM_NS = "http://www.w3.org/2005/Atom"
DC_NS = "http://purl.org/dc/elements/1.1/"

TIMEOUT_SECONDS = 30
USER_AGENT = "LupaDiarios/1.0"
MAX_RETRIES = 3


class TstJuslaborisScraper(BaseScraper):
    """Coleta publicações do feed Atom do JusLaboris (TST)."""

    def __init__(
        self,
        url: str,
        portal_code: str = "TST",
        portal_name: str = "Diário do TST (JusLaboris)",
    ) -> None:
        self.url = url
        self.portal_code = portal_code
        self.portal_name = portal_name

    async def fetch(self) -> list[Publication]:
        """Baixa o feed Atom e retorna as publicações encontradas."""
        xml_text = await self._fetch_feed()
        return self._parse(xml_text)

    async def _fetch_feed(self) -> str:
        headers = {"User-Agent": USER_AGENT}
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=TIMEOUT_SECONDS, headers=headers, follow_redirects=True
                ) as client:
                    response = await client.get(self.url)
                    response.raise_for_status()
                    return response.text
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "TST: tentativa %d/%d falhou ao buscar %s: %s",
                    attempt,
                    MAX_RETRIES,
                    self.url,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))

        assert last_exc is not None
        raise last_exc

    def _parse(self, xml_text: str) -> list[Publication]:
        """Extrai as publicações de um feed Atom já baixado (usado direto nos testes)."""
        root = ET.fromstring(xml_text)  # noqa: S314 - feed confiável do TST, sem entrada externa
        publications: list[Publication] = []

        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            title_el = entry.find(f"{{{ATOM_NS}}}title")
            link_el = entry.find(f"{{{ATOM_NS}}}link")
            published_el = entry.find(f"{{{ATOM_NS}}}published")
            dc_date_el = entry.find(f"{{{DC_NS}}}date")

            title = (title_el.text or "").strip() if title_el is not None else ""
            page_url = link_el.get("href", "") if link_el is not None else ""

            date_text = None
            if published_el is not None and published_el.text:
                date_text = published_el.text
            elif dc_date_el is not None and dc_date_el.text:
                date_text = dc_date_el.text

            if not title or not page_url or not date_text:
                logger.warning("TST: entrada do feed incompleta, ignorada (%s)", title or page_url)
                continue

            published_at = dt.datetime.fromisoformat(date_text.replace("Z", "+00:00")).date()

            publications.append(
                Publication(
                    portal_code=self.portal_code,
                    portal_name=self.portal_name,
                    title=title,
                    published_at=published_at,
                    page_url=page_url,
                    summary=None,
                    file_urls=[],
                )
            )

        return publications
