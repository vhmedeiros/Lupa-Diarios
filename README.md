# Lupa Diários — Manual de Operação

> Este README é um manual de operação para quem vai rodar, testar e
> estender o projeto no dia a dia. Para o roadmap completo (o que já foi
> feito e o que falta, fase por fase) veja `PLANO.md`. Para as regras de
> negócio e o contrato do MVP, veja `SPEC.md`. Para as convenções fixas de
> stack e arquitetura, veja `CLAUDE.md` — este README não substitui
> nenhum dos três, só organiza a leitura para quem vai operar o código.

---

## 1. Visão geral

O Lupa Diários é um microserviço em Python que monitora portais de
Diários Oficiais brasileiros, raspa o texto das publicações, baixa os
arquivos vinculados (PDF/ZIP) e dispara e-mail com as novidades. Roda
24/7 em Docker.

### O que já funciona hoje (Fases 1 a 14 do PLANO.md, implementadas e testadas)

- **Setup do projeto**: `uv`, Python 3.13, dependências, `ruff`,
  `pytest`, `scripts/inspect.py` (`app/`, `pyproject.toml`).
- **Configuração e registry de portais**: `app/config.py` lê o `.env`;
  `app/registry.py` carrega e valida `portals.yaml`.
- **Docker Compose + FastAPI**: `docker-compose.yml`, `Dockerfile`,
  `app/main.py` com `GET /health` (checagem real de banco).
- **Modelo de dados**: tabelas `publications` e `seen_hashes`
  (`app/models.py`), criadas via `create_all` no startup da app
  (`app/main.py`) — não há Alembic/migrations no MVP.
- **BaseScraper + dedupe**: contrato comum de adapter
  (`app/scrapers/base.py`) e a lógica de hash/dedupe (`app/dedupe.py`,
  função `filter_new`).
- **5 adapters funcionando**, todos parte do recorte do MVP definido no
  `PLANO.md` (seção 4) — os únicos 5 portais habilitados
  (`enabled: true`) em `portals.yaml` hoje:
  - **TST** — feed Atom (`app/scrapers/tst_juslaboris.py`)
  - **STJDJN** e **TJDFTDJN** — API JSON do DJEN/comunica_pje, mesmo
    adapter parametrizado por tribunal (`app/scrapers/comunica_pje.py`)
  - **TCU** — HTML estático server-side rendered (`app/scrapers/tcu.py`)
  - **TCDF** — API JSON descoberta no bundle JS da SPA
    (`app/scrapers/tcdf.py`)
- **Downloader de arquivos** (`app/downloader.py`, Fase 11): baixa cada
  arquivo vinculado a uma publicação para
  `data/files/{portal_code}/{published_at}/`, com timeout 30s, retry 3x
  com backoff exponencial e User-Agent `LupaDiarios/1.0`. Quando a URL
  não traz extensão no nome do arquivo (caso real do TCU, cujas URLs de
  PDF terminam em `.../obterDocumentoPdf/{id}`, sem sufixo), infere a
  extensão pelo header `Content-Type` da resposta antes de gravar em
  disco — correção de bug feita depois da Fase 14 original (commit
  `baeaed3`).
- **Mailer** (`app/mailer.py`, Fases 12-13):
  - `build_email(publications)` monta assunto + corpo HTML e decide,
    aplicando a regra R2 do `SPEC.md`, quais arquivos entram como
    anexo. O limite `MAX_ATTACH_MB` é **global por e-mail** (soma de
    todos os portais do ciclo, não por portal) e o desempate quando o
    orçamento não cobre tudo é **ordem de descoberta** (por portal, na
    ordem de primeira aparição, depois por `published_at`) — não
    "menores primeiro". A partir do arquivo que faria a soma estourar,
    ele e todos os seguintes viram link no corpo, com aviso explícito
    de tamanho; nenhuma publicação é omitida por causa de tamanho. Isso
    foi confirmado com o usuário (era a pergunta 1 da seção 7 do
    `PLANO.md`, respondida durante a implementação).
  - `send_email(subject, html_body, attachments)` envia de verdade via
    `aiosmtplib`, com STARTTLS real (MailGrid). `MAIL_TO` já suporta
    múltiplos destinatários separados por vírgula — o `aiosmtplib`
    extrai os destinatários do header `To` da mensagem automaticamente;
    não foi preciso nenhum código extra de parsing para isso
    (confirmado nesta sessão).
- **Pipeline completo** (`app/pipeline.py`, `run_cycle`, Fase 14):
  fetch → dedupe → download → monta e envia UM e-mail (só se houver
  publicação nova, R5) → grava `sent_at`. Erro em qualquer etapa de um
  portal é capturado e logado; os demais portais do ciclo seguem
  normalmente (R4, isolamento de falha).
- **Endpoints de operação** (`app/routers.py` + `app/main.py`, Fase 14):
  `POST /run` (todos os portais habilitados) e `POST /run/{portal_code}`
  (um portal específico) disparam o pipeline via `BackgroundTasks` do
  FastAPI — a rota responde `{"status": "started"}` na hora e o ciclo
  roda em segundo plano, numa sessão de banco própria.
- **CLI completo**: `app/cli.py` tem hoje três comportamentos do
  comando `run`, além de `send-test`:
  - `uv run python -m app.cli run --portal CODE --dry-run` — só coleta
    e imprime; não grava, não baixa, não envia e-mail.
  - `uv run python -m app.cli run [--portal CODE]` — roda o pipeline de
    verdade (grava no banco, baixa arquivo, envia e-mail se houver
    novidade). Sem `--portal`, roda todos os portais habilitados.
  - `uv run python -m app.cli run --portal CODE --force` — feature
    pontual **fora do `PLANO.md` original**, aprovada pelo usuário
    nesta sessão (commit `9b5f5c3`): ver seção 5.1 abaixo para os
    detalhes.
  - `uv run python -m app.cli send-test` — envia um e-mail de teste
    real via SMTP, sem tocar no banco.

### Testes reais já rodados nesta sessão (prova de ponta a ponta)

Os três portais mais simples do recorte já foram disparados de verdade
(sem `--dry-run`) contra os sites reais, com sucesso:

- **TST** (feed Atom, sem arquivos vinculados)
- **TCU** (HTML estático, com download real de PDF anexado ao e-mail)
- **TCDF** (API JSON, sem arquivos vinculados)

Os três já dispararam e-mail real via MailGrid com sucesso. Rodar o
ciclo de novo imediatamente depois não reenviou nada (dedupe
comprovado, critério 5 do `SPEC.md` §11), e o reenvio manual via
`--force` também já foi validado ao vivo para pelo menos um desses
portais.

### Pendência conhecida (não é bug): STJDJN e TJDFTDJN ainda não foram disparados de verdade

Ambos usam o adapter `comunica_pje` (DJEN) e, na primeira coleta real,
trazem um volume muito alto de publicações "novas" — da ordem de
~10.000 cada, mesmo já com o teto `MAX_PAGES = 10` do adapter
(`app/scrapers/comunica_pje.py`) limitando quantas páginas da API são
percorridas por execução. Um e-mail com ~20.000 itens de uma vez é
arriscado (tamanho da mensagem, limite prático do MailGrid), então
esses dois portais só foram testados via `--dry-run` até agora — nunca
com envio de e-mail real. Isso é uma pendência conhecida a resolver
antes de habilitar o pipeline completo para eles em produção (ex.:
lote menor na primeira carga, ou paginação do próprio envio), não um
defeito do código atual.

### O que ainda NÃO existe (Fases 15 a 18 do PLANO.md — não implementadas)

Nada abaixo existe em código ainda. Não confie em nenhum destes
comportamentos até a fase correspondente ser implementada:

- Job de retenção de 3 dias (`app/retention.py` — Fase 15)
- Scheduler/cron (`app/scheduler.py` — Fase 16)
- Endpoints `GET /portals`, `GET /publications` (`app/routers.py` —
  Fase 17)
- Fechamento do MVP (checklist do `SPEC.md` §11 rodado por completo —
  Fase 18)

Ou seja: hoje o projeto **coleta, deduplica, baixa arquivos e envia
e-mail de verdade** para 3 dos 5 portais do recorte já testados ao vivo
(TST, TCU, TCDF), com STJDJN/TJDFTDJN pendentes de um primeiro disparo
real por causa do volume (ver pendência acima). Ele ainda não roda
sozinho (sem scheduler, cada ciclo precisa ser disparado manualmente
via CLI ou `POST /run`) e ainda não tem retenção automática do buffer —
isso é o roadmap em `PLANO.md`, fases 15 em diante.

### Inconsistência que vale registrar

O `PLANO.md` (Fase 10) previa um adapter dedicado `app/scrapers/tjdft.py`
para o TJDFTDJN, com URL previsível de PDF. Na prática, a investigação
mostrou que o TJDFT também é coberto pelo DJEN — o mesmo adapter
`comunica_pje` foi reaproveitado para TJDFTDJN, parametrizado com
`sigla_tribunal: TJDFT` em `portals.yaml`, exatamente como o `SPEC.md`
§10 já cogitava ("intimações TRF1 PJe podem já estar cobertas pelo
DJEN — validar antes de investir tempo"). Não existe `app/scrapers/tjdft.py`
no repositório, e não deveria — a Fase 10 real terminou reaproveitando
`comunica_pje.py`, não criando um adapter novo. Se você ler o `PLANO.md`
tal como está hoje, ele ainda descreve o plano original (arquivo
`tjdft.py`); o código é a fonte de verdade sobre o que de fato foi
construído.

---

## 2. Arquitetura em texto

Pipeline completo, como descrito em `CLAUDE.md`/`SPEC.md` (partes em
**[futuro]** ainda não existem em código):

```
[futuro] scheduler [app/scheduler.py]
  └─▶ registry (app/registry.py) carrega portals.yaml, filtra enabled=true
  └─▶ para cada portal: adapter.fetch() -> list[Publication]
        (app/scrapers/<adapter>.py, herda de app/scrapers/base.py)
        try/except por portal — erro em um não derruba os demais (R4)
  └─▶ dedupe (app/dedupe.py): calcula content_hash, filtra contra
        seen_hashes, grava as novas em seen_hashes + publications
  └─▶ downloader (app/downloader.py): baixa arquivos p/ data/files/
  └─▶ mailer (app/mailer.py): monta e envia UM e-mail agrupado,
        só se houver publicação nova (R5)
  └─▶ grava sent_at nas publicações enviadas

[futuro] job diário de retenção (app/retention.py):
  apaga publications+arquivos com sent_at > RETENTION_DAYS dias;
  nunca toca seen_hashes
```

Tudo dentro de `run_cycle` (`app/pipeline.py`) já existe e roda de
verdade — o único `[futuro]` real do diagrama acima hoje é o
**scheduler**: nada dispara o pipeline sozinho ainda, ele precisa ser
chamado manualmente. Duas formas de disparar o pipeline completo hoje:

```
app/cli.py (run, sem --dry-run)
  └─▶ registry.load_portals() acha o(s) Portal(is) pelo code (ou todos os enabled)
  └─▶ app.pipeline.run_cycle(session, portal_code)
        fetch() -> dedupe -> download -> mailer.build_email + send_email -> sent_at
  └─▶ session.commit() e imprime "N publicações enviadas"

POST /run  ou  POST /run/{portal_code}  (app/routers.py)
  └─▶ mesma run_cycle(), disparada via BackgroundTasks do FastAPI
  └─▶ responde {"status": "started"} na hora; resultado só vai pro log
```

E, sem tocar no pipeline de verdade, o modo seguro de investigar/testar
um adapter isolado:

```
app/cli.py (run --dry-run)
  └─▶ registry.load_portals() acha o Portal pelo code
  └─▶ resolve a classe do adapter no dicionário ADAPTERS
  └─▶ scraper.fetch() -> list[Publication]
  └─▶ imprime no terminal (não toca no banco, não baixa, não envia)
```

Peças centrais para entender antes de mexer em qualquer parte do
pipeline:

- **`app/scrapers/base.py`**: define `Publication` (modelo Pydantic —
  NÃO confundir com `app.models.Publication`, que é a linha do banco) e
  `BaseScraper` (classe abstrata com um único método obrigatório,
  `async def fetch(self) -> list[Publication]`). Todo adapter novo
  herda dessa classe.
- **`app/dedupe.py`**: `compute_hash()` calcula
  `sha256(portal_code + page_url + published_at ISO)`; `filter_new()`
  recebe a lista de `Publication` que o adapter devolveu, consulta
  `seen_hashes` no banco e devolve só as publicações realmente novas,
  já tendo gravado o hash e a linha em `publications` das novas.
  `clear_hashes()` é o inverso, usado só pelo `--force` do CLI (seção
  5.1) — apaga linhas específicas de `seen_hashes`/`publications` pelo
  hash exato.
- **`app/downloader.py`**: `download_publication_files()` baixa os
  `file_urls` de uma `Publication` para
  `data/files/{portal_code}/{published_at}/` e devolve a lista de
  metadados (`{url, path, size_bytes, attached}`) que vai para o campo
  `files` (jsonb) da linha em `publications`. Não decide `attached` —
  isso é o mailer.
- **`app/mailer.py`**: `build_email()` decide `attached` (regra dos
  15MB, R2) e monta o e-mail; `send_email()` envia de verdade via
  `aiosmtplib`.
- **`app/pipeline.py`**: `run_cycle()` orquestra tudo isso por ciclo,
  com isolamento de falha por portal (R4) e "só envia se houver
  novidade" (R5).

---

## 3. Como rodar o projeto hoje

```bash
# 1. Subir só o banco (é o que os testes e o CLI precisam)
docker compose up -d db

# 2. Rodar a suíte de testes
uv run pytest -q

# 3. Testar um adapter manualmente contra o portal real, sem efeitos colaterais
uv run python -m app.cli run --portal TST --dry-run
uv run python -m app.cli run --portal STJDJN --dry-run
uv run python -m app.cli run --portal TCU --dry-run
uv run python -m app.cli run --portal TCDF --dry-run
uv run python -m app.cli run --portal TJDFTDJN --dry-run

# 4. Rodar o pipeline de verdade (grava no banco, baixa arquivo, envia e-mail
#    se houver novidade) — preencha o .env com credenciais reais antes
uv run python -m app.cli run --portal TCU
uv run python -m app.cli run   # todos os portais habilitados

# 5. Reenviar manualmente publicações já vistas de um portal (ver seção 5.1)
uv run python -m app.cli run --portal TCU --force

# 6. E-mail de verificação de configuração SMTP
uv run python -m app.cli send-test

# 7. Lint e format antes de commitar
uv run ruff check --fix . && uv run ruff format .

# 8. Subir tudo em Docker (app + db)
docker compose up --build
```

### Por que os testes precisam do banco de pé (importante, já causou confusão)

Este projeto **não usa banco mockado/sqlite em memória** nos testes —
`tests/conftest.py` conecta no Postgres real do `docker compose` (a
mesma `DATABASE_URL` do `.env`, apontando para `localhost:5432`, porque
os testes rodam com `uv run` fora do container, não dentro dele). Cada
teste abre uma transação numa conexão dedicada e faz `rollback` no
teardown, então o banco fica limpo entre testes — mas ele **precisa
existir e estar acessível** antes de rodar `pytest`.

Se você rodar `uv run pytest -q` sem antes rodar `docker compose up -d
db`, os testes que tocam banco (`tests/test_dedupe.py`,
`tests/test_pipeline.py`, `tests/test_routers.py`, por exemplo) vão
falhar com erro de conexão recusada — não é bug do teste, é o serviço
`db` que não está de pé. Isso é uma decisão deliberada (`CLAUDE.md`:
"Sem ORM extra... simplicidade é requisito de negócio") — testar contra
Postgres real evita bugs que só aparecem com o dialeto real (tipos
`JSONB`, `unique constraint` etc.) e que um SQLite fake não pegaria.

Resumindo o hábito a criar: **sempre `docker compose up -d db` antes de
`uv run pytest -q`** (ou já deixe o `db` rodando o tempo todo durante o
desenvolvimento).

---

## 4. Guia passo a passo: como adicionar um novo portal

Esta é a seção mais importante deste manual. Ela descreve o processo
real que os 5 adapters existentes seguiram — não é hipotético.

### Passo 0 — Antes de qualquer código: investigar o portal

`CLAUDE.md` define a hierarquia de estratégia, em ordem de preferência:

```
API JSON escondida > feed RSS/Atom > URL previsível de arquivo >
HTML estático (httpx+selectolax) > Playwright
```

A regra é: **sempre tentar a opção mais alta da lista primeiro**.
Playwright é o último recurso — é mais lento, mais frágil (quebra
quando o layout muda) e exige instalar o binário do browser. Todo
adapter novo começa com:

```bash
uv run python scripts/inspect.py "https://exemplo.gov.br/algum-endpoint"
```

`scripts/inspect.py` faz um `GET` simples (timeout 30s, User-Agent
"LupaDiarios/1.0") e imprime `status`, `content-type` e os primeiros
~2000 caracteres do corpo. Use-o para responder, nesta ordem:

1. **Existe uma API JSON por trás do site?** Se o site é uma SPA (React,
   Vue, Angular), o `inspect.py` na URL "visível" normalmente devolve
   pouco HTML (um `<div id="app">` vazio). Nesse caso, abra o site no
   navegador, olhe a aba Network do DevTools, procure requisições XHR
   que retornam JSON, e rode `inspect.py` direto nessa URL de API.
2. **Existe um feed RSS/Atom** (`/feed`, `/rss`, `/atom_1.0`)?
3. **Existe um padrão de URL previsível** para o arquivo do dia (ex.:
   `/O/{ano}/{edicao}`)?
4. **O HTML é renderizado no servidor** (SSR)? Se o `inspect.py` já
   devolve a tabela/lista completa em HTML puro, dá para usar
   `httpx` + `selectolax`, sem JS.
5. Só se nada disso funcionar, considere Playwright.

**Não pule este passo, e não assuma a estratégia que está hoje em
`portals.yaml`** — ela é só um palpite inicial e pode estar errada ou
desatualizada. Isso aconteceu de verdade duas vezes no recorte atual:

- **TCU**: `portals.yaml` tinha `engine: playwright`, mas a investigação
  (`app/scrapers/tcu.py`, docstring) mostrou que `portal.tcu.gov.br/btcu`
  é renderizado no servidor (Next.js SSR) — um `GET` simples com
  `httpx` já devolve a tabela completa. `portals.yaml` foi atualizado
  para `engine: http` nessa mesma fase, porque a mudança de estratégia
  ficou comprovada, não porque o autor "achou melhor".
- **TCDF**: a hipótese original do `SPEC.md` era URL previsível
  (`/O/{ano}/{edicao}`), mas essa rota só existe do lado do Vue Router
  — sem JS não renderiza nada. A investigação subiu um degrau na
  hierarquia (não desceu): olhando o bundle JS da SPA, apareceu uma API
  JSON pública em `api-doe.tc.df.gov.br/api/publico` (ver docstring de
  `app/scrapers/tcdf.py`). Ou seja, às vezes a estratégia real é
  *melhor* do que a suposição inicial, não pior — só a investigação
  revela isso.
- **TJDFTDJN**: o `SPEC.md`/`PLANO.md` originais previam um adapter
  dedicado com URL previsível de PDF. A investigação mostrou que o
  TJDFT também está coberto pelo mesmo agregador DJEN usado pelo STJ —
  então **nenhum adapter novo foi criado**; `TJDFTDJN` só ganhou uma
  entrada em `portals.yaml` reaproveitando `adapter: comunica_pje` com
  outro `sigla_tribunal`. Antes de escrever um adapter do zero, vale
  perguntar: "um adapter que já existe serve para este portal, só
  mudando parâmetro?"

Se depois de ~15-20 minutos de investigação a estratégia não ficar
clara, pare e relate a situação em vez de decidir sozinho qual caminho
seguir — é a mesma regra que o agente executor segue (ver
`.claude/agents/executor.md` e `PLANO.md` seção 6, risco 1).

### Passo 1 — Declarar o portal em `portals.yaml`

Adicione (ou ajuste, se o código já existir com `enabled: false`) uma
entrada na lista `portals:`. Campos:

- `code`: identificador curto, em maiúsculas, usado em `--portal CODE`
  e nos logs (ex.: `TCU`, `STJDJN`).
- `name`: nome legível, vai para `portal_name` das publicações e para o
  corpo do e-mail (`app/mailer.py`).
- `url`: URL principal do portal (não necessariamente a URL da API —
  ver exemplos abaixo).
- `adapter`: string que **precisa bater exatamente** com uma chave do
  dicionário `ADAPTERS` — hoje esse dicionário existe **duplicado** em
  dois lugares, `app/cli.py` (usado pelo `--dry-run` e pelo `--force`)
  e `app/pipeline.py` (usado pelo `run_cycle` real) — registre o
  adapter novo nos dois.
- `engine`: `http` ou `playwright` (só esses dois valores são aceitos
  por `app/registry.py`, campo `Literal["http", "playwright"]`).
- `params` (opcional): dicionário livre de parâmetros que o adapter
  usa para se especializar — hoje só `comunica_pje` usa isso
  (`sigla_tribunal`).
- `enabled`: `true`/`false`. Só portais `enabled: true` entram em
  `get_enabled_portals()` (o que já é consumido por `run_cycle` sem
  `--portal`, e vai importar de novo quando o scheduler existir);
  portais em desenvolvimento devem começar como `false`.

Exemplos reais do arquivo atual (`portals.yaml`):

```yaml
# Adapter simples, sem params:
- code: TCU
  name: "Diário do TCU"
  url: "https://portal.tcu.gov.br/btcu"
  adapter: tcu
  engine: http
  enabled: true

# Adapter parametrizado, reaproveitado por dois portais diferentes:
- code: STJDJN
  name: "STJ no DJEN (Comunica PJe)"
  url: "https://comunica.pje.jus.br/consulta?siglaTribunal=STJ&meio=D"
  adapter: comunica_pje
  engine: http
  params: { sigla_tribunal: STJ }
  enabled: true

- code: TJDFTDJN
  name: "TJDFT no DJEN (Comunica PJe)"
  url: "https://comunica.pje.jus.br/consulta?siglaTribunal=TJDFT&meio=D"
  adapter: comunica_pje
  engine: http
  params: { sigla_tribunal: TJDFT }
  enabled: true
```

### Passo 2 — Criar o adapter em `app/scrapers/`

Todo adapter segue o mesmo esqueleto: herda `BaseScraper`, implementa
`fetch()`, e **separa a parte de rede da parte de parse** — isso é o
que permite testar sem rede no Passo 3. Use `app/scrapers/tst_juslaboris.py`
como referência (é o mais simples dos cinco): a estrutura, comentada
passo a passo, é:

```python
class TstJuslaborisScraper(BaseScraper):
    def __init__(self, url: str, portal_code: str = "TST", portal_name: str = "...") -> None:
        # guarda o que o adapter precisa; url/portal_code/portal_name
        # vêm de portals.yaml via app/cli.py (_build_scraper) e
        # app/pipeline.py (build_scraper)
        ...

    async def fetch(self) -> list[Publication]:
        # fetch() é só a "cola": busca os bytes/texto crus e delega
        # o parse para um método síncrono separado
        xml_text = await self._fetch_feed()
        return self._parse(xml_text)

    async def _fetch_feed(self) -> str:
        # TODA a lógica de rede mora aqui: httpx.AsyncClient com
        # timeout=30, header User-Agent "LupaDiarios/1.0", loop de
        # retry 3x com backoff exponencial (2**(tentativa-1) segundos),
        # levanta a última exceção se as 3 tentativas falharem
        ...

    def _parse(self, xml_text: str) -> list[Publication]:
        # NENHUMA chamada de rede aqui — só transforma texto/JSON/HTML
        # já em mãos em list[Publication]. É este método que o teste
        # chama diretamente, passando o conteúdo de uma fixture salva
        # em disco, sem precisar de internet.
        ...
```

Por que separar `_fetch_*` de `_parse`: é o que torna possível escrever
um teste que roda em CI/local sem rede e sem depender do portal estar
no ar — o teste chama `scraper._parse(conteudo_da_fixture)` direto, sem
passar por `fetch()`. Os cinco adapters existentes seguem exatamente
esse padrão (compare `app/scrapers/comunica_pje.py`, `tcu.py`, `tcdf.py`
— todos têm um `_fetch_*` e um ou mais `_parse*`).

Se o seu adapter precisar de parâmetro vindo de `portals.yaml`
(`params`), siga o padrão de `app/scrapers/comunica_pje.py`: o
`__init__` recebe `params: dict` e valida o campo esperado logo de
cara, levantando `ValueError` com mensagem clara se faltar — não falhe
silenciosamente no meio do `fetch()`.

### Passo 3 — Salvar a fixture e escrever o teste sem rede

1. Rode o adapter manualmente (ou `scripts/inspect.py`) contra o portal
   real, copie a resposta (XML/JSON/HTML) e salve em
   `tests/fixtures/<nome_descritivo>.{xml,json,html}` — hoje existem:
   `tst_juslaboris_feed.xml`, `comunica_pje_stj.json`, `tcu.html`,
   `tcdf_diarios.json`, `tcdf_diario_detalhe.json`.
2. Crie `tests/test_scrapers_<portal>.py`. Exemplo real completo
   (`tests/test_scrapers_tst.py`):

```python
from pathlib import Path
from app.scrapers.tst_juslaboris import TstJuslaborisScraper

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tst_juslaboris_feed.xml"


def test_parse_feed_returns_publications() -> None:
    xml_text = FIXTURE_PATH.read_text(encoding="utf-8")
    scraper = TstJuslaborisScraper(url="https://juslaboris.tst.jus.br/feed/atom_1.0/site")

    publications = scraper._parse(xml_text)  # chama o parse direto, sem rede

    assert len(publications) > 0
    first = publications[0]
    assert first.portal_code == "TST"
    assert first.page_url.startswith("http")
```

Note que este teste **não precisa** da fixture `db_session` de
`tests/conftest.py` nem do banco de pé — ele só testa o `_parse`, que é
função pura. Só os testes que tocam o banco (`tests/test_dedupe.py`,
`tests/test_pipeline.py`, `tests/test_routers.py`) precisam do `db` de
pé.

### Passo 4 — Registrar o adapter em `app/cli.py` E em `app/pipeline.py`

Os dois arquivos têm, hoje, um dicionário `ADAPTERS` próprio (mesma
forma, mantidos em paralelo — `app/cli.py` para `--dry-run`/`--force`,
`app/pipeline.py` para o `run_cycle` real). Adicione a importação da
classe e uma entrada em **ambos**, usando a mesma string que você
colocou no campo `adapter` de `portals.yaml`:

```python
from app.scrapers.meu_novo_adapter import MeuNovoScraper

ADAPTERS: dict[str, type[BaseScraper]] = {
    "juslaboris_feed": TstJuslaborisScraper,
    "comunica_pje": ComunicaPjeScraper,
    "tcu": TcuScraper,
    "tcdf": TcdfScraper,
    "meu_novo_adapter": MeuNovoScraper,  # <- nova linha
}
```

Se o portal usa `params` em `portals.yaml`, não precisa mexer na
função que constrói o scraper (`_build_scraper` em `app/cli.py`,
`build_scraper` em `app/pipeline.py`) — ambas já repassam
`portal.params` para qualquer adapter cujo `portals.yaml` declare
`params`.

### Passo 5 — Testar manualmente antes de considerar pronto

```bash
uv run pytest tests/test_scrapers_<portal>.py -q     # sem rede, deve passar
uv run python -m app.cli run --portal CODE --dry-run  # com rede, contra o site real
```

O `--dry-run` deve imprimir uma lista real de publicações do portal
(`[CODE] data - título` + URL). Só considere o adapter pronto quando os
dois passarem — o teste garante que o parse está correto contra uma
amostra fixa; o dry-run garante que a requisição real ainda funciona
hoje (sites mudam). Depois disso, se quiser validar o ciclo completo
(download + e-mail) contra o site real, use `run` sem `--dry-run` — mas
prefira fazer isso com `MAIL_TO` apontando para o seu próprio e-mail
primeiro.

### Convenções obrigatórias (não pule nenhuma — vêm de `CLAUDE.md`)

- **Timeout de 30s** em toda requisição HTTP (`httpx.AsyncClient(timeout=30, ...)`).
- **Retry 3x com backoff exponencial** (`2 ** (tentativa - 1)` segundos:
  1s, 2s) em qualquer falha de rede — todos os adapters e também
  `app/downloader.py` implementam isso manualmente (não há biblioteca
  de retry no projeto).
- **User-Agent fixo**: `"LupaDiarios/1.0"` em todo header.
- **Nunca fazer scraping agressivo**: minimize requests. Exemplo real de
  como isso se traduziu em código: o adapter `comunica_pje.py` usa o
  teto de itens por página que a própria API aceita (`ITEMS_PER_PAGE =
  1000`) para minimizar o número de páginas, tem um teto de páginas por
  execução (`MAX_PAGES = 10` — é a origem da pendência de STJDJN/
  TJDFTDJN na seção 1) e espera `PAGE_DELAY_SECONDS = 5` segundos entre
  páginas — não porque é bonito, mas porque a API do DJEN devolveu um
  429 real durante a investigação (header `x-ratelimit-limit: 20`).
- **Tratamento de rate-limit (429), quando aplicável**: veja
  `app/scrapers/comunica_pje.py`, método `_retry_after_seconds` — em vez
  de aplicar o backoff genérico num 429, o adapter lê o header
  `Retry-After` da resposta e espera exatamente esse tempo; se o header
  não vier, usa um fallback mais longo (`RATE_LIMIT_FALLBACK_SECONDS =
  10`) do que o backoff normal, porque um 429 significa que a janela de
  limite já estourou — esperar pouco só geraria outro 429. Isso não é
  genérico em `BaseScraper`; é tratado dentro do próprio adapter porque
  só `comunica_pje` (STJDJN/TJDFTDJN) mostrou esse comportamento até
  agora. Se o seu novo portal também tiver rate-limit, siga o mesmo
  padrão: leia `Retry-After` antes de assumir um número fixo.
- **Fixture + teste sem rede é obrigatório**, não opcional — nenhum
  adapter deve ser considerado "pronto" sem os dois.
- **Logging, nunca `print`** dentro de `app/`, com uma exceção
  deliberada: `app/cli.py` usa `print` para a saída voltada ao operador
  no terminal (é a própria interface de linha de comando), mas ainda
  usa `logging` para tudo que é diagnóstico interno — os adapters e o
  pipeline usam só `logging.getLogger(__name__)`.
- **Type hints em toda assinatura pública.**

---

## 5. Onde ficam as coisas (referência rápida)

| Eu quero... | Vá em... |
|---|---|
| Adicionar, desabilitar ou reconfigurar um portal | `portals.yaml` |
| Mudar o horário/frequência do scan | `SCAN_CRON` no `.env` (variável já lida por `app/config.py`; ainda não consumida por nenhum scheduler — Fase 16) |
| Mudar o limite de anexo do e-mail | `MAX_ATTACH_MB` no `.env` (já lida por `app/config.py` e **já aplicada de verdade** pelo mailer — `app/mailer.py`, `build_email`) |
| Mudar quantos dias o buffer guarda publicações | `RETENTION_DAYS` no `.env` (já lida; ainda não usada — Fase 15) |
| Ver/mudar o modelo das tabelas do banco | `app/models.py` (`Publication`, `SeenHash`) |
| Ver a regra de dedupe (hash, filtro) | `app/dedupe.py` |
| Ver/mudar a configuração lida do `.env` | `app/config.py` |
| Ver como os arquivos são baixados (retry, extensão por Content-Type) | `app/downloader.py` |
| Ver a regra dos 15MB e a montagem do e-mail | `app/mailer.py` (`build_email`, `send_email`) |
| Ver a orquestração de um ciclo completo (fetch→dedupe→download→mail→sent_at) | `app/pipeline.py` (`run_cycle`) |
| Disparar o pipeline via HTTP | `app/routers.py` (`POST /run`, `POST /run/{portal_code}`) |
| Adicionar um adapter novo | ver seção 4 acima; arquivos em `app/scrapers/`, registro em `app/cli.py` **e** `app/pipeline.py` |
| Ver como o CLI resolve portal → adapter | `app/cli.py`, funções `_find_portal` e `_build_scraper` |
| Rodar/testar um portal sem afetar o banco | `uv run python -m app.cli run --portal CODE --dry-run` |
| Rodar o pipeline de verdade (grava, baixa, envia e-mail) | `uv run python -m app.cli run [--portal CODE]` ou `POST /run` / `POST /run/{portal_code}` |
| Reenviar manualmente publicações já vistas de um portal (sem mexer no banco via SQL) | `uv run python -m app.cli run --portal CODE --force` (ver seção 5.1) |
| Ver o schema real de um portal (JSON/XML/HTML de exemplo) | `tests/fixtures/` |
| Ver a rota de health check | `app/main.py` (`GET /health`) |
| Configurar variáveis de ambiente locais | copiar `.env.example` para `.env` e preencher |
| Ver como o Docker Compose sobe app+banco | `docker-compose.yml` / `Dockerfile` |
| Investigar um portal novo antes de codar | `scripts/inspect.py` |
| Ver o roadmap completo (fases futuras) | `PLANO.md` |
| Fazer deploy na VM Oracle A1 | `DEPLOY.md` |
| Ver as regras de negócio (o "porquê" das decisões) | `SPEC.md` |
| Ver as convenções fixas de stack/arquitetura | `CLAUDE.md` |

### 5.1. Reenviar manualmente publicações já vistas (`--force`)

Feature pontual fora do roadmap do `PLANO.md`, aprovada à parte
(commit `9b5f5c3`): antes, para reprocessar publicações que já tinham
sido enviadas (por exemplo, para testar a correção de um bug), era
preciso rodar `DELETE FROM seen_hashes` / `DELETE FROM publications`
direto no Postgres — funciona, mas é fácil apagar mais do que deveria e
não é uma operação disponível sem acesso ao banco.

```bash
uv run python -m app.cli run --portal CODE --force
```

`--force` sempre exige `--portal CODE` — reenviar todos os portais de
uma vez de uma só tacada seria destrutivo demais, então o comando sai
com erro se `--force` for usado sem `--portal`. Por baixo dos panos:
faz um `fetch()` real do portal, calcula o `content_hash` de cada
publicação encontrada (mesma fórmula de sempre,
`app.dedupe.compute_hash`) e apaga de `seen_hashes`/`publications`
**só as linhas com esses hashes específicos** (`app.dedupe.clear_hashes`)
— nunca a tabela inteira, nunca por `portal_code` cru, para não
arriscar apagar dado de outro portal ou período por engano. Em seguida
roda o pipeline normal (`app.pipeline.run_cycle`), que trata essas
publicações como novas de novo e as reenvia por e-mail. Já validado ao
vivo nesta sessão.

---

## 6. Variáveis de ambiente (`.env.example`)

| Variável | Para que serve | Usada hoje? |
|---|---|---|
| `DATABASE_URL` | String de conexão do Postgres (formato `postgresql+asyncpg://...`). Fora do Docker (`uv run`) aponta para `localhost`; dentro do compose, o serviço `app` recebe uma versão sobrescrita apontando para o host interno `db` (ver comentário no topo do `.env.example` e em `docker-compose.yml`). | **Sim** — `app/db.py` cria o engine a partir dela; testes, dry-run e pipeline real dependem dela. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Credenciais usadas tanto para montar a `DATABASE_URL` do serviço `app` no compose quanto para inicializar o container `db` (imagem `postgres:17-alpine`). | **Sim**, via `docker-compose.yml`. |
| `SCAN_CRON` | Expressão cron de quando rodar o ciclo de coleta (padrão: de hora em hora, 8h-20h, seg-sex). | Lida por `app/config.py`; **ainda não consumida** — não há scheduler implementado (Fase 16). |
| `TZ` | Timezone do agendamento (`America/Sao_Paulo`). | Lida por `app/config.py`; **ainda não consumida** pelo mesmo motivo acima. Nota: o adapter `comunica_pje.py` já usa `America/Sao_Paulo` internamente (hardcoded via `zoneinfo`, não lendo esta variável) para calcular "hoje" na busca por data. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_TLS` | Credenciais do MailGrid para envio de e-mail. | **Sim** — `app/mailer.py` (`send_email`) usa todas para enviar de verdade via `aiosmtplib`, STARTTLS real, já testado contra o MailGrid nesta sessão. |
| `MAIL_FROM` / `MAIL_TO` | Remetente e destinatário(s) do e-mail de novidades. | **Sim** — lidas em `app/mailer.py`. `MAIL_TO` já suporta múltiplos destinatários separados por vírgula (o `aiosmtplib` extrai a lista do header `To` da mensagem automaticamente; nenhum parsing extra foi necessário no código). |
| `MAX_ATTACH_MB` | Limite (em MB) da soma de anexos por e-mail (regra R2 do `SPEC.md`) — **global por e-mail**, não por portal. | **Sim** — `app/mailer.py` (`build_email`) aplica a regra de verdade: soma os arquivos em ordem de descoberta até o limite; o que excede vira link no corpo com aviso de tamanho. |
| `RETENTION_DAYS` | Quantos dias uma publicação enviada fica no buffer antes de ser apagada. | Lida por `app/config.py` (padrão 3); **ainda não usada** — job de retenção é Fase 15. |
| `JWT_SECRET` | Reservado para a futura integração com o SaaS Lupa (Django) via JWT. | Explicitamente **fora de escopo do MVP** — só existe a variável reservada, nenhuma autenticação é implementada (`CLAUDE.md` e `SPEC.md` são explícitos sobre isso). |

Importante: como `SMTP_*`, `MAIL_FROM` e `MAIL_TO` são campos
obrigatórios (sem valor padrão) em `app/config.py`, a aplicação **não
sobe** sem um `.env` com algum valor preenchido nesses campos. Hoje
esses campos já são usados para enviar e-mail de verdade sempre que o
pipeline roda sem `--dry-run` — preencha com credenciais reais do
MailGrid antes de rodar `run` (sem `--dry-run`) ou `send-test`; para
só rodar os testes e o `--dry-run`, valores fictícios bastam.

---

## 7. Glossário rápido

- **Adapter**: classe em `app/scrapers/` que sabe coletar publicações de
  um portal específico (ou de uma família de portais parametrizada, como
  `comunica_pje`). Todo adapter herda de `BaseScraper` e implementa
  `fetch()`.
- **Engine**: campo de `portals.yaml` que diz se o adapter usa requisição
  HTTP simples (`http`, via `httpx`) ou navegador automatizado
  (`playwright`) — hoje nenhum portal habilitado usa `playwright`.
- **Dry-run**: modo de execução (`--dry-run`) que só coleta e imprime,
  sem gravar no banco, sem baixar arquivo e sem enviar e-mail — é o
  modo seguro para testar um portal sem efeitos colaterais.
- **Ciclo**: uma execução completa do pipeline (`app.pipeline.run_cycle`)
  para um portal ou para todos os habilitados: fetch → dedupe →
  download → e-mail (se houver novidade) → `sent_at`. Disparado hoje
  via `run` (sem `--dry-run`) do CLI ou via `POST /run`/`POST
  /run/{portal_code}`; a Fase 16 vai automatizar esse disparo por cron.
- **`--force`**: flag do comando `run` do CLI (fora do `PLANO.md`
  original) que libera as publicações atuais de um portal para reenvio,
  apagando só os hashes exatos delas de `seen_hashes`/`publications`
  antes de rodar o ciclo normal — ver seção 5.1.
- **Dedupe**: mecanismo que evita reenviar a mesma publicação em ciclos
  diferentes, comparando um hash (`content_hash`) contra a tabela
  `seen_hashes`.
- **Regra dos 15MB (R2)**: limite `MAX_ATTACH_MB`, aplicado **globalmente
  por e-mail** (soma de todos os portais do ciclo, não por portal), com
  desempate por ordem de descoberta (por portal, na ordem em que
  apareceram, depois por `published_at`) — não "menores primeiro". A
  partir do arquivo que estouraria a soma, ele e todos os seguintes
  entram no corpo como link com aviso de tamanho; nenhuma publicação é
  omitida por causa disso. Implementada em `app/mailer.py`
  (`_assign_attachments`).
- **`seen_hashes` vs `publications`**: `seen_hashes` guarda só o hash e
  a data em que foi visto pela primeira vez — é a memória de dedupe e
  **nunca é apagada** (nem pela retenção). `publications` guarda o
  conteúdo completo (título, resumo, arquivos) e é um **buffer
  temporário**: existe só para montar o e-mail e é apagado depois de
  `RETENTION_DAYS` dias (quando a Fase 15 existir). Se fossem a mesma
  tabela, o job de retenção teria que decidir linha a linha o que
  preservar — separá-las torna a regra de retenção uma instrução única,
  sem exceções.
- **Retenção**: job (ainda não implementado, Fase 15) que apaga
  publicações antigas de `publications` (e seus arquivos em disco) —
  o banco é um buffer operacional, não um histórico permanente.

---

## Fontes desta documentação

Este README foi escrito originalmente lendo o código do repositório em
2026-08-13 (logo após a Fase 10) e atualizado em 2026-08-13, no mesmo
dia, depois da implementação das Fases 11-14 (`app/downloader.py`,
`app/mailer.py`, `app/pipeline.py`, `app/routers.py`), de uma correção
de bug no downloader (commit `baeaed3`) e da feature `--force` no CLI
(commit `9b5f5c3`, fora do `PLANO.md` original). Se o código mudar de
novo, este arquivo pode ficar desatualizado — em caso de dúvida, o
código em `app/` é sempre a fonte de verdade final sobre o que está de
fato implementado.
