# Primeira execução real na VM — checklist

## Status (atualizado 2026-08-17, à noite)

- [x] TCU — testado, SMTP ok, 50 publicações enviadas.
- [x] STJDJN — rodado, 10.000 publicações, e-mail passou (dentro do
      limite do MailGrid, mas raspando).
- [x] TJDFTDJN — rodado, 10.000 publicações, **e-mail falhou**:
      `552 Message size exceeds maximum permitted` (MailGrid recusou
      por tamanho). Sem perda de dados — a sessão não comitou, nada
      ficou gravado, ele vai tentar de novo do zero no próximo ciclo.

**Causa raiz:** o adapter `comunica_pje` busca sempre "hoje"
(`dataDisponibilizacaoInicio=dataDisponibilizacaoFim=hoje`), não é um
backlog histórico pra zerar uma vez — é o **volume diário normal**
desses dois tribunais (~10-13 mil comunicações/dia). Isso vai se
repetir todo dia enquanto o `mailer` não suportar dividir um e-mail
grande em vários envios menores. Além disso, o `scan` agendado roda
todos os portais habilitados num ciclo só, com **um e-mail combinado
no final** — se esse e-mail estourar o limite, a transação inteira do
ciclo é revertida e **nenhum** dos 8 portais grava ou envia nada
naquele dia.

**Decisão tomada:** desabilitar `STJDJN` e `TJDFTDJN` em
`portals.yaml` (já feito localmente) até o mailer suportar envio em
lotes. Os outros 6 portais (TCU, TCDF, TST, TSTDJN, TRT10DJN, TRFDJN)
seguem habilitados e não têm esse problema de volume.

---

## Passo 1 — Levar o portals.yaml atualizado pra VM

Depois que o `git push` sair daqui (peço sua confirmação separada pra
isso), na VM:

```bash
cd ~/Lupa-Diarios
git pull origin main
docker compose up --build -d
```

- [ ] Rodado — colar resultado aqui:

```
(cole aqui)
```

## Passo 2 — Confirmar que só os 6 portais de volume normal estão agendados

```bash
docker compose logs app --tail 50 | grep -i scheduler
```

- [ ] Rodado — colar resultado aqui:

```
(cole aqui)
```

## Passo 3 — Rodar um ciclo manual com os 6 portais pra confirmar que ficou saudável

```bash
docker compose exec app uv run python -m app.cli run
```

- [ ] Rodado — colar resultado aqui:

```
(cole aqui)
```

## Passo 4 — Conferir espaço em disco

```bash
df -h
du -sh data/files
```

- [ ] Rodado — colar resultado aqui:

```
(cole aqui)
```

---

## Pendência para depois (não bloqueia o deploy de hoje)

Implementar envio de e-mail em lotes (dividir por tamanho/quantidade de
itens quando o corpo ficar grande demais) em `app/mailer.py` +
`app/pipeline.py`, para poder reabilitar `STJDJN` e `TJDFTDJN` com
segurança. Fica para uma fase própria no `PLANO.md`.
