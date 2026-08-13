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
Diários Oficiais brasileiros, raspa o texto das publicações e (em fases
futuras) baixa os arquivos vinculados (PDF/ZIP) e dispara e-mail com as
novidades. Roda 24/7 em Docker.

### O que já funciona hoje (Fases 1 a 10 do PLANO.md, implementadas e testadas)

- **Setup do projeto**: `uv`, Python 3.13, dependências, `ruff`,
  `pytest`, `scripts/inspect.py` (`app/`, `pyproject.toml`).
- **Configuração e registry de portais**: `app/config.py` lê o `.env`;
  `app/registry.py` carrega e valida `portals.yaml`.
- **Docker Compose + FastAPI mínimo**: `docker-compose.yml`,
  `Dockerfile`, `app/main.py` com `GET /health`.
- **Modelo de dados**: tabelas `publications` e `seen_hashes`
  (`app/models.py`), criadas via `create_all` no startup da app
  (`app/main.py`) — não há Alembic/migrations no MVP.
- **BaseScraper + dedupe**: contrato comum de adapter
  (`app/scrapers/base.py`) e a lógica de hash/dedupe
  (`app/dedupe.py`).
- **5 adapters funcionando**, todos parte do recorte do MVP definido no
  `PLANO.md` (seção 4) — os únicos 5 portais habilitados
  (`enabled: true`) em `portals.yaml` hoje:
  - **TST** — feed Atom (`app/scrapers/tst_juslaboris.py`)
  - **STJDJN** e **TJDFTDJN** — API JSON do DJEN/comunica_pje, mesmo
    adapter parametrizado por tribunal (`app/scrapers/comunica_pje.py`)
  - **TCU** — HTML estático server-side rendered (`app/scrapers/tcu.py`)
  - **TCDF** — API JSON descoberta no bundle JS da SPA
    (`app/scrapers/tcdf.py`)
- **CLI de teste manual**: `uv run python -m app.cli run --portal CODE
  --dry-run` (`app/cli.py`) — hoje é o único comando implementado do
  CLI; só faz `fetch()` e imprime, não grava nada, não baixa arquivo,
  não envia e-mail.

### O que ainda NÃO existe (Fases 11 a 18 do PLANO.md — não implementadas)

Nada abaixo existe em código ainda. Não confie em nenhum destes
comportamentos até a fase correspondente ser implementada:

- Download de arquivos para `data/files/` (`app/downloader.py` — Fase 11)
- Montagem e envio de e-mail, regra dos 15 MB (`app/mailer.py` — Fases
  12-13)
- Pipeline completo (fetch → dedupe → download → mailer → `sent_at`) e
  `run` sem `--dry-run` (`app/pipeline.py` — Fase 14)
- Job de retenção de 3 dias (`app/retention.py` — Fase 15)
- Scheduler/cron (`app/scheduler.py` — Fase 16)
- Endpoints `POST /run`, `POST /run/{portal_code}`, `GET /portals`,
  `GET /publications` (`app/routers.py` — Fases 14 e 17)

Ou seja: hoje o projeto **coleta e imprime** publicações de 5 portais,
com dedupe funcionando contra o banco real. Ele ainda não baixa
arquivo, não manda e-mail e não roda sozinho — isso é o roadmap em
`PLANO.md`, fases 11 em diante.

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
scheduler [futuro: app/scheduler.py]
  └─▶ registry (app/registry.py) carrega portals.yaml, filtra enabled=true
  └─▶ para cada portal: adapter.fetch() -> list[Publication]
        (app/scrapers/<adapter>.py, herda de app/scrapers/base.py)
        try/except por portal — erro em um não derruba os demais
  └─▶ dedupe (app/dedupe.py): calcula content_hash, filtra contra
        seen_hashes, grava as novas em seen_hashes + publications
  └─▶ [futuro] downloader (app/downloader.py): baixa arquivos p/ data/files/
  └─▶ [futuro] mailer (app/mailer.py): monta e envia UM e-mail agrupado
  └─▶ [futuro] grava sent_at nas publicações enviadas

[futuro] job diário de retenção (app/retention.py):
  apaga publications+arquivos com sent_at > RETENTION_DAYS dias;
  nunca toca seen_hashes
```

Como rodar isso manualmente hoje (sem scheduler, sem e-mail):

```
app/cli.py (--dry-run)
  └─▶ registry.load_portals() acha o Portal pelo code
  └─▶ resolve a classe do adapter no dicionário ADAPTERS
  └─▶ scraper.fetch() -> list[Publication]
  └─▶ imprime no terminal (não toca no banco, não baixa, não envia)
```

Duas peças centrais para entender antes de mexer em qualquer adapter:

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

---

## 3. Como rodar o projeto hoje

Comandos reais, testados nas Fases 1-10:

```bash
# 1. Subir só o banco (é o que os testes e o dry-run precisam)
docker compose up -d db

# 2. Rodar a suíte de testes
uv run pytest -q

# 3. Testar um adapter manualmente contra o portal real
uv run python -m app.cli run --portal TST --dry-run
uv run python -m app.cli run --portal STJDJN --dry-run
uv run python -m app.cli run --portal TCU --dry-run
uv run python -m app.cli run --portal TCDF --dry-run
uv run python -m app.cli run --portal TJDFTDJN --dry-run

# 4. Lint e format antes de commitar
uv run ruff check --fix . && uv run ruff format .

# 5. Subir tudo em Docker (app + db)
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
db`, os testes que tocam banco (`tests/test_dedupe.py`, por exemplo)
vão falhar com erro de conexão recusada — não é bug do teste, é o
serviço `db` que não está de pé. Isso é uma decisão deliberada
(`CLAUDE.md`: "Sem ORM extra... simplicidade é requisito de negócio") —
testar contra Postgres real evita bugs que só aparecem com o dialeto
real (tipos `JSONB`, `unique constraint` etc.) e que um SQLite fake não
pegaria.

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
- `name`: nome legível, vai para `portal_name` das publicações e (em
  fases futuras) para o corpo do e-mail.
- `url`: URL principal do portal (não necessariamente a URL da API —
  ver exemplos abaixo).
- `adapter`: string que **precisa bater exatamente** com uma chave do
  dicionário `ADAPTERS` em `app/cli.py` — é o nome lógico do adapter,
  não o nome da classe Python nem do arquivo.
- `engine`: `http` ou `playwright` (só esses dois valores são aceitos
  por `app/registry.py`, campo `Literal["http", "playwright"]`).
- `params` (opcional): dicionário livre de parâmetros que o adapter
  usa para se especializar — hoje só `comunica_pje` usa isso
  (`sigla_tribunal`).
- `enabled`: `true`/`false`. Só portais `enabled: true` entram em
  `get_enabled_portals()` (o que vai importar quando o scheduler
  existir); portais em desenvolvimento devem começar como `false`.

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
        # vêm de portals.yaml via app/cli.py (_build_scraper)
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
função pura. Só `tests/test_dedupe.py` (e testes futuros de pipeline)
precisam do banco.

### Passo 4 — Registrar o adapter em `app/cli.py`

Adicione a importação da classe e uma entrada no dicionário `ADAPTERS`,
usando a mesma string que você colocou no campo `adapter` de
`portals.yaml`:

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

Se o portal usa `params` em `portals.yaml`, não precisa mexer em
`_build_scraper()` — ele já repassa `portal.params` para qualquer
adapter cujo `portals.yaml` declare `params` (ver `app/cli.py`, função
`_build_scraper`).

### Passo 5 — Testar manualmente antes de considerar pronto

```bash
uv run pytest tests/test_scrapers_<portal>.py -q   # sem rede, deve passar
uv run python -m app.cli run --portal CODE --dry-run  # com rede, contra o site real
```

O `--dry-run` deve imprimir uma lista real de publicações do portal
(`[CODE] data - título` + URL). Só considere o adapter pronto quando os
dois passarem — o teste garante que o parse está correto contra uma
amostra fixa; o dry-run garante que a requisição real ainda funciona
hoje (sites mudam).

### Convenções obrigatórias (não pule nenhuma — vêm de `CLAUDE.md`)

- **Timeout de 30s** em toda requisição HTTP (`httpx.AsyncClient(timeout=30, ...)`).
- **Retry 3x com backoff exponencial** (`2 ** (tentativa - 1)` segundos:
  1s, 2s) em qualquer falha de rede — todos os 5 adapters implementam
  isso manualmente no próprio método `_fetch_*` (não há biblioteca de
  retry no projeto).
- **User-Agent fixo**: `"LupaDiarios/1.0"` em todo header.
- **Nunca fazer scraping agressivo**: minimize requests. Exemplo real de
  como isso se traduziu em código: o adapter `comunica_pje.py` usa o
  teto de itens por página que a própria API aceita (`ITEMS_PER_PAGE =
  1000`) para minimizar o número de páginas, e espera
  `PAGE_DELAY_SECONDS = 5` segundos entre páginas — não porque é bonito,
  mas porque a API do DJEN devolveu um 429 real durante a investigação
  (header `x-ratelimit-limit: 20`).
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
- **Logging, nunca `print`** dentro de `app/` (o único lugar com `print`
  hoje é `app/cli.py`, porque é a própria interface de linha de comando —
  os adapters usam `logging.getLogger(__name__)`).
- **Type hints em toda assinatura pública.**

---

## 5. Onde ficam as coisas (referência rápida)

| Eu quero... | Vá em... |
|---|---|
| Adicionar, desabilitar ou reconfigurar um portal | `portals.yaml` |
| Mudar o horário/frequência do scan | `SCAN_CRON` no `.env` (variável já lida por `app/config.py`; ainda não consumida por nenhum scheduler — Fase 16) |
| Mudar o limite de anexo do e-mail | `MAX_ATTACH_MB` no `.env` (já lida por `app/config.py`; ainda não usada em código de e-mail — Fase 12) |
| Mudar quantos dias o buffer guarda publicações | `RETENTION_DAYS` no `.env` (já lida; ainda não usada — Fase 15) |
| Ver/mudar o modelo das tabelas do banco | `app/models.py` (`Publication`, `SeenHash`) |
| Ver a regra de dedupe (hash, filtro) | `app/dedupe.py` |
| Ver/mudar a configuração lida do `.env` | `app/config.py` |
| Adicionar um adapter novo | ver seção 4 acima; arquivos em `app/scrapers/`, registro em `app/cli.py` |
| Ver como o CLI resolve portal → adapter | `app/cli.py`, funções `_find_portal` e `_build_scraper` |
| Rodar/testar um portal sem afetar o banco | `uv run python -m app.cli run --portal CODE --dry-run` |
| Reenviar manualmente publicações já vistas de um portal (sem mexer no banco via SQL) | `uv run python -m app.cli run --portal CODE --force` (ver seção 5.1) |
| Ver o schema real de um portal (JSON/XML/HTML de exemplo) | `tests/fixtures/` |
| Ver a rota de health check | `app/main.py` (`GET /health`) |
| Configurar variáveis de ambiente locais | copiar `.env.example` para `.env` e preencher |
| Ver como o Docker Compose sobe app+banco | `docker-compose.yml` / `Dockerfile` |
| Investigar um portal novo antes de codar | `scripts/inspect.py` |
| Ver o roadmap completo (fases futuras) | `PLANO.md` |
| Ver as regras de negócio (o "porquê" das decisões) | `SPEC.md` |
| Ver as convenções fixas de stack/arquitetura | `CLAUDE.md` |

### 5.1. Reenviar manualmente publicações já vistas (`--force`)

Feature pontual fora do roadmap do `PLANO.md`, aprovada à parte: antes,
para reprocessar publicações que já tinham sido enviadas (por exemplo,
para testar a correção de um bug), era preciso rodar `DELETE FROM
seen_hashes` / `DELETE FROM publications` direto no Postgres — funciona,
mas é fácil apagar mais do que deveria e não é uma operação disponível
sem acesso ao banco.

```bash
uv run python -m app.cli run --portal CODE --force
```

`--force` sempre exige `--portal CODE` — reenviar todos os portais de
uma vez seria destrutivo demais, então o comando sai com erro se
`--force` for usado sem `--portal`. Por baixo dos panos: faz um
`fetch()` real do portal, calcula o `content_hash` de cada publicação
encontrada (mesma fórmula de sempre, `app.dedupe.compute_hash`) e apaga
de `seen_hashes`/`publications` **só as linhas com esses hashes
específicos** (`app.dedupe.clear_hashes`) — nunca a tabela inteira, nunca
por `portal_code` cru, para não arriscar apagar dado de outro portal ou
período por engano. Em seguida roda o pipeline normal
(`app.pipeline.run_cycle`), que trata essas publicações como novas de
novo e as reenvia por e-mail.

---

## 6. Variáveis de ambiente (`.env.example`)

| Variável | Para que serve | Usada hoje? |
|---|---|---|
| `DATABASE_URL` | String de conexão do Postgres (formato `postgresql+asyncpg://...`). Fora do Docker (`uv run`) aponta para `localhost`; dentro do compose, o serviço `app` recebe uma versão sobrescrita apontando para o host interno `db` (ver comentário no topo do `.env.example` e em `docker-compose.yml`). | **Sim** — `app/db.py` cria o engine a partir dela; testes e dry-run dependem dela. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Credenciais usadas tanto para montar a `DATABASE_URL` do serviço `app` no compose quanto para inicializar o container `db` (imagem `postgres:17-alpine`). | **Sim**, via `docker-compose.yml`. |
| `SCAN_CRON` | Expressão cron de quando rodar o ciclo de coleta (padrão: de hora em hora, 8h-20h, seg-sex). | Lida por `app/config.py`; **ainda não consumida** — não há scheduler implementado (Fase 16). |
| `TZ` | Timezone do agendamento (`America/Sao_Paulo`). | Lida por `app/config.py`; **ainda não consumida** pelo mesmo motivo acima. Nota: o adapter `comunica_pje.py` já usa `America/Sao_Paulo` internamente (hardcoded via `zoneinfo`, não lendo esta variável) para calcular "hoje" na busca por data. |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_TLS` | Credenciais do MailGrid para envio de e-mail. | Lidas por `app/config.py` (são campos obrigatórios de `Settings`, então o `.env` precisa ter algum valor mesmo hoje, mesmo que fictício, para a aplicação subir); **ainda não usadas** para enviar nada (Fases 12-13). |
| `MAIL_FROM` / `MAIL_TO` | Remetente e destinatário(s) do e-mail de novidades. | Lidas por `app/config.py`, mesma situação acima — **ainda não usadas** (Fases 12-14). |
| `MAX_ATTACH_MB` | Limite (em MB) da soma de anexos por e-mail (regra R2 do `SPEC.md`). | Lida por `app/config.py` (padrão 15); **ainda não usada** — regra de anexo é Fase 12. |
| `RETENTION_DAYS` | Quantos dias uma publicação enviada fica no buffer antes de ser apagada. | Lida por `app/config.py` (padrão 3); **ainda não usada** — job de retenção é Fase 15. |
| `JWT_SECRET` | Reservado para a futura integração com o SaaS Lupa (Django) via JWT. | Explicitamente **fora de escopo do MVP** — só existe a variável reservada, nenhuma autenticação é implementada (`CLAUDE.md` e `SPEC.md` são explícitos sobre isso). |

Importante: como `SMTP_*`, `MAIL_FROM` e `MAIL_TO` são campos
obrigatórios (sem valor padrão) em `app/config.py`, a aplicação **não
sobe** sem um `.env` com algum valor preenchido nesses campos — mesmo
que hoje nenhum e-mail seja de fato enviado. Copie `.env.example` para
`.env` e preencha pelo menos com valores fictícios para poder rodar
`docker compose up` ou os testes.

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
- **Dedupe**: mecanismo que evita reenviar a mesma publicação em ciclos
  diferentes, comparando um hash (`content_hash`) contra a tabela
  `seen_hashes`.
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

Este README foi escrito lendo o código real do repositório em
2026-08-13 (`app/`, `portals.yaml`, `.env.example`, `docker-compose.yml`,
`Dockerfile`, `tests/`, `PLANO.md`, `SPEC.md`, `CLAUDE.md`). Se o código
mudar, este arquivo pode ficar desatualizado — em caso de dúvida, o
código em `app/` é sempre a fonte de verdade final sobre o que está de
fato implementado.
