"""Aplicação FastAPI do Lupa Diários."""

from fastapi import FastAPI

app = FastAPI(title="Lupa Diários")


@app.get("/health")
async def health() -> dict[str, str]:
    """Healthcheck simples, sem banco (chega na Fase 4)."""
    return {"status": "ok"}
