# Spec — Ayanami central (nuvem da Condessa, casa e celular)

Contratos, números e tabelas. Implementa [requirements.md](requirements.md) (R*, RNF-A*, D*)
segundo o [design.md](design.md) (citado como "design §n"). Vale o padrão de cada D* até o Pedro
decidir (D1a, D2a, D3a, D4a, D5a, D6a, D7a, D8a, D10a, D11a, D12a, D13a, D14a, D15a). Onde o
design deixou "a spec fixa" ou "a confirmar", a escolha vem marcada **[DSn]** (tabela abaixo); o
que só a bancada confirma cita o spike (S1–S6, design §14; pendências na §17) e já traz o valor a
usar até lá. A parte B (§10–§16) implementa R6, R7, R9 e RNF-A7–A9 (design §5–§6) e usa os tipos
e rotas das §1–§2 sem redefini-los. Critérios de aceite: **CA-Y1–CA-Y29** no fim de cada seção
da parte A; **CA-Y30–CA-Y59** na §16.2. Todo teste roda sem rede real nem LLM pago (fakes, `procrastinate.testing.
InMemoryConnector`, ASGI em memória, Postgres de teste quando marcado `pg`).

## Sumário

**Parte A — nuvem e contrato**
1. Contrato `magi/elo/` (envelope, tipos, quadros binários, validação)
2. API da Ayanami (REST, WebSocket, SSE, pareamento, tokens)
3. Banco da Ayanami (migrações)
4. Fila (`procrastinate` 3.10)
5. Workers (notícias, `magi-news-sync`, agente, voz, STT, embeddings)
6. Roteamento do turno e modo nuvem
7. Backups
8. MCP
9. Config da Ayanami e Compose

**Parte B — casa e celular**
10. `magi-casa` e `TvDriver`
11. Drivers Samsung, Roku e Android TV
12. Descoberta e pareamento das TVs
13. Intents e ferramentas `tv.*`
14. PWA: telas e API usada
15. Web Push
16. Config da casa e do celular; CA-Y30–CA-Y59
17. Pendências para os spikes

### Decisões desta spec (resumo)

| # | Decisão |
| --- | --- |
| DS1 | Portas fixas: `ayanami-api` `127.0.0.1:8740`; `ayanami-voz` `:8741` (só rede Docker); `magi-casa` `127.0.0.1:10760`; `ayanami-pg` admin `127.0.0.1:54339`. |
| DS2 | Ids do elo são ULID (26 caracteres Crockford) gerados em `magi/elo/ids.py`, sem dependência nova. |
| DS3 | Idempotência de tarefa = índice único parcial em `tarefas.chave` (vivas) **e** `queueing_lock` (o lock da lib só vê `todo`, não `doing`). |
| DS4 | Prioridade no padrão do `procrastinate` (maior sai antes): pedido do Pedro `20`, monitor `10`, lote `0` (o design usava a escala inversa 0/5/9). |
| DS5 | Chave natural da sincronização de notícias: `news_raw.url` (já `UNIQUE`) e coluna nova `news_items.uid uuid`; no `magi-pg`, migração aditiva `005_ayanami_sync.sql`. |
| DS6 | Texto final do turno remoto sai por um gancho novo `TurnDeps.on_turn_done` (§6.3). |
| DS7 | `restic` agrupa por `host,tags` (os caminhos têm data e quebrariam a retenção por caminho). |
| DS8 | Config da Ayanami: `.env` só com segredos; o resto em `ayanami.toml`; chave desconhecida = erro na subida. |
| DS9 | Fuso de todos os horários: `TZ=America/Sao_Paulo` nos contêineres (S5 confirma que o cron do `procrastinate` segue o TZ; senão converter para UTC). |
| DS10 | Volume absoluto emulado: com estado ≤ 60 teclas; sem estado "zerar e subir" (`zerar_passos` 50 + N, N ≤ 50) ≤ 100 teclas; 80 ms entre teclas (design §5.2 dava 60 para os dois; 50 + N não cabe). |
| DS11 | `tv.unmute` é intent próprio, par de `tv.mute` (como `volume.mute`/`volume.unmute`). |
| DS12 | Colisão de frases: toda frase `tv.*` tem "tv"/"televisão", um `{tv}` ou "hdmi"; sem isso vale o intent do PC. |
| DS13 | Escolha da TV: slot `tv` → `padrao` → única TV → única ligada (≠ ligar) → pergunta (§13.3). |
| DS14 | `tv_estado` é tool de leitura (não `ActionTool`, `serial=False`). |
| DS15 | PWA em HTML + JS puro (módulos ES), sem build nem CDN. |
| DS16 | "Desligar" no PWA exige segundo toque em ≤ 3 s; só então `confirmed=true`. |
| DS17 | Push de `confirma` sem botão "Confirmar": abre o card no PWA. |
| DS18 | Silêncio padrão `23:00–07:30` (só `confirma`/`lembrete` passam; resto agrupado às 07:30), ≤ 10 pushes/h por dispositivo. |
| DS19 | Estado da TV tem um tipo só, `EstadoTv` (§1.2), usado por driver, elo, API, MCP e PWA; a parte fixa (`TvInfo`, `AppInfo`) vai no `ola` da casa; o token do elo local viaja em `Ola.token`. |

## 1. Contrato `magi/elo/`

Pacote puro (sem I/O de rede): `magi/elo/mensagens.py` (tipos, `encode`/`decode`),
`magi/elo/quadros.py` (binário), `magi/elo/ids.py`, `magi/elo/converte.py` (ponte com
`contracts.py`). `python -m magi.elo.schema > ayanami/app/elo.schema.json` gera o JSON Schema
usado pelo PWA. Cliente de conexão (`EloCliente`) e `RemoteLink` ficam em `magi/elo/cliente.py`
e `magi/elo/remote.py` (§6), fora do núcleo puro.

### 1.1 Envelope

```json
{"v":1,"t":"acao","id":"01JA2Z7Q8M4V0K3N5R6S7T8W9X","de":"celular-pedro","para":"casa",
 "ts":"2026-10-12T21:04:05.123Z","resp":null,"corpo":{…}}
```

```python
VERSAO: Final = 1
MAX_TEXTO_BYTES: Final = 65_536        # frame de texto WS / corpo JSON do long-poll
MAX_BINARIO_BYTES: Final = 8_192       # frame binário (§1.4)
NOME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")   # nomes de dispositivo; "ayanami" reservado

class Tipo(StrEnum):
    OLA = "ola"; BATE = "bate"; TURNO = "turno"; TURNO_FIM = "turno_fim"; ACAO = "acao"
    ACAO_OK = "acao_ok"; ESTADO = "estado"; EVENTO = "evento"; CONFIRMA = "confirma"
    RESUMO_NUVEM = "resumo_nuvem"; ACK = "ack"; ERRO = "erro"

class EloError(ValueError):
    """``codigo``: "json" | "versao" | "tipo" | "campo" | "tamanho" | "nome"."""
    codigo: str

@dataclass(frozen=True, slots=True)
class Envelope:
    t: Tipo
    corpo: Corpo                # um dos dataclasses de §1.2, coerente com ``t``
    de: str                     # NOME_RE ou "ayanami"
    para: str                   # NOME_RE, "ayanami", ou o tipo "pc"/"casa" (roteado ao online)
    id: str = field(default_factory=novo_id)       # ULID
    ts: datetime = field(default_factory=agora_utc)  # timezone-aware, serializa com "Z" e ms
    resp: str | None = None     # id do envelope que este responde (turno_fim, acao_ok, ack, erro, confirma-resposta)
    v: int = VERSAO

def encode(env: Envelope) -> str            # JSON compacto, ensure_ascii=False; > MAX_TEXTO_BYTES → EloError("tamanho")
def decode(raw: str | bytes) -> Envelope    # valida tudo de §1.3; nunca devolve corpo parcial
def responder(env: Envelope, t: Tipo, corpo: Corpo, de: str) -> Envelope   # para=env.de, resp=env.id
```

### 1.2 Tipos de corpo

| `t` | Sentido | Pede resposta | Dataclass |
| --- | --- | --- | --- |
| `ola` | nó → Ayanami (1º frame) | `ack` | `Ola` |
| `bate` | nó → Ayanami, 10 s | não | `Bate` |
| `turno` | Ayanami → PC | `turno_fim` | `Turno` |
| `turno_fim` | PC → Ayanami | `ack` | `TurnoFim` |
| `acao` | Ayanami → casa/PC; PC → casa no elo local (§10.2) | `acao_ok` | `Acao` |
| `acao_ok` | casa/PC → Ayanami | não | `AcaoOk` |
| `estado` | casa → Ayanami/PC (mudança + a cada 60 s; pedido vazio no elo local) | não | `Estado` |
| `evento` | Ayanami → PC | `ack` | `Evento` |
| `confirma` | Ayanami → PC (pergunta) / PC → Ayanami (resposta, `resp`) | resposta ou expira | `Confirma` |
| `resumo_nuvem` | Ayanami → PC | `ack` com ids | `ResumoNuvem` |
| `ack` / `erro` | qualquer | não | `Ack` / `Erro` |

```python
class TipoDispositivo(StrEnum): PC = "pc"; CASA = "casa"; CELULAR = "celular"; MCP = "mcp"

@dataclass(frozen=True, slots=True)
class Ola:
    tipo: TipoDispositivo
    versao: str                       # versão do pacote (ex.: "0.9.0+ecf2c08")
    caps: tuple[str, ...] = ()        # pc: "turno","acao","evento","resumo"; casa: "acao","estado"
    retomar_desde: str | None = None  # último id de evento recebido (reentrega do que faltou)
    tvs: tuple[TvInfo, ...] = ()      # só casa: TVs configuradas (slot `tv`, botões do PWA)
    apps: tuple[AppInfo, ...] = ()    # só casa: nomes/apelidos do apps.yaml
    token: str | None = None          # só no elo local PC → casa (§10.2); a Ayanami recusa ola com token

@dataclass(frozen=True, slots=True)
class Bate:
    seq: int                          # ≥ 0, crescente por conexão
    custos_mes_usd: float | None = None   # só o pc: total do mês no Budget local (§6.4)

@dataclass(frozen=True, slots=True)
class Turno:
    turno: str                        # ULID do turno (também nos quadros binários)
    satelite: str = "celular"         # SatelliteHello.satellite usado no PC
    texto: str | None = None          # ≤ 4000 caracteres; exclusivo com audio
    audio: bool = False               # True → quadros binários AUDIO_IN seguem; fim = AUDIO_FIM
    dispositivo: str = ""             # nome do celular de origem (auditoria, selo)

@dataclass(frozen=True, slots=True)
class CardElo:
    titulo: str; texto: str = ""; url: str | None = None; nivel: str = "info"   # espelha CardMsg

@dataclass(frozen=True, slots=True)
class TurnoFim:
    turno: str
    ok: bool
    texto: str = ""                   # full_text ou speech; ≤ 16000 caracteres
    fala: str = ""                    # o que foi falado (≤ 2 frases salvo long_speech)
    cards: tuple[CardElo, ...] = ()
    expressao: str | None = None
    audio: bool = False               # True → houve AUDIO_OUT antes deste envelope
    erro: str | None = None           # código curto, nunca texto de exceção

@dataclass(frozen=True, slots=True)
class AcaoPedido:                     # ActionRequest serializável (sem TurnContext)
    intent: str                       # IntentId (ex.: "tv.volume")
    slots: tuple[tuple[str, str], ...] = ()   # (SlotName, value)
    texto: str = ""
    confirmed: bool = False
    args: Mapping[str, str | int | float | bool] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class Acao:
    pedido: AcaoPedido
    origem: str                       # "voz-pc" | "pwa" | "mcp" | "nuvem"
    prazo_ms: int = 8000              # 500..30000; 10000 em tv.power_on e tv.volume absoluto

@dataclass(frozen=True, slots=True)
class AcaoResultado:
    ok: bool
    fala: str = ""
    motivo: str | None = None         # valor de Motivo (§10.5), ex.: "nao_suportado","sem_mac","tempo_esgotado"
    precisa_confirmar: bool = False   # ActionResult.needs_confirmation (on_confirm não viaja: reenvia com confirmed=True)
    perigosa: bool = False
    dados: Mapping[str, Any] = field(default_factory=dict)   # ≤ 4 KiB; tv.*: {"tv","emulado","detalhe","estado":EstadoTv}

@dataclass(frozen=True, slots=True)
class AcaoOk:
    resultado: AcaoResultado

@dataclass(frozen=True, slots=True)
class TvInfo:                         # [DS19] parte fixa da TV (casa.toml + capacidades)
    id: str; nome: str; driver: str   # "samsung" | "roku" | "androidtv"
    apelidos: tuple[str, ...] = (); caps: tuple[str, ...] = ()   # valores de Cap (§10.5), já com as emuladas
    entradas: tuple[str, ...] = (); apps: tuple[str, ...] = (); padrao: bool = False

@dataclass(frozen=True, slots=True)
class AppInfo:
    id: str; nome: str; apelidos: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class EstadoTv:                       # [DS19] tipo único do estado vivo da TV
    id: str; nome: str; driver: str
    online: bool                      # respondeu à última sondagem/conexão
    ligada: bool | None = None        # None = não sabe (Samsung pré-2018 desligada = offline)
    app: str | None = None            # id do apps.yaml se reconhecido, senão nome cru
    volume: int | None = None         # 0–100, só se a TV informa (Android TV); nunca estimado
    mudo: bool | None = None
    entrada: str | None = None
    visto: datetime | None = None     # última resposta da TV

@dataclass(frozen=True, slots=True)
class Estado:
    tvs: tuple[EstadoTv, ...] = ()    # ≤ 16; vazio só no elo local = "me manda o estado" (§10.2)

class EventoTipo(StrEnum):
    TAREFA_PRONTA = "tarefa_pronta"; TAREFA_FALHOU = "tarefa_falhou"; MONITOR = "monitor"
    LEMBRETE = "lembrete"; NOTICIA_BOMBA = "noticia_bomba"; BACKUP_FALHOU = "backup_falhou"
    CONFIRMACAO = "confirmacao"; DISPOSITIVO = "dispositivo"

@dataclass(frozen=True, slots=True)
class Evento:
    seq: int                          # eventos.id (§3), base do retomar_desde e do SSE Last-Event-ID
    tipo: EventoTipo
    titulo: str                       # ≤ 80 caracteres, sem dado sensível (vai ao push, R9.3)
    resumo: str = ""                  # ≤ 200 caracteres
    ref: str | None = None            # "tarefa:<uuid>", "confirma:<ulid>", "noticia:<uid>"
    proativo: bool = True             # PC enfileira na proatividade (R9.2)

@dataclass(frozen=True, slots=True)
class Confirma:
    pedido: str                       # ULID da confirmação
    descricao: str = ""               # frase falável ("desligar a TV da sala")
    origem: str = "mcp"
    expira_em: datetime | None = None # pergunta: agora + 120 s
    resposta: bool | None = None      # só na resposta (PC/celular)

@dataclass(frozen=True, slots=True)
class TurnoNuvem:
    uid: str                          # uuid de nuvem_turnos
    ts: datetime
    dispositivo: str
    texto_usuario: str
    texto_resposta: str
    ferramentas: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class ResumoNuvem:
    turnos: tuple[TurnoNuvem, ...]    # 1..50 por envelope; mais = vários envelopes
    restam: int = 0

@dataclass(frozen=True, slots=True)
class Ack:
    ids: tuple[str, ...] = ()         # resumo_nuvem: uids gravados; demais: vazio (vale o resp)

@dataclass(frozen=True, slots=True)
class Erro:
    codigo: str                       # "invalido","nao_autorizado","escopo","offline","tempo","interno"
    msg: str = ""                     # ≤ 200 caracteres, sem segredo
```

`magi/elo/converte.py`:

```python
def pedido_de_request(req: ActionRequest) -> AcaoPedido
def request_de_pedido(p: AcaoPedido, ctx: TurnContext) -> ActionRequest   # Intent(id, slots, danger do intents.yaml)
def resultado_de_action(res: ActionResult) -> AcaoResultado
def card_de_cardmsg(c: CardMsg) -> CardElo
```

### 1.3 Validação e entrega

- `v != 1` → `EloError("versao")`; `t` fora de `Tipo` → `"tipo"`; campo obrigatório ausente ou de
  tipo errado, `id` que não é ULID, `ts` sem fuso → `"campo"`; `de`/`para` fora de `NOME_RE`
  (salvo `"ayanami"`, `"pc"`, `"casa"`) → `"nome"`; texto > limite → `"tamanho"`.
- Campos **desconhecidos** no corpo são ignorados (compatibilidade para frente); no envelope, idem.
- Quem recebe um frame inválido responde `erro` (`codigo="invalido"`) e **não** derruba a conexão;
  10 inválidos em 60 s fecham a WS com código 1008.
- Quem pede resposta reenvia o **mesmo** envelope (mesmo `id`) após 10 s sem resposta, até 3 vezes;
  o receptor guarda os últimos 512 ids e responde de novo sem reexecutar (`acao` nunca roda 2×).
- `acao` sem `acao_ok` em `prazo_ms` → a API responde ao cliente `AcaoResultado(ok=False,
  motivo="tempo_esgotado")`; um `acao_ok` atrasado só vai à auditoria.

### 1.4 Quadros binários (áudio do turno)

Cabeçalho de 18 bytes + carga: `versao:u8 (=1)`, `tipo:u8` (`1` AUDIO_IN, `2` AUDIO_OUT, `3`
AUDIO_FIM), `turno:16 bytes` (ULID binário), carga PCM s16le mono **16 kHz** em AUDIO_IN (80 ms =
2560 bytes) e **24 kHz** em AUDIO_OUT (formato do `PcmFormat` do TTS; a API converte para opus).
AUDIO_FIM tem carga vazia. Carga > 8174 bytes → `EloError("tamanho")`.

```python
class QuadroTipo(IntEnum): AUDIO_IN = 1; AUDIO_OUT = 2; AUDIO_FIM = 3
@dataclass(frozen=True, slots=True)
class Quadro:
    tipo: QuadroTipo; turno: str; pcm: bytes = b""
def encode_quadro(q: Quadro) -> bytes
def decode_quadro(raw: bytes) -> Quadro
```

**Aceite.**
- **CA-Y1** Ida e volta `decode(encode(env)) == env` para um exemplo de cada um dos 12 tipos,
  incluindo `ts` com milissegundos e texto com acentos/emoji.
- **CA-Y2** `decode` reprova (com o `codigo` certo) `v=2`, `t="xyz"`, `id` inválido, `ts` sem
  fuso, `de="Pedro PC"`, corpo de `acao` sem `pedido` e JSON > 64 KiB; aceita campo extra.
- **CA-Y3** `encode_quadro`/`decode_quadro` ida e volta nos 3 tipos; carga de 8175 bytes e
  cabeçalho com versão 2 são recusados.
- **CA-Y4** `pedido_de_request`→`request_de_pedido` preserva intent, slots, `confirmed` e `args`;
  `resultado_de_action` com `needs_confirmation=True` dá `precisa_confirmar=True` sem `on_confirm`.
- **CA-Y5** Receptor com cache de ids: o mesmo `acao` entregue 3× executa o handler 1× e responde
  3× o mesmo `acao_ok`; 10 frames inválidos em 60 s fecham com 1008.

## 2. API da Ayanami

FastAPI + uvicorn, 1 processo, `127.0.0.1:8740`, publicado por `tailscale serve --bg --https=443
http://127.0.0.1:8740`. Base `https://ayanami.<tailnet>.ts.net`. Corpo JSON UTF-8, datas ISO-8601
com `Z`. Erro sempre `{"erro": "<codigo>", "msg": "<frase curta>"}`.

### 2.1 Tokens e escopos

- Formato `ayn_<tipo>_<43 caracteres base64url sem padding de 32 bytes de secrets.token_bytes>`
  (ex.: `ayn_pc_Q2h…`). Guarda-se `sha256(token)` hex e o prefixo `ayn_<tipo>_<4 primeiros>` para
  listar. Cabeçalho `Authorization: Bearer <token>`; na WS também `?token=` não é aceito (só
  cabeçalho; o PWA usa SSE + REST, nunca WS).
- Cache de verificação em memória com TTL **5 s**; revogar limpa a entrada e fecha WS/SSE do
  dispositivo na hora (R1.4: ≤ 5 s em qualquer caso).

| Escopo | Libera | Tipos que recebem por padrão |
| --- | --- | --- |
| `conversa` | `/v1/turno*`, `/v1/eventos`, `/v1/confirma/*`, `/v1/push/assinar`, `/v1/dispositivo/preferencias` | pc, celular |
| `casa` | `/v1/casa/*` (pedir ação e ler estado) | pc, celular |
| `casa-executar` | receber `acao` e enviar `estado` pela WS | casa |
| `tarefas` | `/v1/tarefas*`, `/v1/fila` | pc, celular, mcp |
| `feed` | `/v1/feed` | pc, celular |
| `noticias` | `/v1/noticias*` | pc |
| `custos` | `/v1/custos` | pc |
| `backup` | `/v1/backup/pc` | pc |
| `ler` | tools MCP de leitura (§8) | mcp |
| `memoria-escrever` | tool MCP `memoria_gravar` | — (D13a: desligado) |

### 2.2 Rotas

| Método e caminho | Escopo | Corpo / parâmetros | Respostas |
| --- | --- | --- | --- |
| `GET /saude` | nenhum (só tailnet) | — | `200` `{"ok":bool,"banco":"ok"\|"falha","fila":{"rapida":{"todo":n,"doing":n,"failed_24h":n},…},"workers":{"rapido":"2026-…Z",…},"ultimo_backup":{"pc":ts\|null,"ayanami":ts\|null,"restic":ts\|null},"online":{"pc":bool,"casa":bool,"celulares":n}}`; `503` se banco falhar |
| `GET /ws` (upgrade) | tipo `pc` ou `casa` | 1º frame `ola` em ≤ 5 s | `101`; `401` token; `403` tipo; fecha `4001` revogado, `4002` outra conexão do mesmo dispositivo (a nova vence), `1008` abuso |
| `GET /v1/longpoll?desde=<seq>&espera=25` | `pc`/`casa` | — | `200` `{"envelopes":[…],"ate":seq}` (vazio após 25 s) |
| `POST /v1/longpoll` | `pc`/`casa` | `{"envelopes":[…]}` (≤ 20) | `200` `{"respostas":[…]}` |
| `POST /v1/pareamento` | tipo `pc` | `{"nome_sugerido":"celular-pedro"}` | `201` `{"codigo":"482913","expira_em":ts}` (6 dígitos, 5 min, uso único; novo código invalida o anterior) |
| `POST /v1/pareamento/trocar` | nenhum | `{"codigo":"482913","nome":"celular-pedro"}` | `201` `{"token":…,"nome":…,"escopos":[…]}`; `400` código errado/expirado; `409` nome em uso; `429` > 5 tentativas/min por IP ou 10 erros no código vigente (o código morre) |
| `DELETE /v1/dispositivo` | qualquer | — | `204` revoga o próprio token ("sair" no PWA) |
| `PUT /v1/dispositivo/preferencias` | `conversa` | `{"push":bool,"push_com_pc":bool,"silencio":"23:00-07:30"\|"","tv_padrao":str\|null,"voz_em_texto":bool}` (§16.1) | `204` (grava `dispositivos.preferencias`); `422` |
| `POST /v1/turno` | `conversa` | JSON `{"texto":"…"}` **ou** `multipart` campo `audio` (`audio/webm;codecs=opus`, ≤ 1 MiB, ≤ 15 s) | `202` `{"turno":ulid,"modo":"pc"\|"nuvem"}`; `413`; `415`; `429` (> 20/min) |
| `GET /v1/turno/{id}` | `conversa` | — | `200` `{"turno","estado":"andando"\|"fim","fim":TurnoFim\|null}`; `404` (só o dono vê) |
| `GET /v1/turno/{id}/audio` | `conversa` | — | `200` `audio/ogg;codecs=opus` (streaming enquanto gera); `410` após 60 s do fim (apagado, R7.3) |
| `GET /v1/eventos` (SSE) | `conversa` | `Last-Event-ID` opcional | `text/event-stream`; eventos `turno.texto` `{"turno","texto"}`, `turno.fim` `TurnoFim`, `evento` `Evento` (`id:` = `seq`), `estado` `Estado`, `confirma` `Confirma`, `ping` (15 s); `data:` = JSON do corpo |
| `POST /v1/confirma/{pedido}` | `conversa` | `{"resposta":true}` | `200`; `410` expirada; `409` já respondida |
| `POST /v1/casa/acao` | `casa` | `{"tv":"TV da sala"\|null,"pedido":AcaoPedido}` | `200` `AcaoResultado`; `202` `{"confirma":ulid}` se `danger` vindo do MCP; `503` `casa_offline`; `504` `tempo_esgotado` (após `prazo_ms`: 8 s; 10 s em `tv.power_on`/volume absoluto); a API preenche `fala` pela tabela da §13.2 |
| `GET /v1/casa/estado` | `casa` ou `ler` | — | `200` `{"online":bool,"visto":ts,"tvs":[TvInfo],"estados":[EstadoTv],"apps":[AppInfo]}` (do último `ola`/`estado` da casa) |
| `GET /v1/feed?antes=<ts>&n=30` | `feed` | `n` 1..100 | `200` `{"cards":[{"tipo":"noticia"\|"tarefa"\|"lembrete","titulo","resumo","ts","ref"}]}` |
| `GET /v1/tarefas?estado=&n=50` | `tarefas` | — | `200` `{"tarefas":[TarefaOut]}` |
| `POST /v1/tarefas` | `tarefas` | `TarefaIn` (§4.3) | `201` `TarefaOut`; `200` `TarefaOut` existente (mesma `chave`, R2.2); `422` |
| `GET /v1/tarefas/{id}` | `tarefas` | — | `200` `TarefaOut`; `404` |
| `DELETE /v1/tarefas/{id}` | `tarefas` | — | `202` `{"estado":"cancelando"\|"cancelada"}`; `409` já terminou |
| `GET /v1/fila` | `tarefas` | — | `200` contagem por estado e fila, 10 mais lentas (em `doing`), 10 últimas falhas |
| `POST /v1/push/assinar` | `conversa` | `PushSubscription.toJSON()` (preferências vão em `/v1/dispositivo/preferencias`) | `201`; `DELETE` mesmo caminho `{"endpoint"}` → `204` |
| `GET /v1/noticias?desde=<cursor>&n=200` | `noticias` | — | `200` §5.2 |
| `PUT /v1/noticias/preferencias` | `noticias` | `{"franchise_prefs":[…],"progress":[…]}` | `204` |
| `GET /v1/custos?desde=<uid>` | `custos` | — | `200` `{"linhas":[{uid,at,provider,task,model,input_units,output_units,usd}]}` |
| `PUT /v1/backup/pc` | `backup` | corpo binário `.tar.zst`, cabeçalhos `X-Sha256`, `X-Data` (`AAAA-MM-DD`), `X-Manifesto` (base64 JSON) | `201` `{"recebido":bytes}`; `400` sha256 não confere (arquivo apagado); `413` > 2 GiB; `409` mesma data já recebida e íntegra |
| `GET /app/*` | nenhum | PWA estático (§14) | `200` |
| `/mcp` | token `mcp` | §8 | — |

`TarefaOut` = `{"id":uuid,"tipo","titulo","estado":"na_fila"|"rodando"|"ok"|"falhou"|"cancelada",
"progresso":0..100|null,"frase":str|null,"origem","criada","atualizada","resultado":{"texto",
"dados"}|null,"erro":str|null}`.

### 2.3 Limites gerais

60 req/min por dispositivo (exceto `/ws`, `/v1/eventos`, `/v1/longpoll`) → `429` com
`Retry-After`; corpo JSON ≤ 256 KiB salvo `/v1/turno` (1 MiB) e `/v1/backup/pc` (2 GiB, em
streaming para disco); 1 WS por dispositivo; até 4 SSE por celular. Logs: método, rota, status,
dispositivo, ms e tamanhos — nunca corpo, token nem áudio (R10.1). Toda rota de `casa`, `backup`,
dispositivo e MCP grava `auditoria`.

**Aceite.**
- **CA-Y6** Token: formato e regex `^ayn_(pc|casa|celular|mcp)_[A-Za-z0-9_-]{43}$`; só o sha256
  vai ao banco; token desconhecido → 401; escopo faltando → 403 em cada linha da tabela §2.2.
- **CA-Y7** Revogar um `pc` com WS aberta (cliente ASGI de teste): a WS fecha com `4001` e o
  próximo REST dá 401 em ≤ 5 s com relógio falso.
- **CA-Y8** Pareamento: código de 6 dígitos expira em 5 min, é de uso único, o 11º erro o mata e
  o 6º pedido/min do mesmo IP dá 429; o token emitido tem os escopos de `celular`.
- **CA-Y9** `/saude` responde sem token, não contém nome de TV, texto, e-mail nem token (varredura
  das chaves do JSON contra uma lista de proibidas) e dá 503 com banco falso fora.
- **CA-Y10** `POST /v1/casa/acao` com casa offline → 503 `casa_offline`; com casa falsa que não
  responde → 504 em 8 s (relógio falso); `PUT /v1/backup/pc` com sha256 errado → 400 e nada fica
  em disco.

## 3. Banco da Ayanami

`ayanami-pg` (`pgvector/pgvector:pg16`), base `ayanami`, usuário `ayanami`. Migrações em
`ayanami/migrations/NNN_*.sql`, aplicadas por `ayanami migrar` com a tabela
`schema_migracoes(versao text PRIMARY KEY, aplicada timestamptz)`; o esquema do `procrastinate`
é da lib (`procrastinate schema --apply`, mesmo serviço `migrar`). Nada de `DROP` em migração.

```sql
-- 001_base.sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;              -- gen_random_uuid

CREATE TABLE dispositivos (
    id         serial PRIMARY KEY,
    nome       text NOT NULL UNIQUE CHECK (nome ~ '^[a-z0-9][a-z0-9-]{0,31}$' AND nome <> 'ayanami'),
    tipo       text NOT NULL CHECK (tipo IN ('pc','casa','celular','mcp')),
    escopos    text[] NOT NULL,
    hash       text NOT NULL UNIQUE,                 -- sha256 hex do token
    prefixo    text NOT NULL,
    criado     timestamptz NOT NULL DEFAULT now(),
    ultimo_uso timestamptz,
    visto      timestamptz,                          -- último ola/bate
    revogado   timestamptz,
    preferencias jsonb NOT NULL DEFAULT '{}'         -- celular: §16.1 (PUT /v1/dispositivo/preferencias)
);
CREATE UNIQUE INDEX dispositivos_pc_unico ON dispositivos (tipo) WHERE tipo = 'pc' AND revogado IS NULL;

CREATE TABLE pareamentos (
    codigo_hash text PRIMARY KEY, criado_por integer NOT NULL REFERENCES dispositivos (id),
    nome_sugerido text, expira timestamptz NOT NULL, usado timestamptz, erros smallint NOT NULL DEFAULT 0
);

CREATE TABLE tarefas (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      bigint,                              -- procrastinate_jobs.id (sem FK: tabela da lib)
    tipo        text NOT NULL CHECK (tipo IN ('pesquisa','resumo','lembrete','monitor','stt','sistema')),
    titulo      text NOT NULL CHECK (length(titulo) <= 120),
    chave       text,                                -- idempotência (R2.2)
    estado      text NOT NULL DEFAULT 'na_fila'
                CHECK (estado IN ('na_fila','rodando','ok','falhou','cancelada')),
    progresso   smallint CHECK (progresso BETWEEN 0 AND 100),
    frase       text,
    origem      integer REFERENCES dispositivos (id),
    params      jsonb NOT NULL DEFAULT '{}',
    pessoal     boolean NOT NULL DEFAULT false,      -- R3.5: true → nunca provedor free_tier
    avisar      boolean NOT NULL DEFAULT true,
    resultado   jsonb,                               -- {"texto": str, "dados": {...}}
    erro        text,                                -- código + frase, sem segredo
    agenda      timestamptz,                         -- lembrete / próximo passo do monitor
    expira      timestamptz,                         -- monitor: padrão criada + 30 dias
    criada      timestamptz NOT NULL DEFAULT now(),
    atualizada  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX tarefas_chave_viva ON tarefas (chave) WHERE estado IN ('na_fila','rodando');
CREATE INDEX tarefas_estado_idx ON tarefas (estado, atualizada DESC);

CREATE TABLE eventos (
    id        bigserial PRIMARY KEY,                 -- = Evento.seq e id do SSE
    tipo      text NOT NULL, titulo text NOT NULL, resumo text NOT NULL DEFAULT '',
    ref       text, para text[] NOT NULL DEFAULT '{pc,celular}',
    criado    timestamptz NOT NULL DEFAULT now(),
    entregue_pc timestamptz, push_enviado timestamptz
);

CREATE TABLE auditoria (
    id bigserial PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(),
    dispositivo integer REFERENCES dispositivos (id), tipo text NOT NULL,   -- casa|mcp|dispositivo|backup|tarefa|push
    alvo text, resumo text NOT NULL CHECK (length(resumo) <= 300), ok boolean NOT NULL
);
CREATE INDEX auditoria_ts_idx ON auditoria (ts);

CREATE TABLE push_assinaturas (
    id serial PRIMARY KEY, dispositivo integer NOT NULL REFERENCES dispositivos (id) ON DELETE CASCADE,
    endpoint text NOT NULL UNIQUE, p256dh text NOT NULL, auth text NOT NULL,
    criada timestamptz NOT NULL DEFAULT now(), falhas smallint NOT NULL DEFAULT 0
);

CREATE TABLE confirmacoes (
    id text PRIMARY KEY,                             -- ULID
    origem integer REFERENCES dispositivos (id), descricao text NOT NULL,
    pedido jsonb NOT NULL, expira timestamptz NOT NULL, resposta boolean, respondida timestamptz
);

CREATE TABLE nuvem_turnos (
    uid uuid PRIMARY KEY DEFAULT gen_random_uuid(), ts timestamptz NOT NULL DEFAULT now(),
    dispositivo integer REFERENCES dispositivos (id), texto_usuario text NOT NULL,
    texto_resposta text NOT NULL, ferramentas text[] NOT NULL DEFAULT '{}', sincronizado timestamptz
);

CREATE TABLE costs (                                 -- mesmo esquema do magi-pg + uid/source
    id bigserial PRIMARY KEY, uid uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    at timestamptz NOT NULL DEFAULT now(), provider text NOT NULL, task text NOT NULL, model text,
    input_units bigint NOT NULL DEFAULT 0, output_units bigint NOT NULL DEFAULT 0,
    usd numeric(12, 6) NOT NULL DEFAULT 0, source text NOT NULL DEFAULT 'nuvem'
);
CREATE TABLE custos_pc (mes date PRIMARY KEY, usd numeric(12, 6) NOT NULL, visto timestamptz NOT NULL);

CREATE TABLE backups (
    id serial PRIMARY KEY, origem text NOT NULL CHECK (origem IN ('pc','ayanami')),
    data date NOT NULL, bytes bigint NOT NULL, sha256 text NOT NULL, manifesto jsonb NOT NULL,
    recebido timestamptz NOT NULL DEFAULT now(), snapshot text, enviado timestamptz,
    UNIQUE (origem, data)
);
CREATE TABLE restore_testes (
    id serial PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(), snapshot text,
    verde boolean NOT NULL, detalhes jsonb NOT NULL
);
CREATE TABLE workers_batimento (fila text PRIMARY KEY, host text NOT NULL, visto timestamptz NOT NULL);
```

`002_noticias.sql`: cópia das `CREATE TABLE news_*`, `franchise_prefs`, `progress` do
`magi/memory/migrations/001_init.sql` (mesma dimensão `{{NEWS_DIM}}`, mesmo renderizador), mais:

```sql
ALTER TABLE news_items ADD COLUMN uid uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE;
ALTER TABLE news_items ADD COLUMN atualizado timestamptz NOT NULL DEFAULT now();
CREATE INDEX news_items_atualizado_idx ON news_items (atualizado, id);
-- gatilho news_items_toca: BEFORE UPDATE → NEW.atualizado = now()
```

No `magi-pg` do PC, **migração aditiva** `magi/memory/migrations/005_ayanami_sync.sql` [DS5]:
`ALTER TABLE news_items ADD COLUMN IF NOT EXISTS ayanami_uid uuid UNIQUE;` e
`ALTER TABLE costs ADD COLUMN IF NOT EXISTS origem_uid uuid UNIQUE;` (nulos nas linhas locais).

Retenção (job `limpeza.diaria`, §4): `auditoria` > 90 dias; `eventos` > 30 dias; `nuvem_turnos`
sincronizados > 30 dias; `confirmacoes` > 7 dias; jobs `succeeded`/`cancelled` do `procrastinate`
> 30 dias; `pareamentos` expirados > 1 dia.

**Aceite.**
- **CA-Y11** (`pg`) `ayanami migrar` num banco vazio aplica 001–002, é idempotente na 2ª vez e o
  texto das migrações não contém `DROP` nem `TRUNCATE` (teste lê os arquivos, inclusive o 005 do PC).
- **CA-Y12** (`pg`) `tarefas_chave_viva`: 2ª inserção com a mesma `chave` falha enquanto a 1ª está
  `na_fila`/`rodando` e passa depois que ela vira `ok`; 2º `pc` não revogado é recusado.

## 4. Fila (`procrastinate` 3.10.0)

`ayanami/fila.py`: `app = procrastinate.App(connector=PsycopgConnector(conninfo=DSN))`, importado
pela API (só `defer`) e pelos workers. Testes trocam por `InMemoryConnector`.

### 4.1 Filas e workers

| Fila | Serviço Compose | Comando | Concorrência | Limites |
| --- | --- | --- | --- | --- |
| `rapida` | `worker-rapido` | `ayanami worker rapida` | 8 | `cpus: 1`, `mem_limit: 512m` |
| `agendada` | `worker-agendado` | `ayanami worker agendada` (único com `periodic`) | 2 | `cpus: 1.5`, `mem_limit: 1g` |
| `lenta` | `worker-lento` | `ayanami worker lenta` | 1 | `cpus: 4`, `mem_limit: 6g`, `cpu_shares: 512` |

`ayanami worker <fila>` = `app.run_worker_async(queues=[fila], concurrency=n,
shutdown_graceful_timeout=30, listen_notify=True)` + tarefa de fundo que grava
`workers_batimento` a cada 30 s. Job em `doing` de worker morto (sem batimento > 5 min) volta a
`todo` pelo job `fila.reanimar` a cada 5 min. **S5 (Y0.4):** a 3.10 **não tem**
`retry_stalled_jobs`; o `fila.reanimar` faz `for j in await app.job_manager.get_stalled_jobs(
seconds_since_heartbeat=300): await app.job_manager.retry_job(j)` (usa o batimento da própria lib,
`procrastinate_workers`, a cada `update_heartbeat_interval=10` s; o worker com `kill -9` deixa o job
em `doing` e ele volta em `todo` → roda de novo do começo, `attempts` +1). Parada limpa
(`SIGTERM`/`docker stop`) com `shutdown_graceful_timeout=30`: após 30 s o job é abortado com motivo
"shutdown" e, se a tarefa tem `retry`, volta sozinho a `todo` gastando uma tentativa (sem `retry`
fica `aborted`): tarefas longas (§4.2, 30–90 min) precisam ser retomáveis e ter `a` ≥ 2. O
`docker stop` do Compose precisa de `stop_grace_period` ≥ 35 s nos workers.

### 4.2 Tarefas registradas

`retry` = `RetryStrategy(max_attempts=a, wait=w, exponential_wait=2)` (espera ≈ `w` + 2^tentativa
s). Prioridade [DS4]: `20` pedido do Pedro, `10` monitor/lembrete, `0` lote e manutenção.

| Nome | Fila | Gatilho | Prazo | `a` / `w` | Lock | Faz |
| --- | --- | --- | --- | --- | --- | --- |
| `agente.pesquisar` | rapida | `POST /v1/tarefas` tipo `pesquisa`/`resumo` | 30 min | 2 / 30 | `queueing_lock=chave` | §5.3 |
| `agente.lembrete` | rapida | `schedule_at=agenda` | 1 min | 3 / 10 | `queueing_lock=chave` | cria `evento` lembrete |
| `monitor.passo` | rapida | `monitores.varrer` | 5 min | 2 / 30 | `lock="monitor:<id>"` | um passo do monitor (§5.3) |
| `push.enviar` | rapida | após cada `evento` com `celular` em `para` | 30 s | 3 / 5 | — | §15 |
| `monitores.varrer` | agendada | cron `*/15 * * * *` | 1 min | 1 | `lock="varrer"` | defere `monitor.passo` dos vencidos |
| `noticias.coletar` | agendada | cron `0 */2 * * *` | 45 min | 2 / 300 | `lock="noticias"` | §5.1 |
| `progresso.atualizar` | agendada | cron `15 */6 * * *` | 10 min | 2 / 300 | `lock="progresso"` | AniList/Steam (só local, nunca Gemini) |
| `backup.restic` | agendada | `PUT /v1/backup/pc` aceito | 60 min | 3 / 600 | `lock="restic"` | §7 |
| `backup.dump_ayanami` | agendada | cron `0 7 * * *` | 15 min | 2 / 60 | `lock="restic"` | §7 |
| `backup.enviar` | agendada | cron `30 7 * * *` | 60 min | 3 / 600 | `lock="restic"` | §7 |
| `backup.reter` | agendada | cron `0 8 * * 0` | 60 min | 2 / 600 | `lock="restic"` | §7 |
| `backup.verificar` | agendada | cron `30 8 * * 0` | 90 min | 1 | `lock="restic"` | §7 |
| `backup.restore_teste` | agendada | cron `0 9 1 * *` | 90 min | 1 | `lock="restic"` | §7 |
| `limpeza.diaria` | agendada | cron `30 6 * * *` | 10 min | 2 / 60 | `lock="limpeza"` | §3 retenção; `entrada/` > 2 dias |
| `fila.reanimar` | agendada | cron `*/5 * * * *` | 1 min | 1 | `lock="reanimar"` | jobs presos |
| `stt.transcrever` | lenta | tarefa tipo `stt` | 60 min | 2 / 60 | `queueing_lock=chave` | §5.5 |
| `voz.cache_frases` | lenta | cron `0 6 * * 1` | 30 min | 1 | `lock="voz"` | §5.4 |
| `embeddings.lote` | lenta | A8 (desligada) | 30 min | 2 / 60 | `lock="emb"` | §5.6 |

**Crons em UTC (S5):** o `periodic` da 3.10 calcula o cron sobre o timestamp em UTC e **ignora o
`TZ`** do contêiner (com `TZ=America/Sao_Paulo`, `0 4 * * *` dispara 01:00 local). Os crons acima
já estão em UTC = local + 3 h (São Paulo sem horário de verão desde 2019): dump 04:00, envio 04:30,
retenção dom 05:00, verificação dom 05:30, restore dia 1 06:00, limpeza 03:30, cache de voz seg
03:00 (horário de Brasília). `TZ=America/Sao_Paulo` segue nos contêineres para logs e
`agenda`/lembretes.

Prazo: `asyncio.timeout(prazo)` dentro da tarefa; estourou → `falhou` com `erro="prazo"` sem
retry. Periódicas usam `periodic_id` = nome; `queueing_lock` das periódicas = nome (sem
acúmulo se o worker ficar parado).

### 4.3 Criar, ver e cancelar

```python
@dataclass(frozen=True, slots=True)
class TarefaIn:
    tipo: Literal["pesquisa", "resumo", "lembrete", "monitor", "stt"]
    titulo: str                          # 1..120
    params: Mapping[str, Any]            # pesquisa: {"pedido": str ≤ 2000}; lembrete: {"texto", "quando"};
                                         # monitor: {"o_que": str, "condicao": str, "a_cada_h": 1..6 (padrão 2),
                                         #           "expira_dias": 1..90 (padrão 30)}; stt: {"arquivo": id}
    chave: str | None = None             # ≤ 128; None → sha256(tipo + params normalizados)
    pessoal: bool = False
    avisar: bool = True

async def criar_tarefa(db: Db, t: TarefaIn, origem: int) -> tuple[TarefaOut, bool]   # (tarefa, criada?)
async def cancelar_tarefa(db: Db, id: UUID) -> Literal["cancelada", "cancelando"]
```

`criar_tarefa`: numa transação insere em `tarefas` (conflito em `tarefas_chave_viva` → devolve a
existente, `criada=False`) e chama `defer_async` com `queueing_lock=chave`; `AlreadyEnqueued` também
devolve a existente. (S5: o `queueing_lock` só barra enquanto o job está em `todo`; com o 1º em
`doing` um 2º `defer` com a mesma chave é aceito — quem segura a idempotência durante a execução é o
`tarefas_chave_viva`.) Estado: `todo`→`na_fila`, `doing`→`rodando`, `succeeded`→`ok`,
`failed`→`falhou`, `cancelled`/`aborted`→`cancelada` (sincronizado pela própria tarefa e por um
`worker_middleware` no worker — S5: a 3.10 **não tem** `on_job_status`; o middleware `async def
(call_next, context, worker)` passado em `run_worker_async(worker_middleware=[…])` vê o início e o
desfecho de cada job, async e síncrono: retorno → `ok`, `JobAborted`/`CancelledError` → `cancelada`,
outra exceção → `falhou` ou, se o `retry` ainda tem tentativa, `na_fila`; o cancelamento em `todo`
nunca chega ao worker e é gravado pelo próprio `cancelar_tarefa`). `cancelar_tarefa`: na fila → `cancel_job_by_id_async(job_id)`
(nunca começa); rodando → `cancel_job_by_id_async(job_id, abort=True)`; tarefas async veem o
abort como `asyncio.CancelledError` e as síncronas checam `context.should_abort()` a cada ≤ 5 s
→ parada em ≤ 10 s (R2.4; **S5 confirmado**: com `listen_notify=True` o pedido chega por NOTIFY —
async `aborted` em 0,02 s, síncrona com checagem a cada 5 s em ≤ 5 s; sem NOTIFY, pelo
`abort_job_polling_interval=5` s, ≤ 5 s + checagem). A tarefa síncrona levanta
`procrastinate.exceptions.JobAborted` ao ver `should_abort()`; se só retornar, vira `succeeded`. Falha após esgotar → `falhou`, `erro` sem segredo
(passa por `redigir()` que tira `sk-…`, `ayn_…`, `Bearer …`) e `evento tarefa_falhou` se
`avisar` (R2.5).

**Aceite.**
- **CA-Y13** Registro: o `app` tem exatamente as 17 tarefas da tabela (18 com `[embeddings] ligado = true`) com fila, retry, lock e cron
  iguais; nenhuma periódica fora da fila `agendada`.
- **CA-Y14** (`InMemoryConnector`) Duas `criar_tarefa` com a mesma chave → uma tarefa, a 2ª devolve
  `criada=False`; depois de `ok`, a mesma chave cria outra.
- **CA-Y15** Cancelar na fila → `cancelada` e o job nunca roda; cancelar uma tarefa async que dorme
  em laço → `cancelada` e o laço sai na 1ª checagem; erro com `sk-abc` e `ayn_pc_x` grava a
  mensagem redigida.

## 5. Workers

### 5.1 Notícias na nuvem (sai do `magi-ayanami.timer`)

`ayanami/workers/noticias.py::coletar()` chama `magi.news.__main__.run_once(config, dsn)` com o
`Config` montado de `ayanami.toml [noticias]` (mesmas fontes e o mesmo embedder/`NEWS_DIM` do PC;
a subida recusa dimensão diferente da do PC informada em `[noticias] dim`). Gemini `free_tier` só
para cluster/classificação de texto público (nunca `progress`/`franchise_prefs`). Ao fim: itens
novos com o mesmo critério de urgência do `proactive/news.py` viram `evento noticia_bomba`. Não
muda `magi/news/*` além de aceitar o DSN da Ayanami.

### 5.2 Sincronização puxada pelo PC (`magi-news-sync`)

Entrada nova `magi-news-sync = magi.elo.news_sync:main`; `deploy/systemd/magi-news-sync.timer`
(`OnBootSec=2min`, `OnUnitActiveSec=15min`, `Persistent=true`).

```
magi-news-sync [--config P] [--dsn D] [--precisa-local] [-v]
  sem flag: puxa páginas até "fim": true; exit 0 ok, 2 Ayanami fora, 3 erro de banco
  --precisa-local: exit 0 = deve coletar local (último OK > 6 h E há internet); exit 1 = não
```

Estado em `~/.local/state/magi/news_sync.json` `{"cursor": str|null, "ultimo_ok": ts|null}`.
Internet = `socket.create_connection(("1.1.1.1", 443), 3)`. `magi-ayanami.service` ganha
`ExecCondition=magi-news-sync --precisa-local` (código 1 pula a coleta sem falhar). Resposta de
`GET /v1/noticias`:

```json
{"cursor":"2026-10-12T20:00:00.000Z|8812","fim":false,
 "fontes":[{"name","kind","url","trust"}],
 "brutos":[{"url","fonte_url","title","body","published_at","fetched_at"}],
 "itens":[{"uid","title","summary","embedding":[…]|null,"first_seen","sources","max_trust",
           "franchise","kind","spoiler","priority","level","brutos":["url",…]}]}
```

Página ≤ 200 itens ordenados por `(atualizado, id)`. *Upsert* no `magi-pg` numa transação por
página: `news_sources` por `url`; `news_raw` por `url`; `news_items` por `ayanami_uid` (atualiza
tudo **menos** `delivered_at`, que é do PC); `news_item_sources` recriado só para o item. Embedding
com tamanho ≠ `NEWS_DIM` vira `NULL` + log. Depois de cada sync OK, envia `PUT
/v1/noticias/preferencias` com `franchise_prefs` e `progress` do PC (dado do Pedro só para a
Ayanami dele, RNF-A1).

### 5.3 Tarefas do agente

`agente.pesquisar` monta `GraphAgent` (`magi.agent`) com a persona da Condessa, ferramentas de
busca web e `Budget` da nuvem (§6.4), prazo 30 min, máx. 12 passos de ferramenta. `pessoal=True`
→ o registry recusa `free_tier` (R3.5). Progresso: grava `progresso`/`frase` a cada passo. Saída:
`resultado = {"texto": ≤ 6000 caracteres, "dados": {"fontes": [url…]}}` + `evento tarefa_pronta`
(título "Pesquisa pronta", resumo ≤ 200). `monitor.passo`: uma consulta (preço/página) e um juízo
do LLM barato `condicao` → `{"bateu": bool, "valor": str}`; bateu → `evento monitor`, tarefa `ok`;
senão `agenda += a_cada_h`; passou `expira` → `ok` com `"texto": "expirou sem bater"`.

### 5.4 TTS Kokoro (`ayanami-voz`)

`kokoro-onnx` 0.4.7 + `onnxruntime` 1.31.0, modelo int8 em volume `ayanami-modelos`; voz
`pf_dora`, `lang="pt-br"`. Carrega na 1ª fala, descarrega após 600 s ocioso.

| Rota (só rede Docker, `:8741`) | Entrada | Saída |
| --- | --- | --- |
| `POST /falar` | `{"texto": 1..600 caracteres, "voz": "pf_dora", "velocidade": 0.8..1.3}` | `200` PCM s16le mono 24 kHz em streaming (`X-Taxa: 24000`); `413`; `503` carregando > 20 s |
| `GET /saude` | — | `{"carregado": bool}` |

Meta S1: RTF ≤ 0,5 (frase de 4 s em ≤ 2 s); acima disso o modo nuvem usa só texto quando a
OpenAI falhar. `voz.cache_frases` gera as frases fixas do modo nuvem (§6.5) em
`/dados/modelos/cache-voz/<sha1>.ogg`.

### 5.5 STT assíncrono

`faster-whisper` 1.2.1, `small`, `compute_type="int8"`, `cpu_threads=4`, `language="pt"`, só na fila
`lenta` (nunca turno ao vivo, R3.4). Entrada: arquivo enviado por `POST /v1/tarefas` tipo `stt`
(upload prévio em `/dados/tmp/`, ≤ 200 MB, ≤ 3 h de áudio). Saída: `resultado.texto` (≤ 200 mil
caracteres; acima, `dados.arquivo` com o texto completo apagado em 7 dias). O áudio é apagado no
`finally` do job. Meta S1: RTF ≤ 0,4, RAM ≤ 2 GB.

### 5.6 Embeddings (só com A8)

`fastembed` 0.9.0, `intfloat/multilingual-e5-small` (384 dim, prefixos `query: `/`passage: `),
lotes de 64, `vector(384)`; o job não é registrado enquanto `[embeddings] ligado = false`.

**Aceite.**
- **CA-Y16** `GET /v1/noticias` pagina por `(atualizado, id)` sem pular nem repetir com 450 itens
  em 3 páginas e `fim` só na última.
- **CA-Y17** (`pg`) `magi-news-sync` contra API falsa: 2 execuções seguidas não duplicam
  `news_raw`/`news_items`; `delivered_at` local sobrevive ao *upsert*; embedding de dimensão errada
  vira `NULL`.
- **CA-Y18** `--precisa-local`: exit 0 só com `ultimo_ok` > 6 h **e** internet (socket falso);
  1 nos outros 3 casos.
- **CA-Y19** `agente.pesquisar` com agente falso: tarefa `pessoal=True` pede ao registry um provedor
  sem `free_tier`; resultado e `evento tarefa_pronta` gravados; o arquivo de áudio de um `stt` falso
  não existe mais depois do job (sucesso e falha).

## 6. Roteamento do turno e modo nuvem

### 6.1 Estados

| PC (`dispositivos.visto` do `pc`) | Casa | Modo do turno | TV pelo celular |
| --- | --- | --- | --- |
| online (< 30 s) | online | `pc` | direto à casa (botão) ou via PC (voz) |
| online | offline | `pc` | `503 casa_offline` |
| offline | online | `nuvem` | direto à casa |
| offline | offline | `nuvem` | "a casa está fora do ar" (frase em cache) |

A decisão é tomada no `POST /v1/turno` e não muda no meio do turno; se a WS do PC cair durante um
turno `pc`, o turno fecha com `TurnoFim(ok=False, erro="pc_caiu")` e o PWA mostra a frase
"perdi o PC no meio; repete?" (não refaz sozinho).

### 6.2 Modo PC

1. Texto → `Turno(texto=…)`. Áudio → `ffmpeg -i pipe: -f s16le -ac 1 -ar 16000 pipe:` (≤ 2 s
   de prazo) e quadros `AUDIO_IN` de 80 ms + `AUDIO_FIM`.
2. Prazo total do turno no PC: 45 s (agente) → senão `TurnoFim(ok=False, erro="tempo")`.
3. `AUDIO_OUT` do PC → `ffmpeg … -c:a libopus -b:a 32k -f ogg` → `GET /v1/turno/{id}/audio`;
   `turno.texto` vai pelo SSE assim que o `TurnoFim` chega (ou antes, se o gancho mandar parcial).

### 6.3 `RemoteLink` e gancho do turno no PC

```python
# magi/elo/remote.py
class RemoteLink:                                   # implementa SatelliteLink
    hello: SatelliteHello                           # SatelliteHello("celular", name="Celular", capabilities=("ptt", "playback"))
    def __init__(self, cliente: EloCliente, turno: str) -> None
    async def send(self, msg: CoreToSatellite) -> None      # ListenRequest etc.: ignora; StopPlayback: manda AUDIO_FIM
    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None   # AUDIO_OUT; fmt ≠ 24 kHz → reamostra
    async def entrada(self) -> AsyncIterator[bytes]  # PCM dos AUDIO_IN até AUDIO_FIM (fila ≤ 400 quadros = 32 s)

# magi/elo/ponte.py
class PonteTurnos:
    def __init__(self, core: CoreService, cliente: EloCliente) -> None
    async def receber(self, env: Envelope) -> None   # Turno → RemoteLink + TurnMachine do satélite "celular"
```

- Um único `TurnMachine` do satélite `celular` é criado na 1ª vez e reusado (como o Wyoming faz
  por satélite); o turno de áudio entra como PTT (`WakeSource` de PTT, `audio-stop` =
  `ptt_release`); o de texto entra pelo mesmo caminho do texto digitado do HUD (se existir) ou
  como transcrição pronta, sem STT.
- **[DS6]** `TurnDeps.on_turn_done: Callable[[TurnContext, ActionResult], Awaitable[None]] | None
  = None`, chamado pelo `TurnMachine` uma vez por turno depois do `compose` e antes de falar;
  `PonteTurnos` registra um que, para `ctx.satellite == "celular"`, envia `TurnoFim`
  (`resultado_de_action` + `card_de_cardmsg`). Para outros satélites é no-op. A resposta nunca vai
  ao headset (R8.1).
- **S6 (Y0.6, `docs/perf/ayanami-s6.md`):** o gancho fica em `TurnMachine._deliver`, logo após
  `tr_result(compose(result))` e antes de cards/legenda/fala (`announce`/`narrate` não passam por
  ele). O registro precisa de um método público novo `CoreService.anexar(link, …) -> TurnMachine`
  (espelha `_serve` sem socket; `followup_ms=None`). Texto = `TurnPipeline` do celular com as
  mesmas `deps` cujo `transcribe` devolve o texto pronto, entrando pelo mesmo PTT com um quadro
  mudo. O celular não manda `playback-done`: `RemoteLink.play` o injeta no `TurnMachine` no fim.
  `ffmpeg` local: webm 15 s → PCM 16 kHz p90 119 ms; PCM 24 kHz → ogg/opus 32k exige
  `-flush_packets 1 -page_duration 20000` (1º byte p90 100 ms).

### 6.4 Gasto e sub-teto (D11a)

```python
# ayanami/custos.py
TETO_NUVEM_USD: Final = Decimal("2.00")     # [budget] teto_nuvem_usd
TETO_GERAL_USD: Final = Decimal("5.00")     # [budget] teto_geral_usd
class BudgetNuvem:                          # mesma interface do Budget do PC (ensure_allowed/record/status)
    async def ensure_allowed(self, task: ProviderTask) -> None   # BudgetExceeded se nuvem_mes ≥ 2 ou nuvem_mes + pc_mes ≥ 5
    async def record(self, usage: Usage) -> None                 # insere em costs (source='nuvem')
```

`pc_mes` = `custos_pc` do mês corrente (vem do `Bate.custos_mes_usd`; sem valor no mês → 0 e o
teto da nuvem sozinho segura). O PC puxa `GET /v1/custos?desde=<último uid>` a cada `ola` e a
cada 15 min e insere em `costs` local com `origem_uid` (sem duplicar). Teto batido → modo nuvem
**sem LLM**: comando de TV direto por regra (mesmas frases `tv.*` do `intents.yaml`, roteador
rapidfuzz local na Ayanami), tarefas, feed e frase em cache "estou sem verba de nuvem este mês".

### 6.5 Modo nuvem

`ayanami/nuvem.py`:

```python
NUVEM_PODE: Final = ("news_query", "tarefa_criar", "tarefa_listar", "tarefa_cancelar",
                     "lembrete_criar", "monitor_criar", "estado", "tv_ligar", "tv_desligar",
                     "tv_volume", "tv_mudo", "tv_app", "tv_entrada")
async def atender(texto: str, dispositivo: str, deps: NuvemDeps) -> TurnoFim
```

- `GraphAgent` com a persona da Condessa e **só** `NUVEM_PODE`; `tv_*` só com casa online (senão a
  ferramenta devolve "a casa está fora do ar"); `tv_desligar` é `danger` → `confirma` no PWA.
- **Não pode:** memória do PC, jogos, HUD, RGB, Spotify, volume do PC, abrir/fechar coisas no PC,
  Learning Mode. Pedido desses → "isso só no PC, e ele está desligado".
- Contexto: últimos 20 `nuvem_turnos` do dispositivo; a persona ganha a linha "Agora você está na
  nuvem, sem a memória do PC; diga isso quando fizer diferença" (R8.3).
- STT: OpenAI (`[nuvem] stt_modelo`), TTS: OpenAI `marin` (D14a) com cache por texto; Kokoro se a
  OpenAI falhar 2× seguidas em 5 min ou o teto bater. Frases em cache fixas (`ayanami/frases.yaml`):
  `casa_offline`, `pc_offline_pedido`, `sem_verba`, `erro_generico`, `pc_caiu`.
- Cada turno grava `nuvem_turnos` (texto, sem áudio).

### 6.6 Reconciliação (`resumo_nuvem`, R8.5)

No `ola` do `pc`: a API envia os `nuvem_turnos` com `sincronizado IS NULL` em envelopes de ≤ 50
(ordem `ts`); o PC grava cada um em `magi/elo/reconciliar.py`:

```python
async def gravar_resumo(r: ResumoNuvem, turns: TurnRepo, memoria: MemoryIngest | None) -> tuple[str, ...]
```

que grava em `turns` (satélite `celular`, marcado `nuvem`) e passa pelo mesmo extrator de memória
dos turnos normais (nome exato no tasks), ignorando `uid` já gravado, e responde `Ack(ids=uids)`;
a API marca `sincronizado = now()` só nos ids do `ack`. Sem `ack` → reenvia no próximo `ola`.

**Aceite.**
- **CA-Y20** Matriz §6.1: com relógio falso, `visto` de 29 s → `pc`, de 31 s → `nuvem`; casa
  offline → 503/`casa_offline` no REST e frase em cache no modo nuvem.
- **CA-Y21** `BudgetNuvem`: nuvem 1,99 + pc 2,00 libera; nuvem 2,00 bloqueia; nuvem 1,00 + pc 4,00
  bloqueia; bloqueado, "liga a TV da sala" ainda gera `acao` (sem LLM) e "pesquisa X" gera a frase
  `sem_verba`. O modo nuvem com agente falso nunca recebe ferramenta fora de `NUVEM_PODE`.
- **CA-Y22** Reconciliação: 120 turnos → 3 envelopes (50/50/20); `ack` parcial marca só os ids
  confirmados; reenvio não duplica em `turns`; `on_turn_done` de satélite `celular` emite um
  `TurnoFim` e de `pc` não emite nada.

## 7. Backups

### 7.1 Do PC

`magi-backup = magi.elo.backup:main`, `deploy/systemd/magi-backup.{service,timer}`
(`OnCalendar=*-*-* 03:30`, `Persistent=true`, `OnStartupSec=10min` — R4.1: ≤ 15 min após o login).

```
docker exec magi-pg pg_dump -Fc -U magi -d magi > $TMP/magi-pg.dump        # só leitura
docker exec magi-pg psql -U magi -d magi -Atc "<contagens>"  → manifesto.json
tar -C ~/.config --exclude='*.token' --exclude='*key*' --exclude='*secret*' -cf - magi | …
tar -cf - magi-pg.dump manifesto.json config.tar | zstd -10 → $TMP/magi-AAAA-MM-DD.tar.zst
PUT /v1/backup/pc  (X-Sha256, X-Data, X-Manifesto)  → apaga $TMP no fim (sucesso ou falha)
```

Manifesto: `{"data","pg_versao","tabelas":{"turns":n,"memories":n,"costs":n,"news_items":n,
"taste":n,"learning_sessions":n}}`. Já recebido no dia (`409`) → sai 0. Falha → 3 tentativas
(1, 5, 15 min) e card no HUD "backup não subiu".

### 7.2 Na Ayanami

Ambiente do `restic` (worker-agendado): `RESTIC_REPOSITORY=b2:<B2_BUCKET>:magi`,
`RESTIC_PASSWORD`, `B2_ACCOUNT_ID`, `B2_ACCOUNT_KEY`, `RESTIC_CACHE_DIR=/dados/restic-cache`.
Inicialização uma vez: `docker compose run --rm migrar ayanami backup iniciar` (`restic init`).

| Job | Comando |
| --- | --- |
| `backup.restic` | `restic backup --host ayanami --tag pc --tag d<data> /dados/entrada/pc/<data>` → grava `snapshot` em `backups` |
| `backup.dump_ayanami` | `pg_dump -Fc -h ayanami-pg -U ayanami ayanami > /dados/entrada/ayanami/<data>/ayanami.dump` + manifesto |
| `backup.enviar` | `restic backup --host ayanami --tag ayanami /dados/entrada/ayanami/<data> /opt-config` (`compose.yml`, `ayanami.toml`; **nunca** `.env`) |
| `backup.reter` [DS7] | `restic forget --group-by host,tags --tag pc --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune` e o mesmo para `--tag ayanami` (D15a) |
| `backup.verificar` | `restic check --read-data-subset=5%` |
| `backup.restore_teste` | `restic restore latest --tag pc --target /dados/tmp/restore-<id>` → `docker run -d --rm --name ayanami-restore-teste --network none -e POSTGRES_PASSWORD=<aleatória> pgvector/pgvector:pg16` → `docker cp` + `pg_restore --no-owner -d postgres --create` → contagens iguais às do manifesto (tolerância 0) → `docker stop` + `rm -rf` do diretório → `restore_testes` + Telegram verde/vermelho |

O `worker-agendado` acessa o Docker do host só para o restore de teste por
`/var/run/docker.sock` montado **somente** nele, e o código só chama `run`/`cp`/`exec`/`stop`
com o nome fixo `ayanami-restore-teste` (lista branca testada).

### 7.3 Alertas e proibições

- `ayanami-vigia.timer` no host (1 min): Telegram se snapshot `pc` ou `ayanami` > 36 h, job de
  backup `falhou`, restore de teste vermelho, `/saude` falhando 3× seguidas, disco > 85%, worker
  sem batimento > 5 min (R4.4, R10.5). Mesmo alerta de backup vira `evento backup_falhou` (push).
  Anti-repetição: 1 mensagem por causa a cada 6 h.
- **Proibido** em qualquer código/script de backup: `docker compose down`, `docker volume rm`,
  `rm` em volume, `DROP`, `TRUNCATE`, `pg_restore` com `--clean` fora do contêiner descartável,
  qualquer comando contra o `magi-pg` além de `pg_dump`/`psql -c "SELECT count(*)…"`, e `restic
  forget` sem `--keep-*`.

**Aceite.**
- **CA-Y23** `magi-backup` com `docker`/HTTP falsos: monta o tar com dump, manifesto e config sem
  arquivos `*.token`/`*key*`; manda o sha256 certo; apaga o temporário mesmo com erro de rede.
- **CA-Y24** Os comandos gerados pelos jobs (capturados num executor falso) batem com a tabela
  §7.2; `forget` sempre com `--group-by host,tags` e os três `--keep-*`; restore só usa o nome
  `ayanami-restore-teste` e `--network none`; manifesto divergente → vermelho e Telegram falso
  chamado.
- **CA-Y25** Varredura estática de `ayanami/`, `magi/elo/backup.py` e `deploy/ayanami/` não acha
  `compose down`, `volume rm`, `DROP `, `TRUNCATE` nem `--clean` (lista de exceções vazia).

## 8. MCP (`mcp` 2.3.0)

```python
# ayanami/mcp_server.py
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

class VerificadorAyanami(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None   # tipo "mcp", não revogado; scopes = escopos

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

mcp = MCPServer("ayanami", token_verifier=VerificadorAyanami(db),
                auth=AuthSettings(issuer_url=URL_BASE, resource_server_url=f"{URL_BASE}/mcp/",
                                  required_scopes=["ler"],          # sem "ler" → 403 no HTTP
                                  validate_token_resource=False))   # S3: sem isto, aviso na 2.3
sub = mcp.streamable_http_app(                   # S3: o caminho vai aqui, não no construtor
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(  # S3: senão Host do tailnet → 421
        enable_dns_rebinding_protection=True,
        allowed_hosts=[HOST_TAILNET, "127.0.0.1", "127.0.0.1:*", "localhost:*"],
        allowed_origins=[f"https://{HOST_TAILNET}", "http://127.0.0.1:*", "http://localhost:*"]))
app.mount("/mcp", sub)       # S3: responde em /mcp/; /mcp → 307 (clientes usam a URL com barra)
# S3: o Mount não roda o lifespan do sub-app → o lifespan do FastAPI entra em
#     `async with mcp.session_manager.run(): ...` (senão "Task group is not initialized")
def exigir(escopo: str) -> AccessToken           # get_access_token(); falta → ToolError("escopo: …")
                                                 # (is_error no resultado) + auditoria ok=false
```

| Tool | Escopo | Parâmetros | Retorno |
| --- | --- | --- | --- |
| `noticias_buscar` | `ler` | `consulta: str` (1..200), `limite: int = 10` (≤ 30), `dias: int = 14` | lista `{uid,titulo,resumo,franquia,data,fontes:[url]}` (sem `spoiler` revelado) |
| `noticias_ultimas` | `ler` | `limite: int = 10` | idem, por `first_seen` |
| `tarefas_listar` | `ler` | `estado: str \| None`, `limite: int = 20` | `TarefaOut[]` sem `params` pessoais |
| `tarefa_ver` | `ler` | `id: str` | `TarefaOut` |
| `estado` | `ler` | — | `{pc_online, casa_online, tvs:[EstadoTv], fila:{…}, ultimo_backup}` |
| `tarefa_criar` | `tarefas` | `tipo`, `titulo`, `pedido`, `chave: str \| None` | `TarefaOut` (idempotente) |
| `tarefa_cancelar` | `tarefas` | `id: str` | `{"estado"}` |
| `tv_acao` | `casa` | `tv: str \| None`, `intent: str` (só `tv.*`), `slots: dict[str,str]` | `AcaoResultado`; `tv.power_off` → `{"confirmacao": ulid, "expira_em"}` e só executa se o Pedro aceitar em 120 s |
| `memoria_gravar` | `memoria-escrever` | `fato: str` (≤ 500) | sempre `confirma` no PC; PC offline → erro "pc_offline" |
| `memoria_buscar` | `ler` + `[mcp] memoria_ler = true` | `consulta: str` | só com D6/D13 (padrão: não registrada) |

Resources (somente leitura, escopo `ler`): `ayanami://noticias/{uid}` (texto do item),
`ayanami://tarefas/{id}` (`TarefaOut` JSON), `ayanami://estado`. Sem prompts.

- Tools de escopo desligado em `[mcp] escopos` **não são registradas** (não aparecem no
  `list_tools`), além de checadas por chamada. Padrão D13a: `["ler", "tarefas"]`.
- Toda chamada → `auditoria(tipo='mcp', alvo=<tool>, resumo=<parâmetros sem texto livre longo>,
  ok)` (R5.4). Confirmação expirada → `auditoria ok=false` e nenhum efeito (R5.3).
- Conexão do Claude Code: `claude mcp add --transport http ayanami
  https://ayanami.<tailnet>.ts.net/mcp --header "Authorization: Bearer $AYANAMI_MCP" -s user`;
  token criado com `ayanami dispositivo criar claude-code --tipo mcp`. Claude Desktop: só pela
  ponte local `npx mcp-remote <url> --header "Authorization: Bearer …"` (conector remoto não
  alcança o tailnet).

**Aceite.**
- **CA-Y26** Com `[mcp] escopos = ["ler","tarefas"]`, `list_tools` tem 7 tools (sem `tv_acao`,
  `memoria_*`); token com só `ler` chamando `tarefa_criar` recebe erro de escopo; token de tipo
  `pc` é recusado pelo verificador.
- **CA-Y27** `tv_acao` com `tv.power_off` cria `confirmacoes`, não manda `acao`; resposta `true`
  em 119 s manda a `acao` com `confirmed=True`; sem resposta em 120 s (relógio falso) expira sem
  `acao`; as três chamadas aparecem na `auditoria`.

## 9. Config da Ayanami e Compose

### 9.1 `/opt/ayanami/.env` (`0600`, fora do git; só segredos)

| Chave | Obrigatória | Uso |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | sim | `ayanami-pg` e DSN |
| `OPENAI_API_KEY` | sim (modo nuvem com LLM) | chave dedicada da Ayanami com limite no painel |
| `GEMINI_API_KEY` | sim | notícias (`free_tier`) |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUB` | sim | Web Push (`VAPID_SUB=mailto:…`) |
| `B2_ACCOUNT_ID`, `B2_ACCOUNT_KEY`, `B2_BUCKET` | sim (A3) | chave restrita ao bucket |
| `RESTIC_PASSWORD` | sim (A3) | também no cofre do Pedro e no keyring do PC |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | sim | alertas de operação |

Faltando obrigatória da fase ligada → a API sobe em modo degradado com `/saude` `ok=false` e o
item que falta (`"faltando":["B2_BUCKET"]`, só nomes).

### 9.2 `/opt/ayanami/ayanami.toml` (montado só-leitura em `/etc/ayanami/ayanami.toml`)

```toml
[geral]
url_base = "https://ayanami.exemplo.ts.net"   # obrigatório; https://
fuso = "America/Sao_Paulo"

[rede]
batimento_s = 10          # 5..30
offline_apos_s = 30       # ≥ 3 × batimento_s
longpoll_s = 25           # 10..55

[fila]
rapida_concorrencia = 8   # 1..16
agendada_concorrencia = 2 # 1..4
lenta_concorrencia = 1    # 1..2

[budget]
teto_nuvem_usd = 2.0      # 0..teto_geral_usd (0 = modo nuvem sem LLM, D11c)
teto_geral_usd = 5.0

[nuvem]
ligado = true
stt_modelo = "gpt-4o-mini-transcribe"   # mesmo do PC; trocar aqui se o PC trocar
tts_voz = "marin"
kokoro_reserva = true
contexto_turnos = 20      # 0..50

[noticias]
ligado = true
dim = 1536                # tem de ser igual ao NEWS_DIM do PC
# demais chaves = as de [news] do config.toml do PC (fontes, timeout_s, embedder)

[backup]
ligado = true
restore_teste = true
alerta_sem_snapshot_h = 36

[push]
max_hora = 10             # 1..60, por dispositivo (§15)
noticias_dia = 3          # 0..10
silencio_padrao = "23:00-07:30"

[mcp]
escopos = ["ler", "tarefas"]   # subconjunto de {"ler","tarefas","casa","memoria-escrever"}
memoria_ler = false

[voz]
modelo = "kokoro-v1.0.int8.onnx"
voz = "pf_dora"
descarregar_apos_s = 600

[embeddings]
ligado = false            # só com a A8
```

Leitura: `ayanami.config.ler(caminho) -> AyanamiConfig` (dataclasses `frozen`, `tomllib`); chave
desconhecida, tipo errado ou fora da faixa → `ConfigError` com o caminho da chave e a API **não
sobe** [DS8]. `stt_modelo` é o valor de hoje do PC; a tasks copia o nome real do `config.toml`.

### 9.3 Compose (`deploy/ayanami/compose.yml`, `name: ayanami`)

Imagem única `ghcr.io/<dono>/ayanami:<sha>` (ou `build: ../..` na A1), `restart:
unless-stopped`, `env_file: .env`, `TZ=America/Sao_Paulo`, rede `ayanami`, logs `json-file`
`max-size: 10m`, `max-file: 3`.

| Serviço | Comando | Portas | Limites | Healthcheck (`interval 30s, timeout 5s, retries 3`) | Depende |
| --- | --- | --- | --- | --- | --- |
| `ayanami-pg` | imagem `pgvector/pgvector:pg16`, `-c shared_buffers=512MB -c max_connections=40` | `127.0.0.1:54339:5432` | `cpus: 2`, `mem_limit: 2g` | `pg_isready -U ayanami` | — |
| `migrar` (`profiles: ["ops"]`) | `ayanami migrar && procrastinate --app=ayanami.fila.app schema --apply` | — | — | — | pg saudável |
| `ayanami-api` | `uvicorn ayanami.api:app --host 0.0.0.0 --port 8740 --workers 1` | `127.0.0.1:8740:8740` | `cpus: 1`, `mem_limit: 1g` | `curl -fsS localhost:8740/saude` | pg saudável |
| `worker-rapido` | `ayanami worker rapida` | — | `cpus: 1`, `mem_limit: 512m` | `ayanami batimento rapida --max 90` | pg |
| `worker-agendado` | `ayanami worker agendada` | — | `cpus: 1.5`, `mem_limit: 1g`; monta `docker.sock` | `ayanami batimento agendada --max 90` | pg |
| `worker-lento` | `ayanami worker lenta` | — | `cpus: 4`, `mem_limit: 6g`, `cpu_shares: 512` | `ayanami batimento lenta --max 90` | pg |
| `ayanami-voz` | `ayanami voz --port 8741` | só rede `ayanami` | `cpus: 2`, `mem_limit: 1536m` | `curl -fsS localhost:8741/saude` | — |

Volumes: `ayanami-pgdata` (pg), `ayanami-modelos` (voz, lento), bind `./dados:/dados` (entrada,
tmp, restic-cache), bind só-leitura `./ayanami.toml`, `./compose.yml` em `/opt-config`. Nenhuma
porta em `0.0.0.0` (Docker ignora o `ufw`). Soma dos limites ≈ 13 GB e lento + voz ≤ 6 vCPU
(RNF-A6). Deploy: `git pull && docker compose pull && docker compose --profile ops run --rm migrar
&& docker compose up -d && curl -fsS http://127.0.0.1:8740/saude`.

**Aceite.**
- **CA-Y28** `config.ler`: arquivo exemplo válido; chave desconhecida, `teto_nuvem_usd >
  teto_geral_usd`, `offline_apos_s < 3 × batimento_s`, `escopos` com valor fora da lista e
  `url_base` em `http://` dão `ConfigError` com o caminho da chave (5 casos).
- **CA-Y29** Teste estático do `compose.yml` (YAML carregado): todas as portas publicadas começam
  com `127.0.0.1:`; todo serviço não-`ops` tem `restart: unless-stopped`, `mem_limit`, `cpus` e
  `healthcheck` (salvo `migrar`); `docker.sock` só no `worker-agendado`; `.env` não é montado em
  nenhum volume.

## 10. `magi-casa`

### 10.1 Processo

| Item | Valor |
| --- | --- |
| Pacote / entrada | `magi/casa/` · `magi-casa` (subcomandos `servir` (padrão), `descobrir`, `nomear`, `parear`, `esquecer`, `estado`, `testar <tv> <acao>`) |
| Unit | `deploy/systemd/magi-casa.service` (user unit), `Restart=always`, `RestartSec=3`, `Nice=10`, `MemoryMax=120M`, `After=network-online.target`; sem `ExecStartPre` de rede (sobe mesmo sem internet) |
| Runtime | asyncio, um processo, um loop; sem thread fora do `to_thread` do WOL; sem GPU |
| Meta | ≤ 1% CPU e ≤ 80 MB RSS em repouso (R6.8), medida com 3 TVs configuradas por 10 min (CA-Y58) |
| Porta local | `127.0.0.1:10760` TCP [DS1]; no Pi (D10b) `[casa] escuta = "<IP tailnet>"`, nunca `0.0.0.0` |
| Arquivos | config `~/.config/magi/casa.toml`, catálogo `magi/casa/apps.yaml` (+ override `~/.config/magi/casa-apps.yaml`), token local `~/.config/magi/casa.token`, token da Ayanami `~/.config/magi/ayanami-casa.token` (ou keyring), pareamentos `~/.local/share/magi/casa/` (`0700`), estado `~/.local/state/magi/casa-estado.json` |

Os caminhos são lidos na hora da chamada (padrão `None`), como no overlay, para os testes trocarem
com `monkeypatch`.

### 10.2 API local para o `magi-core` (elo em JSON-lines)

TCP, uma mensagem do elo (§1) por linha UTF-8, `\n` no fim, ≤ 64 KiB por linha. O `magi-core`
(`TvActions`) mantém **uma** conexão aberta e reconecta sob demanda.

1. Cliente → `ola` (`tipo="pc"`, `token` = conteúdo de `casa.token`; a casa cria o arquivo com
   `secrets.token_urlsafe(32)`, `0600`, na 1ª subida). Token errado → `erro`
   (`codigo="nao_autorizado"`) e a casa fecha.
2. Casa → `ola` (`tipo="casa"`) com `tvs: [TvInfo]` (o roteador usa para o slot `tv`, §13) e
   `apps: [AppInfo]` (§1.2).
3. Cliente → `acao` (`Acao(pedido=AcaoPedido, origem="voz-pc")`); casa → `acao_ok` com `resp` =
   id da `acao` e `AcaoResultado` montado do `ResTv` (§10.5): `ok`, `motivo`,
   `dados={"tv","emulado","detalhe","estado"}`; `fala` vazia (quem fala usa a tabela da §13.2).
4. Cliente → `estado` com `tvs=()` = "me manda o estado"; casa → `estado` com as `EstadoTv`.
   A casa também empurra `estado` sem pedido quando algo muda (ligou, app, volume).
5. Sem `bate` no elo local (a conexão TCP basta); ocioso > 10 min → casa fecha, cliente reabre.

Timeout do lado do `magi-core`: 2,5 s por `acao` (10 s para `tv.power_on` e volume absoluto, que
esperam confirmar/emular);
estourou → `ActionResult(ok=False, speech="A TV não respondeu.")`. Conexão recusada → frase em
cache "A casa está fora do ar." (RNF-A9: nada disso passa pela Ayanami).

### 10.3 Conexão de saída à Ayanami

- `wss://<ayanami>/ws` (Bearer token `casa`, escopo `casa-executar`), só se `[casa] ayanami` estiver
  preenchido; ausente = casa só local (padrão até a A1 existir).
- `ola` com `tvs`/`apps` (como §10.2, sem `token`) → `bate` a cada 10 s → `estado` a cada mudança e
  a cada 60 s. Reconexão 1 → 2 → 4 … → 60 s com jitter ±20% (R1.7); recaída `/v1/longpoll` (§2.2) só se
  o WS falhar 3 vezes seguidas.
- `acao` vinda da Ayanami entra na **mesma fila por TV** da API local (§10.4) e volta `acao_ok`.
- A casa **nunca** executa `tv.power_off` com `confirmed=false`, venha de onde vier → `ok=false,
  motivo="precisa_confirmar"` (a confirmação é do PC, do PWA ou do `confirma` da §1).
- 401 → para de reconectar, loga `ayanami_token_revogado` e segue servindo a API local.

### 10.4 Execução, estado e logs

- **Fila por TV:** um `asyncio.Lock` por TV (comandos da mesma TV em série; TVs diferentes em
  paralelo); fila ≤ 8; cheia → `motivo="ocupada"`. Repetição de tecla do PWA (segurar vol+) chega
  como várias `acao` e é coalescida: ≤ 1 tecla por 80 ms.
- **Ligação viva:** Samsung e Android TV mantêm a conexão aberta enquanto a TV responde; Roku é
  HTTP sem estado. Driver caído reconecta 1 → 30 s, sem bloquear os outros.
- **Estado:** `EstadoTv` em memória, gravado em `casa-estado.json` (só o último, escrita atômica)
  para o `ola` após reinício. Sondagem: Samsung `GET :8001/api/v2/` a cada 30 s; Roku
  `/query/device-info` + `/query/active-app` a cada 30 s; Android TV por callbacks (push da TV).
  Sem resposta em 2 sondagens → `online=False`.
- **Revalidação de IP:** descoberta passiva (SSDP NOTIFY + mDNS) contínua e ativa a cada 10 min;
  TV achada com o mesmo `chave` (§12.1) em IP novo → atualiza `casa.toml` (escrita atômica) e loga.
- **Logs:** JSON em stdout (journald), uma linha por evento: `ts, nivel, evento, tv, driver, acao,
  ok, motivo, ms, origem (local|ayanami)`. Nunca token, cert, chave, código de pareamento nem texto
  digitado (só `len`). Nível padrão `INFO`; sondagem só em `DEBUG`.

### 10.5 Protocolo `TvDriver` (assinaturas finais)

```python
# magi/casa/driver.py — puro (sem I/O), importado pelos drivers e pelos testes
from magi.elo.mensagens import EstadoTv   # §1.2 [DS19]; o driver preenche id/nome/driver da sua TV
class Cap(StrEnum):
    POWER_ON = "power_on"; POWER_OFF = "power_off"; VOL_STEP = "vol_step"; VOL_SET = "vol_set"
    MUTE = "mute"; CHANNEL = "channel"; INPUT = "input"; APP = "app"; KEY = "key"
    TEXT = "text"; STATE = "state"

class Key(StrEnum):   # teclas canônicas; cada driver mapeia (§11.4)
    UP = "up"; DOWN = "down"; LEFT = "left"; RIGHT = "right"; OK = "ok"; BACK = "back"
    HOME = "home"; MENU = "menu"; PLAY_PAUSE = "play_pause"; REWIND = "rewind"; FORWARD = "forward"
    VOL_UP = "vol_up"; VOL_DOWN = "vol_down"; MUTE = "mute"; CH_UP = "ch_up"; CH_DOWN = "ch_down"
    POWER = "power"

class Motivo(StrEnum):
    NAO_SUPORTADO = "nao_suportado"; OFFLINE = "offline"; TEMPO_ESGOTADO = "tempo_esgotado"
    REDE_DESLIGADA = "rede_desligada"; STANDBY_PROFUNDO = "standby_profundo"; SEM_MAC = "sem_mac"
    NAO_PAREADO = "nao_pareado"; ACESSO_NEGADO = "acesso_negado"; APP_DESCONHECIDO = "app_desconhecido"
    ENTRADA_DESCONHECIDA = "entrada_desconhecida"; PRECISA_CONFIRMAR = "precisa_confirmar"
    OCUPADA = "ocupada"; TV_DESCONHECIDA = "tv_desconhecida"; TV_AMBIGUA = "tv_ambigua"
    NAO_AUTORIZADO = "nao_autorizado"; ERRO_DRIVER = "erro_driver"

@dataclass(frozen=True)
class Capacidades:
    caps: frozenset[Cap]
    entradas: tuple[str, ...] = ()        # canônicas: "hdmi1".."hdmi4", "tv", "av"
    apps: tuple[str, ...] = ()            # ids do apps.yaml que esta TV abre
    vol_max: int = 100                    # escala da TV (Android TV informa; demais 100)
    emula: frozenset[Cap] = frozenset()   # caps que o MagiCasa entrega por emulação (§10.7)
    def pode(self, cap: Cap) -> bool: ...  # cap in caps or cap in emula

@dataclass(frozen=True)
class ResTv:
    ok: bool
    motivo: Motivo | None = None
    detalhe: str = ""                     # p/ log e "causa provável"; sem segredo
    emulado: bool = False
    estado: EstadoTv | None = None

class TvDriver(Protocol):
    nome: str                             # "samsung" | "roku" | "androidtv" | "adb" | "falso"
    capacidades: Capacidades
    async def conectar(self) -> ResTv: ...
    async def fechar(self) -> None: ...
    async def power(self, on: bool) -> ResTv: ...
    async def volume(self, step: int | None = None, set_to: int | None = None) -> ResTv: ...
    async def mute(self, on: bool | None) -> ResTv: ...          # None = alterna
    async def channel(self, step: int) -> ResTv: ...
    async def input(self, nome: str) -> ResTv: ...                # canônica
    async def app(self, app_id: str) -> ResTv: ...                # id do apps.yaml
    async def key(self, key: Key) -> ResTv: ...
    async def text(self, s: str) -> ResTv: ...
    async def state(self) -> EstadoTv: ...
```

Regras do contrato:
- Driver **não** emula: método sem cap → `ResTv(False, NAO_SUPORTADO)`. A emulação mora em
  `magi/casa/emula.py` (`Executor`), acima do driver, igual para todos.
- Driver nunca levanta para o chamador: exceção de rede → `OFFLINE`/`TEMPO_ESGOTADO`; inesperada →
  `ERRO_DRIVER` + log `exception` (sem segredo).
- `ok=True` só depois da resposta do protocolo (HTTP 200, frame enviado sem erro e, em `power`,
  estado confirmado). Nunca "pronto" otimista (R6.2).
- `magi/casa/falso.py` `DriverFalso(capacidades, script)`: grava as chamadas, responde do
  `script` (por método: `ResTv` ou exceção), relógio injetado. Base de todos os CA desta parte.

### 10.6 `Executor` (de intent a driver)

`Executor.rodar(req: ActionRequest) -> ResTv`: 1) resolve a TV (§13.3) → `TV_DESCONHECIDA`/
`TV_AMBIGUA`; 2) checa `confirmed` em `tv.power_off`; 3) traduz o intent (§13.1) para método;
4) cap ausente → emulação (§10.7) ou `NAO_SUPORTADO`; 5) aplica o timeout (§11.5); 6) loga.

### 10.7 Emulação honesta (R6.2, R6.5)

| Pedido | Sem a cap | Como emula | Limite |
| --- | --- | --- | --- |
| `volume(set_to=N)` | `VOL_SET` | com `EstadoTv.volume` conhecido: `|N−atual|` × `VOL_UP/DOWN`, relê o estado e corrige ≤ 3 teclas | ≤ 60 teclas |
| idem, volume desconhecido (Samsung, Roku) | `VOL_SET` | `zerar_passos` (padrão 50, por TV no `casa.toml`) × `VOL_DOWN` e depois N × `VOL_UP` | [DS10] total ≤ 100 teclas a 80 ms (≤ 8 s); N > 50 → `NAO_SUPORTADO` com detalhe "acima do que dá para emular" |
| `volume(step=±k)` | — | k teclas (k preso em 1..30) | — |
| `mute(on=True/False)` | estado de mudo | só manda `MUTE` se `EstadoTv.mudo` for conhecido e diferente; desconhecido → alterna e devolve `emulado=True, detalhe="alternado"` (a fala diz "Mudo alternado.") | — |
| `input("hdmi2")` sem `INPUT` | — | **não emula** (menu de fonte varia por modelo) → `NAO_SUPORTADO` | — |
| `power(on)` com tecla que alterna | estado | Samsung/Android TV: `POWER` é alterna; só envia se o estado confirma o contrário do pedido; estado desconhecido → **não envia**, `NAO_SUPORTADO` com detalhe "estado desconhecido" | — |

Teclas extras abortam se outra `acao` da mesma TV chegar (a nova ganha).

**Ligar (R6.5):** dispara o método do driver (§11), sonda o estado a cada 500 ms por até 8 s;
`ligada=True` → `ok`. Falhou → `motivo`: `SEM_MAC` (Samsung/Roku-WOL sem MAC no `casa.toml`),
`REDE_DESLIGADA` (nenhuma resposta de rede antes nem depois), `STANDBY_PROFUNDO` (respondia
antes do WOL mas não ligou; ou Android TV recusou), `ACESSO_NEGADO` (Roku 403). A frase diz a
opção da TV a ligar (§13.2).

## 11. Drivers

### 11.1 Samsung Tizen — `samsungtvws[async]` 3.0.6 + `wakeonlan` 4.0.0

| Item | Valor |
| --- | --- |
| Ligação | `SamsungTVWSAsyncRemote(host, port=8002, token_file=…, name="Condessa")` → `wss://IP:8002/api/v2/channels/samsung.remote.control`. Recaída: `port=8001` (`ws://`) se 8002 recusar **e** `ano < 2018` no `casa.toml` (ou desconhecido) |
| Portas por ano | 2016–2017: 8001 (algumas também 8002); 2018+: 8002 (TLS) obrigatório; REST `http://IP:8001/api/v2/` em todos **[S2]** |
| Token | devolvido no 1º "Permitir"; guardado em `pareamentos/<id>.samsung.token` `0600` e no keyring `magi-keys` (`casa/<id>/samsung`); keyring ganha, arquivo é cópia de recaída |
| Estado | REST `device.PowerState` (`"on"`/`"standby"`, 2018+); sem o campo: REST respondeu = ligada; sem resposta = desligada ou fora |
| Ligar | `PowerState=="standby"` → `KEY_POWER` pela WS; sem resposta → WOL (`send_magic_packet(mac, ip_address=<broadcast da LAN>, port=9)` 3× com 100 ms) e, se em 3 s a REST responder em standby, `KEY_POWER`; confirma em ≤ 8 s **[S2]** |
| Desligar | só com `PowerState=="on"` (ou REST viva sem o campo): `KEY_POWER` |
| Apps | `run_app(app_id)` com o id do `apps.yaml`; `app_list()` não é usado (não responde em 2020+) |
| Entradas | `KEY_HDMI1`..`KEY_HDMI4` (2016+ aceita; modelos sem → só `KEY_SOURCE`, que não emulamos) **[S2]** |
| Texto | `send_text` da lib (só com teclado na tela aberto) |
| Limites | sem volume absoluto (UPnP 9197 fica fora da A2); "Permitir" a cada conexão se *Notificação de acesso* ≠ "Só na primeira vez" → `ACESSO_NEGADO` com essa causa na doc |

### 11.2 Roku — `rokuecp` 0.19.5

| Item | Valor |
| --- | --- |
| Ligação | `rokuecp.Roku(host, session=<aiohttp compartilhada>)`, HTTP `:8060`, sem pareamento |
| Estado | `GET /query/device-info`: `power-mode` (`PowerOn` = ligada; `DisplayOff`/`Ready`/`Headless` = desligada), `is-tv`, `supports-tv-power-control`, `supports-audio-volume-control` (OS 15); `/query/active-app` → `app` |
| Caps | player (`is-tv=false`): `KEY APP TEXT STATE` (+`POWER_*` só se `supports-tv-power-control`); Roku TV: + `POWER_ON POWER_OFF VOL_STEP MUTE CHANNEL INPUT` |
| Ligar | `POST /keypress/PowerOn`; exige *Configurações > Sistema > Energia > Início rápido da TV* (Fast TV start); sem resposta e com MAC → WOL e repete `PowerOn` **[S2]** |
| Teclas | `VolumeUp/VolumeDown/VolumeMute`, `ChannelUp/Down`, `InputHDMI1..4`, `InputTuner`, `InputAV1`, `Home/Back/Select/Up/…/Play/Rev/Fwd`, `PowerOff` |
| Apps | `POST /launch/<id>`; id do `apps.yaml` ou, ausente, procura por nome em `/query/apps` (cache 24 h) |
| Texto | `Lit_<char>` por caractere (URL-encoded), 30 ms entre, ≤ 100 caracteres |
| "Network access" | 403 em `keypress`/`launch` → `ACESSO_NEGADO`, detalhe "Controle por apps móveis > Acesso à rede = Ativado" (OS 14.1.4+ vem "Limitado") |

### 11.3 Android/Google TV — `androidtvremote2` 0.3.2 (+ ADB opcional)

| Item | Valor |
| --- | --- |
| Ligação | `AndroidTVRemote(client_name="Condessa", certfile, keyfile, host)`; TLS `:6466` controle, `:6467` pareamento; `async_connect()` e `keep_reconnecting()` em tarefa própria |
| Pareamento | §12.3; cert/key em `pareamentos/<id>.atv.crt|.key` `0600` (não cabem bem no keyring) |
| Estado | callbacks `is_on`, `current_app` (pacote → id do `apps.yaml` por `pacote:` do catálogo), `volume_info` (`level`, `max`, `muted`) → `EstadoTv.volume` em escala 0–100 (`round(level*100/max)`) |
| Ligar / desligar | `send_key_command("POWER")` só quando `is_on` contradiz o pedido (é alterna) |
| Volume | `VOLUME_UP/DOWN/MUTE`; `VOL_SET` **emulado** com estado (§10.7, caminho de 60 teclas) |
| Apps | `send_launch_app_command(<deep link do apps.yaml>)`; id de pacote não é usado |
| Entradas | `KEYCODE_TV_INPUT_HDMI_1..4` (keycodes 243–246) — funcionam em parte dos modelos **[S2]**; sem efeito não é detectável → `ok` só se `current_app` mudar para o app de entrada; senão `NAO_SUPORTADO` |
| Canal / texto | `CHANNEL_UP/DOWN`; `send_text(s)` (só com IME aberto) |
| Limites | não comanda dentro da Netflix; desconexões a cada ~15 s em alguns modelos (reconexão automática; comando durante reconexão espera ≤ 1,5 s); standby profundo não acorda → `STANDBY_PROFUNDO` |
| Recaída ADB | `adb` (`androidtv` 0.0.75 / `adb-shell` 0.4.4, `:5555`), só se `adb = true` no `casa.toml` **e** o Pedro ligar a depuração por rede; usada para `power_on` (`input keyevent 26`) e `input` (`am start` do app de entrada). Desligada por padrão; chave RSA em `pareamentos/adb.key` `0600` |

### 11.4 Comando × driver

S = suportado · E = emulado pelo `Executor` · N = não (devolve `NAO_SUPORTADO`) · `*` = só Roku TV.

| Comando | Samsung | Roku | Android TV |
| --- | --- | --- | --- |
| ligar | S (WOL/`KEY_POWER`) | S* (`PowerOn`, Fast TV start) | S (`POWER`; falha em standby profundo) |
| desligar (`danger`) | S (com estado) | S* | S |
| volume ± | S | S* | S |
| volume = N | E (zerar e subir, ≤ 50) | E* (idem) | E (com `volume_info`) |
| mudo / tirar mudo | S alterna; E explícito | S* alterna; E explícito | S (estado conhecido) |
| canal ± | S | S* | S |
| entrada HDMI n | S [S2] | S* | S/N conforme modelo [S2] |
| abrir app | S (catálogo) | S | S (deep link) |
| tecla (d-pad, voltar, home, play) | S | S | S |
| digitar texto | S (teclado aberto) | S (`Lit_`) | S (IME aberto) |
| ler estado | S (ligada; sem volume) | S (ligada, app; sem volume) | S (ligada, app, volume, mudo) |

### 11.5 Timeouts (por chamada, no `Executor`)

| Etapa | Samsung | Roku | Android TV |
| --- | --- | --- | --- |
| conectar | 3 s | — (HTTP) | 4 s |
| comando simples (tecla, app, entrada) | 2 s | 1,5 s (HTTP) | 2 s |
| ligar até confirmar | 8 s | 8 s | 8 s |
| sondagem de estado | 1,5 s | 1,5 s | — (push) |
| emulação de volume | 80 ms/tecla, ≤ 8 s | idem | idem, ≤ 4,8 s |

Estourou → `TEMPO_ESGOTADO`; a conexão do driver é descartada e reaberta na próxima chamada.

## 12. Descoberta, identificação e pareamento

### 12.1 Descoberta (R6.4)

`magi-casa descobrir [--segundos 5]` e a revalidação de 10 min usam o mesmo `Descobridor`, na rede
do host (multicast não atravessa Tailscale nem bridge do Docker):

| Fonte | Busca | Confirmação | Chave estável |
| --- | --- | --- | --- |
| SSDP (`async-upnp-client` 0.49.0) | `ST: roku:ecp` | `GET :8060/query/device-info` | `roku:<serial-number>` |
| SSDP | `urn:samsung.com:device:RemoteControlReceiver:1`, `urn:schemas-upnp-org:device:MediaRenderer:1` | `GET :8001/api/v2/` com `device.type == "Samsung SmartTV"` | `samsung:<device.id>` (ou `wifiMac`) |
| mDNS (`zeroconf` 0.151.5) | `_androidtvremote2._tcp.local.` | TCP `:6466` abre | `androidtv:<MAC>`; MAC lido de `/proc/net/arp` após o contato (nome mDNS se faltar) |

Saída: tabela `chave, driver, IP, modelo, nome anunciado, já nomeada?`. MAC de qualquer driver vem
da resposta (Samsung `wifiMac`, Roku `wifi-mac`/`ethernet-mac`) ou de `/proc/net/arp`.

### 12.2 TCL: Roku ou Google TV (D9)

Mesma IP: `:8060/query/device-info` responde → candidato `roku`; anuncia `_androidtvremote2._tcp`
ou abre `:6466` → candidato `androidtv`; os dois → `androidtv` e log `tcl_dois_protocolos`
(design §5.3). O modelo não decide. `nomear` aceita `--driver` para forçar.

### 12.3 Pareamento (por driver)

`magi-casa parear "TV da sala"` (pela CLI; o HUD só mostra o card "aceite na TV"/"digite o código"):

| Driver | Fluxo | Espera | Guarda |
| --- | --- | --- | --- |
| Samsung | abre a WS com `token_file` vazio → TV mostra "Permitir" → token chega no 1º frame | 60 s; recusou/expirou → `ACESSO_NEGADO` | keyring + `<id>.samsung.token` `0600` |
| Roku | sem pareamento; só `GET /query/device-info` (nenhuma tecla, para não mexer na TV); o aviso de "Acesso à rede" sai no 1º comando que der 403 | — | — |
| Android TV | `async_generate_cert_if_missing` → `async_start_pairing` → TV mostra 6 hex → CLI pede o código (`input`, eco desligado) → `async_finish_pairing(code)` → `async_connect` | 120 s; 3 códigos errados → aborta | `<id>.atv.crt/.key` `0600` |

`magi-casa esquecer <tv>` apaga token/cert (arquivo e keyring) e a entrada do `casa.toml`.
Diretório `~/.local/share/magi/casa/` criado `0700`; arquivos com `os.open(…, 0o600)`; a casa
recusa subir se achar arquivo de pareamento com permissão mais aberta (log `permissao_aberta`).
Nada disso entra em git (o repo já ignora `~`) nem em log.

### 12.4 `casa.toml`

```toml
[casa]
escuta = "127.0.0.1"             # Pi (D10b): IP do tailnet
porta = 10760
ayanami = ""                     # "https://ayanami.<tailnet>.ts.net"; vazio = só local
padrao = "sala"                  # id da TV padrão (slot `tv` vazio)
broadcast = "192.168.0.255"      # WOL
descoberta_min = 10

[[tv]]
id = "sala"                      # [a-z0-9_-], estável
nome = "TV da sala"
apelidos = ["sala", "televisão da sala", "tv grande"]
driver = "samsung"               # samsung | roku | androidtv
chave = "samsung:uuid:…"         # §12.1
ip = "192.168.0.40"
mac = "a4:30:7a:…"               # obrigatório p/ ligar Samsung
ano = 2021                       # opcional (porta 8002/8001)
zerar_passos = 50                # §10.7
entradas = { console = "hdmi2", pc = "hdmi1" }   # apelidos de entrada
adb = false                      # Android TV: recaída ADB

[[tv]]
id = "quarto"
nome = "TV do quarto"
apelidos = ["quarto", "tcl"]
driver = "androidtv"
chave = "androidtv:9c:…"
ip = "192.168.0.52"
mac = "9c:…"
```

Validação: `id`/`nome`/apelidos únicos sem acento-sensível (comparação normalizada como no
roteador); `padrao` aponta para TV existente; driver desconhecido → TV ignorada com log, o resto
sobe. Arquivo ausente → casa sobe sem TVs (o `ola` lista vazio).

### 12.5 `apps.yaml`

```yaml
# id canônico → por driver. Samsung: app_id Tizen. Roku: channel id (ausente = busca por nome
# em /query/apps). androidtv: deep link + pacote (só para reconhecer o app atual).
apps:
  - id: netflix
    nome: "Netflix"
    apelidos: ["netflix", "netiflix"]
    samsung: "3201907018807"
    roku: "12"
    androidtv: {link: "https://www.netflix.com/title", pacote: "com.netflix.ninja"}
  - id: youtube
    nome: "YouTube"
    apelidos: ["youtube", "iutubi"]
    samsung: "111299001912"
    roku: "837"
    androidtv: {link: "https://www.youtube.com", pacote: "com.google.android.youtube.tv"}
  - id: prime
    nome: "Prime Video"
    apelidos: ["prime", "prime video", "amazon"]
    samsung: "3201910019365"     # [S2]
    roku: "13"
    androidtv: {link: "https://app.primevideo.com", pacote: "com.amazon.amazonvideo.livingroom"}
  # disney, max, globoplay, spotify, twitch, crunchyroll: ids [S2]; faltou → APP_DESCONHECIDO
```

Ids marcados `[S2]` só valem depois de abrir o app de verdade uma vez. O override do usuário
(`~/.config/magi/casa-apps.yaml`) tem o mesmo formato e ganha por `id`.

## 13. Intents `tv.*` e ferramentas do agente

### 13.1 Ids, slots e frases

`IntentId` novos: `TV_POWER_ON="tv.power_on"`, `TV_POWER_OFF="tv.power_off"`, `TV_VOLUME=
"tv.volume"`, `TV_MUTE="tv.mute"`, `TV_UNMUTE="tv.unmute"` **[DS11]**, `TV_APP="tv.app"`, `TV_INPUT="tv.input"`. `SlotName` novos:
`TV="tv"` (value = id da TV, display = nome), `APP="app"` (value = id do `apps.yaml`), `INPUT=
"input"` (value = `hdmi1`.. ou apelido resolvido). O volume reusa `SlotName.VOLUME`: `"+k"`/`"-k"`
= k teclas (padrão 3; "muito" = 8), `"N"` = absoluto.

`{tv}`, `{app}` e `{input}` são slots de **catálogo** (como `{game}`): o roteador casa por
rapidfuzz contra nomes+apelidos que vieram no `ola` da casa (§10.2), score ≥ 80; abaixo disso a
frase não casa. **Regra de colisão [DS12]:** toda frase `tv.*` tem "tv"/"televisão",
um `{tv}` ou "hdmi"; "aumenta o volume" sem isso continua `volume.set` do PC, "abre o YouTube"
sem "na tv" continua o que é hoje.

```yaml
  # -- TV (R6.6; magi-casa) ---------------------------------------------------
  - id: tv.power_off
    label: "desligar a {tv}"
    reply: "Desligar a TV? Confirma?"
    danger: true
    phrases: ["desliga a tv", "desliga a televisão", "desliga a {tv}"]

  - id: tv.volume
    label: "volume da TV em {volume}"
    reply: "Volume da TV ajustado."
    phrases:
      - "volume da tv em {volume}"
      - "coloca o volume da {tv} em {volume}"
      - say: "aumenta o volume da tv"
        slots: {volume: "+3"}
        label: "aumentar o volume da TV"
      - "abaixa {volume:-} o volume da tv"
```

| Id | `reply` | Frases (além das variantes com `{tv}` e "televisão") |
| --- | --- | --- |
| `tv.power_on` | "Ligando a TV." | "liga a tv", "liga a {tv}" |
| `tv.volume` (resto) | — | "abaixa o volume da tv" (`-3`), "aumenta muito o volume da tv" (`+8`), "aumenta {volume:+} o volume da tv" |
| `tv.mute` | "TV no mudo." | "muta a tv", "tv no mudo", "silencia a {tv}" |
| `tv.unmute` | "Som da TV de volta." | "tira a tv do mudo", "desmuta a tv", "volta o som da {tv}" |
| `tv.app` (`required: [app]`) | "Abrindo na TV." | "abre {app} na tv", "coloca {app} na tv", "abre {app} na {tv}" |
| `tv.input` (`required: [input]`) | "Entrada trocada." | "muda a tv para {input}", "coloca a {tv} no {input}", "tv no {input}", "entrada {input}" (`{input}` só casa hdmi 1..4 e apelidos do `casa.toml`) |

Combinação "abre a Netflix na TV da sala e baixa o volume" vai pelo agente (multi-intent), não
pelo roteador.

### 13.2 Respostas (vão ao `phrases.yaml`)

`fixed`: "Pronto, TV ligada.", "TV desligada.", "Não consegui ligar a TV.", "A TV não respondeu.",
"A casa está fora do ar.", "Essa TV não faz isso.", "Não conheço esse app nessa TV.", "Qual TV?",
"Mudo alternado.", "A TV recusou o comando.", "Essa TV ainda não foi pareada.".
`templates` ({nome} = nome da TV, app ou entrada): "Desligar a {nome}? Confirma?", "Abrindo {nome}
na TV.", "Não consegui ligar a {nome}; ela precisa do Ligar com celular ativo.", "Não consegui
ligar a {nome}; ative o Início rápido da TV.", "Não consegui ligar a {nome}; ela está em espera
profunda.", "A {nome} está bloqueando o controle; ative o Acesso à rede.", "A {nome} está
desligada.", "Mais de uma TV: {nome}?" (nomes juntados com "ou").

Mapeamento `motivo` → frase em `magi/core/actions/tv.py` (`SAY_TV_*`); cada constante está no
`phrases.yaml` (o teste existente confere). Volume relativo responde só "Ok." (frase curta;
fala longa a cada tecla irrita).

### 13.3 Escolha da TV

Ordem **[DS13]**: 1) slot `tv` casado; 2) `padrao` do `casa.toml`; 3) só uma TV
configurada; 4) para comando ≠ ligar, só uma TV `ligada=True` agora; 5) senão `TV_AMBIGUA` →
"Mais de uma TV: sala ou quarto?" e a próxima fala curta ("a da sala") entra como resposta pelo
mecanismo de pergunta pendente do turno (mesmo de "você quis dizer X?"). Nome que não existe →
`TV_DESCONHECIDA` → "Qual TV?".

### 13.4 `TvActions` e `ActionTool`s

`magi/core/actions/tv.py` `TvActions(host="127.0.0.1", port=10760, token_file=None)`, `intents =
frozenset({TV_POWER_ON, TV_POWER_OFF, TV_VOLUME, TV_MUTE, TV_UNMUTE, TV_APP, TV_INPUT})`, no molde
do `RgbActions` (cliente de host de rede, injeta o cliente nos testes). `run(req)` serializa o
`ActionRequest` em `acao` (§10.2), espera `acao_ok`, traduz o `AcaoResultado` (`motivo` → frase,
§13.2) em `ActionResult(ok, speech, expression)`. Com `[casa] endereco` (Pi) aponta para o IP do tailnet.

Ferramentas do agente (`ActionTool`, `serial=True`), args JSON Schema:

| Tool | Args | Intent | `danger` |
| --- | --- | --- | --- |
| `tv_ligar` | `tv?: str` | `tv.power_on` | não |
| `tv_desligar` | `tv?: str` | `tv.power_off` | **sim** (`confirm_speech` = "Desligar a {nome}? Confirma?") |
| `tv_volume` | `valor: str` (`"+3"`, `"-5"`, `"20"`), `tv?` | `tv.volume` | não |
| `tv_mudo` | `ligado: bool`, `tv?` | `tv.mute` / `tv.unmute` | não |
| `tv_app` | `app: str` (nome livre; mapper casa com o catálogo, falhou → `ToolArgsError("Não conheço esse app.")`), `tv?` | `tv.app` | não |
| `tv_entrada` | `entrada: str`, `tv?` | `tv.input` | não |
| `tv_estado` | `tv?` | — (leitura; `serial=False`, não é `ActionTool`) **[DS14]** | não |

Descrição das tools lista os nomes das TVs e a padrão (montada do `ola`). No modo nuvem (§6.5) as
mesmas tools existem, mas o `TvActions` da nuvem manda `acao` pela WS da casa.

## 14. PWA (`ayanami/pwa/`, servido em `/app`)

### 14.1 Tecnologia **[DS15]**

**HTML + JavaScript puro em módulos ES, sem build** (`<script type="module">`, `<template>`,
CSS próprio). Motivos: cinco telas simples e um estado pequeno; nenhum passo de build na imagem
Python (o Dockerfile não ganha Node); o service worker cacheia uma lista de arquivos fixa e
versionada; nenhum CDN (o PWA tem de abrir do cache sem rede e não puxa código de terceiros num app
que controla a casa). htmx descartado (a API é JSON, não HTML parcial); preact+htm descartado
(sem build traria CDN ou vendorização para ganho pequeno). Meta: ≤ 80 KB gzip sem sprites.

Arquivos: `index.html`, `app.js` (roteador por hash `#/conversa|tv/<id>|feed|tarefas[/<id>]|confirma/<ulid>|ajustes|parear`),
`api.js` (fetch com Bearer, SSE, reconexão), `estado.js` (store mínima com `subscribe`),
`telas/{conversa,tv,feed,tarefas,ajustes,parear}.js`, `gravador.js`, `sw.js`,
`manifest.webmanifest`, `icones/{192,512,maskable-512}.png`, `rosto/{dormindo,ouvindo,pensando,
falando}.webp` (D5a, ≤ 40 KB cada). Testes de JS: `node --test` sobre `estado.js`, `gravador.js`
e `api.js` com `fetch`/`MediaRecorder` falsos (sem navegador).

### 14.2 Telas

| Tela | Conteúdo | Ações |
| --- | --- | --- |
| Parear | campo de 6 dígitos (código do HUD/QR); QR abre `/app/#/parear?c=123456` | `POST /v1/pareamento/trocar` `{"codigo","nome"}` (§2.2) → token no IndexedDB |
| Conversa | histórico do dia (texto), rosto por estado, selo **PC**/**nuvem**, botão grande **segurar para falar**, campo de texto | turno texto ou áudio |
| TV | abas por TV (`TvInfo` de `GET /v1/casa/estado`; `EstadoTv` vivo pelo SSE `estado`); botões **só** das `caps`: ligar/desligar, vol ±, mudo, canal ±, HDMI 1–4 das `entradas`, apps do catálogo da TV, d-pad + OK/voltar/home/play, digitar texto | `POST /v1/casa/acao` direto (não passa pelo PC) |
| Feed | cards da Ayanami (notícias, tarefas prontas), rolagem infinita (`GET /v1/feed?n=20&antes=…`) | abrir link |
| Tarefas | lista por estado (R2.3), barra de progresso, idade | ver (`GET /v1/tarefas/{id}`), cancelar (`DELETE`) |
| Ajustes | dispositivo, push liga/desliga, `push_com_pc`, horário de silêncio (§15), TV padrão do celular, versão, **sair** (revoga o token) | `PUT /v1/dispositivo/preferencias`; sair = `DELETE /v1/dispositivo` |

"Desligar" no controle pede segundo toque em ≤ 3 s ("toque de novo para desligar") e só então
manda `confirmed=true` **[DS16]**. Botão segurado (vol±) repete a cada 200 ms enquanto
pressionado (a casa coalesce, §10.4). Botão de cap ausente não aparece; TV `online=false` mostra
os botões cinza com "TV fora da rede".

### 14.3 Estados globais

`sem_token` → Parear · `conectando` · `ok_pc` · `ok_nuvem` · `sem_ayanami` (fora do tailnet ou
Ayanami fora) · `casa_fora` (aba TV mostra "a casa está fora do ar"). Detecção: `GET /saude` com
timeout 4 s na abertura, a cada volta ao primeiro plano (`visibilitychange`) e a cada 30 s com a
tela aberta; 401 → apaga token e vai a Parear.

### 14.4 Gravação (PTT)

`getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}})` no
primeiro toque (gesto); `MediaRecorder(stream, {mimeType: "audio/webm;codecs=opus",
audioBitsPerSecond: 24000})` após `isTypeSupported`; sem suporte → botão some e fica só texto
("seu navegador não grava opus"). Máquina: `ocioso → gravando` (pointerdown) `→ enviando`
(pointerup, ou 15 s automáticos, como o `MAX_LENGTH` do satélite) `→ pensando → falando →
ocioso`; erro em qualquer passo → `ocioso` + toast. Gravação < 400 ms é descartada ("segurou
pouco"). Arrastar para fora do botão cancela. Blob ≤ 15 s ≈ 50 KB, enviado inteiro em `POST
/v1/turno` (multipart `audio`); o microfone é solto (`track.stop()`) ao parar, nunca fica aberto.

### 14.5 Resposta

`POST /v1/turno` devolve o id do turno; o texto chega pelo SSE `GET /v1/eventos` (`turno.texto`/
`turno.fim`, §2.2) e é desenhado assim que chega; o áudio `audio/ogg;codecs=opus` toca num
`<audio>` criado no gesto do PTT (destrava o autoplay no Chrome Android). Turno de texto não toca
áudio salvo se "voz nas respostas de texto" estiver ligada nos Ajustes (padrão desligado). SSE cai
→ reconecta 1 → 30 s com `Last-Event-ID`; sem `turno.fim` em 50 s (prazo do PC é 45 s, §6.2) →
"Ela não respondeu; tenta de novo?".

### 14.6 Instalação, manifest e service worker

```json
{"name": "Condessa", "short_name": "Condessa", "start_url": "/app/#/conversa", "scope": "/app/",
 "display": "standalone", "orientation": "portrait", "background_color": "#0b0b12",
 "theme_color": "#0b0b12", "lang": "pt-BR",
 "icons": [{"src": "icones/192.png", "sizes": "192x192", "type": "image/png"},
           {"src": "icones/512.png", "sizes": "512x512", "type": "image/png"},
           {"src": "icones/maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}
```

Instalação: Chrome Android → "Instalar app" (WebAPK); o app mostra o próprio botão quando recebe
`beforeinstallprompt`. `sw.js`: cache `condessa-shell-v<N>` com a lista fixa (cache-first;
`N` muda a cada deploy e o `activate` apaga os antigos); `/v1/feed` network-first com cópia em
`condessa-feed` (último feed, 1 entrada); todo o resto de `/v1/*` network-only, **nunca** cacheado
(token, casa, tarefas). Sem rede/tailnet (R7.4): shell do cache, faixa "sem conexão com a Ayanami
— ligue o Tailscale", feed do cache com a hora dele, botões de TV e PTT desabilitados. Handlers
`push` e `notificationclick` na §15.

## 15. Web Push

- **Chaves:** VAPID P-256 geradas uma vez por `ayanami push chaves` (`py-vapid`, dependência do
  `pywebpush` 2.5.0) → `.env` `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUB=mailto:<e-mail
  do Pedro>` (§9.1). Trocar as chaves invalida todas as assinaturas (o PWA reassina ao abrir).
- **Assinatura:** Ajustes → `Notification.requestPermission()` (só após toque) →
  `pushManager.subscribe({userVisibleOnly: true, applicationServerKey})` → `POST /v1/push/assinar`
  (tabela `push_assinaturas`, uma por dispositivo `celular`; revogar o dispositivo apaga).
- **Envio:** job `push.enviar` na fila `rapida`; `webpush(subscription_info, data, vapid_private_key,
  vapid_claims={"sub": …}, ttl=…, headers={"Urgency": …, "Topic": tag})` em `asyncio.to_thread`;
  timeout 10 s. 404/410 → apaga a assinatura; 413 → corta `resumo` e reenvia uma vez; 429/5xx →
  3 repetições (5 s, 30 s, 2 min, respeitando `Retry-After`); auditoria registra tipo e status,
  sem texto.

| Quando (R9.1) | `tipo` | Urgency | TTL | Passa no silêncio? |
| --- | --- | --- | --- | --- |
| pedido de confirmação (R5.3) | `confirma` | high | 120 s | sim |
| lembrete marcado pelo Pedro | `lembrete` | high | 1 h | sim |
| tarefa pronta / falhou (se pedia aviso) | `tarefa` | normal | 24 h | não (acumula) |
| monitor bateu | `monitor` | normal | 12 h | não |
| notícia "bomba" (≤ 3/dia) | `noticia` | low | 6 h | não (descarta) |
| backup com falha / sem snapshot 36 h (R4.4) | `operacao` | normal | 24 h | não (Telegram já avisa) |

`tipo` do push a partir do `EventoTipo` (§1.2): `confirmacao`→`confirma`, `lembrete`→`lembrete`,
`tarefa_pronta`/`tarefa_falhou`→`tarefa`, `monitor`→`monitor`, `noticia_bomba`→`noticia`,
`backup_falhou`→`operacao`; `dispositivo` não gera push.

**Payload** (JSON cifrado pelo `pywebpush`, ≤ 3 KB; limite do serviço é 4 KB):
`{"v":1,"tipo":"tarefa","id":"<evento>","titulo":"Pesquisa pronta","resumo":"Monitores OLED 27″",
"url":"/app/#/tarefas/<id>","tag":"tarefa-<id>","ts":"…Z"}`. `titulo` ≤ 40 e `resumo` ≤ 120
caracteres (cortados do `Evento`); `confirma` usa `url` `/app/#/confirma/<ulid>`; sem dado sensível (R9.3: nada de valores, nomes de pessoas, trechos de memória); o
detalhe só abre no PWA autenticado. `tag` igual substitui a notificação anterior (progresso da
mesma tarefa não empilha).

**SW:** `push` → `showNotification(titulo, {body: resumo, tag, data: {url}, icon, badge})`;
`notificationclick` → foca a janela do PWA ou abre `url`. `confirma` **não** tem botão
"Confirmar" na notificação **[DS17]**: abre o card de confirmação no PWA (evita
desligar TV/gravar memória por toque acidental na tela bloqueada); expirou → card "expirou".

**Silêncio à noite [DS18]:** padrão `[push] silencio_padrao` = `23:00–07:30` America/Sao_Paulo,
trocável pela preferência `silencio`. No
silêncio só `confirma` e `lembrete`; `tarefa`/`monitor`/`operacao` acumulam e saem às 07:30 como
**um** push "3 avisos" (tag `resumo-manha`); `noticia` é descartada. **Limite:** ≤ `[push] max_hora` (10) pushes
por hora por dispositivo; o 11º em diante vira o mesmo agrupado ao fim da hora. **Com o PC online**
(R9.2): o evento vai também à fila de proatividade do PC; com a preferência `push_com_pc = false` o push é
pulado enquanto o `pc` estiver online, exceto `confirma`.

## 16. Configuração e critérios de aceite

### 16.1 Config do PC (`~/.config/magi/config.toml`, seção nova)

```toml
[casa]
ligado = true
endereco = "127.0.0.1:10760"    # Pi (D10b): "<IP tailnet>:10760"
timeout_s = 2.5
timeout_longo_s = 10            # tv.power_on e volume absoluto
```

Celular (Ajustes, guardados no IndexedDB e espelhados em `PUT /v1/dispositivo/preferencias` → `dispositivos.preferencias`,
para o push respeitar): `push` (bool, padrão true), `push_com_pc` (true), `silencio` (`"23:00-07:30"`),
`tv_padrao` (id ou vazio = a da casa), `voz_em_texto` (false). Ayanami: `VAPID_*` no `.env` (§9.1), `[push]` no
`ayanami.toml` (§9.2, [DS8]).

### 16.2 Critérios de aceite (CA-Y30 a CA-Y59)

Todos com `DriverFalso`, servidores HTTP/WS falsos em `127.0.0.1:0` (`aiohttp.test_utils`),
relógio injetado e `tmp_path` — sem TV real, sem multicast real, sem rede externa.

- **CA-Y30** `Capacidades.pode` e `ResTv`: cap ausente sem emulação → `NAO_SUPORTADO`; o
  `Executor` nunca devolve `ok=True` quando o driver devolveu `ok=False` (tabela de 11 métodos).
- **CA-Y31** Emulação de volume com estado (`volume=30`, `set_to=20`) → 10× `VOL_DOWN` a 80 ms
  (relógio falso), relê e corrige; delta > 60 → `NAO_SUPORTADO`.
- **CA-Y32** Emulação sem estado: `set_to=20` → 50 `DOWN` + 20 `UP`, `emulado=True`; `set_to=60`
  → `NAO_SUPORTADO` sem enviar tecla nenhuma; nova `acao` na mesma TV aborta a sequência.
- **CA-Y33** Mudo explícito com estado igual → nenhuma tecla; estado desconhecido → 1 tecla e
  `detalhe="alternado"` → fala "Mudo alternado.".
- **CA-Y34** Ligar: estado vira `ligada` no 3º poll → `ok` em < 8 s (relógio falso); nunca vira →
  `STANDBY_PROFUNDO`; TV sem MAC e sem rede → `SEM_MAC`; resposta antes de confirmar nunca é "pronto".
- **CA-Y35** `tv.power_off` com `confirmed=false` vindo da API local **e** da WS da Ayanami →
  `PRECISA_CONFIRMAR`, driver não chamado.
- **CA-Y36** Fila por TV: 2 comandos na mesma TV em série, em TVs diferentes em paralelo; 9º na
  fila cheia → `OCUPADA`; repetição de tecla coalescida a ≤ 1/80 ms.
- **CA-Y37** API local: `ola` com token errado → `erro` `nao_autorizado` e conexão fechada; certo →
  `ola` da casa com TVs, caps e apps; `acao` → `acao_ok` com `resp` igual ao `id`.
- **CA-Y38** API local: `estado` vazio → `estado` com as `EstadoTv`; mudança no driver falso →
  `estado` empurrado sem pedido.
- **CA-Y39** Saída à Ayanami (servidor WS falso): `ola` + `bate` a cada 10 s; queda → reconexão
  1, 2, 4… ≤ 60 s com jitter dentro de ±20%; 401 → para de reconectar e a API local segue.
- **CA-Y40** Samsung (servidor falso REST `:8001` + WS): `PowerState=standby` → `KEY_POWER`;
  REST muda → `ok`; 8002 recusado com `ano=2017` → tenta 8001; `ano=2021` → não tenta.
- **CA-Y41** Samsung WOL: `send_magic_packet` falso recebe MAC e broadcast do `casa.toml` 3×;
  desligar com `PowerState=standby` → não envia `KEY_POWER`.
- **CA-Y42** Roku (HTTP falso): `is-tv=false` → caps sem `VOL_STEP`/`INPUT`; Roku TV → completas;
  `keypress` 403 → `ACESSO_NEGADO` com a dica "Acesso à rede"; app sem id → busca por nome em
  `/query/apps` (cache 24 h).
- **CA-Y43** Roku `text("ab c")` → `Lit_a`, `Lit_b`, `Lit_%20`, `Lit_c` em ordem; > 100 → corta e
  loga só o tamanho.
- **CA-Y44** Android TV (`AndroidTVRemote` falso): `volume_info` `level=10,max=50` →
  `EstadoTv.volume=20`; `power(True)` com `is_on=True` → nenhuma tecla; deep link do catálogo
  enviado em `app("netflix")`; entrada sem mudança de `current_app` → `NAO_SUPORTADO`.
- **CA-Y45** Timeouts da §11.5: driver falso que dorme → `TEMPO_ESGOTADO` no limite de cada
  driver; conexão descartada e reaberta na chamada seguinte.
- **CA-Y46** Descoberta (respostas SSDP/mDNS injetadas no `Descobridor`, sem socket multicast):
  Roku, Samsung e Android TV viram 3 candidatos com `chave` certa; mesma `chave` em IP novo →
  `casa.toml` atualizado de forma atômica.
- **CA-Y47** TCL: IP que responde `:8060` e anuncia `_androidtvremote2._tcp` → `androidtv` + log
  `tcl_dois_protocolos`; só `:8060` → `roku`.
- **CA-Y48** Pareamento Samsung (WS falsa que manda token): token no keyring falso e no arquivo
  `0600`; Android TV: código errado 3× → aborta sem gravar; certo → `.crt/.key` `0600`; arquivo
  de pareamento `0644` encontrado na subida → recusa com `permissao_aberta`.
- **CA-Y49** Nenhum log (caplog de um ciclo completo descobrir → parear → 20 ações) contém token,
  código de pareamento, conteúdo de cert nem texto digitado.
- **CA-Y50** `casa.toml`: ausente → sobe sem TVs; apelido duplicado (normalizado) → erro claro;
  driver desconhecido → só aquela TV ignorada; `apps.yaml` + override → override ganha por `id`.
- **CA-Y51** Roteador: "liga a tv da sala" → `tv.power_on` com `tv=sala`; "aumenta o volume" →
  `volume.set` (PC); "aumenta o volume da tv" → `tv.volume` `+3`; "abre a netflix na tv" →
  `tv.app` `app=netflix`; "desliga a tv" → `danger`; "entrada hdmi 2" → `tv.input`.
- **CA-Y52** Escolha da TV (§13.3): as cinco regras em ordem, incluindo "só uma ligada" e a
  pergunta "Mais de uma TV: sala ou quarto?" com resposta curta resolvida no turno seguinte.
- **CA-Y53** `TvActions` (casa falsa em TCP): cada `motivo` vira a frase da §13.2; casa recusando
  conexão → "A casa está fora do ar." sem tentar a Ayanami; toda `SAY_TV_*` está no `phrases.yaml`.
- **CA-Y54** `ActionTool`s: `tv_desligar` devolve `needs_confirmation` e não chama o registry
  antes da confirmação; `tv_app` com app desconhecido → `ToolArgsError`; `tv_estado` não é serial.
- **CA-Y55** PWA (`node --test`): máquina do PTT — < 400 ms descarta, 15 s para sozinho, sair do
  botão cancela, `track.stop()` sempre chamado; sem `isTypeSupported` opus → modo só texto.
- **CA-Y56** PWA: `fetch` de `/saude` falhando → estado `sem_ayanami`, faixa "ligue o Tailscale",
  feed do cache; 401 → apaga token e vai a Parear; controle só desenha botões das `caps`;
  "desligar" exige 2º toque em 3 s e só então manda `confirmed=true`.
- **CA-Y57** Service worker (teste com `caches`/`fetch` falsos): `/v1/feed` network-first com
  recaída, `/v1/casa/*` e `/v1/tarefas` nunca cacheados, `activate` apaga `shell-v<N-1>`; manifest
  válido (campos da §14.6, ícones existem).
- **CA-Y58** Recursos: `magi-casa servir` com 3 `DriverFalso` e sondagem real por 10 min
  (`pytest -m lento`) → ≤ 1% CPU médio e ≤ 80 MB RSS (R6.8).
- **CA-Y59** Web Push (`webpush` falso): payload ≤ 3 KB com `titulo`≤40/`resumo`≤120; 410 apaga a
  assinatura; 429 com `Retry-After` respeitado; no silêncio só `confirma`/`lembrete` saem e os
  demais viram **um** "N avisos" às 07:30; 11º push na hora agrupado; `push_com_pc=false` com PC
  online pula tudo menos `confirma`; notificação de `confirma` sem botão de confirmar.

Validação ao vivo (fora dos CA, precisa do Pedro, S2/S4): critério de sucesso 1 (20 comandos por
driver, p90 ≤ 1,5 s), critério 2 (botão do PWA no 4G p90 ≤ 1,5 s; voz p90 ≤ 4 s), instalação
WebAPK, push com a tela bloqueada e uma semana de uso (critério 8).

## 17. Pendências para os spikes

Valores acima valem até a bancada confirmar; o que mudar volta a esta spec antes da tasks.

| Spike | Precisa confirmar | Se não confirmar |
| --- | --- | --- |
| S1 (node 2) | RTF do Kokoro int8 `pf_dora` ≤ 0,5 (§5.4); faster-whisper `small` int8 RTF ≤ 0,4 e RAM ≤ 2 GB (§5.5); vazão do e5-small; repouso do Compose dentro do RNF-A6 (§9.3) | modo nuvem só texto quando a OpenAI falhar; baixar limites/concorrência da fila `lenta` |
| S2 (TVs reais) | TCL é Roku ou Google TV (§12.2); portas Samsung por ano (8001/8002, §11.1) e `PowerState`; WOL Wi-Fi/cabo; Roku "Acesso à rede" e *Fast TV start* (§11.2); `androidtvremote2` em 6466/6467, reconexão e HDMI por keycode (§11.3); ids `[S2]` do `apps.yaml`; latência por driver (critério 1) | ajustar §11/§12.5 e a matriz §11.4 |
| S3 (`mcp` 2.3) | montagem do `MCPServer` no FastAPI em `/mcp` (`streamable_http_app`, `streamable_http_path`), `AuthSettings`/`token_verifier` com escopos, `get_access_token()`; `claude mcp add` pelo tailnet e ponte `mcp-remote` (§8) — **local feito (Y0.5)**: montagem, verificador, escopos e `get_access_token()` confirmados; bloco da §8 corrigido (caminho no `streamable_http_app`, lifespan, `allowed_hosts`, URL `/mcp/`); falta o tailnet (Y1.6) | servir o MCP em processo/porta própria atrás do mesmo `tailscale serve` |
| S4 (Android do Pedro) | `tailscale serve` + WebAPK; `MediaRecorder` opus; autoplay após o PTT; Web Push via FCM saindo do node 2 com a tela bloqueada (§14–§15) | gravar em WAV via `AudioWorklet`; tocar só após toque |
| S5 (`procrastinate` 3.10) | **feito (Y0.4, `docs/perf/ayanami-s5.md`)**: `retry_stalled_jobs` mudou para `get_stalled_jobs(seconds_since_heartbeat=…)` + `retry_job`; `cancel_job_by_id_async(abort=True)` confirmado (≤ 5 s); `queueing_lock` + `AlreadyEnqueued` confirmado (só em `todo`); `on_job_status` mudou para `worker_middleware`; job de 30 min sobrevive a `kill -9` (via `fila.reanimar`) e a `SIGTERM` (via `retry`); LISTEN/NOTIFY confirmado (500/500, p90 2,6 ms); cron **não** segue o `TZ` → crons da §4.2 convertidos para UTC [DS9] | — (§4 já ajustada) |
| S6 (turno remoto) | `RemoteLink` no `CoreService`: webm → PCM 16 kHz (ffmpeg ≤ 2 s) → turno → PCM 24 kHz → opus; ponto do `on_turn_done` [DS6]; p90 no 4G (voz ≤ 4 s) — **local feito (Y0.6)**: transcodificação e gancho confirmados (§6.3); falta o p90 no 4G (F.x) | ajustar o gancho e os prazos da §6.2 |
