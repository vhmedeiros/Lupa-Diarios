"""Adapter do portal TCU — HTML estático via SSR (ver PLANO.md Fase 8).

Investigação com `scripts/inspect.py`: não existe API JSON de listagem em
`btcu.apps.tcu.gov.br` — o único endpoint desse domínio é
`/api/obterDocumentoPdf/{id}`, que é só o download do PDF de uma edição
específica, sem parâmetro de data/paginação (confirmado batendo nele
manualmente). Só é possível chegar a um `id` de edição olhando a página de
listagem.

Só que a própria página de listagem, `https://portal.tcu.gov.br/btcu`
(a URL que já está em `portals.yaml`), é renderizada no servidor (Next.js
SSR): um `GET` simples com `httpx`, sem executar JS, já devolve uma
`<table>` completa com as edições mais recentes do boletim — colunas
Caderno, Edição Nº (com o link do PDF), Data de Publicação e Assunto,
ordenadas da mais recente para a mais antiga. Ou seja, cai um degrau
abaixo de API/feed na hierarquia de `CLAUDE.md`, mas ainda em "HTML
estático" (httpx + selectolax) — não precisa de Playwright. Por isso
`portals.yaml` foi atualizado nesta fase de `engine: playwright` para
`engine: http` (mudança prevista e autorizada pelo próprio PLANO.md,
Fase 8, condicionada à confirmação de uma estratégia funcional via httpx
puro).

Cada edição não tem página de detalhe própria (só o PDF), então
`page_url` usa o link do PDF — é o único URL estável e específico daquela
edição; o URL do portal em si é genérico e igual para todas as linhas da
tabela.
"""

import asyncio
import datetime as dt
import logging

import httpx
from selectolax.parser import HTMLParser

from app.scrapers.base import BaseScraper, Publication

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
USER_AGENT = "LupaDiarios/1.0"
MAX_RETRIES = 3


class TcuScraper(BaseScraper):
    """Coleta edições do Boletim do TCU a partir da tabela SSR de portal.tcu.gov.br/btcu."""

    def __init__(
        self,
        url: str,
        portal_code: str = "TCU",
        portal_name: str = "Diário do TCU",
    ) -> None:
        self.url = url
        self.portal_code = portal_code
        self.portal_name = portal_name

    async def fetch(self) -> list[Publication]:
        """Baixa a página do BTCU e retorna as publicações encontradas na tabela."""
        html_text = await self._fetch_page()
        return self._parse(html_text)

    async def _fetch_page(self) -> str:
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
                    "TCU: tentativa %d/%d falhou ao buscar %s: %s",
                    attempt,
                    MAX_RETRIES,
                    self.url,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))

        assert last_exc is not None
        raise last_exc

    def _parse(self, html_text: str) -> list[Publication]:
        """Extrai as publicações da tabela do BTCU já baixada (usado direto nos testes)."""
        tree = HTMLParser(html_text)
        table = tree.css_first("table")
        publications: list[Publication] = []

        if table is None:
            logger.warning("TCU: tabela de edições não encontrada na página")
            return publications

        for row in table.css("tbody tr"):
            cells = row.css("td")
            if len(cells) < 4:
                logger.warning("TCU: linha da tabela com colunas inesperadas, ignorada")
                continue

            caderno = cells[0].text(strip=True)
            link_el = cells[1].css_first("a")
            edicao = link_el.text(strip=True) if link_el is not None else cells[1].text(strip=True)
            pdf_url = link_el.attributes.get("href") if link_el is not None else None
            data_publicacao = cells[2].text(strip=True)
            assunto = cells[3].text(strip=True)

            if not edicao or not pdf_url or not data_publicacao:
                logger.warning("TCU: linha sem edição, PDF ou data, ignorada (caderno=%s)", caderno)
                continue

            try:
                published_at = dt.datetime.strptime(data_publicacao, "%d/%m/%Y").date()
            except ValueError:
                logger.warning("TCU: data de publicação inválida, ignorada: %s", data_publicacao)
                continue

            title_parts = [part for part in (caderno, f"Edição {edicao}") if part]
            title = " - ".join(title_parts)

            publications.append(
                Publication(
                    portal_code=self.portal_code,
                    portal_name=self.portal_name,
                    title=title,
                    published_at=published_at,
                    page_url=pdf_url,
                    summary=assunto or None,
                    file_urls=[pdf_url],
                )
            )

        return publications
