# Design — Ayanami plataforma (o node 2 inteiro como MCP/cérebro)

Requisitos em [requirements.md](requirements.md) (R0–R4, D1–D14, orçamento consolidado). Este
documento diz **onde cada peça roda**, como a CPU é dividida entre o dia e a madrugada, a segurança,
a integração com o que já existe e a ordem de entrega. Contratos (tabelas, payloads, tools com
parâmetros) e números finos ficam para a `spec.md`.

## 1. Princípios

1. **Um cérebro, um endpoint.** Toda capacidade nova é uma tool do `/mcp/` existente ou um job da
   fila procrastinate existente. Serviços de terceiros ficam **atrás** da Ayanami, nunca expostos
   direto ao Pedro.
2. **Dia interativo, noite de lote.** Os núcleos 0–1 nunca recebem lote. A madrugada é sequencial
   e tem checkpoints.
3. **Pull só-leitura.** O node 2 busca, e o node 1 nunca recebe nada. Nenhum container monta
   `docker.sock`.
4. **Local primeiro, molde sempre.** Primeiro o `llm-local`, depois o molde determinístico, por último
   a API no sub-teto "lote". Nada falha em silêncio.
5. **Reuso antes de serviço novo.** Postgres, restic, vigia, eventos, push e ntfy já existem. Serviço
   novo só entra quando é leve e declarativo (Gatus, Beszel, SearXNG, Miniflux).

## 2. Arquitetura

```
                        tailnet (Tailscale) ─ nada público, salvo D8 (erros.dekasis.com.br/envelope)
 ┌─────────────┐  MCP (token mcp)   ┌──────────────────────────── node 2 (8 vCPU / 23 GiB) ──────────────────────────────┐
 │ Claude Code │──────────────────▶ │ ayanami-api  FastAPI + /mcp/ (escopos, auditoria, redator R0.8, gateway D14)         │
 │ (PC/outros) │  hook SessionEnd ▶ │   │  /v1/sessoes-dev  /v1/ops/alerta  /v1/turno  SSE/eventos  push.enviar ─────────┼─▶ ntfy ─▶ celular
 └─────────────┘                    │   ▼                                                                                │   (cond.-celular §6)
 ┌─────────────┐  /v1 (pc/celular)  │ ayanami-pg (pgvector): sessoes_dev, codigo_*, diario, incidentes, email, miniflux  │
 │ Condessa PC │◀──── SSE/turno ───▶│   ▲            ▲                    ▲                                              │─▶ Telegram (D11)
 │ PWA/celular │                    │ worker-rapido  worker-agendado      worker-lento (cpuset 2-7)                      │
 └─────────────┘                    │ (turno, push)  crons: ci, gatus-hb,  código/tree-sitter, e5, trafilatura,           │
                                    │                backup.node1, bom dia marcação audiolivro, pesquisa profunda        │
 GitHub API ◀── PAT só-leitura ─────│                   │  ssh ayanami-ro (command=) ────────────────────────────────────┼──▶ node 1 (tag:prod)
                                    │                   ▼                                                                 │    pg_dump/filas/disco
                                    │ sandbox-db (cópia mascarada)    restic ─▶ repo local (+B2, D7a)                     │    (só leitura, D5)
                                    │ ayanami-voz (Kokoro)            llm-local (llama-server, só 00h–07h, D2)            │
                                    │ searxng+valkey   miniflux   gatus ──▶ HTTP de fora: sites node 1, Vercel, magi./ayanami.
                                    │ beszel hub ◀── agentes: node 2, PC, node 1 (D10)    bugsink (D8)                   │
                                    │ host: ayanami-vigia.timer, ayanami-noite.timer (sobe/desce llm-local), ping D12 ─────┼─▶ healthchecks.io
                                    └───────────────────────────────────────────────────────────────────────────────────┘
```

## 3. Onde cada peça roda

| Peça | Tipo | Onde | Fila / horário (America/Sao_Paulo; crons em UTC na `fila.py`, S5) | Frente |
| --- | --- | --- | --- | --- |
| Perfil "node 2 inteiro" | override `compose.node2-inteiro.yml` | Compose | — | F0 |
| Escopos, `tools/list` filtrado, auditoria, redator | código | `ayanami-api` (`mcp_server.py`, novo `redator.py`) | — | F0 |
| Gateway de terceiros (D14 b) | código + containers `read_only` | `ayanami-api` + Compose | — | F0 |
| ntfy | container | Compose, **do condessa-celular §6** | — | F0 |
| `ci.coletar` | tarefa agendada | `worker-agendado` | `*/5` | F1 |
| `POST /v1/sessoes-dev` + hook | API + script stdlib no repo (`hooks/`) | `ayanami-api` / PC | por sessão | F1 |
| `git.espelhar` | tarefa agendada | `worker-agendado` (só rede e disco) | 00h40 e a cada push visto pelo `ci.coletar` | F1 |
| `codigo.indexar` | tarefa lenta | `worker-lento` | depois do `git.espelhar`, incremental | F1 |
| `sandbox-db` | container `postgres:16` (o major do node 1) | Compose | sempre de pé, restore às 00h | F1/F2 |
| `bugsink` (D8) | container | Compose | — | F1 |
| `backup.node1` → restic → `sandbox.restaurar` | tarefa agendada + lenta | `worker-agendado` (pull, restic) e `worker-lento` (restore, máscara) | 00h00 | F2 |
| Gatus | container, `gatus.yaml` no repo | Compose | contínuo; heartbeats dos jobs | F2 |
| Beszel hub + agente local | container + binário | Compose; agentes no PC e no node 1 (D10) | contínuo | F2 |
| `ops.alerta` (dedup, correlaciona, resume) | API + tarefa rápida | `ayanami-api` / `worker-rapido` | por webhook; correlação de 2–3 min | F2 |
| Tools `ops_*` | código | `ayanami-api` | — | F2 |
| Ping externo (D12) | unidade systemd do host | `deploy/ayanami/host/` | a cada 5 min | F2 |
| `noite.diario`, `noite.aula` | tarefa lenta | `worker-lento` → `llm-local` | 04h10 (depois do fechamento das 04h) | F3 |
| `pesquisar` modo profundo | tarefa lenta (existe, ganha modo) | `worker-lento` | com prazo; a parte local fica na janela | F3 |
| `audiolivro.renderizar` | tarefa lenta | `worker-lento` (marcação) + `ayanami-voz` (Kokoro) | 01h00–04h00 | F3 |
| `noite.bom_dia` | tarefa agendada | `worker-agendado` + `ayanami-voz` | 05h30, pronto até 06h00 | F3 |
| SearXNG + Valkey | containers | Compose | — | F4 |
| Miniflux | container (banco próprio no `ayanami-pg`) | Compose | refresh próprio | F4 |
| `llm-local` | container com `profiles: ["noite"]` | Compose, subido por `ayanami-noite.timer` | 01h45–06h30 | F4 |
| `email.ler` (D7b) | tarefa agendada + lenta | `worker-agendado` (IMAP) / `worker-lento` (classificação) | a cada hora (cabeçalhos); classificação às 02h | F4 |

Não há serviço novo para "alerta", "SRE de bolso", "bom dia" ou "diário": são código e tarefas na
Ayanami que já existe.

## 4. Janela noturna e prioridades de CPU

### 4.1 Divisão da CPU

- **Núcleos 0–1 (interativo):** nenhum container de lote os recebe, porque todo lote tem `cpuset: "2-7"`.
  `ayanami-api`, `worker-rapido`, `ayanami-pg`, `ayanami-voz` (fala em tempo real) e `ntfy` ficam
  sem `cpuset` (podem usar os 8) e com `cpu_shares: 1024`.
- **Prioridade por `cpu_shares`** (é o `cpu.weight` do cgroup e faz o papel do `nice` entre
  containers): 1024 interativo, 512 serviços leves (`worker-agendado`, SearXNG, Miniflux, Gatus,
  Beszel), 256 lote (`worker-lento`, `sandbox-db`, `bugsink`), 128 `llm-local` e runner. Dentro do
  `worker-lento`, os subprocessos pesados (tree-sitter, ffmpeg/Opus) rodam com `os.nice(10)`.
- **Teto:** `cpus` de cada serviço, conforme o orçamento. De dia, o lote soma ≤ 3 vCPU (R0.3): o
  `worker-lento` lê `cpus_dia = 3` / `cpus_noite = 6` do `ayanami.toml` e ajusta as threads (torch,
  onnx, Kokoro) ao começar cada etapa. Não há `docker update` de dentro do container.
- **Cessão:** os jobs longos são divididos em etapas com checkpoint. Entre etapas, consultam a
  profundidade da fila `rapida` (R0.3) e dormem pelo relógio injetado enquanto houver trabalho.

### 4.2 Linha do tempo da madrugada (padrão D3: 00h–07h, lote sequencial)

| Hora | Etapa | CPU | RAM de pico |
| --- | --- | --- | --- |
| 00h00 | `backup.node1`: pull dos dumps → restic (local, + B2) | ~1 | 0,2 GiB |
| 00h15 | `sandbox.restaurar`: staging → máscara → contagens → troca | 2 | 1,5 GiB |
| 00h40 | `git.espelhar` → `codigo.indexar` (incremental; a primeira vez leva 1–2 h) | 4 | 1,5 GiB |
| 01h00 | `audiolivro.renderizar`: próximos 2 capítulos (Kokoro, 4 vCPU) | 4 | 1,5 GiB |
| 01h45 | `ayanami-noite.timer` sobe o `llm-local` (warm-up e health) | — | 3,5 GiB |
| 02h00 | lote LLM: resumo de notícias, classificação de e-mail, resumo das pesquisas profundas | 6 | 3,5 GiB |
| 04h00 | fechamento do dia (existente) | — | — |
| 04h10 | `noite.diario` → `noite.aula` (LLM) + áudio das frases-modelo | 6 | 3,5 GiB |
| 05h30 | `noite.bom_dia`: molde + 1 frase (LLM) → Kokoro → evento "briefing pronto" | 2 | 1,5 GiB |
| 06h30 | o timer derruba o `llm-local`. Etapas atrasadas seguem pelo R4.5 | — | — |
| 07h00 | fim da janela: o lote volta a ≤ 3 vCPU | — | — |

Cada etapa manda um heartbeat ao Gatus (R2.5). Uma etapa atrasada não empurra o bom dia (R3.7):
ele lê o que estiver pronto às 05h30. A ordem coloca backup e restore **antes** de tudo, porque são
o dado mais valioso, e o LLM depois do audiolivro, porque os dois disputam CPU e o Kokoro termina
antes.

### 4.3 Subir e descer o `llm-local`

O `llm-local` usa `profiles: ["noite"]` no Compose. Uma unidade `ayanami-noite.service`/`.timer` em
`deploy/ayanami/host/` (o mesmo padrão do `ayanami-vigia.timer`) roda
`docker compose --profile noite up -d llm-local` às 01h45 e `stop llm-local` às 06h30, e só sobe se
o runner (D9) não estiver ativo, o que garante a exclusão mútua (R0.4). Os workers só enxergam
`http://llm-local:8080/v1` e o health. Não controlam containers.

## 5. Segurança

### 5.1 Rede

- Tudo escuta em `127.0.0.1` ou na rede interna do Compose. O que o Pedro acessa (API, MCP, ntfy,
  UIs do Gatus, Beszel e Miniflux) passa pelo `tailscale serve`, como na central §10.1.
- **Única exceção possível: D8 (c).** `erros.dekasis.com.br` por Caddy, **só** o caminho de envelope
  do Bugsink, com rate-limit, sem UI. O DNS é com o Pedro. Os subdomínios `magi.` e `ayanami.` estão
  liberados, mas continuam só no tailnet.
- SearXNG e Gatus fazem requisições de saída com o IP da VPS, sem entrada nova.

### 5.2 Node 1 (D5): porta única só-leitura

- O node 1 entra no tailnet com `tag:prod`. A ACL libera só `tag:ayanami → tag:prod:22`.
- `ayanami-ro` com `restrict,command="/usr/local/sbin/ayanami-ro"` no `authorized_keys`. Verbos em
  lista branca: `pg_dump <projeto>`, `filas <projeto>`, `disco`. Argumento livre é ignorado; não
  há shell, pty nem port-forward.
- Papel Postgres `ayanami_ro` com `pg_read_all_data`. RabbitMQ com tag `monitoring`.
- A chave privada fica num arquivo de segredo montado só no `worker-agendado` (`0400`). O node 1 nunca
  recebe credencial do node 2.
- **Risco residual aceito pela D5:** quem comprometer o node 2 **lê** os dumps, mas não altera o node 1.
  Mitigações: o dump bruto é apagado depois do restore, o restic cifra em repouso, e o `sandbox-db`
  só tem dado mascarado (a staging é derrubada depois da troca).

### 5.3 Tokens, escopos e auditoria (estende a central §4.5 e §10.3)

| Escopo novo | Tools | Padrão (D13) |
| --- | --- | --- |
| `dev-ler` | `ci_*`, `pr_status`, `ci_deploys`, `sessoes_*` | token `mcp` |
| `codigo-ler` | `codigo_buscar`, `codigo_simbolo`, `codigo_semelhante` | token `mcp` |
| `ops-ler` | `ops_status`, `ops_incidentes`, `ops_backup`, `ops_filas` | `mcp`, `pc`, `celular` |
| `web` | `web_buscar`, `rss_novidades`, `rss_assinar` | `mcp`, `pc`, `celular` |
| `pessoal-ler` | `memoria_diario` | `pc`, `celular` |
| `prod-ler` | `sql_schema`, `sql_ler`, `prod_erros` | desligado |
| `email-ler` | `email_buscar`, `email_importantes` | desligado |

- Gravação em `sessoes_dev` só com o token `pc` (escopo de escrita `sessoes-escrever`, só HTTP, sem tool MCP).
- O redator (R0.8) roda na **saída** de toda tool com texto de terceiros e na **entrada** do resumo
  de incidentes, antes de qualquer LLM.
- Segredos novos em `/opt/ayanami/.env` (`0600`): `GITHUB_PAT_RO`, `NODE1_SSH_KEY` (como arquivo),
  `IMAP_*`, `MINIFLUX_*`, `SEARXNG_SECRET`, `BESZEL_*`, `HC_PING_URL`. Os logs registram só os nomes.

### 5.4 Dados

`sql_ler` lê só o `sandbox-db`. Ninguém consulta a produção ao vivo. As tools `ops_*` devolvem
agregados. O corpo de e-mail não é guardado. Diário e e-mail só passam pelo `llm-local`, salvo
opt-in. Tudo vai ao restic cifrado, menos os caches (SearXNG/Valkey, modelos, índice de código, que é
reconstruível). Os espelhos git **entram**, porque são o backup dos repos.

## 6. Integração com o que já existe

| Existente | Como este SDD usa | Não faz |
| --- | --- | --- |
| `BudgetNuvem` (`ayanami/custos.py`) | Ganha o sub-teto **`lote`** (D4: US$ 1) ao lado do `nuvem` (US$ 2), com `ensure_allowed`/`record` por tarefa. O gasto do `llm-local` conta como zero | não cria outro contador |
| Fila procrastinate (`ayanami/fila.py`, `Def` com fila, lock e cron em UTC) | Novas linhas `Def`: `ci.coletar`, `git.espelhar`, `codigo.indexar`, `backup.node1`, `sandbox.restaurar`, `noite.*`, `audiolivro.renderizar`, `email.ler`. Locks por recurso (`sandbox`, `llm`, `kokoro`) serializam a madrugada | não cria fila nova; `lenta` já é a de lote |
| Backups Y4.2 (`workers/backup.py`, restic, `restore_teste`) | `backup.node1` reusa o repositório e a retenção. Sem B2, pula com aviso (comportamento atual) | não cria outro repositório restic |
| Vigia (`deploy/ayanami/vigia/`) | Continua no host. Passa a mandar webhook a `/v1/ops/alerta` e ganha limiares por serviço (R0.10) | não é substituído pelo Beszel; o Beszel cobre histórico e o node 1 |
| Eventos/SSE e Web Push (`eventos.py`, `push.py`) | Incidentes, "briefing pronto", "CI vermelho" e "aula pronta" viram eventos. O push segue o caminho atual | — |
| ntfy | O do [condessa-celular design §6](../condessa-celular/design.md) (`binwiederhier/ntfy`, `deny-all`, token de escrita só para a Ayanami). Este SDD só o põe no perfil e usa prioridade por criticidade | não define um segundo ntfy nem outro formato |
| `telegram.py` | Reserva da entrega "produção fora" quando houver token (D11) | — |
| `workers/noticias.py`, `embeddings.py` | O Miniflux vira fonte. O e5-small é reusado em `sessoes_dev`, `diario`, `email` e, no início, em `codigo_*` (troca para modelo de código só se o A/B mostrar ganho) | não duplica a clusterização |
| Tarefa `pesquisar` (`workers/agente.py`) | Ganha o modo profundo com prazo, SearXNG e `llm-local` | — |
| Audiolivro do PC (Kokoro + Qwen) | O código de marcação vira worker. O elenco Kokoro reusa o `ayanami-voz` | o PC deixa de sintetizar durante a leitura |
| Ponte de turno PC↔celular, presença | Gatilho "primeira presença do dia" para o bom dia e o marcador do audiolivro | — |
| `compose.node2.yml` (perfil enxuto Y1.0b) | Substituído pelo `compose.node2-inteiro.yml` (D1). O enxuto fica no repo para o caso de o Minecraft voltar | — |

## 7. Ordem de entrega

Ordem por risco ÷ esforço, sem esperar credenciais do Pedro onde não for preciso.

| Passo | Frente | Entrega | Depende de |
| --- | --- | --- | --- |
| 1 | F0 | Perfil "node 2 inteiro" + `cpuset`/`cpu_shares` + escopos novos e `tools/list` filtrado + redator + limiares do vigia + ntfy no perfil | D1 |
| 2 | F2a | Gatus (`gatus.yaml`) + Beszel (node 2 e PC) + `/v1/ops/alerta` com incidentes + `ops_status`/`ops_incidentes` | — |
| 3 | F1a | `ci_*` + hook e `sessoes_*` | PAT só-leitura |
| 4 | F4a | SearXNG + `web_buscar` → Miniflux + `rss_*` | OPML (opcional) |
| 5 | F3a | Bom dia **só com molde** (clima, notícias, ops, placar) + Kokoro + heartbeat | 2, 4 |
| 6 | F2b | `backup.node1` + `sandbox.restaurar` com máscara + `ops_backup`/`ops_filas` + ping externo | D5, D7a, D12 |
| 7 | F1b | `git.espelhar` + `codigo_*` → `sql_ler`/`sql_schema` | 6 (para `sql_ler`), D6 |
| 8 | F4b | `llm-local` + `ayanami-noite.timer` + `llama-bench` + A/B (R4.4) + sub-teto `lote` | D2, D3, D4 |
| 9 | F3b | Diário + aula do dia + pesquisa profunda + frase de humor no bom dia | 8 |
| 10 | F3c | Audiolivro no node 2 + player no PWA | 8 (marcação) |
| 11 | F4c / F1c | E-mail IMAP (D7b) · Bugsink (D8) · runner (D9) · gateway (D14) | as respectivas D |

## 8. Riscos

| Risco | Mitigação |
| --- | --- |
| A vCPU da Contabo rende menos que o esperado e o lote não cabe na janela | `llama-bench` antes (passo 8). Etapas com prioridade (backup > bom dia > diário > resto). Adiar para a noite seguinte (R4.5) |
| OOM com os limites somando ~18 GiB | Lote sequencial com locks; `memswap_limit` só no lote; alerta a 90% (R0.10) |
| Dump de cliente no node 2 | D5 explícita, máscara antes de servir, bruto apagado, restic cifrado |
| Prompt injection por log, e-mail, página web ou descrição de tool de terceiro | Redator, texto marcado como não confiável, tools de escrita fora do alcance, digest no gateway |
| Alerta virar spam | Dedup e correlação, silêncio (D11), teto de cenas da persona (R3.6) |
| Node 1 e node 2 no mesmo provedor | Ping externo (D12) e B2 (D7a) |
| SearXNG bloqueado por captcha | Sem Google; rotação de motores; Gemini com Google Search na cota grátis como alternativa |

## 9. Spikes antes de implementar

- **S1:** `llama-bench -t 6` com Qwen3-4B Q4_K_M no node 2 (tok/s de prompt e de geração) e Kokoro
  em 4 vCPU (fator de tempo real). Isso fecha a linha do tempo do §4.2.
- **S2:** tamanho dos dumps do node 1 e tempo de `pg_restore` mais máscara (pedir o número ao Pedro,
  sem tocar no node 1).
- **S3:** e5-small contra `jina-embeddings-v2-base-code` em 30 consultas de código dos repos do Pedro.
- **S4:** formato do hook `SessionEnd` do Claude Code (campos disponíveis e tempo-limite) na versão
  instalada.
