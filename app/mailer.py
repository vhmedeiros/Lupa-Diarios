"""Montagem do e-mail de novidades (ver PLANO.md Fase 12 / SPEC.md §2 R2, §6).

`build_email` NÃO envia nada — apenas decide, aplicando a regra R2, quais
arquivos entram como anexo e monta o assunto + corpo HTML. O envio via
SMTP real (aiosmtplib) é escopo da Fase 13.

Decisões de design desta fase:
- Entrada: `Sequence[app.models.Publication]` (o modelo ORM, não o
  `app.scrapers.base.Publication`). É o formato que já sai do pipeline
  depois do dedupe + downloader: `files` já é a lista de
  `{url, path, size_bytes, attached}` que `app/downloader.py` produz (com
  `attached` sempre `False` até aqui — ver docstring de
  `download_publication_files`). O mailer é quem decide `attached` de
  fato, então `build_email` MUTA esses dicts em memória para refletir a
  decisão (mesma estrutura que a Fase 14 vai persistir no banco).
- Ordem de soma global (R2): confirmado com o usuário que o limite
  `MAX_ATTACH_MB` é global por e-mail (soma de todos os portais do
  ciclo) e o desempate é ORDEM DE DESCOBERTA — não "menores primeiro".
  Ordem de descoberta = ordem de primeira aparição de cada portal na
  lista de entrada (a ordem em que o pipeline os processou), e dentro de
  um mesmo portal, por `published_at`; dentro de uma publicação, a
  ordem de `files` (ordem de descoberta dos links pelo scraper/downloader).
- Uma vez que a soma acumulada estoura o limite, TODO arquivo seguinte
  nessa ordem também vira link — mesmo que individualmente pequeno —
  conforme a Fase 12 do PLANO.md ("o primeiro que faria a soma estourar
  e todos os seguintes").
"""

import datetime as dt
import html
from collections.abc import Sequence
from pathlib import Path

from app.config import settings
from app.models import Publication

BYTES_PER_MB = 1024 * 1024


def _ordered_publications(publications: Sequence[Publication]) -> list[Publication]:
    """Agrupa por portal (ordem de primeira aparição) e ordena cada grupo por data."""
    portal_order: list[str] = []
    by_portal: dict[str, list[Publication]] = {}
    for pub in publications:
        if pub.portal_code not in by_portal:
            portal_order.append(pub.portal_code)
            by_portal[pub.portal_code] = []
        by_portal[pub.portal_code].append(pub)

    ordered: list[Publication] = []
    for code in portal_order:
        ordered.extend(sorted(by_portal[code], key=lambda p: p.published_at))
    return ordered


def _assign_attachments(ordered_publications: list[Publication], max_attach_mb: int) -> list[dict]:
    """Decide `attached` (R2) percorrendo os arquivos na ordem de descoberta.

    Muta `file["attached"]` em cada dict de `publication.files`. Retorna a
    lista dos arquivos efetivamente anexados, na mesma ordem, prontos para
    o envio SMTP da Fase 13 (`{path, filename}`).
    """
    limit_bytes = max_attach_mb * BYTES_PER_MB
    running_total = 0
    overflow = False
    attachments: list[dict] = []

    for pub in ordered_publications:
        for file in pub.files:
            if not overflow:
                tentative_total = running_total + file["size_bytes"]
                if tentative_total <= limit_bytes:
                    file["attached"] = True
                    running_total = tentative_total
                    attachments.append({"path": file["path"], "filename": Path(file["path"]).name})
                    continue
                overflow = True
            file["attached"] = False

    return attachments


def _format_size_mb(size_bytes: int) -> str:
    """Formata o tamanho em MB para o aviso do e-mail (ex.: '42 MB')."""
    size_mb = size_bytes / BYTES_PER_MB
    if size_mb < 1:
        return f"{size_mb:.1f}"
    return f"{round(size_mb)}"


def _file_html(file: dict, max_attach_mb: int) -> str:
    filename = html.escape(Path(file["path"]).name)
    if file["attached"]:
        return f"<li>📎 {filename} (anexado)</li>"

    url = html.escape(file["url"])
    size = _format_size_mb(file["size_bytes"])
    return (
        f"<li>📎 Arquivo de {size} MB — acima do limite de anexo de "
        f'{max_attach_mb} MB, <a href="{url}">acesse pelo link</a></li>'
    )


def _publication_html(pub: Publication, max_attach_mb: int) -> str:
    title = html.escape(pub.title)
    page_url = html.escape(pub.page_url)
    date_str = pub.published_at.strftime("%d/%m/%Y")

    parts = [
        "<li>",
        f'<a href="{page_url}"><strong>{title}</strong></a>',
        f"<br>Data: {date_str}",
    ]
    if pub.summary:
        parts.append(f"<br>{html.escape(pub.summary)}")
    if pub.files:
        files_html = "".join(_file_html(f, max_attach_mb) for f in pub.files)
        parts.append(f"<ul>{files_html}</ul>")
    parts.append("</li>")
    return "".join(parts)


def _build_html_body(ordered_publications: list[Publication], max_attach_mb: int) -> str:
    sections: list[str] = []
    current_portal_code: str | None = None
    current_portal_name = ""
    current_items: list[str] = []

    def flush() -> None:
        if current_portal_code is not None:
            items_html = "".join(current_items)
            title = html.escape(current_portal_name)
            sections.append(f"<h2>{title}</h2><ul>{items_html}</ul>")

    for pub in ordered_publications:
        if pub.portal_code != current_portal_code:
            flush()
            current_portal_code = pub.portal_code
            current_portal_name = pub.portal_name
            current_items = []
        current_items.append(_publication_html(pub, max_attach_mb))
    flush()

    footer = "<hr><p>Lupa Diários Oficiais — monitor automático de publicações.</p>"
    return "".join(sections) + footer


def build_email(
    publications: Sequence[Publication],
    max_attach_mb: int | None = None,
    now: dt.datetime | None = None,
) -> tuple[str, str, list[dict]]:
    """Monta assunto, corpo HTML e anexos do e-mail de novidades (R2, §6).

    NÃO envia nada — apenas decide e monta. O envio real (SMTP) é a
    Fase 13. `max_attach_mb` e `now` são parametrizáveis para testes
    determinísticos; em produção usam `settings.MAX_ATTACH_MB` e o
    horário atual.
    """
    limit_mb = max_attach_mb if max_attach_mb is not None else settings.MAX_ATTACH_MB
    moment = now if now is not None else dt.datetime.now()

    ordered = _ordered_publications(publications)
    attachments = _assign_attachments(ordered, limit_mb)
    html_body = _build_html_body(ordered, limit_mb)

    subject = (
        f"Lupa Diários Oficiais — {len(publications)} novas publicações — "
        f"{moment.strftime('%d/%m/%Y %H:%M')}"
    )

    return subject, html_body, attachments
