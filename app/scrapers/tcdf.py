"""Adapter do portal TCDF — API JSON escondida (ver PLANO.md Fase 9).

Investigação com `scripts/inspect.py`: `doe.tc.df.gov.br` é de fato uma SPA
(Vue/Vite) sem HTML renderizado no servidor — confirma a suspeita do
planejador, então a hipótese de URL previsível `/O/{ano}/{edicao}` do
SPEC.md não podia ser validada direto (aquela URL só existe como rota do
Vue Router, sem conteúdo sem JS). Só que, um degrau acima na hierarquia de
CLAUDE.md, o bundle JS da SPA (`assets/VMain-*.js`) expõe uma API JSON
pública e sem autenticação em `https://api-doe.tc.df.gov.br/api/publico`
(estilo API Platform/Hydra):

- `GET /diarios?situacao=P&order[dataPublicacao]=desc` — lista as edições
  publicadas, mais recente primeiro (paginação default de 30 itens,
  confirmado batendo na API real).
- `GET /diarios/{id}/json` — detalhe de uma edição: `link` (URL humana,
  ex. `https://doe.tc.df.gov.br/O/2026/105`) e uma árvore de `secoes`
  (cada uma com sub-`secoes` e uma lista `publicacoes`, cada publicação já
  com `titulo`, `subtitulo`, `texto` em HTML e `slug`).

Ou seja, cada publicação individual já vem com o texto integral — mesmo
padrão do adapter `comunica_pje`: usamos selectolax só para extrair texto
plano de `texto` (sem requisição adicional) e `file_urls` fica vazio,
porque não há anexo público por publicação (`anexos` sempre veio vazio nas
edições inspecionadas) e o PDF completo da edição
(`/api/diarios/pdf/download/{id}`, visto no bundle) responde 401 "JWT
Token not found" sem autenticação — não existe download público de
arquivo para essa API, só o texto.

O campo `dataPublicacao` do endpoint de listagem vem como datetime ISO
(`2026-08-13T01:01:18-03:00`), mas o mesmo campo no endpoint de detalhe
vem como texto humano (`"QUINTA-FEIRA, 13 DE AGOSTO DE 2026"`) — por isso
a data de publicação é sempre lida da listagem, nunca do detalhe.

A `page_url` de cada publicação é montada como `{link da edição}/{slug}`,
espelhando a rota `DiarioPublicacao` do Vue Router
(`/:edicao(O|E)/:ano/:numero/:slug`) — não renderiza sem JS, mas é a URL
estável e específica daquela publicação (mesma lógica do TCU: preferir o
identificador mais específico disponível).

Minimalismo de requests (CLAUDE.md): o filtro por data
(`dataPublicacao[after]`/`[before]`) da API se mostrou pouco confiável no
teste manual (não bateu com o formato de datetime armazenado), então o
adapter busca só a primeira página da listagem (mais recentes primeiro) e
processa apenas a edição mais recente — 2 requests por ciclo (listagem +
detalhe), o dedupe da Fase 5 cuida do resto.
"""

import asyncio
import datetime as dt
import json
import logging
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from app.scrapers.base import BaseScraper, Publication

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api-doe.tc.df.gov.br/api/publico"
LISTAGEM_URL = f"{API_BASE_URL}/diarios"
DETALHE_URL_TEMPLATE = f"{API_BASE_URL}/diarios/{{id}}/json"

TIMEOUT_SECONDS = 30
USER_AGENT = "LupaDiarios/1.0"
MAX_RETRIES = 3


class TcdfScraper(BaseScraper):
    """Coleta publicações da edição mais recente do Diário do TCDF."""

    def __init__(
        self,
        url: str,
        portal_code: str = "TCDF",
        portal_name: str = "Diário do TCDF",
    ) -> None:
        self.url = url
        self.portal_code = portal_code
        self.portal_name = portal_name

    async def fetch(self) -> list[Publication]:
        """Busca a edição mais recente do TCDF e retorna suas publicações."""
        listagem_json = await self._fetch_json(
            LISTAGEM_URL, params={"situacao": "P", "order[dataPublicacao]": "desc"}
        )
        latest = self._parse_listing(listagem_json)
        if latest is None:
            logger.warning("TCDF: nenhuma edição publicada encontrada na listagem")
            return []

        detalhe_json = await self._fetch_json(DETALHE_URL_TEMPLATE.format(id=latest["id"]))
        return self._parse_detail(detalhe_json, published_at=latest["published_at"])

    async def _fetch_json(self, url: str, params: dict[str, str] | None = None) -> str:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/ld+json"}
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=TIMEOUT_SECONDS, headers=headers, follow_redirects=True
                ) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    return response.text
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "TCDF: tentativa %d/%d falhou ao buscar %s: %s",
                    attempt,
                    MAX_RETRIES,
                    url,
                    exc,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2 ** (attempt - 1))

        assert last_exc is not None
        raise last_exc

    def _parse_listing(self, json_text: str) -> dict[str, Any] | None:
        """Extrai a edição mais recente da resposta de listagem (usado direto nos testes)."""
        data = json.loads(json_text)
        members = data.get("member", [])
        if not members:
            return None

        latest = members[0]
        diario_id = latest.get("id")
        data_publicacao = latest.get("dataPublicacao")
        if not diario_id or not data_publicacao:
            logger.warning("TCDF: edição mais recente sem id ou dataPublicacao, ignorada")
            return None

        try:
            published_at = dt.datetime.fromisoformat(data_publicacao).date()
        except ValueError:
            logger.warning("TCDF: dataPublicacao inválida na listagem: %s", data_publicacao)
            return None

        return {"id": diario_id, "published_at": published_at}

    def _parse_detail(self, json_text: str, published_at: dt.date) -> list[Publication]:
        """Extrai as publicações de uma edição já baixada (usado direto nos testes)."""
        data = json.loads(json_text)
        members = data.get("member", [])
        if not members:
            logger.warning("TCDF: detalhe da edição sem member, ignorado")
            return []

        diario = members[0]
        link = diario.get("link")
        if not link:
            logger.warning("TCDF: edição sem link, ignorada (id=%s)", diario.get("id"))
            return []

        publications: list[Publication] = []
        for secao in diario.get("secoes", {}).values():
            self._collect_from_section(secao, link, published_at, publications)
        return publications

    def _collect_from_section(
        self,
        secao: dict[str, Any],
        link: str,
        published_at: dt.date,
        publications: list[Publication],
    ) -> None:
        for item in secao.get("publicacoes", []):
            titulo = (item.get("titulo") or "").strip()
            slug = item.get("slug")
            if not titulo or not slug:
                logger.warning(
                    "TCDF: publicação sem título ou slug, ignorada (id=%s)", item.get("id")
                )
                continue

            summary = None
            texto_html = item.get("texto")
            if texto_html:
                summary = HTMLParser(texto_html).text(separator=" ", strip=True) or None

            publications.append(
                Publication(
                    portal_code=self.portal_code,
                    portal_name=self.portal_name,
                    title=titulo,
                    published_at=published_at,
                    page_url=f"{link}/{slug}",
                    summary=summary,
                    file_urls=[],
                )
            )

        sub_secoes = secao.get("secoes")
        if isinstance(sub_secoes, dict):
            for sub in sub_secoes.values():
                self._collect_from_section(sub, link, published_at, publications)
        elif isinstance(sub_secoes, list):
            for sub in sub_secoes:
                self._collect_from_section(sub, link, published_at, publications)
