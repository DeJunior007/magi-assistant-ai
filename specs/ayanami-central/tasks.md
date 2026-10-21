# Tarefas — Ayanami central (nuvem da Condessa, casa e celular)

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **um agente** com janela de **até 128k tokens** (teto duro), salvo as marcadas
**precisa do Pedro**. Várias rodam em paralelo (campo *Paralelo*); o orquestrador (Pedro ou a sessão
principal do Claude Code) só lança uma tarefa quando todas as de *Depende de* estão no `main`.

Este arquivo cobre a **nuvem** (Y0–Y6), a **casa** (C1.x `magi-casa` e TVs, C2.x intents e
ferramentas `tv.*`), o **celular** (P1.x PWA, P2.x Web Push) e o **fechamento** (F.x validação ao
vivo e documentação), num grafo só.

**Ordem sugerida de ondas** (cada onda roda junta; a seguinte começa quando a anterior está no
`main`; *Pedro* = precisa do Pedro): **1** Y0.1, Y0.2 · **2** Y0.3, Y0.5, Y0.6, Y0.7, Y1.1, Y1.3,
Y2.4, Y4.1, C1.1, C2.1 · **3** Y0.4, Y1.2, Y2.1, Y3.3, Y6.2, C1.1b, C1.1c, C1.2, C1.3, C1.4 ·
**4** Y1.4, Y2.2, Y3.1, C1.5, C2.2, Y1.5 *Pedro* · **5** Y2.3, Y3.2, Y3.5, Y3.6, Y5.1, Y6.1, C1.6,
Y1.6 *Pedro*, C1.S2 *Pedro* · **6** Y3.4, Y4.2, Y6.3, Y6.6, P1.1, P2.1, Y0.8 *Pedro* · **7** Y6.4,
Y6.5, P1.3, P1.4, Y4.3 *Pedro* · **8** P1.2, P2.2 · **9** P1.S4 *Pedro* · **10** F.1 *Pedro* → F.2.

**Decisões:** valem os padrões D1a–D15a do requirements até o Pedro decidir (spec, cabeçalho) e as
DS1–DS19 da spec. Duas correções ao copiar da spec para o código (valem acima da §9.2): `[nuvem]
stt_modelo` = `"gpt-transcribe"` (o valor real do `config.example.toml` do PC, não
`gpt-4o-mini-transcribe`); `[noticias] dim` = o `NEWS_DIM` real do PC (`magi/memory/migrate.py`,
padrão `768`; o `1536` da §9.2 é só exemplo). Os spikes (Y0.4–Y0.8) podem mudar nomes da spec §4/§8/§6;
quando mudarem, o próprio spike corrige o trecho da spec antes das tarefas que dependem dele.

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*). Design por `design §`, spec por `spec §`,
   requisitos por `R`/`RNF-A`/`D`. A `spec.md` tem ~1700 linhas: **nunca leia inteira**; use
   `grep -n "^## \|^### " specs/ayanami-central/spec.md` e leia só os intervalos das seções citadas.
2. **Orçamento planejado ≤ 50–60k tokens**; o resto da janela de 128k é margem. Perto de **90k**:
   pare, faça commit do que está verde e anote o que faltou em *Sobras* (fim desta lista).
3. **Contratos primeiro:** use os tipos de `magi/elo/` (Y0.1), `ayanami/config.py` (Y0.2), o banco
   da Y0.3 e os stubs com docstring "dono: <ID>" (Y0.2, Y2.1, Y3.1, Y6.2, C1.1, P1.1). Não leia o código de
   outras tarefas além das assinaturas.
4. **Só os arquivos do campo *Escreve*.** Precisou de outro? Pare e anote em *Sobras*. Tarefas
   paralelas têm *Escreve* disjunto; onde dois IDs tocam o mesmo arquivo, o campo diz o trecho.
5. **Arquivos grandes por trecho** (`grep -n` + leitura por intervalo): nunca leia inteiros
   `magi/core/turn.py`, `magi/core/service.py`, `magi/core/assemble.py`, `magi/agent/graph.py`,
   `magi/common/contracts.py`, `magi/news/__main__.py`, `magi/memory/migrations/001_init.sql`,
   `specs/ayanami-central/spec.md`.
6. **Testes curtos:** `uv run pytest -q -x tests/<área>` (`tests/elo`, `tests/ayanami`,
   `tests/deploy`, ou o arquivo da tarefa) e `uv run ruff check <seus arquivos>`. Relógio, `rng`,
   `sleep` e executor de comandos (`docker`, `restic`, `ffmpeg`, `pg_dump`) **sempre injetados**;
   nada de `sleep` real acima de 50 ms.
7. **Nada ao vivo nos testes:** sem rede real (HTTP/WS por ASGI em memória ou servidor falso em
   `127.0.0.1` de porta efêmera), sem TV real, sem LLM pago nem chave de API (provedores falsos),
   sem modelo baixado (Kokoro/faster-whisper/fastembed falsos), fila em `procrastinate.testing.
   InMemoryConnector`. Testes marcados `pg` usam **só** o contêiner descartável
   `ayanami-pg-teste` (`127.0.0.1:54340`, subido por `deploy/ayanami/pg-teste.sh`) e pulam sem
   `AYANAMI_TEST_DSN`; o fixture recusa DSN na porta `54329` ou com base `magi`.
8. **Proibições** (código, script, teste e comando do agente):
   - nada de `qdbus`/`gdbus` nem D-Bus para KGlobalAccel/KWin;
   - nada de `docker compose down`, `docker volume rm`, `rm` em volume, `DROP`, `TRUNCATE` nem
     `pg_restore --clean` no `magi-pg`; contra o `magi-pg` só `pg_dump` e `SELECT count(*)`
     (spec §7.3), e migração do PC só aditiva;
   - **nada no node 1** (MultiVideos, wedding, gold-crm): não ler, não instalar, não rotear, não
     reaproveitar nada de lá sem o Pedro pedir;
   - **nada de `ssh`, `scp`, `docker context` nem deploy real no node 2 por agente**: a infra é
     escrita como código (`deploy/ayanami/`) e aplicada pelo Pedro nas tarefas "precisa do Pedro";
   - segredos (`.env`, tokens `ayn_…`, `sk-…`, senha do restic, chaves B2/VAPID/Telegram) **nunca**
     em git, log, teste, mensagem de commit ou *Sobras*; exemplos só com nomes e valores falsos.
9. **Uma tarefa = um commit** direto no `main`, mensagem com o ID (`Y2.1: tokens, pareamento e
   saúde`); sem `--amend`, sem `rebase`, sem `push` (o Pedro empurra).
10. **O PC é o piso:** com `[ayanami]` ausente no `config.toml` o `magi-core` sobe e todos os testes
    atuais de `tests/core/`, `tests/agent/`, `tests/news/`, `tests/memory/` passam sem mudar
    asserção.
11. **Casa e celular nos testes:** nas C1.x, **nunca** TV real nem multicast real: servidores
    HTTP/WS falsos em `127.0.0.1:0` (`aiohttp.test_utils`), `AndroidTVRemote`/`send_magic_packet`/
    keyring falsos, respostas SSDP/mDNS injetadas, relógio injetado, `tmp_path` para
    `~/.config/magi`, `~/.local/share/magi/casa` e `~/.local/state/magi`. JS do PWA: `node --test
    'tests/ayanami/pwa/*.mjs'` (o Node 24 não aceita o diretório) com `fetch`/`MediaRecorder`/`caches` falsos, **sem navegador**. A casa roda
    **sem** a Ayanami: C1.1–C1.5 e C2.x não esperam Y1/Y2 (só a C1.6 usa o `EloCliente` da Y2.4).

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~9k
(ler por R), `design.md` ~12k (ler por §), `spec.md` ~45k (**só por §**: §1 ~6k, §2 ~4k, §3 ~3k,
§4 ~3k, §5 ~3k, §6 ~3k, §7 ~2k, §8 ~2k, §9 ~3k), `001_init.sql` ~4k, `magi/news/__main__.py` ~3k.

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
Y0.1 elo ─┬─ Y2.4 EloCliente ─┬─ C1.6 saída da casa (+C1.1b, C1.1c; depois da C1.5) ──────┐
   │      │                   └─ Y6.2 RemoteLink/Ponte ─┬─ Y6.5 reconciliação (+Y6.3)     │
   │      └─ Y0.6 S6 (local) ──────────┘                └─ Y6.6 PC: eventos/custos/       │
   │                                                         confirma/pareamento (+Y6.1)  │
   ├─ C1.1 casa (+Y0.2) ─┬─ C1.1b executor ─┐                                             │
   │                     ├─ C1.1c servir ───┤                                             │
   │                     ├─ C1.2 Samsung ───┼─ C1.5 descoberta ─┬─ C1.6 (acima)           │
   │                     ├─ C1.3 Roku ──────┤                   └─ C1.S2 TVs reais ───────┤
   │                     └─ C1.4 Android ───┘                       (Pedro; +C2.2)        │
   └─ C2.1 intents/frases tv.* ── C2.2 TvActions/tv_* ─┬─ C1.S2 (voz no PC)               │
                                                       └─ Y6.3 (tv_* no modo nuvem)       │
Y0.2 esqueleto ─┬─ Y0.3 banco ─┬─ Y0.4 S5 ── Y3.1 fila ─┬─ Y3.2 notícias nuvem            │
   │            │              │       (+Y2.1)          ├─ Y3.4 agente (+Y2.3)            │
   │            │              │                        ├─ Y3.5 voz Kokoro                │
   │            │              ├─ Y3.3 news-sync (PC)   ├─ Y3.6 STT + embeddings          │
   │            │              │                        ├─ Y4.2 backup nuvem (+Y2.3)      │
   │            │              │                        └─ P2.1 push servidor (+Y2.3)     │
   │            │              └─ Y2.1 API base ─┬─ Y2.2 WS/hub/casa ─┬─ Y2.3 SSE/feed    │
   │            │                                │                    ├─ Y5.1 MCP         │
   │            │                                │                    │  (+Y0.5, Y3.1)    │
   │            │                                │                    └─ Y6.1 Budget      │
   │            │                                │                       (+Y3.1)          │
   │            │                                │   Y6.1 + Y2.2 + Y3.1 + C2.2 ─ Y6.3     │
   │            │                                │   Y6.3 + Y2.3 ─ Y6.4 rota do turno     │
   │            │                                └─ P1.1 PWA base (+Y2.3) ─┬─ P1.2 (+Y6.4)│
   │            │                                                          ├─ P1.3        │
   │            │                                                          └─ P1.4 ─ P2.2 │
   │            │                                                    P2.1 ────────────┘   │
   │            │                 P1.2, P1.3, P2.2, C1.6, Y6.4, Y1.6 ─ P1.S4 (Pedro) ─┤   │
   │            ├─ Y1.1 compose ─┬─ Y1.2 host/runbook ── Y1.5 node 2 (Pedro)          │   │
   │            │                ├─ Y1.4 CI (+Y1.2)        │                          │   │
   │            ├─ Y1.3 vigia    └────────────────────── Y1.6 1º deploy (Pedro) ──────┤   │
   │            │                         (+Y1.3, Y1.5, Y2.1, Y3.1)                   │   │
   │            ├─ Y4.1 magi-backup (PC) ─────────────── Y4.3 B2/restore (Pedro) ─────┤   │
   │            ├─ Y0.7 S1 script ──────────────────── Y0.8 S1 node 2 (Pedro) ───────┤   │
   │            └─ Y0.5 S3 (local) ── Y5.1                                            ▼   ▼
   └─ C1.1 (pyproject; ver acima)                           F.1 validação (Pedro) ◀── tudo
                                                            F.1 ── F.2 documentação
```

**Setas** (valem acima do desenho; "Depende de" de cada tarefa é a fonte): `C1.1 ← Y0.1, Y0.2` ·
`C1.1b/C1.1c/C1.2/C1.3/C1.4 ← C1.1` · `C1.5 ← C1.1b, C1.1c, C1.2, C1.3, C1.4` · `C1.6 ← C1.1b,
C1.1c, C1.5, Y2.4` (Y2.2 só para a prova ao vivo) · `C1.S2 ← C1.5, C2.2` · `C2.1 ← Y0.1` ·
`C2.2 ← C2.1` · `Y6.3 ← Y6.1, Y2.2, Y3.1, C2.2` · `P1.1 ← Y2.1, Y2.3` · `P1.2 ← P1.1, Y6.4` ·
`P1.3/P1.4 ← P1.1` · `P2.1 ← Y2.3, Y3.1` · `P2.2 ← P1.4, P2.1` · `P1.S4 ← P1.2, P1.3, P2.2, C1.6,
Y6.4, Y1.6` · `F.1 ← Y1.6 e todas as Y*, C*, P*` · `F.2 ← F.1`. **Todo C e P depende de Y0.1**
(direto ou por cadeia).

**Arquivos com mais de um dono** (nunca na mesma onda; cada um só no trecho dito no *Escreve*):
`pyproject.toml`/`uv.lock` (Y0.2 → C1.1) · `ayanami/cli.py` (só Y0.2) · `ayanami/api/app.py`
(Y2.1 → Y5.1) · `ayanami/api/push.py` (stub Y2.1 → P2.1) · `ayanami/workers/push.py` (stub Y3.1 →
P2.1) · `ayanami/deps.py` (Y3.1 → Y6.1) · `ayanami/api/tarefas.py` (Y3.1 → Y3.6) ·
`magi/core/turn.py` e `magi/core/assemble.py` (Y6.2 → C2.2) · `config.example.toml` (Y3.3 → C2.2) ·
`magi/core/phrases.yaml`, `intents.yaml`, `router.py`, `magi/common/contracts.py` (só C2.1) ·
`magi/casa/servir.py` (C1.1c → C1.5 → C1.6) · `magi/casa/__main__.py` (C1.1 → C1.1c) ·
`magi/casa/cli.py` (C1.1 → C1.5) · `ayanami/pwa/gravador.js` (P1.1 → P1.2) · `ayanami/pwa/sw.js`
(P1.1 → P2.2) · `ayanami/pwa/telas/ajustes.js` (P1.1 → P1.4 → P2.2) · `specs/ayanami-central/spec.md`
(spikes, cada um só nas suas §). `tests/hud/conftest.py`: nenhuma tarefa escreve.

---

## Fase Y0 — Contratos e spikes

- [x] **Y0.1 Contrato do elo** — pacote puro `magi/elo/` (sem I/O de rede): `ids.py` (ULID [DS2],
  gerar/validar/binário de 16 bytes), `mensagens.py` (`Tipo`, `Envelope`, os 12 corpos, `encode`/
  `decode`, `EloError` com `codigo`, `NOME_RE`, limites de tamanho, campo extra ignorado),
  `quadros.py` (`QuadroTipo`, `Quadro`, `encode_quadro`/`decode_quadro`, cabeçalho de 18 bytes,
  carga ≤ 8174), `converte.py` (`pedido_de_request`, `request_de_pedido`, `resultado_de_action`,
  `card_de_cardmsg` ↔ `contracts.py`), `receptor.py` (cache dos últimos 512 ids com resposta
  guardada, contador de 10 inválidos/60 s → fechar 1008, relógio injetado), `schema.py`
  (`python -m magi.elo.schema` → JSON Schema) e o arquivo gerado. *(R1, design §3.2, spec §1)*
  - Lê: design §3.2; spec §1 inteira (linhas ~60–310) e a tabela DS (DS2, DS19); `contracts.py` por trecho (`grep -n "class ActionRequest\|class ActionResult\|class CardMsg\|class PcmFormat"`)
  - Escreve: `magi/elo/__init__.py`, `magi/elo/ids.py`, `magi/elo/mensagens.py`, `magi/elo/quadros.py`, `magi/elo/converte.py`, `magi/elo/receptor.py`, `magi/elo/schema.py`, `ayanami/app/elo.schema.json`, `tests/elo/__init__.py`, `tests/elo/test_mensagens.py`, `tests/elo/test_quadros.py`, `tests/elo/test_converte.py`, `tests/elo/test_receptor.py`
  - Depende de: —
  - Orçamento: ~55k
  - Pronto: CA-Y1, CA-Y2, CA-Y3, CA-Y4, CA-Y5 verdes; schema gerado é determinístico (teste compara com o arquivo); `ruff` limpo; nenhum import de rede em `magi/elo/{ids,mensagens,quadros,converte,receptor,schema}.py` (teste por `ast`).
  - Paralelo: Y0.2

- [x] **Y0.2 Esqueleto da Ayanami e config** — pacote `ayanami/` com `config.py` (`ler(caminho) ->
  AyanamiConfig`, dataclasses `frozen`, `ConfigError` com caminho da chave, faixas e regras da §9.2,
  [DS8]; leitura dos segredos do `.env` só por nome, com lista `faltando`), `relogio.py` (`Relogio`
  protocolo + real + falso para testes), `cli.py` (`ayanami <sub>` com `argparse`: `migrar`,
  `worker`, `batimento`, `voz`, `dispositivo`, `backup`, `push` — cada um despacha, por import preguiçoso, para a função `cli(args)` do
  módulo dono: `ayanami.migrar` (Y0.3), `ayanami.dispositivos_cli` (Y2.1), `ayanami.worker` (Y3.1),
  `ayanami.voz.servidor` (Y3.5), `ayanami.workers.backup` (Y4.2), `ayanami.push` (P2.1, `ayanami push
  chaves`); módulo ausente → erro claro com
  "dono: <ID>"; depois da Y0.2 ninguém mais edita a `cli.py`), `deploy/ayanami/ayanami.example.toml`
  (§9.2 com as duas correções do cabeçalho), `deploy/ayanami/env.example` (só nomes, valores
  falsos); `pyproject.toml`: pacote `ayanami` no wheel, scripts `ayanami`, `magi-news-sync`,
  `magi-backup`, marcador `pg`, dependências da nuvem num grupo opcional `ayanami` (`fastapi`,
  `uvicorn`, `procrastinate==3.10.0`, `psycopg[pool]`, `mcp==2.3.0`, `httpx`, `websockets`,
  `pywebpush==2.5.0` — traz o `py-vapid` — para a P2.1) e as
  pesadas num grupo `ayanami-ml` (`kokoro-onnx==0.4.7`, `onnxruntime==1.31.0`,
  `faster-whisper==1.2.1`, `fastembed==0.9.0`) que os testes nunca importam no topo; `uv.lock`;
  `.gitignore` com `deploy/ayanami/.env` e `deploy/ayanami/dados/`. *(R10, RNF-A, spec §9.1–§9.2)*
  - Lê: spec §9.1, §9.2, tabela DS (DS1, DS8, DS9); design §11; `pyproject.toml`; `config.example.toml` linhas 25–35; `magi/memory/migrate.py` linhas 1–40
  - Escreve: `ayanami/__init__.py`, `ayanami/config.py`, `ayanami/relogio.py`, `ayanami/cli.py`, `deploy/ayanami/ayanami.example.toml`, `deploy/ayanami/env.example`, `pyproject.toml`, `uv.lock`, `.gitignore`, `tests/ayanami/__init__.py`, `tests/ayanami/test_config.py`
  - Depende de: —
  - Orçamento: ~40k
  - Pronto: CA-Y28 verde (5 casos + exemplo válido); `uv sync` resolve com e sem os grupos; `ayanami --help` lista os subcomandos; suíte atual inteira verde (`uv run pytest -q`); `ruff` limpo.
  - Paralelo: Y0.1

- [x] **Y0.3 Banco da Ayanami e migração do PC** — `ayanami/migrations/001_base.sql` e
  `002_noticias.sql` (spec §3, cópia das `news_*`/`franchise_prefs`/`progress` do `001_init.sql`
  com o mesmo renderizador de `{{NEWS_DIM}}`, `uid`, `atualizado`, índice e gatilho);
  `ayanami/db.py` (pool `psycopg`, `Db` protocolo mínimo, transação); `ayanami/migrar.py`
  (`schema_migracoes`, idempotente, `cli(args)` do `ayanami migrar`); no PC,
  `magi/memory/migrations/005_ayanami_sync.sql` [DS5] (aditiva: `ayanami_uid`, `origem_uid`);
  `deploy/ayanami/pg-teste.sh` (sobe/derruba **só** o contêiner `ayanami-pg-teste`, porta 54340,
  `--rm`); fixture `pg` em `tests/ayanami/conftest.py` (cria uma base por sessão dentro do
  contêiner de teste, aplica 001–002; outra base com as migrações do PC para a Y3.3). *(R1, R2, spec §3)*
  - Lê: spec §3 inteira (linhas ~397–530), DS3, DS5; `magi/memory/migrate.py` por trecho (`grep -n "def \|NEWS_DIM"`); `001_init.sql` por trecho (`grep -n "CREATE TABLE news_\|franchise_prefs\|progress"`); `tests/memory/test_migrate.py` por trecho (`grep -n "004\|len("`)
  - Escreve: `ayanami/migrations/001_base.sql`, `ayanami/migrations/002_noticias.sql`, `ayanami/db.py`, `ayanami/migrar.py`, `magi/memory/migrations/005_ayanami_sync.sql`, `tests/memory/test_migrate.py` (só as contagens da 005), `deploy/ayanami/pg-teste.sh`, `tests/ayanami/conftest.py`, `tests/ayanami/test_migrar.py`
  - Depende de: Y0.2
  - Orçamento: ~50k
  - Pronto: CA-Y11 e CA-Y12 verdes no `ayanami-pg-teste`; sem `AYANAMI_TEST_DSN` os testes `pg` pulam e o resto passa; `tests/memory/` verde (marcador `db` como hoje); o fixture recusa a porta 54329.
  - Paralelo: Y1.1, Y1.3, Y4.1, Y0.7

- [x] **Y0.4 Spike S5 — `procrastinate` 3.10** — script local contra o `ayanami-pg-teste`:
  `retry_stalled_jobs` (nome exato), `cancel_job_by_id_async(abort=True)` com parada ≤ 10 s em
  tarefa async e síncrona (`should_abort`), `queueing_lock` + `AlreadyEnqueued`, `on_job_status`,
  job de 30 min sobrevivendo a reinício do worker (simulado: matar e subir o processo do worker
  local), LISTEN/NOTIFY chegando a um ouvinte, cron de `periodic` com `TZ=America/Sao_Paulo`
  [DS9]. Registra o resultado e corrige a spec §4/§17 se algum nome mudar. *(design §14 S5, spec §4, §17)*
  - Lê: design §4.2, §14; spec §4 inteira, §17 (linha S5); docs da lib por `uv run python -c "import procrastinate, inspect; …"` (não pela rede)
  - Escreve: `spikes/ayanami_s5_procrastinate.py`, `docs/perf/ayanami-s5.md`, `specs/ayanami-central/spec.md` (só §4 e a linha S5 da §17, se mudar)
  - Depende de: Y0.3
  - Orçamento: ~35k
  - Pronto: cada pergunta da linha S5 da §17 com "confirmado"/"mudou para …" e a evidência (saída do script); spec atualizada quando mudou.
  - Paralelo: Y0.5, Y0.6, Y2.1, Y3.3

- [x] **Y0.5 Spike S3 — MCP 2.3 (parte local)** — `MCPServer` montado num FastAPI em `/mcp`
  (`streamable_http_app`, `streamable_http_path="/"`), `TokenVerifier` com escopos,
  `get_access_token()` dentro da tool, `AuthSettings` com `required_scopes`; cliente MCP da própria
  lib contra o ASGI em memória e contra `uvicorn` em `127.0.0.1` (porta efêmera) listando e chamando
  tools com tokens de escopos diferentes. A parte "pelo tailnet" (`claude mcp add`, `mcp-remote` no
  Desktop) fica na Y1.6. *(design §4.5, §14 S3, spec §8, §17)*
  - Lê: design §4.5, §14; spec §8 (só o bloco de código e as notas), §17 (linha S3)
  - Escreve: `spikes/ayanami_s3_mcp.py`, `docs/perf/ayanami-s3.md`, `specs/ayanami-central/spec.md` (só o bloco de código da §8 e a linha S3 da §17, se mudar)
  - Depende de: Y0.2
  - Orçamento: ~30k
  - Pronto: montagem, verificador e escopos confirmados ou a alternativa da §17 ("processo/porta própria") escolhida e anotada; spec atualizada.
  - Paralelo: Y0.3, Y0.4, Y0.6, Y0.7

- [x] **Y0.6 Spike S6 — turno remoto (parte local)** — no PC, sem Ayanami: `ffmpeg` webm/opus →
  PCM 16 kHz (prazo ≤ 2 s para 15 s de áudio) e PCM 24 kHz → ogg/opus 32k em streaming; achar o
  ponto do `on_turn_done` [DS6] no `TurnMachine` (depois do `compose`, antes de falar) e como um
  segundo `SatelliteLink` entra no `CoreService` (PTT e texto pronto), com um protótipo de
  `RemoteLink` falso no script. Mede tempos locais; o p90 no 4G fica para F.x. *(design §7.2, §14 S6, spec §6.2–§6.3, §17)*
  - Lê: design §7.2, §14; spec §6.2, §6.3, §17 (linha S6); `turn.py` por trecho (`grep -n "class TurnDeps\|class TurnMachine\|def _deliver\|compose"`); `service.py` por trecho (`grep -n "SatelliteLink\|def _on_satellite\|TurnMachine("`); `contracts.py` por trecho (`grep -n "class SatelliteLink\|class SatelliteHello\|WakeSource"`)
  - Escreve: `spikes/ayanami_s6_turno.py`, `docs/perf/ayanami-s6.md`, `specs/ayanami-central/spec.md` (só §6.3 e a linha S6 da §17, se mudar)
  - Depende de: Y0.1
  - Orçamento: ~40k
  - Pronto: tempos de transcodificação medidos (p50/p90 de 20 rodadas); linha exata do gancho e do registro do satélite `celular` anotadas no doc para a Y6.2; spec atualizada se o gancho mudar.
  - Paralelo: Y0.3, Y0.4, Y0.5, Y0.7

- [x] **Y0.7 Spike S1 — script de bancada** — `spikes/ayanami_s1_bancada.py` que mede, sem rede:
  Kokoro int8 `pf_dora` (RTF em 10 frases pt-BR), faster-whisper `small` int8 `cpu_threads=4` (RTF
  e RAM de pico num áudio de 5 min), fastembed e5-small (vazão em lotes de 64) e imprime uma tabela;
  baixa os modelos só para `--modelos <dir>`. Roda uma vez no PC para ter a linha de base. A rodada
  no node 2 é a Y0.8. *(design §4.4, §14 S1, spec §5.4–§5.6, §17)*
  - Lê: design §4.4, §14; spec §5.4, §5.5, §5.6, §17 (linha S1)
  - Escreve: `spikes/ayanami_s1_bancada.py`, `docs/perf/ayanami-s1.md` (só a seção "PC")
  - Depende de: Y0.2
  - Orçamento: ~30k
  - Pronto: tabela do PC registrada; o script roda com `uv run --group ayanami-ml` e sai com código ≠ 0 se faltar modelo, sem baixar nada sem `--modelos`.
  - Paralelo: Y0.3, Y0.4, Y0.5, Y0.6

- [ ] **Y0.8 Spike S1 no node 2** — **precisa do Pedro (não implementar por agente).** Rodar o
  script da Y0.7 no node 2 (dentro da imagem da Y1.1) e o Compose parado/ocioso por 30 min
  (`docker stats`, repouso dentro do RNF-A6); colar a tabela em `docs/perf/ayanami-s1.md`
  (seção "node 2"); se RTF ou RAM estourarem, o agente da sessão principal ajusta spec §5.4/§5.5/
  §9.3 (limites da fila `lenta`) conforme a §17.
  - Lê: spec §17 (linha S1); `docs/perf/ayanami-s1.md`
  - Escreve: `docs/perf/ayanami-s1.md` (seção "node 2"), `specs/ayanami-central/spec.md` (§5.4, §5.5, §9.3, só se mudar)
  - Depende de: Y0.7, Y1.6
  - Orçamento: ~15k (sessão)
  - Pronto: números do node 2 registrados; decisão "Kokoro serve de reserva" sim/não anotada.
  - Paralelo: Y4.3

## Fase Y1 — Infra como código

- [x] **Y1.1 Imagem e Compose** — `deploy/ayanami/Dockerfile` (multi-stage com `uv`, usuário não
  root, `TZ`, grupo `ayanami`; variante com `ayanami-ml` para `worker-lento`/`ayanami-voz` por
  `--build-arg`), `deploy/ayanami/compose.yml` exatamente como a §9.3 (7 serviços, `migrar` em
  `profiles: ["ops"]`, limites, healthchecks, volumes, `docker.sock` só no `worker-agendado`, portas só
  em `127.0.0.1`), `.dockerignore`. Teste estático do YAML. *(R10.4, RNF-A6, design §11, spec §9.3)*
  - Lê: design §3.1, §4.4, §11; spec §9.3 inteira, §4.1 (tabela de filas)
  - Escreve: `deploy/ayanami/Dockerfile`, `deploy/ayanami/compose.yml`, `.dockerignore`, `tests/deploy/test_ayanami_compose.py`
  - Depende de: Y0.2
  - Orçamento: ~30k
  - Pronto: CA-Y29 verde; soma dos `mem_limit` ≤ 13 GB e `cpus` de lento + voz ≤ 6 (no teste); `docker build` local da imagem leve passa (sem subir nada); `ruff` limpo.
  - Paralelo: Y0.3, Y1.3, Y4.1

- [x] **Y1.0b Perfil enxuto da Ayanami no node 2 compartilhado** — override
  `deploy/ayanami/compose.node2.yml` (usado com `-f compose.yml -f compose.node2.yml` ou
  `COMPOSE_FILE=compose.yml:compose.node2.yml` no `.env`), mantendo o `compose.yml` da §9.3: todos em
  `cpuset: "6,7"`; pg 1g/1 (`shared_buffers=256MB`), api 512m/0.5, rápido 384m/0.5, agendado 512m/0.5,
  lento 3g/2, voz 1g/1.5 (soma 6528 MiB ≤ 6,5 GiB); `memswap_limit` = `mem_limit` exceto lento (+2g) e
  voz (+1g); `stop_grace_period: 40s` nos workers; `lenta_concorrencia = 1` (no `ayanami.toml`, sem
  variável de ambiente). Seção "Perfil node 2 compartilhado" no runbook. Teste estático da mescla.
  *(RNF-A6, spec §9.3; decisão do Pedro de 2026-10-17)*
  - Lê: spec §9.3; `ayanami/worker.py`, `ayanami/config.py` (`[fila]`); `deploy/ayanami/compose.yml`
  - Escreve: `deploy/ayanami/compose.node2.yml`, `tests/deploy/test_ayanami_compose.py`, `docs/ayanami/runbook.md` (só a seção nova), `specs/ayanami-central/tasks.md` (esta entrada)
  - Depende de: Y1.1
  - Orçamento: ~40k
  - Pronto: `docker compose -f compose.yml -f compose.node2.yml config -q` passa com `.env` falso numa cópia temporária; testes da soma, `cpuset`, swap, portas só em `127.0.0.1` e nenhum nome do serviço vizinho verdes; `ruff` limpo.
  - Paralelo: Y1.3b

- [x] **Y1.2 Host do node 2 como script e runbook** — scripts idempotentes, revisáveis e **não
  executados pelo agente**: `deploy/ayanami/host/preparar.sh` (pacotes, usuário `ayanami`,
  `/opt/ayanami`, `dados/`), `ufw.sh` (nega entrada; libera 22/tcp e 41641/udp; nada mais),
  `tailscale.sh` (`tailscale up` com hostname `ayanami` e `tailscale serve --bg --https=443
  http://127.0.0.1:8740`), `deploy.sh` (o deploy da §9.3: `git pull`, `pull`, `run --rm migrar`,
  `up -d`, `curl /saude`), `limpar-multivideos.sh` (lista e só remove com `--sim` o que o requirements
  "O que precisa do Pedro" item 2 enumera, pedindo confirmação item a item; nunca toca node 1);
  `docs/ayanami/runbook.md` (provisionar, deploy, rollback por tag de imagem, ver filas, girar token,
  restore manual, o que fazer com cada alerta). Teste estático: `bash -n`, `set -euo pipefail` em
  todos, nenhum `compose down`/`volume rm`/`DROP`/IP ou nome do node 1. *(R10.4, design §10.1–§10.2, §11, spec §9.3)*
  - Lê: design §10.1, §10.2, §11, §13; requirements "O que precisa do Pedro"; spec §9.3 (parágrafo "Deploy")
  - Escreve: `deploy/ayanami/host/preparar.sh`, `deploy/ayanami/host/ufw.sh`, `deploy/ayanami/host/tailscale.sh`, `deploy/ayanami/host/deploy.sh`, `deploy/ayanami/host/limpar-multivideos.sh`, `docs/ayanami/runbook.md`, `tests/deploy/test_ayanami_host.py`
  - Depende de: Y1.1
  - Orçamento: ~35k
  - Pronto: teste estático verde; runbook cobre os passos da Y1.5/Y1.6 na ordem; nenhum segredo nem host real no repo.
  - Paralelo: Y1.4, Y2.x, Y3.x

- [x] **Y1.3 Vigia e Telegram** — `deploy/ayanami/vigia/vigia.py` (só biblioteca padrão, roda no
  python3 do host): `/saude` (3 falhas seguidas), `df` > 85%, worker sem batimento > 5 min,
  snapshot `pc`/`ayanami` > 36 h, backup `falhou`, restore vermelho (tudo lido do JSON da `/saude`
  e de `df`), Telegram por `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` lidos do `.env`, anti-repetição
  1 por causa a cada 6 h em `/opt/ayanami/dados/vigia.json`; `ayanami-vigia.{service,timer}` (1
  min). Rede e relógio injetados no teste. *(R4.4, R10.5, design §11, spec §7.3)*
  - Lê: design §11 (Vigia); spec §2.2 (linha `GET /saude`), §7.3
  - Escreve: `deploy/ayanami/vigia/vigia.py`, `deploy/ayanami/vigia/ayanami-vigia.service`, `deploy/ayanami/vigia/ayanami-vigia.timer`, `tests/deploy/test_ayanami_vigia.py`
  - Depende de: Y0.2
  - Orçamento: ~30k
  - Pronto: cada causa dispara 1 mensagem e não repete em 6 h (relógio falso); `/saude` ok → nada; mensagem nunca contém token nem corpo de resposta; `ruff` limpo.
  - Paralelo: Y0.3, Y1.1, Y4.1

- [x] **Y1.3b Vigia também olha o servidor e o Minecraft** — `vigia.py` (ainda só biblioteca
  padrão) passa a ler CPU por grupo de núcleos (0-5 Minecraft, 6-7 Ayanami) de `/proc/stat`, RAM e
  swap de `/proc/meminfo` e o load; alerta núcleos 0-5 > 95% por 5 leituras, RAM disponível < 1
  GiB, swap usado > 6 GiB; `docker inspect minecraft` (alerta parado ou `RestartCount` subiu;
  container inexistente → `minecraft: ausente`, sem erro); RCON por `socket` em 127.0.0.1:25575
  (senha `RCON_PASSWORD` de `/opt/minecraft/.env`; `list` + `spark tps`, sem Spark só jogadores),
  alerta TPS < 15 por 3 leituras; resumo JSON atômico em `/opt/ayanami/dados/servidor.json`.
  Limites/nomes em `VIGIA_*` no `.env`; `--sem-servidor` desliga. *(node 2 dividido com o
  Minecraft)*
  - Escreve: `deploy/ayanami/vigia/*`, `tests/deploy/test_ayanami_vigia.py`
  - Depende de: Y1.3
  - Pronto: `/proc` falso em tmp, docker injetado, RCON falso em 127.0.0.1:0, relógio falso; cada
    causa nova dispara 1× e respeita as 6 h; ausente não alerta; `ruff` limpo.

- [x] **Y1.3c A Ayanami responde "como está o servidor?"** — `ayanami/servidor.py` lê o
  `servidor.json` do vigia (`AYANAMI_SERVIDOR_JSON`, senão `$AYANAMI_DADOS/servidor.json`, senão
  `/dados/servidor.json` no container), valida campo a campo, marca `velho` se `ts` > 3 min, mede o
  disco da partição dos dados e monta um resumo curto em pt-BR (CPU dos grupos, RAM, swap, disco,
  Minecraft no ar/jogadores/TPS ou ausente, alertas). Rota `GET /v1/servidor` (escopo `conversa` ou
  `ler`; sempre 200, estado `ok|velho|ausente|corrompido`), tool `servidor` no MCP (`ler`) e no modo
  nuvem (só leitura, em `NUVEM_PODE`). *(Sobras Y1.3b item 1)*
  - Escreve: `ayanami/servidor.py`, `ayanami/api/servidor.py`, `ayanami/api/auth.py` (1 linha),
    `ayanami/api/app.py` (`ROTEADORES`), `ayanami/mcp_server.py` e `ayanami/nuvem_tools.py` (tool
    `servidor`), `ayanami/nuvem.py` (`NUVEM_PODE`), `tests/ayanami/test_servidor.py`,
    `tests/ayanami/test_mcp.py` (contagem de tools)
  - Depende de: Y1.3b
  - Pronto: JSON falso em tmp (ok, velho, ausente, corrompido, campos tortos), rota por ASGI com o
    escopo sobrescrito, tool da nuvem com leitor injetado; sem rede; `ruff` limpo.

- [x] **Y1.4 CI no GitHub Actions** — *(deploy automático ligado por agente com autorização do Pedro em 2026-10-21; runbook §3 "Deploy automático")* `.github/workflows/ayanami.yml`: em push no `main` que toque
  `ayanami/**`, `magi/elo/**`, `magi/news/**`, `deploy/ayanami/**`: `uv sync`, `ruff`, `pytest -q
  tests/elo tests/ayanami tests/deploy` (com serviço `pgvector/pgvector:pg16` e `AYANAMI_TEST_DSN`),
  build da imagem → `ghcr.io`; job `deploy` (`appleboy/ssh-action` rodando `deploy.sh`, smoke
  `/saude`) só quando `AYANAMI_HOST` existe (gate por `env` lido de `secrets`, já que `if:` não lê
  `secrets` direto). Teste estático do YAML. *(R10.4, design §11)*
  - Lê: design §11 (Deploy); `deploy/ayanami/host/deploy.sh`
  - Escreve: `.github/workflows/ayanami.yml`, `tests/deploy/test_ayanami_ci.py`
  - Depende de: Y1.1, Y1.2
  - Orçamento: ~20k
  - Pronto: teste estático verde (gatilhos, gate de secrets, nenhum segredo literal); `actionlint` se houver no PC, senão anotar.
  - Paralelo: Y2.x, Y3.x

- [x] **Y1.5 Provisionar o node 2** — *(feita por agente com autorização do Pedro em 2026-10-21; desvios no runbook §2.1; pendências em Sobras)* **precisa do Pedro (não implementar por agente).**
  Confirmar no painel da Contabo que o node 2 existe e não está para cancelar (requirements "O que
  precisa do Pedro" 1); revisar e rodar `limpar-multivideos.sh` (item 2); criar a conta Tailscale,
  instalar no PC/node 2/celular, aprovar ACL (item 3); rodar `preparar.sh`, `ufw.sh`,
  `tailscale.sh`; `nmap` de fora mostra só 22 e 41641. O agente da sessão principal só lê a saída
  que o Pedro colar e atualiza o runbook. Nada no node 1.
  - Lê: `docs/ayanami/runbook.md`
  - Escreve: `docs/ayanami/runbook.md` (só correções do que divergiu)
  - Depende de: Y1.2
  - Orçamento: — (Pedro)
  - Pronto: `tailscale status` mostra `ayanami`; `ufw status` como no script; restos do MultiVideos removidos ou anotados como "fica".
  - Paralelo: Y2.x, Y3.x

- [x] **Y1.6 Primeiro deploy** — *(feita por agente com autorização do Pedro em 2026-10-21; runbook §2.1; pendências em Sobras)* **precisa do Pedro (não implementar por agente).** Criar
  `/opt/ayanami/.env` (`0600`, §9.1) e `ayanami.toml`; `deploy.sh`; `ayanami dispositivo criar pc
  --tipo pc` e guardar o token no keyring do PC; instalar o vigia (Y1.3) e testar uma mensagem do
  Telegram (item 6); `curl https://ayanami.<tailnet>.ts.net/saude` do PC e do celular; parte
  tailnet do S3: `claude mcp add --transport http ayanami …` e `mcp-remote` no Desktop (spec §8);
  secrets do GitHub se quiser CI (item 7).
  - Lê: `docs/ayanami/runbook.md`; spec §8 (conexão do Claude Code), §9.1
  - Escreve: `docs/ayanami/runbook.md` (só correções), `docs/perf/ayanami-s3.md` (seção "tailnet")
  - Depende de: Y1.1, Y1.3, Y1.5, Y2.1, Y3.1
  - Orçamento: — (Pedro)
  - Pronto: `/saude` `ok=true` pelo tailnet; os 7 serviços `healthy` (salvo `migrar`); Telegram de teste chegou; `claude mcp list` mostra `ayanami` (depois da Y5.1).
  - Paralelo: Y3.x, Y4.x, Y5.1, Y6.x

## Fase Y2 — API (spec §2)

- [x] **Y2.1 API base: tokens, pareamento, limites, auditoria e saúde** — `ayanami/api/` com
  `app.py` (`criar_app(cfg, db, relogio, …)` e `app` do `uvicorn`; inclui os roteadores de uma lista
  fixa de módulos; monta `/app` chamando `montar_pwa(app)` de `ayanami/pwa_estatico.py` (P1.1) por
  import preguiçoso — módulo ausente ou diretório `ayanami/pwa/` inexistente → não monta e loga
  `pwa_ausente`, sem erro; depois da Y2.1 só a Y5.1 mexe na `app.py`), `auth.py` (formato `ayn_<tipo>_…`, sha256, cache 5 s, revogação que avisa o hub
  por um gancho, `exigir(escopo)`, tabela `ESCOPO_DE_ROTA` com todas as linhas da §2.2),
  `limites.py` (60 req/min por dispositivo com `Retry-After`, tamanhos de corpo da §2.3),
  `auditoria.py`, `logs.py` (método/rota/status/dispositivo/ms/tamanhos; nunca corpo nem token),
  `dispositivos.py` (`/v1/pareamento`, `/v1/pareamento/trocar`, `DELETE /v1/dispositivo`,
  `PUT /v1/dispositivo/preferencias`), `saude.py` (`/saude` com `faltando`); **stubs** que só
  autenticam e respondem `501` em `nos.py` (Y2.2), `eventos.py` (Y2.3), `tarefas.py` (Y3.1),
  `noticias.py` (Y3.2), `custos.py` (Y6.1), `backup.py` (Y4.2), `turno.py` (Y6.4), `casa.py` e `confirma.py`
  (Y2.2), `feed.py` (Y2.3), `push.py` (P2.1: `/v1/push/assinar`) — cada um com `router` e docstring "dono: <ID>"; `ayanami dispositivo criar|listar|
  revogar` em `ayanami/dispositivos_cli.py`. *(R1, R1.1–R1.4, R10.1, spec §2.1–§2.3)*
  - Lê: design §4.1, §10.3; spec §2 inteira (linhas ~311–396); spec §3 só `dispositivos`, `pareamentos`, `auditoria` (`grep -n "CREATE TABLE dispositivos\|CREATE TABLE pareamentos\|CREATE TABLE auditoria"`); `ayanami/db.py`, `ayanami/config.py` (assinaturas)
  - Escreve: `ayanami/api/__init__.py`, `ayanami/api/app.py`, `ayanami/api/auth.py`, `ayanami/api/limites.py`, `ayanami/api/auditoria.py`, `ayanami/api/logs.py`, `ayanami/api/dispositivos.py`, `ayanami/api/saude.py`, stubs `ayanami/api/{nos,eventos,tarefas,noticias,custos,backup,turno,casa,confirma,feed,push}.py`, `ayanami/dispositivos_cli.py`, `tests/ayanami/api/__init__.py`, `tests/ayanami/api/conftest.py` (cliente ASGI, banco `pg` e banco falso), `tests/ayanami/api/test_tokens.py`, `tests/ayanami/api/test_pareamento.py`, `tests/ayanami/api/test_saude.py`, `tests/ayanami/api/test_limites.py`, `tests/ayanami/api/test_app_pwa.py` (sem `pwa_estatico` → sobe sem `/app`)
  - Depende de: Y0.1, Y0.3
  - Orçamento: ~60k
  - Pronto: CA-Y6 (403 parametrizado sobre `ESCOPO_DE_ROTA`, inclusive rotas ainda stub), CA-Y8, CA-Y9 verdes; 61ª requisição/min → 429 com `Retry-After`; `caplog` de 50 requisições sem `ayn_`/`Bearer`/corpo; `ruff` limpo.
  - Paralelo: Y0.4, Y0.5, Y3.3, Y4.1

- [x] **Y2.2 WebSocket dos nós, hub, ação na casa e confirmações** — `ayanami/hub.py` (conexões
  por dispositivo, 1 WS por dispositivo — a nova fecha a antiga com `4002`; `enviar_e_esperar(env,
  prazo)` com retransmissão 10 s × 3 [spec §1.3]; `visto` e `online` do `pc`/`casa`; último
  `ola`/`estado` da casa; ganchos `ao_ola(tipo, fn)` e `ao_receber(tipo, fn)` para Y6.x/Y5.1;
  fechar `4001` na revogação), `ayanami/api/nos.py` (`/ws`: `ola` em ≤ 5 s, `401`/`403`, `1008` por
  abuso via `magi.elo.receptor`; `/v1/longpoll` GET/POST), `ayanami/confirmacoes.py` (criar,
  responder, expirar em 120 s com relógio; `409`/`410`), `ayanami/api/casa.py`
  (`POST /v1/casa/acao` com `503 casa_offline`/`504 tempo_esgotado`, `prazo_ms` 8 s/10 s, `fala`
  pela tabela da §13.2 lida de `magi/core/phrases.yaml` — quem **preenche** essas frases é a C2.1;
  a Y2.2 só escreve o carregador, com recaída para uma frase genérica quando a chave falta, e não
  edita o `phrases.yaml`; `GET /v1/casa/estado`) e `POST /v1/confirma/{pedido}` em `ayanami/api/confirma.py`.
  *(R1.5–R1.7, R5.3, R6.6, spec §1.3, §2.2, §6.1)*
  - Lê: design §3.2, §4.1; spec §1.2 (tabela), §1.3, §2.2 (linhas `/ws`, `longpoll`, `casa/*`, `confirma`), §6.1; spec §3 só `confirmacoes`; `magi/elo/receptor.py`, `ayanami/api/auth.py` (assinaturas); spec §13.2 só a tabela de respostas
  - Escreve: `ayanami/hub.py`, `ayanami/confirmacoes.py`, `ayanami/api/nos.py`, `ayanami/api/casa.py`, `ayanami/api/confirma.py`, `tests/ayanami/api/test_ws.py`, `tests/ayanami/api/test_casa.py`, `tests/ayanami/test_confirmacoes.py`
  - Depende de: Y2.1
  - Orçamento: ~60k
  - Pronto: CA-Y7 e CA-Y10 (parte casa) verdes; CA-Y5 de ponta a ponta pela WS (mesmo `acao` 3× → 1 execução); 2ª WS do mesmo `pc` fecha a 1ª com 4002; casa sem `ola` em 5 s → fechada; `ruff` limpo.
  - Paralelo: Y2.4, Y3.1, Y3.3, Y4.1

- [x] **Y2.2b Confirmação vira evento, SSE e push** — sobra da P2.3: `Confirmacoes.criar` só
  perguntava ao PC. Agora grava o `Evento` `confirmacao` pela `Eventos.criar` da Y2.3 (só `celular`;
  `ref="confirma:<ulid>"`, `resumo` = descrição curta → `d`; `expira` = `criado` + 120 s no push da
  P2.1) e publica o SSE `confirma`; ao responder publica o fechamento (`confirma` com `resposta`) no
  SSE e manda o mesmo `Confirma` ao PC (salvo se foi o PC que respondeu), que descarta a pergunta. A
  expiração fecha pela varredura do SSE (`confirma` relido, `resposta: null`, `expira_em` vencido);
  a varredura e o ao vivo não se repetem. `confirmacoes_de` liga `eventos_de`/`sse_de`.
  - Escreve: `ayanami/confirmacoes.py`, `ayanami/api/eventos.py` (só a varredura de `confirma`), `tests/ayanami/test_confirmacoes.py`, `tests/ayanami/api/test_sse.py`
  - Depende de: Y2.2, Y2.3, P2.1
  - Pronto: evento + SSE + push deferido na criação; fechamento na resposta (SSE e PC) e na expiração (SSE) com cliente SSE de teste e `pg`; `ruff` limpo.

- [x] **Y2.3 Eventos, SSE e feed** — `ayanami/eventos.py` (`criar_evento(db, …)` grava em `eventos`
  com `seq`, faz `NOTIFY`, e entrega ao hub para o `pc` online; ouvinte `LISTEN` que relê pendentes
  ao reconectar — design §13), `ayanami/api/eventos.py` (`GET /v1/eventos` SSE com `Last-Event-ID`,
  `ping` 15 s, ≤ 4 SSE por celular, fecha na revogação; eventos `turno.texto`, `turno.fim`,
  `evento`, `estado`, `confirma`; publicador `sse.publicar(dispositivo|tipo, nome, corpo)` usado
  pelas Y2.2/Y6.4), `ayanami/api/feed.py` (`GET /v1/feed`, cards de notícia/tarefa/lembrete).
  *(R1.5, R9, spec §2.2 linhas `eventos`/`feed`, §3 `eventos`)*
  - Lê: design §4.1, §13 (linha NOTIFY); spec §1.2 (só `Evento`), §2.2 (linhas `/v1/eventos`, `/v1/feed`), §3 só `eventos`/`news_items`; `ayanami/hub.py` (assinaturas)
  - Escreve: `ayanami/eventos.py`, `ayanami/api/eventos.py`, `ayanami/api/feed.py`, `tests/ayanami/api/test_sse.py`, `tests/ayanami/api/test_feed.py`, `tests/ayanami/test_eventos.py`
  - Depende de: Y2.1, Y2.2
  - Orçamento: ~50k
  - Pronto: SSE retoma do `Last-Event-ID` sem perder nem repetir (100 eventos, corte no 37º); 5º SSE do mesmo celular → 429; revogar fecha o SSE em ≤ 5 s (relógio falso); `NOTIFY` perdido → evento entregue no reconectar (`pg`); feed pagina por `antes`.
  - Paralelo: Y3.1, Y3.3, Y4.1 (Y5.1/Y6.1 só depois da Y3.1)

- [x] **Y2.4 `EloCliente`** — `magi/elo/cliente.py`: conexão de saída `wss://…/ws` com Bearer,
  `ola` → `ack`, `bate` a cada `batimento_s`, reconexão 1 → 2 → 4 … → 60 s com jitter ±20% (rng
  injetado), recaída `/v1/longpoll` após 3 falhas seguidas de WS, retransmissão e cache de ids pelo
  `receptor`, `401` → para e loga `ayanami_token_revogado`, despacho por tipo (`on(tipo, fn)`),
  quadros binários; usado pelo PC (Y6.2) e pela casa (C1.x). Teste contra servidor WS falso local.
  *(R1.7, spec §1.3, §10.3 — só o comportamento de conexão)*
  - Lê: spec §1.3, §1.4, §2.2 (linhas `/ws` e `longpoll`), §10.3; `magi/elo/receptor.py`, `magi/elo/mensagens.py` (assinaturas)
  - Escreve: `magi/elo/cliente.py`, `tests/elo/test_cliente.py`
  - Depende de: Y0.1
  - Orçamento: ~45k
  - Pronto: sequência de esperas de reconexão bate com 1/2/4/…/60 ± 20% (rng fixo); 3 falhas → longpoll; 401 → sem nova tentativa; `bate` a cada 10 s com relógio falso; envelope sem resposta reenviado 3× com o mesmo `id`; `ruff` limpo.
  - Paralelo: Y0.2, Y0.3, Y2.1

## Fase Y3 — Fila e workers (spec §4–§5)

- [x] **Y3.1 Fila, tarefas e workers** — `ayanami/fila.py` (`app` com `PsycopgConnector`; registro
  das 17 tarefas da §4.2 com fila, `RetryStrategy`, prazo por `asyncio.timeout`, `queueing_lock`/
  `lock`, `periodic` só na `agendada`; `embeddings.lote` só com `[embeddings] ligado`), corpos
  **stub** em `ayanami/workers/{noticias,agente,voz,stt,embeddings,backup,push}.py` (assinatura
  final, docstring "dono: <ID>"; `push.py` → dono P2.1), corpos reais de `limpeza.diaria` e `fila.reanimar` em
  `ayanami/workers/manutencao.py`; `ayanami/tarefas.py` (`TarefaIn`/`TarefaOut`, `criar_tarefa`,
  `cancelar_tarefa`, mapa de estados, `on_job_status`, `redigir()`); `ayanami/worker.py`
  (`cli(args)` de `ayanami worker <fila>` e `ayanami batimento <fila> --max`); `ayanami/deps.py` (`Deps`: db, cfg,
  relógio, registry, budget, hub — o que os jobs recebem); rotas `/v1/tarefas*` e `/v1/fila`.
  *(R2, R2.1–R2.6, spec §4)*
  - Lê: design §4.2, §4.3; spec §4 inteira (com o que a Y0.4 corrigiu); `docs/perf/ayanami-s5.md`; spec §2.2 (linhas `tarefas`/`fila`); spec §3 só `tarefas`/`workers_batimento` e "Retenção"
  - Escreve: `ayanami/fila.py`, `ayanami/tarefas.py`, `ayanami/worker.py`, `ayanami/deps.py`, `ayanami/workers/__init__.py`, `ayanami/workers/manutencao.py`, stubs `ayanami/workers/{noticias,agente,voz,stt,embeddings,backup,push}.py`, `ayanami/api/tarefas.py`, `tests/ayanami/test_fila.py`, `tests/ayanami/test_tarefas.py`, `tests/ayanami/api/test_tarefas_api.py`
  - Depende de: Y0.4, Y2.1
  - Orçamento: ~60k
  - Pronto: CA-Y13, CA-Y14, CA-Y15 verdes; `POST /v1/tarefas` repetido com a mesma `chave` → `200` com a existente; limpeza respeita os prazos da §3 (`pg`, relógio falso); `ruff` limpo.
  - Paralelo: Y2.2, Y2.3, Y6.1

- [x] **Y3.2 Notícias na nuvem** — `ayanami/workers/noticias.py` (`noticias.coletar` chamando
  `magi.news.__main__.run_once(config, dsn)` com `Config` de `[noticias]`, recusa `dim` ≠ do PC,
  `free_tier` só para texto público, `evento noticia_bomba` pelo critério de
  `magi/core/proactive/news.py`; `progresso.atualizar`), `ayanami/api/noticias.py`
  (`GET /v1/noticias` paginado por `(atualizado, id)`, `PUT /v1/noticias/preferencias`); em
  `magi/news/__main__.py` só o que for preciso para aceitar o DSN da Ayanami. *(R3.1, R3.2, spec §5.1, §5.2 resposta)*
  - Lê: design §8; spec §5.1, §5.2 (só o JSON de resposta e a regra da página); `magi/news/__main__.py` por trecho (`run_once`, `_load_config`); `magi/core/proactive/news.py` por trecho (`grep -n "urgen\|bomba\|def "`); spec §3 `002_noticias.sql`
  - Escreve: `ayanami/workers/noticias.py`, `ayanami/api/noticias.py`, `magi/news/__main__.py` (só a entrada do DSN), `tests/ayanami/test_noticias.py`, `tests/ayanami/api/test_noticias_api.py`
  - Depende de: Y3.1
  - Orçamento: ~45k
  - Pronto: CA-Y16 verde; `tests/news/` sem mudar asserção; coleta com provedores falsos grava itens no banco `pg` e cria `noticia_bomba` só no item urgente.
  - Paralelo: Y3.4, Y3.5, Y3.6, Y4.2

- [x] **Y3.3 `magi-news-sync` no PC e recaída do timer** — `magi/elo/news_sync.py` (`main`, cursor
  e `ultimo_ok` em `~/.local/state/magi/news_sync.json`, upsert por página numa transação no
  `magi-pg`, `delivered_at` preservado, embedding de dimensão errada → `NULL`, `PUT
  /v1/noticias/preferencias` depois do OK, `--precisa-local`, códigos de saída 0/1/2/3, internet e
  HTTP injetados; token do keyring `magi`/`ayanami_pc`, URL de `[ayanami] url` do `config.toml`),
  `deploy/systemd/magi-news-sync.{service,timer}`, `ExecCondition=` no `magi-ayanami.service`,
  `[ayanami]` comentada no `config.example.toml`. *(R3.1, R3.3, D6a, spec §5.2)*
  - Lê: design §8; spec §5.2 inteira, DS5; `005_ayanami_sync.sql`; `magi/news/repo.py` por trecho (`grep -n "def \|INSERT"`); `deploy/systemd/magi-ayanami.service`; `tests/deploy/test_units.py` por trecho (como testa unidades)
  - Escreve: `magi/elo/news_sync.py`, `deploy/systemd/magi-news-sync.service`, `deploy/systemd/magi-news-sync.timer`, `deploy/systemd/magi-ayanami.service` (só `ExecCondition`), `config.example.toml` (só `[ayanami]` comentada), `tests/elo/test_news_sync.py`, `tests/deploy/test_news_sync_units.py`
  - Depende de: Y0.1, Y0.3
  - Orçamento: ~50k
  - Pronto: CA-Y17 (`pg`, base com as migrações do PC no `ayanami-pg-teste`) e CA-Y18 verdes; `tests/deploy/test_units.py` sem mudar asserção; sem `[ayanami]` o timer de notícias do PC roda como hoje.
  - Paralelo: Y2.1, Y3.1, Y4.1; **não** com C2.2 (`config.example.toml`)

- [x] **Y3.4 Tarefas do agente** — `ayanami/workers/agente.py`: `agente.pesquisar` (`GraphAgent`
  com persona da Condessa, busca web, `deps.budget`, prazo 30 min, ≤ 12 passos, `pessoal=True`
  recusa `free_tier`, progresso/frase a cada passo, resultado ≤ 6000 caracteres + fontes, `evento
  tarefa_pronta`), `agente.lembrete`, `monitores.varrer` e `monitor.passo` (juízo `condicao` no LLM
  barato, `a_cada_h`, `expira`). Agente e registry falsos nos testes. *(R2.3, R3.5, R9, spec §5.3)*
  - Lê: spec §5.3, §4.2 (linhas `agente.*`/`monitor*`); `magi/agent/graph.py` por trecho (`grep -n "class GraphAgent\|def __init__\|async def run"`); `magi/providers/registry.py` por trecho (`grep -n "free_tier\|def get\|def pick"`); `ayanami/deps.py`, `ayanami/eventos.py` (assinaturas)
  - Escreve: `ayanami/workers/agente.py`, `tests/ayanami/test_agente.py`
  - Depende de: Y3.1, Y2.3
  - Orçamento: ~45k
  - Pronto: CA-Y19 (parte agente) verde; monitor bate → `evento monitor` e `ok`; não bate → `agenda += a_cada_h`; expirado → `"expirou sem bater"`; prazo estourado → `falhou` com `erro="prazo"` sem retry.
  - Paralelo: Y3.2, Y3.5, Y3.6, Y4.2

- [x] **Y3.5 `ayanami-voz` (Kokoro)** — `ayanami/voz/servidor.py` (`ayanami voz --port 8741`:
  `POST /falar` PCM s16le 24 kHz em streaming, `X-Taxa`, `413`, `503` carregando > 20 s, `GET
  /saude`), carga preguiçosa e descarga após `descarregar_apos_s` (relógio injetado), motor Kokoro
  atrás de um protocolo `Motor` (falso nos testes; import de `kokoro_onnx` só dentro do real);
  `ayanami/workers/voz.py` (`voz.cache_frases` lendo a lista de frases de um caminho injetado e
  gravando `/dados/modelos/cache-voz/<sha1>.ogg`, ffmpeg injetado). *(R3.6, D14a, spec §5.4)*
  - Lê: design §4.3, §4.4; spec §5.4; `docs/perf/ayanami-s1.md` (se já houver)
  - Escreve: `ayanami/voz/__init__.py`, `ayanami/voz/servidor.py`, `ayanami/voz/motor.py`, `ayanami/workers/voz.py`, `tests/ayanami/test_voz.py`
  - Depende de: Y3.1
  - Orçamento: ~40k
  - Pronto: rotas e faixas da §5.4 testadas com motor falso; descarrega após 600 s ocioso; cache não regenera frase com `sha1` existente; nenhum teste importa `kokoro_onnx`.
  - Paralelo: Y3.2, Y3.4, Y3.6, Y4.2

- [x] **Y3.6 STT assíncrono e embeddings** — `ayanami/workers/stt.py` (`stt.transcrever` com
  faster-whisper atrás de protocolo, `small` int8 4 threads `pt`, só na `lenta`, texto ≤ 200 mil
  caracteres ou `dados.arquivo` com expiração de 7 dias, áudio apagado no `finally`), upload do
  `stt` em `ayanami/api/tarefas.py` (só o ramo multipart `tipo=stt`: ≤ 200 MB, para `/dados/tmp/`),
  `ayanami/workers/embeddings.py` (`embeddings.lote` fastembed e5-small com prefixos, lotes de 64,
  só registrado com `[embeddings] ligado`). *(R3.4, R3.7, spec §5.5, §5.6)*
  - Lê: spec §5.5, §5.6, §4.2 (linhas `stt`/`embeddings`); `ayanami/api/tarefas.py` por trecho (`POST`)
  - Escreve: `ayanami/workers/stt.py`, `ayanami/workers/embeddings.py`, `ayanami/api/tarefas.py` (só o ramo `stt`), `tests/ayanami/test_stt.py`, `tests/ayanami/test_embeddings.py`
  - Depende de: Y3.1
  - Orçamento: ~40k
  - Pronto: CA-Y19 (parte `stt`: áudio some em sucesso e falha) verde; upload > 200 MB → 413 sem arquivo em disco; texto longo vai a arquivo; embeddings desligado → job não registrado (CA-Y13 continua 17).
  - Paralelo: Y3.2, Y3.4, Y3.5, Y4.2

## Fase Y4 — Backups (spec §7)

- [x] **Y4.1 `magi-backup` no PC** — `magi/elo/backup.py` (`main`: `pg_dump -Fc` e contagens por
  `docker exec magi-pg` **só leitura**, `tar` do `~/.config/magi` sem `*.token`/`*key*`/`*secret*`,
  `zstd -10`, manifesto, `PUT /v1/backup/pc` com `X-Sha256`/`X-Data`/`X-Manifesto`, `409` → sai 0,
  3 tentativas 1/5/15 min com `sleep` injetado, temporário apagado sempre, card "backup não subiu"
  pelo canal que o PC já usa para avisar o HUD — se não houver um usável fora do `magi-core`, anotar
  em *Sobras*), `deploy/systemd/magi-backup.{service,timer}` (`03:30`, `Persistent`,
  `OnStartupSec=10min`). Executor de comandos e HTTP falsos. *(R4.1, R4.2, spec §7.1, §7.3)*
  - Lê: spec §7.1, §7.3; spec §2.2 (linha `PUT /v1/backup/pc`); `deploy/systemd/magi-clean.{service,timer}` (modelo); `tests/deploy/test_units.py` por trecho
  - Escreve: `magi/elo/backup.py`, `deploy/systemd/magi-backup.service`, `deploy/systemd/magi-backup.timer`, `tests/elo/test_backup.py`, `tests/deploy/test_backup_units.py`
  - Depende de: Y0.2
  - Orçamento: ~40k
  - Pronto: CA-Y23 verde; os únicos comandos contra o `magi-pg` capturados são `pg_dump` e `psql -Atc "SELECT count(*)…"`; `tests/deploy/test_units.py` sem mudar asserção.
  - Paralelo: Y0.3, Y1.1, Y1.3, Y2.1, Y3.3

- [x] **Y4.1b Sobras da Y3.3/Y4.1: credenciais, scripts e units no `install.sh`** — `magi/elo/backup.py`
  usa `magi/elo/credenciais.py` (`url_ayanami(cfg)`, `token_pc()`: keyring `magi`/`ayanami_pc`
  primeiro, `ayanami.token` ao lado do config como recaída; sem url o keyring nem é lido);
  `[project.scripts]` conferido (`magi-news-sync`/`magi-backup` já existiam); `hud/install.sh`
  copia `magi-news-sync.{service,timer}`, `magi-backup.{service,timer}` e `magi-casa.service` em
  `UNIT_FILES` **sem** habilitar nem iniciar (só `daemon-reload`, que já existia).
  - Lê: `magi/elo/credenciais.py`; `hud/install.sh` por trecho; `tests/deploy/test_units.py`
  - Escreve: `magi/elo/backup.py`, `tests/elo/test_backup.py`, `pyproject.toml` (só scripts), `hud/install.sh` (só `UNIT_FILES`), `specs/ayanami-central/tasks.md`
  - Depende de: Y3.3, Y4.1
  - Orçamento: ≤ 30k
  - Pronto: `uv run pytest -q tests/elo tests/deploy` código 0.

- [x] **Y4.2 Backup na Ayanami: recebimento, restic e restore de teste** — `ayanami/api/backup.py`
  (`PUT /v1/backup/pc` em streaming para `/dados/entrada/pc/<data>/`, sha256, `400` apaga, `409`,
  `413`, defere `backup.restic`), `ayanami/workers/backup.py` (os 6 jobs da §7.2 gerando comandos
  num executor injetado; `forget` sempre com `--group-by host,tags` e `--keep-*` [DS7];
  restore de teste em `ayanami-restore-teste` com `--network none` e lista branca
  `run`/`cp`/`exec`/`stop`; manifesto divergente → `restore_testes` vermelho, `evento backup_falhou`
  e Telegram), `ayanami/telegram.py` (cliente mínimo, HTTP injetado), `cli(args)` de `ayanami backup
  iniciar` (`restic init`) em `workers/backup.py`;
  varredura estática de proibições. *(R4, R4.3–R4.5, D7a, D15a, spec §7.2, §7.3)*
  - Lê: design §9; spec §7.2, §7.3, §2.2 (linha `PUT /v1/backup/pc`), §3 só `backups`/`restore_testes`, §4.2 (linhas `backup.*`); `ayanami/eventos.py` (assinatura)
  - Escreve: `ayanami/api/backup.py`, `ayanami/workers/backup.py`, `ayanami/telegram.py`, `tests/ayanami/api/test_backup_api.py`, `tests/ayanami/test_backup_jobs.py`, `tests/ayanami/test_proibicoes.py`
  - Depende de: Y3.1, Y2.3
  - Orçamento: ~55k
  - Pronto: CA-Y10 (parte backup), CA-Y24 e CA-Y25 verdes (a varredura cobre `ayanami/`, `magi/elo/backup.py`, `deploy/ayanami/` inteiros, com lista de exceções vazia); corpo > 2 GiB → 413 sem arquivo.
  - Paralelo: Y3.2, Y3.4, Y3.5, Y3.6, Y5.1

- [ ] **Y4.3 Backup de verdade** — **precisa do Pedro (não implementar por agente).** Escolher
  o storage (D7), criar bucket e chave restrita, guardar `RESTIC_PASSWORD` no cofre e no keyring do
  PC (requirements "O que precisa do Pedro" 5); `docker compose run --rm migrar ayanami backup
  iniciar`; ligar o `magi-backup.timer` no PC; ver o 1º snapshot `pc` e `ayanami`; rodar
  `backup.restore_teste` à mão e um restore manual pelo runbook; desligar o PC 36 h (ou forjar a
  data no teste do vigia) e ver o Telegram.
  - Lê: `docs/ayanami/runbook.md` (backup e restore)
  - Escreve: `docs/ayanami/runbook.md` (só correções)
  - Depende de: Y1.6, Y4.1, Y4.2
  - Orçamento: — (Pedro)
  - Pronto: snapshot `pc` e `ayanami` no B2; restore de teste verde; alerta de 36 h chegou.
  - Paralelo: Y0.8, F.x

## Fase Y5 — MCP (spec §8)

- [x] **Y5.1 Servidor MCP** — `ayanami/mcp_server.py`: `VerificadorAyanami` (só tipo `mcp`, não
  revogado, escopos), `MCPServer` montado em `/mcp` como a Y0.5 confirmou, `exigir(escopo)`, as
  tools da §8 registradas só para escopos ligados em `[mcp] escopos` (padrão D13a), resources
  `ayanami://…`, auditoria de toda chamada, `tv_acao` com `tv.power_off` → `confirmacoes` (Y2.2) e
  `acao` só se aceita em 120 s; `memoria_gravar` → `confirma` no PC; montagem em
  `ayanami/api/app.py` (só a linha do `mount`). Cliente MCP da lib contra ASGI em memória. *(R5, R5.1–R5.4, D13a, spec §8)*
  - Lê: design §4.5; spec §8 inteira (com o que a Y0.5 corrigiu); `docs/perf/ayanami-s3.md`; `ayanami/confirmacoes.py`, `ayanami/tarefas.py`, `ayanami/hub.py`, `ayanami/api/auth.py` (assinaturas)
  - Escreve: `ayanami/mcp_server.py`, `ayanami/api/app.py` (só o `mount("/mcp")`), `tests/ayanami/test_mcp.py`
  - Depende de: Y0.5, Y2.2, Y3.1
  - Orçamento: ~50k
  - Pronto: CA-Y26 e CA-Y27 verdes; `tools/list` não mostra `tv_acao` sem `casa` em `[mcp] escopos`; `noticias_buscar` nunca devolve texto marcado `spoiler`; `ruff` limpo.
  - Paralelo: Y3.2, Y3.4–Y3.6, Y4.2, Y6.x

## Fase Y6 — Roteamento do turno e modo nuvem (spec §6)

- [x] **Y6.1 Gasto da nuvem** — `ayanami/custos.py` (`BudgetNuvem` com a interface do `Budget` do
  PC: `ensure_allowed`/`record`/`status`; tetos de `[budget]`; `pc_mes` de `custos_pc` alimentado
  pelo `Bate.custos_mes_usd` via gancho do hub), `ayanami/api/custos.py` (`GET /v1/custos?desde=`),
  e o `budget` no `Deps` dos workers. *(R8.4, D11a, spec §6.4)*
  - Lê: design §7.4; spec §6.4, §1.2 (só `Bate`), §3 só `costs`/`custos_pc`; `magi/providers/budget.py` por trecho (`grep -n "class Budget\|def ensure_allowed\|def record\|def status\|BudgetExceeded"`); `ayanami/deps.py`, `ayanami/hub.py` (assinaturas)
  - Escreve: `ayanami/custos.py`, `ayanami/api/custos.py`, `ayanami/deps.py` (só o campo `budget`), `tests/ayanami/test_custos.py`
  - Depende de: Y2.2, Y3.1
  - Orçamento: ~35k
  - Pronto: CA-Y21 (parte `BudgetNuvem`: 1,99+2,00 libera; 2,00 bloqueia; 1,00+4,00 bloqueia) verde; `record` grava `source='nuvem'`; `/v1/custos` pagina por `uid`.
  - Paralelo: Y2.3, Y3.2, Y3.4–Y3.6, Y4.2, Y5.1

- [x] **Y6.2 `RemoteLink`, `PonteTurnos` e o elo no PC** — `magi/elo/remote.py` (`RemoteLink`
  implementa `SatelliteLink`: `AUDIO_IN` → `entrada()` com fila ≤ 400 quadros, `play` → `AUDIO_OUT`
  reamostrando para 24 kHz, `StopPlayback` → `AUDIO_FIM`), `magi/elo/ponte.py` (`PonteTurnos`: um
  `TurnMachine` do satélite `celular` criado uma vez, áudio como PTT, texto sem STT, prazo 45 s →
  `TurnoFim(erro="tempo")`), **[DS6]** `TurnDeps.on_turn_done` e a chamada única no `TurnMachine`
  (ponto achado na Y0.6), `magi/elo/pc.py` (`NoPc`: `EloCliente` do PC com token do keyring e
  `[ayanami] url`, `Bate.custos_mes_usd` do `Budget` local, despacho de `turno` → ponte, `evento`/
  `confirma` → `magi/elo/eventos_pc.py`, `resumo_nuvem` → `magi/elo/reconciliar.py`, custos →
  `magi/elo/custos_pc.py` — esses três como **stubs** "dono: Y6.5/Y6.6"), montagem em `assemble.py`
  só com `[ayanami]` presente. *(R8.1, design §7.2, §12, spec §6.2, §6.3)*
  - Lê: design §7.2, §12; spec §6.1–§6.3; `docs/perf/ayanami-s6.md`; `turn.py` por trecho (`class TurnDeps`, o ponto da Y0.6); `service.py` por trecho (`SatelliteLink`, criação de `TurnMachine`); `assemble.py` por trecho (`grep -n "TurnDeps\|cfg.raw\|def assemble"`); `magi/elo/cliente.py`, `magi/elo/converte.py` (assinaturas)
  - Escreve: `magi/elo/remote.py`, `magi/elo/ponte.py`, `magi/elo/pc.py`, stubs `magi/elo/eventos_pc.py`, `magi/elo/reconciliar.py`, `magi/elo/custos_pc.py`, `magi/core/turn.py` (só `TurnDeps.on_turn_done` e a chamada), `magi/core/service.py` (só o registro do satélite remoto, se a Y0.6 apontou que precisa), `magi/core/assemble.py` (só a montagem do `NoPc`), `tests/elo/test_remote.py`, `tests/elo/test_ponte.py`
  - Depende de: Y0.6, Y2.4
  - Orçamento: ~60k
  - Pronto: CA-Y22 (parte gancho: `celular` emite 1 `TurnoFim`, `pc` nada) verde; turno de texto e de áudio (PCM falso) com core de teste devolvem `TurnoFim` com cards; resposta nunca vai ao satélite do headset; sem `[ayanami]` nada muda (regra 10); `tests/core/` sem mudar asserção.
  - Paralelo: Y3.x, Y4.2, Y5.1, Y6.1, Y6.3, C1.x; **não** com C2.2 (`turn.py`, `assemble.py`)

- [x] **Y6.3 Modo nuvem** — `ayanami/nuvem.py` (`NUVEM_PODE`, `atender(texto, dispositivo, deps)`:
  `GraphAgent` só com as ferramentas permitidas e a linha "Agora você está na nuvem…", contexto dos
  últimos `contexto_turnos` de `nuvem_turnos`, `tv_*` só com casa online, `tv_desligar` → `confirma`;
  teto batido → roteador sem LLM com as frases `tv.*` do `intents.yaml` (rapidfuzz) e frase
  `sem_verba`; pedido de PC → "isso só no PC…"; grava `nuvem_turnos`), `ayanami/nuvem_tools.py`
  (as ferramentas: tarefa/lembrete/monitor por `criar_tarefa`, `estado`, `news_query`; as `tv_*` são as
  mesmas ferramentas de `magi/agent/tools/tv.py` (C2.2) ligadas a um `TvActionsNuvem` que manda
  `acao` à casa pelo hub — spec §13.4, último parágrafo — sem reescrever as ferramentas), `ayanami/frases.yaml` (`casa_offline`, `pc_offline_pedido`, `sem_verba`, `erro_generico`,
  `pc_caiu`), STT/TTS da nuvem (OpenAI `[nuvem] stt_modelo`/`marin` com cache por texto; Kokoro após
  2 falhas em 5 min ou teto) atrás de protocolos. *(R8.2, R8.3, D11a, D14a, spec §6.5)*
  - Lê: design §7.3, §7.4; spec §6.4 (último parágrafo), §6.5; `ayanami/custos.py`, `ayanami/tarefas.py`, `ayanami/hub.py`, `ayanami/confirmacoes.py` (assinaturas); `magi/core/intents.yaml` por trecho (`grep -n "tv\."`, bloco da C2.1); `magi/agent/tools/tv.py` e `magi/core/actions/tv.py` (C2.2, só assinaturas); `magi/agent/graph.py` por trecho (`__init__`)
  - Escreve: `ayanami/nuvem.py`, `ayanami/nuvem_tools.py`, `ayanami/frases.yaml`, `ayanami/voz_nuvem.py`, `tests/ayanami/test_nuvem.py`
  - Depende de: Y6.1, Y2.2, Y3.1, C2.2
  - Orçamento: ~55k
  - Pronto: CA-Y21 (parte modo nuvem: bloqueado, "liga a TV da sala" gera `acao` sem LLM e "pesquisa X" dá `sem_verba`; agente falso nunca recebe ferramenta fora de `NUVEM_PODE`) e CA-Y20 (parte frase em cache com casa offline) verdes; troca para Kokoro na 2ª falha em 5 min (relógio falso).
  - Paralelo: Y3.2, Y3.4–Y3.6, Y4.2, Y5.1, Y6.2

- [x] **Y6.4 Rota do turno** — `ayanami/api/turno.py`: `POST /v1/turno` (texto ou `multipart`
  `audio/webm;codecs=opus` ≤ 1 MiB/15 s, `413`/`415`/`429` > 20/min), decisão de modo pela §6.1
  (`visto` < `offline_apos_s`) fixa no turno, modo `pc` (ffmpeg injetado webm → PCM 16 kHz em ≤ 2 s,
  quadros de 80 ms + `AUDIO_FIM` pelo hub, `AUDIO_OUT` → ogg/opus), queda da WS do PC no meio →
  `TurnoFim(erro="pc_caiu")`, modo `nuvem` → `nuvem.atender`; `GET /v1/turno/{id}` (só o dono),
  `GET /v1/turno/{id}/audio` (streaming; `410` após 60 s, arquivo apagado); `turno.texto`/
  `turno.fim` pelo SSE. *(R7.2, R7.3, R8, spec §2.2 linhas `turno`, §6.1, §6.2)*
  - Lê: design §7.1–§7.3; spec §6.1, §6.2, §2.2 (linhas `/v1/turno*`), §1.4; `ayanami/hub.py`, `ayanami/api/eventos.py`, `ayanami/nuvem.py` (assinaturas)
  - Escreve: `ayanami/api/turno.py`, `ayanami/turnos.py` (estado dos turnos em andamento e áudio temporário), `tests/ayanami/api/test_turno.py`
  - Depende de: Y2.3, Y6.3
  - Orçamento: ~55k
  - Pronto: CA-Y20 verde (29 s → `pc`, 31 s → `nuvem`; casa offline → 503 no REST); queda do PC no meio → `pc_caiu` sem refazer; áudio some em 60 s (relógio falso); outro dispositivo pedindo o turno → 404.
  - Paralelo: Y6.5, Y6.6, Y4.2, Y5.1

- [x] **Y6.5 Reconciliação `resumo_nuvem`** — na Ayanami, `ayanami/reconciliacao.py` (no `ola` do
  `pc`, pelo gancho `hub.ao_ola`: `nuvem_turnos` não sincronizados em envelopes de ≤ 50 por `ts`;
  `ack` marca só os ids confirmados; sem `ack` reenvia no próximo `ola`); no PC,
  `magi/elo/reconciliar.py` (`gravar_resumo`: grava em `turns` com satélite `celular` marcado
  `nuvem`, passa pelo extrator de memória dos turnos normais, ignora `uid` já gravado, devolve os
  ids). *(R8.5, D6a, spec §6.6)*
  - Lê: design §7.5; spec §6.6, §1.2 (só `ResumoNuvem`/`Ack`), §3 só `nuvem_turnos`; `magi/memory/turns_repo.py` ou equivalente por trecho (`grep -rn "class .*Turn.*Repo\|def add\|def save" magi/memory`); extrator de memória por trecho (`grep -rn "def extract\|MemoryIngest\|ingest" magi/memory magi/core | head`)
  - Escreve: `ayanami/reconciliacao.py`, `magi/elo/reconciliar.py`, `tests/ayanami/test_reconciliacao.py`, `tests/elo/test_reconciliar.py`
  - Depende de: Y6.2, Y6.3
  - Orçamento: ~45k
  - Pronto: CA-Y22 (parte reconciliação: 120 → 50/50/20; `ack` parcial; reenvio não duplica `turns`) verde; nome exato do extrator anotado em *Sobras* (a spec deixou "nome exato no tasks").
  - Paralelo: Y6.4, Y6.6

- [x] **Y6.5b Sobras da reconciliação** — `Reconciliacao.fechar()` na parada da app (lifespan de
  `ayanami/api/app.py`); migração aditiva `006_turns_nuvem_uid.sql` (`turns.nuvem_uid uuid` +
  índice único parcial, `turns.ferramentas jsonb`); o PC grava `intent = "nuvem"` com `nuvem_uid`
  e as `ferramentas` do `TurnoNuvem` (`ON CONFLICT … DO NOTHING`) e ainda lê o formato antigo
  `intent = 'nuvem:<uid>'` para não duplicar. *(R8.5, spec §6.6)*
  - Escreve: `ayanami/api/app.py` (só `_vida`), `magi/memory/migrations/006_turns_nuvem_uid.sql`, `magi/elo/reconciliar.py`, `tests/elo/test_reconciliar.py`, `tests/ayanami/test_reconciliacao.py`, `tests/ayanami/test_migrar.py`, `tests/memory/test_migrate.py` e `tests/learning/test_interview_store.py` (só as listas de migrações)
  - Depende de: Y6.5
  - Pronto: 006 reexecutável e só aditiva (testada no `ayanami-pg-teste`); reenvio e linhas antigas não duplicam `turns`; parada da app fecha as rodadas pendentes. A 006 entra no magi-pg no próximo reinício do magi-core.

- [x] **Y6.6 PC: eventos, confirmações e custos** — `magi/elo/eventos_pc.py` (`evento` → `sink`
  novo da proatividade em `magi/core/proactive/` respeitando silêncio/jogo; cards existentes
  "Pesquisa pronta", "código de pareamento", "celular conectado"; `confirma` → pergunta ao Pedro
  pelo caminho de confirmação que o core já usa e responde `Confirma(resp=…)`; expirada → nada),
  `magi/elo/custos_pc.py` (`GET /v1/custos?desde=` a cada `ola` e 15 min, insere em `costs` com
  `origem_uid` sem duplicar; total do mês para o `Bate`); **lado PC do pareamento do celular**:
  `magi/elo/parear.py` (`pedir_codigo()` → `POST /v1/pareamento` com o token `pc`; card "código de
  pareamento 123 456" no HUD pelo mesmo `sink`; `main()` rodável por `uv run python -m
  magi.elo.parear` imprime o código e a URL `…/app/#/parear?c=<código>`, e o QR em texto só se a
  lib `qrcode` já estiver instalada — sem dependência nova, sem script novo no `pyproject`). *(R8.4, R9, R9.2, design §12, spec §6.4)*
  - Lê: design §12; spec §6.4 (parágrafo do PC), §1.2 (só `Evento`, `Confirma`); `magi/core/proactive/sink.py` inteiro; `magi/memory/costs_repo.py` por trecho (`grep -n "def \|INSERT"`); confirmação no core por trecho (`grep -rn "needs_confirmation\|on_confirm" magi/core | head`)
  - Escreve: `magi/elo/eventos_pc.py`, `magi/elo/custos_pc.py`, `magi/core/proactive/ayanami.py`, `magi/elo/parear.py`, `tests/elo/test_eventos_pc.py`, `tests/elo/test_custos_pc.py`, `tests/elo/test_parear.py`
  - Depende de: Y6.1, Y6.2
  - Orçamento: ~50k
  - Pronto: evento em jogo/silêncio fica na fila da proatividade como os locais; 2 puxadas seguidas de custos não duplicam (`db` ou repo falso); `confirma` sem resposta em 120 s não manda nada; `pedir_codigo` com API falsa gera o card e nunca loga o código; `tests/core/` sem mudar asserção.
  - Paralelo: Y6.4, Y6.5

- [x] **Y6.6b "Condessa, pareia o celular"** — sobra da Y6.6: o card do código só saía quando o
  core chamava `pedir_codigo(avisos=…)`. Intent `celular.parear` ("pareia o celular", "conectar
  celular", "código do celular"…) + `IntentId.CELULAR_PAREAR`; `magi/core/actions/celular.py`
  (`CelularActions`) chama `pedir_codigo` com `AvisosAyanami(core.proactive)` e fala "Código na
  tela, vale 5 minutos." (a spec §2.2 diz 5 min); sem `[ayanami]` → "A Ayanami não está
  configurada."; registrado sempre no `assemble.py`. O código só vai ao card (nem fala nem log).
  - Escreve: `magi/core/intents.yaml` (bloco `celular.*`), `magi/common/contracts.py` (só o
    `IntentId`), `magi/core/phrases.yaml` e `magi/core/i18n/en-gb.yaml` (frases do pareamento),
    `magi/core/actions/celular.py`, `magi/core/assemble.py` (só o registro), `tests/core/test_parear_celular.py`
  - Pronto: Ayanami falsa (`MockTransport`) gera o card e a fala curta sem o código; `tests/core` e
    `tests/agent` sem mudar asserção.

---

## Fase C1 — `magi-casa`

- [x] **C1.1 Esqueleto e contrato da casa** — pacote `magi/casa/` com o contrato puro
  `driver.py` (`Cap`, `Key`, `Motivo`, `Capacidades.pode`, `ResTv`, `TvDriver`, spec §10.5,
  assinaturas finais), `falso.py` (`DriverFalso(capacidades, script)` que grava chamadas e responde
  do script, relógio injetado), `config.py` (`casa.toml` §12.4: leitura, validação, escrita
  atômica; caminhos lidos na hora da chamada, padrão `None`), `apps.py` + `apps.yaml` (catálogo
  §12.5 com override por `id`), `log.py` (JSON em stdout, campos §10.4, filtro que nunca grava
  token/cert/código/texto), `__main__.py` (entrada `magi-casa`, subcomandos da §10.1; `servir`
  e os da CLI como **stubs** com docstring da tarefa dona), a unit e a entrada no `pyproject`.
  *(R6.1–R6.3, R6.8, spec §10.1, §10.5, §12.4–§12.5)*
  - Lê: design §5 (intro, §5.1, §5.5); spec §10.1, §10.5, §12.4, §12.5, §16.2 (CA-Y30, CA-Y50); assinaturas de `magi/elo/mensagens.py` (`EstadoTv`, `TvInfo`, `AppInfo`; só `grep -n "class "` e as classes); `pyproject.toml` só `[project.scripts]` e `dependencies`; `deploy/systemd/magi-core.service` (molde)
  - Escreve: `magi/casa/__init__.py`, `magi/casa/__main__.py`, `magi/casa/driver.py`, `magi/casa/falso.py`, `magi/casa/config.py`, `magi/casa/apps.py`, `magi/casa/apps.yaml`, `magi/casa/log.py`, `magi/casa/cli.py` (stubs), `magi/casa/drivers/__init__.py` (registro `DRIVERS` com os três nomes apontando por import preguiçoso para `magi.casa.drivers.{samsung,roku,androidtv}` — módulo ausente → `NAO_SUPORTADO` com "dono: <ID>"; ninguém mais edita), `tests/casa/drivers/__init__.py`, `deploy/systemd/magi-casa.service`, `uv.lock`, `pyproject.toml` (script `magi-casa` e deps `samsungtvws[async]==3.0.6`, `wakeonlan==4.0.0`, `rokuecp==0.19.5`, `androidtvremote2==0.3.2`, `async-upnp-client==0.49.0`, `zeroconf==0.151.5`), `tests/casa/__init__.py`, `tests/casa/conftest.py` (isola caminhos em `tmp_path`, relógio falso), `tests/casa/test_contrato.py`, `tests/casa/test_config.py`
  - Depende de: Y0.1, Y0.2 (`pyproject.toml`)
  - Orçamento: ~45k
  - Pronto: CA-Y30 (parte do contrato: `Capacidades.pode`, `ResTv`, driver sem cap → `NAO_SUPORTADO`) e CA-Y50 verdes; `magi-casa --help` lista os subcomandos; `systemd-analyze --user verify` da unit limpo; `ruff` limpo; `magi/casa/driver.py` importa sem I/O.
  - Paralelo: C2.1 e a onda 2 da nuvem; **não** com Y0.2 (`pyproject.toml`)

- [x] **C1.1b `Executor`, emulação, fila e timeouts** — `magi/casa/emula.py` (`Executor.rodar`,
  §10.6: resolve a TV pelas cinco regras da §13.3 devolvendo `TV_AMBIGUA` com os candidatos no
  `detalhe`; `confirmed` em `tv.power_off`; intent → método; emulação da §10.7; ligar com sonda de
  500 ms até 8 s; timeouts da §11.5) e `magi/casa/fila.py` (um `asyncio.Lock` por TV, fila ≤ 8,
  coalescência ≤ 1 tecla/80 ms, nova `acao` aborta a sequência emulada). *(R6.2, R6.5, spec
  §10.4, §10.6, §10.7, §11.5, §13.3)*
  - Lê: design §5.2; spec §10.4 (só *Fila por TV*), §10.6, §10.7, §11.4, §11.5, §13.3, §16.2 (CA-Y30–Y36, Y45, Y52); `magi/casa/driver.py` e `falso.py` (C1.1); `magi/common/contracts.py` só `ActionRequest` (`grep -n "class ActionRequest" -A25`)
  - Escreve: `magi/casa/emula.py`, `magi/casa/fila.py`, `tests/casa/test_executor.py`, `tests/casa/test_emulacao.py`, `tests/casa/test_fila.py`
  - Depende de: C1.1
  - Orçamento: ~50k
  - Pronto: CA-Y30 (tabela dos 11 métodos no `Executor`), CA-Y31, CA-Y32, CA-Y33, CA-Y34, CA-Y35 (caminho local), CA-Y36, CA-Y45 e CA-Y52 (as cinco regras em ordem; a pergunta no turno é da C2.2) verdes, só com `DriverFalso` e relógio falso; nenhum `sleep` real.
  - Paralelo: C1.1c, C1.2, C1.3, C1.4, C2.x, P1.x

- [x] **C1.1c API local e `servir`** — `magi/casa/local.py`: servidor TCP JSON-lines do elo
  (§10.2: `ola` com token de `casa.token` criado `0600` na 1ª subida, `acao` → `acao_ok` com
  `resp`, `estado` pedido e empurrado, ociosidade 10 min, linha ≤ 64 KiB; escuta `127.0.0.1` ou o
  IP do tailnet do `[casa] escuta`, nunca `0.0.0.0`); `magi/casa/estado.py` (`EstadoTv` em memória,
  `casa-estado.json` atômico, sondagem por driver a cada 30 s, `online=False` após 2 falhas);
  `magi/casa/servir.py` (monta config + drivers + `Executor` + API local; recusa subir com arquivo
  de pareamento mais aberto que `0600`). A `acao` chega ao `Executor` por uma interface
  (`Protocol`) para a C1.1b não ser lida além da assinatura. *(R6.7, spec §10.2, §10.4)*
  - Lê: spec §1.1–§1.3 (envelope, `ola`/`acao`/`acao_ok`/`estado`), §10.1, §10.2, §10.4 (*Estado*, *Logs*), §16.2 (CA-Y37, CA-Y38); `magi/elo/mensagens.py` só `encode`/`decode` e os tipos citados; `magi/casa/driver.py`, `config.py`, `log.py` (C1.1); assinatura de `Executor.rodar` (C1.1b, só a linha `def`)
  - Escreve: `magi/casa/local.py`, `magi/casa/estado.py`, `magi/casa/servir.py`, `magi/casa/__main__.py` (só o corpo de `servir`), `tests/casa/test_local.py`, `tests/casa/test_estado.py`
  - Depende de: C1.1
  - Orçamento: ~45k
  - Pronto: CA-Y37 e CA-Y38 verdes (cliente TCP em `127.0.0.1:0`, `DriverFalso`); `magi-casa servir` sobe sem `casa.toml` e sem internet; `ola` lista vazio.
  - Paralelo: C1.1b, C1.2, C1.3, C1.4

- [x] **C1.2 Driver Samsung** — `magi/casa/drivers/samsung.py` (`samsungtvws[async]` 3.0.6 +
  `wakeonlan` 4.0.0, spec §11.1): 8002/8001 por `ano`, `PowerState` pela REST, ligar por
  `KEY_POWER`/WOL 3× ao broadcast, desligar só com estado, `run_app` do catálogo, `KEY_HDMIn`,
  `send_text`, token do keyring (ganha) ou arquivo. Testes com REST e WS falsos; `send_magic_packet`
  e keyring injetados. **Nunca TV real.** *(R6.1, spec §11.1, §11.4)*
  - Lê: design §5.1 (tabela, linha Samsung); spec §10.5, §11.1, §11.4, §11.5, §16.2 (CA-Y40, CA-Y41); `magi/casa/driver.py`, `falso.py`; `magi/common/secrets.py` só a API do keyring (`grep -n "^def "`)
  - Escreve: `magi/casa/drivers/samsung.py`, `tests/casa/drivers/test_samsung.py` (o registro `DRIVERS` já aponta para cá; C1.1)
  - Depende de: C1.1
  - Orçamento: ~45k
  - Pronto: CA-Y40 e CA-Y41 verdes; 401/recusa de "Permitir" → `ACESSO_NEGADO`; exceção de rede vira `OFFLINE`/`TEMPO_ESGOTADO`, nunca sobe.
  - Paralelo: C1.1b, C1.1c, C1.3, C1.4

- [x] **C1.3 Driver Roku** — `magi/casa/drivers/roku.py` (`rokuecp` 0.19.5, spec §11.2): caps de
  `device-info` (`is-tv`, `supports-tv-power-control`), `PowerOn` + WOL de recaída, teclas,
  `launch/<id>` com busca por nome em `/query/apps` (cache 24 h), `Lit_` por caractere (≤ 100, 30 ms),
  403 → `ACESSO_NEGADO` com a dica "Acesso à rede". Servidor HTTP falso `:8060`. *(R6.1, spec
  §11.2)*
  - Lê: spec §10.5, §11.2, §11.4, §11.5, §16.2 (CA-Y42, CA-Y43); `magi/casa/driver.py`, `falso.py`
  - Escreve: `magi/casa/drivers/roku.py`, `tests/casa/drivers/test_roku.py`
  - Depende de: C1.1
  - Orçamento: ~35k
  - Pronto: CA-Y42 e CA-Y43 verdes; nenhum log com o texto digitado (só `len`).
  - Paralelo: C1.1b, C1.1c, C1.2, C1.4

- [x] **C1.4 Driver Android TV** — `magi/casa/drivers/androidtv.py` (`androidtvremote2` 0.3.2,
  spec §11.3): `async_connect` + `keep_reconnecting` em tarefa própria, comando durante reconexão
  espera ≤ 1,5 s, estado por callbacks (`is_on`, `current_app` → id pelo `pacote:`, `volume_info` →
  0–100), `POWER` só quando o estado contradiz, deep link do catálogo, HDMI por keycode com
  confirmação por `current_app`. ADB (`adb = true`) fica só como gancho `NAO_SUPORTADO` com TODO
  (opcional, fora do padrão). `AndroidTVRemote` falso. *(R6.1, spec §11.3)*
  - Lê: design §5.1 (linha `androidtv`); spec §10.5, §11.3, §11.4, §11.5, §16.2 (CA-Y44); `magi/casa/driver.py`, `falso.py`, `apps.py` (só `AppCatalogo`/assinaturas)
  - Escreve: `magi/casa/drivers/androidtv.py`, `tests/casa/drivers/test_androidtv.py`
  - Depende de: C1.1
  - Orçamento: ~45k
  - Pronto: CA-Y44 verde; reconexão testada com o falso caindo 3× sem bloquear outra TV.
  - Paralelo: C1.1b, C1.1c, C1.2, C1.3

- [x] **C1.5 Descoberta, TCL e pareamento (CLI)** — `magi/casa/descoberta.py` (`Descobridor`:
  SSDP `async-upnp-client` + mDNS `zeroconf` com fontes **injetáveis**; confirmação por HTTP;
  `chave` estável; MAC de `/proc/net/arp` injetável; regra TCL §12.2; revalidação de IP com escrita
  atômica do `casa.toml`, ligada ao `servir` a cada `descoberta_min`); `magi/casa/pareamento.py`
  (Samsung 60 s, Android TV 120 s com 3 códigos, Roku só `device-info`; `0700`/`0600`;
  `esquecer`); corpos dos subcomandos `descobrir`, `nomear [--padrao] [--driver]`, `parear`,
  `esquecer`, `estado`, `testar` em `cli.py` (código lido com eco desligado). Teste de ponta a ponta
  sem segredo no log. *(R6.4, D9, spec §12.1–§12.3)*
  - Lê: design §5.3, §5.4; spec §10.1 (subcomandos), §12.1–§12.4, §16.2 (CA-Y46–Y49); assinaturas de `magi/casa/drivers/*.py` (só `class`/`def` públicos), `config.py`, `servir.py` (só onde liga a revalidação)
  - Escreve: `magi/casa/descoberta.py`, `magi/casa/pareamento.py`, `magi/casa/cli.py` (corpos), `magi/casa/servir.py` (só a chamada da revalidação periódica), `tests/casa/test_descoberta.py`, `tests/casa/test_pareamento.py`, `tests/casa/test_sem_segredo.py`
  - Depende de: C1.1b, C1.1c, C1.2, C1.3, C1.4
  - Orçamento: ~55k
  - Pronto: CA-Y46, CA-Y47, CA-Y48 e CA-Y49 (caplog de descobrir → parear → 20 ações com drivers falsos) verdes; nenhum socket multicast aberto nos testes.
  - Paralelo: C2.x, P1.x; **não** com C1.6 (`servir.py`; a C1.6 vem depois)

- [x] **C1.6 Conexão de saída à Ayanami e recursos** — `magi/casa/saida.py`: `wss://<ayanami>/ws`
  com o token `casa` (`~/.config/magi/ayanami-casa.token` ou keyring), só se `[casa] ayanami`
  estiver preenchido; `ola` (sem `token`) → `bate` 10 s → `estado` a cada mudança e a cada 60 s;
  reconexão, recaída `/v1/longpoll` e 401 (para e segue local) **pelo `EloCliente` de
  `magi/elo/cliente.py` (Y2.4)** — nada de cliente próprio; aqui só o que é da casa: token,
  `ola`/`estado` e despacho de `acao` remota para a mesma fila por TV (`origem=ayanami` no log). Também o teste de recursos (`pytest -m lento`). *(R1.7, R6.7, R6.8,
  spec §10.3)*
  - Lê: design §5.6 (*Pela Ayanami*); spec §1.1 (envelope, `bate`), §2.2 (linhas `/ws` e `/v1/longpoll`), §10.3, §10.1 (*Meta*), §16.2 (CA-Y35, CA-Y39, CA-Y58); assinaturas de `magi/casa/servir.py`, `fila.py`, `emula.py`; `magi/elo/cliente.py` (Y2.4) só as assinaturas
  - Escreve: `magi/casa/saida.py`, `magi/casa/servir.py` (só ligar a saída quando configurada e recriar o driver quando o IP muda), `magi/casa/local.py` (só `dados["candidatos"]`, sobra da C1.1b), `tests/casa/test_saida.py`, `tests/casa/test_recursos.py` (marcado `lento`)
  - Depende de: C1.1b, C1.1c, C1.5 (`servir.py` em sequência), Y2.4 (`EloCliente`); a integração com a API real depende de Y2.2 e fica para a prova ao vivo (P1.S4/F.1) — os CA usam WS falso
  - Orçamento: ~45k
  - Pronto: CA-Y39 e CA-Y35 (caminho da WS) verdes com servidor WS falso; CA-Y58 rodado uma vez com `-m lento` e o número anotado no commit (≤ 1% CPU, ≤ 80 MB RSS).
  - Paralelo: C2.x, P1.x; **não** com C1.5

- [ ] **C1.S2 Spike S2 — TVs reais (precisa do Pedro)** — com o Pedro na sala: `magi-casa
  descobrir`, `nomear`, `parear` na Samsung e na TCL (Roku ou Google TV? §12.2); conferir as
  marcas `[S2]`: portas 8001/8002 e `PowerState` pelo ano, WOL no Wi-Fi e no cabo, "Notificação de
  acesso", HDMI por tecla; na TCL Google TV, 6466/6467, reconexão e keycodes HDMI; se Roku,
  "Acesso à rede" e *Início rápido da TV*; ids `[S2]` do `apps.yaml` (abrir cada app uma vez);
  latência do critério 1 (20 comandos por driver, `magi-casa testar` + voz no PC, p90 ≤ 1,5 s).
  Roku de verdade só quando houver um (fica anotado). O que mudar volta à spec §11/§12.5 e ao
  `apps.yaml` antes de fechar.
  - Lê: spec §11, §12, §17 (linha S2); requirements *Critérios de sucesso* 1
  - Escreve: `docs/spikes/s2-tvs-reais.md`, `magi/casa/apps.yaml` (ids confirmados), `specs/ayanami-central/spec.md` (§11.1–§11.4, §12.5, só os `[S2]`), `~/.config/magi/casa.toml` do Pedro (fora do git)
  - Depende de: C1.5 (e C2.2 para medir a voz no PC)
  - Orçamento: ~30k do agente + tempo do Pedro
  - Pronto: as duas TVs pareadas e nomeadas; tabela de latência por driver no doc do spike; nenhum `[S2]` aberto sem decisão.
  - Paralelo: P1.x, P2.x

## Fase C2 — Intents `tv.*` e ferramentas

- [x] **C2.1 Intents, slots de catálogo e frases** — `IntentId.TV_*` (7) e `SlotName.TV/APP/INPUT`
  em `contracts.py`; bloco TV no `intents.yaml` (§13.1, com a **regra de colisão** [DS12]: toda frase
  `tv.*` tem "tv"/"televisão", `{tv}` ou "hdmi"; "aumenta o volume" segue `volume.set`, "abre o
  YouTube" sem "na tv" segue o de hoje); no roteador, slots de catálogo `{tv}`, `{app}`, `{input}`
  casados por rapidfuzz (≥ 80) contra um `CasaCatalogo` injetado (nomes + apelidos de `TvInfo`/
  `AppInfo` e entradas `hdmi1..4` + apelidos), no molde do `{game}`; `"+k"/"-k"/"N"` e "muito" = 8.
  Todas as frases da §13.2 — inclusive as `fala` que a Ayanami devolve em `/v1/casa/acao` e que a
  Y2.2 só lê (carregador com recaída) — no `phrases.yaml` e no `i18n/en-gb.yaml`; a C2.1 é a única
  que escreve `phrases.yaml`, `intents.yaml`, `router.py` e `contracts.py` nesta lista. *(R6.6, spec §13.1, §13.2)*
  - Lê: design §5.6; spec §13.1, §13.2, §16.2 (CA-Y51); `magi/common/contracts.py` linhas 395–470 (`SlotName`, `IntentId`); `magi/core/intents.yaml` linhas 150–240 (`volume.*`, `rgb.*`); `magi/core/router.py` por trecho (`grep -n "game\|_game\|catalog"`, ~90–110 e ~430–600); `magi/core/phrases.yaml` e `i18n/en-gb.yaml` só o topo (formato); `tests/core/test_router.py` só os helpers do topo
  - Escreve: `magi/common/contracts.py` (só os enums), `magi/core/intents.yaml` (bloco TV), `magi/core/router.py` (slots de catálogo da casa), `magi/core/phrases.yaml`, `magi/core/i18n/en-gb.yaml`, `tests/core/test_router_tv.py`
  - Depende de: Y0.1 (tipos `TvInfo`/`AppInfo`)
  - Orçamento: ~50k
  - Pronto: CA-Y51 verde; `uv run pytest -q tests/core/test_router.py tests/core/test_i18n.py` continua verde (nenhuma frase antiga muda de intent); `ruff` limpo.
  - Paralelo: C1.x, P1.x

- [x] **C2.2 `TvActions`, ferramentas `tv_*` e a pergunta "qual TV?"** — `magi/core/actions/tv.py`
  (`TvActions` no molde do `RgbActions`: uma conexão TCP JSON-lines com a casa, `ola` com
  `casa.token`, `acao` → `acao_ok`, timeouts 2,5 s / 10 s, `motivo` → `SAY_TV_*`, casa recusando →
  "A casa está fora do ar." sem tentar a Ayanami; o `ola` da casa alimenta o `CasaCatalogo` do
  roteador); `magi/agent/tools/tv.py` (`tv_ligar`, `tv_desligar` `danger`, `tv_volume`, `tv_mudo`,
  `tv_app` com `ToolArgsError`, `tv_entrada`, `tv_estado` não serial; descrição com os nomes das
  TVs); registro no `assemble.py`; seção `[casa]` do `config.toml` (§16.1); `TV_AMBIGUA` →
  "Mais de uma TV: sala ou quarto?" pela pergunta pendente do turno, e a resposta curta reenvia a
  `acao` com o slot `tv`. *(R6.6, R6.7, spec §10.2, §13.2–§13.4, §16.1)*
  - Lê: spec §10.2, §13.2–§13.4, §16.1, §16.2 (CA-Y52, CA-Y53, CA-Y54); `magi/core/actions/system.py` linhas 150–220 (`RgbActions`); `magi/agent/tools/system.py` (molde `ActionTool`/`Mapped`); `magi/agent/tools/base.py` só assinaturas; `magi/core/assemble.py` por trecho (`grep -n "system_tools\|RgbActions\|registry"`); `magi/core/turn.py` por trecho (`grep -n "quis dizer\|pendente"`); `magi/common/config.py` só o molde de uma seção (`grep -n "class .*Config"`)
  - Escreve: `magi/core/actions/tv.py`, `magi/agent/tools/tv.py`, `magi/core/assemble.py` (registro), `magi/core/turn.py` (só o caso `TV_AMBIGUA` na pergunta pendente, se o mecanismo existente não bastar), `magi/common/config.py` (`CasaConfig`), `config.example.toml` (só a seção `[casa]` comentada), `tests/core/test_tv_actions.py`, `tests/agent/test_tv_tools.py`
  - Depende de: C2.1
  - Orçamento: ~55k
  - Pronto: CA-Y53, CA-Y54 e CA-Y52 (pergunta + resposta curta no turno seguinte) verdes com casa falsa em TCP `127.0.0.1:0`; `tests/core/test_actions_registry.py` e `tests/agent/` verdes.
  - Paralelo: C1.x, P1.x; **não** com Y6.2 (`turn.py`, `assemble.py`) nem Y3.3 (`config.example.toml`)

## Fase P1 — Celular (PWA, `ayanami/pwa/`)

- [x] **P1.1 Esqueleto do PWA** — HTML + JS em módulos ES, sem build e sem CDN (DS15):
  `index.html`, `app.js` (roteador por hash da §14.1 e estados globais da §14.3: `/saude` com 4 s na
  abertura, em `visibilitychange` e a cada 30 s; 401 → apaga o token e vai a Parear; faixa "sem
  conexão com a Ayanami — ligue o Tailscale"), `api.js` (fetch com Bearer do IndexedDB, SSE com
  `Last-Event-ID` e reconexão 1 → 30 s), `estado.js` (store com `subscribe`), `estilo.css`,
  `sw.js` (cache `condessa-shell-v<N>` com a **lista fixa de todos os arquivos**, inclusive as telas;
  `/v1/feed` network-first em `condessa-feed`; resto de `/v1/*` network-only; `activate` apaga
  versões antigas), `manifest.webmanifest` (§14.6), ícones e sprites do rosto (D5a, gerados uma vez
  da arte do HUD; ≤ 40 KB cada), **stubs** de `telas/{conversa,tv,feed,tarefas,ajustes,parear,
  confirma}.js` e `gravador.js` com `export function montar(el, ctx)` e docstring da tarefa dona;
  montagem estática em `/app` por `montar_pwa(app)`, que a Y2.1 já chama. Meta ≤ 80 KB gzip sem sprites. *(R7.1, R7.4, spec §14.1,
  §14.3, §14.6)*
  - Lê: design §6; spec §2.2 (linhas `/saude`, `/v1/eventos`, `/app/*`), §14.1, §14.3, §14.6, §16.2 (CA-Y56, CA-Y57); `ayanami/api/app.py` (Y2.1) só o trecho que chama `montar_pwa`; `hud/` só o caminho da arte da Condessa (`ls`)
  - Escreve: `ayanami/pwa/index.html`, `ayanami/pwa/app.js`, `ayanami/pwa/api.js`, `ayanami/pwa/estado.js`, `ayanami/pwa/estilo.css`, `ayanami/pwa/sw.js`, `ayanami/pwa/manifest.webmanifest`, `ayanami/pwa/icones/{192,512,maskable-512}.png`, `ayanami/pwa/rosto/{dormindo,ouvindo,pensando,falando}.webp`, `ayanami/pwa/telas/*.js` (stubs), `ayanami/pwa/gravador.js` (stub), `ayanami/pwa_estatico.py` (`montar_pwa(app)`; `Cache-Control: no-cache` no `sw.js`; **não** edita `ayanami/api/app.py`), `tests/ayanami/pwa/test_sw.mjs`, `tests/ayanami/pwa/test_app.mjs`, `tests/ayanami/test_pwa_estatico.py`
  - Depende de: Y2.1 (`criar_app` chamando `montar_pwa`, `/saude`), Y2.3 (SSE `/v1/eventos`)
  - Orçamento: ~55k
  - Pronto: CA-Y57 verde; CA-Y56 na parte global (`/saude` falhando → `sem_ayanami` + faixa; 401 → Parear) verde; `GET /app/` responde 200 no teste da API; `gzip -c` dos arquivos sem sprites ≤ 80 KB.
  - Paralelo: C1.x, C2.x, P2.1

- [x] **P1.2 Conversa, push-to-talk, SSE e áudio** — `gravador.js` (máquina da §14.4:
  `getUserMedia` no gesto, `MediaRecorder` opus 24 kbps após `isTypeSupported`, < 400 ms descarta,
  15 s para sozinho, sair do botão cancela, `track.stop()` sempre; sem opus → só texto) e
  `telas/conversa.js` (histórico do dia, rosto por estado, selo PC/nuvem pelo `modo` do `POST
  /v1/turno`, campo de texto, texto pelo SSE `turno.texto`/`turno.fim`, `<audio>` criado no gesto
  tocando `GET /v1/turno/{id}/audio`, 50 s sem `turno.fim` → "Ela não respondeu; tenta de
  novo?"). *(R7.2, R7.3, spec §14.2 Conversa, §14.4, §14.5)*
  - Lê: design §6 (PTT, Resposta); spec §2.2 (linhas `/v1/turno*`, `/v1/eventos`), §14.2, §14.4, §14.5, §16.2 (CA-Y55); `ayanami/pwa/api.js`, `estado.js` só as exportações
  - Escreve: `ayanami/pwa/gravador.js`, `ayanami/pwa/telas/conversa.js`, `tests/ayanami/pwa/test_gravador.mjs`, `tests/ayanami/pwa/test_conversa.mjs`
  - Depende de: P1.1, Y6.4 (contrato de `/v1/turno*`; a prova ao vivo fica no P1.S4)
  - Orçamento: ~45k
  - Pronto: CA-Y55 verde com `MediaRecorder`/`fetch`/`EventSource` falsos; o microfone nunca fica aberto depois de `parar`/erro.
  - Paralelo: P1.3, P1.4

- [x] **P1.3 Controle remoto** — `telas/tv.js`: abas por TV (`GET /v1/casa/estado`, `EstadoTv`
  vivo pelo SSE `estado`); botões **só** das `caps` (ligar/desligar, vol ±, mudo, canal ±, HDMI das
  `entradas`, apps do catálogo da TV, d-pad + OK/voltar/home/play, digitar texto); `POST
  /v1/casa/acao` direto; "desligar" pede 2º toque em ≤ 3 s e só então `confirmed=true` (DS16);
  vol± segurado repete a cada 200 ms; TV `online=false` → botões cinza "TV fora da rede"; casa
  offline (503) → "a casa está fora do ar"; TV padrão do celular (`tv_padrao`). *(R6.7, R7.1,
  spec §14.2 TV)*
  - Lê: design §5.6 (*Pela Ayanami*), §6; spec §1.2 (só `TvInfo`, `EstadoTv`, `AcaoPedido`, `AcaoResultado`), §2.2 (linhas `/v1/casa/*`), §10.5 (`Cap`, `Key`), §14.2, §16.2 (CA-Y56); `ayanami/pwa/api.js`, `estado.js` só as exportações; `ayanami/app/elo.schema.json` (Y0.1) se existir
  - Escreve: `ayanami/pwa/telas/tv.js`, `tests/ayanami/pwa/test_tv.mjs`
  - Depende de: P1.1
  - Orçamento: ~40k
  - Pronto: CA-Y56 na parte do controle (só desenha as `caps`; 2º toque em 3 s → `confirmed=true`; um toque só não manda nada) verde.
  - Paralelo: P1.2, P1.4

- [x] **P1.4 Feed, tarefas, ajustes, pareamento e confirmação** — `telas/parear.js` (6 dígitos;
  `?c=` do QR; `POST /v1/pareamento/trocar` → token no IndexedDB), `telas/feed.js` (rolagem
  infinita `GET /v1/feed?n=20&antes=…`; sem rede → feed do cache com a hora), `telas/tarefas.js`
  (lista por estado, progresso, idade, ver e cancelar), `telas/ajustes.js` (dispositivo,
  `push_com_pc`, silêncio, TV padrão, `voz_em_texto`, versão, sair = `DELETE /v1/dispositivo`;
  espelha em `PUT /v1/dispositivo/preferencias`; o interruptor de push fica **vazio** para a P2.2),
  `telas/confirma.js` (card de `#/confirma/<ulid>` e do SSE `confirma`; expirou → "expirou").
  *(R7.1, R7.4, spec §14.2, §16.1)*
  - Lê: design §6 (tabela de telas); spec §2.2 (linhas de pareamento, dispositivo, feed, tarefas, confirma), §14.2, §14.3, §16.1 (*Celular*), §16.2 (CA-Y56); `ayanami/pwa/api.js`, `estado.js` só as exportações
  - Escreve: `ayanami/pwa/telas/parear.js`, `ayanami/pwa/telas/feed.js`, `ayanami/pwa/telas/tarefas.js`, `ayanami/pwa/telas/ajustes.js`, `ayanami/pwa/telas/confirma.js`, `tests/ayanami/pwa/test_telas.mjs`
  - Depende de: P1.1
  - Orçamento: ~50k
  - Pronto: CA-Y56 na parte do feed (sem rede → cache com a hora; botões de TV e PTT desabilitados) verde; pareamento com código errado mostra o erro do 400/429 sem guardar nada.
  - Paralelo: P1.2, P1.3

- [ ] **P1.S4 Spike S4 — PWA no Android do Pedro (precisa do Pedro)** — com a Ayanami no ar:
  `tailscale serve` com o cert do tailnet; instalar pelo Chrome (WebAPK) e pelo botão do
  `beforeinstallprompt`; `MediaRecorder` opus no aparelho; autoplay depois do PTT; Web Push com a
  tela bloqueada saindo do node 2 pelo FCM; abrir sem Tailscale (faixa + feed do cache). Se opus ou
  autoplay falharem, aplicar a recaída da §17 (WAV por `AudioWorklet`; tocar só após toque) como
  tarefa nova. Medir o critério 2 (botão no 4G p90 ≤ 1,5 s; voz p90 ≤ 4 s; 20 medições cada).
  - Lê: design §6, §14 (S4); spec §14.6, §15, §17 (linha S4); requirements *Critérios de sucesso* 2
  - Escreve: `docs/spikes/s4-pwa-android.md`, `specs/ayanami-central/spec.md` (§14–§15, só o que mudar)
  - Depende de: P1.2, P1.3, P2.2, C1.6, Y6.4, Y1.6 (Ayanami no node 2)
  - Orçamento: ~30k do agente + tempo do Pedro
  - Pronto: PWA instalado no celular do Pedro; push recebido com a tela bloqueada; tabela do critério 2 no doc do spike.
  - Paralelo: C1.S2

## Fase P2 — Web Push

- [x] **P2.1 Web Push no servidor** — `ayanami/push.py` (lógica + `cli(args)`, para onde a `ayanami/cli.py` da Y0.2 despacha
  `ayanami push chaves`: `gerar_chaves()` (VAPID P-256 via `py-vapid`; imprime as linhas do `.env`); `tipo` a partir
  do `EventoTipo`; payload ≤ 3 KB (`titulo` ≤ 40, `resumo` ≤ 120, sem dado sensível, `tag`, `url`);
  Urgency/TTL da tabela §15; silêncio (`[push] silencio_padrao` ou preferência `silencio`, fuso
  America/Sao_Paulo) com o agrupado "N avisos" às 07:30 (`resumo-manha`); limite `[push] max_hora`;
  `push_com_pc=false` com PC online pula tudo menos `confirma`; envio por `webpush` em
  `asyncio.to_thread` (injetável), 404/410 apaga a assinatura, 413 corta e reenvia, 429/5xx com
  `Retry-After`; auditoria sem texto. Corpo do job `push.enviar` no stub `ayanami/workers/push.py`
  (Y3.1) chamando `ayanami.push`; rota `/v1/push/assinar` (POST/DELETE) no stub `ayanami/api/push.py`
  (Y2.1). *(R9, D12a,
  spec §15)*
  - Lê: design §6 (Web Push); spec §1.2 (só `Evento`/`EventoTipo`), §3 (só `push_assinaturas` e `dispositivos.preferencias`), §4.2 (linha `push.enviar`), §9.1–§9.2 (`VAPID_*`, `[push]`), §15, §16.2 (CA-Y59); `ayanami/fila.py` (Y3.1, só `grep -n "push"`), `ayanami/workers/push.py` e `ayanami/api/push.py` (stubs), `ayanami/api/auth.py` (assinatura de `exigir`), `ayanami/eventos.py` (Y2.3, assinaturas)
  - Escreve: `ayanami/push.py`, `ayanami/workers/push.py` (corpo), `ayanami/api/push.py` (corpo), `tests/ayanami/test_push.py`, `tests/ayanami/api/test_push_api.py` — não edita `ayanami/cli.py`, `ayanami/fila.py` nem `pyproject.toml` (o `pywebpush` já vem da Y0.2)
  - Depende de: Y2.3 (eventos; Y2.1 por cadeia: stub da rota, tabela `push_assinaturas` da Y0.3), Y3.1 (fila `rapida`, `push.enviar` registrado)
  - Orçamento: ~50k
  - Pronto: CA-Y59 (parte do servidor: payload, 410, 429, silêncio, limite por hora, `push_com_pc`) verde com `webpush` falso e relógio injetado.
  - Paralelo: P1.x, C1.x, C2.x, Y3.4, Y4.2, Y6.3, Y6.6

- [x] **P2.2 Web Push no PWA** — `sw.js`: handlers `push` (`showNotification(titulo, {body,
  tag, data:{url}, icon, badge})`, **sem** botão "Confirmar" em `confirma`, DS17) e
  `notificationclick` (foca a janela ou abre `url`); `telas/ajustes.js`: interruptor de push
  (`Notification.requestPermission()` só após toque → `pushManager.subscribe` com a chave pública
  → `POST /v1/push/assinar`; desligar → `DELETE`); reassina ao abrir se a chave mudou.
  *(R9, spec §15)*
  - Lê: spec §2.2 (linha `/v1/push/assinar`), §14.6, §15 (*Assinatura*, *SW*), §16.2 (CA-Y59); `ayanami/pwa/sw.js` e `telas/ajustes.js` (P1.1/P1.4) inteiros (pequenos)
  - Escreve: `ayanami/pwa/sw.js` (só os handlers `push`/`notificationclick`), `ayanami/pwa/telas/ajustes.js` (só o interruptor de push), `tests/ayanami/pwa/test_push_sw.mjs`
  - Depende de: P1.4, P2.1
  - Orçamento: ~35k
  - Pronto: CA-Y59 (parte do PWA: notificação de `confirma` sem ação de confirmar; clique abre a `url`) verde; CA-Y57 continua verde.
  - Paralelo: —

- [x] **P2.3 Sobras do PWA (P1.2, P1.4, P2.2, P1.x)** — badge monocromático `icones/badge-96.png`
  (desenho geométrico próprio, cinza+alfa) no `ARQUIVOS` e no `push`; `pushsubscriptionchange` no
  `sw.js` reassina com o token do IndexedDB (`GET /v1/push/chave` → `subscribe` → `POST
  /v1/push/assinar`; `DELETE` da velha); push de `confirma` abre `#/confirma/<ulid>?d=&expira=`
  (servidor manda na `url` + campos `d`/`expira`; o SW completa payload antigo); `VERSAO_APP`
  centralizada em `versao.js` (= `VERSAO` do `sw.js`, conferido no teste); transcrição no
  `turno.fim` avaliada (anotada em *Sobras*).
  - Lê: *Sobras* da P1.2, P1.4, P2.2 e P1.x; `ayanami/pwa/sw.js`, `telas/ajustes.js`, `telas/confirma.js` (`rotaDe`); `ayanami/push.py` (`montar_payload`)
  - Escreve: `ayanami/pwa/sw.js`, `ayanami/pwa/versao.js` (novo), `ayanami/pwa/icones/badge-96.png` (novo), `ayanami/pwa/telas/ajustes.js` (só a `VERSAO_APP`), `ayanami/push.py` (só `montar_payload` de `confirma`), `tests/ayanami/pwa/test_push_sw.mjs`, `tests/ayanami/pwa/test_sw.mjs`, `tests/ayanami/test_push.py` (só o caso `confirma`)
  - Depende de: P2.2, P1.x
  - Orçamento: ~60k
  - Pronto: `node --test 'tests/ayanami/pwa/*.mjs'` e `tests/ayanami/test_push.py` verdes; CA-Y57/CA-Y59 continuam verdes.
  - Paralelo: Y1.3c, Y6.5b, Y6.6b, F.2

- [x] **P2.4 O PWA fecha o card de confirmação** — sobra da Y2.2b: o SSE `confirma` também fecha
  (`resposta` preenchida = respondida em outro lugar; `resposta: null` com `expira_em` vencido =
  expirou). `telas/confirma.js` ganha `fechamentoDe(c, agoraMs)`/`tagDe(pedido)`: o card aberto fecha
  com "respondida em outro lugar"/"expirou" (o eco do próprio POST em voo não conta), fechamento sem
  card não desenha nada; o assinante global do `app.js` não navega para confirmação fechada e manda
  ao SW `{tipo: "fechar-notificacao", tag: "confirma-<ulid>"}` (tag de `push._url_e_tag`); o `sw.js`
  fecha pela `registration.getNotifications({tag})`. Shell v5.
  - Lê: `ayanami/push.py` (`_url_e_tag`), `ayanami/confirmacoes.py` (fechamento)
  - Escreve: `ayanami/pwa/telas/confirma.js`, `ayanami/pwa/app.js`, `ayanami/pwa/sw.js`, `ayanami/pwa/versao.js`, `tests/ayanami/pwa/test_telas.mjs`, `tests/ayanami/pwa/test_integracao.mjs`, `tests/ayanami/pwa/test_push_sw.mjs`
  - Depende de: Y2.2b, P2.3
  - Pronto: `node --test 'tests/ayanami/pwa/*.mjs'` verde.

## Fase F — Fechamento

- [ ] **F.1 Validação ponta a ponta (precisa do Pedro)** — com tudo no `main` e no ar: critério 1
  (20 comandos por driver pela voz no PC, p90 ≤ 1,5 s), critério 2 (botão do PWA no 4G p90 ≤ 1,5 s;
  voz no PWA p90 ≤ 4 s), critério 3 (vigia rodando, disponibilidade medida), critério 4 (um restore
  completo real da Ayanami num diretório novo em ≤ 2 h, anotado em `docs/ops/ayanami-restore.md`;
  restore mensal verde), critérios 5–7 (custo, repouso do node 2, varredura de portas na IP pública),
  push com a tela bloqueada, instalação WebAPK e **uma semana de uso** (critério 8, nota do Pedro).
  Falhas viram tarefas novas no fim do `tasks.md`, não remendos aqui.
  - Lê: requirements *Critérios de sucesso*; spec §16.2 (*Validação ao vivo*); docs dos spikes S1–S6
  - Escreve: `docs/spikes/ayanami-validacao.md` (medições e a nota da semana), `docs/ops/ayanami-restore.md` (tempo real do restore), `specs/ayanami-central/tasks.md` (marcar o fechamento e *Sobras*)
  - Depende de: Y1.6 e todas as Y*, C*, P*, inclusive C1.S2 e P1.S4
  - Orçamento: ~30k do agente + uma semana do Pedro
  - Pronto: os 8 critérios de sucesso com número medido (ou decisão do Pedro registrada para o que não bater).
  - Paralelo: —

- [ ] **F.2 Documentação** — README (o que é a Ayanami, a casa e o PWA; comandos `magi-casa`,
  `ayanami`), `docs/GUIA.md` (parear TV, instalar o PWA, parear o celular, ligar o push, o que fazer
  quando "a casa está fora do ar" ou "ligue o Tailscale", Roku "Acesso à rede", Samsung "Ligar com
  celular"), `docs/PROXIMOS-PASSOS.md` (Pi D10b, TWA D4b, ADB, o que ficou dos spikes e da
  validação). Só o que a F.1 confirmou; nada de promessa.
  - Lê: `README.md`, `docs/GUIA.md`, `docs/PROXIMOS-PASSOS.md` por trecho (`grep -n "^#"`); `docs/spikes/s2-tvs-reais.md`, `s4-pwa-android.md`, `ayanami-validacao.md`; design §11, §13
  - Escreve: `README.md`, `docs/GUIA.md`, `docs/PROXIMOS-PASSOS.md`
  - Depende de: F.1
  - Orçamento: ~35k
  - Pronto: os três arquivos citam só comandos que existem (`magi-casa --help`, `ayanami --help` conferidos); links internos válidos.
  - Paralelo: —

---

## Cobertura dos critérios (CA-Y1..Y59)

| CA | Tarefa | CA | Tarefa |
| --- | --- | --- | --- |
| Y1–Y5 | Y0.1 (Y5 também na Y2.2) | Y31–Y34, Y36, Y45 | C1.1b |
| Y6, Y8, Y9 | Y2.1 | Y35 | C1.1b (local) + C1.6 (WS) |
| Y7 | Y2.2 | Y37, Y38 | C1.1c |
| Y10 | Y2.2 (casa), Y4.2 (backup) | Y39, Y58 | C1.6 |
| Y11, Y12 | Y0.3 | Y40, Y41 | C1.2 |
| Y13–Y15 | Y3.1 | Y42, Y43 | C1.3 |
| Y16 | Y3.2 | Y44 | C1.4 |
| Y17, Y18 | Y3.3 | Y46–Y49 | C1.5 |
| Y19 | Y3.4 (agente), Y3.6 (stt) | Y50 | C1.1 |
| Y20 | Y6.4 (+ frase em cache na Y6.3) | Y51 | C2.1 |
| Y21 | Y6.1 (budget), Y6.3 (modo nuvem) | Y52 | C1.1b (regras) + C2.2 (pergunta no turno) |
| Y22 | Y6.2 (gancho), Y6.5 (reconciliação) | Y53, Y54 | C2.2 |
| Y23 | Y4.1 | Y55 | P1.2 |
| Y24, Y25 | Y4.2 | Y56 | P1.1 (global) + P1.3 (controle) + P1.4 (feed) |
| Y26, Y27 | Y5.1 | Y57 | P1.1 (P2.2 mantém) |
| Y28 | Y0.2 | Y59 | P2.1 (servidor) + P2.2 (SW) |
| Y29 | Y1.1 | Y30 | C1.1 (contrato) + C1.1b (`Executor`) |

Critérios de sucesso 1–8 (ao vivo): C1.S2 (1), P1.S4 (2), F.1 (todos).

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)

- **C2.1:** `CasaCatalogo` (tvs, apps, `entradas` = apelidos do `casa.toml`) mora em
  `magi/core/router.py`; a C2.2 troca `LocalRouter.casa` quando chega o `ola` (as entradas-apelido
  não vêm no `TvInfo`: a C2.2 decide de onde tirá-las). Em en-GB, "Mais de uma TV: {nome}?" sai
  com os nomes em português ("sala ou quarto"); o "ou" não é traduzido.

- **C2.2:** (1) Contrato com a casa (C1.1/C1.1b conferem): `TV_AMBIGUA` pode trazer
  `dados["candidatos"]` (ids) — sem isso a pergunta lista todas as TVs do `ola`; a pergunta usa o
  1º apelido (ou o nome). (2) Apelidos de entrada: lidos do `casa.toml` ao lado do `config.toml`
  (`[[tv]] entradas`) quando a casa é `127.0.0.1`, e de itens `"apelido=hdmiN"` em `TvInfo.entradas`
  (para o Pi, D10b, a casa pode mandar assim). (3) `casa.token` é lido ao lado do `config.toml`
  (`~/.config/magi/`); sem ele o `TvActions` nem conecta e diz "A casa está fora do ar.".
  (4) `tv.power_off` sem `confirmed` é confirmado no PC antes de ir à casa. (5) O `GraphAgent`
  lê `spec` das ferramentas na montagem: a descrição com os nomes das TVs só aparece se o `ola`
  chegou antes (o aquecimento roda em `start_proactive`); a Y6.3 pode remontar. (6) A pergunta
  "qual TV?" usa `ARG_ESCOLHA` (função no `on_confirm.args`) + `ARG_QUIET`; o caminho "sim
  atrasado" (`_stale`) não resolve escolha de TV.

- **Y3.5:** (1) Modelo do `ayanami-voz` em `$AYANAMI_MODELOS/kokoro/<[voz] modelo>` +
  `voices-v1.0.bin` ao lado (no contêiner `/modelos/kokoro/`): a Y1.6 (deploy) põe os dois
  arquivos no volume `ayanami-modelos`. (2) `voz.cache_frases` não carrega o Kokoro no
  `worker-lento`: sintetiza por `POST` ao `ayanami-voz` (`$AYANAMI_VOZ_URL`, padrão
  `http://ayanami-voz:8741`) e transcodifica com `ffmpeg` (Opus/OGG 32k); nome =
  `ayanami.workers.voz.chave(texto)` (SHA-1 do texto UTF-8, sem a voz) — a Y6.x usa a mesma função.
  Lê `ayanami/frases.yaml` (`{nome: texto}` ou lista); o arquivo ainda não existe (dono do modo
  nuvem, §6.5): sem ele o job termina sem gerar nada. Injeção por `deps.extras` (`voz_frases`,
  `voz_sintetizar`, `voz_ffmpeg`). (3) `503` também quando a carga falha (próximo pedido tenta de
  novo); texto > 600 ou corpo > 16 KiB → `413`; resto inválido → `422`. (4) Teste opcional com o
  Kokoro real (`AYANAMI_KOKORO_REAL=1`) falha no `.venv` atual: falta `phonemizer` (dependência
  do `kokoro-onnx`; algum `uv sync` sem `--extra ayanami-ml` tirou?) — não rodei `uv sync`.
  (5) `tests/ayanami/test_fila.py::test_stubs_apontam_o_dono` falha por `noticias.coletar` (Y3.2,
  docstring sem "dono:"), não pela voz.
- **Y0.2:** (1) `ayanami-ml` fixa `kokoro-onnx==0.6.1` e `onnxruntime==1.30.0` (as do PC), não
  `0.4.7`/`1.31.0`: o `uv.lock` é um só e os pinos da spec rebaixariam o Kokoro do PC (audiolivro).
  A Y3.5 usa a API do 0.6.1. (2) Sem `tests/ayanami/__init__.py`: com `--import-mode=importlib` ele
  vira o pacote `ayanami` e esconde o pacote real; `tests/ayanami/` fica sem `__init__` (as próximas
  tarefas não criam um). (3) `ayanami batimento` despacha para `ayanami.worker:cli_batimento(args)`
  (Y3.1), não `cli`; todos os donos recebem a lista crua de argumentos depois do subcomando e
  devolvem `int | None`. (4) Extras via `[project.optional-dependencies]`: `uv sync --extra ayanami
  [--extra ayanami-ml]`. (5) Segredos: `config.ler_segredos(cfg, arquivo=None, env=None)` →
  `Segredos` (`faltando` por fase: `OPENAI_API_KEY` só com nuvem ligada e `teto_nuvem_usd > 0`;
  B2/restic só com `[backup] ligado`). `[noticias]` aceita `fontes`, `timeout_s`, `embedder`.
- **Y1.1:** (1) DSN: o compose dá `PGHOST=ayanami-pg`, `PGPORT`, `PGUSER=ayanami`, `PGDATABASE=ayanami`
  e o `.env` dá `POSTGRES_PASSWORD`; quem monta o DSN (Y0.3 `ayanami/db.py`, Y3.1 `fila.py`) usa
  essas variáveis libpq + `POSTGRES_PASSWORD` (sem `PGPASSWORD` no compose, para a senha não sair no
  `docker compose config`). (2) Imagem: `${AYANAMI_IMAGEM:-ayanami}:${AYANAMI_TAG:-local}` (leve) e
  `…-ml` (lento/voz, `--build-arg AYANAMI_ML=1`), com `build: ../..` para a A1; a Y1.2 (`deploy.sh`)
  usa `docker compose pull --ignore-buildable` (ou `build`) enquanto não houver ghcr, e a Y1.4 publica
  as duas tags. (3) A imagem pula `pyside6*`, `shiboken6` e `evdev` (`--no-install-package`): são do
  PC e o `evdev` não tem wheel. (4) `docker.sock` no `worker-agendado` com `group_add:
  ${DOCKER_GID:-988}`; a Y1.2 (`preparar.sh`) grava o GID real do grupo `docker` em `DOCKER_GID` no
  `.env`. A imagem traz o binário `docker` (CLI, de `docker:27.5.1-cli`), `restic`, `curl`; a `-ml`
  traz `ffmpeg`. Sem `postgresql-client` (o do Debian é 15): backup do pg por `docker exec ayanami-pg
  pg_dump` (Y4.2). (5) `ayanami-modelos` em `/modelos` (`HF_HOME=/modelos/hf`, `AYANAMI_MODELOS`);
  `ayanami-pg` tem `container_name: ayanami-pg`. Imagem leve ≈ 1,2 GB (build local ok).
- **Y0.3:** (1) A 005 faz `tests/learning/test_interview_store.py::test_migracao_no_fixture_nao_muda_tabelas_003`
  (`db`) falhar: a linha 266 espera `== ["004"]` e agora vem `["004", "005"]`. Arquivo fora do
  *Escreve*; correção de uma linha: `== ["004", "005"]`. (2) `ayanami.db.dsn_padrao()` usa
  `AYANAMI_DB_DSN`, senão `POSTGRES_PASSWORD` + `PGHOST`/`PGPORT`/`PGUSER`/`PGDATABASE` (as do
  Compose da Y1.1). `ayanami.db.recusar_magi(dsn)` (porta 54329 ou base `magi`) vale para o
  `ayanami migrar` e o fixture. (3) `001_base.sql` ganhou `costs_at_idx` (o `costs` do PC tem). (4)
  Fixtures em `tests/ayanami/conftest.py`: `pg_dsn`, `pg_nova_base()` (fábrica de bases vazias),
  `pg_base` (001–002), `pg_base_pc` (migrações do PC até a 005, para a Y3.3) e `pg` (conexão). (5)
  `psycopg_pool` (extra `ayanami`) só é importado em `abrir_pool`; o teste do pool roda com
  `uv run --extra ayanami` ou `--with psycopg-pool` e pula sem ele. (6) A 005 foi validada numa
  cópia só-esquema (`pg_dump -s`) do `magi-pg` restaurada no `ayanami-pg-teste`: aplica só a `005`,
  2ª vez não faz nada. Os testes `db` de `tests/memory/` rodaram com `MAGI_DB_DSN` no
  `ayanami-pg-teste` (verdes), sem tocar no `magi-pg`.
- **C1.1:** (1) Fábrica dos drivers: cada `magi/casa/drivers/<nome>.py` expõe
  `criar(tv: TvConfig, ctx: ContextoDriver) -> TvDriver`; `TvConfig` (uma `[[tv]]`) e
  `ContextoDriver` (`broadcast`, `apps`, `dir_pareamento`, `relogio`) moram em `driver.py`, que as
  C1.2–C1.4 já leem. `drivers.criar_driver(tv, ctx)`; módulo ausente ou sem `criar` → `DriverAusente`.
  (2) `RelogioFalso` (`relogio()`, `avancar`, `async dormir`) está em `magi/casa/falso.py`, não no
  conftest, para as C1.1b/C1.1c/C1.x importarem. `DriverFalso` levanta a exceção do script (quem
  converte é o chamador) e aceita lista (consumida, a última repete) ou chamável sync/async.
  (3) Config da casa: `magi.casa.config.CasaConfig`/`ler`/`salvar`/`validar`/`tv_info`/`normaliza` e
  os caminhos (`caminho_casa`, `caminho_token_local`, `dir_pareamento`, `caminho_estado`…), via
  `XDG_*` com recaída em `~`; não confundir com o `CasaConfig` da C2.2 em `magi/common/config.py`
  (seção `[casa]` do `config.toml` do PC). `padrao` numa TV ignorada vira `""` com log.
  (4) Fora do *Escreve*: `hud/install.sh` não instala `magi-casa.service` (lista `UNIT_FILES` fixa);
  a unit não foi instalada nem habilitada. Verificada com `systemd-analyze --user verify` numa
  cópia com `@REPO@` trocado. (5) As deps da casa entraram em `dependencies` (o PC roda a casa);
  um `uv sync` puro remove os extras `ayanami`/`ayanami-ml` do `.venv` — use
  `uv sync --extra ayanami --extra ayanami-ml`.
- **Y0.5:** (1) Montagem no próprio `ayanami-api` confirmada (28/28 em `spikes/ayanami_s3_mcp.py`,
  detalhes em `docs/perf/ayanami-s3.md`); bloco da §8 corrigido. (2) Fora do *Escreve*: a nota da
  §8 (`claude mcp add … https://ayanami.<tailnet>.ts.net/mcp`) deve usar **`/mcp/`** (com barra):
  `/mcp` leva 307 e, atrás do `tailscale serve`, o `Location` sai `http://` e o cliente recusa o
  downgrade (ou uvicorn com `--proxy-headers --forwarded-allow-ips=127.0.0.1`) — a Y1.6 confere e
  corrige a nota/design §4.5. (3) Y5.1: lifespan do FastAPI entra em `mcp.session_manager.run()`;
  `allowed_hosts` precisa do host do tailnet (`[ayanami]` dá a URL base); `mcp` 2.3.0 já está no
  `uv.lock` (sem `--with`).
- **C1.3:** (1) `RokuDriver.power` confirma sozinho: depois do `PowerOn`/`PowerOff` relê
  `device-info` a cada 0,5 s por até 7 s (abaixo dos 8 s do `Executor`) e já devolve o motivo
  (`SEM_MAC`, `REDE_DESLIGADA` depois do WOL, `STANDBY_PROFUNDO` com a dica do *Início rápido da TV*,
  `ACESSO_NEGADO`); a C1.1b pode pular a própria sondagem para o Roku. (2) `mute(True/False)` →
  `NAO_SUPORTADO` (o Roku não informa o mudo); o `Executor` emula com `mute(None)` (alterna).
  `VOL_SET` vem em `capacidades.emula` só na Roku TV. (3) Caps começam como player (`KEY APP TEXT
  STATE`) e viram as reais no `conectar()` (lê `device-info`). (4) Usa `rokuecp.Roku._request`
  (privado; versão fixada 0.19.5) porque o `literal()` da lib codifica espaço como `+`, e a spec
  pede `Lit_%20`. (5) Sem sessão `aiohttp` compartilhada no `ContextoDriver`: o driver aceita
  `session=` e, sem ela, a `rokuecp` abre a sua (fechada no `fechar()`).
- **C1.4:** (1) `magi.casa.drivers.androidtv.parear(tv, ctx, pedir_codigo, *, fabrica, gerar_cert,
  prazo_s=120, tentativas=3) -> ResTv` faz o fluxo da §12.3 (a C1.5 só orquestra e lê o código com
  eco desligado): cert/key gerados direto em `0600` (`os.open`, não pelo
  `async_generate_cert_if_missing`, que grava com a umask) em `<id>.atv.crt|.key.novo`, renomeados
  só com o código certo; errado 3× → `ACESSO_NEGADO`, cancelado na TV → `ACESSO_NEGADO`, prazo →
  `TEMPO_ESGOTADO`, sempre sem gravar. Cada código errado reinicia o `async_start_pairing` (a TV
  mostra código novo). `caminhos_cert(tv_id, dir)` também é público. (2) O driver troca
  `capacidades` por uma cópia com `vol_max = volume_info.max` quando ele chega: a emulação de
  `VOL_SET` (C1.1b) deve converter passos com `vol_max` (1 tecla = 100/`vol_max` na escala 0–100).
  (3) `mute(True/False)` com mudo desconhecido alterna e devolve `emulado=True, detalhe="alternado"`.
  (4) `power` espera a confirmação pelo callback `is_on` até 8 s; sem ligar → `STANDBY_PROFUNDO`.
  (5) Construtor aceita `fabrica`, `dormir` e `agora` injetados (testes sem rede).
- **C1.1b:** (1) `Executor(cfg, drivers, *, estados, fila, relogio, dormir, prazos)`; `estados`
  (`tv_id → EstadoTv`) é o cache da regra 4 da §13.3 ("só uma ligada"): a C1.1c deve passar o mesmo
  dicionário que a sondagem atualiza (hoje o `servir.executor_padrao` chama só `Executor(cfg,
  drivers)`). `rodar(req, *, origem="local")` loga `acao` com a origem. (2) `TV_AMBIGUA`: ids
  candidatos em `ResTv.detalhe` separados por vírgula; `magi.casa.emula.candidatos(res)` os devolve —
  a C1.1c põe em `dados["candidatos"]` (contrato da C2.2). (3) Intents do controle remoto além da
  §13.1, constantes em `emula.py`: `tv.channel` (args `step`), `tv.key` (args `key` = valor de `Key`),
  `tv.text` (args `texto`), `tv.state` (devolve `estado`); a P1.x/C1.5 (`testar`) usam esses. (4)
  Emulação abortada por outra `acao` → `OCUPADA` com `detalhe="interrompida por outra ação"`,
  `emulado=True`; repetição coalescida → `ok` com `detalhe="coalescida"` (sem chamar o driver).
  (5) Emulação só quando a cap está em `capacidades.emula` (Roku player sem `VOL_SET` ali →
  `NAO_SUPORTADO`). Mudo: desconhecido → `mute(None)` direto (1 tecla); conhecido e diferente →
  `mute(on)` e, se `NAO_SUPORTADO` (Roku), `mute(None)`. (6) Prazo: `asyncio.wait_for` real **e**
  conferência pelo relógio injetado (driver falso que "dorme" no `RelogioFalso` estoura igual);
  estouro → `fechar()` e `conectar()` antes da próxima chamada daquela TV.
- **Y0.4:** (1) A linha DS9 do resumo da spec (linha ~48, fora do trecho da Y0.4) ainda diz "cron
  segue o TZ"; o S5 mostrou que não: os crons da §4.2 já estão em UTC (local + 3 h); falta trocar o
  texto da DS9. (2) Para a Y1.x (compose): `stop_grace_period` ≥ 35 s nos três workers (graceful de
  30 s da §4.1). (3) Para a Y3.1: `fila.reanimar` = `get_stalled_jobs(seconds_since_heartbeat=300)` +
  `retry_job`; estado de `tarefas` por `worker_middleware` (não há `on_job_status`); detalhes em
  `docs/perf/ayanami-s5.md`.
- **Y4.1:** (1) Card "backup não subiu": não há canal fora do `magi-core` para o HUD; o
  `magi-backup` grava `<data_dir>/backup_state.json` (`resultado` `ok`/`ja_recebido`/`falhou`/
  `desligado`, `erro`, `data`, `tentativas`), como o `magi-clean` faz com `cleanup_state.json`.
  Falta o `AlertMonitor` (`magi/core/proactive/alerts.py`, fora do *Escreve*) ler esse arquivo e
  entregar o card quando `resultado == "falhou"` (uma vez por `quando`). (2) Config do PC: URL em
  `[ayanami] url` e token do PC (escopo `backup`) em `~/.config/magi/ayanami.token` ao lado do
  `config.toml` (excluído do tar por `*.token`); sem um dos dois o backup fica desligado (sai 0). A
  Y3.3 (`[ayanami]` no `config.example.toml`) e a Y6.2 devem usar os mesmos nomes. (3) Tentativas:
  1ª + 3 repetições (esperas 1/5/15 min) em rede fora, `5xx`, `400`, `408`, `425`, `429`;
  `401`/`403`/`413` falham na hora. (4) Temporário em `~/.cache/magi/magi-backup-*` (o `/tmp` é
  tmpfs), apagado sempre. `pg_versao` vem de `docker exec magi-pg pg_dump --version`; tabela que
  não existe vira `null` no manifesto (a Y4.2 deve tratar `null` como "não comparar"). (5) Fora do
  *Escreve*: `hud/install.sh` não instala `magi-backup.{service,timer}` (lista fixa); units não
  instaladas nem habilitadas (Y4.3).
- **Y3.3:** (1) Fora do *Escreve*: falta a entrada `magi-news-sync = "magi.elo.news_sync:main"` no
  `pyproject.toml` e as units novas na lista `UNIT_FILES` do `hud/install.sh`; por isso as units
  chamam `"@REPO@/.venv/bin/python" -m magi.elo.news_sync` (o `ExecCondition` funciona sem `uv
  sync`). (2) Helper único `magi/elo/credenciais.py` (pedido do orquestrador): `url_ayanami(cfg)`
  (dict cru ou `Config.raw`) e `token_pc(config_dir=None, *, keyring_get=None)` — keyring
  `magi`/`ayanami_pc` primeiro, recaída `ayanami.token` ao lado do `config.toml`. A Y6.2 usa; o
  `magi/elo/backup.py` (Y4.1) ainda lê o arquivo sozinho: trocar pelo helper depois. (3) `NEWS_DIM`
  lido do banco (`atttypmod` de `news_items.embedding`). Item local (sem `ayanami_uid`) que cite
  uma crua do item da nuvem é adotado (ganha o uid, mantém `delivered_at`): a recaída não entrega
  a mesma notícia de novo. (4) `--precisa-local` com erro inesperado ou sem `[ayanami]` sai 0
  (coleta local); um `ImportError` do módulo sairia 1 e pularia a coleta — imports pesados são
  locais para isso não acontecer. Falha no `PUT /v1/noticias/preferencias` só registra (exit 0).
- **C1.1c:** (1) Interface do executor: `magi.casa.local.Executor` (`Protocol`, `async rodar(req:
  ActionRequest) -> ResTv`); o `servir` monta `magi.casa.emula.Executor(cfg, drivers)` (recaída
  `NAO_SUPORTADO` se o módulo faltar). O `Executor` da C1.1b tem o próprio `estados`; o
  `EstadoCasa` (`magi/casa/estado.py`) só recebe o `ResTv.estado` de cada `acao` e a sondagem — a
  C1.5/C1.6 pode unificar (`Executor(estados=…)` com aviso aos ouvintes). (2) Caps do `ola` saem de
  `driver.capacidades.anunciadas()`; as emuladas só aparecem se o driver/Executor as puser em
  `capacidades.emula`. (3) `AcaoResultado.dados["tv"]` = `ResTv.estado.id` ou o slot `tv`;
  `precisa_confirmar` = motivo `PRECISA_CONFIRMAR`; `detalhe` cortado em 200. Prazo de segurança
  `local.prazo_s(acao)` = `prazo_ms` (acima dos timeouts do `Executor`). (4) Idempotência: um
  `Receptor` por servidor (reenvio da mesma `acao` depois de reconectar não roda 2×); cada linha
  roda em tarefa própria (respostas fora de ordem, casadas por `resp`). (5) Android TV é lida a
  cada 5 s (`estado.INTERVALOS`, lê o cache dos callbacks); demais 30 s. (6) `servir` também recusa
  `casa.token` mais aberto que `0600`. (7) Fora do *Escreve*: `tests/casa/test_contrato.py`
  (`test_magi_casa_stubs_apontam_o_dono` chamava `main([])` esperando o stub — com o `servir` real
  ele subia a casa na 10760 de verdade; agora troca o `servir` por um falso).
- **Y6.2:** (1) `CoreService.anexar(link, *, pipeline, hud, followup_ms=None)` guarda o `TurnMachine`
  do celular em `_remotos`, **fora** de `satellites`: a proatividade (`targets[0].announce`) e o
  clique no rosto nunca vão ao celular; `service.machine("celular")` acha. HUD do turno do celular =
  `NullHud` (não mexe no rosto do PC nem mostra o card lá). (2) `[ayanami]` no PC: só `url`
  (`magi.elo.credenciais.url_ayanami`) + token `token_pc()`; sem URL/token → aviso e segue sem elo.
  O bloco `[ayanami]` do PC no `config.example.toml`/spec §16.1 não foi escrito (fora do *Escreve*).
  `NoPc` liga em `run()` (`core.ayanami.iniciar(service)`) e fecha em `Core.aclose`. (3) Para a
  Y6.4: `TurnoFim` sai **antes** da fala (gancho antes do `speaker.say`), então `audio=True` só com
  fala antecipada; o áudio vem depois em `AUDIO_OUT` e cada `play` fecha com `AUDIO_FIM` (fala com
  lotes antecipados pode ter mais de um `AUDIO_FIM` no turno). `Turno` com outro em andamento →
  `TurnoFim(erro="ocupado")`; erro inesperado → `erro="interno"`; prazo 45 s → `"tempo"` e a fala
  atrasada é descartada. (4) Stubs com classes injetáveis por `core`: `EventosPc(core).evento/
  confirma`, `Reconciliador(core).gravar_resumo(resumo) -> tuple[str, ...]` (o `NoPc` responde
  `Ack(ids=…)`), `CustosPc(core, cliente).rodar()/total_mes()` (o `Bate` usa `total_mes()` ou, sem
  ele, o gasto do `Budget` local relido a cada 60 s). (5) Fora do *Escreve*:
  `tests/hud/test_overlay_install.py::test_templates` falha no working tree (não é desta tarefa).
- **Y2.1:** (1) Stubs por `auth.rota_stub(router, método, caminho, dono)` (autentica pela linha de
  `ESCOPO_DE_ROTA` e dá `501`); o `/ws` é um `GET` HTTP no stub — a Y2.2 troca por rota WebSocket
  sem mexer na tabela. `/mcp` fica fora da tabela (verificador próprio da Y5.1). (2) Ganchos no
  `app.state.ctx` (`Contexto`): `auth.ao_revogar` (lista de `fn(Dispositivo)`, chamada na revogação
  pela API), `extras` (hub da Y2.2; `extras["online"]` = `() -> dict` substitui o `online` do
  `/saude`), `ciclo` (fábricas de `AsyncContextManager` que o lifespan abre: a Y5.1 põe
  `mcp.session_manager.run` e faz `app.mount("/mcp", …)`). (3) `ayanami dispositivo revogar` roda
  noutro processo: o REST recusa em ≤ 5 s pelo TTL do cache, mas fechar WS/SSE na hora precisa de
  sinal entre processos (NOTIFY ou varredura de `revogado`) — decisão da Y2.2. (4) `/saude`: `ok` =
  banco ok e `faltando` vazio; `workers` por nome da fila (`workers_batimento`); `failed_24h` lê
  `procrastinate_events` (conferir o esquema na Y3.1); `restic` = `max(backups.enviado)`; `online`
  do `pc`/`casa` por `dispositivos.visto` dentro de `offline_apos_s`, celulares por `ultimo_uso`.
  (5) FastAPI 0.143 inclui roteadores de forma preguiçosa (`app.routes` só mostra
  `_IncludedRouter`): teste de rotas lê `mod.router.routes`. (6) Pareamento: `409` não gasta o
  código; o 10º erro dá `429 codigo_morto` e mata o código; erro em `{"erro","msg"}` também para
  `404`/`405`/`422` (`invalido`). Fixtures em `tests/ayanami/api/conftest.py`: `fazer_app(db, **kw)`,
  `cliente(app, token=None, ip=…)`, `db` (base nova por teste), `db_fora`, `novo_token`, `relogio`.
- **C1.2:** (1) Keyring: o nome da §11.1 (`casa/<id>/samsung`) não passa no `_NAME_RE` de
  `magi/common/secrets.py` (sem `/`); o driver usa `casa.<id>.samsung` (serviço `magi-assistant`).
  Quem escreve o pareamento (C1.5/`magi-casa parear`) usa o mesmo nome. (2) `SamsungDriver(tv, ctx,
  *, portas, tls, dormir, enviar_wol, ler_segredo, gravar_segredo, sessao)`: `portas` mapeia a porta
  lógica (8002/8001) para a real (testes); `criar(tv, ctx)` usa os padrões. (3) O driver confirma
  `power` sozinho (sonda a REST a cada 500 ms até 8 s, relógio do `ctx`), devolvendo `REDE_DESLIGADA`/
  `STANDBY_PROFUNDO`/`SEM_MAC`; desligar já em standby → `ok` sem tecla; desligar sem REST → `OFFLINE`.
  `mute(True/False)` e `volume(set_to=)` → `NAO_SUPORTADO` (emulação é do `Executor`).
  (4) `_Remote.open` reescreve o da lib: a lib deixa o socket aberto quando a TV recusa
  ("Permitir") e loga o token; aqui fecha e não loga (logger `samsungtvws` em WARNING).
  (5) `Key.PLAY_PAUSE` → `KEY_PLAY` (Tizen não tem alterna confiável; validar na F.1).
- **Y1.3b:** (1) Falta a rota/tool da Ayanami que lê `/opt/ayanami/dados/servidor.json` para
  responder "como está o servidor?" (o JSON já tem `cpu`, `load`, `ram`, `swap`, `minecraft` com
  status/RestartCount/jogadores/nomes/TPS, `alertas` e `ts`; é reescrito a cada minuto). (2) A 1ª
  leitura não tem % de CPU (precisa de duas amostras do `/proc/stat`) nem alerta de reinício (só
  guarda o `RestartCount`). (3) TPS é a média de 1 min do `spark tps`; RCON fora/senha errada só
  aparece no resumo (`rcon: "erro (…)"`), sem alerta. (4) `docker` ausente ou falhando → resumo
  `minecraft: {"status": "erro"}` sem alerta. (5) Requer o Minecraft com `enable-rcon=true` e RCON
  só em 127.0.0.1 (conferir na Y1.6).
- **Y1.3:** (1) A `/saude` (Y2.1/Y4.2) ainda não expõe "job de backup `falhou`" nem "restore de
  teste vermelho": o vigia lê, se vierem, `backup_falhou: true` e `restore_teste: {"verde": false,
  …}` no JSON; o dono da `/saude` acrescenta esses campos. (2) `ultimo_backup.pc/ayanami` nulo conta
  como atrasado (alerta 1×/6 h até o 1º backup). (3) Só `/saude` sem `200`/JSON conta como falha;
  `200` com `ok=false` (segredo faltando) não alerta. (4) Sem `docker`: tudo vem da `/saude` e do
  `statvfs` (`/` e `/opt/ayanami/dados`). Instalar as units fica na Y1.6 (Pedro).
- **Y1.2:** (1) Layout: `/opt/ayanami` é o clone; `.env`, `ayanami.toml` e `dados/` reais ficam em
  `/opt/ayanami/` e o `preparar.sh` cria links `deploy/ayanami/{.env,ayanami.toml,dados}` para eles
  (o `compose.yml` usa `build: ../..` e lê tudo ao lado dele) + `.git/info/exclude`. (2) `deploy.sh`:
  `git pull --ff-only` → `pull --ignore-buildable` → `build` só sem `AYANAMI_IMAGEM` (env ou `.env`)
  → `--profile ops run --rm migrar` → `up -d` → `/saude` (30×2 s); `--tag X` grava `AYANAMI_TAG` no
  `.env` (rollback), `--sem-git`. A Y1.4 chama `deploy.sh` como o usuário `ayanami`. (3)
  `limpar-multivideos.sh` exige `--host-esperado` e `--ip-esperado` (do painel, fora do repo) e
  aborta antes de ler qualquer coisa se não baterem ou se houver contêiner rodando com
  `multivideos|wedding|gold`; é o único script com `docker volume rm` (só volumes `ollama|whisper`
  sem contêiner, nunca `ayanami|magi`), e o teste estático tolera só esse. (4) Sem `shellcheck` no
  PC: só `bash -n` + execução com falsos no PATH. (5) Runbook: o `run --rm migrar <outro comando>`
  para `restic snapshots` não foi conferido (o `migrar` pode ter comando fixo); a Y1.6 confere ou
  usa `exec worker-agendado`. Keyring do token do PC segue a Y3.3 (`magi`/`ayanami_pc`), não o
  `magi-keys` do design §10.3.
- **C1.5:** (1) Revalidação no `servir`: só a ativa, a cada `descoberta_min` (relê o `casa.toml`,
  descobre e grava o IP novo de forma atômica); a passiva contínua (SSDP NOTIFY/mDNS) não foi feita.
  Os drivers já montados seguem com o IP antigo até reiniciar: `revalidar_periodicamente(ao_mudar=…)`
  existe para a C1.6 recriar o driver. (2) Sobras da C1.1b: o `estados` do `Executor` agora acompanha
  a sondagem (`servir._ligar_estados`, ouvinte do `EstadoCasa`); `candidatos(res)` em
  `dados["candidatos"]` fica para a C1.6 (é no `local.py`, fora do *Escreve*). (3) O pareamento
  Samsung usa privados do driver da C1.2 (`_novo_remote`, `_guardar_token`, `_res_erro`,
  `_pode_8001`, `samsung._recusada`) para abrir a WS sem token com prazo de 60 s (o `conectar` tem
  3 s); keyring `casa.<id>.samsung`. Android TV usa `androidtv.parear`/`caminhos_cert` (C1.4). (4) CLI:
  `descobrir` grava `~/.local/state/magi/casa-descobertas.json` (sem segredo) e o `nomear <nº|chave|IP>
  <id> [nome] [--apelido A] [--padrao] [--driver D]` lê dali; `testar <tv> <acao> chave=valor…`
  (slots `volume`/`app`/`input`, args `step`/`key`/`texto`) roda sempre com `confirmed=True`; `estado`
  lê o `casa-estado.json` (`--sondar` pergunta às TVs); `esquecer <tv> [--manter-config]`.
  (5) O filtro do log (C1.1) descarta campos chamados `chave`: a descoberta loga `ip`/`tv`. As fontes
  reais `ssdp_real`/`mdns_real` nunca rodam nos testes: validar na C1.S2/F.1. (6) Fora do *Escreve*:
  `tests/casa/test_contrato.py` (a asserção do stub `testar` esperava "dono: C1.5").
- **C1.6:** (1) `magi/casa/saida.py`: `SaidaAyanami(url, token, executor, estado, catalogo, *, versao,
  periodo_estado_s=60, relogio, dormir, agora, **elo_kw)` embrulha o `EloCliente` (Y2.4): `ola` com
  `tvs`/`apps` remontado a cada conexão, `acao` → mesmo `Executor` (`rodar(req, origem="ayanami")`
  quando aceita) → `acao_ok`, `estado` vazio → `estado`, `estado` empurrado a cada mudança (ouvinte do
  `EstadoCasa`) e a cada 60 s; token revogado → `ayanami_token_revogado` (log da casa) e a API local
  segue. Token: `ler_token()` lê `ayanami-casa.token` (recusa mais aberto que `0600`) e depois o
  keyring `casa.ayanami` (sem `/`, como na C1.2). O `servir` só liga com `[casa] ayanami` + token
  (sem token: `ayanami_sem_token`); `servir_async(saida_kw=…)` repassa ao `EloCliente` (testes).
  Recaída `/v1/longpoll` precisa de `http` (`httpx.AsyncClient`) no `EloCliente`: o `servir` ainda não
  passa um, então hoje a casa fica só na WS — ligar na P1.S4/F.1 junto com a API real (Y2.2).
  (2) Sobras da C1.1b/C1.5 feitas: `dados["candidatos"]` (lista de ids) no `local.resultado_de_res`
  quando `TV_AMBIGUA` (vale para a API local e a WS); `servir.trocar_drivers` recria o driver da TV
  cujo IP/MAC mudou (gancho `ao_mudar` da revalidação), fecha o antigo e troca no `Executor` (mesmo
  dict, `executor.cfg = novo`) e no `EstadoCasa.drivers`. (3) CA-Y58 (`pytest -m lento
  tests/casa/test_recursos.py`, processo próprio, 3 `DriverFalso`, 600 s): CPU médio 0,003%, RSS 34,4 MB (meta ≤ 1% e ≤ 80 MB). O marcador `lento`
  não está registrado no `pyproject.toml` (fora do *Escreve*): dá `PytestUnknownMarkWarning`; o teste
  pula sozinho sem `-m lento`. Registrar em `[tool.pytest.ini_options] markers` numa limpeza.
- **Y3.1:** (1) Contrato do corpo: `async def corpo(deps, contexto, **kwargs) -> dict | None`; o
  `Deps` chega por `run_worker_async(additional_context={"deps": deps})` e `fila.registrar` embrulha
  com `asyncio.timeout` (estouro → `PrazoEstourado`, nunca repetido pela `fila.Repeticao`). Jobs de
  `tarefas` recebem só `tarefa_id` (lêem `params` do banco); o retorno `{"texto","dados"}` vira
  `resultado` pelo middleware `tarefas.on_job_status(deps)`. Abort do usuário (`CancelledError` com
  `AbortReason.USER_REQUEST`) vira `JobAborted` (sem retry; a lib repetiria um `CancelledError`). (2)
  Contradição na spec: `voz.cache_frases` é periódica (cron `0 6 * * 1`) mas da fila `lenta`, e o
  CA-Y13 diz "nenhuma periódica fora da `agendada`". Ficou na `lenta` (precisa da imagem `-ml`); só o
  worker `agendada` monta o app com periódicas (`montar(periodicas=False)` nos outros), então só ele
  defere o cron. O teste aceita essa única exceção. (3) `a` da §4.2 = `RetryStrategy(max_attempts=a)`
  da lib, que conta **repetições** (a=2 → até 3 execuções); `a=1` = sem retry. (4) O evento
  `tarefa_falhou` é gravado direto em `eventos` + `NOTIFY ayanami_eventos` (`tarefas.criar_evento`);
  a Y2.3 pode trocar por `ayanami.eventos`, e o `push.enviar` depois do evento fica para a P2.1/Y2.3.
  (5) Monitor: `criar_tarefa` grava `agenda=agora`, `expira=agora+expira_dias` e defere já o 1º
  `monitor.passo` com `lock="monitor:<id>"`; a Y3.4 decide o resto. (6) A API acha a fila em
  `ctx.extras["fila"]` (testes) ou abre o app de produção no 1º uso (`fila.app_aberto`); ninguém o
  fecha no fim (o `app.py` é da Y2.1/Y5.1: pôr `app.open_async` em `ctx.ciclo` se fizer falta).
  (7) `workers_batimento.fila` = nome da fila (`rapida`…); healthcheck do Compose: `ayanami batimento
  <fila> --max 90` (0 ok, 1 velho/ausente, 2 banco). (8) Limpeza: `confirmacoes` e `pareamentos` pela
  `expira`; jobs pelo último `procrastinate_events.at`; `tarefas` não são apagadas (a §3 não pede).
- **Y2.2:** (1) O hub nasce preguiçoso em `hub_de(ctx)` (`ctx.extras["hub"]`; a `app.py` é da
  Y5.1) e se liga a `auth.ao_revogar`; `confirmacoes_de(ctx)` fica em `extras["confirmacoes"]`.
  `extras["online"]` não é usado: a `/saude` segue por `dispositivos.visto`, que o hub grava no
  `ola`/`bate` (e a cada `GET /v1/longpoll`, que não manda `bate`). (2) Revogação feita por outro
  processo: enquanto houver conexão aberta, o hub varre `dispositivos.revogado` dos conectados a cada
  2,5 s e fecha com `4001` (≤ 5 s); a Y2.3 pode fazer igual no SSE. (3) `/ws` é rota WebSocket com
  `methods=set()` + `GET /ws` HTTP que dá `426`, para a tabela da Y2.1 seguir batendo; recusa do
  upgrade por `send_denial_response` (401/403); sem `ola` válido em 5 s fecha com `4003` (código
  não fixado na spec). Quadros binários na WS são ignorados por ora (Y6.x liga ao turno).
  (4) `casa.pedir_acao(ctx, disp, tv, pedido, origem)` é a chamada interna para a Y5.1: origem
  `"mcp"` + `danger` do `intents.yaml` sem `confirmed` → `202 {"confirma"}`; no "sim" o executor
  `"casa.acao"` roda com `confirmed=True`. A pergunta vai ao PC por `confirma` (espera 30 s; resposta
  por `resp` ou depois pelo `ao_receber(CONFIRMA)`); a entrega pelo SSE é da Y2.3. `POST
  /v1/confirma/{pedido}` → `{"pedido","resposta","resultado"}`; `404` se não existe. (5) Auditoria
  só no `POST /v1/casa/acao` (e no `acao_ok` atrasado); o `GET /v1/casa/estado` não audita (o PWA
  consulta toda hora). (6) `pc_caiu` no meio do turno (§6.1) fica para a Y6.4 (`hub.destino`/
  `online`/`ativo`). Uma conexão long-poll vira a ativa e fecha a WS com `4002`.

- **Y3.6:** (1) Fora do *Escreve*: `ayanami/api/limites.py` ganhou `"/v1/tarefas": 201 MiB` em
  `CORPO_POR_ROTA` (sem isso o `LimiteCorpo` cortava o upload em 256 KiB); a própria rota segura o
  JSON em 256 KiB e o áudio em 200 MB (`api/tarefas.STT_MAX_BYTES`), contando no fluxo. (2) O
  middleware `tarefas._resultado` (Y3.1) corta `resultado.texto` em 6000 caracteres: a transcrição
  devolve até 200 mil, mas só 6000 ficam no banco até o dono subir o corte para o `stt` (o arquivo
  `stt/<id>.txt` só existe acima de 200 mil). (3) Upload: multipart `tipo`, `titulo`, `arquivo`
  (+ `chave`/`pessoal`/`avisar`), gravado em `ctx.extras["dados"]` (padrão `/dados`)`/tmp/<uuid>.<ext>`
  e `params={"arquivo": nome}`; `stt` por JSON → 422. (4) O áudio é apagado no `finally` em sucesso,
  falha final, prazo e abort; fica só quando a fila vai repetir (a=2) ou no desligamento do worker.
  Áudio órfão em `tmp/` (API caiu entre gravar e criar) não tem varredura: a `limpeza.diaria` pode
  apagar `tmp/` > 2 dias. (5) Textos longos vencidos (`/dados/stt/*.txt` > 7 dias) são apagados no
  início de cada `stt.transcrever` (`stt.limpar_textos`); a `limpeza.diaria` pode chamá-la também.
  (6) `embeddings.lote(textos, tipo)` devolve os vetores em `dados.vetores`; quem grava em
  `vector(384)` fica para a A8. Modelos em `/dados/modelos/{whisper,fastembed}`.
- **Y3.2:** (1) `magi/news/__main__.py` não mudou: `run_once(config, dsn)` já aceita qualquer DSN e o
  `PgNewsRepo` só usa as tabelas da `002`. O DSN do job vem de `deps.extras["dsn"]` (testes) ou
  `db.dsn_padrao()`, com `recusar_magi`. (2) `[noticias]` → `Config`: `fontes` = nomes das fontes
  padrão (as outras ficam `enabled = false`); `embedder = {provider, model, free_tier, keys, …}` →
  `[providers.<p>]` + `[tasks.news]`; o `magi-news` já recusa provedor que não seja `free_tier`. As
  chaves vêm do keyring do contêiner: falta decidir como o `.env` chega ao `Registry` (Y6.1/Y3.4).
  (3) `noticia_bomba`: `level = 'bomba'`, tocado nesta coleta (`atualizado ≥ clock_timestamp()` do
  início), `first_seen` ≤ 48 h, obra não largada, uma vez por `ref = noticia:<uid>`; manchete sem
  spoiler (`safe_title` ou "Tem notícia de X com spoiler", sem resumo). Evento por
  `tarefas.criar_evento` (a Y2.3 pode trocar por `ayanami.eventos`). (4) Cursor com microssegundos
  (`…T20:00:00.000500Z|8812`), opaco para o PC. Risco conhecido: linha gravada por transação longa
  com `atualizado` anterior a um cursor já servido seria pulada (o `PgNewsRepo` é autocommit, então
  hoje não acontece). (5) `PUT /v1/noticias/preferencias`: `franchise_prefs` do PC substitui a da
  Ayanami; `progress` por *upsert* sem regredir (`updated_at` mais novo fica). (6) `progresso.atualizar`
  = `update_if_due` + `score_pending` com o relógio do `Deps`, sem `Registry`.
- **Y6.1:** (1) `BudgetNuvem(db, relogio, *, teto_nuvem_usd, teto_geral_usd, preco=None)` /
  `.de_config(db, cfg, relogio)`; conta como o PC (mês civil America/Sao_Paulo, bloqueia só
  `BUDGET_BLOCKED_TASKS`: STT/TTS passam com o teto batido). `status()` → `spent_usd`=nuvem do mês,
  `cap_usd`=teto efetivo `max(0, min(2, 5 − pc))` (`spent ≥ cap` ⇔ bloqueado); `gasto()` dá
  `GastoMes` com nuvem/pc/tetos. Preço: `usage.usd` ou o `preco(usage)` injetado (a Ayanami não tem
  `[budget.prices]`; a Y6.3 pode passar o `MonthlyBudget.price_usd` do PC ou uma tabela própria).
  (2) `Deps.__post_init__` cria o `BudgetNuvem` de `cfg.budget` quando `budget` vem `None` (o worker
  não precisou mudar). (3) Gancho do `bate`: `custos.ligar(hub, db, relogio)` (idempotente) liga
  `ao_bate` → upsert em `custos_pc` (só nó `pc`, valor finito ≥ 0). Quem liga: o `lifespan` do
  roteador `ayanami/api/custos.py` (`APIRouter(lifespan=…)`, mesclado pelo FastAPI ao da app) e a
  própria rota; sem mexer no `hub.py`. (4) `GET /v1/custos?desde=&n=` (n ≤ 500, padrão 500): só
  `source='nuvem'`, ordem de `id`; `desde` desconhecido recomeça do início (o PC deduplica por
  `origem_uid`); `desde` inválido → 422; `at` por `iso_z` (segundos).
- **Y6.6:** (1) Sink novo `magi/core/proactive/ayanami.py`: `AvisosAyanami(core.proactive)` sem fila
  própria — tudo pelo `ProactiveSink`, logo as regras de call/jogo/satélite ocupado são as dos
  avisos locais (o core não tem modo "silêncio" separado). `evento` usa o título da Ayanami com
  prefixo por tipo ("Pesquisa pronta", "Lembrete"…); `confirmacao`/`dispositivo` só tela;
  `proativo=False` só card. (2) `confirma`: o handler responde `ack` na hora (não segura o elo 120 s)
  e pergunta pela `Offer` proativa (a mesma da sugestão de música); "sim"/"não" → `Confirma(resposta,
  resp=<id da pergunta>)` ao `hub.ao_receber(CONFIRMA)`; silêncio/expirada → nada; `confirma` com
  `resposta` (respondida no celular) esquece a pergunta. Em call/sem satélite a pergunta fica só na
  legenda (responde pelo PWA). (3) `CustosPc`: o `EloCliente` não tem gancho de `ola`, então `rodar`
  observa `cliente.modo` (`None` → conectado) a cada 5 s, mais 15 min; `ao_ola()` existe para o
  `NoPc.ola` chamar se quiser (fora do *Escreve*). HTTP próprio com `cliente.base_url` e
  `cliente._cabecalhos` (o `EloCliente` do PC nasce sem `http`); repo pela conexão do
  `core.repos.costs._conn` (`Repos` não expõe outra) — trocar por um método no `CostsRepo` depois.
  `total_mes()` = só `origem_uid IS NULL` (local) no mês de São Paulo, senão a nuvem contaria duas
  vezes no `pc_mes`; o fallback do `NoPc` (`Budget.status().spent_usd`) inclui as linhas copiadas.
  (4) Card "backup não subiu" (pedido da Y4.1): `AvisoBackup` em `ayanami.py`, chamado na volta do
  `CustosPc.rodar` (só com `[ayanami]`, como o próprio backup); uma vez por `quando` (marca
  `avisado` no `backup_state.json`); `data_dir` vem de `core._brain_args[0]`. O `AlertMonitor` não
  foi tocado. (5) O design cita `magi-elo parear`: é `uv run python -m magi.elo.parear [--nome …]`
  (sem script no `pyproject`). Esse processo não alcança o HUD (o socket só aceita `cmd`): o card
  "código de pareamento" sai só quando o core chamar `pedir_codigo(url, token, avisos=…)` — falta
  um intent/`cmd` "parear celular" no core (fora do *Escreve*).
- **Y2.3:** (1) `ayanami/eventos.py`: `gravar(conn, …)` / `criar_evento(db, tipo, titulo, resumo, ref, *,
  para, agora)` + `NOTIFY ayanami_eventos` (payload = id, o mesmo canal da Y3.1: o
  `tarefas.criar_evento` já é ouvido; trocá-lo por `ayanami.eventos.gravar` fica para quem mexer em
  `tarefas.py`). `eventos_de(ctx)` (`extras["eventos"]`): `await criar(…)` grava e distribui. O
  `LISTEN` sobe no lifespan do router de `api/eventos.py` (`APIRouter(lifespan=…)`, que o FastAPI
  mescla ao da app) só se o `Db` expõe `dsn`/`conninfo`; a cada (re)conexão relê `id >` último.
  (2) PC: `evento` por `hub.enviar_e_esperar` (30 s), `ack` → `entregue_pc`; offline fica pendente e
  sai no `ola` do `pc`; `ola.retomar_desde` (seq numérico) marca como entregue o que o PC já tem. O
  reenvio usa envelope novo: o PC (Y6.6) deduplica por `seq`. (3) SSE: `sse_de(ctx)`
  (`extras["sse"]`).`publicar(alvo, nome, corpo, id=None)`, alvo = id/nome/tipo/`"*"`; o `estado` da
  casa vai ao SSE `celular` por `hub.ao_receber(ESTADO)`; confirmações pendentes saem na varredura de
  2,5 s (a `Confirmacoes` não avisa ao criar; atraso ≤ 2,5 s); sem `Last-Event-ID` não relê nada.
  O `push.enviar` depois do evento fica para a P2.1. (4) Feed: `antes` exclusivo e `ts` com
  microssegundos; tarefas = `ok`/`falhou` sem tipo `lembrete`; lembrete = `eventos` tipo `lembrete`;
  não filtra spoiler de notícia. (5) Fora do *Escreve*: `tests/ayanami/api/test_tokens.py`,
  `test_limites.py` e `test_pareamento.py` esperavam `501` do stub do `/v1/feed` (agora `200`), e o
  `GET /v1/eventos` não termina no ASGI de teste (ocupam as 4 vagas → `429`).

- **Y1.0b:** (1) Por que override e não trocar o `compose.yml`: a §9.3 descreve a Ayanami com o
  node 2 só dela (≈ 13 GB, RNF-A6); o perfil enxuto vale só enquanto o node é dividido, e voltar é
  tirar o `-f`. (2) `deploy.sh` (Y1.2) não passa `-f`: basta `COMPOSE_FILE=compose.yml:compose.node2.yml`
  no `/opt/ayanami/.env` (o runbook diz); quem mexer no `deploy.sh` pode passar o `-f` explícito.
  (3) `rapida_concorrencia = 8` e `agendada_concorrencia = 2` ficaram no padrão do `ayanami.toml`;
  se o `worker-rapido` encostar nos 384m, baixar para 4 (não há variável de ambiente para isso).
  (4) A tabela/RNF-A6 da spec não foi editada (spec compartilhada): anotar o perfil node 2 nela se o
  Pedro quiser.
- **P1.1:** (1) Contrato das telas: `montar(el, ctx)` pode devolver a função de desmontagem; `ctx` =
  `{api, estado, eventos, params, navegar}`; `eventos.on(nome, fn)` recebe o SSE (`turno.texto`,
  `turno.fim`, `evento`, `estado`, `confirma`; `"*"` = todos); `api.pedir` lança `ErroApi`
  (`status`, `corpo`); `estado` tem `conexao`, `casa_fora`, `rota`, `saude` e `instalar` (o
  `beforeinstallprompt`, para a P1.4). (2) SSE lido por `fetch` + `ReadableStream` (o `EventSource`
  não manda `Authorization` nem `Last-Event-ID`). (3) `.precisa-rede` e `.precisa-casa` já ficam
  desabilitadas pelo CSS conforme `body[data-conexao]`/`body[data-casa]`. (4) Cópia do feed em
  `condessa-feed`, chave `/v1/feed`, cabeçalho `X-Condessa-Cache-Em` (ISO) para a P1.4. (5) A P2.2
  acrescenta `push`/`notificationclick` no `sw.js` e sobe `VERSAO`; arquivo novo tem de entrar em
  `ARQUIVOS` (o `test_sw.mjs` confere). (6) `gravador.js` exporta `suportado()`. (7) Ícones são a
  arte do HUD ampliada (cabem nos 80 KB, mas com pouca resolução): trocar se houver arte maior.
  (8) `montar_pwa(app, pwa_dir=None)`: a `criar_app` não repassa o `pwa_dir` dela (só decide se monta).
- **Y6.3:** (1) A Y6.4 monta `NuvemDeps.de_deps(deps, hub, confirmacoes=, app=)`, aquece a
  `FalaNuvem` com `carregar_frases().values()` na subida, chama `FalaNuvem.sintetizar(fim.fala)`
  ("opus" da OpenAI ou "pcm16" do Kokoro) e avisa o PWA da confirmação criada (o `TurnoFim` não leva
  o id; talvez SSE `confirma`); `atender` aceita `turno=`. (2) O `ProviderRegistry` da nuvem (com
  `chat(AGENT)` gravando no `BudgetNuvem`) e o `openai.AsyncOpenAI` com `OPENAI_API_KEY` não estão
  montados. (3) Sem reserva local de STT (o `WhisperLocal` trabalha por arquivo): `EscutaNuvem`
  aceita uma reserva injetável, `None` → `VozIndisponivel`. (4) `tv_estado` ficou fora (não está
  em `NUVEM_PODE`). (5) `news_query` da nuvem é SQL simples em `news_items`, sem embeddings.
- **Y3.4:** (1) Feito à parte (a56ba88): `tarefas.on_job_status` não marca `ok` quando o job
  devolve `{"segue": True}` (o monitor que não bateu já voltou a `na_fila`). (2) O 1º `monitor.passo`
  (da `criar_tarefa`) sai com `queueing_lock=chave`, não `monitor:<id>`: a varredura pode deferir um
  2º enquanto ele espera; inofensivo (o `lock` serializa e o passo antes da hora não faz nada).
  (3) `deps.registry` continua `None` no worker de produção (mesma pendência da Y3.2/Y6.1). (4) O
  juízo do monitor usa `ProviderTask.NEWS` como "LLM barato"; trocar se houver tarefa própria.
- **Y4.2:** (1) CA-Y25 não fecha por dois arquivos de outros donos: `deploy/ayanami/host/
  limpar-multivideos.sh:158` (Y1.2, comando de remover volume) e a docstring de
  `magi/elo/backup.py:12` (Y4.1, cita TRUNCATE e `--clean`); `test_varredura_completa_sem_excecoes`
  está `xfail(strict=True)` até corrigirem. (2) A imagem precisa de `zstd` (`tar --zstd` do restore
  de teste; conferir o Dockerfile da Y1.1). (3) `/saude` ainda não expõe `backup_falhou` nem
  `restore_teste` (tabela `restore_testes` pronta). (4) `ayanami backup` só tem `iniciar`; `rodar` e
  `testar` dão código 2. (5) Dump da Ayanami por `docker exec ayanami-pg pg_dump -Fc` (a imagem não
  tem cliente pg); senha do contêiner descartável só por ambiente; 409 = arquivo presente com o
  tamanho registrado (sem refazer o sha256). (6) Restore real (`pg_restore` da base `magi`) fica
  para a Y4.3.
- **Y5.1:** (1) `memoria_gravar` cria a confirmação `{"tipo":"memoria.gravar","fato":…}`, mas não há
  executor `ao_confirmar("memoria.gravar", …)` nem mensagem do elo para levar o fato ao PC: o "sim"
  não grava nada (precisa de dono Y6.x/PC). (2) `memoria_buscar` não registrada (D6/D13). (3) A
  expiração auditada da confirmação da TV só vale com a API viva (varrer `confirmacoes` expiradas na
  limpeza da Y3.x resolveria). (4) `montar()` roda em todo `criar_app`: os testes de API criam um
  `MCPServer` (um pouco mais lentos). (5) Metadado RFC 9728 em `/mcp/.well-known/…`, não na raiz.
  (6) `tarefa_criar` aceita `params` opcional além de `pedido`; `stt` recusado.
- **Y6.4:** (1) Feito à parte (8855b59): `api/nos.py` entrega os quadros binários da WS a
  `turnos_de(ctx).receber_quadro`. (2) `CanalWs` não tem `enviar_bytes`: `turnos._mandar_binario` usa
  `canal.ws.send_bytes` com a trava privada; dar ao `CanalWs` um `enviar_bytes` (já é usado se
  existir). (3) Em produção falta montar `ctx.extras["nuvem"|"escuta"|"fala"|"conversor"|
  "dir_turnos"]` (registry/OpenAI da Y6.3) e o `FalaNuvem.aquecer(...)` na subida. (4) Modo pc: o
  áudio fecha no 1º `AUDIO_FIM` depois do `TurnoFim` ou após 5 s sem `AUDIO_OUT`. (5) Sem `[turno]`
  na config (`mkdtemp`, `PRAZO_PC_S = 50`, 20/min constantes); turnos só em memória (10 min). (6)
  `test_limites.py`: asserção 501 → 422 (rota real). (7) `TurnoFim` ao PWA leva `audio=True` sempre
  que há fala sem erro; o áudio do modo pc pode começar segundos depois (P1.2).
- **P1.3:** (1) TV padrão lida de `estado.get().prefs.tv_padrao`; a P1.4 guarda as prefs na chave
  `preferencias` do armazém — ligar as duas (o `app.js` pôr `prefs` no estado na subida). (2)
  `ctx.relogio` opcional. (3) `estilo.css` sem regras para `.controle.cinza`, `.grupo-*`,
  `.abas-tv`, `.botao-tv.armado`, `[data-papel=casa-fora]` e o d-pad. (4) Intents fora da §13.1:
  `tv.channel` (`args.step`), `tv.key` (`args.key`), `tv.text` (`args.texto`); registrar na spec.
- **P1.4:** (1) `app.js`: pôr `verificar` e o armazém no `ctx` (hoje o parear dispara
  `visibilitychange`; as telas acham `ctx.armazem` → `armazemIdb()` → memória); ninguém assina o SSE
  `confirma` globalmente — navegar para `rotaDe(c)` de `telas/confirma.js`. (2) `sw.js` guarda
  qualquer `/v1/feed` (com `antes=` também) na mesma chave: cachear só sem `antes`. (3) P2.2:
  preencher `[data-campo=push]` (a pref `push` já vai no PUT); push de confirmação pode abrir
  `#/confirma/<ulid>?d=&expira=`. (4) `VERSAO_APP = "0.1.0"` solta no `ajustes.js`. (5) As telas
  caem num texto simples sem `ownerDocument` (teste de stubs da P1.1); o teste aceita "Dono:".
- **P2.1:** (1) Feito à parte (bbe3e6b): `Eventos.distribuir` defere `push.enviar` dos eventos com
  `celular` em `para` (fila de `extras["fila"]` ou a de produção, com `extras["fila_producao"]` ligado
  pelo `app_de_producao`). Evento criado com a API fora do ar não gera push (a distribuição recomeça
  do último `seq`). (2) `/saude` não avisa da falta das chaves VAPID. (3) `falhas` acumuladas não
  apagam a assinatura (só 404/410). (4) A `auditoria` (tipo `push`) é o livro-caixa: idempotência,
  contagem por hora/dia e acumulados no silêncio; o limite por hora é a hora cheia local.
- **Y0.7:** (1) Só o Kokoro fp32 medido no PC (10 frases, 43 s): 2 threads RTF p50 0,404 / p90 0,425,
  576 MB; 4 threads 0,279 / 0,293. Kokoro int8, whisper `small` e e5-small ficaram sem número (sem
  modelos no disco e sem rede): o Pedro roda `uv run --extra ayanami-ml python
  spikes/ayanami_s1_bancada.py all --modelos ~/.cache/magi/ayanami-s1` (≈ 1 GB) para fechar a seção
  "PC". (2) O `ayanami-ml` é extra, não grupo: o *Pronto* diz `--group`, vale `--extra`. (3) O
  fastembed 0.9.0 não traz o `intfloat/multilingual-e5-small`: o script usa `add_custom_model`
  (MEAN, normalizado), não testado sem rede; anotar na §5.6 ou trocar por um 384-dim da lista
  (`paraphrase-multilingual-MiniLM-L12-v2`).
- **Y1.4 (parcial, 05567e6):** testes (pgvector na 54340, ruff, pytest) e imagens no ghcr
  (`:<sha>[-ml]`, `:main[-ml]`) prontos; **falta o job de deploy** — a gravação foi bloqueada pela
  permissão do modo automático e não foi contornada. Falta: job `portao` (lê `secrets.AYANAMI_HOST`
  por `env:` → `outputs.tem_host`) e job `deploy` (`needs: [imagem, portao]`, `if:
  needs.portao.outputs.tem_host == 'true'`, `appleboy/ssh-action@v1.2.0` com `AYANAMI_HOST`/
  `AYANAMI_USER`/`AYANAMI_SSH_KEY`, `deploy.sh --tag ${{ github.sha }}` e `curl -fsS
  http://127.0.0.1:8740/saude`). O teste do job já existe (pula enquanto ele não existir). No node 2:
  `AYANAMI_IMAGEM=ghcr.io/<dono>/ayanami` no `.env` (e `docker login ghcr.io` se o pacote for
  privado). actionlint não rodado (não está no PC). Gatilho também em `.github/workflows/ayanami.yml`.
- **Y1.4 (deploy, 2026-10-21):** jobs `portao` + `deploy` no workflow; gatilho ganhou `pyproject.toml`
  e `uv.lock`. A chave da CI é `restrict,command=` → `deploy/ayanami/host/ci-deploy.sh` (instalado em
  `/usr/local/bin/ayanami-ci-deploy`; aceita só `deploy <sha40>` e `saude`), então o `script` do
  `appleboy/ssh-action` é `deploy <sha>`/`saude`, não o `deploy.sh` cru. `deploy.sh` com
  `AYANAMI_IMAGEM` agora faz `docker compose pull` sem `--ignore-buildable` (os serviços da Ayanami
  têm `build:` e eram pulados). Pacote ghcr `ayanami` público (as `-ml` são tags do mesmo pacote).
  Pendentes: `fingerprint` do host no `ssh-action` (hoje sem verificação da chave do host; exigiria
  um 4º secret); `actionlint` segue fora do PC; mudança no `ci-deploy.sh` exige reinstalar a cópia.
- **P1.2:** (1) O áudio é lido por `api.bruto` (o `<audio>` não manda o Bearer), virado blob e só
  toca com o stream fechado; provar latência e autoplay no P1.S4 (saídas: token curto na URL ou
  cookie). (2) `voz_em_texto` lido de `estado.get().prefs` — mesma pendência do `app.js` carregar as
  `preferencias` do armazém no estado e passar `armazem` no `ctx` (P1.3/P1.4). (3) `estilo.css` sem
  regras para `.ptt`, `.historico`, `.fala.*`, `.selo`, `.toast`, `.aviso*`, `.area-ptt[data-estado]`,
  `.campo-texto`. (4) A fala do usuário aparece como "(voz)" (o servidor não devolve a transcrição);
  `modo` não fica no histórico.
- **P2.2:** (1) Feito à parte (d46f177, 0486c0b): `GET /v1/push/chave` → `{"chave": VAPID_PUBLIC_KEY}`
  (escopo `conversa`, qualquer tipo; 503 `sem_vapid` sem chave). (2) `app.js` deveria chamar
  `reassinarSeMudou(ctx)` (de `telas/ajustes.js`) na subida; hoje só ao montar os Ajustes. (3) Badge
  usa `icones/192.png` (Android pede monocromático de 96 px; arquivo novo entra em `ARQUIVOS`). (4)
  Sem `pushsubscriptionchange` no SW. (5) Push de `confirma` abre `#/confirma/<ulid>` sem `?d=&expira=`.
  (6) O interruptor só aparece ligado com permissão concedida e assinatura ativa (`PREFS_PADRAO.push`
  é `true`).
- **Y6.5:** (1) Feito à parte: `api/nos.py` chama `reconciliacao_de(ctx)` quando o `pc` conecta pela WS
  (o long-poll do PC não liga); `Reconciliacao.fechar()` não é chamado na parada da app. (2)
  Extrator: `magi.memory.profile.ProfileUpdater.maybe_update()` via `PerfilIngest`, uma vez por lote
  com turno novo (respeita o `due` diário); memórias só saem do `memory_remember`. (3) Marca e chave
  anti-duplicação em `turns.intent = "nuvem:<uid>"` (sem coluna de uid); migração aditiva sugerida
  `turns.nuvem_uid uuid UNIQUE` (as `ferramentas` do `TurnoNuvem` se perdem hoje). (4) `TurnRepo`
  ganhou `ja_gravados(uids)`; `PRAZO_PC_S = 60` constante.
- **P1.x integração (b108467):** `app.js` carrega as `preferencias` no `estado.prefs` (invólucro do
  armazém mantém o estado em dia), passa `armazem`/`verificar` no `ctx`, assina o SSE `confirma`
  globalmente (navega para `rotaDe(c)` fora da tela) e chama `reassinarSeMudou` na subida sem esperar;
  `sw.js` não cacheia `/v1/feed?antes=` (VERSAO 3); `estilo.css` com as classes da Conversa/TV e
  d-pad 3×3. Restam: aparência real no P1.S4; P2.2 itens 3–5; P1.4 item 4 (`VERSAO_APP` solta).
- **F.2 (parcial, antes da F.1):** README (seção Ayanami/casa/celular), `docs/GUIA.md` §15 (casa,
  PWA, pareamento, push, domínio, node 2 compartilhado, vigia) e `docs/PROXIMOS-PASSOS.md` §13–§15
  descrevem o `main` de 2026-10-21; o que depende do ao vivo está marcado "a confirmar no F.1".
  Falta, depois da F.1: trocar esses trechos pelos números/comportamento medidos, o nome real
  (`ayanami.dekasis.com.br` × `.ts.net`, certificado), o "Condessa, pareia o celular" quando a Y6.6b
  entrar, e marcar a F.2 `[x]`. Runbook não foi tocado.
- **P2.3:** (1) Ninguém cria hoje um `Evento` `CONFIRMACAO` com `ref="confirma:<ulid>"` nem publica o
  SSE `confirma` (`Confirmacoes.criar` só pergunta ao PC): sem isso não há push nem card ao vivo de
  confirmação — tarefa nova (em `ayanami/confirmacoes.py`, `descricao` no `resumo`). (2) O `expira` do
  payload é `criado + 120 s` (`EXPIRA_CONFIRMA_S` = `confirmacoes.EXPIRA_S`; o `Evento` não leva
  `expira_em`). (3) Transcrição da voz no `turno.fim`: não é pouco esforço — o `TurnoFim` (contrato do
  elo, `magi/elo/mensagens.py` + schema) não tem campo e no modo pc quem transcreve é o PC; caminho:
  campo `ouvido: str = ""` no `TurnoFim`, preenchido pelo PC e pelo STT da nuvem, e a Conversa troca
  "(voz)" por ele. (4) Áudio com Bearer segue para o P1.S4. (5) Badge e ícones: conferir aparência
  real no P1.S4.
- **Y1.5/Y1.6 (primeiro deploy, 2026-10-21, por agente):** no ar no node 2 os 6 serviços `healthy`
  (perfil `compose.node2.yml`, núcleos 6-7), `/saude` com `banco=ok` e `ok=false` só por segredos;
  pelo tailnet (`tailscale serve` ligado pelo orquestrador) do PC com token `pc` (keyring) e `casa`
  (`ayanami-casa.token`); vigia ligado; `magi-news-sync`/`magi-backup` timers ligados no PC.
  Faltam (Pedro): (1) Telegram (`TELEGRAM_*` no `.env`, apagar o drop-in `sem-telegram.conf` e testar
  o alerta); (2) B2/restic (`B2_*`; copiar o `RESTIC_PASSWORD` gerado para fora do node);
  (3) `OPENAI_API_KEY`/`GEMINI_API_KEY` dedicadas; (4) DNS de `ayanami.dekasis.com.br` e, se for
  usado, o MCP aceitar mais de um host (hoje só o do `url_base`, que está no `.ts.net`); (5) ACL do
  tailnet/`nmap` de fora; (6) `claude mcp add` + token `mcp`; (7) secrets da CI (Y1.4) — e o job
  de deploy precisa de `--sem-build` (sem build no node 2); (8) SSH do node 2 ainda aceita senha.
