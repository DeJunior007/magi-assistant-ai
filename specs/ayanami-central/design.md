# Design — Ayanami central (nuvem da Condessa, casa e celular)

Implementa [requirements.md](requirements.md) (R*, RNF-A*, D*). Contratos finais, números medidos
e critérios de aceite ficam na [spec.md](spec.md). Seções citadas por `§`. Versões de bibliotecas
vêm do PyPI em 2026-10-12; o que está marcado *a confirmar no spike* entra na §14.

## 1. Onde mora hoje

```
PC (Fedora/Nobara, user units)                                     internet
 magi-satellite ──Wyoming TCP 127.0.0.1:10750──▶ magi-core ──HTTPS──▶ OpenAI / Gemini
                                                  │  │  └─ hud.sock (JSON-lines) ──▶ HUD
                                                  │  └─ OpenRGB 127.0.0.1:6742 (RgbActions)
                                                  └─ magi-pg (pgvector pg16, 127.0.0.1:54329)
 magi-ayanami.timer (2 h) ─▶ magi-ayanami (magi.news) ─▶ news_* no magi-pg
```

| Peça | Onde | O que muda | O que não muda |
| --- | --- | --- | --- |
| `magi-core` | `magi/core/service.py` `CoreService` (um `TurnMachine` por satélite; `SatelliteLink`) | ganha um **cliente de saída** à Ayanami (`magi/elo/`) que registra um satélite remoto `celular` (§7) e um cliente local do `magi-casa` | servidor Wyoming, HUD, roteador, agente, `Budget` |
| Satélite | `magi-satellite`, Wyoming em `127.0.0.1:10750` (`WYOMING_HOST/PORT` em `contracts.py`) | nada | tudo |
| Ações | `magi/core/actions/*` (`RgbActions` = cliente de host de rede, modelo do `TvActions`) | `TvActions` novo (§5.6) | demais ações |
| Agente | `magi/agent/tools/base.py` `ActionTool` (`serial`, `danger` → `needs_confirmation`) | `ActionTool`s `tv_*` e `tarefa_*` (§5.6, §4.3) | regra `danger` |
| Intents | `magi/core/intents.yaml` + `IntentId` em `contracts.py` | ids `tv.*` (R6.6) | roteador rapidfuzz |
| Notícias | `magi/news/__main__.py` (`magi-ayanami`/`magi-news`), timer 2 h | passa a rodar no node 2; no PC vira **recaída** (§8) | `news_*`, `news_query`, `proactive/news.py`, Rádio Ayanami |
| Banco | `deploy/docker-compose.yml` `magi-pg` | ganha `pg_dump` noturno só-leitura (§9) | nada de `down`/`rm`/`DROP` (RNF-A11) |
| Providers | `magi/providers/registry.py` (recusa `personal` em `free_tier`; `Budget.ensure_allowed/record`) | `Budget` aprende o sub-teto `nuvem` (§7.4) | regra `free_tier` |
| Node 2 | Contabo 8 vCPU/~23 GB, sem GPU, parado | vira a Ayanami (`/opt/ayanami`) | — |
| Node 1 | MultiVideos/wedding/gold-crm | **nada** (§11) | tudo |

## 2. Princípios

1. **Casa e PC funcionam sem nuvem.** Voz no PC → TV vai pela LAN (R6.7, RNF-A9). Sem a Ayanami,
   o PC faz tudo o que faz hoje; notícias voltam ao timer local (R3.2, RNF-A10).
2. **Nada público.** Só SSH (22/tcp) e Tailscale (41641/udp) na IP do node 2 (critério 7). Tudo o
   mais escuta em `127.0.0.1` e sai para o tailnet por `tailscale serve` (D1a/D2a).
3. **A nuvem nunca abre conexão para a LAN.** PC e `magi-casa` ligam **de saída** (R1.5); a ACL
   do tailnet impede o contrário (§10.1).
4. **Dado pessoal só no que é do Pedro.** PC e Ayanami self-hosted; provedores já autorizados;
   Gemini continua recusando `personal=True` (R3.5, RNF-A1). A réplica viva de memória só com D6.
5. **Um contrato de mensagens** (o *elo*, §3.2) para PC, casa, celular e MCP: mesmo envelope,
   mesmos tipos de ação (`ActionRequest`/`ActionResult` serializados), mesmo token por dispositivo.
6. **Um repositório.** A Ayanami mora neste repo (`ayanami/` + `deploy/ayanami/`) para reusar
   `magi.news`, `magi.agent`, `magi.providers`, persona e contratos; o node 2 só roda a imagem.

## 3. Visão geral

```
                              ╔════════════ tailnet (WireGuard, D2a) ═════════════╗
 ┌───────────── LAN de casa ──────────────┐                                       ║
 │ PC (user units)                        │        node 2 Contabo = AYANAMI       ║
 │  magi-satellite ─Wyoming─▶ magi-core ──┼─WS saída─▶┌──────────────────────────┐║
 │        HUD ◀─hud.sock──┘   │  │        │  (elo)    │ tailscale serve :443     │║
 │                 TCP 127.0.0.1:10760    │           │   └▶ ayanami-api :8740   │║
 │  magi-pg :54329   ▼        │ pg_dump  │           │      FastAPI: /v1 /ws    │║
 │             magi-casa ─────┼──WS saída┼──────────▶│      /app (PWA) /mcp     │║
 │   (PC hoje; Pi depois)     └─PUT──────┼──────────▶│  worker-rapido           │║
 │    │SSDP/mDNS, WS, HTTP, TLS          │           │  worker-agendado (restic)│║
 │    ▼                                  │           │  worker-lento (STT, emb.)│║
 │  TV Samsung :8002  TV TCL :6466/8060  │           │  ayanami-voz (Kokoro)    │║
 │  Roku :8060   (WOL udp/9)             │           │  ayanami-pg (pg16+vector)│║
 └────────────────────────────────────────┘           │  vigia (systemd timer)   │║
                                                      └──┬───────────┬───────────┘║
 Celular Android (app Tailscale) ── PWA https://ayanami.<tailnet>.ts.net/app ─────▶║
 Claude Code ── https://…/mcp (Bearer) ───────────────────────────────────────────▶║
                              ╚═══════════════════════════════════════════════════╝
                                    restic (S3/b2) ▼          ▼ Telegram, FCM (Web Push),
                                      Backblaze B2 (D7a)        OpenAI/Gemini (saída HTTPS)
```

### 3.1 Portas

| Serviço | Escuta | Quem alcança |
| --- | --- | --- |
| `ayanami-api` (uvicorn, 1 processo) | `127.0.0.1:8740` | só `tailscale serve` → `https://ayanami.<tailnet>.ts.net` (443) |
| `ayanami-pg` | rede Docker `ayanami` + `127.0.0.1:54339` (admin por SSH) | API e workers |
| `ayanami-voz` (Kokoro) | rede Docker `ayanami`, `:8741` | API e workers |
| `magi-casa` | `127.0.0.1:10760` (PC); IP do tailnet/LAN no Pi (D10b) | `magi-core` |
| SSH / Tailscale | `22/tcp`, `41641/udp` | internet (critério 7) |

Portas 8740/8741/10760/54339 são escolha deste design (livres no PC hoje: 10750, 54329, 6742,
11435 em uso); a spec fixa.

### 3.2 O elo (contrato único)

Pacote novo **`magi/elo/`** (puro, sem I/O, importado pelo PC, `magi-casa`, Ayanami e PWA via um
JSON Schema gerado). Envelope JSON, uma mensagem por frame WebSocket:

```json
{"v": 1, "t": "acao", "id": "01J…(ULID)", "de": "celular", "para": "casa", "ts": "…Z", "corpo": {…}}
```

| `t` | Sentido | Corpo |
| --- | --- | --- |
| `ola` / `bate` | nó → Ayanami | dispositivo, versão, capacidades; batimento a cada 10 s |
| `turno` / `turno_fim` | Ayanami ↔ PC | texto ou áudio (frames binários, §7.2), satélite `celular`; resposta: texto, cards, áudio |
| `acao` / `acao_ok` | qualquer → casa/PC | `ActionRequest` serializado (`intent`, `slots`, `confirmed`) / `ActionResult` |
| `estado` | casa → Ayanami | TVs (nome, driver, online, ligada, app, volume) |
| `evento` | Ayanami → PC/celular | tarefa pronta, monitor, lembrete, confirmação pendente (R9) |
| `confirma` | Ayanami ↔ PC/celular | pedido `danger` vindo do MCP (R5.3), expira em 120 s |
| `resumo_nuvem` | Ayanami → PC | turnos do modo nuvem a reconciliar (§7.5) |

O MCP não fala o elo direto: suas tools viram as mesmas chamadas internas (§4.5).

## 4. Componentes da Ayanami

Código em `ayanami/` (pacote Python), imagem única `ghcr.io/<dono>/ayanami:<sha>` (Python 3.12,
`uv`, `ffmpeg`, `restic`, `postgresql-client-16`), um comando por serviço do Compose.

### 4.1 API (`ayanami-api`)

FastAPI + uvicorn, **um processo** (as conexões WS ficam em memória; sem Redis, §4.2).

- **Dispositivos e tokens (R1.3–R1.4):** tabela `dispositivos(id, nome, tipo, escopos[], hash,
  criado, ultimo_uso, revogado)`. Token `ayn_<tipo>_<32 bytes base64url>`; guarda `sha256` (token
  de alta entropia dispensa hash lento). CLI `ayanami dispositivo criar|listar|revogar` (`docker
  compose exec ayanami-api ayanami …`). Revogar fecha as WS do dispositivo e invalida o cache de
  tokens (TTL 5 s) → 401 em ≤ 5 s.
- **Pareamento do celular (R7.1):** o `magi-core` (já autenticado) pede `POST /v1/pareamento`
  → código de 6 dígitos (5 min, uso único) mostrado num card do HUD ou como QR no terminal
  (`magi-elo parear`); o PWA manda o código → recebe token `celular` com escopos `conversa,
  casa, tarefas, feed`, guardado no IndexedDB.
- **Canal de saída (R1.5, R1.7):** `GET /ws` (Bearer) para `pc` e `casa`; batimento 10 s, offline
  após 30 s sem batida; recaída `GET /v1/longpoll?desde=` (25 s) se o WS falhar. Clientes
  reconectam com espera 1 → 2 → 4 … → 60 s e jitter.
- **Celular:** `POST /v1/turno` (texto ou áudio `audio/webm;codecs=opus`), `GET /v1/eventos` (SSE
  para o PWA aberto), `POST /v1/casa/acao`, `GET /v1/casa/estado`, `GET /v1/feed`, `GET|POST|DELETE
  /v1/tarefas`, `POST /v1/push/assinar`. PWA estático em `/app`.
- **Saúde (R1.6):** `GET /saude` sem auth dentro do tailnet, sem dado pessoal: banco, fila
  (contagem por estado/classe), batimento de cada worker, último backup, dispositivos online.
- **Painel de filas (R10.2):** `GET /v1/fila` + aba "Fila" no PWA + `ayanami fila` no CLI.
- **Auditoria (R10.3):** tabela `auditoria(ts, dispositivo, tipo, alvo, resumo, ok)`; job diário
  apaga > 90 dias.

### 4.2 Fila: `procrastinate` 3.10.0 (D3a)

Fila no próprio `ayanami-pg` (retry, periódicas, prioridade, `queueing_lock` para idempotência,
cancel/abort cooperativo, jobs longos em `doing` que sobrevivem a reinício). Tabela própria
`tarefas` (estado R2.3 em pt-BR, progresso, origem, resultado) ligada ao `job_id`; a chave de
idempotência (R2.2) vira `queueing_lock`. Cancelar (R2.4): fila → `cancel`; rodando → `abort`,
o job checa a cada ≤ 5 s (cancelamento em ≤ 10 s; a confirmar no spike S5).

**Redis não entra:** workers avisam a API por `LISTEN/NOTIFY` no canal `ayanami_eventos`
(payload = id do evento); a API lê a linha e empurra pela WS/SSE/Web Push. Só se o spike mostrar
perda de NOTIFY sob carga se reavalia (D3).

| Classe (fila) | Serviço | Concorrência | Limites Compose | Exemplos |
| --- | --- | --- | --- | --- |
| `rapida` | `worker-rapido` | 8 (async, I/O) | `cpus: 1`, `mem_limit: 512m` | comando, consulta, push, monitor 1 passo |
| `agendada` | `worker-agendado` | 2 | `cpus: 1.5`, `mem_limit: 1g` | notícias, AniList/Steam, monitores, backup, restore teste, limpeza |
| `lenta` | `worker-lento` | 1 | `cpus: 4`, `mem_limit: 6g`, `cpu_shares: 512` | STT assíncrono, embeddings em lote, cache de frases Kokoro |

Prioridade dentro da fila: `0` pedido do Pedro, `5` monitores, `9` lote noturno. Tarefas longas do
agente (pesquisa, "pesquisa e me avisa") rodam em `rapida` (são I/O de LLM/web) com prazo de 30 min.

### 4.3 Workers

- **Notícias (R3, §8):** `magi.news` como job periódico `noticias.coletar` cron `0 */2 * * *`
  contra o `ayanami-pg` (mesmas migrações `news_*`); Gemini `free_tier` para cluster/classificação.
  O progresso AniList/Steam (`a cada 6 h`) é dado pessoal: só pontuação local, nunca ao Gemini.
- **Tarefas do agente (R3.3):** `ActionTool`s `tarefa_criar` (pesquisa/resumo), `lembrete_criar`,
  `monitor_criar`, `tarefa_listar`, `tarefa_cancelar` no `magi-core` chamam `POST /v1/tarefas`
  e respondem "deixei na fila" (sem afirmar resultado). O worker roda o `GraphAgent` com
  ferramentas de busca web e budget da tarefa; dado pessoal → só provedor pago autorizado (R3.5).
- **Lembretes:** job agendado com `schedule_at`; **monitores:** periódico a cada 1–6 h (spec),
  até bater ou expirar (padrão 30 dias).
- **Backups (§9).**
- **TTS Kokoro (`ayanami-voz`):** serviço HTTP interno (`kokoro-onnx` 0.4.7 + `onnxruntime`
  1.31.0, voz `pf_dora`, lang `pt-br`), carrega o modelo na 1ª fala e descarrega após 10 min
  ocioso; `cpus: 2`, `mem_limit: 1536m`. Usado no modo nuvem só quando a D14 mandar (OpenAI
  `marin` cai/teto) e no job de cache de frases. RTF esperado 0,2–0,5 (a confirmar, S1).
- **STT assíncrono (R3.4):** `faster-whisper` 1.2.1 `small` int8, só em `lenta`; nunca em turno ao
  vivo. Áudio apagado ao fim do job.
- **Embeddings (A8):** `intfloat/multilingual-e5-small` via `fastembed` 0.9.0, `vector(384)`;
  só liga com a A8.
- **Ollama:** não (D8a).

### 4.4 Orçamento de CPU/RAM no node 2 (8 vCPU / ~23 GB)

| Componente | Repouso (estimado) | Pico / limite |
| --- | --- | --- |
| `ayanami-pg` (`shared_buffers=512MB`, `max_connections=40`) | ~150 MB, ~0% | `mem_limit: 2g`, `cpus: 2` |
| `ayanami-api` | ~120 MB | `1g`, `cpus: 1` |
| `worker-rapido` / `worker-agendado` | ~100 MB cada | `512m` / `1g` |
| `worker-lento` (modelos carregados sob demanda) | ~100 MB | `6g`, `cpus: 4` |
| `ayanami-voz` (descarregado) | ~80 MB | `1536m`, `cpus: 2` |
| Tailscale + Docker + SO | ~400 MB | — |
| **Total** | **≤ 1,2 GB, < 3% CPU** (meta RNF-A6: ≤ 6 GB, ≤ 10%) | soma dos limites ≈ 12 GB |

Lento + voz nunca passam de 6 vCPU juntos; sobram ≥ 2 vCPU e ~10 GB ao sistema (RNF-A6).

### 4.5 MCP (`mcp` 2.3.0, `MCPServer`)

`from mcp.server import MCPServer`, Streamable HTTP montado como app ASGI em `/mcp` no próprio
`ayanami-api` (mesmo processo, mesmo banco). Auth: `token_verifier` próprio que consulta
`dispositivos` (tipo `mcp`) e devolve `AccessToken` com `scopes`; cada tool checa o escopo com
`get_access_token()` (montagem e `AuthSettings` a confirmar no spike S3).

| Escopo | Tools | Padrão (D13a) |
| --- | --- | --- |
| `ler` | `noticias_buscar`, `noticias_ultimas`, `tarefas_listar`, `tarefa_ver`, `estado` (PC/casa online, TVs) | ligado |
| `tarefas` | `tarefa_criar`, `tarefa_cancelar` | ligado |
| `casa` | `tv_acao` (desligar = `danger` → `confirma`, R5.3) | desligado |
| `memoria-escrever` | `memoria_gravar` (via PC, sempre `confirma`) | desligado |
| `ler` + D6 | `memoria_buscar` (só leitura) | desligado até D6/D13 |

Toda chamada vai à `auditoria` (R5.4). Claude Code: `claude mcp add --transport http ayanami
https://ayanami.<tailnet>.ts.net/mcp --header "Authorization: Bearer $AYANAMI_MCP" -s user`.

## 5. `magi-casa`

Processo novo (`magi/casa/`, entrada `magi-casa`, user unit `deploy/systemd/magi-casa.service`,
`Restart=always`), asyncio, sem GPU, meta ≤ 1% CPU e ≤ 80 MB (R6.8).

### 5.1 Drivers (`TvDriver`, R6.1–R6.3)

```python
class TvDriver(Protocol):
    caps: frozenset[Cap]   # POWER_ON, POWER_OFF, VOL_STEP, VOL_SET, MUTE, CHANNEL, INPUT, APP, KEY, TEXT, STATE
    async def power(self, on: bool) -> Res; async def volume(self, step: int | None = None, set_to: int | None = None) -> Res
    async def mute(self, on: bool | None) -> Res; async def input(self, name: str) -> Res
    async def app(self, app: str) -> Res; async def key(self, key: Key) -> Res
    async def text(self, s: str) -> Res; async def state(self) -> TvState
```

| Driver | Biblioteca | Ligação | Ligar | Limites conhecidos |
| --- | --- | --- | --- | --- |
| `samsung` | `samsungtvws[async]` 3.0.6 (Tizen 2016+) | `wss://IP:8002` (token), REST `:8001/api/v2/` p/ `PowerState` | WOL (`wakeonlan` 4.0.0) ao `wifiMac`/MAC cabo | sem volume absoluto (emula com ±, §5.2); lista de apps instalados não responde em 2020+ → catálogo fixo; "Permitir" a cada conexão se a notificação de acesso não for "só na 1ª vez" |
| `roku` | `rokuecp` 0.19.5 (async) | HTTP `:8060` ECP, sem pareamento | `keypress/PowerOn` com *Fast TV start* | volume/power/HDMI só em Roku TV; **"Limited"** (OS 14.1.4+) dá 403 → exige "Enabled" |
| `androidtv` | `androidtvremote2` 0.3.2 | TLS `:6466` (controle), `:6467` (pareamento), cert de cliente | `KEYCODE_POWER` (pode falhar em standby profundo) | apps por **deep link**; não comanda dentro da Netflix; reconexões frequentes em alguns modelos; volume absoluto não (só ± e `volume_info`) |
| `adb` (recaída) | `androidtv` 0.0.75 / `adb-shell` 0.4.4 | `:5555`, depuração por rede | `input keyevent 26` | invasivo; só se o Pedro ligar o modo dev (opcional, fora do padrão) |

Comportamentos marcados [C] na pesquisa (portas 8001/8002 por ano, `PowerState`, 6466/6467,
*Fast TV start*) ficam *a confirmar no spike S2* com as TVs reais.

### 5.2 Emulação e honestidade (R6.2, R6.5)

`volume(set_to=20)` sem `VOL_SET`: lê o volume se houver estado (Android TV `volume_info`), senão
zera com 50× `VOL_DOWN` e sobe 20× (limite 60 teclas, 80 ms entre teclas); sem estado e sem limite
suficiente → `Res(ok=False, motivo="nao_suportado")`. Ligar: WOL e confirma por estado em ≤ 8 s;
falhou → `motivo` (`rede_desligada`, `standby_profundo`, `sem_mac`) que vira frase dela ("não
consegui ligar a TV da sala; ela precisa do *Ligar com celular* ativo"). Nunca diz "pronto" sem
confirmação do driver.

### 5.3 Descoberta e identificação (R6.4, D9)

`async-upnp-client` 0.49.0 (SSDP) + `zeroconf` 0.151.5 (mDNS), na rede do host (multicast não
atravessa Tailscale/Docker). Buscas: `roku:ecp`; `urn:samsung.com:device:RemoteControlReceiver:1`
e `MediaRenderer:1` (confirma em `:8001/api/v2/`); `_androidtvremote2._tcp.local.`.
**TCL Roku vs Google TV:** responde `GET :8060/query/device-info` → `roku`; anuncia
`_androidtvremote2._tcp` ou abre `:6466` → `androidtv`; os dois → prefere `androidtv` e loga.
`magi-casa descobrir` lista as novas; `magi-casa nomear <id> "TV da sala" [--padrao]` grava em
`~/.config/magi/casa.toml` (nome, driver, IP, MAC, apelidos, app catalog override). DHCP: o
identificador estável é o MAC/serial; IP é revalidado na descoberta a cada 10 min.

### 5.4 Pareamento e segredos

`magi-casa parear "TV da sala"`: Samsung → abre a WS e espera o "Permitir" (60 s); Android TV →
gera cert, pede o código de 6 hex que a TV mostra, `async_finish_pairing`; Roku → nada.
Tokens e certs em `~/.local/share/magi/casa/` (`0700`; arquivos `0600`), token Samsung também no
keyring `magi-keys` se couber (cert/key do Android TV ficam em arquivo `0600`). Nunca em git/log.

### 5.5 Catálogo fixo de apps

`magi/casa/apps.yaml`: nome canônico + apelidos → por driver: Samsung `run_app` (Netflix
`3201907018807`, YouTube `111299001912`, demais a confirmar), Roku `launch/<id>` (ids do
`/query/apps`, cacheados), Android TV deep link (`https://www.netflix.com/title`,
`https://www.youtube.com`, …). Entradas faltantes → "não conheço esse app nessa TV".

### 5.6 Intents, ferramentas e caminhos de chamada

- `IntentId`: `tv.power_on`, `tv.power_off` (`danger`), `tv.volume` (slot `volume`, relativo ou
  absoluto), `tv.mute`, `tv.app` (slot `app`), `tv.input` (slot `input`), slot novo `tv` (nome;
  vazio = TV padrão). Frases em `intents.yaml`; `ActionTool`s `tv_ligar`, `tv_desligar`
  (`danger=True`), `tv_volume`, `tv_mudo`, `tv_app`, `tv_entrada`.
- **Local (R6.7):** `TvActions` (como `RgbActions`) fala com `magi-casa` em `127.0.0.1:10760`,
  JSON-lines do elo (`acao`/`acao_ok`), token local em `~/.config/magi/casa.token` (`0600`).
  Sem Ayanami nem internet. Casa fora → frase em cache "a casa está fora do ar".
- **Pela Ayanami:** `magi-casa` mantém `wss://ayanami…/ws` (token `casa`); celular/MCP mandam
  `acao` → API → WS da casa → `acao_ok` → resposta. Casa offline → 503 + "a casa está fora do ar"
  (D10a). Botão do PWA não passa pelo PC (critério 2: p90 ≤ 1,5 s).
- **Pi (D10b):** o mesmo processo; `magi-core` aponta `[casa] endereco` ao IP do Pi no tailnet.

## 6. Celular (PWA, D4a)

Servido pela API em `/app` através de `tailscale serve` (cert Let's Encrypt do tailnet = contexto
seguro). Estático (HTML/JS sem build pesado, a confirmar framework na spec), `manifest.webmanifest`
(`display: standalone`, ícones 192/512), service worker com cache do *shell* e do último feed.

| Tela | Conteúdo |
| --- | --- |
| Conversa | chat, botão **segurar para falar**, rosto em sprite por estado (D5a: dormindo/ouvindo/pensando/falando), selo "PC" ou "nuvem" |
| TV | uma aba por TV, só botões das `caps` (ligar, vol ±, mudo, HDMI, apps do catálogo, d-pad, texto) |
| Feed | cards da Ayanami (notícias, tarefas prontas) |
| Tarefas | lista por estado, progresso, cancelar |
| Ajustes | dispositivo, push on/off, `push_com_pc`, sair (revoga o token) |

- **PTT:** `getUserMedia` + `MediaRecorder` `audio/webm;codecs=opus` (checa `isTypeSupported`),
  máximo 15 s (como `MAX_LENGTH` do satélite), envia o blob em `POST /v1/turno`. Áudio fica só na
  memória do turno no servidor e é apagado ao fim (R7.3).
- **Resposta:** texto chega por SSE assim que existe; áudio como `audio/ogg;codecs=opus` tocado
  por `<audio>` (o gesto de PTT libera o autoplay).
- **Web Push (R9, D12a):** `pywebpush` 2.5.0, chaves VAPID no `.env`; assinatura em
  `push_assinaturas`; 404/410 → apaga. O envio sai do node 2 para o FCM (cifrado ponta a ponta);
  o texto é só título + resumo curto (R9.3).
- **Instalação:** Chrome → "Instalar app" (WebAPK). TWA por Bubblewrap fica para D4b.
- **Fora do tailnet (R7.4):** `fetch` falha → faixa "sem conexão com a Ayanami — ligue o
  Tailscale", feed do cache.
- **Limites aceitos:** sem microfone em segundo plano, sem wake word (fora do escopo).

## 7. Roteamento da conversa

### 7.1 Decisão

`POST /v1/turno` → a API olha o dispositivo `pc`: online (batida < 30 s) → **modo PC**; senão
→ **modo nuvem**. A decisão vai no selo da resposta.

### 7.2 Modo PC (R8.1)

1. API transcodifica webm/opus → PCM 16 kHz mono s16le (`ffmpeg`, ~50 ms; a confirmar S6) e
   manda `turno` + frames binários de 80 ms pela WS do PC (texto vai direto).
2. No PC, `magi/elo/remote.py` `RemoteLink` implementa `SatelliteLink` com `SatelliteHello(
   satellite="celular", capabilities=("ptt", "playback"))` e registra um `TurnMachine` no
   `CoreService` (mesmo caminho do Wyoming: `magi-wake` PTT, `audio-*`, `audio-stop` com
   `ptt_release`). Mesma memória, persona, ferramentas e `Budget`.
3. A fala sai por `RemoteLink.play` (PCM) → WS → API → opus → celular; o texto final vem por um
   gancho de saída do turno (onde exatamente o `compose` entrega o texto ao link: a confirmar na
   spec). Responde no satélite `celular`, nunca no headset (R8.1).
4. Pedido de TV no turno → `TvActions` local no PC (LAN). Meta: p90 ≤ 4 s (critério 2).

### 7.3 Modo nuvem (R8.2–R8.3)

`ayanami/nuvem.py` monta um `GraphAgent` com a persona da Condessa e **só** estas ferramentas:
`news_query` (contra o `ayanami-pg`), `tarefa_*`, `lembrete_criar`, `monitor_criar`, `estado`,
`tv_*` (só se `casa` online; senão "a casa está fora do ar"). Pode: conversar, notícias, criar e
ver tarefas, lembretes, TV via casa. **Não pode:** memória do PC (até A8), jogos/HUD/RGB/Spotify,
ações do PC, abrir coisas no PC. STT da OpenAI (`gpt-transcribe`, turno ao vivo) e TTS `marin`
com cache (D14a); Kokoro se a OpenAI cair ou bater o teto. Contexto: últimos 20 turnos de
`nuvem_turnos`. A persona recebe a linha "estou sem a memória do PC agora" para usar quando
importar (R8.3). Chaves OpenAI/Gemini no `.env` `0600` do node 2 (chave OpenAI dedicada, com
limite no painel da OpenAI, a confirmar com o Pedro).

### 7.4 Gasto (R8.4, D11a)

A Ayanami tem `costs` com o mesmo esquema e `source='nuvem'`. Sub-teto `nuvem` US$ 2/mês dentro
do teto geral de US$ 5: o PC manda o total do mês no `bate`; a Ayanami bloqueia quando `nuvem ≥ 2`
**ou** `pc + nuvem ≥ 5`. O PC puxa as linhas `nuvem` e grava no `costs` local (chave = id da
linha), então o `Budget` do PC enxerga tudo. Teto batido → modo nuvem sem LLM: TV, tarefas, feed
e frase em cache.

### 7.5 Memória (D6a, R8.5)

`magi-pg` é a fonte da verdade. Turnos do modo nuvem ficam em `nuvem_turnos` (texto, sem áudio).
Quando o PC volta (`ola`), a API manda `resumo_nuvem` (turnos não sincronizados); o PC grava pelo
caminho normal de ingestão de memória (função exata a confirmar) e devolve `ack` com os ids; a
Ayanami marca `sincronizado` e apaga após 30 dias. Sem réplica viva da memória do PC na nuvem até
o Pedro aceitar (D6); a A8 (embeddings, `memoria_buscar`) só depois.

## 8. Notícias saindo do PC

- **Nuvem:** job `noticias.coletar` (§4.3) grava `news_*` no `ayanami-pg`.
- **Sincronização puxada (R3.1):** `magi-news-sync` (entrada nova; `magi-news-sync.timer` a cada
  15 min, `Persistent=true`) chama `GET /v1/noticias?desde=<cursor>` e faz *upsert* em `news_*`
  do `magi-pg` pela chave natural do item (a confirmar no esquema: url canônica/hash) com cursor
  em `~/.local/state/magi/news_cursor`. Consumidores (`news_query`, `proactive/news.py`, Rádio
  Ayanami) não mudam.
- **Recaída (R3.2):** `magi-ayanami.service` ganha `ExecCondition=magi-news-sync --precisa-local`,
  que só deixa rodar se a última sincronização OK tiver > 6 h **e** houver internet. Assim o
  timer de 2 h continua instalado, mas fica mudo enquanto a nuvem entrega; quando a Ayanami volta,
  a sincronização seguinte zera o relógio e a coleta local para de novo. Duplicatas entre as duas
  coletas caem no *upsert*.

## 9. Backups

| Passo | Onde | Quando | Como |
| --- | --- | --- | --- |
| Dump do PC | `magi-backup.timer` (user unit) | `03:30`, `Persistent=true` + `OnStartupSec=10min` (R4.1: ≤ 15 min após login) | `docker exec magi-pg pg_dump -Fc -U magi magi` (só leitura) + tar de `~/.config/magi/` sem chaves → `zstd` → `PUT /v1/backup/pc` (sha256, token `pc`, escopo `backup`) |
| Recepção | API | — | grava em `/opt/ayanami/dados/entrada/pc/<data>/`, confere sha256, enfileira `backup.restic` |
| Dump da Ayanami | `worker-agendado` | `04:00` | `pg_dump -Fc` do `ayanami-pg` → `/opt/ayanami/dados/entrada/ayanami/` |
| Envio | `worker-agendado` | após cada chegada e `04:30` | `restic backup` → `b2:<bucket>:/magi` (D7a); apaga a entrada local após 2 dias |
| Retenção | `worker-agendado` | domingo `05:00` | `restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune` (D15a) |
| Verificação | `worker-agendado` | domingo `05:30` | `restic check --read-data-subset=5%` |
| Restore teste (R4.3) | `worker-agendado` | dia 1, `06:00` | `restic restore latest` em `/tmp` → container descartável `pgvector/pgvector:pg16` `ayanami-restore-teste` (sem porta, rede própria) → `pg_restore` → conta linhas de `memories`/`costs`/`news_items` (nomes a confirmar) e compara com o manifesto do dump → apaga container e diretório → Telegram verde/vermelho |
| Alerta (R4.4) | `vigia` | a cada 1 min | sem snapshot novo em 36 h ou job `falhou` → Telegram + push |

Segredos: `RESTIC_PASSWORD` e chave B2 (restrita ao bucket) no `.env` `0600`; a senha também no
gerenciador do Pedro e no keyring do PC (R4.2). Nenhum passo toca o `magi-pg` além do `pg_dump`
(R4.5). Custo: B2 ~US$ 0,007/GB·mês; estimativa < 5 GB → < US$ 0,10/mês (meta ≤ US$ 3).
RTO manual (critério 4): runbook `docs/ops/ayanami-restore.md` (clone, `.env` do cofre, `restic
restore`, `pg_restore`, `compose up -d`).

## 10. Segurança

### 10.1 Tailscale (D2a)

Tailscale no **host** do node 2 (`tailscale up --advertise-tags=tag:ayanami --ssh`), `serve` em
443 → `127.0.0.1:8740`. MagicDNS + HTTPS ligados. Plano Personal grátis (6 usuários, dispositivos
ilimitados, 50 recursos com tag). Política (grants):

```
tag:ayanami  dono: autogroup:admin        tag:casa  dono: autogroup:admin (Pi, D10b)
pedro (PC, celular)  → tag:ayanami : 443, 22
tag:casa             → tag:ayanami : 443
tag:ayanami          → (nada)           # a nuvem não alcança PC, Pi nem LAN
```

Sem *subnet router* nem *exit node*. `tailscale funnel` proibido salvo D2c/D1b.

### 10.2 Node 2

`ufw default deny incoming`, `allow 22/tcp`, `allow 41641/udp`; Docker só publica em
`127.0.0.1` (Docker ignora o ufw para portas publicadas, por isso nada em `0.0.0.0`). SSH só por
chave, `PasswordAuthentication no`. `unattended-upgrades` de segurança.

### 10.3 Tokens, escopos, segredos, auditoria

| Tipo | Escopos | Onde fica |
| --- | --- | --- |
| `pc` | `conversa`, `casa`, `tarefas`, `feed`, `backup`, `noticias`, `custos` | keyring `magi-keys` (`ayanami/pc`) |
| `casa` | `casa-executar` | `~/.config/magi/ayanami-casa.token` `0600` (ou keyring) |
| `celular` | `conversa`, `casa`, `tarefas`, `feed` | IndexedDB do PWA |
| `mcp` | §4.5 | config do Claude Code (`-s user`) |

Segredos do node 2 em `/opt/ayanami/.env` (`0600`, fora do git): `POSTGRES_PASSWORD`,
`OPENAI_API_KEY`, `GEMINI_API_KEY`, `VAPID_*`, `B2_*`, `RESTIC_PASSWORD`, `TELEGRAM_*`. Logs JSON
sem token, chave, áudio nem texto de conversa (só ids e tamanhos, R10.1). Auditoria §4.1.
Proibições do repo (RNF-A11): nada de `qdbus`/`gdbus` para KGlobalAccel/KWin no `magi-casa`;
nada de `down`/`rm`/`DROP` no `magi-pg`; nada no node 1.

## 11. Operação e deploy

- **Layout:** `/opt/ayanami` = clone do repo (só `deploy/ayanami/` é usado), `compose.yml`,
  `.env`, `dados/` (`pg/`, `entrada/`, `modelos/`, `restic-cache/`). Volumes nomeados
  `ayanami-pgdata`, `ayanami-modelos`. `restart: unless-stopped`, `name: ayanami`.
- **Deploy (R10.4):** A1 manual: `git pull && docker compose pull && docker compose up -d && curl
  -fsS http://127.0.0.1:8740/saude`. Migrações (`ayanami migrar` + `procrastinate schema`) num
  serviço `migrar` de uma vez (`profiles: ["ops"]`). Depois: `.github/workflows/ayanami.yml` em
  push que toque `ayanami/**`, `magi/news/**`, `magi/elo/**`: testes → build → `ghcr.io` → ssh
  (`appleboy/ssh-action`, secrets `AYANAMI_HOST/USER/SSH_KEY`) → smoke `/saude`. Sem secrets, o job
  de deploy é pulado.
- **Healthchecks:** Compose em cada serviço (`pg_isready`; API `curl /saude`; workers gravam
  batimento em `workers_batimento` a cada 30 s).
- **Vigia (R10.5, critério 3):** `ayanami-vigia.timer` no **host** (fora do Docker), 1 min:
  `curl /saude`, `df` (> 85%), batimento de worker > 5 min, backup > 36 h → Telegram (bot do
  Pedro; reaproveitar o do node 1 só se ele quiser). Do PC, o `magi-elo` mede a disponibilidade
  enquanto ligado.
- **Painel de filas:** §4.1.
- **Node 1:** nada é instalado, roteado ou alterado lá; qualquer coisa que precise dele vira
  tarefa "precisa do Pedro".

## 12. Convivência com o que existe

- **HUD:** nada muda no protocolo; cards novos ("Pesquisa pronta", "código de pareamento 123 456",
  "celular conectado") usam `CardMsg` existente. O turno do satélite `celular` aparece no HUD como
  qualquer turno (selo `celular` via `TurnTagMsg`, a confirmar).
- **Satélite Wyoming:** intocado; o `RemoteLink` é um segundo implementador de `SatelliteLink`.
  O satélite do Raspberry Pi (R22) continua possível e independe da Ayanami.
- **Budget:** um teto geral, dois lugares que gastam (§7.4); `free_tier` igual nos dois.
- **Proatividade:** eventos da Ayanami chegam ao PC pela WS e entram na fila de proatividade
  existente (`magi/core/proactive/`, um `sink` novo), com as regras de silêncio/jogo (R9.2).
- **Learning Mode / `magi-qwen`:** nada muda; o Ollama do PC não vai para a nuvem.
- **`condessa-engine`:** fora de escopo; o MCP e a fila foram pensados para recebê-lo depois
  (escopo novo `engine`), sem promessa.

## 13. Riscos e mitigação

| Risco | Efeito | Mitigação |
| --- | --- | --- |
| Node 2 cancelado/agendado para cancelar (D-P1) | sem Ayanami | A0 confirma antes de qualquer código de nuvem; A2 (casa) e o PC não dependem dela; compose portátil para outra VPS; backup fora da Contabo |
| Roku em "Limited" (OS 14.1.4+) | 403 em keypress/launch | driver detecta 403 e diz qual opção ligar ("Controle por apps móveis → Ativado"); doc do pareamento |
| Samsung não liga por WOL no Wi-Fi | "liga a TV" falha | cabo quando der; "Ligar com celular"; resposta honesta (§5.2) |
| Android TV desconecta a cada ~15 s / standby profundo | latência e falha ao ligar | reconexão automática; manter conexão aberta; ADB como recaída opcional |
| MCP do Claude Desktop/claude.ai não alcança o tailnet (conectores remotos saem da Anthropic) | sem MCP no Desktop | Claude Code funciona (sai da máquina local); no Desktop, ponte stdio local `npx mcp-remote <url> --header …`; Funnel/Caddy público só com D2c |
| PC desligado + `magi-casa` no PC (D10a) | TV pelo celular indisponível | resposta clara "a casa está fora do ar"; código pronto para o Pi (D10b) |
| Latência modo PC (4G → node 2 → PC → node 2 → 4G) | voz > 4 s | transcodificação curta, frames de 80 ms, TTS em streaming; medir no S6; se estourar, STT na própria Ayanami e só texto ao PC |
| `LISTEN/NOTIFY` perdido em reconexão da API | evento atrasado | API relê `eventos` pendentes ao reconectar; Redis só se o S5 mandar |
| Gasto do modo nuvem | estouro do teto | sub-teto + teto geral somado (§7.4); chave OpenAI dedicada com limite |
| Dado pessoal na nuvem (RNF-A1 vs RNF-10 do MVP) | privacidade | D6a: só backup cifrado + `nuvem_turnos`; réplica viva só com OK |
| Vazamento de token do celular | acesso à casa | revogação em ≤ 5 s; tailnet obrigatório; escopos sem `backup`/`memoria` |
| Senha do restic perdida | backup inútil | cópia no gerenciador do Pedro e no keyring do PC; restore mensal prova que ela funciona |
| Nome do host no Certificate Transparency | nome `ayanami.<tailnet>.ts.net` público | não expõe serviço (só tailnet); aceitar ou renomear (D1) |

## 14. Spikes antes de implementar

| # | Spike | Pergunta | Orçamento |
| --- | --- | --- | --- |
| S1 | Node 2 em bancada | Kokoro RTF em pt-BR, faster-whisper `small` int8 RTF/RAM, e5-small vazão, repouso do Compose (RNF-A6) | precisa do node 2 (A0) |
| S2 | TVs reais | TCL é Roku ou Google TV? `PowerState` Samsung, WOL Wi-Fi/cabo, Roku "Limited"/Fast TV start, reconexão `androidtvremote2`, latência por driver (critério 1) | precisa do Pedro na TV |
| S3 | MCP 2.3 | `MCPServer` montado no FastAPI, `token_verifier` com escopos, `claude mcp add` pelo tailnet, ponte `mcp-remote` no Desktop | ~30k |
| S4 | PWA no Android dele | `tailscale serve` + instalação WebAPK, `MediaRecorder` opus, autoplay após PTT, Web Push via FCM saindo do node 2 | ~30k |
| S5 | `procrastinate` 3.10 | `abort` em ≤ 10 s, job de 30 min sobrevive a `restart`, `queueing_lock`, NOTIFY → API | ~25k |
| S6 | Turno remoto | `RemoteLink` no `CoreService` com webm→PCM→turno→PCM→opus; p90 do caminho 4G | ~40k |
