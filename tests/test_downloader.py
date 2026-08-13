"""Testes do downloader (app/downloader.py) — sem rede real.

Usa httpx.MockTransport (recurso nativo do httpx) para simular as
respostas HTTP, seguindo a exigência da Fase 11 do PLANO.md.
"""

import datetime as dt
from pathlib import Path

import httpx
import pytest

from app.downloader import download_publication_files
from app.scrapers.base import Publication


def _publication(file_urls: list[str], portal_code: str = "TCU") -> Publication:
    return Publication(
        portal_code=portal_code,
        portal_name="Tribunal de Contas da União",
        title="Edição de teste",
        published_at=dt.date(2026, 8, 13),
        page_url="https://exemplo.gov.br/edicao/1",
        summary=None,
        file_urls=file_urls,
    )


@pytest.mark.asyncio
async def test_download_success_writes_file_and_records_size(tmp_path: Path) -> None:
    content = b"%PDF-1.4 conteudo fake do arquivo"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"] == "LupaDiarios/1.0"
        return httpx.Response(200, content=content)

    transport = httpx.MockTransport(handler)
    publication = _publication(["https://exemplo.gov.br/arquivos/edicao1.pdf"])

    async with httpx.AsyncClient(transport=transport) as client:
        results = await download_publication_files(publication, base_dir=tmp_path, client=client)

    assert len(results) == 1
    result = results[0]
    assert result["url"] == "https://exemplo.gov.br/arquivos/edicao1.pdf"
    assert result["size_bytes"] == len(content)
    assert result["attached"] is False

    expected_dir = tmp_path / "TCU" / "2026-08-13"
    saved_path = Path(result["path"])
    assert saved_path.parent == expected_dir
    assert saved_path.name == "edicao1.pdf"
    assert saved_path.read_bytes() == content


@pytest.mark.asyncio
async def test_download_multiple_files_keeps_order_and_paths(tmp_path: Path) -> None:
    contents = {
        "https://exemplo.gov.br/a.pdf": b"conteudo-a",
        "https://exemplo.gov.br/b.pdf": b"conteudo-bb",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=contents[str(request.url)])

    transport = httpx.MockTransport(handler)
    publication = _publication(list(contents.keys()))

    async with httpx.AsyncClient(transport=transport) as client:
        results = await download_publication_files(publication, base_dir=tmp_path, client=client)

    assert [r["url"] for r in results] == list(contents.keys())
    assert results[0]["size_bytes"] == len(contents["https://exemplo.gov.br/a.pdf"])
    assert results[1]["size_bytes"] == len(contents["https://exemplo.gov.br/b.pdf"])


@pytest.mark.asyncio
async def test_no_file_urls_returns_empty_list(tmp_path: Path) -> None:
    publication = _publication([])

    results = await download_publication_files(publication, base_dir=tmp_path)

    assert results == []


@pytest.mark.asyncio
async def test_network_failure_triggers_retry_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []

    async def fast_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.downloader.asyncio.sleep", fast_sleep)

    attempts = {"count": 0}
    content = b"conteudo-final"

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise httpx.ConnectError("falha simulada de rede", request=request)
        return httpx.Response(200, content=content)

    transport = httpx.MockTransport(handler)
    publication = _publication(["https://exemplo.gov.br/instavel.pdf"])

    async with httpx.AsyncClient(transport=transport) as client:
        results = await download_publication_files(publication, base_dir=tmp_path, client=client)

    assert attempts["count"] == 3
    assert results[0]["size_bytes"] == len(content)
    assert sleeps == [1, 2]


@pytest.mark.asyncio
async def test_persistent_failure_propagates_after_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fast_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("app.downloader.asyncio.sleep", fast_sleep)

    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ConnectError("falha simulada de rede", request=request)

    transport = httpx.MockTransport(handler)
    publication = _publication(["https://exemplo.gov.br/indisponivel.pdf"])

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ConnectError):
            await download_publication_files(publication, base_dir=tmp_path, client=client)

    assert attempts["count"] == 3
    # Nenhum arquivo parcial deve sobrar no disco após falha definitiva.
    assert list((tmp_path / "TCU" / "2026-08-13").glob("*")) == []


@pytest.mark.asyncio
async def test_duplicate_filenames_do_not_overwrite_each_other(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=str(request.url).encode())

    transport = httpx.MockTransport(handler)
    publication = _publication(
        [
            "https://exemplo.gov.br/pasta1/edicao.pdf",
            "https://exemplo.gov.br/pasta2/edicao.pdf",
        ]
    )

    async with httpx.AsyncClient(transport=transport) as client:
        results = await download_publication_files(publication, base_dir=tmp_path, client=client)

    paths = {Path(r["path"]) for r in results}
    assert len(paths) == 2
    for r in results:
        assert Path(r["path"]).read_bytes() == r["url"].encode()
