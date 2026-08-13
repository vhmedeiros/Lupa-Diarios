# Deploy — VM Oracle A1 (linux/arm64)

Guia passo a passo para colocar o Lupa Diários rodando 24/7 na VM Oracle
A1, conforme `CLAUDE.md` já define: Docker Compose (app + Postgres),
sem API exposta publicamente (acesso só via túnel SSH).

Este guia assume que **você** executa os comandos na VM (via SSH),
seguindo o passo a passo abaixo. Nada aqui é executado automaticamente.

---

## 0. Antes de começar

- [ ] `git push origin main` já feito **do seu terminal local** (não
      deste ambiente — ele não tem credenciais do GitHub configuradas).
      Confirme com `git log --oneline -1` no GitHub (pela web) ou
      `git status -sb` local (não deve mais dizer "ahead").
- [ ] Você tem o IP público (ou hostname) da VM e acesso SSH com sua
      chave já configurada (`ssh usuario@IP_DA_VM` funcionando).
- [ ] Você tem o `.env` preenchido com os valores de produção (pode ser
      uma cópia do `.env` local, como decidido) — **não cole segredos
      neste chat nem em nenhum lugar que vire log**. Transporte o
      arquivo direto por `scp` (passo 4).

---

## 1. Instalar Docker + Docker Compose na VM

Conecte via SSH:

```bash
ssh usuario@IP_DA_VM
```

Se a VM for **Ubuntu** (mais comum no free tier da Oracle A1):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Rodar docker sem sudo (opcional, recomendado)
sudo usermod -aG docker $USER
# depois disso, saia e reconecte via SSH para o grupo valer
```

Se a VM for **Oracle Linux** (imagem padrão do Oracle Cloud): use
`sudo dnf install -y docker-ce docker-ce-cli containerd.io
docker-compose-plugin` (mesmo repositório do Docker, adaptado para
`dnf`) — se tiver dúvida de qual SO a VM roda, `cat /etc/os-release`
confirma.

Confirme a instalação:

```bash
docker --version
docker compose version
```

**Nota sobre arquitetura**: a VM A1 é `linux/arm64` (ARM). A imagem
base do `Dockerfile` (`ghcr.io/astral-sh/uv:python3.13-bookworm-slim`)
é multi-arquitetura e deve puxar a variante arm64 automaticamente — mas
se o build falhar com erro de plataforma, é o primeiro lugar a
investigar (não deveria acontecer, é só uma nota de atenção).

---

## 2. Clonar o repositório

```bash
git clone https://github.com/vhmedeiros/Lupa-Diarios.git lupa-diarios
cd lupa-diarios
```

(Se já tinha clonado antes, é só `git pull` — ver seção 6, "Atualizar".)

---

## 3. Criar o diretório de dados

```bash
mkdir -p data/files
```

(`docker-compose.yml` monta `./data` no container; sem esse diretório
existir antes, o Docker cria como root e pode dar problema de permissão
depois — mais seguro criar você mesmo primeiro.)

---

## 4. Levar o `.env` para a VM

**Do seu computador local** (não da VM), copie o `.env` que já está
funcionando (mesmas credenciais de dev, como decidido):

```bash
scp .env usuario@IP_DA_VM:~/lupa-diarios/.env
```

Confirme na VM que o arquivo chegou e **não** foi commitado por engano
(`.env` está no `.gitignore`, então `git status` não deve mostrá-lo):

```bash
ls -la .env
git status --short   # não deve listar .env
```

---

## 5. Subir os containers

```bash
docker compose up --build -d
```

Isso builda a imagem da app (Python 3.13 + uv), sobe o Postgres 17 e a
app, com `restart: unless-stopped` nos dois — sobrevivem a reboot da VM
e a crashes eventuais, sem precisar de systemd/supervisor extra.

Confirme que subiu certo:

```bash
sleep 5
curl -s http://localhost:8000/health
```

Deve responder `{"status":"ok","db":true,"last_run_at":null}`.

Confirme que o scheduler registrou os jobs:

```bash
docker compose logs app --tail 50 | grep -i scheduler
```

Deve mostrar os próximos horários de `scan` (cron `SCAN_CRON`) e
`retention` (03h).

---

## 6. Acessar a API de fora (túnel SSH — nunca exposta publicamente)

Como decidido, as portas 8000 (API) e 5432 (Postgres) estão vinculadas
só a `127.0.0.1` **dentro da VM** — não são alcançáveis de fora, mesmo
que o firewall da Oracle Cloud esteja mal configurado. Para acessar a
API do seu computador local:

```bash
ssh -L 8000:localhost:8000 usuario@IP_DA_VM
```

Com esse túnel aberto (deixe o terminal rodando), acesse
`http://localhost:8000` no seu navegador/curl local normalmente —
o tráfego passa pelo túnel SSH.

**Confirme no console da Oracle Cloud** que a Security List / NSG da VM
não tem nenhuma regra liberando as portas 8000 ou 5432 publicamente —
só a porta 22 (SSH) deveria estar aberta para a internet.

---

## 7. Operação do dia a dia

Rodando via `docker compose`, o pipeline dispara sozinho pelo
scheduler (`SCAN_CRON`, padrão de hora em hora 8h-20h seg-sex) — não
precisa de comando manual para funcionar 24/7.

Comandos úteis, rodados de dentro da pasta `lupa-diarios` na VM:

```bash
# ver logs em tempo real
docker compose logs -f app

# rodar um ciclo manual (ex.: testar um portal específico)
docker compose exec app uv run python -m app.cli run --portal TCU

# reenviar manualmente publicações já vistas (ver README.md, seção 5.1)
docker compose exec app uv run python -m app.cli run --portal TCU --force

# enviar e-mail de teste
docker compose exec app uv run python -m app.cli send-test

# parar tudo
docker compose down

# ver status dos containers
docker compose ps
```

## 8. Atualizar para uma versão nova (deploy de mudanças futuras)

```bash
cd ~/lupa-diarios
git pull origin main
docker compose up --build -d
```

O `--build` reconstrói a imagem só se algo mudou (cache do Docker cuida
disso); os containers reiniciam com o código novo, o Postgres
(`db_data`, volume nomeado) e os arquivos baixados (`data/`) não são
afetados.

---

## 9. Pendências conhecidas para depois do deploy

- **STJDJN e TJDFTDJN** (via DJEN/comunica_pje) têm volume alto
  (~10.000 publicações "novas" na primeira coleta real) — ainda não
  foram disparados de verdade em nenhum ambiente. O primeiro ciclo do
  scheduler na VM vai tentar processar os 5 portais habilitados,
  incluindo esses dois — o e-mail resultante pode ser grande. Considere
  rodar `--portal STJDJN`/`--portal TJDFTDJN` manualmente uma vez fora
  do horário de pico antes de deixar o scheduler cuidar disso sozinho,
  ou desabilitar esses dois temporariamente em `portals.yaml` até
  decidir a estratégia (ver conversa anterior sobre o volume do DJEN).
