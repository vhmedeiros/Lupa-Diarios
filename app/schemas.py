"""Modelos Pydantic de resposta da API (ver PLANO.md Fase 17 / SPEC.md §7)."""

import datetime as dt

from pydantic import BaseModel, ConfigDict


class PortalOut(BaseModel):
    """Um portal de portals.yaml, com status enabled e última execução conhecida.

    `last_run_at`: não existe hoje nenhuma tabela de histórico de execuções
    por portal (fora de escopo das fases anteriores). O valor mais sensato
    disponível sem inventar tracking novo é o `MAX(sent_at)` das publicações
    desse portal ainda presentes no buffer (`publications`) — ou seja, a
    última vez que um e-mail com algo desse portal foi enviado, entre o que
    ainda não foi apagado pela retenção. Fica `None` se o portal nunca
    enviou nada ou se tudo que já enviou já saiu do buffer.
    """

    code: str
    name: str
    url: str
    adapter: str
    engine: str
    enabled: bool
    last_run_at: dt.datetime | None = None


class PublicationOut(BaseModel):
    """Uma publicação do buffer (tabela `publications`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    portal_code: str
    portal_name: str
    title: str
    published_at: dt.date
    page_url: str
    summary: str | None
    files: list[dict]
    content_hash: str
    created_at: dt.datetime
    sent_at: dt.datetime | None
