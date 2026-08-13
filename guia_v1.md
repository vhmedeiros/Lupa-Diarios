# Guia Profissional: Claude Code + Harness para o Radar de Diários Oficiais (Lupa)

Este documento tem três objetivos: (1) ensinar você a usar o Claude Code do absoluto zero, (2) entregar um "harness" pronto — a estrutura de repositório, o CLAUDE.md e a sequência de prompts que fazem o agente desenvolver o projeto de forma controlada e rápida — e (3) definir a arquitetura da aplicação (FastAPI + Playwright + SMTP + Docker na Oracle A1) de modo que ela já nasça preparada para virar módulo do seu SaaS Lupa.

---

## Parte 1 — Claude Code do zero

### 1.1 O que é

O Claude Code é um agente de programação que roda no seu terminal. Diferente de um chat comum, ele lê e edita arquivos do seu projeto, executa comandos (testes, docker, git), navega no código e trabalha em tarefas de várias etapas de forma autônoma — sempre pedindo sua permissão antes de ações sensíveis. Você conversa com ele em linguagem natural ("crie o adapter do portal do TCU seguindo o padrão do BaseScraper") e ele planeja, implementa, testa e mostra o diff.

Documentação oficial: https://code.claude.com/docs — vale manter aberta enquanto aprende.

### 1.2 Instalação

O instalador nativo é o caminho recomendado pela Anthropic. No Linux, macOS ou WSL:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Alternativa via npm (requer Node.js instalado):

```bash
npm install -g @anthropic-ai/claude-code
```

Verifique:

```bash
claude --version
claude doctor   # diagnóstico completo da instalação
```

Se aparecer "command not found" após o instalador nativo, adicione `~/.local/bin` ao PATH do seu shell.

### 1.3 Autenticação

Na primeira execução de `claude`, ele abre o navegador para login com sua conta Claude (planos Pro/Max incluem uso do Claude Code) ou conta do Console/API. Alternativamente, você pode exportar `ANTHROPIC_API_KEY` no ambiente — útil na VM, onde não há navegador. As credenciais ficam salvas localmente e não é preciso logar de novo.

### 1.4 Primeiro contato — os comandos que você vai usar todo dia

Entre na pasta do projeto e rode `claude`. Você cai num prompt interativo. O essencial:

```
/init        gera um CLAUDE.md inicial analisando o projeto
/help        lista comandos
/clear       zera o contexto da conversa (use entre tarefas distintas)
/compact     resume a conversa para liberar contexto sem perder o fio
/permissions gerencia o que o agente pode fazer sem perguntar
Esc          interrompe o agente no meio de uma ação
Shift+Tab    alterna para o Plan Mode (explicado abaixo)
```

Fora do modo interativo, `claude -p "pergunta"` executa uma tarefa única e sai — útil em scripts.

### 1.5 CLAUDE.md — a memória do projeto

O arquivo `CLAUDE.md` na raiz do repositório é lido automaticamente em toda sessão. É onde você grava as regras do projeto: arquitetura, convenções, comandos de teste, o que o agente nunca deve fazer. É o componente mais importante do harness — um bom CLAUDE.md transforma o agente de "estagiário criativo" em "engenheiro que segue o padrão da casa". Na Parte 2 há um CLAUDE.md completo pronto para este projeto.

### 1.6 Plan Mode — planejar antes de tocar no código

Pressionando `Shift+Tab` você entra no Plan Mode: o agente pesquisa o código e apresenta um plano de implementação **sem editar nada**. Você revisa, ajusta, aprova — e só então ele executa. Para tarefas não triviais (um novo adapter de portal, o módulo de e-mail), use sempre Plan Mode primeiro. Isso evita retrabalho e é a prática que mais acelera iniciantes.

### 1.7 Permissões

Por padrão o Claude Code pede confirmação antes de rodar comandos e editar arquivos fora do escopo. Você pode permitir ações recorrentes ("sempre permitir `pytest`") pelo próprio diálogo ou por `/permissions`. Existe a flag `--dangerously-skip-permissions` para rodar sem confirmações — use apenas dentro de containers/ambientes descartáveis, nunca na sua máquina com credenciais reais.

### 1.8 Comandos customizados (slash commands)

Arquivos Markdown em `.claude/commands/` viram comandos reutilizáveis. Exemplo — crie `.claude/commands/novo-portal.md`:

```markdown
Crie um novo adapter de portal seguindo estas etapas:
1. Leia app/scrapers/base.py e um adapter existente como referência.
2. Acesse a URL informada em $ARGUMENTS com o script scripts/inspect.py
   para entender a estrutura HTML/API do portal.
3. Implemente o adapter em app/scrapers/, registre em portals.yaml.
4. Escreva um teste com HTML gravado (fixture) em tests/.
5. Rode pytest e o comando `python -m app.cli run --portal <codigo> --dry-run`.
```

Depois, dentro do Claude Code: `/novo-portal TCDF https://doe.tc.df.gov.br`. Como você vai adicionar portais continuamente, esse comando é o coração da sua operação futura.

### 1.9 Hooks, subagents e MCP (visão rápida)

Hooks executam scripts seus em eventos do agente (ex.: rodar `ruff format` após cada edição de arquivo). Subagents são agentes especializados que o principal delega tarefas. MCP conecta o Claude Code a ferramentas externas (bancos, browsers, APIs). Para este projeto você não precisa de nada disso no início — cito para você saber que existe quando o Lupa crescer. Detalhes em https://code.claude.com/docs.

### 1.10 As cinco práticas que definem quem usa bem um agente

Primeira: tarefas pequenas e verificáveis — "implemente o adapter do TCU e prove com um teste", nunca "faça o sistema inteiro". Segunda: Plan Mode antes de tarefas médias/grandes. Terceira: commits frequentes — peça ao próprio agente para commitar após cada etapa aprovada; se algo der errado, `git checkout` resolve. Quarta: revise os diffs — você é o revisor, o agente é o executor. Quinta: dê ao agente um meio de se autoverificar (testes, `--dry-run`, scripts de inspeção); agente que consegue checar o próprio trabalho erra muito menos. O harness abaixo materializa essas cinco práticas.

---

## Parte 2 — O Harness

"Harness" aqui significa: repositório pré-estruturado + CLAUDE.md + especificação + sequência de prompts em fases. Você não pede "faça tudo"; você conduz o agente por um trilho onde cada fase produz algo testável.

### 2.1 Estrutura do repositório

Crie a pasta e os arquivos de controle antes de chamar o agente:

```
lupa-diarios/
├── CLAUDE.md              # regras do projeto (abaixo)
├── SPEC.md                # especificação funcional (abaixo)
├── portals.yaml           # cadastro dos portais (abaixo)
├── .claude/commands/      # slash commands (novo-portal.md etc.)
├── app/
│   ├── main.py            # FastAPI
│   ├── cli.py             # execução manual: run, run --portal X, --dry-run
│   ├── models.py          # Publication, dataclasses/pydantic
│   ├── db.py              # SQLite + dedupe
│   ├── mailer.py          # SMTP
│   ├── scheduler.py       # APScheduler
│   ├── downloader.py      # download de PDFs/ZIPs
│   └── scrapers/
│       ├── base.py        # BaseScraper (contrato)
│       ├── registry.py    # carrega adapters a partir do portals.yaml
│       └── ...um arquivo por portal
├── scripts/inspect.py     # abre URL com Playwright e salva HTML/screenshot
├── tests/
├── data/                  # sqlite + arquivos baixados (volume no Docker)
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

### 2.2 CLAUDE.md — copie na íntegra

```markdown
# Projeto: Lupa Diários — monitor de Diários Oficiais

## O que é
Serviço em Python que monitora portais de Diários Oficiais brasileiros,
detecta publicações novas, baixa os arquivos (PDF/ZIP) e envia por e-mail
via SMTP. Roda 24/7 em container Docker numa VM Oracle A1 (ARM64/aarch64).

## Stack (não mudar sem aprovação explícita)
- Python 3.12, FastAPI, APScheduler, SQLite (stdlib sqlite3), httpx,
  selectolax (parse HTML), Playwright apenas nos portais que exigem JS,
  aiosmtplib para envio.
- Sem ORM, sem Celery, sem Redis, sem microserviços. Simplicidade é requisito.

## Arquitetura
- Padrão adapter: cada portal é uma classe em app/scrapers/ que herda de
  BaseScraper e implementa `async def fetch(self) -> list[Publication]`.
- portals.yaml é a fonte de verdade: código, nome, url, adapter, enabled,
  e `engine: http|playwright`.
- Pipeline: scheduler -> para cada portal habilitado -> fetch() ->
  filtra itens já vistos (hash em SQLite) -> baixa arquivos ->
  envia e-mail -> marca como enviado. Falha em um portal NUNCA pode
  derrubar o ciclo dos demais (try/except por portal + log).
- Dedupe: hash sha256 de (portal_code + url_da_publicacao + data).

## Convenções
- Preferir httpx + selectolax; usar Playwright só se o conteúdo for
  renderizado por JS. Antes de escrever um adapter, SEMPRE inspecionar o
  portal com scripts/inspect.py e verificar se existe API JSON, feed
  RSS/Atom ou URL previsível de PDF — isso é mais estável que scraping de HTML.
- Timeouts em toda request (30s), retry simples (3x, backoff), User-Agent
  identificável "LupaDiarios/1.0".
- Todo adapter novo precisa de teste com fixture (HTML/JSON salvo em
  tests/fixtures/) — testes não podem depender de rede.
- Logging estruturado com o módulo logging; nada de print.
- Tipos em todas as assinaturas públicas.

## Comandos
- Testes: pytest -q
- Lint/format: ruff check --fix . && ruff format .
- Rodar um portal manualmente: python -m app.cli run --portal TCU --dry-run
- Subir tudo: docker compose up --build

## Nunca fazer
- Nunca commitar segredos; SMTP e destinatários vêm de variáveis de
  ambiente (ver .env.example).
- Nunca remover o mecanismo de dedupe ou enviar e-mail em --dry-run.
- Nunca fazer scraping agressivo: mínimo de requests, respeitar o site.
- Ao terminar cada tarefa aprovada, criar um commit com mensagem curta.
```

### 2.3 SPEC.md — a especificação que o agente vai consultar

Coloque no SPEC.md o objetivo do produto, o modelo de dados (`Publication`: portal_code, portal_name, title, published_at, page_url, file_urls, summary, hash), o formato do e-mail (um e-mail por ciclo agrupando as novidades por portal, com anexos até um limite de tamanho e links quando exceder), os endpoints da API (`GET /health`, `POST /run`, `GET /publications`, `GET /portals`) e a tabela de portais com suas particularidades (seção 3.3 deste guia serve de base — cole-a lá).

### 2.4 portals.yaml inicial

```yaml
portals:
  - code: JFDFDJN
    name: "Diário da Justiça Federal do DF"
    url: "https://trf1.jus.br/trf1/biblioteca/diarios-da-justica"
    adapter: trf1_biblioteca
    engine: playwright
    enabled: true
  - code: TCU
    name: "Diário do TCU"
    url: "https://portal.tcu.gov.br/btcu"
    adapter: tcu
    engine: playwright
    enabled: true
  - code: TCDF
    name: "Diário do TCDF"
    url: "https://doe.tc.df.gov.br"
    adapter: tcdf
    engine: http
    enabled: true
  - code: STFDJE
    name: "DJe do STF"
    url: "https://digital.stf.jus.br/publico/publicacoes"
    adapter: stf_dje
    engine: playwright
    enabled: true
  - code: STJ
    name: "Diário do STJ"
    url: "https://processo.stj.jus.br/processo/dj/init"
    adapter: stj
    engine: playwright
    enabled: true
  - code: STJDJN
    name: "STJ no DJEN (Comunica PJe)"
    url: "https://comunica.pje.jus.br/consulta?siglaTribunal=STJ&meio=D"
    adapter: comunica_pje
    engine: http
    params: { sigla_tribunal: STJ }
    enabled: true
  - code: TST
    name: "Diário do TST (JusLaboris)"
    url: "https://juslaboris.tst.jus.br/feed/atom_1.0/site"
    adapter: juslaboris_feed
    engine: http
    enabled: true
  - code: TSTDJN
    name: "TST no DEJT/DJEN"
    url: "https://dejt.jt.jus.br/dejt/f/n/diariocon"
    adapter: dejt
    engine: playwright
    enabled: true
  - code: TRT10DJN
    name: "TRT 10ª Região"
    url: "https://dejt.jt.jus.br/dejt/f/n/diariocon"
    adapter: dejt
    engine: playwright
    params: { tribunal: "TRT da 10ª Região" }
    enabled: true
  - code: TJDFTDJN
    name: "TJDFT 1º e 2º graus"
    url: "https://pesquisadje.tjdft.jus.br/"
    adapter: tjdft
    engine: playwright
    enabled: true
  - code: TRFDJN
    name: "TRF 1ª Região"
    url: "https://trf1.jus.br/trf1/biblioteca/diarios-da-justica"
    adapter: trf1_biblioteca
    engine: playwright
    params: { secao: "TRF1" }
    enabled: true
  - code: TRF1ATA
    name: "TRF1 Atas de Distribuição"
    url: "https://www.trf1.jus.br/trf1/ataas/atas"
    adapter: trf1_atas
    engine: playwright
    enabled: true
```

Repare em dois ganhos: `JFDFDJN` e `TRFDJN` compartilham o mesmo adapter (`trf1_biblioteca`, a página da biblioteca do TRF1 publica as seções de todos os diários da 1ª Região), e `TSTDJN`/`TRT10DJN` compartilham o adapter `dejt` parametrizado por tribunal. Menos código, menos manutenção.

### 2.5 A sequência de prompts (as fases do desenvolvimento)

Rode `claude` na pasta e execute uma fase por vez. Entre fases, use `/clear`. Para as fases 2 em diante, ative o Plan Mode (Shift+Tab), revise o plano e aprove.

**Fase 0 — Setup.** Crie manualmente CLAUDE.md, SPEC.md, portals.yaml e `git init`. Prompt:

> Leia CLAUDE.md e SPEC.md. Crie o esqueleto do projeto: pyproject.toml com as dependências, estrutura de pastas conforme o CLAUDE.md, app/models.py com Publication, .env.example, configuração de ruff e pytest, e o scripts/inspect.py (recebe uma URL, abre com Playwright, salva o HTML final e um screenshot em data/inspect/). Nada de lógica de scraping ainda. Ao final, rode pytest e ruff, e faça o commit inicial.

**Fase 1 — Core.** 

> Implemente app/db.py (SQLite: tabela publications com hash único, funções is_new/mark_sent), app/scrapers/base.py (BaseScraper com fetch abstrato, helpers de http com retry/timeout e de playwright), app/scrapers/registry.py lendo portals.yaml, app/downloader.py e app/cli.py com o comando `run --portal X --dry-run` que imprime as publicações encontradas sem enviar nada. Testes unitários do dedupe. Commit ao final.

**Fase 2 — Primeiros adapters (os fáceis).**

> Implemente os adapters juslaboris_feed (feed Atom do TST — parse de XML, sem browser) e comunica_pje. Para o comunica_pje: inspecione https://comunica.pje.jus.br/consulta?siglaTribunal=STJ&meio=D com scripts/inspect.py e com as ferramentas de rede; verifique se o site consome uma API JSON e, se sim, use a API diretamente via httpx em vez de scraping. Valide com `python -m app.cli run --portal TST --dry-run` e `--portal STJDJN --dry-run`. Fixtures + testes. Commit.

**Fase 3 — Adapters com Playwright.** Um prompt por portal (ou use o slash command `/novo-portal`), nesta ordem de dificuldade: `tcdf` (a URL segue padrão por data — teste antes se dá para montar a URL do PDF diretamente), `trf1_biblioteca`, `tcu`, `stf_dje`, `stj` (atenção: publica um ZIP com muitos PDFs — baixar o ZIP e listar o conteúdo no e-mail), `dejt`, `tjdft`, `trf1_atas`. Modelo de prompt:

> Implemente o adapter tcdf. Primeiro inspecione https://doe.tc.df.gov.br com scripts/inspect.py e descubra como listar a edição mais recente e o link do PDF (observe que URLs como /O/2026/104 sugerem padrão data/edição). Prefira montar URLs previsíveis a automatizar o browser. Depois valide com --dry-run, grave fixture, escreva teste e commite.

**Fase 4 — E-mail.**

> Implemente app/mailer.py com aiosmtplib: um e-mail HTML por ciclo, agrupado por portal, listando título/data/link de cada publicação nova, anexando arquivos até MAX_ATTACH_MB (env, padrão 15) e incluindo apenas links quando exceder. Configuração 100% via env (ver .env.example). Adicione ao cli o comando `send-test` que envia um e-mail de teste. Teste unitário montando a mensagem sem enviar. Commit.

**Fase 5 — Scheduler + API.**

> Implemente app/scheduler.py com APScheduler (intervalo via env SCAN_INTERVAL_MINUTES) executando o pipeline completo com isolamento de falhas por portal, e app/main.py (FastAPI) com GET /health, POST /run, GET /portals e GET /publications?limit=50. O scheduler inicia junto com o app (lifespan). Commit.

**Fase 6 — Docker/Deploy.**

> Crie o Dockerfile (base compatível com linux/arm64, instalando chromium do Playwright com dependências) e o docker-compose.yml com restart: unless-stopped, volume ./data, env_file .env e healthcheck no /health. Documente no README o passo a passo de deploy na Oracle A1. Valide com docker compose up --build. Commit.

### 2.6 Como você valida cada fase

Sempre com o mesmo ritual: `pytest -q`, depois `python -m app.cli run --portal <X> --dry-run` olhando a saída real, depois leitura do diff (`git diff` ou o resumo que o agente mostra). Se algo estiver errado, diga ao agente exatamente o sintoma ("o adapter do TCU retornou lista vazia; o screenshot em data/inspect mostra que a lista carrega depois de um clique na aba Y") — feedback concreto é o que faz o agente convergir rápido.

---

## Parte 3 — Arquitetura da aplicação (referência)

### 3.1 O contrato que unifica portais diferentes

A heterogeneidade dos portais é resolvida por um único contrato:

```python
class BaseScraper(ABC):
    def __init__(self, portal: PortalConfig): ...
    @abstractmethod
    async def fetch(self) -> list[Publication]:
        """Retorna as publicações visíveis hoje no portal (o dedupe
        decide o que é novo)."""
```

Cada portal vira um arquivo de 40–120 linhas. Adicionar portal novo = 1 entrada no YAML + 1 adapter + 1 teste — exatamente o fluxo do slash command `/novo-portal`. Quando o Lupa crescer, esse mesmo contrato vira o plugin system do SaaS.

### 3.2 Hierarquia de estratégias (do mais estável ao mais frágil)

Ordem de preferência ao investigar um portal: API JSON não documentada (abra o DevTools/inspect e veja os XHR — o Comunica PJe, por exemplo, é um front que consome API) → feed RSS/Atom (o JusLaboris do TST tem, você mesmo achou) → URL previsível de arquivo (padrões com data, como o TCDF sugere) → scraping de HTML estático (httpx+selectolax) → Playwright (último recurso). Essa hierarquia deve estar no CLAUDE.md (está) porque muda radicalmente a estabilidade e o custo de manutenção.

### 3.3 Particularidades dos seus portais

O portal do Comunica PJe (comunica.pje.jus.br) merece atenção especial: ele é o DJEN, que centraliza diários de muitos tribunais do país — um único adapter parametrizado por `siglaTribunal` pode, no futuro, cobrir dezenas de diários estaduais de uma vez, o que é ouro para o Lupa. O STJ tem três fontes; comece pelo `processo.stj.jus.br/processo/dj/init` (ZIP com os PDFs do dia) e pelo DJEN, que juntos cobrem o conteúdo. O TRF1 biblioteca atende JFDFDJN e TRFDJN com um adapter só. O DEJT atende TST e TRT10 (o site do TRT10 aponta para o DEJT como diário oficial). Sobre o "TRF1 PJe 1º e 2º grau" e "Atas de Julgamento" que você não encontrou: as intimações do PJe do TRF1 são publicadas justamente via DJEN/Comunica PJe (`siglaTribunal=TRF1`), então o adapter comunica_pje provavelmente resolve os dois casos — vale confirmar durante a Fase 2.

### 3.4 E-mail

Um e-mail por ciclo (não um por publicação — caixa de entrada agradece), HTML simples agrupado por portal, anexos até ~15 MB somados e links para o restante. Variáveis: `SMTP_HOST/PORT/USER/PASSWORD/TLS`, `MAIL_FROM`, `MAIL_TO` (lista separada por vírgula). Com Gmail, use senha de app; para volume maior no futuro, um SMTP transacional (SES, Resend, Brevo) evita cair em spam.

---

## Parte 4 — Deploy na Oracle A1 (ARM64)

A A1 é aarch64 — o único cuidado real é o Chromium do Playwright, que funciona em ARM64 Linux desde que instalado com dependências. Dockerfile de referência:

```dockerfile
FROM python:3.12-slim-bookworm
WORKDIR /srv/app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
RUN playwright install --with-deps chromium
COPY . .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
services:
  lupa-diarios:
    build: .
    restart: unless-stopped
    env_file: .env
    ports: ["8000:8000"]
    volumes: ["./data:/srv/app/data"]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request as u;u.urlopen('http://localhost:8000/health')"]
      interval: 60s
      timeout: 10s
      retries: 3
```

Na VM: instale Docker (`curl -fsSL https://get.docker.com | sh`), clone o repo, preencha o `.env`, `docker compose up -d --build`. O `restart: unless-stopped` + Docker iniciando no boot (`sudo systemctl enable docker`) garantem o "sempre online". Se for expor a API publicamente, lembre que na Oracle é preciso liberar a porta em dois lugares: Security List/NSG do painel OCI e o firewall interno da VM (iptables/ufw) — para começar, não exponha; acesse via SSH ou túnel. Rotina de logs: `docker compose logs -f --tail 100`.

Dica: você pode instalar o Claude Code na própria VM e usá-lo para depurar em produção ("o adapter do STF parou de encontrar publicações; investigue com scripts/inspect.py e corrija").

---

## Parte 5 — Ponte para o SaaS Lupa

O desenho já deixa o caminho pronto: o pacote `app/scrapers` + `models` + `db` vira uma lib interna; o e-mail é só o primeiro "notifier" (a interface `Notifier.send(publications)` permite plugar webhook, WhatsApp, painel do Lupa depois); o SQLite migra para Postgres quando houver multi-tenant; e filtros por palavra-chave/OAB/nome de parte — que é onde o Lupa gera valor de verdade — entram como uma etapa entre o dedupe e o notifier. Nada disso precisa existir agora; o que importa é que a arquitetura não bloqueia nenhum desses passos.

---

## Apêndice — Checklist de informações para fecharmos o funcional

Antes da Fase 4/5 preciso que você defina: frequência de verificação (a cada hora? 2x ao dia? diários costumam sair 1x/dia em horário fixo); destinatários (um e-mail seu ou lista); anexar PDFs ou enviar só links (diários como o do STJ passam facilmente de 50 MB); provedor SMTP que você já tem; e se já quer filtro por palavras-chave no MVP ou o diário inteiro. Com essas respostas, o `.env.example` e o SPEC.md ficam fechados e o desenvolvimento inteiro cabe em poucos dias de sessões com o Claude Code.