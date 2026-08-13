"""Inspeciona uma URL de portal antes de escrever um adapter.

Uso:
    uv run python scripts/inspect.py <URL>

Faz um GET simples e imprime status code, content-type e os primeiros
~2000 caracteres do corpo, para decidir a estratégia de scraping
(API JSON > feed RSS/Atom > URL previsível > HTML estático > Playwright).
"""

import os
import sys

# Executado como `python scripts/inspect.py`, o Python insere o diretório
# scripts/ na frente de sys.path. Como este arquivo se chama inspect.py,
# isso sombreia o módulo padrão `inspect` (do qual httpx/h11 dependem) e
# quebra o import de httpx. Removemos o diretório do script do sys.path
# antes de importar qualquer dependência de terceiros para evitar o choque
# de nome sem precisar renomear o arquivo.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR in sys.path:
    sys.path.remove(_SCRIPT_DIR)

import httpx  # noqa: E402

TIMEOUT_SECONDS = 30
USER_AGENT = "LupaDiarios/1.0"
BODY_PREVIEW_CHARS = 2000


def inspect(url: str) -> None:
    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=TIMEOUT_SECONDS, headers=headers, follow_redirects=True) as client:
        response = client.get(url)

    content_type = response.headers.get("content-type", "")
    print(f"status={response.status_code}")
    print(f"content-type={content_type}")
    print("---")
    print(response.text[:BODY_PREVIEW_CHARS])


def main() -> None:
    if len(sys.argv) != 2:
        print("uso: uv run python scripts/inspect.py <URL>", file=sys.stderr)
        sys.exit(1)
    inspect(sys.argv[1])


if __name__ == "__main__":
    main()
