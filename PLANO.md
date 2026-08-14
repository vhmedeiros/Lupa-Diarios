# PLANO.md — Lupa Diários (MVP de hoje, 13/08/2026)

Lido antes de escrever este plano: `CLAUDE.md`, `SPEC.md`, `portals.yaml`.
Nenhum conflito encontrado entre `CLAUDE.md` e `SPEC.md` — este plano segue
os dois à risca. Onde este plano precisa de uma dependência não listada
explicitamente em `CLAUDE.md` (caso do `pyyaml`), isso é sinalizado na
fase correspondente, não decidido em silêncio.

---

## 1. Arquitetura

### Pipeline (texto)

```
scheduler (APScheduler, cron SCAN_CRON, TZ America/Sao_Paulo)
  └─▶ para cada portal com enabled=true em portals.yaml:
        try: adapter.fetch() -> list[Publication]
        except: loga erro do portal e segue para o próximo (R4)
  └─▶ dedupe: para cada Publication, calcula content_hash;
        se já existe em seen_hashes, descarta; senão grava em
        seen_hashes e em publications
  └─▶ downloader: baixa os arquivos das publicações novas para
        data/files/{portal}/{data}/, registra size_bytes em files (jsonb)
  └─▶ mailer: se houver >=1 publicação nova, monta UM e-mail HTML
        agrupado por portal (regra dos 15MB, R2) e envia via SMTP
  └─▶ grava sent_at nas publicações que entraram no e-mail

job diário de retenção (mesmo scheduler, 1x/dia):
  apaga de publications (+ arquivos em disco) as linhas com
  sent_at anterior a RETENTION_DAYS dias. NUNCA toca seen_hashes.
```

Os dois jobs (scan e retenção) são independentes: o job de retenção não
precisa que um ciclo de scan tenha acabado de rodar, e vice-versa.

### Árvore de arquivos completa

```
lupa-diarios/
├── app/
│   ├── __init__.py            # marca o pacote Python
│   ├── main.py                # cria a app FastAPI; lifespan roda create_all
│   │                          #   e inicia o scheduler; inclui as rotas
│   ├── config.py               # Settings (pydantic-settings) lendo .env
│   ├── db.py                   # engine async SQLAlchemy, sessionmaker, Base
│   ├── models.py                # ORM: Publication e SeenHash
│   ├── schemas.py                # modelos Pydantic de resposta da API
│   ├── registry.py               # carrega/valida portals.yaml; get_enabled_portals()
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py               # BaseScraper (ABC) + Publication (modelo
│   │   │                        #   intermediário, antes de virar linha do banco)
│   │   ├── tst_juslaboris.py     # adapter TST — feed Atom
│   │   ├── comunica_pje.py       # adapter STJDJN — API JSON do DJEN
│   │   ├── tcu.py                 # adapter TCU — API do btcu.apps.tcu.gov.br
│   │   ├── tcdf.py                 # adapter TCDF — URL previsível de edição/PDF
│   │   └── tjdft.py                 # adapter TJDFTDJN — URL previsível de PDF do DJe
│   ├── downloader.py                # baixa arquivos p/ data/files/{portal}/{data}/
│   ├── dedupe.py                     # calcula content_hash; filtra via seen_hashes
│   ├── mailer.py                      # monta e-mail HTML (regra 15MB) + envia (aiosmtplib)
│   ├── pipeline.py                     # orquestra um ciclo: fetch→dedupe→download→mail→sent_at
│   ├── retention.py                     # apaga publications+arquivos velhos; nunca toca seen_hashes
│   ├── scheduler.py                      # registra os jobs do APScheduler (scan + retenção)
│   ├── routers.py                         # /health /run /run/{portal} /portals /publications
│   └── cli.py                              # `python -m app.cli run|send-test`
├── scripts/
│   └── inspect.py                          # GET manual num portal; imprime status/headers/
│                                          #   trecho do body — usado ANTES de codar um adapter
├── tests/
│   ├── fixtures/                          # HTML/JSON/XML salvos de cada portal (sem rede)
│   ├── conftest.py                         # fixtures pytest (sessão de banco de teste)
│   ├── test_dedupe.py
│   ├── test_mailer.py
│   ├── test_retention.py
│   ├── test_downloader.py
│   ├── test_scrapers_tst.py
│   ├── test_scrapers_comunica_pje.py
│   ├── test_scrapers_tcu.py
│   ├── test_scrapers_tcdf.py
│   ├── test_scrapers_tjdft.py
│   └── test_api.py
├── data/files/                              # arquivos baixados, por portal/data (gitignored)
├── portals.yaml                              # fonte de verdade dos portais (já existe)
├── CLAUDE.md / SPEC.md / PLANO.md             # documentação e contrato (PLANO.md é este arquivo)
├── .env.example                                # variáveis documentadas (já existe)
├── pyproject.toml / uv.lock                     # dependências via uv
├── Dockerfile                                    # imagem da app (Python 3.13 + uv)
├── docker-compose.yml                             # serviços app + db (postgres:17-alpine)
└── .gitignore                                      # .venv, .env, data/files, __pycache__...
```

**Nota (14/08/2026, ver seção 9):** esta árvore descreve o plano *antes*
da implementação. O código real diverge em pontos conhecidos e já
documentados (`app/scrapers/tjdft.py` nunca foi criado, `tests/test_api.py`
virou `tests/test_routers.py`, e existem `tests/test_cli.py` e
`tests/test_scheduler.py` que não estavam previstos aqui) — ver `README.md`
seção "Inconsistência que vale registrar" e a seção 9.6 deste plano. Isso
não é retrabalho pendente, é só a árvore original ficando desatualizada
como registro histórico; `app/` é sempre a fonte de verdade.

---

## 2. Modelo de dados

Exatamente o que `SPEC.md` §4 define — nenhuma tabela extra (minimalismo é
requisito de negócio):

- **publications**: id (pk), portal_code, portal_name, title, published_at
  (date), page_url, summary (text, nullable), files (jsonb: lista de
  `{url, path, size_bytes, attached}`), content_hash (unique), created_at,
  sent_at (nullable). Índices em (portal_code, published_at) e sent_at.
- **seen_hashes**: content_hash (pk), first_seen_at.

`content_hash = sha256(portal_code + page_url + published_at ISO)`.

**Por que duas tabelas separadas** (e não uma só com uma flag "arquivada"):
`publications` guarda o conteúdo completo (título, resumo, caminho dos
arquivos) e é um **buffer operacional** — existe só para montar o e-mail e
some 3 dias depois (R3), porque este serviço não é um acervo. `seen_hashes`
guarda só o hash e uma data — é a **memória de dedupe** e precisa
sobreviver para sempre (ou até o portal parar de listar aquela publicação),
senão o mesmo item, ainda visível no site de origem depois que sua linha em
`publications` foi apagada pela retenção, pareceria "novo" de novo no
próximo ciclo e seria reenviado. Se fossem a mesma tabela, o job de
retenção teria que decidir linha a linha o que apagar e o que preservar —
mais lógica, mais risco de apagar dedupe por engano. Separar as tabelas
torna a regra do job de retenção uma única instrução SQL sem exceções.

---

## 3. Análise portal a portal (todos os 12 de `portals.yaml`)

Ordem de preferência de estratégia: API JSON escondida > feed RSS/Atom >
URL previsível de arquivo > HTML estático (httpx+selectolax) > Playwright.

| Código | Estratégia proposta | Risco | Justificativa (1 linha) |
|---|---|---|---|
| **TST** | Feed Atom (`juslaboris.tst.jus.br/feed/atom_1.0/site`) | **Baixo** | Testado agora: feed Atom válido, 25 entradas com datas de ago/2026, parse XML padrão, sem JS nem auth. |
| **STJDJN** | API JSON escondida (`comunicaapi.pje.jus.br/api/v1/comunicacao`) | **Baixo-médio** | API pública do DJEN, documentada em Swagger da CNJ e amplamente usada pela comunidade jurídica; falta confirmar parâmetros exatos de paginação/data via `inspect.py`. |
| **TCU** | API JSON escondida (`btcu.apps.tcu.gov.br`) — a confirmar | **Médio** | Achamos o padrão `btcu.apps.tcu.gov.br/api/obterDocumentoPdf/{id}` em resultados de busca, forte indício de uma API de listagem por trás; `portals.yaml` hoje marca `engine: playwright` — precisa ser revisto na fase do adapter se a API de listagem se confirmar. |
| **TCDF** | URL previsível de arquivo (`/O/{ano}/{edicao}`, a confirmar) | **Médio** | `doe.tc.df.gov.br` é um sistema lançado recentemente (~mar/2026); o `WebFetch` não retornou HTML estático (típico de SPA), então o padrão de URL do SPEC ainda não foi validado diretamente — `inspect.py` decide entre URL previsível e HTML estático antes de codar. |
| **TJDFTDJN** | URL previsível de arquivo (`pesquisadje-api.tjdft.jus.br/v1/diarios/pdf/{ano}/{numero}.pdf`) | **Médio** | Padrão de URL de PDF confirmado por busca, mas o sistema de consulta do TJDFT foi trocado em 23/09/2025 — falta confirmar se a numeração e a forma de descobrir o "PDF do dia" ainda seguem esse padrão. |
| **JFDFDJN** e **TRFDJN** (mesmo adapter `trf1_biblioteca`) | HTML estático a validar (`portals.yaml` assume Playwright) | **Médio-alto** | Portal institucional grande (Liferay); achamos evidência de outras APIs do TRF1 (`api-noticias-institucionais`), sugerindo que o CMS pode ter REST reaproveitável, mas não confirmado para a seção de diários — Playwright como fallback seguro. |
| **TRF1ATA** | HTML estático a validar (mesmo CMS do TRF1) | **Médio** | Provável tabela simples de PDFs (atas de distribuição), não veio evidência contrária nem a favor na busca; `portals.yaml` assume Playwright por precaução. |
| **STFDJE** | Playwright (procurar XHR/API antes de aceitar) | **Médio-alto** | Front confirmado como moderno/SPA (`digital.stf.jus.br`), sem API pública encontrada na busca; existe um sistema legado em ASP (`portal.stf.jus.br/servicos/dje`) mas não é a URL que `portals.yaml` define. |
| **STJ** | Playwright + download de ZIP diário | **Alto** | Combina front dinâmico com um ZIP grande contendo vários PDFs (é preciso listar o conteúdo do ZIP no e-mail e aplicar a regra dos 15MB a cada item) — maior complexidade de implementação, não só de scraping. |
| **TSTDJN** e **TRT10DJN** (mesmo adapter `dejt`) | Playwright | **Alto** | Busca não revelou API/feed público; o sistema tem inclusive tela de login para algumas funções, sinal de fluxo de navegação mais complexo. |

Observação de `SPEC.md` §10: intimações "TRF1 PJe" podem já estar
cobertas pelo DJEN (`comunica_pje` com `siglaTribunal=TRF1`) — vale
validar isso *antes* de investir tempo em JFDFDJN/TRFDJN num dia futuro,
porque pode eliminar a necessidade do adapter Playwright inteiramente.

**Nota (14/08/2026):** esta tabela é a análise original, feita ANTES de
qualquer implementação. Ela já se mostrou parcialmente errada nos dois
sentidos — algumas estratégias "Playwright" viraram HTTP simples (TCU,
TCDF, TJDFTDJN, TRFDJN, TSTDJN, TRT10DJN, todas confirmadas na prática) —,
e a seção 9.2 deste plano traz uma reavaliação, com evidência nova, dos
três últimos portais que restaram sem investigação (STFDJE, STJ,
TRF1ATA). Mantida aqui como registro histórico da decisão original.

---

## 4. Recorte do MVP de hoje

**Entram habilitados hoje (`enabled: true`):** TST, STJDJN, TCU, TCDF,
TJDFTDJN.

**Ficam `enabled: false`** (sessão curta de outro dia, um por vez):
JFDFDJN, TRFDJN, TRF1ATA, STFDJE, STJ, TSTDJN, TRT10DJN.

**Por quê estes 5:** são os únicos cinco portais cuja estratégia de
maior preferência (API/feed/URL previsível) tem evidência concreta —
nenhum deles precisa de Playwright. Isso não é coincidência de escopo:
é a decisão central deste plano para caber num único dia. Playwright
exige instalar binário de browser, é mais lento por natureza e mais
frágil a mudanças de layout — adiar todo portal que dependeria dele é o
que torna 18 fases pequenas viáveis em uma sessão. Cobertura: 2 tribunais
de contas (TCU federal, TCDF/DF), Justiça do Trabalho (TST), Justiça do
DF (TJDFTDJN) e o agregador DJEN para o STJ (STJDJN) — diversidade
razoável de fontes com o menor risco técnico disponível hoje.

---

## 5. Fases de execução

Cada fase termina com `uv run ruff check --fix . && uv run ruff format .`,
`uv run pytest -q` verde (quando já houver testes) e um commit. Nenhuma
fase depende de código de fase futura.

### Fase 1 — Setup do projeto
Rodar `uv init` (ou equivalente) e `uv python pin 3.13`; criar a árvore de
pastas da seção 1 com `__init__.py` vazios; `uv add fastapi
"uvicorn[standard]" httpx selectolax playwright sqlalchemy asyncpg
apscheduler aiosmtplib pydantic-settings pyyaml` e `uv add --dev ruff
pytest pytest-asyncio`. **Nota:** `pyyaml` não está listado explicitamente
em `CLAUDE.md`, mas é exigido pela própria arquitetura que o CLAUDE.md
define (`portals.yaml` como fonte de verdade) — adicionado por
necessidade, não por preferência. Configurar `ruff` no `pyproject.toml`.
Criar `.gitignore` (`.venv`, `.env`, `data/files/`, `__pycache__`, etc.).
Criar `scripts/inspect.py`: script simples que recebe uma URL, faz GET
com httpx (timeout 30s, User-Agent "LupaDiarios/1.0") e imprime status
code, content-type e os primeiros ~2000 caracteres do corpo. Não instalar
os binários de browser do Playwright ainda — nenhum portal do recorte de
hoje precisa (comando fica documentado no README/PLANO para quando for
necessário: `uv run playwright install --with-deps chromium`).

**Aceite:** `uv run python -c "import fastapi, sqlalchemy, httpx,
selectolax, playwright, apscheduler, aiosmtplib, pydantic_settings, yaml"`
sai sem erro; `uv run ruff check .` sem erros; `uv run python
scripts/inspect.py https://juslaboris.tst.jus.br/feed/atom_1.0/site`
imprime `status=200` e um trecho de XML.
**Commit:** "chore: setup do projeto e dependências"

### Fase 2 — Config e registry de portais (recorte do MVP)
Criar `app/config.py` (Settings lendo `.env`: DATABASE_URL, SCAN_CRON,
TZ, SMTP_*, MAIL_FROM, MAIL_TO, MAX_ATTACH_MB, RETENTION_DAYS,
JWT_SECRET reservado). Criar `app/registry.py`: carrega `portals.yaml`,
valida cada entrada com um modelo Pydantic (code, name, url, adapter,
engine, params, enabled) e expõe `get_enabled_portals()`. Editar
`portals.yaml`: `enabled: true` só em TST, STJDJN, TCU, TCDF, TJDFTDJN;
`enabled: false` nos outros 7 (essa edição é a aplicação do recorte da
seção 4 deste plano, não uma decisão nova).

**Aceite:** `uv run python -c "from app.registry import
get_enabled_portals; print(sorted(p.code for p in
get_enabled_portals()))"` imprime exatamente
`['STJDJN', 'TCDF', 'TCU', 'TJDFTDJN', 'TST']`.
**Commit:** "feat: registry de portais e recorte do MVP"

### Fase 3 — Esqueleto Docker Compose + FastAPI mínimo
Criar `Dockerfile` (Python 3.13 slim + uv, copia o projeto, roda
uvicorn). Criar `docker-compose.yml` com serviços `app` e `db`
(`postgres:17-alpine`, porta 5432 publicada para o host, volume
nomeado); variáveis de ambiente do `app` lidas de `.env`, exceto
`DATABASE_URL` do serviço `app`, que aponta para o host interno `db`
(diferente do `DATABASE_URL` usado por `uv run` fora do Docker, que
aponta para `localhost` — documentar essa diferença no `.env.example`).
Criar `app/main.py` com a app FastAPI e uma rota `GET /health` que por
enquanto só retorna `{"status": "ok"}` fixo (sem banco ainda).

**Aceite:** `docker compose up --build -d && curl -s
http://localhost:8000/health` retorna `{"status":"ok"}`; `docker compose
down`.
**Commit:** "feat: esqueleto docker compose e FastAPI minimo"

### Fase 4 — Modelo de dados + create_all + /health com banco
Criar `app/db.py` (engine assíncrono, sessionmaker, `Base`) e
`app/models.py` (`Publication`, `SeenHash` conforme seção 2). No
`lifespan` do `app/main.py`, chamar `create_all` na subida. Atualizar
`GET /health` para `{"status": "ok", "db": true, "last_run_at": null}`,
fazendo um `SELECT 1` real para popular `db`.

**Aceite:** `docker compose up --build -d && curl -s
http://localhost:8000/health` retorna `{"status":"ok","db":true,
"last_run_at":null}`; `docker compose exec db psql -U lupa -d
lupa_diarios -c "\dt"` lista `publications` e `seen_hashes`.
**Commit:** "feat: modelo de dados e create_all"

### Fase 5 — BaseScraper + dedupe
Criar `app/scrapers/base.py`: `Publication` (modelo Pydantic do
scraper: portal_code, portal_name, title, published_at, page_url,
summary, file_urls) e `BaseScraper` (ABC com `async def fetch(self) ->
list[Publication]`). Criar `app/dedupe.py`: função de hash
(`sha256(portal_code + page_url + published_at.isoformat())`) e função
assíncrona que recebe uma lista de `Publication`, consulta
`seen_hashes`, grava as novas (em `seen_hashes` e `publications`) e
retorna só as que eram novas. Criar `tests/conftest.py` com fixture de
sessão de banco de teste (usa o `db` do compose, já de pé; cada teste
roda dentro de uma transação revertida no teardown).

**Aceite:** `docker compose up -d db && uv run pytest tests/test_dedupe.py
-q` → `2 passed` (hash determinístico; segunda chamada com o mesmo hash
não retorna a publicação como nova).
**Commit:** "feat: dedupe com seen_hashes e testes"

### Fase 6 — Adapter TST (feed Atom)
Criar `tests/fixtures/tst_juslaboris_feed.xml` (salvar o feed real de
hoje). Implementar `app/scrapers/tst_juslaboris.py` usando httpx +
`xml.etree.ElementTree` (biblioteca padrão, sem nova dependência).
Criar `app/cli.py` com o comando `run --portal CODE --dry-run` mínimo:
resolve o adapter pelo `registry`, chama `fetch()`, imprime as
publicações (sem gravar nada, sem baixar arquivo, sem e-mail).

**Aceite:** `uv run pytest tests/test_scrapers_tst.py -q` → `1 passed`
(sem rede, usa a fixture); `uv run python -m app.cli run --portal TST
--dry-run` imprime uma lista de publicações reais do feed.
**Commit:** "feat: adapter TST (feed Atom) e cli dry-run"

### Fase 7 — Adapter STJDJN (comunica_pje / DJEN)
Rodar `uv run python scripts/inspect.py
"https://comunicaapi.pje.jus.br/api/v1/comunicacao?siglaTribunal=STJ&..."`
para confirmar parâmetros reais (data, paginação). Salvar
`tests/fixtures/comunica_pje_stj.json`. Implementar
`app/scrapers/comunica_pje.py`, parametrizado por `params.sigla_tribunal`
do `portals.yaml`.

**Aceite:** `uv run pytest tests/test_scrapers_comunica_pje.py -q` → `1
passed`; `uv run python -m app.cli run --portal STJDJN --dry-run` imprime
publicações reais.
**Commit:** "feat: adapter STJDJN (DJEN/comunica_pje)"

### Fase 8 — Adapter TCU
Rodar `scripts/inspect.py` em `btcu.apps.tcu.gov.br` para achar o
endpoint de listagem (não só o de PDF por id). Se em ~20 min não
confirmar uma API de listagem, parar e reportar ao usuário (a regra 2 do
executor) antes de partir para HTML estático ou Playwright — não é
decisão silenciosa. Salvar fixture. Implementar `app/scrapers/tcu.py`.
Se a estratégia mudar de `playwright` para `http`, atualizar o `engine`
de TCU em `portals.yaml` nesta mesma fase.

**Aceite:** `uv run pytest tests/test_scrapers_tcu.py -q` → `1 passed`;
`uv run python -m app.cli run --portal TCU --dry-run` imprime a edição
mais recente do boletim.
**Commit:** "feat: adapter TCU"

### Fase 9 — Adapter TCDF
Rodar `scripts/inspect.py` em `doe.tc.df.gov.br` para confirmar se é
HTML estático com padrão de URL `/O/{ano}/{edicao}` ou se exige
JS. Salvar fixture. Implementar `app/scrapers/tcdf.py`.

**Aceite:** `uv run pytest tests/test_scrapers_tcdf.py -q` → `1 passed`;
`uv run python -m app.cli run --portal TCDF --dry-run` imprime a edição
mais recente.
**Commit:** "feat: adapter TCDF"

### Fase 10 — Adapter TJDFTDJN
Rodar `scripts/inspect.py` para confirmar o padrão
`pesquisadje-api.tjdft.jus.br/v1/diarios/pdf/{ano}/{numero}.pdf` e como
descobrir o número do dia corrente. Salvar fixture. Implementar
`app/scrapers/tjdft.py`.

**Aceite:** `uv run pytest tests/test_scrapers_tjdft.py -q` → `1 passed`;
`uv run python -m app.cli run --portal TJDFTDJN --dry-run` imprime o DJe
mais recente.
**Commit:** "feat: adapter TJDFTDJN"

### Fase 11 — Downloader de arquivos
Implementar `app/downloader.py`: baixa cada `file_url` de uma
`Publication` para `data/files/{portal_code}/{published_at}/`, timeout
30s, retry 3x com backoff, User-Agent "LupaDiarios/1.0", registra
`size_bytes`. Testar com `httpx.MockTransport` (recurso nativo do
httpx, sem nova dependência) simulando respostas — sem rede real.

**Aceite:** `uv run pytest tests/test_downloader.py -q` → verde.
**Commit:** "feat: downloader de arquivos"

### Fase 12 — Mailer: regra dos 15MB (sem enviar de verdade)
Implementar `app/mailer.py`: `build_email(publications) -> (subject,
html_body, attachments)`. Aplica R2: soma os `size_bytes` na ordem de
descoberta (por portal, depois por `published_at`); enquanto a soma
não ultrapassar `MAX_ATTACH_MB`, o arquivo é anexado; o primeiro que
faria a soma estourar (e todos os seguintes) vira link no corpo com
aviso de tamanho. Nenhuma publicação é omitida. Teste cobre: soma dentro
do limite (tudo anexado), soma estourando no meio (parte anexada, parte
vira link), arquivo individual maior que o limite sozinho.

**Aceite:** `uv run pytest tests/test_mailer.py -q` → verde, sem chamar
SMTP real.
**Commit:** "feat: regra dos 15MB no mailer"

### Fase 13 — send-test (checkpoint manual de SMTP real)
Adicionar `send_email` (aiosmtplib, STARTTLS) ao `app/mailer.py` e o
comando `send-test` ao `app/cli.py`.

**Aceite:** preencher `.env` com credenciais reais do MailGrid; `uv run
python -m app.cli send-test` termina com código 0 e imprime "e-mail
enviado"; **verificação manual:** o e-mail chega na caixa de entrada
configurada em `MAIL_TO` (checkpoint do usuário, não automatizável).
**Commit:** "feat: send-test via SMTP"

### Fase 14 — Pipeline completo + CLI run + endpoints /run
Implementar `app/pipeline.py` (fetch→dedupe→download→mailer→sent_at,
try/except por portal — R4). Estender `app/cli.py` com `run [--portal
CODE]` sem `--dry-run`. Criar `POST /run` e `POST /run/{portal_code}`
em `app/routers.py` (dispara o pipeline de forma assíncrona).

**Aceite:** com `.env` configurado (MAIL_TO = e-mail do próprio usuário),
`uv run python -m app.cli run` roda os 5 portais do recorte, imprime "N
publicações enviadas" e o e-mail chega (verificação manual); rodando
`uv run python -m app.cli run` de novo imediatamente, imprime "0
publicações novas, nenhum e-mail enviado" e nenhum e-mail chega
(dedupe comprovado, critério 5 do `SPEC.md` §11).
**Commit:** "feat: pipeline completo end-to-end"

### Fase 15 — Job de retenção
Implementar `app/retention.py`: apaga de `publications` (+ arquivos em
`data/files/`) as linhas com `sent_at` anterior a `RETENTION_DAYS` dias;
não toca `seen_hashes` em nenhuma linha de código dessa função. Teste:
insere uma `publication` com `sent_at` antigo e seu hash correspondente
em `seen_hashes`, roda a retenção, confirma que a linha de
`publications` sumiu e a de `seen_hashes` continua lá.

**Aceite:** `uv run pytest tests/test_retention.py -q` → verde,
incluindo o teste que afirma explicitamente que `seen_hashes` não foi
tocada.
**Commit:** "feat: job de retencao"

### Fase 16 — Scheduler
Implementar `app/scheduler.py`: registra no APScheduler o job de scan
(cron `SCAN_CRON`, TZ `America/Sao_Paulo`) chamando o pipeline, e o job
diário de retenção. Chamar `start()` no `lifespan` do `app/main.py`, e
logar (módulo `logging`, sem `print`) os próximos horários agendados na
subida.

**Aceite:** `docker compose up --build -d && docker compose logs app
--tail 50 | grep -i scheduler` mostra uma linha confirmando os dois jobs
agendados com seus próximos horários.
**Commit:** "feat: scheduler com scan e retencao"

### Fase 17 — API: /portals e /publications
Completar `app/routers.py` com `GET /portals` (lista do `portals.yaml`
com `enabled` e última execução) e `GET /publications?limit=50`.
Testar com `fastapi.testclient.TestClient` (usa o `httpx` já instalado,
sem nova dependência).

**Aceite:** `uv run pytest tests/test_api.py -q` → verde.
**Commit:** "feat: endpoints /portals e /publications"

### Fase 18 — Fechamento do dia
Sem código novo: rodar a suíte completa e o checklist do `SPEC.md` §11
na ordem (itens 1 a 6), incluindo `docker compose up --build` limpo.

**Aceite:** `uv run pytest -q` → todos verdes; `docker compose up
--build -d && curl -s http://localhost:8000/health` → `{"status":"ok",
"db":true,...}`.
**Commit:** "chore: MVP funcional"

---

## 6. Riscos de não terminar hoje

1. **APIs/URLs previsíveis de TCU, TCDF e TJDFTDJN podem não se confirmar**
   como a pesquisa sugeriu (achados por busca podem estar desatualizados).
   Mitigação: cada fase de adapter começa com `scripts/inspect.py`,
   time-boxed (~15-20 min); se não confirmar, o executor para e relata
   ao usuário (regra 2 do executor) em vez de trocar de estratégia
   sozinho — as fases são independentes, então isso atrasa só aquele
   portal, não os outros.
2. **SMTP/MailGrid pode falhar** por config de host/porta ou SPF/DKIM do
   domínio. Mitigação: Fase 13 (send-test) é isolada e cedo no dia, dando
   tempo de corrigir antes de fases que dependem de e-mail real (14 em
   diante).
3. **18 fases podem não caber num dia.** Mitigação: fases pequenas e
   independentes — se o tempo acabar, cortar as últimas (17 e 18 mais
   facilmente que 12, 14, 15, que são o núcleo). Dedupe, regra dos 15MB e
   retenção NUNCA são cortados (são os 3 mecanismos mais caros de
   quebrar: e-mail duplicado, anexo gigante rejeitado pelo servidor de
   SMTP, banco crescendo sem limite).
4. **Limite de uso do Claude Pro** pode interromper sessões longas.
   Mitigação: cada fase termina em commit — nada se perde, retoma-se de
   onde parou.
5. **Ambiguidades da seção 7 não respondidas a tempo** podem atrasar a
   Fase 12. Mitigação: se não houver resposta, seguir a leitura mais
   literal do `SPEC.md` (ver premissas assumidas abaixo) e seguir em
   frente — ajustar depois é uma fase isolada e já coberta por teste.

---

## 7. Perguntas para o usuário

1. **Regra dos 15MB é global por e-mail ou por portal?** `SPEC.md` diz
   "anexar arquivos até a soma de MAX_ATTACH_MB" no contexto de "UM
   e-mail por ciclo" (R5), o que leio como limite **global** (soma de
   todos os portais do ciclo, não 15MB por portal). Vou seguir essa
   leitura na Fase 12 salvo confirmação em contrário.
2. **Critério de desempate quando o orçamento de 15MB não cobre todos os
   arquivos**: anexar por ordem de descoberta (por portal, depois por
   `published_at`) até estourar, ou priorizar arquivos menores para
   maximizar quantidade de anexos? Vou seguir "ordem de descoberta" na
   Fase 12 salvo confirmação em contrário — é mais previsível e mais
   simples de testar.
3. **Confirma o recorte de hoje** (TST, STJDJN, TCU, TCDF, TJDFTDJN — os
   5 portais sem Playwright) e que os outros 7 ficam `enabled: false`
   para sessões futuras, um portal (ou par de portais que compartilham
   adapter) por sessão?

Se não houver objeção às premissas assumidas em (1) e (2), não é preciso
responder — o plano segue com elas.

---

## 8. Fases 19+ — Expansão: TRF1 e TST/TRT10 no DJEN (sessão de 14/08/2026)

Lido antes de estender este plano: `CLAUDE.md`, `SPEC.md`, `portals.yaml`
(estado atual, depois das Fases 1-18: TST, STJDJN, TCU, TCDF e TJDFTDJN
`enabled: true`; os outros 7 `enabled: false`). Nenhuma mudança de stack
ou de regra de negócio é necessária aqui — esta seção só habilita mais
portais reaproveitando um adapter já em produção. Nota lateral: também
descobri, lendo o código já commitado, que `TJDFTDJN` acabou implementado
reaproveitando `comunica_pje` (`params.sigla_tribunal: TJDFT`) em vez do
`app/scrapers/tjdft.py`/URL previsível que a Fase 10 original previa — a
árvore de arquivos da seção 1 e a Fase 10 ficam como registro histórico da
decisão de planejamento, não como o que existe hoje no repositório. Essa
mesma dinâmica (reaproveitar `comunica_pje` em vez de escrever um adapter
novo) é exatamente o que a investigação desta seção encontrou de novo para
os quatro portais abaixo.

### 8.1 O que mudou desde a análise original da seção 3

A seção 3 deste plano foi escrita **antes de qualquer implementação** e
supôs `engine: playwright` tanto para JFDFDJN/TRFDJN (adapter
`trf1_biblioteca`, nunca implementado) quanto para TSTDJN/TRT10DJN
(adapter `dejt`, nunca implementado). Investigação real feita agora por
`WebFetch`/`WebSearch` (não tenho acesso a `scripts/inspect.py` nem a
rodar comandos — essa parte cabe ao executor) encontrou evidência forte
de que os quatro portais podem ser cobertos pelo adapter `comunica_pje`
já implementado e em produção (hoje usado por STJDJN e TJDFTDJN), **sem
escrever nenhum adapter novo**:

- A própria página do TRF1 para a qual `portals.yaml` aponta JFDFDJN e
  TRFDJN (`trf1.jus.br/trf1/biblioteca/diarios-da-justica`) traz, para o
  acesso a diários correntes, um link direto para
  `https://comunica.pje.jus.br/consulta?siglaTribunal=TRF1` — o próprio
  TRF1 direciona ao DJEN para diários atuais; o resto da página é acervo
  histórico (e-DJF1 2009-2020), irrelevante para um buffer de 3 dias.
- O CNJ confirma publicamente que o TRF1 usa o DJEN desde 09/12/2020 e
  descreve a Central Nacional de Comunicações como instrumento oficial
  "em 1º e 2º grau" do tribunal sob a mesma `siglaTribunal` — não achei
  evidência de uma sigla separada para a Seção Judiciária do DF (1º grau,
  seria o alvo natural de JFDFDJN).
- O CNJ e o próprio TST confirmam que o DJEN substituiu o DEJT como
  instrumento oficial de publicação dos atos do PJe na Justiça do
  Trabalho a partir de 01/08/2024, mantendo o DEJT só para "matérias
  administrativas" (fora do escopo de um serviço de diário de
  intimações). TST está no DJEN desde então; os 24 TRTs também
  (inclusive TRT10).
- Um resultado de busca indexado mostra uma URL real de
  `comunicaapi.pje.jus.br/api/v1/comunicacao/.../certidao` para "Tribunal
  Regional Federal da 1ª Região", confirmando que a API tem conteúdo real
  para esse tribunal — a mesma API já usada em produção neste projeto.

Não consegui bater diretamente na API (`comunicaapi.pje.jus.br`) nem no
front (`comunica.pje.jus.br`) via `WebFetch`: as chamadas voltaram
`403 Forbidden`, provavelmente um WAF/anti-bot que não reconhece o
user-agent do `WebFetch` — isso é uma **limitação da minha ferramenta de
investigação**, não evidência de que a API não funcione (ela já funciona
em produção neste projeto via `httpx` com o User-Agent
`LupaDiarios/1.0`, exatamente como `scripts/inspect.py` faz, e como a
Fase 7 já confirmou para STJ). Por isso cada fase abaixo **começa** com o
executor confirmando com `scripts/inspect.py` de verdade, no mesmo
timebox e mesma disciplina de "parar e reportar" da Fase 8 (TCU) — eu não
decido por evidência indireta, peço confirmação direta antes de qualquer
commit.

### 8.2 Análise portal a portal (JFDFDJN, TRFDJN, TSTDJN, TRT10DJN)

| Código | Estratégia proposta | Risco | Justificativa (1 linha) |
|---|---|---|---|
| **TRFDJN** | Reaproveitar `comunica_pje` (`sigla_tribunal: TRF1`) — zero adapter novo | **Baixo** | TRF1 está no DJEN desde 2020, a própria página institucional do TRF1 aponta para lá, e a API é a mesma já em produção (STJDJN/TJDFTDJN). |
| **JFDFDJN** | Mesma fonte que TRFDJN (`siglaTribunal=TRF1` parece cobrir 1º e 2º grau) — ver pergunta 1 (8.5) | **Baixo tecnicamente, decisão de produto pendente** | Não achei sigla separada para a Seção Judiciária do DF — habilitar os dois como portais distintos arriscaria e-mail duplicado (mesma publicação, `portal_code` diferente → hash diferente no dedupe). |
| **TSTDJN** | Reaproveitar `comunica_pje` (`sigla_tribunal: TST`) — zero adapter novo | **Baixo** | TST está no DJEN desde 01/08/2024 (confirmado pelo próprio TST/CNJ); o DEJT (URL que `portals.yaml` aponta hoje) ficou só com conteúdo administrativo desde então — fora do escopo de "diário de intimações" deste projeto. |
| **TRT10DJN** | Reaproveitar `comunica_pje` (`sigla_tribunal: TRT10`) — zero adapter novo | **Baixo** | Mesma migração nacional do DJEN cobre todos os 24 TRTs desde 01/08/2024, inclusive o TRT10; padrão de sigla `TRTn` confirmado por uma URL real indexada (`siglaTribunal=TRT1`). |

**Nota para não confundir com o portal `TST` já habilitado:** `TST`
(feed Atom de `juslaboris.tst.jus.br`) é a biblioteca digital jurídica do
TST (jurisprudência/publicações), uma fonte totalmente diferente de
`TSTDJN` (intimações processuais do DJEN) — habilitar `TSTDJN` não
duplica o conteúdo de `TST`.

Consequência prática: nenhum dos quatro portais parece precisar de
Playwright, ao contrário do que os nomes de adapter em `portals.yaml`
sugerem hoje (`trf1_biblioteca`, `dejt`, nenhum dos dois implementado).
Por isso nenhuma fase abaixo instala
`uv run playwright install --with-deps chromium`. Se a confirmação por
`scripts/inspect.py` falhar em qualquer uma delas, a fase correspondente
para e reporta ao usuário (mesma regra da Fase 8) em vez de escrever um
adapter Playwright por conta própria — isso ficaria para uma sessão
futura à parte, fora deste plano.

### 8.3 Fases de execução

Mesma disciplina das Fases 1-18: cada fase termina com
`uv run ruff check --fix . && uv run ruff format .`, `uv run pytest -q`
verde e um commit; nenhuma fase depende de código de fase futura.

### Fase 19 — TRF1 no DJEN (habilita TRFDJN; decide o destino de JFDFDJN)
Rodar `uv run python scripts/inspect.py
"https://comunicaapi.pje.jus.br/api/v1/comunicacao?siglaTribunal=TRF1&dataDisponibilizacaoInicio=<hoje>&dataDisponibilizacaoFim=<hoje>&itensPorPagina=50&pagina=1"`
(data de hoje em ISO) para confirmar que a API devolve itens reais para
`siglaTribunal=TRF1`. Nesse mesmo passo, inspecionar o campo
`orgaoJulgador` dos itens retornados para checar se aparecem tanto
juízos de 1º grau (ex.: contendo "Vara Federal" ou "Seção Judiciária")
quanto de 2º grau (ex.: "Turma", "Gabinete", "Desembargador") — isso
confirma ou refuta a hipótese da seção 8.1 de que uma única
`siglaTribunal=TRF1` cobre as duas instâncias. Se em ~20 min não
confirmar itens reais, parar e reportar ao usuário antes de prosseguir
(mesma regra da Fase 8) em vez de partir para Playwright por conta
própria. Salvar `tests/fixtures/comunica_pje_trf1.json` com uma amostra
real. Adicionar `test_parse_page_returns_publications_trf1` em
`tests/test_scrapers_comunica_pje.py` (mesmo padrão dos testes já
existentes nesse arquivo, só trocando a fixture e as asserções de
`portal_code`/`page_url`). Atualizar `portals.yaml`: `TRFDJN` passa a
`adapter: comunica_pje`, `engine: http`,
`params: {sigla_tribunal: TRF1}` (troca o atual `params: {secao: "TRF1"}`,
que não é um parâmetro que o adapter lê), `enabled: true`. `JFDFDJN`
segue conforme a resposta à pergunta 1 (seção 8.5); por padrão, continua
`enabled: false`, com um comentário no YAML explicando que o conteúdo já
é coberto por `TRFDJN` via DJEN — a menos que o usuário responda diferente
antes desta fase rodar.

**Aceite:** `uv run pytest tests/test_scrapers_comunica_pje.py -q` → `3
passed`; `uv run python -m app.cli run --portal TRFDJN --dry-run` imprime
publicações reais do dia.
**Commit:** "feat: habilita TRFDJN reaproveitando comunica_pje (DJEN)"

### Fase 20 — TST no DJEN (habilita TSTDJN)
Rodar `uv run python scripts/inspect.py
"https://comunicaapi.pje.jus.br/api/v1/comunicacao?siglaTribunal=TST&dataDisponibilizacaoInicio=<hoje>&dataDisponibilizacaoFim=<hoje>&itensPorPagina=50&pagina=1"`
para confirmar itens reais. Timebox ~20 min; se não confirmar, parar e
reportar ao usuário (mesma regra da Fase 8). Salvar
`tests/fixtures/comunica_pje_tst.json`. Adicionar
`test_parse_page_returns_publications_tst` em
`tests/test_scrapers_comunica_pje.py`. Atualizar `portals.yaml`:
`TSTDJN` → `adapter: comunica_pje`, `engine: http`,
`params: {sigla_tribunal: TST}`, `enabled: true`.

**Aceite:** `uv run pytest tests/test_scrapers_comunica_pje.py -q` → `4
passed`; `uv run python -m app.cli run --portal TSTDJN --dry-run` imprime
publicações reais do dia.
**Commit:** "feat: habilita TSTDJN reaproveitando comunica_pje (DJEN)"

### Fase 21 — TRT10 no DJEN (habilita TRT10DJN)
Rodar `uv run python scripts/inspect.py
"https://comunicaapi.pje.jus.br/api/v1/comunicacao?siglaTribunal=TRT10&dataDisponibilizacaoInicio=<hoje>&dataDisponibilizacaoFim=<hoje>&itensPorPagina=50&pagina=1"`
para confirmar itens reais. Timebox ~20 min; se não confirmar, parar e
reportar ao usuário (mesma regra da Fase 8). Salvar
`tests/fixtures/comunica_pje_trt10.json`. Adicionar
`test_parse_page_returns_publications_trt10` em
`tests/test_scrapers_comunica_pje.py`. Atualizar `portals.yaml`:
`TRT10DJN` → `adapter: comunica_pje`, `engine: http`,
`params: {sigla_tribunal: TRT10}` (troca o atual
`params: {tribunal: "TRT da 10ª Região"}`, que não é o formato que o
adapter lê), `enabled: true`.

**Aceite:** `uv run pytest tests/test_scrapers_comunica_pje.py -q` → `5
passed`; `uv run python -m app.cli run --portal TRT10DJN --dry-run`
imprime publicações reais do dia.
**Commit:** "feat: habilita TRT10DJN reaproveitando comunica_pje (DJEN)"

### Fase 22 — Fechamento da expansão
Sem código novo: rodar a suíte completa e, com `.env` configurado, rodar
`uv run python -m app.cli run --dry-run` sem `--portal` para conferir que
todos os portais agora habilitados (os 5 do MVP + TRFDJN + TSTDJN +
TRT10DJN, e JFDFDJN se a pergunta 1 da seção 8.5 tiver sido respondida
com "manter habilitado") rodam num único ciclo sem exceção não tratada
(R4 — falha em um portal não pode derrubar os demais).

**Aceite:** `uv run pytest -q` → todos verdes; `uv run python -m app.cli
run --dry-run` imprime publicações de cada portal habilitado, sem
traceback.
**Commit:** "chore: expansão TRF1/TST/TRT10 no DJEN concluída"

### 8.4 Riscos desta expansão

1. **A hipótese de reaproveitamento pode não se confirmar** no
   `scripts/inspect.py` real — minha evidência é indireta (busca e
   leitura de páginas públicas), já que `WebFetch` tomou 403 direto na
   API e no front. Mitigação: cada fase começa com essa confirmação,
   time-boxed, e para/reporta se falhar, em vez de decidir Playwright
   sozinha.
2. **JFDFDJN pode ter conteúdo distinto de TRFDJN** se a Seção Judiciária
   do DF usar, na prática, uma sigla própria que a investigação por fora
   não encontrou. Mitigação: a Fase 19 verifica isso olhando o campo
   `orgaoJulgador` dos itens reais devolvidos por `siglaTribunal=TRF1`;
   se aparecer evidência de que 1º grau não está coberto, a fase para e
   reporta em vez de assumir.
3. **Volume diário desconhecido para TRF1/TST/TRT10** — podem ser maiores
   que o do STJ (~13 mil comunicações/dia, que já exige paginação e
   respeita um rate limit de 20 requisições/janela). Mitigação: as Fases
   19-21 reaproveitam a paginação e o controle de rate limit já
   implementados em `comunica_pje.py` (Fase 7); o risco é operacional
   (ciclo mais lento naquele portal), não de código novo a escrever.

### 8.5 Perguntas para o usuário

1. **JFDFDJN e TRFDJN parecem ser a mesma fonte de dados.** A
   investigação não achou uma `siglaTribunal` separada para a Seção
   Judiciária do DF (1º grau) — tudo indica que `siglaTribunal=TRF1` já
   cobre 1º e 2º grau. Se isso se confirmar na Fase 19, habilitar os dois
   códigos como portais distintos entregaria a **mesma** publicação duas
   vezes no e-mail (uma vez agrupada em "JFDFDJN", outra em "TRFDJN"),
   porque o dedupe usa `portal_code` no hash (`SPEC.md` §4) — publicações
   idênticas em conteúdo teriam hashes diferentes. Por isso a Fase 19
   assume, por padrão, que **só `TRFDJN` fica habilitado** e `JFDFDJN`
   continua `enabled: false`, documentado como redundante. Confirma essa
   leitura, ou prefere: (a) apagar `JFDFDJN` de `portals.yaml` de vez, já
   que seria redundante; (b) investigar mais a fundo (fora deste plano)
   se dá para filtrar por `orgaoJulgador` e manter os dois sem duplicar;
   ou (c) aceitar a duplicação mesmo assim, por algum motivo de negócio
   que eu não conheço?
2. **Não tive acesso a `scripts/inspect.py` nem a rodar comandos** — as
   evidências das seções 8.1/8.2 vêm de busca e leitura de páginas
   públicas (`WebFetch`/`WebSearch`), não de uma chamada direta e
   confirmada à API real com os parâmetros exatos de cada tribunal (a
   própria API bloqueou meu `WebFetch` com 403). Estou tratando isso como
   "forte indício, a confirmar pelo executor no início de cada fase", não
   como fato definitivo — ok seguir assim, ou prefere que eu tente mais
   alguma investigação antes de aprovar as Fases 19-21?

Se não houver objeção, o plano segue com a leitura padrão assumida em (1)
(só `TRFDJN` habilitado) e com a disciplina de confirmação descrita em (2).

---

## 9. Fases 23+ — Levantamento completo de pendências (sessão de 14/08/2026)

Lido antes de escrever esta seção: `CLAUDE.md`, `SPEC.md`, `portals.yaml`
e o código real em `app/`, `tests/` e `DEPLOY.md` (estado após as Fases
1-22, todas implementadas e commitadas localmente — ver 9.4 sobre "commitado
localmente" não ser o mesmo que "publicado"). Esta seção não propõe
mudança de stack nem de regra de negócio; é um inventário do que falta,
com uma fase pequena e verificável por pendência, na mesma disciplina das
seções 5 e 8.

Nenhum conflito novo entre `CLAUDE.md` e `SPEC.md` foi encontrado. Um
ponto de atenção (não um conflito, ver 9.2.1): `SPEC.md` §10 sugere
"listar o conteúdo do ZIP" do STJ no e-mail — a Fase 23 propõe simplificar
essa ideia original, e isso está marcado como pergunta ao usuário na
seção 9.7, não decidido em silêncio.

### 9.1 Método desta revisão

Assim como na seção 8, não tenho acesso a `scripts/inspect.py` nem a
rodar comandos — toda a investigação abaixo usou `WebFetch`/`WebSearch`
contra os sites reais dos três portais nunca investigados, e leitura
direta do código/git deste repositório para os outros dois pontos. Onde
a investigação encontrou evidência concreta (URLs reais, respostas HTTP
reais, não só busca), eu digo explicitamente; onde é só indício por
busca, digo isso também. Cada fase de portal novo abaixo começa,
igualmente, com o executor confirmando via `scripts/inspect.py` antes de
codar — mesma regra de "parar e reportar" das Fases 8 e 19-21.

### 9.2 Pendência 1 — três portais nunca investigados (STFDJE, STJ, TRF1ATA)

`portals.yaml` ainda tem `STFDJE`, `STJ` e `TRF1ATA` como `enabled: false`,
todos com `engine: playwright`, herdados sem revisão da análise original
da seção 3 (feita antes de qualquer implementação). Diferente de
JFDFDJN/TRFDJN/TSTDJN/TRT10DJN (seção 8), estes três nunca foram
reexaminados. A investigação de hoje mudou a avaliação de risco dos três,
em direções diferentes — um caso melhorou bastante (STJ), um revelou um
problema não previsto (TRF1ATA) e um manteve o risco alto, com um detalhe
técnico novo (STFDJE).

#### 9.2.1 Achados da investigação de hoje

**STJ (portal `STJ`, adapter `stj` — não confundir com `STJDJN`, que já
roda via DJEN):** `WebFetch` em `https://processo.stj.jus.br/processo/dj/init`
mostrou uma página com formulário renderizado no servidor (não é SPA) e,
mais importante, um **padrão de URL previsível e por data** para o Diário
de Justiça Eletrônico completo em ZIP:
`https://processo.stj.jus.br/docs_internet/processo/dje/zip/stj_dje_{AAAAMMDD}.zip`.
Uma tentativa direta de baixar essa URL com a data de hoje
(`stj_dje_20260814.zip`) devolveu um arquivo real maior que 10MB (o
`WebFetch` cortou por exceder o limite de conteúdo da ferramenta — a
própria falha é evidência de que a URL serviu um binário grande de
verdade, não uma página de erro). Isso é exatamente o padrão que
`SPEC.md` §10 já cogitava ("Publica ZIP diário com muitos PDFs") — a
mudança é que a *descoberta* do arquivo do dia não precisa de Playwright
nenhum: é só montar a URL com a data de hoje. Isso rebaixa a estratégia
de "Playwright" (seção 3 original) para **URL previsível de arquivo**, a
segunda opção mais preferida da hierarquia de `CLAUDE.md` — risco cai de
**Alto** para **Baixo-médio**.

**TRF1ATA (portal `TRF1ATA`, adapter `trf1_atas`):** `WebFetch` em
`https://www.trf1.jus.br/trf1/ataas/atas` (a URL exata que `portals.yaml`
já define) mostrou uma página HTML estática de verdade, sem necessidade
de JS — mas o conteúdo listado é uma tabela fixa de ~30 documentos
`.doc`, todos de **2009 e 2010** (ex.: `Ata01-ProcessoDigital_30072009.doc`,
`Ata30-ProcessoDigital_30032010.doc`), sem paginação, busca ou qualquer
sinal de que a página é atualizada. Parece ser o arquivo morto de um
projeto institucional antigo ("Processo Digital"), não uma lista viva de
atas de distribuição diárias. Isso **não é** uma questão de Playwright vs.
HTML estático (a página já é HTML estático, fácil de raspar) — é uma
dúvida mais básica: **é a URL certa?** Uma pista encontrada por busca:
outras seções judiciárias do TRF1 têm páginas próprias de "atas e pautas"
(ex.: `trf1.jus.br/sjrr/atas-de-julgamento/atas-e-pautas`, para a Seção
Judiciária de Roraima), sugerindo que "atas de distribuição" reais podem
viver espalhadas por seção, não numa página institucional central. Risco
técnico de scraping continua **Médio** (HTML estático, se a URL certa for
achada), mas o risco de **escopo/URL errada** é novo e mais sério — ver
pergunta 3 na seção 9.7.

**STFDJE (portal `STFDJE`, adapter `stf_dje`):** `WebFetch` em
`https://digital.stf.jus.br/publico/publicacoes` e em
`https://digital.stf.jus.br/publico/publicacao/463139` falhou nas duas
vezes com o erro `unable to verify the first certificate` — não consegui
nem confirmar se o HTML é SSR ou SPA. O mesmo aconteceu com o sistema
legado (`https://portal.stf.jus.br/servicos/dje/listarDiarioJustica.asp`).
Busca por fora confirma que sites `.jus.br` que usam certificado
ICP-Brasil às vezes não são reconhecidos por cadeias de confiança padrão
fora do ambiente configurado para isso — mas isso é um padrão conhecido
em geral, não uma confirmação de que o `httpx`/`certifi` do ambiente do
executor (que roda localmente, não pela minha ferramenta de busca) vai
falhar do mesmo jeito. Ou seja: **não sei se este é um problema real do
ambiente de produção ou só uma limitação da minha ferramenta de
investigação** — fica marcado como algo a confirmar logo no primeiro
passo da fase (9.2 abaixo), porque, se for real, contornar checagem de
certificado (`verify=False` ou equivalente) é uma decisão de segurança
que precisa aprovação explícita, não algo para o executor decidir
sozinho. Fora esse obstáculo, nada mudou da análise original: nenhuma
evidência de API JSON pública foi encontrada por busca, e o front
(`digital.stf.jus.br`) segue parecendo um SPA moderno. Risco continua
**Alto**.

#### 9.2.2 Tabela de risco atualizada

| Código | Estratégia (seção 3, original) | Estratégia (hoje, 9.2.1) | Risco (hoje) | O que mudou |
|---|---|---|---|---|
| **STJ** | Playwright + ZIP | URL previsível de arquivo (ZIP por data) | **Baixo-médio** (era Alto) | Padrão de URL do ZIP diário confirmado por download real; não precisa de browser para descobrir o arquivo. |
| **TRF1ATA** | HTML estático a validar | HTML estático confirmado, **mas URL parece ser um arquivo morto (2009-2010)** | **Médio-alto** (risco de escopo, não de scraping) | A raspagem em si seria fácil; o problema é não haver evidência de que aquela página ainda é "atas de distribuição" vivas. |
| **STFDJE** | Playwright | Playwright (mantido) + risco novo de certificado SSL | **Alto** | Confirma SPA sem API pública encontrada; acrescenta um obstáculo técnico não previsto (SSL) a confirmar antes de investir tempo. |

### Fase 23 — Habilita STJ (adapter `stj`, URL previsível de ZIP diário)
Rodar `uv run python scripts/inspect.py
"https://processo.stj.jus.br/docs_internet/processo/dje/zip/stj_dje_<hoje em AAAAMMDD>.zip"`
para confirmar status 200, `content-type` de arquivo binário (zip/
octet-stream) e tamanho (`content-length`) num dia útil; testar também
um fim de semana/feriado (deve dar 404 ou similar — a ausência de edição
não pode ser tratada como erro fatal). Rodar `scripts/inspect.py` também
em `https://processo.stj.jus.br/processo/dj/init` (página de referência
para `page_url`) para confirmar que segue no ar e sem exigir JS. Timebox
~20 min; se o padrão de URL não bater, parar e reportar ao usuário (regra
das Fases 8/19-21) em vez de partir para Playwright.

Implementar `app/scrapers/stj.py`: **decisão de design assumida por
padrão** (ver pergunta 2, seção 9.7) — tratar o ZIP do dia como **UMA
única `Publication`** (título `"DJe do STJ — {data}"`, `page_url` =
página de consulta do DJe, `file_urls = [url_do_zip]`), em vez de abrir o
ZIP e listar cada PDF interno como item separado. Isso reaproveita 100%
da arquitetura existente (downloader baixa o ZIP como um arquivo comum;
mailer aplica a regra dos 15MB a ele como a qualquer outro arquivo — como
o ZIP tende a ser bem maior que 15MB, o caminho mais provável é ele
**sempre** virar link com aviso de tamanho no corpo do e-mail, nunca
anexo, o que já é um comportamento válido e testado do mailer, R2). É
mais simples que a leitura literal de `SPEC.md` §10 ("listar o conteúdo
do ZIP"), então fica marcado como decisão a confirmar, não assumida
silenciosamente.

`fetch()` aceita um `reference_date` opcional (mesmo padrão de `now` em
`app.mailer.build_email`, para testes determinísticos); sem ele, usa a
data de hoje em `America/Sao_Paulo`. Faz um `HEAD` (não `GET` — minimiza
tráfego, `CLAUDE.md`: "mínimo de requests") na URL do ZIP do dia; se
`200`, monta a `Publication`; se `404` (dia sem edição — fim de semana,
feriado, ou o DJe daquele dia ainda não foi publicado, já que costuma
sair só à noite), retorna lista vazia sem erro. **Nota sobre fixture:**
diferente dos outros adapters, aqui não há um HTML/JSON de conteúdo para
salvar como fixture — a única variável é a data. O teste
(`tests/test_scrapers_stj.py`) cobre a construção determinística da
`Publication` a partir de uma `reference_date` fixa, sem rede (chama o
método de montagem diretamente, não `fetch()`), e é a exceção documentada
à regra "fixture obrigatória" de `CLAUDE.md` — não por preguiça, mas
porque não existe HTML/JSON remoto a fixar aqui. Atualizar `portals.yaml`:
`STJ` → `adapter: stj`, `engine: http` (troca de `playwright`);
`enabled` continua `false` até o usuário revisar o resultado do
`--dry-run` (mesmo padrão cauteloso das Fases 19-21 antes de ligar em
produção).

**Aceite:** `uv run pytest tests/test_scrapers_stj.py -q` → `1 passed`
(sem rede); `uv run python -m app.cli run --portal STJ --dry-run` roda
sem traceback e ou imprime a publicação do ZIP do dia (dia útil, após a
publicação noturna) ou confirma explicitamente "nenhuma edição disponível
hoje" (fim de semana/antes da publicação) — as duas saídas são aceitáveis,
o critério é não haver exceção não tratada.
**Commit:** "feat: habilita STJ (URL previsível de ZIP diário do DJe)"

### Fase 24 — TRF1ATA: investigar se a URL atual ainda é válida
**Esta fase é de investigação primeiro, código depois** — o achado da
seção 9.2.1 (URL aponta para um arquivo morto de 2009-2010) precisa ser
resolvido antes de escrever qualquer adapter. Rodar
`uv run python scripts/inspect.py "https://www.trf1.jus.br/trf1/ataas/atas"`
para confirmar (ou refutar) o achado de hoje. Se confirmado que o
conteúdo é mesmo só o arquivo morto, procurar por ~20 min (busca no
próprio site do TRF1, ex. campo de busca institucional, ou variações de
URL por seção judiciária como `/sjdf/atas-de-julgamento/atas-e-pautas`,
inspirado no padrão real achado para `/sjrr/`) uma página viva de atas de
distribuição da Seção Judiciária do DF (relevante para o escopo deste
projeto, focado em DF/federal — ver `portal_code` `JFDFDJN` na seção 8).

**Ramo A — fonte viva encontrada dentro do timebox:** implementar
`app/scrapers/trf1_atas.py` seguindo a estratégia que o `inspect.py`
confirmar (provavelmente HTML estático, mesma família de portais
institucionais do TRF1 já bem-sucedida nas Fases 19-21 para o conteúdo
processual). Fixture + teste sem rede, como todo adapter. Atualizar
`portals.yaml` (`engine`, `adapter` se mudar, `enabled` continua `false`
até revisão).
**Aceite (ramo A):** `uv run pytest tests/test_scrapers_trf1_atas.py -q`
→ `1 passed`; `uv run python -m app.cli run --portal TRF1ATA --dry-run`
imprime atas reais e recentes (não as de 2009-2010).
**Commit (ramo A):** "feat: habilita TRF1ATA (fonte viva de atas de distribuição)"

**Ramo B — não encontrada dentro do timebox:** nenhum código novo.
Atualizar o comentário de `TRF1ATA` em `portals.yaml` documentando o
achado (URL atual é um arquivo morto de 2009-2010) e continuar
`enabled: false`. Esta fase para aqui e devolve a decisão ao usuário (
pergunta 3, seção 9.7) em vez de escrever um adapter Playwright por conta
própria só para raspar um arquivo morto.
**Aceite (ramo B):** nenhum teste novo esperado; `git log -1 --format=%s`
mostra o commit de documentação abaixo.
**Commit (ramo B):** "docs: registra que a URL de TRF1ATA aponta para arquivo morto (2009-2010)"

### Fase 25 — STFDJE: confirmar SSL/estratégia e, se necessário, Playwright
Primeiro passo, antes de qualquer outra investigação: rodar
`uv run python scripts/inspect.py "https://digital.stf.jus.br/publico/publicacoes"`.

**Se `scripts/inspect.py` falhar com erro de certificado/SSL** (o mesmo
problema que o `WebFetch` teve hoje, seção 9.2.1): **parar e reportar ao
usuário** antes de qualquer outra ação — em especial, não desativar a
verificação de certificado (`verify=False` no `httpx`, ou equivalente)
por conta própria; é uma decisão de segurança que precisa aprovação
explícita (ver pergunta 4, seção 9.7). Esta fase termina aqui nesse
cenário, sem código novo.

**Se `scripts/inspect.py` funcionar normalmente:** confirmar se a URL
devolve HTML com conteúdo real (SSR) ou uma casca vazia de SPA (o
esperado, pela análise da seção 9.2.1). Timebox ~20 min olhando por
qualquer chamada de API JSON referenciada no HTML/JS servido (mesmo
processo das Fases 8/19-21). Se nenhuma API for encontrada, **instalar o
Playwright de verdade pela primeira vez neste projeto**:
`uv run playwright install --with-deps chromium`. Implementar
`app/scrapers/stf_dje.py`: `fetch()` usa Playwright para navegar até a
página, esperar a lista de publicações renderizar, e capturar o HTML
renderizado; um método `_parse()` separado (mesmo padrão de todo adapter
já existente) usa `selectolax` sobre esse HTML já renderizado — o teste
(`tests/fixtures/stf_dje_rendered.html` + `tests/test_scrapers_stf_dje.py`)
chama `_parse()` direto, sem precisar do Playwright instalado para rodar
a suíte. Atualizar `Dockerfile` para instalar o browser também na imagem
de produção (`RUN uv run playwright install --with-deps chromium` — ou
equivalente, ver documentação do Playwright para imagens Debian slim),
já que a imagem atual nunca precisou disso até agora. Atualizar
`portals.yaml`: `STFDJE` → `engine: playwright` (mantido), `enabled`
continua `false` até revisão.

**Aceite (SSL falhou):** nenhum código novo; a fase produz só um relato
ao usuário (fora do PLANO.md, na conversa) — sem commit de código.
**Aceite (SSL funcionou, Playwright necessário):**
`uv run playwright install --with-deps chromium` termina sem erro;
`uv run pytest tests/test_scrapers_stf_dje.py -q` → `1 passed` (sem
navegador, usa a fixture já renderizada); `uv run python -m app.cli run
--portal STFDJE --dry-run` (com o navegador instalado) imprime
publicações reais; `docker compose up --build -d && curl -s
http://localhost:8000/health` → `{"status":"ok","db":true,...}` (confirma
que a imagem com Playwright ainda builda e sobe).
**Commit:** "feat: habilita STFDJE via Playwright (primeiro portal com browser real)"

### 9.3 Pendência 2 — cinco portais de alto volume nunca disparados de verdade em produção

`STJDJN` (~10 mil/dia), `TJDFTDJN` (~10 mil/dia), `TRFDJN` (~32 mil/dia,
o maior de todos), `TSTDJN` (~12 mil/dia) e `TRT10DJN` (~5,8 mil/dia, o
único sem estar capado pelo teto de páginas na prática, porque seu volume
diário já fica abaixo do teto) usam todos `comunica_pje` e estão
`enabled: true` — mas nunca foram rodados sem `--dry-run` de verdade.
`app/scrapers/comunica_pje.py` tem `MAX_PAGES = 10` e `ITEMS_PER_PAGE =
1000`, ou seja, cada execução processa no máximo 10.000 itens por portal
por ciclo. Isso não é um bug — é uma pendência de produto/operação, como
o `README.md` e o `DEPLOY.md` já registram — mas ela nunca foi resolvida
de fato, e a investigação de hoje encontrou um segundo problema
relacionado, mais sério que "e-mail grande".

#### 9.3.1 O problema do primeiro disparo ("e-mail gigante")

Como `seen_hashes` está vazio para esses 5 portais, a primeira execução
real trataria **tudo** como novo — de ~5,8 mil a ~32 mil publicações num
único e-mail. Analisando as opções levantadas:

- **(a) Aceitar o e-mail grande na primeira vez.** Simples, zero código
  novo, mas arriscado: um e-mail HTML com dezenas de milhares de `<li>`
  pode estourar limite de tamanho de mensagem do MailGrid (ou do cliente
  de e-mail do destinatário), e não há como saber isso sem testar.
- **(b) Carga inicial manual controlada, portal por portal, fora do
  horário de pico**, antes de deixar o scheduler assumir aquele portal.
  Não exige código novo — só disciplina operacional, reaproveitando o
  `--force`/`run --portal CODE` que já existem. Permite observar o
  resultado real (o e-mail chegou? o MailGrid aceitou?) antes de
  comprometer o próximo ciclo automático a fazer a mesma coisa sem
  supervisão.
- **(c) Aumentar `MAX_PAGES` ou mudar a paginação.** Não resolve o
  problema do primeiro disparo (só aumentaria ainda mais o volume do
  primeiro e-mail) — é uma resposta ao problema *diferente* da seção
  9.3.2 abaixo, não deste.
- **(d) Outra ideia:** poderia se cogitar um "modo de carga inicial" que
  grava os hashes em `seen_hashes` sem enviar e-mail (popular a memória
  de dedupe silenciosamente, como se o portal já estivesse rodando há
  dias) — mas isso violaria a regra de nunca perder uma publicação (o
  usuário nunca veria essas publicações nem no primeiro e-mail nem
  depois, já que ficariam marcadas como "já vistas"). Descartado por
  contrariar `CLAUDE.md`/`SPEC.md` (nenhuma publicação pode ser
  silenciosamente descartada).

**Minha recomendação:** opção (b). É a mais segura (dá para observar e
abortar antes de comprometer o scheduler automático) e não exige nenhum
código novo — só um roteiro operacional, que a Fase 27 documenta e deixa
registrado em `DEPLOY.md`. Fica como pergunta ao usuário (seção 9.7,
pergunta 1) porque, mesmo sendo minha recomendação, é uma decisão de
produto/operação, não uma correção técnica óbvia.

#### 9.3.2 Achado novo: risco de perda estrutural por causa do teto `MAX_PAGES`

Lendo `app/scrapers/comunica_pje.py` com atenção: `fetch()` pagina pela
API filtrando por `dataDisponibilizacaoInicio`/`Fim` = hoje, para de
paginar quando uma página devolve menos que `ITEMS_PER_PAGE` itens, e tem
um teto de `MAX_PAGES = 10` (10.000 itens) por execução. Isso é
inofensivo para portais com menos de 10 mil publicações/dia (a paginação
sempre alcança o fim antes do teto). Mas `TRFDJN` já tem ~32 mil/dia
confirmadas (`README.md`) — **mais que o triplo do teto**.

O problema em potencial: `SCAN_CRON` roda de hora em hora (padrão), e
cada execução volta a paginar **a partir da página 1** do dia corrente.
Se a API devolver os itens do dia sempre na mesma ordem (por exemplo, por
ID crescente, mais antigos primeiro) e a lista só cresce ao longo do dia,
então toda execução do dia vai ficar re-lendo os mesmos primeiros 10.000
itens (que o dedupe descarta rapidamente, sem custo de e-mail, mas com
custo de requisições) — e os itens que existem **além** da posição
10.000 no dia (para `TRFDJN`, isso pode ser a maioria: ~22 mil de ~32
mil) **nunca seriam alcançados**, em nenhuma execução daquele dia,
porque o teto nunca "avança" — cada execução recomeça do zero. Isso seria
uma perda **estrutural e recorrente**, não um problema de "primeiro
e-mail grande" — publicações reais do DJEN, todo santo dia, nunca
chegando ao usuário, silenciosamente.

Isso é uma **hipótese a confirmar**, não um fato — não tenho como rodar
o adapter real para testar a ordenação da API. A forma mais barata de
confirmar (ou refutar) sem escrever código novo: comparar os hashes
devolvidos na página 10 da consulta `siglaTribunal=TRF1` em dois horários
bem espaçados do mesmo dia (ex.: 9h e 17h). Se os hashes da página 10
mudarem entre as duas capturas (itens novos aparecendo nas últimas
páginas à medida que o dia avança), a ordenação não é estável por
posição fixa — o teto só atrasa a entrega de alguns itens para o ciclo
seguinte dentro do mesmo dia, sem perda. Se os hashes da página 10
continuarem sendo os mesmos nas duas capturas (mesmo com o total do dia
claramente maior), a perda estrutural está confirmada.

### Fase 26 — Investigar se `MAX_PAGES=10` causa perda estrutural em TRFDJN
Rodar, em dois horários bem espaçados do mesmo dia útil (ex.: 9h e 17h):
`uv run python -m app.cli run --portal TRFDJN --dry-run` (ou
`scripts/inspect.py` direto na API, página 10) e comparar os hashes
(campo `hash` de cada item) retornados na página 10 das duas capturas.

**Se os hashes da página 10 mudarem** entre as duas capturas (evidência
de que a ordenação não é por posição fixa e itens novos aparecem nas
páginas finais ao longo do dia): sem perda estrutural confirmada. Nenhuma
mudança de código — só documentar a confirmação como comentário na
docstring de `app/scrapers/comunica_pje.py`, perto de `MAX_PAGES`.
**Aceite:** `uv run pytest -q` → todos verdes (nada quebrou); a docstring
de `comunica_pje.py` passa a citar essa confirmação, com a data do teste.
**Commit:** "docs: confirma que MAX_PAGES não causa perda estrutural em TRFDJN"

**Se os hashes da página 10 forem os mesmos nas duas capturas** (evidência
de perda estrutural real): **parar e reportar ao usuário** — não decidir
sozinho entre aumentar `MAX_PAGES` (mais requisições, mais tempo de
ciclo, ainda pode não bastar para 32 mil/dia), implementar paginação por
cursor/ID em vez de recomeçar do zero a cada execução (mudança de código
mais profunda no adapter compartilhado por 5 portais), ou aceitar a perda
parcial como um limite conhecido do MVP. Ver pergunta 2, seção 9.7. Esta
fase termina aqui nesse cenário, sem código novo além do relato.
**Aceite (perda confirmada):** nenhum teste novo esperado — a fase produz
um relato ao usuário com a evidência (hashes comparados) em vez de commit
de correção.

### Fase 27 — Carga inicial controlada dos 5 portais de alto volume
Só depois da Fase 26 concluída (nenhum sentido em popular `seen_hashes`
de um portal com paginação estruturalmente incompleta sem essa decisão
tomada primeiro). Roteiro operacional, sem código novo, assumindo a
recomendação (b) da seção 9.3.1 (a confirmar com o usuário, pergunta 1,
seção 9.7):

1. Antes de expor os 5 portais ao scheduler automático (seja localmente
   ou já na VM, ver seção 9.4), confirmar que estão `enabled: true` em
   `portals.yaml` mas rodar o primeiro ciclo de cada um **manualmente**,
   um de cada vez, fora do horário de pico: `uv run python -m app.cli run
   --portal CODE` (ou, na VM, `docker compose exec app uv run python -m
   app.cli run --portal CODE`, ver `DEPLOY.md`).
2. Observar se o e-mail chega e é aceito pelo MailGrid sem erro/rejeição
   por tamanho. Se for rejeitado, é um sinal de que a opção (a) da seção
   9.3.1 (aceitar sem controle) teria falhado — evidência a favor de (b).
3. Repetir para os 5 portais, um de cada vez (podem ser dias diferentes,
   se o volume individual já se mostrar grande demais para conforto).
   Depois do primeiro disparo bem-sucedido de cada portal,
   `seen_hashes` já estará populada para ele — os próximos ciclos do
   scheduler (automáticos) só verão o delta do dia a partir daí, um
   volume ordens de magnitude menor.
4. Atualizar `DEPLOY.md` seção 9 ("Pendências conhecidas"): hoje ela só
   cita `STJDJN` e `TJDFTDJN` (desatualizado — são 5 portais de alto
   volume hoje, não 2, ver `README.md`); atualizar a lista e referenciar
   este roteiro.

**Aceite:** para cada um dos 5 portais, um e-mail real chega e é aceito
pelo MailGrid (checkpoint manual do usuário, mesmo padrão da Fase 13 —
não automatizável); `DEPLOY.md` atualizado citando os 5 portais e o
roteiro de carga inicial.
**Commit:** "docs: roteiro de carga inicial para portais de alto volume + atualiza DEPLOY.md"

### 9.4 Pendência 3 — deploy na VM Oracle A1 ainda não aconteceu

`DEPLOY.md` já existe, pronto, com passo a passo completo (instalação de
Docker, clone, `.env`, `docker compose up --build -d`, túnel SSH,
atualização) — não é código faltando, é execução pendente. Conferido
agora, lendo o histórico do git deste repositório: `refs/heads/main`
aponta para o commit `0abf42c` (o mais recente, "docs: atualiza README.md
com Fases 15-22"), enquanto `refs/remotes/origin/main` ainda aponta para
`005f9c2e2a` ("docs: atualiza README.md com Fases 11-14 e feature
--force") — **cerca de 10 commits committed localmente e nunca
publicados** (do job de retenção, Fase 15, até o fechamento da expansão
DJEN, Fase 22, incluindo TRFDJN/TSTDJN/TRT10DJN). Isso confirma
diretamente o item 0 do próprio `DEPLOY.md` ("`git push origin main` já
feito... não deste ambiente") como uma pendência real, não hipotética.
Nota: esta checagem foi feita comparando as referências locais do git,
não um `git fetch` ao vivo — o passo abaixo pede para confirmar com
`git status -sb` antes de agir, já que o estado remoto pode ter mudado
desde a última sincronização local.

### Fase 28 — Publicar o repositório e executar o deploy real (operacional, sem código novo)
Esta fase não segue o template "código + commit" das demais — é checklist
de execução, não desenvolvimento. Passos, na ordem:

1. No terminal local (não neste ambiente, que não tem credenciais do
   GitHub): `git status -sb` para confirmar quantos commits estão à
   frente de `origin/main`; `git push origin main`.
2. Seguir `DEPLOY.md` do início ao fim (seções 0 a 8) — já cobre
   instalação de Docker, clone, `.env`, subida dos containers e
   confirmação de `/health` e do scheduler. Não duplicado aqui.
3. Só depois do deploy básico confirmado (containers de pé, `/health`
   ok, scheduler com os jobs agendados), aplicar o roteiro da Fase 27
   (carga inicial controlada) antes de considerar os 5 portais de alto
   volume "em produção" de fato — a seção 9 do `DEPLOY.md`, já
   atualizada pela Fase 27, cobre isso.

**Aceite:** `git log --oneline -1` no GitHub (via web ou `gh`) mostra o
commit mais recente deste repositório; na VM,
`curl -s http://localhost:8000/health` → `{"status":"ok","db":true,...}`;
`docker compose logs app --tail 50 | grep -i scheduler` mostra os jobs
`scan` e `retention` agendados.
**Sem commit de código** — esta fase é sobre publicar e operar commits já
existentes, não criar um novo.

### 9.5 Ligação com `SPEC.md` §11 (critérios de aceite do MVP)

Os critérios 4 e 5 de `SPEC.md` §11 ("um ciclo real entrega e-mail... e
grava sent_at" / "segundo ciclo imediato não reenvia nada") foram
validados ao vivo apenas para 3 dos 8 portais hoje habilitados (TST, TCU,
TCDF — ver `README.md`, seção "Testes reais já rodados"). Os outros 5
(exatamente os da seção 9.3: STJDJN, TJDFTDJN, TRFDJN, TSTDJN, TRT10DJN)
seguem pendentes desses dois critérios — não é uma pendência nova, é a
mesma pendência da seção 9.3 vista pela ótica do checklist original do
MVP. A Fase 27 fecha essa lacuna para os 5 de uma vez.

### 9.6 Outras divergências encontradas (sem fase própria — cosméticas)

- **Nomes de arquivo de teste divergem do plano original:** a seção 1
  (árvore de arquivos) e a Fase 17 citam `tests/test_api.py`; o arquivo
  real chama-se `tests/test_routers.py`. Também existem `tests/test_cli.py`
  e `tests/test_scheduler.py`, não previstos na árvore original. Isso já
  é esperado e consistente com o aviso que o próprio `README.md` faz
  ("o código é a fonte de verdade") — não há ação a tomar, só registro.
- **`app/scrapers/tjdft.py` nunca existiu** (a Fase 10 real reaproveitou
  `comunica_pje`) — já documentado no `README.md` ("Inconsistência que
  vale registrar") e na seção 8 deste plano; sem ação nova aqui.

### 9.7 Perguntas para o usuário

1. **Rollout dos 5 portais de alto volume (seção 9.3.1):** confirma a
   recomendação — opção (b), carga inicial manual controlada por portal,
   fora do horário de pico, antes do scheduler assumir — ou prefere (a)
   aceitar o e-mail grande na primeira vez mesmo assim, ou outra
   abordagem?
2. **Se a Fase 26 confirmar perda estrutural em TRFDJN** (itens além da
   posição 10.000 do dia nunca alcançados): aumentar `MAX_PAGES` (mais
   requisições/ciclo mais lento, pode não bastar sozinho para 32 mil/dia),
   implementar paginação por cursor/ID entre execuções (mudança mais
   profunda em `comunica_pje.py`, adapter compartilhado por 5 portais), ou
   aceitar a perda parcial como limitação conhecida do MVP por enquanto?
   Não tenho uma recomendação técnica óbvia sem antes ver a confirmação
   real da Fase 26 — é decisão de produto quando/se o problema se
   confirmar.
3. **TRF1ATA (seção 9.2.1, Fase 24):** a URL que `portals.yaml` já define
   aponta para um arquivo morto de 2009-2010. Se a Fase 24 não achar uma
   página viva de atas de distribuição em ~20 min de busca (ramo B),
   prefere: (a) deixar `TRF1ATA` documentado como `enabled: false`
   indefinidamente, sem mais investimento; (b) que eu tente uma nova
   rodada de investigação por fora antes da próxima sessão; ou (c)
   remover `TRF1ATA` de `portals.yaml` de vez, por não haver evidência de
   que a fonte pretendida ainda existe? Minha recomendação, dado o achado
   de hoje, é (a) — não vejo motivo para insistir sem uma pista concreta
   de onde a fonte viva estaria.
4. **STFDJE (seção 9.2.1, Fase 25):** se `scripts/inspect.py` confirmar o
   mesmo erro de certificado que meu `WebFetch` teve hoje contra
   `digital.stf.jus.br`, como prefere resolver — instalar a cadeia
   ICP-Brasil no ambiente (mais correto, mais trabalho), desativar a
   verificação de certificado só para esse portal (mais rápido, risco de
   segurança a avaliar), ou pausar `STFDJE` até decidir? Não tenho
   recomendação padrão aqui porque envolve trade-off de segurança, não só
   engenharia.
5. **STJ (seção 9.2.1, Fase 23):** confirma tratar o ZIP diário do DJe
   como **um único arquivo anexado/linkado por publicação** (minha
   recomendação, mais simples, reaproveita a arquitetura existente sem
   mudança), em vez de abrir o ZIP e listar cada PDF interno como item
   separado (mais fiel à sugestão original de `SPEC.md` §10, mais código:
   extrair, nomear e decidir dedupe/anexo por PDF individual dentro do
   ZIP)?

Se não houver objeção às recomendações (1 = opção b, 3 = opção a, 5 =
manter zip único), o plano segue com elas; as perguntas 2 e 4 dependem de
confirmação técnica que ainda não existe (Fases 26 e 25, respectivamente)
e não têm uma leitura padrão a assumir.
