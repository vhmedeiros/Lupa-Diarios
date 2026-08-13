"""CLI operacional do Lupa Diários (ver PLANO.md Fases 6, 13 e 14 / SPEC.md §8).

Uso:
    uv run python -m app.cli run --portal CODE --dry-run
    uv run python -m app.cli run [--portal CODE]
    uv run python -m app.cli run --portal CODE --force
    uv run python -m app.cli send-test

`run --dry-run`: resolve o adapter do portal pelo registry, chama
`fetch()` e imprime as publicações — sem gravar no banco, sem baixar
arquivo e sem enviar e-mail.

`run` (sem `--dry-run`, Fase 14): roda o pipeline de verdade
(`app.pipeline.run_cycle`) — grava no banco, baixa arquivos e envia UM
e-mail agrupado se houver publicação nova. Sem `--portal`, roda todos os
portais habilitados em portals.yaml.

`run --force` (fora do PLANO.md original, feature pontual aprovada em
sessão): exige `--portal CODE` (reenvio forçado de todos os portais de
uma vez seria destrutivo demais). Antes de rodar o pipeline, faz um
`fetch()` do portal, calcula o `content_hash` de cada publicação
encontrada e apaga essas linhas específicas de `seen_hashes` e
`publications` (`app.dedupe.clear_hashes`) — nunca a tabela inteira nem
por `portal_code` cru. Com o hash liberado, o pipeline normal trata
aquelas publicações como novas de novo e as reenvia por e-mail. Usado
para reenviar manualmente sem precisar de DELETE direto no Postgres.

`send-test`: checkpoint manual da Fase 13 — monta um e-mail com uma
publicação fictícia via `build_email` e o envia de verdade via SMTP
(MailGrid), usando as credenciais de `app.config.settings`. Não grava
nada no banco.
"""

import argparse
import asyncio
import datetime as dt
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.dedupe import clear_hashes, compute_hash
from app.mailer import build_email, send_email
from app.models import Publication
from app.pipeline import run_cycle
from app.registry import Portal, load_portals
from app.scrapers.base import BaseScraper
from app.scrapers.base import Publication as ScrapedPublication
from app.scrapers.comunica_pje import ComunicaPjeScraper
from app.scrapers.tcdf import TcdfScraper
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
    "tcdf": TcdfScraper,
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


def _print_publications(publications: list[ScrapedPublication]) -> None:
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


async def _force_clear_seen(session: AsyncSession, portal_code: str) -> None:
    """Libera as publicações atuais de `portal_code` para reenvio (--force).

    Faz um fetch() real do portal (igual ao dry-run), calcula o hash de
    cada publicação encontrada e apaga só essas linhas específicas de
    seen_hashes/publications via `app.dedupe.clear_hashes`. Não comita —
    quem chama (`_run_pipeline`) comita junto com o resto do ciclo.
    """
    portal = _find_portal(portal_code)
    scraper = _build_scraper(portal)
    publications = await scraper.fetch()
    hashes = [compute_hash(pub.portal_code, pub.page_url, pub.published_at) for pub in publications]
    removed = await clear_hashes(session, hashes)
    if removed:
        print(f"--force: {removed} publicação(ões) já vistas liberadas para reenvio")
    else:
        print("--force: nenhuma publicação já vista encontrada para liberar")


async def _run_pipeline(portal_code: str | None, force: bool = False) -> None:
    """Roda o pipeline de verdade (Fase 14) e imprime o resultado do ciclo."""
    async with async_session() as session:
        if force:
            assert portal_code is not None  # já validado em main()
            await _force_clear_seen(session, portal_code)

        count = await run_cycle(session, portal_code)
        await session.commit()

    if count:
        print(f"{count} publicações enviadas")
    else:
        print("0 publicações novas, nenhum e-mail enviado")


async def _run_send_test() -> None:
    """Monta e envia um e-mail de teste real via SMTP (Fase 13)."""
    fake_publication = Publication(
        portal_code="TESTE",
        portal_name="Portal de Teste",
        title="Publicação fictícia — checkpoint manual de SMTP",
        published_at=dt.date.today(),
        page_url="https://exemplo.gov.br/publicacao/teste",
        summary="Este é um e-mail de teste do comando 'send-test' do Lupa Diários.",
        files=[],
        content_hash="send-test-checkpoint",
    )
    subject, html_body, attachments = build_email([fake_publication])
    await send_email(subject, html_body, attachments)
    print("e-mail enviado")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Executa o pipeline de coleta")
    run_parser.add_argument(
        "--portal",
        required=False,
        default=None,
        help="Código do portal (ver portals.yaml); sem isso, roda todos os habilitados",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só imprime o que seria coletado; não grava, não baixa, não envia e-mail",
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Libera para reenvio as publicações atuais do portal (apaga o hash delas de "
            "seen_hashes/publications antes de rodar o ciclo); exige --portal CODE"
        ),
    )

    subparsers.add_parser(
        "send-test", help="Envia um e-mail de teste real via SMTP (checkpoint manual da Fase 13)"
    )

    args = parser.parse_args()

    if args.command == "run":
        if args.dry_run:
            if args.portal is None:
                raise SystemExit("'run --dry-run' exige '--portal CODE'")
            asyncio.run(_run_dry_run(args.portal))
        else:
            if args.force and args.portal is None:
                raise SystemExit("'run --force' exige '--portal CODE' (não é permitido em massa)")
            asyncio.run(_run_pipeline(args.portal, force=args.force))
    elif args.command == "send-test":
        asyncio.run(_run_send_test())


if __name__ == "__main__":
    main()
