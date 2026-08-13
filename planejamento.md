Use o subagent "planejador" para a tarefa abaixo. O subagent "executor"
NÃO deve ser acionado nesta etapa — nenhuma linha de código será
escrita antes da minha aprovação do plano.

CONTEXTO SOBRE MIM E SOBRE O PROCESSO

Esta é a primeira vez que desenvolvo com agentes de IA (antes programava
manualmente no VS Code). Trabalharemos com dois agentes: o PLANEJADOR
(você, agora) produz e mantém o PLANO.md; o EXECUTOR implementará o
plano fase a fase, sempre com minha aprovação entre as fases. Eu sou o
ponto de decisão entre os dois. Preciso de um MVP básico funcionando
HOJE — simplicidade é requisito de negócio.

O PRODUTO

Microserviço que monitora portais de Diários Oficiais brasileiros
(portals.yaml). Em cada ciclo agendado, para cada portal: raspa as
publicações/notícias em TEXTO (título, data, resumo/corpo quando
existir) E baixa os ARQUIVOS vinculados (PDF/ZIP) para data/files/.
Publicações novas (dedupe por hash) são disparadas por e-mail via SMTP
MailGrid: um e-mail por ciclo, agrupado por portal, com o texto de cada
item e os arquivos ANEXADOS até o limite de 15 MB somados — arquivo que
exceder o limite não é anexado: o item traz o link original com aviso
explícito de tamanho (ex.: "Arquivo de 42 MB — acima do limite, acesse
pelo link"). Nenhuma publicação é omitida por causa de tamanho.

O PostgreSQL é um BUFFER temporário, não histórico: publicações ganham
sent_at no disparo, e um job diário de retenção apaga registros e
arquivos com sent_at anterior a 3 dias. O dedupe vive numa tabela
mínima seen_hashes (hash + data) que a retenção nunca toca — sem isso,
publicações ainda visíveis nos portais seriam reenviadas após 3 dias.

Futuramente este serviço será módulo do meu SaaS (Django, comunicação
via JWT). Hoje NÃO implementamos JWT — apenas não bloquear a evolução
(JWT_SECRET já reservado no .env.example).

Stack fixa (não propor alternativas): Python 3.13 via uv, FastAPI,
Playwright somente onde httpx+selectolax não bastar, PostgreSQL 17 +
SQLAlchemy 2 async + asyncpg, APScheduler (cron 8h-20h seg-sex,
America/Sao_Paulo), aiosmtplib, Docker Compose. Dev em WSL, deploy em
VM Oracle A1 (linux/arm64).

SUA TAREFA: produza o PLANO.md com:

1. Arquitetura: pipeline em texto (scheduler → scrapers → dedupe →
   download → e-mail → marcação sent_at; + job de retenção) e árvore de
   arquivos completa com uma linha por arquivo.
2. Modelo de dados: tabelas publications, seen_hashes e o que mais for
   necessário — minimalismo; explique a separação retenção vs dedupe.
3. Análise portal a portal do portals.yaml: estratégia preferida
   (API JSON > feed > URL previsível > HTML estático > Playwright) e
   risco baixo/médio/alto com justificativa de uma linha.
4. Recorte do MVP DE HOJE: 4-5 portais de menor risco/maior cobertura
   entram hoje; o resto fica enabled=false. Justifique a escolha.
5. Fases de execução para o EXECUTOR: pequenas, com critério de aceite
   verificável (comando exato + saída esperada), commit ao final de
   cada uma, sem dependências de fases futuras. Inclua fases
   específicas para: regra dos 15 MB no mailer (com teste), job de
   retenção de 3 dias (com teste), e docker compose com app + postgres.
6. Riscos de não terminar hoje (3-5) e como o plano mitiga cada um.
7. Perguntas para mim: tudo que ficou ambíguo. Se nada, diga que não há.

Seja concreto (nomes de arquivos e comandos reais), não invente
requisitos, e escreva para eu conseguir acompanhar e aprender. Aguarde
minha aprovação antes de qualquer implementação.