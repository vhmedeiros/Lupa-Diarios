# PASSO A PASSO — Do zero ao MVP rodando (roteiro do dia)

Materiais que você já tem e onde cada um entra: **guia v1** (portals.yaml
e conceitos), **guia v2** (Cursor, Parte 2; prompt antigo, ignorar),
**guia v3** (agentes na Parte 3 e prompt de planejamento na Parte 4),
**CLAUDE.md** e **SPEC.md** (entregues junto com este arquivo — versões
finais, substituem qualquer trecho anterior).

---

## Bloco 1 — Ambiente (~45 min, faça uma única vez)

1. No Windows: instale o Cursor (cursor.com) e o Docker Desktop
   (Settings → Resources → WSL Integration → habilite seu Ubuntu).
2. Abra o Cursor → `Ctrl+Shift+J` → General → **Import from VS Code**
   (traz extensões, tema, settings, keybindings).
3. Instale a extensão **WSL** no Cursor → `Ctrl+Shift+P` →
   "WSL: Connect to WSL". Confirme "WSL: Ubuntu" na barra inferior.
4. No terminal integrado (`` Ctrl+` ``, já é o WSL), rode:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh          # uv
curl -fsSL https://claude.ai/install.sh | bash            # Claude Code
exec $SHELL                                               # recarrega PATH
uv --version && claude --version && docker compose version
git config --global user.name "Seu Nome"
git config --global user.email "voce@exemplo.com"
```

5. Rode `claude` uma vez em qualquer pasta → login no navegador com sua
   conta **Claude Pro** → saia com `Ctrl+C` duas vezes.
6. MCP de documentação (requer Node: `sudo apt install -y nodejs npm`):

```bash
claude mcp add context7 -- npx -y @upstash/context7-mcp
claude mcp list
```

Se travar aqui: aulas 02 e 03 do curso (Instalação / Introdução).

## Bloco 2 — Esqueleto do repositório (~20 min)

```bash
mkdir -p ~/projetos/lupa-diarios && cd ~/projetos/lupa-diarios
git init
mkdir -p .claude/agents
cursor .    # abre a pasta no Cursor conectado ao WSL
```

Crie estes 5 arquivos colando o conteúdo dos materiais:

| Arquivo | Fonte |
|---|---|
| `CLAUDE.md` | o CLAUDE.md final entregue agora |
| `SPEC.md` | o SPEC.md final entregue agora |
| `portals.yaml` | guia v1, seção 2.4 |
| `.claude/agents/planejador.md` | guia v3, seção 3.2 |
| `.claude/agents/executor.md` | guia v3, seção 3.3 |

Commit inicial:

```bash
git add -A && git commit -m "docs: contexto do projeto (CLAUDE, SPEC, portais, agents)"
```

(Opcional, 8 min: aula 08 do curso — Subagents — antes de prosseguir.)

## Bloco 3 — Planejamento (~45 min, a etapa mais importante)

1. No terminal do Cursor, dentro da pasta: `claude`.
2. Cole o **prompt de planejamento da Parte 4 do guia v3** na íntegra.
   O subagent planejador vai ler CLAUDE.md/SPEC.md/portals.yaml e
   produzir o `PLANO.md`.
3. **Leia o PLANO.md inteiro** (10-15 min). Verifique quatro coisas:
   o recorte de hoje tem 4-5 portais e o TST (feed Atom) está entre
   eles; existe fase específica da regra dos 15 MB; existe fase do job
   de retenção preservando seen_hashes; toda fase tem comando de
   aceite que VOCÊ consegue rodar.
4. Responda as perguntas que o planejador fizer. Peça ajustes se o
   plano parecer grande demais ("reduza o recorte de hoje para X").
5. Aprove explicitamente: "Plano aprovado. Não mude o escopo sem me
   consultar."

## Bloco 4 — Execução fase a fase (o resto do dia)

O ciclo, repetido até acabar as fases:

```
1. No claude:  use o subagent executor para implementar a Fase N do PLANO.md
2. Acompanhe; aprove as permissões que ele pedir (pytest, uv, etc.)
3. Rode VOCÊ MESMO o critério de aceite da fase (comando do PLANO.md)
4. Revise o diff no Source Control do Cursor (Ctrl+Shift+G)
5. Confirme o commit da fase
6. /clear   (limpa contexto; CLAUDE.md + PLANO.md mantêm a memória)
```

Regras de condução: uma fase por vez, nunca "faça as fases 3 a 6".
Se algo falhar, descreva o sintoma concreto (erro + comando) em vez de
"não funcionou". Se um portal se revelar diferente do previsto:
`use o planejador para revisar a estratégia do portal X no PLANO.md`,
aprove a revisão, devolva ao executor. Se bater limite do plano Pro,
pause até a janela renovar — o PLANO.md garante que nada se perde.

Dois checkpoints com hora marcada:

- **Assim que a fase do mailer terminar** (não deixe para o fim do
  dia): preencha o `.env` com seus dados do MailGrid e rode
  `uv run python -m app.cli send-test`. E-mail na caixa de entrada?
  Siga. Caiu em spam ou falhou? Confira host/porta no painel do
  MailGrid e configure SPF/DKIM do domínio antes de continuar.
- **Após cada adapter**: `uv run python -m app.cli run --portal CODE
  --dry-run` e confira se as publicações impressas batem com o portal
  aberto no navegador.

## Bloco 5 — Fechamento do dia (~30 min)

Percorra os 6 critérios de aceite da seção 11 do SPEC.md, na ordem.
O item 6 é:

```bash
docker compose up --build
# em outro terminal:
curl http://localhost:8000/health
```

Tudo verde → `git add -A && git commit -m "chore: MVP funcional"` e,
se tiver remoto, `git push`. **Este é o "pronto" de hoje.** Portais
fora do recorte ficam enabled=false — cada um vira uma sessão curta de
outro dia ("planejador revisa estratégia do portal X → executor
implementa"), usando o mesmo ciclo do Bloco 4.

## Bloco 6 — Amanhã: deploy na Oracle A1 (~40 min, referência)

```bash
# na VM (Ubuntu ARM64), via SSH:
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && exit   # reconecte o SSH
sudo systemctl enable docker
git clone <seu-repo> && cd lupa-diarios
nano .env                                # produção: MailGrid + DB_PASSWORD forte
docker compose up -d --build
docker compose logs -f --tail 100        # acompanhe o primeiro ciclo
```

Não exponha a porta 8000 publicamente (não libere no Security List da
Oracle); opere via SSH. O `restart: unless-stopped` + Docker no boot
garantem o "sempre online". Validação final: no horário do próximo
ciclo (cron 8h-20h seg-sex), o e-mail chega sozinho — e no dia
seguinte, `docker compose logs` mostra o job de retenção rodando.

---

## Se algo sair muito do trilho

Plano confuso ou você se perdeu no meio: `/clear` e recomece o Bloco 3
— o custo de replanejar é 30 min; o custo de seguir um plano ruim é o
dia. Executor insistindo num erro: interrompa com Esc, dê o erro exato,
e se persistir peça "abandone essa abordagem, proponha outra". Dia
acabando com fases sobrando: corte portais do recorte, jamais corte
dedupe, retenção ou testes — portal a menos é feature adiada; dedupe
quebrado é e-mail duplicado para sempre.