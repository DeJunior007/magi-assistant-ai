# Tarefas — Ayanami plataforma (o node 2 inteiro como MCP/cérebro)

Implementa [requirements.md](requirements.md), [design.md](design.md) e [spec.md](spec.md). Cada tarefa é
feita por **um agente** com janela de **até 128k tokens** (teto duro), salvo as marcadas **precisa do
Pedro**. O orquestrador (Pedro ou a sessão principal) só lança uma tarefa quando todas as de *Depende de*
estão no `main`. Fases por frente: **P0** base, **P1** dev/MCP, **P2** ops, **P3** Condessa noturna,
**P4** serviços pessoais, **F** = precisa do Pedro (decisões, node 1, node 2, contas).

**Pré-requisito:** a onda 1 do [condessa-celular](../condessa-celular/tasks.md) no `main` — M1.1
(`auth.py`/`app.py`), M1.2 (`magi/elo/mensagens.py`), M1.5 (`push.py`, `config.py [push]`, migração
`003_push_tipo.sql`) e M1.6 (serviço `ntfy` no `compose.yml`). Este SDD **não** redefine o ntfy nem o push:
só depende deles. Migrações daqui: **004–012** (spec §3).

**Ondas** (cada onda roda junta; a seguinte começa quando a anterior está no `main`; seguem a ordem de
entrega do design §7):
**1** P0.1, P0.2, P0.3, P0.4, P0.5, F.1 *Pedro* · **2** P2.1, P2.2, P2.3 · **3** P2.4, P1.1, P1.2,
F.2 *Pedro* · **4** P4.1, P4.2, P2.5, F.3 *Pedro* · **5** P3.1, P2.6, F.7 *Pedro* · **6** P2.7, P1.3,
P3.6, F.4 *Pedro* · **7** P1.4, P1.5, P4.3, P4.4, F.5 *Pedro* · **8** P3.2, P3.3, P3.7, F.6 *Pedro* ·
**9** P3.4, P3.5 · **10** P4.5, P1.6, P1.7, P0.6 · **11** F.8 *Pedro*, F.9 *Pedro* · **12** F.10 *Pedro*.

**Decisões:** valem os padrões D1–D14 do requirements e as DSP1–DSP11 da spec. Tudo o que depende de
credencial nasce **desligado** no `ayanami.toml` e pula com aviso (padrão do a2057df); o Pedro liga no F.

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*): spec por `spec §`, design por `design §`, requisitos por
   `R`/`RNF-P`/`D`. Leia a spec por trecho (`grep -n "^## \|^### " specs/ayanami-plataforma/spec.md`).
   Siga também `specs/DECISOES-2026-10-10.md` e as regras da rodada em `.git/regras-rodada.txt`.
2. **Orçamento planejado ≤ 50–60k tokens**; teto duro 128k. Perto de **90k**: pare, faça commit do que
   está verde e anote o resto em *Sobras*.
3. **Contratos primeiro:** a P0.2 cria os módulos `ayanami/mcp_tools/*.py` e os routers como stubs
   ("dono: <ID>") e todas as linhas de `ESCOPO_DE_ROTA`; a P0.5 cria todas as seções de config, os
   `EventoTipo` novos e `ayanami/plataforma.py`. As tarefas seguintes preenchem sem mudar assinatura
   (mudou? atualize a spec no mesmo commit e anote em *Sobras*).
4. **Só os arquivos do campo *Escreve*.** Arquivos compartilhados (`ayanami/fila.py`,
   `deploy/ayanami/compose.yml`, `deploy/ayanami/host/tailscale.sh`, `deploy/ayanami/env.example`,
   `docs/ayanami/runbook.md`, `tests/ayanami/test_fila.py`): só as **suas** linhas/seção (runbook: seção
   nova no fim) e `git add -p` só dos seus hunks. Precisou de outro arquivo? Pare e anote em *Sobras*.
5. **Arquivos grandes por trecho** (`grep -n` + `sed -n`): `ayanami/mcp_server.py`, `ayanami/push.py`,
   `ayanami/turnos.py`, `ayanami/config.py`, `ayanami/workers/agente.py`, `ayanami/workers/noticias.py`,
   `deploy/ayanami/vigia/vigia.py`, `magi/common/contracts.py`, `specs/ayanami-central/spec.md`.
6. **Testes curtos:** `uv run pytest -q -x tests/ayanami tests/deploy` (ou só os arquivos da tarefa;
   confira o código de saída, sem `| tail`) e `uv run ruff check <seus arquivos>`; PWA com `node --test
   'tests/ayanami/pwa/*.mjs'`. Relógio, `rng`, HTTP (`httpx.MockTransport`), `subprocess`/`ssh`/`git`/
   `docker`/`restic`/`imaplib` **sempre injetados**; nada de `sleep` real acima de 50 ms.
7. **Nada ao vivo nos testes:** sem rede real, GitHub, node 1, node 2, IMAP, SearXNG, Miniflux, Gatus,
   Beszel, `llama-server`, Kokoro real nem LLM pago. Postgres só o **`ayanami-pg-teste`**
   (`deploy/ayanami/pg-teste.sh estado/subir`, marca `pg`), **nunca** o `magi-pg` (54329) nem o
   `ayanami-pg` de produção. O tree-sitter roda de verdade (é local), nos arquivos de fixture.
8. **Proibições** (código, script, teste e comando do agente):
   - **repo público**: nenhum segredo, token `ayn_…`/`ghp_…` real, chave SSH, senha, IP, nome do
     tailnet, domínio ou URL de cliente, e-mail real nem dump em commit, log, teste ou *Sobras*; exemplos
     com `exemplo.invalid`, `ayanami.exemplo.ts.net` e chaves falsas fixas;
   - **nada no node 1** (MultiVideos, wedding, gold-crm): o agente escreve o script e o runbook; quem
     instala é o Pedro no F.4. Nenhum verbo de escrita no node 1, nem em código;
   - **nada de `ssh`, `scp`, `docker compose up/down`, `systemctl`, deploy real** no node 2 por agente: a
     infra é código, aplica o Pedro nas tarefas F; nada no Minecraft parado (`/opt/minecraft`);
   - **nenhum container com `docker.sock`** nem `privileged`; nenhuma porta fora de `127.0.0.1`;
   - **sem `uv sync`/`uv lock`** (dependência nova, como `sqlglot`, `tree-sitter-language-pack`,
     `trafilatura`, `ebooklib`: anote em *Sobras*; se faltar pacote já declarado, `uv sync --extra
     ayanami --extra ayanami-ml` e avise); o `magi-core` está em produção: não reinicie nada;
   - **arquivos do HUD/tray do Pedro intocados** (`hud/alternar.py`, `hud/gamerhud-watch.py`,
     `hud/install.sh`, `hud/steam-mangohud.sh`, `hud/magi_tray.py`, `hud/system/autostart/*`,
     `tests/hud/*`); `ayanami/workers/backup.py` só pela P2.6 e só a função nova;
   - **arquivos do condessa-celular**: `ayanami/api/app_android.py`, `ayanami/api/retrato.py`,
     `ayanami/retrato.py`, `deploy/ayanami/ntfy/`, `android/` — só leitura;
   - nada de `qdbus`/`gdbus`/`dbus-send` para KGlobalAccel/KWin; nada de `docker compose down`,
     `docker rm`, `DROP`/`TRUNCATE` fora do banco de teste; nada de `git stash`, worktree, `--amend`,
     `rebase`, `push`.
9. **Uma tarefa = um commit** no `main`, mensagem com o ID (`P2.3: alertas e incidentes`) e a linha
   final `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, sempre `git commit -m … --
   <seus caminhos>` (nunca `git commit` puro; nos compartilhados e no `tasks.md` só os seus hunks com
   `git add -p`). Sem push (o orquestrador faz).
10. **Não quebre o que existe:** `tests/ayanami`, `tests/deploy` e os `.mjs` do PWA seguem verdes; a
    lista de tools antiga do MCP (`noticias_*`, `tarefa_*`, `estado`, `servidor`, `tv_acao`,
    `memoria_gravar`) não muda de nome nem de escopo.

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~8k,
`design.md` ~5k, `spec.md` ~14k (por §: §1 ~1,5k, §2 ~1,5k, §3 ~1,2k, §4 ~2k, §5–§7 ~2k, §8 ~2k,
§9 ~2k, §10 ~2k, §11–§13 ~2,5k, §14 ~0,7k).

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
[celular M1.1 M1.2 M1.5 M1.6] ─┬─ P0.1 compose inteiro ─┬─ P2.1 gatus ─┐   ┌─ F.2 deploy inteiro (Pedro)
                               │                        ├─ P2.2 beszel ┤   │
                               ├─ P0.2 escopos/MCP ─────┤              ├─ P2.4 ops_status ─┐
                               ├─ P0.3 redator ─────────┤ P2.3 alerta/incidentes ─┘         │
                               ├─ P0.4 vigia ───────────┘     │                              │
                               └─ P0.5 config/eventos/cessão ─┼─ P1.1 ci_* ── F.3 PAT+hook (Pedro)
                                                              ├─ P1.2 sessões+hook ─┘
                                                              ├─ P4.1 searxng ─┬─ P3.3 pesquisa profunda
                                                              ├─ P4.2 miniflux ┤
                                                              │                └─ P3.1 bom dia (molde) ── P3.6 PC toca
                                                              ├─ P2.5 porta única ── P2.6 backup+sandbox ─┬─ P2.7 ops_backup/filas/ping
                                                              │                                          ├─ P1.5 sql_ler ── F.4 node 1 (Pedro)
                                                              ├─ P1.3 espelho+índice ── P1.4 codigo_*     │
                                                              └─ P4.3 llm-local+Cadeia+lote ─┬─ P3.2 diário+aula ◀─ P3.7 learning_sync (PC)
                                                                 P4.4 bench/A-B ─── F.6 S1/S3/A-B (Pedro)
                                                                                             ├─ P3.4 audiolivro ── P3.5 player PWA
                                                                                             └─ P4.5 e-mail ── F.8 (Pedro)
                       P1.6 bugsink · P1.7 runner · P0.6 gateway ── F.9 D8/D9/D14 (Pedro)
                                                     tudo ── F.10 validação e medições (Pedro)
```

## Fase P0 — Base (perfil, MCP único, redator, vigia, config)

- [x] **P0.1 Perfil "node 2 inteiro"** — `deploy/ayanami/compose.node2-inteiro.yml` com os limites dos
  serviços existentes da spec §1 (pg com `shared_buffers=768MB`, `worker-lento`/`migrar` em `2-7`,
  `ntfy` só `cpu_shares`); mesclador de compose em Python para testes (`tests/deploy/compose_mesclado.py`,
  dict merge à moda do Compose: `services.*` campo a campo, listas substituídas); cabeçalho explicando
  `COMPOSE_FILE`. O `compose.node2.yml` fica intocado.
  - Lê: spec §1, DSP1–DSP2; design §4.1; `deploy/ayanami/compose.yml` (serviços e âncoras), `deploy/ayanami/compose.node2.yml`, `tests/deploy/test_ayanami_compose.py` (`grep -n "def "`)
  - Escreve: `deploy/ayanami/compose.node2-inteiro.yml`, `tests/deploy/compose_mesclado.py`, `tests/deploy/test_compose_inteiro.py`
  - Depende de: celular M1.6
  - Orçamento: ~30k
  - Pronto: CA-P1 (com os serviços que existirem; cada serviço novo estende o teste), CA-P2, CA-Y29 verde.
  - Paralelo: P0.2, P0.3, P0.4, P0.5

- [ ] **P0.2 Escopos, `tools/list` por token e registro de módulos** — `auth.py`: escopos novos em
  `ESCOPOS_PADRAO` (spec §4) e **todas** as linhas de `ESCOPO_DE_ROTA` da spec §6; `app.py`: routers
  novos em `ROTEADORES` (`sessoes_dev`, `ops`, `bom_dia`, `learning`, `audiolivro`) como stubs com
  `router` vazio "dono: <ID>"; `ayanami/mcp_tools/__init__.py` (`MODULOS`) + 9 stubs (`ci`, `sessoes`,
  `codigo`, `ops`, `web`, `rss`, `pessoal`, `prod`, `email`) com `TOOLS` da tabela e `registrar` vazio;
  `mcp_server.py`: itera `MODULOS`, `ESCOPO_DAS_TOOLS` unido, listagem filtrada por token (DSP4),
  auditoria `escopo= ms= bytes=` e `alvo=`/`q=` para `prod-ler`/`email-ler` (DSP5).
  - Lê: spec §4, §6 (só a tabela), DSP3–DSP5; `ayanami/mcp_server.py` (linhas 1–80, 150–230), `ayanami/api/auth.py` (linhas 30–100), `ayanami/api/app.py` (`ROTEADORES`), `ayanami/api/auditoria.py`, `tests/ayanami/test_mcp.py` (`grep -n "def "`)
  - Escreve: `ayanami/api/auth.py` (só `ESCOPOS_PADRAO`/`ESCOPO_DE_ROTA`), `ayanami/api/app.py` (só `ROTEADORES`), `ayanami/api/{sessoes_dev,ops,bom_dia,learning,audiolivro}.py` (stubs), `ayanami/mcp_tools/*.py` (stubs), `ayanami/mcp_server.py`, `tests/ayanami/test_mcp_escopos.py`
  - Depende de: celular M1.1
  - Orçamento: ~55k
  - Pronto: CA-P7, CA-P8, CA-P9 verdes; `tests/ayanami/test_mcp.py` e `tests/ayanami/api` verdes.
  - Paralelo: P0.1, P0.3, P0.4, P0.5

- [x] **P0.3 Redator** — `ayanami/redator.py` (`redigir`, `envelope`, regras da spec §5) e testes.
  - Lê: spec §5, DSP6; R0.8
  - Escreve: `ayanami/redator.py`, `tests/ayanami/test_redator.py`
  - Depende de: —
  - Orçamento: ~25k
  - Pronto: CA-P10 verde.
  - Paralelo: P0.1, P0.2, P0.4, P0.5

- [ ] **P0.4 Vigia: limiares por serviço e webhook** — `vigia.py`: `mem:`/`oom:` por serviço (10 leituras
  > 90% do `mem_limit`), disco > 70%, POST a `/v1/ops/alerta?fonte=vigia` (bearer `OPS_WEBHOOK_TOKEN`
  do `.env`) nas causas novas e resoluções; Minecraft só com `VIGIA_MINECRAFT=1`.
  - Lê: spec §9 (parágrafo "Vigia"), DSP7; R0.10; `deploy/ayanami/vigia/vigia.py` (`grep -n "def \|class "` e as funções de causa), `tests/deploy/test_ayanami_vigia.py` (`grep -n "def "`)
  - Escreve: `deploy/ayanami/vigia/vigia.py`, `tests/deploy/test_ayanami_vigia.py` (só testes novos)
  - Depende de: —
  - Orçamento: ~40k
  - Pronto: CA-P21 verde; testes antigos do vigia verdes (os de Minecraft com `VIGIA_MINECRAFT=1`).
  - Paralelo: P0.1, P0.2, P0.3, P0.5

- [ ] **P0.5 Config, segredos, eventos e cessão** — seções novas da spec §2 em `config.py` e no
  `ayanami.example.toml`; nomes dos segredos no `env.example` e no `Segredos` (frente desligada sem
  segredo); `EventoTipo` novos (spec §9, último parágrafo) em `magi/elo/mensagens.py`; campo aditivo
  `urgencia` no payload do `push.enviar` (DSP9, sem mexer no resto do push); `ayanami/plataforma.py`
  (`na_janela`, `threads_lote`, `ceder`, spec §7).
  - Lê: spec §2, §7 (só "Cessão"), §9 (eventos), DSP8–DSP10; `ayanami/config.py` (`grep -n "class \|def "` e o carregador de uma seção), `deploy/ayanami/ayanami.example.toml`, `deploy/ayanami/env.example`, `magi/elo/mensagens.py` (`grep -n "EventoTipo" -A30`), `ayanami/push.py` (`grep -n "def enviar\|payload\|Urgency"`), `tests/ayanami/test_config.py` (`grep -n "def "`)
  - Escreve: `ayanami/config.py` (só seções novas, `[budget] teto_lote_usd`, padrão de `[mcp] escopos`), `deploy/ayanami/ayanami.example.toml` (idem), `deploy/ayanami/env.example` (só nomes novos), `magi/elo/mensagens.py` (só `EventoTipo`), `ayanami/push.py` (só `urgencia`), `ayanami/plataforma.py`, `tests/ayanami/test_config_plataforma.py`, `tests/ayanami/test_plataforma.py`
  - Depende de: celular M1.1, M1.2, M1.5
  - Orçamento: ~50k
  - Pronto: CA-P4, CA-P5, CA-P14 verdes; `tests/ayanami` e `tests/elo` verdes.
  - Paralelo: P0.1, P0.2, P0.3, P0.4

- [ ] **P0.6 Gateway de MCP de terceiros (D14 b)** — `ayanami/gateway.py` (spec §13 "Gateway"), perfil
  `gateway` no compose (um sub-servidor de exemplo comentado), registro em `MODULOS`.
  - Lê: spec §13 (Gateway), §4 (DSP3, DSP4); R0.9; `ayanami/mcp_tools/__init__.py`
  - Escreve: `ayanami/gateway.py`, `ayanami/mcp_tools/__init__.py` (só a entrada do gateway), `deploy/ayanami/compose.yml` (só o bloco comentado), `tests/ayanami/test_gateway.py`
  - Depende de: P0.2
  - Orçamento: ~45k
  - Pronto: CA-P47 verde; `[gateway] ligado=false` não muda `tools/list`.
  - Paralelo: P4.5, P1.6, P1.7

## Fase P2 — Ops

- [ ] **P2.1 Gatus e heartbeats** — serviço `gatus` (spec §1), `deploy/ayanami/gatus/config.yaml` (spec §9),
  `GATUS_URL_*`/`GATUS_HB_TOKEN` no `env.example`, `tailscale serve` 8446, `ayanami/heartbeat.py`, seção
  "Gatus" no runbook (como preencher as URLs, F.7).
  - Lê: spec §1 (regras e linha `gatus`), §9 (Gatus), DSP7, DSP11; R2.5; `deploy/ayanami/compose.yml` (um serviço), `deploy/ayanami/host/tailscale.sh`, `tests/deploy/compose_mesclado.py`
  - Escreve: `deploy/ayanami/compose.yml` (só `gatus` e volume), `deploy/ayanami/gatus/config.yaml`, `deploy/ayanami/host/tailscale.sh` (só 8446), `deploy/ayanami/env.example` (só `GATUS_*`), `ayanami/heartbeat.py`, `docs/ayanami/runbook.md` (seção "Gatus"), `tests/deploy/test_compose_gatus.py`, `tests/ayanami/test_heartbeat.py`
  - Depende de: P0.1, P0.5
  - Orçamento: ~40k
  - Pronto: CA-P19, CA-P20 verdes; CA-P1/CA-P2 com o `gatus`.
  - Paralelo: P2.2, P2.3

- [ ] **P2.2 Beszel** — `beszel` e `beszel-agent` (spec §1, §9), `tailscale serve` 8447,
  `deploy/pc/beszel-agent.service`, `deploy/node1/beszel-agent.md` (D10 a), seção "Beszel" no runbook
  (alertas e webhook pela UI).
  - Lê: spec §1, §9 (Beszel); R2.6, D10; `deploy/ayanami/compose.yml` (um serviço), `tests/deploy/compose_mesclado.py`
  - Escreve: `deploy/ayanami/compose.yml` (só `beszel*` e volume), `deploy/ayanami/host/tailscale.sh` (só 8447), `deploy/ayanami/env.example` (só `BESZEL_*`), `deploy/pc/beszel-agent.service`, `deploy/node1/beszel-agent.md`, `docs/ayanami/runbook.md` (seção "Beszel"), `tests/deploy/test_compose_beszel.py`
  - Depende de: P0.1
  - Orçamento: ~25k
  - Pronto: CA-P1/CA-P2 com o Beszel; o agente sem `docker.sock` (teste).
  - Paralelo: P2.1, P2.3

- [ ] **P2.3 `/v1/ops/alerta` e incidentes** — migração `004_ops.sql`; `ayanami/ops.py` (normalizadores
  gatus/beszel/vigia/job/bugsink, dedup, correlação, classificação, molde, entrega por criticidade com
  silêncio, fechamento); router `ayanami/api/ops.py`; `Def ops.correlacionar`; frases em
  `ayanami/frases.yaml` (`incidente.*`).
  - Lê: spec §3 (linha 004), §6 (linha do alerta), §7 (linha `ops.correlacionar`), §9 (Normalização), DSP7–DSP9; R2.7, R2.8; `ayanami/fila.py` (linhas 60–125), `ayanami/telegram.py`, `ayanami/eventos.py` (`gravar`), `ayanami/push.py` (`grep -n "def \|urgencia"`), `ayanami/api/backup.py` (padrão de router)
  - Escreve: `ayanami/migrations/004_ops.sql`, `ayanami/ops.py`, `ayanami/api/ops.py`, `ayanami/fila.py` (só a linha `Def`), `ayanami/frases.yaml` (só `incidente.*`), `tests/ayanami/test_ops.py`, `tests/ayanami/api/test_ops_alerta.py`
  - Depende de: P0.2, P0.3, P0.5
  - Orçamento: ~60k
  - Pronto: CA-P12, CA-P22, CA-P23, CA-P24 verdes (`pg` no `ayanami-pg-teste`); CA-P6 parcial (004).
  - Paralelo: P2.1, P2.2

- [ ] **P2.4 `ops_status` e `ops_incidentes`** — módulo `ayanami/mcp_tools/ops.py` (as duas tools),
  clientes de leitura do Gatus (`/api/v1/endpoints/statuses`) e do Beszel (API do hub) em
  `ayanami/ops_fontes.py`, pontos cegos (node1, ping, B2).
  - Lê: spec §4 (linhas `ops_*`), §9, §13 (Ping, só o ponto cego); R2.9; `ayanami/ops.py` (`grep -n "def "`), `ayanami/mcp_tools/ops.py` (stub)
  - Escreve: `ayanami/mcp_tools/ops.py`, `ayanami/ops_fontes.py`, `tests/ayanami/test_mcp_ops.py`
  - Depende de: P2.1, P2.2, P2.3
  - Orçamento: ~40k
  - Pronto: CA-P56 verde (parte `ops_status`); `ops_incidentes` testado com incidentes de fixture.
  - Paralelo: P1.1, P1.2

- [ ] **P2.5 Porta única só-leitura (código)** — `deploy/node1/ayanami-ro`, `authorized_keys.exemplo`,
  `ayanami_ro.sql`, `projetos.exemplo`, `docs/ayanami/node1-porta-unica.md` (ACL, passos, reverter);
  `ayanami/node1.py` (`Node1`, executor real por `ssh` e `ExecutorFalso`); teste do script com binários
  falsos no `PATH`.
  - Lê: spec §8 (Porta única, Cliente); design §5.2; R2.1, D5
  - Escreve: `deploy/node1/ayanami-ro`, `deploy/node1/authorized_keys.exemplo`, `deploy/node1/ayanami_ro.sql`, `deploy/node1/projetos.exemplo`, `docs/ayanami/node1-porta-unica.md`, `ayanami/node1.py`, `tests/deploy/test_node1_ro.py`, `tests/ayanami/test_node1.py`
  - Depende de: P0.5
  - Orçamento: ~40k
  - Pronto: CA-P15 verde; `ExecutorFalso` cobre os 3 verbos.
  - Paralelo: P4.1, P4.2

- [ ] **P2.6 `backup.node1` e `sandbox.restaurar`** — serviço `sandbox-db` (spec §1), migração
  `008_node1.sql`, função `backup_node1` (nova, em `ayanami/workers/backup.py` ou módulo
  `ayanami/workers/node1.py` — prefira o módulo novo), `ayanami/sandbox.py` (restore, máscara, contagens,
  troca), `deploy/ayanami/sandbox/exemplo/mascara.toml`, linhas `Def`, heartbeats.
  - Lê: spec §1 (linha `sandbox-db`), §3 (linha 008), §7 (linhas `backup.node1`/`sandbox.restaurar`), §8; R2.1–R2.4; `ayanami/workers/backup.py` (`grep -n "def \|restic"` e a função `restic`), `ayanami/node1.py`, `ayanami/heartbeat.py`, `ayanami/ops.py` (só a assinatura de abrir incidente)
  - Escreve: `deploy/ayanami/compose.yml` (só `sandbox-db` e volume), `ayanami/migrations/008_node1.sql`, `ayanami/workers/node1.py`, `ayanami/sandbox.py`, `deploy/ayanami/sandbox/exemplo/mascara.toml`, `ayanami/fila.py` (só as 2 linhas), `tests/ayanami/test_backup_node1.py`, `tests/ayanami/test_sandbox.py`, `tests/deploy/test_compose_sandbox.py`
  - Depende de: P2.3, P2.5, P2.1
  - Orçamento: ~60k
  - Pronto: CA-P16, CA-P17 verdes; `test_backup_jobs.py` verde; CA-P1 com o `sandbox-db`.
  - Paralelo: P3.1

- [ ] **P2.7 `ops_backup`, `ops_filas` e ping externo** — as duas tools em `mcp_tools/ops.py`,
  `deploy/ayanami/host/ayanami-ping.{service,timer}`, `preparar.sh` instala as unidades (só a linha).
  - Lê: spec §4 (linhas), §13 (Ping); R2.9, R2.10, D12; `ayanami/mcp_tools/ops.py`, `ayanami/node1.py` (assinaturas), `deploy/ayanami/host/preparar.sh` (`grep -n "vigia"`), `tests/deploy/test_units.py` (`grep -n "def "`)
  - Escreve: `ayanami/mcp_tools/ops.py` (só as duas tools), `deploy/ayanami/host/ayanami-ping.service`, `deploy/ayanami/host/ayanami-ping.timer`, `deploy/ayanami/host/preparar.sh` (só a instalação), `tests/ayanami/test_mcp_ops_backup.py`, `tests/deploy/test_ping_units.py`
  - Depende de: P2.4, P2.6
  - Orçamento: ~35k
  - Pronto: CA-P48, CA-P56 (parte `ops_backup`), CA-P57 verdes.
  - Paralelo: P1.3, P3.6

## Fase P1 — Dev/MCP

- [ ] **P1.1 `ci.coletar` e `ci_*`** — migração `005_ci.sql`; `ayanami/workers/ci.py` (GitHub REST só `GET`
  com `GITHUB_PAT_RO`, ETag, backoff, log baixado redigido com `expira`, verde→vermelho emite
  `ci.vermelho` + push `low`, volta emite `ci.verde`, defer `git.espelhar` ao ver push na padrão
  quando o Def existir); `ayanami/ci_log.py` (extrator por regra pytest/PHPUnit/tsc/ESLint);
  `mcp_tools/ci.py` (4 tools); heartbeat `ci-coletar`; 4 logs de fixture.
  - Lê: spec §3 (linha 005), §4 (linhas `ci_*`), §7 (linha), CA-P49/P50; R1.1–R1.3; `ayanami/fila.py` (linhas 60–125), `ayanami/redator.py`, `ayanami/heartbeat.py`, `ayanami/mcp_tools/ci.py` (stub)
  - Escreve: `ayanami/migrations/005_ci.sql`, `ayanami/workers/ci.py`, `ayanami/ci_log.py`, `ayanami/mcp_tools/ci.py`, `ayanami/fila.py` (só `ci.coletar`), `tests/ayanami/test_ci.py`, `tests/ayanami/test_ci_log.py`, `tests/fixtures/ci_logs/*`
  - Depende de: P0.2, P0.3, P0.5, P2.1
  - Orçamento: ~60k
  - Pronto: CA-P49, CA-P50 verdes; CA-P13 para a linha nova.
  - Paralelo: P1.2, P2.4

- [ ] **P1.2 Sessões dev e hook** — migração `006_sessoes_dev.sql`; router `ayanami/api/sessoes_dev.py`;
  `mcp_tools/sessoes.py` (3 tools, busca híbrida com o e5 do `embeddings.py`); `hooks/claude-sessao-fim.py`
  (stdlib, fila local, ≤ 3 s, sem transcript); `docs/ayanami/hook-sessoes.md` (como instalar no
  `settings.json` do Claude Code; quem instala é o Pedro no F.3).
  - Lê: spec §3 (linha 006), §4 (linhas `sessoes_*`), §6 (linha), CA-P51/P52; R1.4, R1.5; `ayanami/workers/embeddings.py` (`grep -n "def "`), `ayanami/redator.py`, `ayanami/api/backup.py` (padrão de router)
  - Escreve: `ayanami/migrations/006_sessoes_dev.sql`, `ayanami/api/sessoes_dev.py`, `ayanami/mcp_tools/sessoes.py`, `hooks/claude-sessao-fim.py`, `docs/ayanami/hook-sessoes.md`, `tests/ayanami/api/test_sessoes_dev.py`, `tests/ayanami/test_mcp_sessoes.py`, `tests/hooks/test_sessao_fim.py`
  - Depende de: P0.2, P0.3, P0.5
  - Orçamento: ~55k
  - Pronto: CA-P11, CA-P51, CA-P52 verdes.
  - Paralelo: P1.1, P2.4

- [ ] **P1.3 Espelhos git e índice de código** — migração `009_codigo.sql`; `ayanami/workers/git_espelho.py`
  (`clone --mirror`/`remote update --prune`, PAT por `GIT_ASKPASS`, defer de `codigo.indexar` se mudou
  o HEAD); `ayanami/workers/codigo.py` (tree-sitter PHP/Blade/TS/TSX/Py, incremental por `sha_arquivo`,
  exclusões, e5 em lote, `ceder` e `threads_lote`); 2 linhas `Def`; volume `ayanami-git` no compose
  (montado em `worker-agendado` e `worker-lento`) e incluído no restic (`backup.restic`, só o caminho).
  - Lê: spec §3 (linha 009), §7 (linhas), CA-P53/P54; R1.6, R1.7; `ayanami/plataforma.py`, `ayanami/workers/embeddings.py` (`grep -n "def "`), `ayanami/workers/backup.py` (`grep -n "caminhos\|paths"`)
  - Escreve: `ayanami/migrations/009_codigo.sql`, `ayanami/workers/git_espelho.py`, `ayanami/workers/codigo.py`, `ayanami/fila.py` (só as 2 linhas), `deploy/ayanami/compose.yml` (só o volume e as 2 montagens), `ayanami/workers/backup.py` (só a lista de caminhos do restic), `tests/ayanami/test_git_espelho.py`, `tests/ayanami/test_codigo_indexar.py`, `tests/fixtures/codigo/*`
  - Depende de: P1.1, P0.5
  - Orçamento: ~60k
  - Pronto: CA-P53, CA-P54 verdes. Dependência nova (`tree-sitter-language-pack`) → *Sobras* se faltar.
  - Paralelo: P2.7, P3.6

- [ ] **P1.4 Tools `codigo_*`** — `mcp_tools/codigo.py` (busca híbrida HNSW + `tsvector`, filtro
  projeto/linguagem, `Classe::metodo`).
  - Lê: spec §4 (linhas `codigo_*`), CA-P55; `ayanami/workers/codigo.py` (`grep -n "def "`), `ayanami/mcp_tools/codigo.py` (stub)
  - Escreve: `ayanami/mcp_tools/codigo.py`, `tests/ayanami/test_mcp_codigo.py`
  - Depende de: P1.3
  - Orçamento: ~30k
  - Pronto: CA-P55 verde.
  - Paralelo: P1.5, P4.3, P4.4

- [ ] **P1.5 `sql_schema` e `sql_ler`** — `ayanami/sql_ler.py` (filtro `sqlglot`, `LIMIT`, transação
  `READ ONLY`, `statement_timeout`), `mcp_tools/prod.py` (2 tools), auditoria `alvo=`/`q=`.
  - Lê: spec §8 (`sql_ler`), §4 (linhas), DSP5; R1.8, D6; `ayanami/sandbox.py` (`grep -n "def \|leitor"`), `ayanami/mcp_tools/prod.py` (stub)
  - Escreve: `ayanami/sql_ler.py`, `ayanami/mcp_tools/prod.py` (só as 2 tools), `tests/ayanami/test_sql_ler.py`
  - Depende de: P2.6, P0.2
  - Orçamento: ~40k
  - Pronto: CA-P18 verde; `prod-ler` fora de todo padrão (CA-P7). `sqlglot` faltando → *Sobras*.
  - Paralelo: P1.4, P4.3, P4.4

- [ ] **P1.6 Bugsink e `prod_erros` (D8)** — serviço `bugsink` (perfil `erros`), `prod_erros` em
  `mcp_tools/prod.py`, alerta de grupo novo, `deploy/ayanami/caddy/erros.Caddyfile.exemplo`.
  - Lê: spec §1 (linha), §13 (Bugsink), §9 (classificação `baixa`); R1.9, D8; `ayanami/ops.py` (assinaturas)
  - Escreve: `deploy/ayanami/compose.yml` (só `bugsink`), `ayanami/bugsink.py`, `ayanami/mcp_tools/prod.py` (só `prod_erros`), `deploy/ayanami/caddy/erros.Caddyfile.exemplo`, `tests/ayanami/test_bugsink.py`, `tests/deploy/test_compose_bugsink.py`
  - Depende de: P2.3, P1.5
  - Orçamento: ~40k
  - Pronto: CA-P44, CA-P45 verdes; CA-P3 com `erros`.
  - Paralelo: P4.5, P1.7, P0.6

- [ ] **P1.7 Runner self-hosted (D9)** — serviço `runner` (perfil `runner`), `ayanami-runner.{service,timer}`
  e `runner.sh` (exclusão com `llm-local`), `deploy/ayanami/runner/repos.txt.exemplo`.
  - Lê: spec §1 (linha), §13 (Runner), §11 (`noite.sh`); R0.4, D9; `deploy/ayanami/host/noite.sh`
  - Escreve: `deploy/ayanami/compose.yml` (só `runner`), `deploy/ayanami/host/ayanami-runner.service`, `deploy/ayanami/host/ayanami-runner.timer`, `deploy/ayanami/host/runner.sh`, `deploy/ayanami/runner/repos.txt.exemplo`, `tests/deploy/test_runner.py`
  - Depende de: P4.3
  - Orçamento: ~30k
  - Pronto: CA-P46 verde; CA-P35 segue verde.
  - Paralelo: P4.5, P1.6, P0.6

## Fase P3 — Condessa noturna

- [ ] **P3.1 Bom dia só com molde** — migração `007_bom_dia.sql`; `ayanami/workers/bom_dia.py` (spec §10:
  clima, notícias, ops, incidentes, placar; `faltou`; humor só pelo molde nesta tarefa — o gancho do LLM
  fica para a P3.3), Kokoro pelo `ayanami-voz`, heartbeat `bom-dia`, evento `bom_dia.pronto`, entrega na
  primeira presença (`tocado`), router `ayanami/api/bom_dia.py`, `Def noite.bom_dia`, frases `bom_dia.*`.
  - Lê: spec §3 (linha 007), §6 (linhas bom dia), §7 (linha), §10 (Bom dia); R3.1, R3.6, R3.7; `ayanami/workers/voz.py` (`grep -n "def "`), `ayanami/turnos.py` (`grep -n "presen"`), `ayanami/hub.py` (`grep -n "presen\|def "`), `ayanami/mcp_tools/ops.py` (assinaturas), `ayanami/frases.yaml` (`grep -n "^[a-z]"`)
  - Escreve: `ayanami/migrations/007_bom_dia.sql`, `ayanami/workers/bom_dia.py`, `ayanami/api/bom_dia.py`, `ayanami/fila.py` (só a linha), `ayanami/frases.yaml` (só `bom_dia.*`), `ayanami/hub.py` (só o gancho de primeira presença), `tests/ayanami/test_bom_dia.py`, `tests/ayanami/api/test_bom_dia.py`
  - Depende de: P2.4, P4.1, P4.2, P0.5
  - Orçamento: ~60k
  - Pronto: CA-P25 (sem a parte do LLM), CA-P26, CA-P27 verdes.
  - Paralelo: P2.6

- [ ] **P3.6 A Condessa do PC toca o bom dia** — no PC, ao receber `bom_dia.pronto` pelo elo, baixa
  `/v1/bom-dia/hoje` e o `.opus`, toca pela saída de voz atual e mostra o card no HUD (aviso existente);
  adia se houver jogo.
  - Lê: spec §10 (Bom dia, último trecho); `magi/elo/` (`grep -rn "EventoTipo\.\|def _on_evento\|evento"`), `magi/elo/mensagens.py` (EventoTipo)
  - Escreve: o handler de evento do elo no PC (arquivo apontado pelo grep, só o ramo novo) e `tests/elo/test_bom_dia_pc.py`
  - Depende de: P3.1
  - Orçamento: ~40k
  - Pronto: teste com elo falso: evento → 1 download + 1 reprodução falsa; segundo evento no dia ignorado; jogo ativo adia.
  - Paralelo: P2.7, P1.3

- [ ] **P3.2 Diário e aula do dia** — migração `010_diario_aula.sql`; `ayanami/workers/diario.py`
  (`noite.diario`, semana no domingo, só `Cadeia` com `llm-local`), `ayanami/workers/aula.py`
  (`noite.aula`), `ayanami/sm2.py`, `ayanami/prompts/diario.md`, router `ayanami/api/learning.py`
  (`POST /v1/learning/obs`), `mcp_tools/pessoal.py` (`memoria_diario`), 2 linhas `Def`.
  - Lê: spec §3 (linha 010), §4 (linha), §6 (linha), §7 (linhas), §10 (Diário e aula), §11 (Cadeia); R3.2, R3.3; `ayanami/llm_local.py` (`grep -n "def \|class "`), `ayanami/workers/embeddings.py` (`grep -n "def "`)
  - Escreve: `ayanami/migrations/010_diario_aula.sql`, `ayanami/workers/diario.py`, `ayanami/workers/aula.py`, `ayanami/sm2.py`, `ayanami/prompts/diario.md`, `ayanami/api/learning.py`, `ayanami/mcp_tools/pessoal.py`, `ayanami/fila.py` (só as 2 linhas), `tests/ayanami/test_diario.py`, `tests/ayanami/test_aula.py`, `tests/ayanami/test_sm2.py`
  - Depende de: P4.3
  - Orçamento: ~60k
  - Pronto: CA-P28, CA-P29, CA-P30 (parte da rota) verdes.
  - Paralelo: P3.3, P3.7

- [ ] **P3.7 `learning_sync` no PC** — `magi/elo/learning_sync.py` (lê `learning_*` do `magi-pg` só com
  `SELECT`, posta `/v1/learning/obs` com o token `pc`, idempotente por `uid`), ligado ao fechamento local
  do Learning Mode ou a um timer de usuário (`hud/system/` **não**: `deploy/pc/magi-learning-sync.{service,timer}`).
  - Lê: spec §10 (último trecho do Diário e aula), §6 (linha); `magi/learning/repo.py` (`grep -n "def \|class "`), `magi/elo/` (cliente HTTP com token: `grep -rln "Authorization"`)
  - Escreve: `magi/elo/learning_sync.py`, `deploy/pc/magi-learning-sync.service`, `deploy/pc/magi-learning-sync.timer`, `tests/elo/test_learning_sync.py`
  - Depende de: P3.2 (contrato da rota; pode começar com a rota da spec e Ayanami falsa)
  - Orçamento: ~35k
  - Pronto: CA-P30 (parte do PC) verde; nada toca o `magi-pg` real nos testes.
  - Paralelo: P3.2, P3.3

- [ ] **P3.3 Pesquisa profunda e humor no bom dia** — modo `profundo` na `pesquisar`
  (`agente.pesquisar_profundo`, spec §10), `trafilatura`, orçamento `usd_max` no `BudgetLote`, evento
  `pesquisa.pronta`, 3 frases no bom dia; gancho da frase de humor do bom dia pela `Cadeia` (≤ 60 s).
  - Lê: spec §7 (linha), §10 (Pesquisa profunda e o trecho do humor), §11 (Cadeia, BudgetLote); R3.4; `ayanami/workers/agente.py` (`grep -n "def \|pesquisar"` e o corpo de `pesquisar`), `ayanami/web.py`, `ayanami/workers/bom_dia.py` (`grep -n "def \|humor"`)
  - Escreve: `ayanami/workers/agente.py` (só o modo profundo), `ayanami/workers/pesquisa_profunda.py`, `ayanami/workers/bom_dia.py` (só o gancho do humor e as frases da pesquisa), `ayanami/fila.py` (só a linha), `tests/ayanami/test_pesquisa_profunda.py`, `tests/ayanami/test_bom_dia_humor.py`
  - Depende de: P4.3, P4.1, P3.1
  - Orçamento: ~55k
  - Pronto: CA-P31 e a parte LLM do CA-P25 verdes; `test_agente.py` verde.
  - Paralelo: P3.2, P3.7

- [ ] **P3.4 Audiolivro no node 2** — migração `011_audiolivro.sql`; `ayanami/workers/audiolivro.py`
  (EPUB → capítulos, marcação portada do código do PC, elenco Kokoro, Opus por `ffmpeg` com `nice`,
  2 à frente, apagar após 30 dias), router `ayanami/api/audiolivro.py`, `Def audiolivro.renderizar`.
  - Lê: spec §3 (linha 011), §6 (linhas), §7 (linha), §10 (Audiolivro); R3.5; o código de marcação do audiolivro do PC (`grep -rln "audiolivro\|epub" magi hud scripts`, só as funções de marcação), `ayanami/workers/voz.py` (`grep -n "def "`), `ayanami/plataforma.py`
  - Escreve: `ayanami/migrations/011_audiolivro.sql`, `ayanami/workers/audiolivro.py`, `ayanami/audiolivro_marcacao.py`, `ayanami/api/audiolivro.py`, `ayanami/fila.py` (só a linha), `tests/ayanami/test_audiolivro.py`, `tests/ayanami/api/test_audiolivro.py`
  - Depende de: P4.3 (marcação pela `Cadeia`), P0.5
  - Orçamento: ~60k
  - Pronto: CA-P32 verde. `ebooklib` faltando → leitor de EPUB com `zipfile` (EPUB é zip) e anote.
  - Paralelo: P3.5

- [ ] **P3.5 Player do audiolivro no PWA** — tela/aba de audiolivros (lista, upload de EPUB, play/pause,
  ±30 s, marcador a cada 15 s) no PWA existente, sem mudar o resto.
  - Lê: spec §6 (linhas audiolivro), §10 (último trecho); `ayanami/pwa/` (`ls` e o roteamento de abas), `tests/ayanami/pwa/` (`ls`)
  - Escreve: `ayanami/pwa/audiolivro.mjs`, `ayanami/pwa/index.html` (só o link da aba), `tests/ayanami/pwa/audiolivro.test.mjs`
  - Depende de: P3.4 (contrato; pode usar Ayanami falsa)
  - Orçamento: ~40k
  - Pronto: CA-P33 verde; os `.mjs` antigos verdes.
  - Paralelo: P3.4

## Fase P4 — Serviços pessoais

- [ ] **P4.1 SearXNG e `web_buscar`** — `searxng` + `valkey` (spec §1, §12), `settings.yml`,
  `ayanami/web.py`, `mcp_tools/web.py`, motor padrão da `pesquisar` e do modo nuvem por injeção (a fonte
  antiga vira reserva).
  - Lê: spec §1 (linhas), §4 (linha `web_buscar`), §12 (SearXNG); R4.1; `ayanami/nuvem_tools.py` (`grep -n "busca\|search"`), `ayanami/workers/agente.py` (`grep -n "busca\|search"`)
  - Escreve: `deploy/ayanami/compose.yml` (só `searxng`, `valkey`), `deploy/ayanami/searxng/settings.yml`, `deploy/ayanami/env.example` (só `SEARXNG_SECRET`), `ayanami/web.py`, `ayanami/mcp_tools/web.py`, `ayanami/nuvem_tools.py` e `ayanami/workers/agente.py` (só a injeção do motor), `tests/ayanami/test_web.py`, `tests/deploy/test_compose_searxng.py`
  - Depende de: P0.1, P0.2, P0.3
  - Orçamento: ~45k
  - Pronto: CA-P39 verde; CA-P1 com os dois serviços; `test_agente.py`/`test_nuvem.py` verdes.
  - Paralelo: P4.2, P2.5

- [ ] **P4.2 Miniflux e `rss_*`** — `miniflux` (spec §1, §12), `tailscale serve` 8448, `ayanami/rss.py`,
  `mcp_tools/rss.py`, fonte `miniflux` no coletor de notícias e `marcar_lido` no feedback, seção
  "Miniflux" no runbook (criar banco e papel `miniflux`, OPML).
  - Lê: spec §1 (linha), §4 (linhas `rss_*`), §12 (Miniflux); R4.2; `ayanami/workers/noticias.py` (`grep -n "def \|fonte"`), `ayanami/api/noticias.py` (`grep -n "feedback"`)
  - Escreve: `deploy/ayanami/compose.yml` (só `miniflux`), `deploy/ayanami/host/tailscale.sh` (só 8448), `deploy/ayanami/env.example` (só `MINIFLUX_*`), `ayanami/rss.py`, `ayanami/mcp_tools/rss.py`, `ayanami/workers/noticias.py` (só a fonte nova), `ayanami/api/noticias.py` (só o `marcar_lido`), `docs/ayanami/runbook.md` (seção "Miniflux"), `tests/ayanami/test_rss.py`, `tests/deploy/test_compose_miniflux.py`
  - Depende de: P0.1, P0.2, P0.3
  - Orçamento: ~50k
  - Pronto: CA-P40, CA-P41 verdes; `test_noticias.py` verde.
  - Paralelo: P4.1, P2.5

- [ ] **P4.3 `llm-local`, janela e sub-teto "lote"** — serviço `llm-local` (perfil `noite`),
  `deploy/ayanami/host/noite.sh` + `ayanami-noite.service` + timers de subir/descer, `preparar.sh`
  (só a instalação), `ayanami/llm_local.py` (`LlmLocal`, `Cadeia`, `Adiar`), `BudgetLote` em
  `custos.py`, `Def noite.lote_llm` (resumo de notícias pela `Cadeia`), heartbeat `lote-noite`.
  - Lê: spec §1 (linha), §7 (linha), §11; design §4.3; R0.4, R4.3, R4.5, D2–D4; `ayanami/custos.py` (linhas 1–130), `deploy/ayanami/vigia/ayanami-vigia.timer`, `deploy/ayanami/host/preparar.sh` (`grep -n "vigia"`), `ayanami/workers/noticias.py` (`grep -n "resum"`)
  - Escreve: `deploy/ayanami/compose.yml` (só `llm-local`), `deploy/ayanami/host/noite.sh`, `deploy/ayanami/host/ayanami-noite.service`, `deploy/ayanami/host/ayanami-noite-subir.timer`, `deploy/ayanami/host/ayanami-noite-descer.timer`, `deploy/ayanami/host/preparar.sh` (só a instalação), `ayanami/llm_local.py`, `ayanami/custos.py` (só `BudgetLote`), `ayanami/workers/lote_llm.py`, `ayanami/fila.py` (só a linha), `tests/ayanami/test_llm_local.py`, `tests/ayanami/test_custos_lote.py`, `tests/deploy/test_noite.py`
  - Depende de: P0.1, P0.5, P2.1
  - Orçamento: ~60k
  - Pronto: CA-P34–CA-P37 e CA-P58 (parte do import) verdes; `test_custos.py` verde.
  - Paralelo: P1.4, P1.5, P4.4

- [ ] **P4.4 Bench e A/B** — `scripts/ayanami/llm_bench.sh`, `scripts/ayanami/ab_llm.py`, 30 amostras
  sintéticas por tarefa em `tests/fixtures/ab/` (sem dado real do Pedro), formato da nota em
  `docs/spikes/ayanami-plataforma-ab.md` (modelo a preencher no F.6).
  - Lê: spec §11 (Bench e A/B), §14 (S1, M8); R4.4
  - Escreve: `scripts/ayanami/llm_bench.sh`, `scripts/ayanami/ab_llm.py`, `tests/fixtures/ab/**`, `docs/spikes/ayanami-plataforma-ab.md`, `tests/ayanami/test_ab_llm.py`
  - Depende de: —
  - Orçamento: ~30k
  - Pronto: CA-P38 verde.
  - Paralelo: P1.4, P1.5, P4.3

- [ ] **P4.5 E-mail IMAP só leitura (D7b)** — migração `012_email.sql`; `ayanami/workers/email.py`
  (IMAP injetado, `readonly`, `BODY.PEEK`, comandos proibidos, classificação pela `Cadeia`, regra de
  boleto), `ops.vencimentos`, `mcp_tools/email.py` (2 tools), 3 linhas `Def`, item no bom dia.
  - Lê: spec §3 (linha 012), §4 (linhas), §7 (linhas), §13 (E-mail); R4.6, R4.7, D7b; `ayanami/llm_local.py` (`grep -n "class \|def "`), `ayanami/workers/bom_dia.py` (`grep -n "def \|secoes"`)
  - Escreve: `ayanami/migrations/012_email.sql`, `ayanami/workers/email.py`, `ayanami/mcp_tools/email.py`, `ayanami/fila.py` (só as 3 linhas), `ayanami/workers/bom_dia.py` (só a seção de vencimentos), `tests/ayanami/test_email.py`
  - Depende de: P4.3, P3.1
  - Orçamento: ~55k
  - Pronto: CA-P42, CA-P43 verdes; CA-P6 completo (004–012).
  - Paralelo: P1.6, P1.7, P0.6

## Fase F — Precisa do Pedro

- [ ] **F.1 Decisões D1–D4, D11 e D13 (precisa do Pedro)** — Pedro responde: Minecraft não volta (D1),
  LLM local sim/não e modelo (D2), janela (D3: joga de madrugada?), sub-teto `lote` (D4), horário de
  silêncio e bot do Telegram (D11, DSP8), escopos por token (D13). O agente grava as respostas no
  requirements (seção Decisões, "Decidido em …") e ajusta os padrões da spec §2 se mudarem.
  - Lê: requirements (Decisões), spec §2
  - Escreve: `specs/ayanami-plataforma/requirements.md` (só as linhas de decisão), `specs/ayanami-plataforma/spec.md` (só §2, se mudar), `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: —
  - Orçamento: ~10k do agente + Pedro
  - Pronto: D1–D4, D11, D13 decididas por escrito.
  - Paralelo: onda 1

- [ ] **F.2 Deploy do perfil "node 2 inteiro" e M1/M2 (precisa do Pedro)** — Pedro: `COMPOSE_FILE` com o
  override, deploy pela CI, cria banco e papel `miniflux` quando chegar a P4.2 (runbook), gera
  `OPS_WEBHOOK_TOKEN`/`GATUS_HB_TOKEN`, `tailscale serve` 8446–8448, configura alertas e webhook do Beszel
  na UI, instala o agente Beszel no PC; mede repouso 24 h (M1) e latência com/sem lote (M2).
  - Lê: spec §1, §9, §14 (M1, M2); runbook seções "Gatus", "Beszel"
  - Escreve: `docs/spikes/ayanami-plataforma-m1-m2.md`, `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: P0.1–P0.5, P2.1–P2.3, F.1
  - Orçamento: ~15k do agente + Pedro
  - Pronto: M1 ≤ 3 GiB em repouso; CA-P1 confirmado no `docker compose config` real.
  - Paralelo: P2.4, P1.1, P1.2

- [ ] **F.3 PAT do GitHub, hook do Claude Code e S4 (precisa do Pedro)** — Pedro cria o PAT
  *fine-grained* só-leitura (Actions, Contents, Pull requests, Metadata) em todos os repos, põe
  `GITHUB_PAT_RO` no `.env`, liga `[ci]`; instala o hook (doc da P1.2) no `settings.json` e roda uma
  sessão; o agente confere o formato real do `SessionEnd`/`Stop` (S4) e corrige a fixture se precisar.
  - Lê: spec §4 (linhas `ci_*`/`sessoes_*`), §14 (S4); `docs/ayanami/hook-sessoes.md`
  - Escreve: `docs/spikes/ayanami-plataforma-s4.md`, `tests/hooks/fixtures/*` (se o formato mudou), `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: P1.1, P1.2, F.2
  - Orçamento: ~15k do agente + Pedro
  - Pronto: `ci_falhas` real responde no Claude Code; uma sessão aparece em `sessoes_ultimas`.
  - Paralelo: P4.1, P4.2, P2.5

- [ ] **F.4 Node 1: porta única, Beszel e máscara (D5, D6, D10, S2) (precisa do Pedro)** — Pedro: aceita
  contratualmente a cópia dos dados (D5); node 1 no tailnet com `tag:prod` e ACL; instala `ayanami-ro`,
  `authorized_keys` com `restrict,command=`, papel `ayanami_ro` e usuário `monitoring` no RabbitMQ
  (doc da P2.5); agente Beszel só host (D10 a); revisa `mascara.toml` de cada projeto (D6); mede o
  tamanho dos dumps e o tempo de restore (S2); liga `[node1]` e, se quiser, `prod-ler` no token do
  Claude Code. O agente ajusta horários da spec §7 se S2 pedir.
  - Lê: spec §8, §14 (S2, M7); `docs/ayanami/node1-porta-unica.md`, `deploy/node1/beszel-agent.md`
  - Escreve: `docs/spikes/ayanami-plataforma-s2.md`, `specs/ayanami-plataforma/spec.md` (só §7, se mudar), `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: P2.5, P2.6, P2.2, F.2 (ligar `prod-ler` só depois da P1.5)
  - Orçamento: ~15k do agente + Pedro
  - Pronto: uma noite com `backup.node1` + `sandbox.restaurar` verdes; `ops_filas` real responde; M7 parte node 1.
  - Paralelo: P2.7, P1.3, P3.6

- [ ] **F.5 B2, healthchecks.io e Telegram (D7a, D12, D11) (precisa do Pedro)** — Pedro cria a conta B2 e
  a chave restrita ao bucket (o envio Y4.2 passa a incluir `node1-*`), a conta healthchecks.io
  (`HC_PING_URL`, `[ops] ping_ligado=true`, instala `ayanami-ping.timer`) e o bot do Telegram.
  - Lê: spec §13 (Ping), §9 (entrega); runbook de backup
  - Escreve: `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: P2.7, F.2
  - Orçamento: ~5k do agente + Pedro
  - Pronto: `ops_backup` mostra `b2: true`; `ops_status` sem o ponto cego "ping"; um push de teste chega pelo Telegram.
  - Paralelo: P1.4, P1.5, P4.3, P4.4

- [ ] **F.6 LLM local: S1, S3 e A/B (D2) (precisa do Pedro)** — com a P4.3 no ar: Pedro baixa o modelo
  para o volume `ayanami-modelos`, roda `llm_bench.sh` (S1) e o RTF do Kokoro em 4 vCPU; roda
  `ab_llm.py` com 30 amostras reais por tarefa (M8) e dá a nota; S3 (e5 × jina code) nas consultas de
  código; liga `[llm_local]` e põe as tarefas aprovadas em `tarefas_aprovadas`. O agente fecha a linha do
  tempo do design §4.2 com os números.
  - Lê: spec §11, §14 (S1, S3, M8); `docs/spikes/ayanami-plataforma-ab.md`
  - Escreve: `docs/spikes/ayanami-plataforma-s1.md`, `docs/spikes/ayanami-plataforma-s3.md`, `docs/spikes/ayanami-plataforma-ab.md`, `specs/ayanami-plataforma/design.md` (só a tabela §4.2), `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: P4.3, P4.4, P1.3, F.1
  - Orçamento: ~20k do agente + Pedro
  - Pronto: S1, S3 e M8 registrados; `tarefas_aprovadas` decidida.
  - Paralelo: P3.2, P3.3

- [ ] **F.7 URLs do Gatus e feeds do Miniflux (precisa do Pedro)** — Pedro lista as URLs críticas e se
  gold-crm e wedding têm endpoint de saúde (`GATUS_URL_*` no `.env`, nunca no repo) e manda o OPML ou os
  feeds iniciais; o agente ajusta o `gatus/config.yaml` (só nomes de variáveis e asserções).
  - Lê: spec §9 (Gatus), §12 (Miniflux); runbook seções "Gatus" e "Miniflux"
  - Escreve: `deploy/ayanami/gatus/config.yaml` (só asserções), `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: P2.1, P4.2
  - Orçamento: ~10k do agente + Pedro
  - Pronto: todos os sites do node 1 e da Vercel verdes no Gatus real; CA-P19 verde.
  - Paralelo: P3.1, P2.6

- [ ] **F.8 E-mail IMAP (D7b) (precisa do Pedro)** — Pedro gera a senha de app (2FA), escolhe as pastas,
  põe `IMAP_*` no `.env`, liga `[email]` e, se quiser, `email-ler` no token da Condessa; confere uma
  semana de classificação.
  - Lê: spec §13 (E-mail)
  - Escreve: `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: P4.5, F.6
  - Orçamento: ~5k do agente + Pedro
  - Pronto: `email_importantes` real responde; nenhum corpo no banco (consulta do Pedro).
  - Paralelo: F.9

- [ ] **F.9 Bugsink, runner e gateway quando a dor aparecer (D8, D9, D14) (precisa do Pedro)** — Pedro
  decide: D8 (b/c: SDK do Sentry nos repos dos clientes, DNS `erros.dekasis.com.br`, Caddy), D9 (minutos
  do Actions apertando? lista de repos privados), D14 (`github-mcp-server` só leitura, digest). Cada
  "sim" é ligar o perfil e a config; o agente registra a decisão.
  - Lê: spec §13; requirements D8, D9, D14
  - Escreve: `specs/ayanami-plataforma/requirements.md` (só as decisões), `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: P1.6, P1.7, P0.6
  - Orçamento: ~10k do agente + Pedro
  - Pronto: cada D registrada; o que foi ligado tem um teste ao vivo anotado.
  - Paralelo: F.8

- [ ] **F.10 Validação, medições e documentação (precisa do Pedro)** — 20 dias de uso: M2–M7 da spec §14
  (latência, restore, queda simulada, bom dia ≥ 95%, custo `lote`, portas), revisão de ruído dos alertas;
  o agente escreve a nota e a seção "Plataforma" do `docs/GUIA.md` (o que cada tool faz, como ligar cada
  D, onde ver Gatus/Beszel/Miniflux).
  - Lê: requirements (Critérios de sucesso), spec §14; notas dos F anteriores
  - Escreve: `docs/spikes/ayanami-plataforma-validacao.md`, `docs/GUIA.md` (só a seção nova), `specs/ayanami-plataforma/tasks.md` (marcar)
  - Depende de: todas as P e F.2–F.9 (as opcionais não ligadas contam como "fora")
  - Orçamento: ~25k do agente + Pedro
  - Pronto: critérios de sucesso 1–7 medidos e anotados (ou o desvio com plano).
  - Paralelo: —

## Cobertura dos critérios (CA-P1..P58)

| CA | Tarefa | CA | Tarefa |
| --- | --- | --- | --- |
| P1, P2 | P0.1 (+ cada tarefa que cria serviço) | P30 | P3.2 (rota) + P3.7 (PC) |
| P3 | P0.1 + P4.3, P1.6, P1.7 | P31 | P3.3 |
| P4, P5, P14 | P0.5 | P32 | P3.4 |
| P6 | P2.3, P1.1, P1.2, P3.1, P2.6, P1.3, P3.2, P3.4, P4.5 (cada uma a sua; completo na P4.5) | P33 | P3.5 |
| P7, P8, P9 | P0.2 | P34–P37 | P4.3 |
| P10 | P0.3 | P38 | P4.4 |
| P11 | P1.2 | P39 | P4.1 |
| P12 | P2.3 | P40, P41 | P4.2 |
| P13 | cada tarefa com `Def` nova | P42, P43 | P4.5 |
| P15 | P2.5 | P44, P45 | P1.6 |
| P16, P17 | P2.6 | P46 | P1.7 |
| P18 | P1.5 | P47 | P0.6 |
| P19, P20 | P2.1 | P48 | P2.7 |
| P21 | P0.4 | P49, P50 | P1.1 |
| P22–P24 | P2.3 | P51, P52 | P1.2 |
| P25 | P3.1 (molde) + P3.3 (humor) | P53, P54 | P1.3 |
| P26, P27 | P3.1 | P55 | P1.4 |
| P28, P29 | P3.2 | P56 | P2.4 (+ P2.7 `ops_backup`) |
| P57 | P2.7 | P58 | P4.3 (import) + cada tarefa nova em `ayanami/` mantém |

Medições ao vivo (spec §14): S1, S3, M8 → F.6 · S2, M7 (node 1) → F.4 · S4 → F.3 · M1, M2 → F.2 ·
M2–M7 → F.10. Critérios de sucesso 1–7: F.2 (1, 2), F.4 (3, 7), F.10 (todos).

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)

- Síntese: o celular (condessa-celular) não tem tela para o card do bom dia nem para o audiolivro; o
  player entra só no PWA (P3.5). Pedir uma tarefa A* no SDD condessa-celular quando a P3.1 estiver no `main`.
- O diário (P3.2) só enxerga o que passa pela Ayanami (turnos da nuvem e da ponte, tarefas, sessões dev,
  incidentes, `learning_obs`); conversas só do PC ficam de fora até haver sincronização (decidir depois).
- `sqlglot`, `tree-sitter-language-pack`, `trafilatura` e (opcional) `ebooklib` ainda não estão no
  `pyproject.toml`: o Pedro adiciona no extra `ayanami`/`ayanami-ml` antes da onda 6–9 (ninguém roda
  `uv lock` por agente).
- Digests das imagens novas (`@sha256:`) são fixados por cada tarefa de serviço com o valor do dia; sem
  rede no agente, deixar `@sha256:PREENCHER` falha o CA-P2 de propósito e vira item do F.2.
- P0.1: o CA-P2 ("nenhum serviço monta `docker.sock`") foi lido como "nenhum serviço **novo**": o
  `worker-agendado` segue com o socket da central (CA-Y29) até a P2.6 decidir; `migrar` (perfil `ops`)
  fica fora da exigência de `mem_limit`/`cpus`/`cpu_shares` do CA-P1 (a tabela §1 só dá o `cpuset`).
  Serviço novo: acrescente a linha em `ORCAMENTO`/`LOTE` de `tests/deploy/test_compose_inteiro.py`.
