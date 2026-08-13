"""Pipeline completo de coleta (ver PLANO.md Fase 14 / SPEC.md §11 R4, R5).

Por ciclo, para cada portal (todos os habilitados, ou um único, quando
`portal_code` é informado a `run_cycle`): `fetch()` -> dedupe
(`app.dedupe.filter_new`, que já grava as publicações novas em
`seen_hashes` e `publications`) -> download dos arquivos vinculados
(`app.downloader.download_publication_files`), gravado no campo `files`
de cada linha.

Erro em qualquer etapa de um portal é capturado e logado — os demais
portais do ciclo seguem normalmente (R4). Se ao final do ciclo houver ao
menos uma publicação nova (em qualquer portal), monta-se UM e-mail
agrupado (`app.mailer.build_email`) e ele é enviado de verdade
(`app.mailer.send_email`); as publicações que entraram nesse e-mail têm
`sent_at` gravado. Se nenhum portal trouxe publicação nova, nenhum
e-mail é montado nem enviado (R5).

`run_cycle` recebe a sessão já aberta (mesmo padrão de
`app.dedupe.filter_new`) e NÃO comita — quem chama (`app.cli` ou
`app.routers`) decide quando comitar, o que também permite aos testes
rodarem dentro de uma transação revertida ao final (ver
tests/conftest.py).
"""

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dedupe import compute_hash, filter_new
from app.downloader import download_publication_files
from app.mailer import build_email, send_email
from app.models import Publication as PublicationORM
from app.registry import Portal, get_enabled_portals, load_portals
from app.scrapers.base import BaseScraper
from app.scrapers.base import Publication as ScrapedPublication
from app.scrapers.comunica_pje import ComunicaPjeScraper
from app.scrapers.tcdf import TcdfScraper
from app.scrapers.tcu import TcuScraper
from app.scrapers.tst_juslaboris import TstJuslaborisScraper

logger = logging.getLogger(__name__)

# Mapeia o campo `adapter` de portals.yaml para a classe do scraper. Só os
# adapters já implementados entram aqui (ver PLANO.md, uma fase por portal).
ADAPTERS: dict[str, type[BaseScraper]] = {
    "juslaboris_feed": TstJuslaborisScraper,
    "comunica_pje": ComunicaPjeScraper,
    "tcu": TcuScraper,
    "tcdf": TcdfScraper,
}


def find_portal(portal_code: str) -> Portal:
    """Resolve um portal pelo código, entre TODOS os portais (habilitados ou não)."""
    portals = {p.code: p for p in load_portals()}
    portal = portals.get(portal_code)
    if portal is None:
        raise ValueError(f"portal '{portal_code}' não encontrado em portals.yaml")
    return portal


def build_scraper(portal: Portal) -> BaseScraper:
    """Instancia o adapter correspondente a `portal.adapter`."""
    adapter_cls = ADAPTERS.get(portal.adapter)
    if adapter_cls is None:
        raise ValueError(
            f"adapter '{portal.adapter}' do portal {portal.code} ainda não foi implementado"
        )
    kwargs = {"url": portal.url, "portal_code": portal.code, "portal_name": portal.name}
    if portal.params:
        kwargs["params"] = portal.params
    return adapter_cls(**kwargs)


async def _fetch_new_rows(
    session: AsyncSession, new_scraped: list[ScrapedPublication]
) -> list[PublicationORM]:
    """Recupera as linhas ORM das publicações que `filter_new` acabou de gravar.

    `filter_new` grava as publicações novas via `session.add` + `flush`, mas
    devolve o modelo intermediário (`app.scrapers.base.Publication`), não o
    ORM. Recuperamos as linhas pelo mesmo hash de dedupe, na mesma ordem,
    para poder gravar `files` e `sent_at` nelas a seguir.
    """
    hashes = [compute_hash(p.portal_code, p.page_url, p.published_at) for p in new_scraped]
    result = await session.execute(
        select(PublicationORM).where(PublicationORM.content_hash.in_(hashes))
    )
    by_hash = {row.content_hash: row for row in result.scalars()}
    return [by_hash[h] for h in hashes]


async def run_cycle(session: AsyncSession, portal_code: str | None = None) -> int:
    """Executa um ciclo completo de coleta.

    Se `portal_code` for informado, roda apenas esse portal; caso
    contrário, roda todos os portais habilitados em portals.yaml. Retorna
    o número de publicações novas enviadas por e-mail neste ciclo (0 se
    nenhuma novidade — nenhum e-mail é enviado nesse caso, R5). Não comita
    a sessão — isso é responsabilidade de quem chama.
    """
    portals = [find_portal(portal_code)] if portal_code is not None else get_enabled_portals()

    new_rows: list[PublicationORM] = []

    for portal in portals:
        try:
            scraper = build_scraper(portal)
            scraped = await scraper.fetch()
            new_scraped = await filter_new(session, scraped)
            if not new_scraped:
                continue

            rows = await _fetch_new_rows(session, new_scraped)
            for scraped_pub, row in zip(new_scraped, rows, strict=True):
                row.files = await download_publication_files(scraped_pub)

            new_rows.extend(rows)
        except Exception:
            # R4: erro em um portal não derruba os demais — loga e segue.
            logger.exception(
                "Falha ao processar o portal %s neste ciclo — seguindo para os demais",
                portal.code,
            )

    if not new_rows:
        logger.info("Nenhuma publicação nova neste ciclo — nenhum e-mail enviado")
        return 0

    subject, html_body, attachments = build_email(new_rows)
    await send_email(subject, html_body, attachments)

    sent_at = dt.datetime.now(dt.UTC)
    for row in new_rows:
        row.sent_at = sent_at

    logger.info("%d publicações novas enviadas por e-mail neste ciclo", len(new_rows))
    return len(new_rows)
