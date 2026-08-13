"""Downloader de arquivos vinculados às publicações (ver PLANO.md Fase 11).

Baixa cada `file_url` de uma `Publication` (modelo intermediário de
`app/scrapers/base.py`) para `data/files/{portal_code}/{published_at}/`,
com o mesmo padrão de timeout/retry/User-Agent já usado nos adapters
(ver `app/scrapers/tst_juslaboris.py`).

Esta função NÃO decide se o arquivo será anexado ao e-mail — isso é regra
do mailer (Fase 12). Aqui `attached` fica sempre com o valor padrão
`False`, placeholder até o mailer decidir.
"""

import asyncio
import logging
from pathlib import Path

import httpx

from app.scrapers.base import Publication

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
USER_AGENT = "LupaDiarios/1.0"
MAX_RETRIES = 3

DEFAULT_FILES_DIR = Path("data/files")


async def _download_one(client: httpx.AsyncClient, url: str, dest_dir: Path) -> dict:
    """Baixa um único arquivo para `dest_dir`, com retry 3x e backoff exponencial.

    Retorna `{url, path, size_bytes, attached}` no formato do campo `files`
    (jsonb) de `app/models.py`.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = url.rsplit("/", 1)[-1] or "arquivo"
    dest_path = dest_dir / filename
    if dest_path.exists():
        # Evita sobrescrever um arquivo já baixado nesta pasta (ex.: duas
        # publicações do mesmo dia linkando para nomes de arquivo iguais).
        stem, _, suffix = filename.partition(".")
        suffix = f".{suffix}" if suffix else ""
        counter = 2
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}-{counter}{suffix}"
            counter += 1

    headers = {"User-Agent": USER_AGENT}
    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            dest_path.write_bytes(response.content)
            return {
                "url": url,
                "path": str(dest_path),
                "size_bytes": dest_path.stat().st_size,
                "attached": False,
            }
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning(
                "Downloader: tentativa %d/%d falhou ao baixar %s: %s",
                attempt,
                MAX_RETRIES,
                url,
                exc,
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2 ** (attempt - 1))

    assert last_exc is not None
    raise last_exc


async def download_publication_files(
    publication: Publication,
    base_dir: Path = DEFAULT_FILES_DIR,
    client: httpx.AsyncClient | None = None,
) -> list[dict]:
    """Baixa todos os `file_urls` de uma publicação.

    Salva em `{base_dir}/{portal_code}/{published_at}/` e retorna a lista
    de metadados (`{url, path, size_bytes, attached}`) na mesma ordem de
    `publication.file_urls`. Um `client` pode ser injetado (usado nos
    testes com `httpx.MockTransport`); por padrão um novo client real é
    criado e fechado ao final.
    """
    if not publication.file_urls:
        return []

    dest_dir = base_dir / publication.portal_code / publication.published_at.isoformat()

    if client is not None:
        return [await _download_one(client, url, dest_dir) for url in publication.file_urls]

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=True) as owned_client:
        return [await _download_one(owned_client, url, dest_dir) for url in publication.file_urls]
