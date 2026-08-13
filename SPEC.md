# SPEC — Lupa Diários (MVP)

## 1. Objetivo
Monitorar portais de Diários Oficiais brasileiros e entregar por e-mail,
no mesmo dia da publicação, o texto das publicações novas e seus
arquivos. O serviço roda sozinho (agendado), com dedupe confiável e
retenção curta: o banco é um buffer operacional, não um acervo.

## 2. Escopo do MVP / Fora de escopo
Entra no MVP: pipeline completo (scrape texto + download de arquivos →
dedupe → e-mail → retenção), 4-5 portais de menor risco (o PLANO.md
define o recorte; os demais ficam enabled=false no portals.yaml), API
mínima de operação, Docker Compose com app + PostgreSQL.
Fora de escopo (não implementar): JWT/autenticação, integração com o
SaaS Lupa (Django), filtros por palavra-chave/OAB, painel web, filas,
multi-tenant, Alembic/migrations. Nada disso pode, porém, ser
bloqueado pela arquitetura.

## 3. Regras de negócio
R1 — Coleta dupla: de cada portal, raspar o TEXTO das publicações
(título, data de publicação, resumo/corpo quando existir, URL da
página) E baixar os ARQUIVOS vinculados (PDF/ZIP) para data/files/,
organizados por portal/data.
R2 — Limite de anexo: no e-mail, anexar arquivos até a soma de
MAX_ATTACH_MB (padrão 15). Arquivo que exceda o limite individual ou
estoure a soma NÃO é anexado: o item aparece no corpo com o link
original e aviso explícito, ex.: "📎 Arquivo de 42 MB — acima do
limite de anexo de 15 MB, acesse pelo link". Nenhuma publicação é omitida por
causa de tamanho.
R3 — Buffer de 3 dias: publicações recebem sent_at no disparo. Job
diário de retenção apaga registros de publications e os arquivos
correspondentes em disco com sent_at anterior a RETENTION_DAYS (3).
A tabela seen_hashes (dedupe) nunca é apagada por esse job.
R4 — Isolamento de falha: erro em um portal não interrompe o ciclo dos
demais; o erro é logado e o portal tenta de novo no próximo ciclo.
R5 — Um e-mail por ciclo, somente quando houver novidade. Ciclo sem
publicação nova não envia nada.

## 4. Modelo de dados (PostgreSQL 17)
Tabela publications: id (pk), portal_code, portal_name, title,
published_at (date), page_url, summary (text, nullable), files (jsonb:
lista de {url, path, size_bytes, attached: bool}), content_hash
(unique), created_at, sent_at (nullable). Índices em (portal_code,
published_at) e sent_at.
Tabela seen_hashes: content_hash (pk), first_seen_at.
content_hash = sha256(portal_code + page_url + published_at ISO).
Criação via SQLAlchemy create_all no startup do app.

## 5. Pipeline
scheduler (cron SCAN_CRON, TZ America/Sao_Paulo)
  → registry carrega portals.yaml (enabled=true)
  → adapter.fetch() por portal (paralelismo simples é aceitável;
    correção > velocidade)
  → para cada Publication: se hash ∈ seen_hashes, descarta; senão
    grava em seen_hashes + publications
  → downloader baixa os arquivos (timeout, retry, tamanho registrado)
  → mailer monta UM e-mail HTML agrupado por portal e envia (R2)
  → grava sent_at nas publicações enviadas
Job diário de retenção (uma execução/dia dentro do scheduler): aplica R3.

## 6. E-mail
Assunto: "Lupa Diários Oficiais — {N} novas publicações — {dd/mm/aaaa HH:MM}".
Corpo HTML simples: um bloco por portal (nome do portal como título),
e por publicação: título com link para page_url, data, resumo (se
houver) e a lista de arquivos — anexado (nome do anexo) ou link com
aviso de tamanho (R2). Rodapé com identificação do serviço.
SMTP: MailGrid, STARTTLS, credenciais via env. Comando `send-test`
envia e-mail de verificação de configuração.

## 7. API (FastAPI) — operação, sem autenticação no MVP
GET /health → {status, db, last_run_at}
POST /run → dispara um ciclo completo imediatamente (async)
POST /run/{portal_code} → dispara um portal específico
GET /portals → portais do portals.yaml com enabled e última execução
GET /publications?limit=50 → últimas publicações do buffer
A API não é exposta publicamente no MVP (acesso via SSH/túnel).

## 8. CLI
uv run python -m app.cli run [--portal CODE] [--dry-run]
  --dry-run: executa fetch e imprime o que seria enviado; não grava
  sent_at, não baixa arquivos, NUNCA envia e-mail.
uv run python -m app.cli send-test

## 9. Configuração (.env — ver .env.example)
DATABASE_URL=postgresql+asyncpg://lupa:...@db:5432/lupa_diarios
SCAN_CRON="0 8-20 * * 1-5"        TZ=America/Sao_Paulo
SMTP_HOST / SMTP_PORT=587 / SMTP_USER / SMTP_PASSWORD / SMTP_TLS=true
MAIL_FROM / MAIL_TO (lista separada por vírgula)
MAX_ATTACH_MB=15                  RETENTION_DAYS=3
JWT_SECRET=  (reservado; não usado no MVP)

## 10. Portais e particularidades
| Código | Fonte | Notas de estratégia |
|---|---|---|
| JFDFDJN | trf1.jus.br/trf1/biblioteca/diarios-da-justica | Mesmo adapter do TRFDJN (trf1_biblioteca); seções por diário. |
| TCU | portal.tcu.gov.br/btcu | Investigar API/URL de PDF antes de Playwright. |
| TCDF | doe.tc.df.gov.br | URLs sugerem padrão /O/{ano}/{edição}; tentar URL previsível. |
| STFDJE | digital.stf.jus.br/publico/publicacoes | Front moderno; procurar XHR/API no inspect. |
| STJ | processo.stj.jus.br/processo/dj/init | Publica ZIP diário com muitos PDFs; listar conteúdo do ZIP no e-mail; arquivos grandes → R2. |
| STJDJN | comunica.pje.jus.br (siglaTribunal=STJ) | DJEN: front consome API JSON; usar a API via httpx. Adapter comunica_pje parametrizado. |
| TST | juslaboris.tst.jus.br/feed/atom_1.0/site | Feed Atom — parse XML, sem browser. Menor risco de todos. |
| TSTDJN | dejt.jt.jus.br/dejt/f/n/diariocon | Adapter dejt parametrizado por tribunal. |
| TRT10DJN | dejt (tribunal=TRT da 10ª Região) | Mesmo adapter dejt. |
| TJDFTDJN | pesquisadje.tjdft.jus.br | Investigar API do buscador. |
| TRFDJN | trf1_biblioteca (secao=TRF1) | Mesmo adapter do JFDFDJN. |
| TRF1ATA | trf1.jus.br/trf1/ataas/atas | Atas de distribuição. |
Observação: intimações "TRF1 PJe" tendem a estar cobertas pelo DJEN
(comunica_pje com siglaTribunal=TRF1) — validar na fase do adapter.

## 11. Critérios de aceite do MVP (fim do dia)
1. `uv run pytest -q` verde, com testes de dedupe, regra dos 15 MB e
   retenção (seen_hashes preservada).
2. `--dry-run` de cada portal do recorte imprime publicações reais.
3. `send-test` chega na caixa de entrada via MailGrid.
4. Um ciclo real (`POST /run` ou cli sem --dry-run) entrega e-mail com
   texto + anexos/links conforme R2 e grava sent_at.
5. Segundo ciclo imediato não reenvia nada (dedupe comprovado).
6. `docker compose up --build` sobe app + postgres no WSL com
   /health respondendo.