# Guia v3 — Subagents (Planejador + Executor), novas regras de negócio e mapa do curso

Este documento atualiza o v2 em três frentes: incorpora as novas regras de negócio (raspagem de texto + arquivos, limite de 15 MB, buffer de 3 dias no PostgreSQL), introduz a arquitetura de dois agentes — **Planejador** e **Executor** — com os prompts de criação prontos, e mapeia as aulas do seu curso (Pythonando — Desenvolvimento Assistido por IA) para cada etapa do que vamos fazer, para você consultar sob demanda sem precisar assistir tudo hoje.

---

## Parte 1 — Mapa do curso: o que assistir e quando

Você não precisa do curso inteiro hoje. A correspondência entre o curso e este projeto:

**Para hoje (se travar em algo, ~40 min no total):** Módulo 1, aulas 02 (Instalação — Claude Code e Cursor) e 03 (Introdução) cobrem o que as Partes 1-3 do guia v2 descrevem em texto; assista se preferir ver na tela. Aula 06 (Rules) é o conceito por trás do nosso CLAUDE.md. Aula 07 (Conectando a MCP server) é exatamente o Context7 da Parte 4 do v2. **Aulas 08 e 09 (Subagents)** são as mais importantes para esta versão do guia — é o mecanismo dos agentes Planejador e Executor abaixo; se assistir só duas aulas hoje, que sejam essas.

**Para esta semana:** Módulo 2 (Spec Driven Development, aulas 01-03) — nosso fluxo CLAUDE.md → SPEC.md → PLANO.md → fases é uma forma de SDD, e o módulo vai dar nome e profundidade ao que você já estará praticando. Módulo 3 (TDD) conversa com a nossa regra "todo adapter tem teste com fixture".

**Para quando o projeto virar módulo da Lupa:** Módulo 4 (PR Review com GitHub Actions) quando você quiser CI revisando seus PRs; Módulo 5 (Context Engineering) quando o repositório crescer e o CLAUDE.md precisar de manutenção; Módulo 7 (Quality Gate) antes de colocar clientes reais dependendo do serviço.

Ordem sugerida de estudo, portanto: 08-09 → 06 → 07 → módulo 2 → módulo 3 → resto conforme necessidade.

---

## Parte 2 — Novas regras de negócio (o que muda no sistema)

Consolidando o que você definiu, em linguagem de requisito — é assim que vai entrar no CLAUDE.md e no prompt:

**R1 — Conteúdo raspado.** De cada portal coletamos duas coisas: o **texto** da notícia/publicação (título, data, resumo/corpo quando existir) e os **arquivos** vinculados (PDF/ZIP), baixados para `data/files/`.

**R2 — Regra dos 15 MB.** No e-mail, anexamos os arquivos enquanto a soma dos anexos couber em 15 MB. Arquivo que exceda (ou que estoure a soma) **não é anexado**: no corpo do e-mail, o item aparece com o link original e um aviso visível do tipo "📎 Arquivo de 42 MB — acima do limite de anexo, acesse pelo link".

**R3 — Buffer com retenção de 3 dias.** O PostgreSQL é um buffer local, não um arquivo histórico: cada publicação ganha `sent_at` no momento do disparo, e um job diário de limpeza apaga registros (e seus arquivos em disco) com `sent_at` anterior a 3 dias. **Importante — decisão que tomei e você deve confirmar:** o dedupe não pode depender do registro apagado, senão a publicação voltaria a ser enviada após 3 dias. Solução: apagamos o conteúdo (texto e arquivos), mas mantemos numa tabela mínima `seen_hashes` apenas o hash e a data, que pesa bytes. Se você preferir apagar absolutamente tudo, o efeito colateral é reenvio de qualquer publicação que continue visível no portal — quase certamente não é o que você quer.

Acrescente ao CLAUDE.md, na seção Arquitetura:

```markdown
- Coleta = texto da publicação + arquivos (PDF/ZIP) em data/files/.
- E-mail: anexos até 15 MB somados; acima disso, o item entra no corpo
  com o link original e aviso de tamanho. Nunca omitir uma publicação
  por causa de tamanho de arquivo.
- Retenção: publicações e arquivos são um buffer — job diário do
  scheduler apaga tudo com sent_at > 3 dias. O dedupe vive na tabela
  seen_hashes (hash + data), que NUNCA é apagada pelo job de retenção.
```

---

## Parte 3 — Subagents: os agentes Planejador e Executor

### 3.1 O conceito em um parágrafo

No Claude Code, um *subagent* é um agente auxiliar com prompt de sistema próprio, ferramentas próprias e **contexto próprio** — o agente principal delega tarefas a ele e recebe de volta só o resultado. Os dois ganhos práticos: especialização (o Planejador tem instruções de arquiteto e não sabe editar código; o Executor tem instruções de implementador disciplinado) e economia de contexto (a pesquisa longa do planejamento não polui a janela onde o código será escrito — relevante no seu plano Pro). Subagents são arquivos Markdown com um cabeçalho YAML, salvos em `.claude/agents/` no projeto. Você pode criá-los pelo comando interativo `/agents` dentro do Claude Code, ou simplesmente colar os dois arquivos abaixo — colar é mais rápido e o resultado é o mesmo.

### 3.2 Agente 1 — crie o arquivo `.claude/agents/planejador.md`

```markdown
---
name: planejador
description: >
  Arquiteto e planejador do projeto. Use este agente SEMPRE que a tarefa
  for: criar ou revisar o PLANO.md, analisar portais novos antes de
  implementar, decidir estratégia de scraping, ou avaliar impacto de
  mudanças de requisito. Ele NÃO implementa código.
tools: Read, Glob, Grep, WebSearch, WebFetch, Write
---

Você é o PLANEJADOR: arquiteto de software sênior, especialista em
Python, web scraping e sistemas de coleta de dados públicos brasileiros
(Diários Oficiais). Você trabalha em dupla com um agente EXECUTOR que
implementará o que você planejar — seus planos são o contrato dele.

Seu usuário é iniciante em desenvolvimento com agentes: escreva planos
que ele consiga ler, julgar e aprovar; explique decisões não óbvias em
1-2 frases; nunca otimize para impressionar.

Regras invioláveis:
1. Você NUNCA escreve código de produção, não edita arquivos do app e
   não roda comandos. Seu único artefato de escrita é PLANO.md (ou
   revisões dele).
2. Todo plano lê antes CLAUDE.md, SPEC.md e portals.yaml — eles são a
   fonte de verdade sobre stack e regras de negócio. Se o que você
   quer propor conflita com eles, aponte o conflito em vez de ignorar.
3. Todo plano é dividido em fases pequenas; cada fase tem critério de
   aceite VERIFICÁVEL (comando exato + saída esperada) e termina em
   commit. Nenhuma fase depende de código de fase futura.
4. Para cada portal, defina a estratégia na ordem de preferência:
   API JSON escondida > feed RSS/Atom > URL previsível de arquivo >
   HTML estático (httpx+selectolax) > Playwright. Atribua risco
   (baixo/médio/alto) e justifique em uma linha.
5. Quando houver ambiguidade de requisito, liste a pergunta para o
   usuário em vez de assumir silenciosamente.
6. Escopo é sagrado: não invente features. Simplicidade de MVP é
   requisito de negócio deste projeto.
```

### 3.3 Agente 2 — crie o arquivo `.claude/agents/executor.md`

```markdown
---
name: executor
description: >
  Implementador do projeto. Use este agente para executar fases do
  PLANO.md aprovado: escrever código, testes, rodar comandos, corrigir
  bugs. Ele NÃO altera o plano nem o escopo por conta própria.
---

Você é o EXECUTOR: engenheiro de software sênior, disciplinado e
minimalista, especialista na stack deste projeto (Python 3.13 + uv,
FastAPI, Playwright, PostgreSQL/SQLAlchemy async, APScheduler,
aiosmtplib, Docker). Você implementa EXATAMENTE o que o PLANO.md
aprovado descreve, fase a fase.

Regras invioláveis:
1. Antes de qualquer fase, releia CLAUDE.md e a fase correspondente do
   PLANO.md. Implemente somente o que a fase pede — nada de melhorias
   espontâneas, refactors não pedidos ou dependências novas sem
   aprovação explícita do usuário.
2. Se durante a implementação você descobrir que o plano está errado ou
   inviável (ex.: o portal mudou, a API não existe), PARE, explique o
   problema em 2-3 frases e proponha o ajuste — a decisão é do usuário
   (que pode reencaminhar ao planejador). Nunca contorne o plano em
   silêncio.
3. Toda fase termina com: `uv run ruff check --fix . && uv run ruff
   format .`, `uv run pytest -q` verde, o critério de aceite da fase
   demonstrado, e um commit com mensagem curta no imperativo.
4. Todo comando Python roda via `uv run`; dependências entram só via
   `uv add`. Nunca usar pip.
5. Adapters novos exigem fixture salva em tests/fixtures/ e teste que
   roda sem rede. Antes de escrever um adapter, inspecione o portal com
   scripts/inspect.py.
6. Segredos só via variáveis de ambiente. Jamais em código ou commit.
7. Explique ao usuário, em 1-2 frases por decisão relevante, o que fez
   e por quê — ele está aprendendo o fluxo.
```

### 3.4 Como usar a dupla no dia a dia

O campo `description` faz o Claude Code delegar automaticamente na maioria dos casos, mas você pode (e no começo deve) ser explícito. O ciclo fica assim: `use o subagent planejador para criar o PLANO.md conforme o prompt que vou colar` → você lê, pede ajustes, aprova → `use o subagent executor para implementar a Fase 1 do PLANO.md` → valida o critério de aceite → `/clear` → Fase 2, e assim por diante. Quando um portal se revelar diferente do previsto no meio da execução, o fluxo é Executor reporta → você decide → `use o planejador para revisar a estratégia do portal X no PLANO.md` → Executor retoma. Esse vai-e-vem com você no meio é proposital: você é o gate de qualidade entre os dois agentes, e é assim que se mantém controle sendo iniciante.

Uma nota honesta: para um MVP solo, dava para viver só com o Plan Mode. O motivo de eu endossar a dupla no seu caso é triplo — seu curso ensina exatamente esse mecanismo (aulas 08-09, você pratica o que estuda), a separação de contextos economiza seu limite do plano Pro, e os prompts acima criam guard-rails que protegem um iniciante dos dois erros clássicos (plano que vira código sem revisão, e executor que "melhora" coisas por conta própria).

---

## Parte 4 — Prompt de planejamento v2 (cole no Claude Code)

Preparação igual à do guia v2 (pasta, `git init`, CLAUDE.md com os deltas da Parte 2 acima, portals.yaml, os dois arquivos de agents). Depois abra `claude` e cole:

```text
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
```

---

## Parte 5 — Sequência de hoje, revisada

1. Ambiente (guia v2, Partes 1-3). Se travar: aulas 02-03 do curso.
2. Criar pasta + `git init` + CLAUDE.md (com deltas da Parte 2) + portals.yaml + `.claude/agents/planejador.md` + `.claude/agents/executor.md`.
3. (Opcional, 8 min) Aula 08 do curso para ver subagents na tela antes de usar.
4. `claude` → colar o prompt da Parte 4 → ler o PLANO.md → responder as perguntas → aprovar.
5. `use o subagent executor para implementar a Fase 1` → validar → `/clear` → próxima fase.
6. Teste real do MailGrid (`send-test`) assim que a fase do mailer terminar — não deixe para o fim do dia.
7. `docker compose up --build` no WSL fecha o dia; deploy na A1 amanhã.