# Guia v2 — Cursor + Claude Code + uv: do zero ao MVP em um dia

Este documento complementa o guia anterior e o substitui nos pontos em que divergem (SQLite → PostgreSQL, pip → uv). Ele cobre, nesta ordem: preparação do ambiente Windows/WSL, primeiro contato com o Cursor (migrando do VS Code), Claude Code dentro do Cursor com seu plano Pro, MCPs para consulta de documentação, a stack com versões definidas, o fluxo `uv`, e — o centro de tudo — o **prompt de planejamento** que você vai dar ao Claude Code antes de qualquer linha de código.

---

## Parte 1 — Ambiente: Windows + WSL

Regra de ouro: **todo o projeto vive dentro do WSL** (ex.: `~/projetos/lupa-diarios`), nunca em `/mnt/c/...`. O filesystem do Windows acessado via WSL é lento e causa problemas com Playwright e Docker. Como o deploy será em Linux (Oracle A1), desenvolver no WSL significa desenvolver no mesmo mundo do deploy.

Checklist no terminal do WSL (Ubuntu):

```bash
# 1. uv (gerencia Python, venv, dependências — tudo)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Claude Code (instalador nativo)
curl -fsSL https://claude.ai/install.sh | bash

# 3. Docker Desktop no Windows com "WSL 2 based engine" ligado
#    (Settings → Resources → WSL Integration → habilite seu Ubuntu)
docker --version && docker compose version   # valida dentro do WSL

# 4. git configurado
git config --global user.name "Seu Nome"
git config --global user.email "voce@exemplo.com"
```

Não precisa instalar Python manualmente: o `uv` baixa e gerencia a versão do Python do projeto sozinho.

---

## Parte 2 — Cursor: primeiro contato (vindo do VS Code)

### 2.1 O que é e como você vai usá-lo no seu cenário

O Cursor é um fork do VS Code com IA integrada — visual, atalhos e extensões praticamente idênticos, então a transição é indolor. No seu caso (Cursor gratuito + Claude Pro), a estratégia correta é: **Cursor como editor, Claude Code como agente**. O plano gratuito do Cursor tem uma cota pequena de uso da IA própria dele; você não vai depender dela. O agente que escreve o código é o Claude Code rodando no **terminal integrado do Cursor**, consumindo seu plano Claude Pro. Você ganha o melhor dos dois: editor moderno para revisar diffs e navegar no código, agente potente sem custo adicional.

### 2.2 Importando suas configs do VS Code (1 clique)

Instale o Cursor no Windows (cursor.com), abra e pressione `Ctrl+Shift+J` (Cursor Settings) → seção **General/Account** → botão **Import from VS Code**. Isso traz extensões, tema, settings.json e keybindings de uma vez. Dois avisos: o Cursor usa o registro **Open VSX**, não o Marketplace da Microsoft — a grande maioria das extensões populares está lá, mas alguma específica pode faltar (dá para instalar o `.vsix` manualmente se precisar); e desabilite Copilot/outros autocompletes de IA se importar, pois conflitam com o do Cursor.

### 2.3 Conectando o Cursor ao WSL

Igual ao VS Code: instale a extensão **WSL**, depois `Ctrl+Shift+P` → "WSL: Connect to WSL" (ou, dentro do terminal do WSL, `cursor .` na pasta do projeto). A barra inferior deve mostrar "WSL: Ubuntu". A partir daí, o terminal integrado (`` Ctrl+` ``) já é um shell do WSL — é nele que você roda `claude`.

### 2.4 Recursos do Cursor que valem conhecer (mesmo no plano free)

O **Tab** (autocomplete da IA) funciona no free com limites. O **@Docs** permite indexar documentações externas: em Cursor Settings → Indexing & Docs → Add Doc, cole URLs como `https://docs.astral.sh/uv`, `https://playwright.dev/python/docs/intro` e `https://fastapi.tiangolo.com` — aí, no chat do Cursor, `@Docs` responde com base nelas. Como sua cota free é curta, use isso para dúvidas pontuais de leitura; o trabalho pesado fica com o Claude Code. O arquivo `.cursor/rules` (ou `AGENTS.md`) cumpre para o Cursor o papel que o CLAUDE.md cumpre para o Claude Code — você pode simplesmente manter as regras no CLAUDE.md e referenciá-lo.

### 2.5 MCP no Cursor

MCPs se configuram em `.cursor/mcp.json` (por projeto) ou `~/.cursor/mcp.json` (global). Exemplo com o Context7 (documentação atualizada de bibliotecas, seção 4):

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    }
  }
}
```

---

## Parte 3 — Claude Code com seu plano Pro, dentro do Cursor

Com o Claude Code instalado no WSL (Parte 1), abra o terminal integrado do Cursor na pasta do projeto e rode `claude`. No primeiro uso ele abre o navegador para login — **entre com sua conta Claude Pro** (não é preciso API key nem custo extra; o Pro inclui uso do Claude Code com limites que se renovam em janelas de algumas horas — detalhes atuais em support.claude.com). Duas consequências práticas dos limites do Pro: use `/clear` entre tarefas para não desperdiçar contexto, e prefira tarefas cirúrgicas a pedidos gigantes — o que, convenientemente, já é a boa prática de qualquer forma. Existe também a extensão do Claude Code para o editor (aparece no Open VSX), que mostra os diffs numa interface gráfica; o terminal, porém, é suficiente e é por onde recomendo começar.

Fluxo de trabalho no dia a dia: painel esquerdo com os arquivos, terminal embaixo com o `claude`, e o Source Control do Cursor (`Ctrl+Shift+G`) para revisar cada diff antes de aprovar o commit. Você conversa no terminal, revisa no editor.

---

## Parte 4 — MCPs no Claude Code (consulta de documentação)

O Claude Code já tem busca e leitura de páginas web nativas, então MCP não é obrigatório. Mas para um projeto que depende de APIs de bibliotecas em versão recente (FastAPI, Playwright, SQLAlchemy async), o **Context7** evita que o agente use sintaxe desatualizada: ele injeta documentação atual da versão exata da lib. Instalação (dentro do WSL, requer Node/npx — se não tiver, `sudo apt install nodejs npm`):

```bash
claude mcp add context7 -- npx -y @upstash/context7-mcp
claude mcp list   # confirma
```

Uso: dentro do Claude Code, acrescente "use context7" quando pedir algo que dependa de doc atualizada ("implemente o lifespan do FastAPI com APScheduler — use context7"). Segundo MCP opcional, para depois do MVP: o **Playwright MCP** (`@playwright/mcp`), que deixa o agente controlar um navegador de verdade para inspecionar os portais visualmente — poderoso para depurar adapters, mas o `scripts/inspect.py` do harness já cobre o essencial hoje. Não adicione mais MCPs que isso: cada um consome contexto e você quer o agente focado.

---

## Parte 5 — Stack com versões definidas

Versões verificadas em agosto/2026. Pinamos por faixa compatível (prática correta: patch livre, minor/major travado onde importa):

| Componente | Versão | Papel |
|---|---|---|
| uv | 0.12.x (atual 0.12.3) | projeto, venv, deps, Python |
| Python | 3.13 (via `uv python pin 3.13`) | runtime |
| FastAPI | >=0.141,<0.150 | API |
| Uvicorn | >=0.35 | servidor ASGI |
| Playwright | >=1.61,<2 | portais com JS |
| httpx | >=0.28,<1 | requests HTTP |
| selectolax | >=0.3,<1 | parse de HTML |
| SQLAlchemy | >=2.0,<3 (modo async) | acesso ao banco |
| asyncpg | >=0.30,<1 | driver PostgreSQL |
| PostgreSQL | 17 (imagem `postgres:17-alpine`) | banco |
| APScheduler | >=3.11,<4 | agendamento (v4 ainda não-estável) |
| aiosmtplib | >=4,<5 | SMTP MailGrid |
| pydantic-settings | >=2.7,<3 | config via .env |
| ruff | >=0.12 | lint + format |
| pytest / pytest-asyncio | >=8 / >=1 | testes |
| Docker Engine + Compose | atual do get.docker.com | dev e prod |

Notas de decisão: PostgreSQL 17 em vez do 18 recém-lançado por maturidade de ecossistema (e é o que você provavelmente usará com Django na Lupa); SQLAlchemy sem Alembic no MVP — `create_all` no startup resolve hoje, migrations entram quando virar módulo da Lupa; e no MVP **sem autenticação** na API (ela nem fica exposta publicamente) — o JWT para o Django da Lupa entra depois como um middleware simples, e a única providência hoje é deixar `JWT_SECRET` já previsto no `.env.example` para não mudar contrato depois.

## Parte 6 — O fluxo `uv` (cola rápida)

```bash
uv init lupa-diarios && cd lupa-diarios   # cria projeto + pyproject.toml
uv python pin 3.13                        # trava o Python (gera .python-version)
uv add "fastapi>=0.141,<0.150" uvicorn playwright httpx selectolax \
       "sqlalchemy>=2.0" asyncpg "apscheduler>=3.11,<4" aiosmtplib \
       pydantic-settings pyyaml
uv add --dev ruff pytest pytest-asyncio
uv run playwright install --with-deps chromium   # navegador + deps do SO
uv run python -m app.cli run --portal TST --dry-run
uv run uvicorn app.main:app --reload
uv sync                                   # recria o ambiente a partir do uv.lock
```

O `uv.lock` vai para o git — é ele que garante que a VM Oracle instala exatamente o que você testou no WSL. No Dockerfile, o padrão profissional é copiar o binário do uv da imagem oficial e usar `uv sync --frozen`:

```dockerfile
FROM python:3.13-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/
WORKDIR /srv/app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
RUN uv run playwright install --with-deps chromium
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

E o compose ganha o serviço do banco (mesmo arquivo serve dev no WSL e prod na A1):

```yaml
services:
  db:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: lupa
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: lupa_diarios
    volumes: ["pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U lupa"]
      interval: 10s
      retries: 5
  app:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      db: { condition: service_healthy }
    ports: ["8000:8000"]
    volumes: ["./data:/srv/app/data"]
volumes:
  pgdata:
```

No `.env`: `DATABASE_URL=postgresql+asyncpg://lupa:senha@db:5432/lupa_diarios` (em dev fora do Docker, troque `db` por `localhost`).

---

## Parte 7 — O prompt de planejamento (o coração do processo)

Por que planejar antes: com agentes, o erro clássico do iniciante é pedir código direto. O agente produz algo plausível, você não sabe avaliar se a estrutura está certa, e três horas depois está preso num labirinto que não entende. O fluxo profissional inverte: primeiro o agente **lê o contexto e escreve um plano**, você lê o plano (isso você consegue julgar, mesmo iniciante — é português, não código), corrige o rumo barato ainda no papel, e só então libera a execução fase a fase. O Plan Mode do Claude Code (`Shift+Tab`) existe exatamente para isso: nele o agente não pode editar arquivos.

Preparação: crie a pasta, rode `git init`, cole o `CLAUDE.md` e o `portals.yaml` do guia anterior (com dois ajustes no CLAUDE.md: troque "SQLite (stdlib sqlite3)" por "PostgreSQL 17 + SQLAlchemy 2 async + asyncpg" e acrescente na seção Stack a linha "Gerenciador: uv — todo comando Python roda via `uv run`; dependências via `uv add`; nunca usar pip direto"). Abra `claude`, pressione `Shift+Tab` até aparecer **plan mode**, e cole o prompt abaixo na íntegra:

```text
CONTEXTO SOBRE MIM E SOBRE O PROJETO

Esta é a primeira vez que desenvolvo software usando um agente de IA
(antes eu programava manualmente no VS Code), então preciso que você
seja meu par sênior: explique decisões relevantes em 1-2 frases quando
tomá-las, e me avise explicitamente quando algo que eu pedi for uma má
ideia. Sou iniciante, e o projeto precisa ficar pronto HOJE como MVP
básico — simplicidade é requisito de negócio, não preguiça.

O projeto é um microserviço de monitoramento de Diários Oficiais
brasileiros: verifica portais em horários definidos, detecta publicações
novas, baixa PDFs/ZIPs e envia por e-mail (SMTP MailGrid). Futuramente
será um módulo do meu SaaS (Django), que se comunicará com este serviço
via JWT — hoje NÃO implementaremos JWT nem integração, apenas deixaremos
a arquitetura sem bloqueios para isso.

Leia com atenção: CLAUDE.md (regras e stack obrigatórias), portals.yaml
(portais e particularidades). Stack fixa, não proponha alternativas:
Python 3.13 gerenciado por uv, FastAPI, Playwright (só onde HTML+httpx
não bastar), PostgreSQL 17 + SQLAlchemy 2 async + asyncpg, APScheduler,
aiosmtplib, Docker Compose. Desenvolvimento em WSL, deploy em VM Oracle
A1 (ARM64) — tudo precisa funcionar em linux/arm64.

SUA TAREFA AGORA (NÃO ESCREVA CÓDIGO)

Produza um arquivo PLANO.md com:

1. Arquitetura resumida: diagrama em texto do pipeline
   (scheduler → scrapers → dedupe → download → e-mail) e árvore de
   arquivos completa do projeto, com uma linha explicando cada arquivo.

2. Modelo de dados: tabelas PostgreSQL (publications com hash único
   para dedupe, e o que mais julgar necessário — minimalismo).

3. Análise portal a portal do portals.yaml: para cada um, qual
   estratégia você pretende investigar primeiro (API JSON escondida,
   feed RSS/Atom, URL previsível de PDF, HTML estático, Playwright),
   e uma nota de risco (baixo/médio/alto) de dar trabalho.

4. Recorte do MVP DE HOJE: proponha quais 4-5 portais entram hoje
   (priorize os de menor risco e maior cobertura) e quais ficam
   habilitados=false para os próximos dias. Justifique.

5. Fases de execução: divida o desenvolvimento em fases pequenas
   (setup, core, adapters, e-mail, scheduler+API, docker), cada uma com
   critério de aceite VERIFICÁVEL (comando que eu rodo e saída que devo
   ver) e um commit ao final. Nenhuma fase pode depender de código que
   só existirá em fase futura.

6. Riscos e mitigação: os 3-5 maiores riscos de não terminar hoje e
   como o plano os mitiga.

7. Perguntas para mim: liste o que ficou ambíguo e precisa da minha
   decisão antes de começar. Se nada, diga que não há.

Regras do plano: seja concreto (nomes de arquivos, comandos reais),
não invente requisitos que não pedi, e otimize para eu conseguir
acompanhar e aprender — não para me impressionar. Aguarde minha
aprovação do PLANO.md antes de qualquer implementação.
```

Como conduzir depois do plano: leia o PLANO.md inteiro (10 minutos bem gastos), responda as perguntas dele, peça ajustes se o recorte do MVP parecer grande demais para hoje, aprove — e daí em diante peça **uma fase por vez**, sempre validando com o critério de aceite antes de seguir ("execute a Fase 2 do PLANO.md"). Entre fases: `/clear`, e o PLANO.md + CLAUDE.md garantem que o agente retoma o contexto. Se uma fase quebrar, descreva o sintoma concreto (mensagem de erro, saída do comando) em vez de "não funcionou".

---

## Parte 8 — Cronograma realista para hoje

Manhã: ambiente (Partes 1-3, ~1h), planejamento e leitura do PLANO.md (~45min), fases de setup e core (~1h30). Tarde: adapters do recorte MVP — comece pelos de risco baixo que o plano indicar; feed Atom do TST e Comunica PJe tendem a sair em minutos cada, os de Playwright levam mais iteração. Fim de tarde: e-mail (teste com `send-test` no seu MailGrid cedo, para sobrar tempo se SPF/DKIM travarem), scheduler, e `docker compose up --build` no WSL. O deploy na A1 pode ficar para amanhã sem culpa — a aplicação rodando em Docker no WSL é 95% do caminho, e o restante é `git clone` + `.env` + `docker compose up -d` na VM. Se o dia apertar, corte portais, nunca corte o dedupe nem os testes dos adapters que entraram: portal a menos é feature adiada; dedupe quebrado é e-mail duplicado para sempre.