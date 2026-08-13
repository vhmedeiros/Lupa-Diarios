"""Carrega e valida portals.yaml, a fonte de verdade dos portais monitorados."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

PORTALS_YAML_PATH = Path(__file__).resolve().parent.parent / "portals.yaml"


class Portal(BaseModel):
    """Configuração validada de um portal, conforme portals.yaml."""

    code: str
    name: str
    url: str
    adapter: str
    engine: Literal["http", "playwright"]
    params: dict = {}
    enabled: bool = False


def load_portals(path: Path = PORTALS_YAML_PATH) -> list[Portal]:
    """Lê e valida todas as entradas de portals.yaml, habilitadas ou não."""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return [Portal.model_validate(entry) for entry in data["portals"]]


def get_enabled_portals(path: Path = PORTALS_YAML_PATH) -> list[Portal]:
    """Retorna somente os portais com enabled: true."""
    return [portal for portal in load_portals(path) if portal.enabled]
