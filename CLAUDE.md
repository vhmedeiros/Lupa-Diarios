# Projeto: Lupa Diários — monitor de Diários Oficiais

## O que é
Microserviço em Python que monitora portais de Diários Oficiais
brasileiros, raspa as publicações em texto, baixa os arquivos vinculados
(PDF/ZIP) e dispara as novidades por e-mail via SMTP (MailGrid).
Roda 24/7 em Docker numa VM Oracle A1 (linux/arm64). Futuramente será
módulo do SaaS Lupa (Django), que se comunicará com este serviço via
JWT — hoje o JWT NÃO é implementado, apenas JWT_SECRET fica reservado
no .env.example.

## Stack (fixa — não mudar sem aprovação explícita do usuário)
- Gerenciador: uv. Todo comando Python roda via `uv run`; dependências
  entram somente via `uv add`. Nunca usar pip diretamente.
- Python 3.13 (pinado via `uv python pin 3.13`).
- FastAPI (>=0.141,<0.150) + Uvicorn.
- httpx (>=0.28) + selectolax para portais de HTML estático/API.
- Playwright (>=1.61,<2) SOMENTE nos portais que exigem JS.
- PostgreSQL 17 + SQLAlchemy 2 async + asyncpg. Sem Alembic no MVP:
  create_all no startup.
- APScheduler (>=3.11,<4) com cron trigger.
- aiosmtplib (>=4) para SMTP.
- pydantic-settings para configuração via .env.
- ruff (lint+format), pytest + pytest-asyncio.
- Docker Compose (serviços: app + db postgres:17-alpine).
- Sem ORM extra, sem Celery, sem Redis, sem microserviços adicionais.
  Simplicidade é requisito de negócio.

## Arquitetura
- Padrão adapter: cada portal é uma classe em app/scrapers/ que herda
  de BaseScraper e implementa `async def fetch(self) -> list[Publication]`.
- portals.yaml é a fonte de verdade: code, name, url, adapter, engine
  (http|playwright), params, enabled.
- Pipeline por ciclo: scheduler → para cada portal enabled → fetch() →
  filtra por hash em seen_hashes → salva em publications → baixa
  arquivos para data/files/ → monta e envia UM e-mail agrupado por
  portal → grava sent_at. Falha em um portal NUNCA derruba o ciclo dos
  demais (try/except por portal + log).
- Coleta = texto da publicação (título, data, resumo/corpo quando
  existir) + arquivos vinculados (PDF/ZIP).
- Dedupe: hash sha256 de (portal_code + url_da_publicacao + data),
  registrado na tabela seen_hashes (hash + first_seen_at).
- E-mail: anexos até MAX_ATTACH_MB (padrão 15) somados; arquivo que
  exceder não é anexado — o item entra no corpo com o link original e
  aviso explícito de tamanho. Nunca omitir publicação por tamanho.
- Retenção: o banco é um BUFFER, não histórico. Job diário do scheduler
  apaga publications (e arquivos em data/files/) com sent_at anterior a
  RETENTION_DAYS (padrão 3). A tabela seen_hashes NUNCA é tocada pela
  retenção — é ela que impede reenvio de publicações ainda visíveis.
- Agendamento: cron via env SCAN_CRON (padrão "0 8-20 * * 1-5"),
  timezone America/Sao_Paulo.

## Convenções
- Hierarquia de estratégia por portal, nesta ordem de preferência:
  API JSON escondida > feed RSS/Atom > URL previsível de arquivo >
  HTML estático (httpx+selectolax) > Playwright. Antes de escrever um
  adapter, SEMPRE inspecionar o portal com scripts/inspect.py e
  procurar API/feed/URL previsível.
- Timeout de 30s em toda request, retry 3x com backoff, User-Agent
  "LupaDiarios/1.0".
- Todo adapter novo exige fixture (HTML/JSON salvo em tests/fixtures/)
  e teste que roda SEM rede.
- Logging estruturado com o módulo logging; nada de print.
- Type hints em todas as assinaturas públicas.
- Ao final de cada fase aprovada: `uv run ruff check --fix . &&
  uv run ruff format .`, `uv run pytest -q` verde, commit com mensagem
  curta no imperativo.

## Comandos
- Testes: uv run pytest -q
- Lint/format: uv run ruff check --fix . && uv run ruff format .
- Rodar um portal manualmente: uv run python -m app.cli run --portal TCU --dry-run
- E-mail de teste: uv run python -m app.cli send-test
- API em dev: uv run uvicorn app.main:app --reload
- Subir tudo: docker compose up --build

## Agentes deste repositório
- planejador (.claude/agents/planejador.md): produz e mantém PLANO.md.
  Nunca escreve código de produção.
- executor (.claude/agents/executor.md): implementa fases do PLANO.md
  aprovado. Nunca altera plano ou escopo por conta própria.
- O usuário aprova o plano e valida cada fase entre os dois.

## Nunca fazer
- Nunca commitar segredos; SMTP, banco e JWT_SECRET vêm de variáveis
  de ambiente (.env.example documenta todas).
- Nunca remover o mecanismo de dedupe; nunca enviar e-mail em --dry-run.
- Nunca apagar seen_hashes no job de retenção.
- Nunca fazer scraping agressivo: mínimo de requests, respeitar o site.
- Nunca usar pip; nunca adicionar dependência sem aprovação do usuário.