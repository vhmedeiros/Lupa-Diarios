# Primeira execução real na VM — checklist

## Status (atualizado 2026-08-17, à noite — rodada 2)

- [x] TCU — testado, SMTP ok, 50 publicações enviadas.
- [x] STJDJN — rodado isoladamente, 10.000 publicações, e-mail passou
      (dentro do limite do MailGrid, mas raspando).
- [x] TJDFTDJN — rodado isoladamente, 10.000 publicações, **e-mail
      falhou**: `552 Message size exceeds maximum permitted`.
- [x] `STJDJN`/`TJDFTDJN` desabilitados em `portals.yaml`.
- [x] `run` (sem `--portal`) rodado com os 6 restantes habilitados
      (TCU, TCDF, TST, TSTDJN, TRT10DJN, TRFDJN) — **quebrou de novo**,
      mesmo erro 552. TSTDJN (10 páginas) + TRT10DJN (7 páginas) +
      TRFDJN (10 páginas) sozinhos já somam ~25-27 mil itens.
- [x] `TSTDJN`, `TRT10DJN`, `TRFDJN` também desabilitados em
      `portals.yaml`. Restam habilitados: `TCU`, `TCDF`, `TST` (feed) —
      nenhum dos três teve problema de volume até agora.

**Causa raiz confirmada:** não é exclusivo de STJDJN/TJDFTDJN — é
qualquer combinação de portais DJEN (`comunica_pje`) cujo volume
combinado gere um HTML grande o bastante para estourar o limite de
tamanho do servidor SMTP (MailGrid). O adapter busca sempre "hoje", não
é backlog histórico — é volume diário normal, então o problema se
repete todo dia até o `mailer` suportar dividir um e-mail grande em
vários envios menores. Como o `scan` roda todos os portais habilitados
num ciclo só com um e-mail combinado no final, um estouro derruba a
transação inteira (nenhum portal daquele ciclo grava ou envia nada) —
sem perda de dados por causa disso (rollback automático, sessão nunca
comita antes do e-mail sair), mas sem monitoramento algum naquele
ciclo.

**Decisão tomada:** deixar habilitados só `TCU`, `TCDF` e `TST` (feed)
até implementar envio de e-mail em lotes no `mailer`. Todos os portais
DJEN (`STJDJN`, `TJDFTDJN`, `TSTDJN`, `TRT10DJN`, `TRFDJN`) ficam
desabilitados até lá.

---

## Passo 1 — Levar o portals.yaml atualizado pra VM

```bash
cd ~/Lupa-Diarios
git pull origin main
docker compose up --build -d
```

- [ ] Rodado — colar resultado aqui:

```
(cole aqui)
```

## Passo 2 — Confirmar que só TCU/TCDF/TST estão agendados

```bash
docker compose logs app --tail 50 | grep -i scheduler
```

- [ ] Rodado — colar resultado aqui:

```
(cole aqui)
```

## Passo 3 — Rodar um ciclo manual pra confirmar que ficou saudável

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

## Pendência para depois (bloqueia reabilitar os portais DJEN)

Implementar envio de e-mail em lotes (dividir por tamanho/quantidade de
itens quando o corpo ficar grande demais) em `app/mailer.py` +
`app/pipeline.py`, antes de reabilitar qualquer portal DJEN
(`STJDJN`, `TJDFTDJN`, `TSTDJN`, `TRT10DJN`, `TRFDJN`). Fica para uma
fase própria no `PLANO.md`.
