"""Job de retenção de publications (ver PLANO.md Fase 15 / SPEC.md §3 R3).

Publicações com `sent_at` preenchido e anterior a `RETENTION_DAYS` dias
(config em `app.config.settings`) são apagadas de `publications`, junto
com os arquivos correspondentes em disco (campo `files` jsonb, cada item
com `path`). Publicações com `sent_at` NULL (ainda não enviadas) NUNCA
são apagadas por este job — retenção só vale para o que já saiu por
e-mail (SPEC.md §3: "publicações recebem sent_at no disparo").

A tabela `seen_hashes` NUNCA é tocada aqui — regra explícita de
CLAUDE.md ("Nunca fazer": nunca apagar seen_hashes no job de retenção).
É ela que impede reenvio de uma publicação que já não está mais em
`publications`. Não comita — quem chama decide quando comitar (mesmo
padrão de `app.dedupe.filter_new`).
"""

import datetime as dt
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Publication

logger = logging.getLogger(__name__)


def _delete_files(files: list[dict]) -> None:
    """Apaga do disco os arquivos vinculados a uma publicação, se existirem.

    Arquivo já ausente em disco não é erro (idempotência): apenas loga um
    aviso e segue para o próximo.
    """
    for file_info in files:
        path = file_info.get("path")
        if not path:
            continue
        try:
            Path(path).unlink()
        except FileNotFoundError:
            logger.warning("Retenção: arquivo já não existia em disco: %s", path)


async def run_retention(session: AsyncSession, retention_days: int | None = None) -> int:
    """Apaga publications (+ arquivos em disco) com sent_at expirado.

    `retention_days` default para `settings.RETENTION_DAYS`. NÃO apaga
    seen_hashes. NÃO apaga publications com sent_at NULL. Não comita a
    sessão — isso é responsabilidade de quem chama. Retorna o número de
    publications apagadas.
    """
    days = settings.RETENTION_DAYS if retention_days is None else retention_days
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)

    result = await session.execute(
        select(Publication).where(
            Publication.sent_at.is_not(None),
            Publication.sent_at < cutoff,
        )
    )
    rows = list(result.scalars())

    for row in rows:
        _delete_files(row.files or [])
        await session.delete(row)

    await session.flush()

    if rows:
        logger.info("Retenção: %d publicações apagadas (sent_at < %s)", len(rows), cutoff)

    return len(rows)
