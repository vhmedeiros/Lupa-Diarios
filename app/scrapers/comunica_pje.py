"""Adapter comunica_pje — API JSON do DJEN (ver PLANO.md Fase 7 / SPEC.md §10).

Estratégia de maior preferência confirmada com `scripts/inspect.py`: a
Central Nacional de Comunicações Processuais (comunica.pje.jus.br) é um
front Angular sem HTML renderizado no servidor, mas ele consome uma API
JSON pública e sem autenticação em
`https://comunicaapi.pje.jus.br/api/v1/comunicacao`, aceitando os filtros
`siglaTribunal`, `dataDisponibilizacaoInicio`/`dataDisponibilizacaoFim` e
paginação via `pagina`/`itensPorPagina` (confirmado testando as
variações contra a API real — inclusive que `itensPorPagina` tem teto de
1000 itens por página e que `pagina` avança corretamente sem repetir
registros).

Cada item já traz o texto integral da comunicação em HTML no campo
`texto` — usamos selectolax só para extrair o texto plano dele, sem
requisição adicional. O campo `link` da API aponta para um documento
protegido (retorna 401 sem autenticação), então, seguindo a orientação
do plano, `file_urls` fica vazio em vez de inventar um passo de
scraping/autenticação extra. Como o front não tem página de detalhe
renderizada no servidor, `page_url` usa o endpoint de detalhe da própria
API por `hash` (também público, também confirmado com `scripts/inspect.py`)
— é o link estável e navegável mais próximo de uma "página" que a API
oferece para aquela comunicação específica.

A API responde com o header `x-ratelimit-limit: 20` (confirmado batendo
nela repetidamente durante a inspeção, o que gerou um 429 real) — ou
seja, tem um limite estrito de requisições por janela. Por isso
`ITEMS_PER_PAGE` usa o teto de itens por página que a própria API aceita
(1000, também confirmado no inspect), minimizando o número de páginas
necessárias, e o laço de paginação espera `PAGE_DELAY_SECONDS` entre
páginas — respeita CLAUDE.md ("nunca fazer scraping agressivo: mínimo de
requests, respeitar o site").

O adapter é parametrizado por `params.sigla_tribunal` (ver portals.yaml),
não hardcoded para STJ, mesmo que hoje só o portal STJDJN o utilize.
"""

import asyncio
import datetime as dt
import json
import logging
from zoneinfo import ZoneInfo

import httpx
from selectolax.parser import HTMLParser

from app.scrapers.base import BaseScraper, Publication

logger = logging.getLogger(__name__)

API_URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
DETAIL_URL_TEMPLATE = "https://comunicaapi.pje.jus.br/api/v1/comunicacao/{hash}"

TIMEOUT_SECONDS = 30
USER_AGENT = "LupaDiarios/1.0"
MAX_RETRIES = 3
# Teto de itens por página aceito pela própria API (confirmado no inspect);
# usar o máximo minimiza o número de requisições feitas por ciclo.
ITEMS_PER_PAGE = 1000
# Teto de segurança para não entrar em loop de paginação indefinido caso a
# API se comporte de forma inesperada.
MAX_PAGES = 10
# Pausa entre páginas para não estourar o rate limit da API (x-ratelimit-limit:
# 20/janela, confirmado no inspect); 5s é uma folga maior que os 3s originais
# porque, na prática, o volume diário do STJ (~13 mil comunicações) já exige
# várias páginas, e um 429 real durante o dry-run mostrou que 3s não bastava.
PAGE_DELAY_SECONDS = 5
# Fallback de espera para 429 sem header Retry-After: mais longo que o backoff
# exponencial normal (1s/2s/4s) porque um 429 significa que a janela de rate
# limit da API já estourou, não é um erro transitório comum.
RATE_LIMIT_FALLBACK_SECONDS = 10


class ComunicaPjeScraper(BaseScraper):
    """Coleta comunicações do DJEN (Comunica PJe) via API JSON, por tribunal."""

    def __init__(
        self,
        url: str,
        portal_code: str,
        portal_name: str,
        params: dict,
    ) -> None:
        self.url = url
        self.portal_code = portal_code
        self.portal_name = portal_name

        sigla_tribunal = params.get("sigla_tribunal")
        if not sigla_tribunal:
            raise ValueError(
                f"comunica_pje: portal {portal_code} precisa de params.sigla_tribunal "
                "em portals.yaml"
            )
        self.sigla_tribunal = sigla_tribunal

    async def fetch(self) -> list[Publication]:
        """Busca todas as páginas de comunicações do dia corrente e retorna as publicações."""
        today = dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()

        publications: list[Publication] = []
        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                await asyncio.sleep(PAGE_DELAY_SECONDS)

            json_text = await self._fetch_page(today, page)
            page_publications = self._parse(json_text)
            publications.extend(page_publications)

            if len(page_publications) < ITEMS_PER_PAGE:
                break

        return publications

    async def _fetch_page(self, date: dt.date, page: int) -> str:
        params = {
            "siglaTribunal": self.sigla_tribunal,
            "dataDisponibilizacaoInicio": date.isoformat(),
            "dataDisponibilizacaoFim": date.isoformat(),
            "itensPorPagina": ITEMS_PER_PAGE,
            "pagina": page,
        }
        headers = {"User-Agent": USER_AGENT}
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=TIMEOUT_SECONDS, headers=headers, follow_redirects=True
                ) as client:
                    response = await client.get(API_URL, params=params)
                    response.raise_for_status()
                    return response.text
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 429:
                    wait_seconds = self._retry_after_seconds(exc.response)
                    logger.warning(
                        "comunica_pje (%s): rate limit (429) na página %d, "
                        "tentativa %d/%d — aguardando %ds antes de tentar de novo",
                        self.sigla_tribunal,
                        page,
                        attempt,
                        MAX_RETRIES,
                        wait_seconds,
                    )
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(wait_seconds)
                    continue

                logger.warning(
                    "comunica_pje (%s): tentativa %d/%d falhou na página %d: %s",
                    self.sigla_tribunal,
                    attempt,
                    MAX_RETRIES,
                    page,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "comunica_pje (%s): tentativa %d/%d falhou na página %d: %s",
                    self.sigla_tribunal,
                    attempt,
                    MAX_RETRIES,
                    page,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))

        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> int:
        """Lê o header Retry-After da resposta 429; usa um fallback se ausente/inválido."""
        retry_after = response.headers.get("retry-after")
        if retry_after is not None:
            try:
                seconds = int(float(retry_after))
                if seconds > 0:
                    return seconds
            except ValueError:
                pass
        return RATE_LIMIT_FALLBACK_SECONDS

    def _parse(self, json_text: str) -> list[Publication]:
        """Extrai as publicações de uma página de resposta da API já baixada
        (usado direto nos testes)."""
        data = json.loads(json_text)
        publications: list[Publication] = []

        for item in data.get("items", []):
            data_disponibilizacao = item.get("data_disponibilizacao")
            item_hash = item.get("hash")
            tipo_comunicacao = item.get("tipoComunicacao", "")
            numero_processo = item.get("numeroprocessocommascara", "")
            nome_classe = item.get("nomeClasse", "")

            if not data_disponibilizacao or not item_hash:
                logger.warning(
                    "comunica_pje (%s): item sem data ou hash, ignorado (id=%s)",
                    self.sigla_tribunal,
                    item.get("id"),
                )
                continue

            published_at = dt.date.fromisoformat(data_disponibilizacao)
            title_parts = [
                part for part in (tipo_comunicacao, numero_processo, nome_classe) if part
            ]
            title = " - ".join(title_parts) or f"Comunicação {item_hash}"

            summary = None
            texto_html = item.get("texto")
            if texto_html:
                summary = HTMLParser(texto_html).text(separator=" ", strip=True) or None

            publications.append(
                Publication(
                    portal_code=self.portal_code,
                    portal_name=self.portal_name,
                    title=title,
                    published_at=published_at,
                    page_url=DETAIL_URL_TEMPLATE.format(hash=item_hash),
                    summary=summary,
                    file_urls=[],
                )
            )

        return publications
