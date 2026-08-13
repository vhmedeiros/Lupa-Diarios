"""CLI operacional do Lupa Diários (ver PLANO.md Fase 6 / SPEC.md §8).

Uso:
    uv run python -m app.cli run --portal CODE --dry-run

Nesta fase, somente `--dry-run` está implementado: resolve o adapter do
portal pelo registry, chama `fetch()` e imprime as publicações — sem
gravar no banco, sem baixar arquivo e sem enviar e-mail (isso é de fases
futuras do PLANO.md).
"""

import argparse
import asyncio
import logging

from app.registry import Portal, load_portals
from app.scrapers.base import BaseScraper, Publication
from app.scrapers.comunica_pje import ComunicaPjeScraper
from app.scrapers.tcu import TcuScraper
from app.scrapers.tst_juslaboris import TstJuslaborisScraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mapeia o campo `adapter` de portals.yaml para a classe do scraper.
# Só os adapters já implementados entram aqui (ver PLANO.md, uma fase por portal).
ADAPTERS: dict[str, type[BaseScraper]] = {
    "juslaboris_feed": TstJuslaborisScraper,
    "comunica_pje": ComunicaPjeScraper,
    "tcu": TcuScraper,
}


def _find_portal(portal_code: str) -> Portal:
    portals = {p.code: p for p in load_portals()}
    portal = portals.get(portal_code)
    if portal is None:
        raise SystemExit(f"portal '{portal_code}' não encontrado em portals.yaml")
    return portal


def _build_scraper(portal: Portal) -> BaseScraper:
    adapter_cls = ADAPTERS.get(portal.adapter)
    if adapter_cls is None:
        raise SystemExit(
            f"adapter '{portal.adapter}' do portal {portal.code} ainda não foi implementado"
        )
    kwargs = {"url": portal.url, "portal_code": portal.code, "portal_name": portal.name}
    # Só passa `params` para adapters que de fato o exigem (ex.: comunica_pje,
    # parametrizado por sigla_tribunal); adapters sem params no portals.yaml
    # continuam com a assinatura mais simples (ver TstJuslaborisScraper).
    if portal.params:
        kwargs["params"] = portal.params
    return adapter_cls(**kwargs)


def _print_publications(publications: list[Publication]) -> None:
    if not publications:
        print("Nenhuma publicação encontrada.")
        return

    for pub in publications:
        print(f"[{pub.portal_code}] {pub.published_at} - {pub.title}")
        print(f"    {pub.page_url}")


async def _run_dry_run(portal_code: str) -> None:
    portal = _find_portal(portal_code)
    scraper = _build_scraper(portal)
    publications = await scraper.fetch()
    _print_publications(publications)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Executa a coleta de um portal")
    run_parser.add_argument("--portal", required=True, help="Código do portal (ver portals.yaml)")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só imprime o que seria coletado; não grava, não baixa, não envia e-mail",
    )

    args = parser.parse_args()

    if args.command == "run":
        if not args.dry_run:
            raise SystemExit(
                "apenas 'run --portal CODE --dry-run' está disponível nesta fase do projeto"
            )
        asyncio.run(_run_dry_run(args.portal))


if __name__ == "__main__":
    main()
