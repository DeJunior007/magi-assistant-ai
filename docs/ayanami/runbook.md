# Runbook da Ayanami (node 2)

Operação da Ayanami no node 2 (design §10–§11, spec §7 e §9). Quem roda é só o Pedro: ele é o
único com SSH no node 2. Os scripts ficam em `deploy/ayanami/host/`. Cada um é idempotente e deve
ser **lido antes de rodar**. Nenhum agente roda estes passos.

> **Node 1 nunca.** MultiVideos, wedding e gold-crm estão em produção no node 1. Nenhum passo
> deste runbook roda lá, nem por engano. Antes de qualquer comando, confira o `hostname` e o IP
> com o painel da Contabo.

O que se sabe do node 2 (sem confirmação do Pedro): VPS Contabo com 8 vCPU, ~23 GB de RAM e sem
GPU. Pode ter restos do MultiVideos: `/opt/multivideos` antigo, um `docker-compose.node2.yml`
parado, volumes de modelos do Ollama e do Whisper, a interface `wg0` e regras antigas no `ufw`.

Layout: `/opt/ayanami` é um clone do repo, e só `deploy/ayanami/` é usado. Ficam fora do git, em
`/opt/ayanami`, o `.env` (`0600`, só segredos, spec §9.1), o `ayanami.toml` (§9.2) e o `dados/`.
O `compose.yml` fica em `deploy/ayanami/` (porque usa `build: ../..`). O `preparar.sh` cria os
links `deploy/ayanami/{.env,ayanami.toml,dados}` → `/opt/ayanami/…`. Todos os comandos
`docker compose` abaixo rodam em `/opt/ayanami/deploy/ayanami`.

---

## 1. Provisionar (Y1.5)

Siga na ordem. Anote aqui o que for diferente do esperado (a Y1.5 corrige este runbook).

1. **Painel da Contabo** (requirements "O que precisa do Pedro" item 1): confirme que o node 2
   existe e que não está agendado para cancelar. Anote o hostname e o IP público, mas **fora do
   repo**.
2. **SSH:** entre no node 2 com a sua chave e confira:
   `hostname; hostname -I; docker ps --format '{{.Names}}'`.
   Se aparecer qualquer coisa do MultiVideos, wedding ou gold-crm **rodando**, pare: pode ser o
   node 1.
3. **Leve os scripts** (sem clonar ainda): `scp -r deploy/ayanami/host <node2>:/tmp/ayanami-host`.
   Também dá para colar arquivo por arquivo.
4. **Restos do MultiVideos** (item 2). Primeiro rode sem `--sim`, que só lista:
   ```
   bash /tmp/ayanami-host/limpar-multivideos.sh --host-esperado <hostname> --ip-esperado <ip>
   ```
   Revise a lista. Depois rode com `--sim`, que pede `s/N` item a item:
   ```
   sudo bash /tmp/ayanami-host/limpar-multivideos.sh --host-esperado <hostname> --ip-esperado <ip> --sim
   ```
   O script aborta se o hostname ou o IP não baterem, ou se houver contêiner com cara de produção
   rodando. A config do `wg0` vai para `/var/backups/limpar-multivideos-*`. Anote o que ficou
   ("fica") e o porquê.
5. **Conta do Tailscale** (item 3): crie a conta e instale o Tailscale no PC e no celular. No
   painel, ligue **MagicDNS** e **HTTPS**. Configure a política (design §10.1):
   ```
   tagOwners: tag:ayanami → autogroup:admin ; tag:casa → autogroup:admin
   grants:    pedro (PC, celular) → tag:ayanami : 443, 22
              tag:casa            → tag:ayanami : 443
              (tag:ayanami não alcança nada)
   ```
   Não use subnet router, exit node nem Funnel.
6. **Preparar o host:**
   ```
   sudo bash /tmp/ayanami-host/preparar.sh --repo <url-do-repo> [--ref main]
   ```
   O script instala os pacotes, o Docker e o compose v2 (precisa ter `pull --ignore-buildable`).
   Cria o usuário `ayanami` (no grupo `docker`), o `/opt/ayanami` e o `dados/`. Grava
   `DOCKER_GID` no `.env` e liga SSH só por chave, mas **só se** já houver chave em
   `authorized_keys`.
   Se o repo for privado, use uma *deploy key* só de leitura do usuário `ayanami`. Ela nunca vai
   para o repo.
7. **Firewall:** `sudo bash /opt/ayanami/deploy/ayanami/host/ufw.sh`. O script libera o
   `22/tcp` antes de ligar o ufw. Se ele avisar de regras extras, volte ao passo 4. Se avisar de
   portas em `0.0.0.0`, descubra de quem é o contêiner.
8. **Tailscale no node 2:** `sudo bash /opt/ayanami/deploy/ayanami/host/tailscale.sh`.
   - O login é interativo. Também dá para usar `TS_AUTHKEY=… sudo -E …`, com chave de uso único e
     sem gravar em arquivo.
   - O script faz o `tailscale up` com hostname `ayanami`, `tag:ayanami` e `--ssh`, e depois o
     `tailscale serve --bg --https=443 http://127.0.0.1:8740`.
   - No painel, aprove a máquina e confira a tag.
9. **Conferência por fora** (de uma rede fora do tailnet):
   `nmap -Pn -p- <ip-publico>` só pode mostrar `22/tcp`.
   `sudo nmap -sU -p 41641 <ip-publico>` dá `open|filtered`.
   Do PC: `tailscale status` mostra `ayanami`.
   No node 2: `sudo ufw status` mostra só `22/tcp` e `41641/udp` (v4 e v6).

## 2. Primeiro deploy (Y1.6)

1. **Segredos:** `sudo -u ayanami cp /opt/ayanami/deploy/ayanami/env.example /opt/ayanami/.env.novo`.
   Junte os valores reais da spec §9.1 com o `DOCKER_GID` que já está no `.env`. Depois
   `mv .env.novo .env` e `chmod 0600 /opt/ayanami/.env`. Nada de segredo em outro arquivo, no
   histórico do shell ou no repo.
   Dica: digite os valores com `read -rs` ou num editor, nunca como argumento de comando.
2. **Config:** copie `deploy/ayanami/ayanami.example.toml` para `/opt/ayanami/ayanami.toml` e
   ajuste. A `[ayanami]` dá a URL base `https://ayanami.<tailnet>.ts.net`.
3. **Deploy:** `sudo -u ayanami /opt/ayanami/deploy/ayanami/host/deploy.sh`.
   Na A1, a imagem é construída no próprio node 2 porque não há `AYANAMI_IMAGEM`.
   Saída esperada: o JSON da `/saude`. `ok=false` com `faltando` lista só nomes de segredos.
   `docker compose ps`: os 7 serviços `healthy`, menos o `migrar` (perfil `ops`, roda e sai).
4. **Token do PC:**
   ```
   docker compose exec ayanami-api ayanami dispositivo criar pc --tipo pc
   ```
   O token aparece **uma vez**. Guarde no keyring do PC (`magi` / `ayanami_pc`) ou em
   `~/.config/magi/ayanami.token` (`0600`), e ponha `[ayanami] url` no `config.toml` do PC
   (`magi/elo/credenciais.py`).
5. **Vigia (Y1.3):**
   ```
   sudo cp /opt/ayanami/deploy/ayanami/vigia/ayanami-vigia.{service,timer} /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now ayanami-vigia.timer
   ```
   Teste o Telegram (item 6): pare a API (`docker compose stop ayanami-api`). Depois de ~3 min
   deve chegar o alerta de `/saude`. Volte com `docker compose up -d`.
6. **Pelo tailnet:** `curl -fsS https://ayanami.<tailnet>.ts.net/saude` do PC e do celular (com
   o Tailscale ligado).
7. **MCP (depois da Y5.1):**
   - Crie o token: `docker compose exec ayanami-api ayanami dispositivo criar claude-code --tipo mcp`.
   - No PC:
     ```
     claude mcp add --transport http ayanami https://ayanami.<tailnet>.ts.net/mcp/ --header "Authorization: Bearer $AYANAMI_MCP" -s user
     ```
     Use **`/mcp/` com barra**. Sem a barra vem um 307 com `Location: http://` atrás do
     `tailscale serve`, e o cliente recusa. A outra saída é o uvicorn com `--proxy-headers
     --forwarded-allow-ips=127.0.0.1`.
   - Claude Desktop: `npx mcp-remote https://ayanami.<tailnet>.ts.net/mcp/ --header "Authorization: Bearer …"`.
   - Confira com `claude mcp list`.
8. **CI (opcional, item 7):** cadastre os secrets `AYANAMI_HOST`, `AYANAMI_USER` (`ayanami`) e
   `AYANAMI_SSH_KEY` no GitHub. Sem eles, o job de deploy é pulado.

## 3. Deploy de rotina

```
sudo -u ayanami /opt/ayanami/deploy/ayanami/host/deploy.sh
```

A sequência é `git pull --ff-only` → `docker compose pull --ignore-buildable` (mais `build` se a
imagem for local) → `docker compose --profile ops run --rm migrar` → `docker compose up -d` →
`curl /saude`, com até 30 tentativas a cada 2 s.
O script nunca derruba a pilha nem apaga volume. Se a `/saude` não responder, ele sai com 1:
veja a §6.

## 4. Rollback por tag de imagem

As migrações só andam para a frente e são aditivas, então uma imagem anterior roda no esquema
novo. Se a versão nova trouxe migração incompatível, **não volte a imagem**: corrija para a frente.

- **Com `ghcr.io`** (`AYANAMI_IMAGEM` no `.env`):
  `deploy.sh --sem-git --tag <sha-bom>`. O script grava `AYANAMI_TAG=<sha-bom>` no `.env`, e por
  isso o próximo deploy continua nela. Para voltar ao normal, rode `deploy.sh --tag <sha-novo>`.
- **Na A1** (imagem local):
  `git -C /opt/ayanami checkout <commit-bom>`, depois `deploy.sh --sem-git` (reconstrói).
  Para voltar ao normal: `git -C /opt/ayanami checkout main` e `deploy.sh`.
- Imagens disponíveis: `docker image ls ayanami*` ou a lista do pacote no ghcr.

## 5. Ver filas

- **API:** `GET /v1/fila` (token com escopo `tarefas`) ou a aba "Fila" do PWA. Há também
  `ayanami fila` no CLI, quando existir (design §4.1).
- **Direto no banco** (só leitura):
  ```
  docker compose exec ayanami-pg psql -U ayanami -d ayanami -c \
    "select queue_name, status, count(*) from procrastinate_jobs group by 1,2 order by 1,2"
  ```
- **Batimento dos workers:**
  ```
  docker compose exec ayanami-pg psql -U ayanami -d ayanami -c "select * from workers_batimento"
  ```

## 6. Girar token

Tokens são de dispositivo (`ayn_<tipo>_…`). O banco guarda só o sha256.

1. Crie o novo: `docker compose exec ayanami-api ayanami dispositivo criar <nome-novo> --tipo <tipo>`.
2. Troque no cliente:
   - **PC:** keyring ou `ayanami.token`.
   - **Casa:** `~/.config/magi/ayanami-casa.token` (`0600`).
   - **Celular:** pareie de novo.
   - **MCP:** `claude mcp remove ayanami` e `add` de novo.
3. Revogue o antigo: `docker compose exec ayanami-api ayanami dispositivo revogar <nome-antigo>`.
   Vale em ≤ 5 s e fecha o WS/SSE.
4. Confira com `ayanami dispositivo listar`, que mostra só o prefixo.

**Segredos do `.env`:** edite o `/opt/ayanami/.env` (`0600`) e rode `docker compose up -d`, que
recria os serviços afetados.
`POSTGRES_PASSWORD` **não** se troca só no `.env`. Antes, faça
`ALTER ROLE ayanami PASSWORD …` dentro do `ayanami-pg` e só depois atualize o `.env`.

## 7. Restore manual

O restore de teste mensal é automático (spec §7.2). Os passos abaixo são para quando precisar de
um dump de verdade. Nada aqui usa `--clean` nem apaga base.

1. **Listar snapshots:**
   ```
   docker compose --profile ops run --rm -e RESTIC_REPOSITORY=b2:<B2_BUCKET>:magi \
     -e RESTIC_CACHE_DIR=/dados/restic-cache migrar restic snapshots
   ```
   Confira na Y1.6 se o `run` do `migrar` aceita outro comando. Senão, use
   `docker compose exec worker-agendado restic snapshots`, que já tem o ambiente do restic.
2. **Restaurar para um diretório:**
   `… restic restore <snapshot> --target /dados/tmp/restore-manual`.
   O resultado fica em `/opt/ayanami/dados/tmp/restore-manual` no host.
3. **Inspecionar** num contêiner descartável, como o restore de teste: `pgvector/pgvector:pg16`,
   `--network none`, `pg_restore --no-owner -d postgres --create`. Compare as contagens com o
   `manifesto.json`.
4. **Usar:**
   - **PC** (`magi-pg`): leve o `magi-pg.dump` para o PC e decida à mão. O restore numa base nova
     é decisão do Pedro, fora destes scripts.
   - **Ayanami em VPS nova:**
     1. Rode `preparar.sh`, a config e `deploy.sh`. O volume `ayanami-pgdata` começa vazio e o
        `migrar` cria o esquema.
     2. Pare o que escreve: `docker compose stop ayanami-api worker-rapido worker-agendado worker-lento`.
     3. Restaure com `pg_restore --no-owner --data-only -d ayanami` no `ayanami-pg`.
     4. Suba de novo com `docker compose up -d`.
5. Apague o diretório `/opt/ayanami/dados/tmp/restore-manual` no fim. Ele tem dados pessoais.

## 8. Alertas do vigia (Telegram)

O vigia manda 1 mensagem por causa a cada 6 h (spec §7.3).

| Alerta | O que fazer |
| --- | --- |
| `/saude` falhou 3× seguidas | `docker compose ps` e `docker compose logs --tail 100 ayanami-api ayanami-pg`. Contêiner parado: `docker compose up -d`. `ok=false` com `faltando`: complete o `.env`. Banco fora: veja o disco (linha abaixo). Se veio depois de um deploy: rollback (§4). |
| Disco > 85% | `df -h`; `du -sh /opt/ayanami/dados/*`; `docker system df`. Limpe `dados/tmp/` antigo e imagens velhas (`docker image prune`, nunca volume). Se for o `ayanami-pgdata`, veja a retenção e o tamanho das tabelas. |
| Worker sem batimento > 5 min | `docker compose ps`; `docker compose logs --tail 200 worker-<fila>`; `docker compose restart worker-<fila>`. Job travado é reanimado pelo próprio worker (`retry` dos parados). Se repetir, veja a fila (§5). |
| Snapshot `pc` > 36 h | O backup do PC não chegou. No PC: `backup_state.json` e `journalctl --user -u magi-backup`. Confira o token do PC e o tailnet. |
| Snapshot `ayanami` > 36 h | `docker compose logs worker-agendado`; olhe os jobs `backup.*` na fila. Confira `B2_*` e `RESTIC_PASSWORD` no `.env`. |
| Backup `falhou` | Mesmo caminho da linha anterior. Erro de credencial do B2: gire a chave (bucket restrito) e rode `docker compose up -d`. |
| Restore de teste vermelho | Contagens divergentes ou restore quebrado: o backup pode não servir. Rode o restore manual (§7, passos 1–3) e compare com o manifesto. Se a senha do restic falhar, pegue a cópia no cofre/keyring do PC. Trate como urgente. |

## 9. Proibições (valem para tudo acima)

- Nada no node 1.
- Nada de `docker compose down`, de remover volume da Ayanami nem de `DROP`/`TRUNCATE`.
- Nada de `pg_restore --clean` fora do contêiner descartável.
- Nada de Funnel.
- Nenhuma porta publicada fora de `127.0.0.1`.
- Segredos só no `/opt/ayanami/.env` (`0600`) e no cofre do Pedro.
