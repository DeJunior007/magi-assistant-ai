# Spec — Espera viva

Contratos, números e tabelas. Implementa [requirements.md](requirements.md) segundo o
[design.md](design.md). Os números com "(D*)" seguem o padrão da decisão em aberto até o Pedro
decidir.

## 1. Mensagem `think` (núcleo → HUD)

```python
THINK_KINDS = frozenset({"wait", "tool", "lote"})   # magi/common/contracts.py
THINK_TOOLS = frozenset({"search", "news_query", "steam_game", "game_help", "self_info",
                         "screenshot", "spotify_play", "spotify_pick", "spotify_control",
                         "open_game", "close_game", "volume", "rgb", "hud", "remember",
                         "forget", "other"})

@dataclass(frozen=True, slots=True)
class ThinkMsg(_HudMsg):
    """núcleo -> HUD ``{"t":"think","v":"tool","tool":"search"}`` (espera viva, R2/R5.3)."""
    T: ClassVar[str] = "think"
    v: str                    # THINK_KINDS
    tool: str | None = None   # só com v="tool"; nome fora de THINK_TOOLS vira "other"
    n: int = 0                # só com v="lote": lote que acabou de ser falado (1..)
    def to_dict(self) -> dict[str, Any]:  # omite tool/n quando não se aplicam
```

| Exemplo | Quando |
| --- | --- |
| `{"t":"think","v":"wait"}` | a frase de espera local começou a tocar (R3) |
| `{"t":"think","v":"tool","tool":"news_query"}` | `_tools_node` vai rodar a ferramenta (uma por ferramenta; em paralelo, várias) |
| `{"t":"think","v":"lote","n":1}` | o lote 1 fechou e o modelo segue (R5.3) |

`events.decode_hud` e `hud_bridge._MIN_DECODERS` decodificam `think`; v inválido → `DecodeError`
no núcleo e linha ignorada no HUD. `ThinkMsg` entra em `HudMessage`.

## 2. Pose de pensar (`hud/wired/pensando.py`)

```python
@dataclass(frozen=True)
class Pose:
    etapa: str                       # "hm" | "pensando" | "concentrada"
    ciclo: tuple[tuple[str, float, float], ...]   # (olhos, dx, dy) como THINK_CYCLE
    passo_s: float                   # tempo em cada olhar do ciclo
    tilt: float                      # graus a mais (hoje THINK_TILT 2.2)
    efeitos: tuple[str, ...] = ()    # "dots", "question"
    corpo: tuple[str, ...] = ()      # "sway", "bob_lento", "braco:P14"
    look: str | None = None          # painel (chave de LOOK_DIRS) quando há ferramenta

def pose(desde_s: float, tool: str | None, lote: int, tem: Callable[[str], bool]) -> Pose
```

### 2.1 Etapas (R1)

| Etapa | Tempo (`desde_s`) | Ciclo de olhos | passo | tilt | efeitos | corpo |
| --- | --- | --- | --- | --- | --- | --- |
| hm | 0–1,2 s | F4 (cima) fixo | — | 3,0 | — | — |
| pensando | 1,2–3,5 s | `THINK_CYCLE` de hoje | 1,3 s | 2,2 | `dots` | `sway` |
| concentrada | > 3,5 s | B18 → B13 (semicerrados; sem B18: B13, F7) | 2,0 s | 1,5 | `dots` rápido | `bob_lento`, `braco:P14` |

- `lote ≥ 1` → `desde_s` conta a partir do aviso do lote, mas a etapa mínima é **pensando**.
- Olhar sem asset (`tem("eyes/X.png")` falso) sai do ciclo; ciclo vazio → `THINK_CYCLE`.
- Boca: C1 (como hoje). Fundo: `focus` (como hoje).

### 2.2 Efeito `dots`

Três pontos acima da cabeça (mesma âncora do `question`), cada um acende em sequência; período
0,9 s em **pensando**, 0,6 s em **concentrada**; esmaece em 0,2 s ao sair. Em código no
`_reaction_effect` (com PNG `extra/D10.png`, se existir, estático como os D* da R3.1 das reações).

### 2.3 Ferramenta → olhar (R2.1)

| Ferramenta | Painel (`LOOK_DIRS["main"]`) |
| --- | --- |
| `news_query` | `radio` (Rádio Ayanami) |
| `spotify_play`, `spotify_pick`, `spotify_control` | `player` |
| `open_game`, `close_game`, `game_help`, `steam_game` | `fps` |
| `rgb` | `led` |
| `search`, `self_info`, `screenshot`, `hud`, `volume`, `remember`, `forget`, `other` | — (sem olhar; segue o ciclo) |

O olhar para o painel dura 1,5 s e volta ao ciclo da etapa. Tela `idle` usa `LOOK_DIRS["idle"]`.

### 2.4 Chip (R2.2, R5.3)

| Situação | Rótulo |
| --- | --- |
| `thinking` sem ferramenta | `Thinking · 思考中` (hoje) |
| ferramenta `search`/`news_query` | `Searching · 検索中` |
| ferramenta `steam_game`/`game_help` | `Checking · 確認中` |
| ferramenta de mídia/PC (`spotify_*`, `open_game`, `close_game`, `volume`, `rgb`, `hud`, `screenshot`) | `Working · 作業中` |
| entre lotes (`lote`) | `Thinking · 思考中` até o próximo som |

Mesma cor/aceso do `thinking`. `MIN_DWELL_S` vale para a troca de rótulo.

## 3. Frase de espera

### 3.1 Catálogo `magi/core/espera.yaml`

```yaml
# Frases de espera da Condessa (espera viva, R3/R4). Saem do acordo do Conselho (E2.1).
# Placeholders: {jogo} (jogo em foco). Toda frase precisa passar no linter (spec §4).
topicos:
  jogo:     {palavras: [build, boss, chefe, conquista, fase, mapa, patch, lore], frases: [...], moldes: ["Hm, {jogo}… deixa eu pensar."]}
  noticia:  {palavras: [noticia, manchete, aconteceu, saiu], frases: [...]}
  musica:   {palavras: [musica, faixa, banda, album, artista, toca], frases: [...]}
  pc:       {palavras: [pc, gpu, cpu, temperatura, fps, memoria, disco], frases: [...]}
  conta:    {palavras: [quanto, quantos, calcula, converte, porcento], frases: [...]}
  geral:    {frases: [...]}   # sem tópico
vetadas: []   # o Pedro também veta em ~/.config/magi/condessa-gosto.toml [espera] vetadas
```

Mínimo: 4 frases por tópico, 8 em `geral`, ≥ 1 molde em `jogo`. Exemplos do tom (o texto final é do
Conselho): "Hm, deixa eu pensar nessa.", "Peraí, tô juntando as ideias.", "Boa. Um segundo de
cérebro aqui.", "Hm, {jogo}… deixa eu pensar."

### 3.2 Tópico

`topico(texto, ctx)`: normaliza (minúsculo, sem acento), procura prefixo de palavra de cada
`palavras`; vence o tópico com mais acertos, empate pela ordem do arquivo; sem acerto → `geral`.
Molde com `{jogo}` só se há jogo em foco (`ctx.game` / `GameContext`) **e** o tópico é `jogo`;
nome do jogo > 30 caracteres → frase sem molde.

### 3.3 Quando (R3, D2)

| Regra | Valor |
| --- | --- |
| Só rota | `RouteKind.AGENT` (depois do `_settle`) |
| Espera mínima | `frase_apos_ms` = 700 ms contados do fim do `transcribe` |
| Não fala se | `early.started`; turno de continuação com texto ≤ 3 palavras; `[espera] frase = false`; tarefa cancelada |
| Por turno | ≤ 1 |
| Repetição | nenhuma das 2 últimas frases ditas (por satélite) |
| Folga | depois de 2 turnos de agente seguidos com frase, o 3º não tem |
| Vetadas | `espera.yaml vetadas` ∪ `condessa-gosto.toml [espera] vetadas` |

### 3.4 Eco do modelo (R3.4)

`mesma_espera(frase)`: normalizada, ≤ 8 palavras e começa por um destes prefixos: "deixa eu ver",
"deixa eu pensar", "deixa eu checar", "um segundo", "um instante", "peraí", "pera", "so um
momento", "vou ver", "hm". Se a frase local já tocou, a **1ª** frase interina do modelo que bate
é descartada (vai para `early.skipped`, não volta no fim).

## 4. Honestidade (linter `honesta`)

Frase reprovada se, normalizada, contém:

| Tipo | Padrões (prefixo de palavra) |
| --- | --- |
| ação de ferramenta | "vou pesquisar", "vou buscar", "to pesquisando", "to buscando", "abrindo", "consultando", "olhando aqui na" |
| resultado | "achei", "encontrei", "ja sei", "ja vi", "pronto", "aqui esta", "e isso" |
| certeza/promessa | "com certeza", "sei sim", "garanto", "prometo", "ja ja", "rapidinho", "num instante te digo" |
| fonte | "segundo", "de acordo com", "no google", "na wiki", "no site" |
| número/dado | qualquer dígito ou número por extenso |
| tamanho | > 8 palavras ou > 1 frase |

Permitido: o que ela faz com a própria cabeça agora ("pensar", "lembrar", "juntar as ideias",
"hm"), comentário do pedido sem dado ("boa pergunta", "essa é das boas"), o nome do jogo em foco.
O teste roda em todas as frases e moldes preenchidos com 3 jogos falsos.

## 5. `[espera]` no `config.toml`

```toml
[espera]
frase = true              # R3 (frase de espera local)
frase_apos_ms = 700       # espera após a transcrição antes da frase (D2)
lotes = true              # R5.1–R5.4
lotes_max = 3             # lotes por turno (D3)
lotes_frases_max = 6      # frases faladas no turno: lotes + resposta final (D3)
ferramentas_paralelo = true   # R5.5
```

Valor inválido → `ConfigError` com o nome da chave; seção ausente → padrões. Entra em
`config.example.toml` comentado.

## 6. `EarlySpeech` (`magi/core/early.py`)

| Membro | Novo/Muda | Contrato |
| --- | --- | --- |
| `waits: list[str]` | novo | frases de espera locais faladas |
| `lotes: list[list[str]]` | novo | frases de cada lote, em ordem |
| `say_wait(s)` | novo | fala `s` se `not started`; abre o envio; fora de todas as cotas; devolve `bool` |
| `say(s, lote=False)` | muda | com `lote=True` entra no lote aberto; recusa se passar de `lotes_frases_max` |
| `open_lote()` / `close_lote() -> int` | novo | abre/fecha um lote; `close_lote` devolve n (0 se vazio) e o `_Voice` avisa o HUD |
| `drop_wait_echo(s) -> bool` | novo | R3.4 |
| `missing(speech)` | muda | também tira `waits` e lotes |
| `full_text(final) -> str` | novo | lotes + `final`, sem repetir frase (R5.4) |
| `max_sentences` | igual | 2 para a resposta final |

`_Voice` (graph.py): a volta `steps ≥ 2` que termina em ferramenta e tem texto → lote; a 1ª volta
continua interina (até `INTERIM_MAX`), exceto texto com ≥ 2 frases (já é parte da resposta) → lote.
Retenção da 1ª volta (`held`) igual a hoje.

## 7. Ferramentas em paralelo (R5.5)

`Tool.serial: bool = False` (atributo lido por `getattr`, como `final`); `True` em `spotify_*`,
`open_game`, `close_game`, `volume`, `rgb`, `hud`, `remember`, `forget`, `screenshot`. Na volta:
ferramentas `serial` rodam em série, na ordem; as outras em `gather` junto. Confirmação: a
primeira em ordem que devolver `needs_confirmation` vence, as demais em curso são canceladas e o
resultado delas descartado. Exceção numa ferramenta = resultado de erro dela (não derruba a volta).

## 8. Medida e log (R8)

- `tools/perf.py latency` ganha a coluna `primeiro_som` (1º `audio-chunk` do satélite após o
  `audio-stop` do turno) ao lado da atual; resumo com média/p90 das duas.
- Log INFO do núcleo: `espera: frase "<texto>" (<tópico>) em <ms> ms`, `espera: sem frase
  (<motivo>)`, `espera: lote <n> (<frases>) em <ms> ms`, `espera: ferramentas <a>,<b> em paralelo`.

## 9. Critérios de aceite (testes)

- **CA-01** `ThinkMsg` ida e volta (`to_dict` → `decode_hud` → `hud_bridge._decode_min`); v
  inválido recusado.
- **CA-02** `pose()` dá a etapa certa nos tempos 0; 1,19; 1,21; 3,49; 3,51 s; com `lote=1` nunca
  dá `hm`; asset ausente sai do ciclo.
- **CA-03** Linter reprova cada linha da tabela §4 e aprova o catálogo inteiro (+ moldes).
- **CA-04** `escolher` respeita §3.3 (repetição, folga, vetadas, continuação curta) com `rng` fixo.
- **CA-05** Turno de agente com chat falso que demora 2 s: a frase de espera toca a ~700 ms
  (relógio do loop controlado) e a resposta entra no **mesmo** envio; com chat que fala em 300 ms,
  nenhuma frase de espera. Comando local: nenhuma.
- **CA-06** Eco: frase local + interina "Deixa eu ver isso." → a interina não toca; "O tempo eu já
  sei: sol." toca.
- **CA-07** Pedido de 2 partes com 2 voltas de ferramenta: lote 1 toca antes da 2ª ferramenta
  terminar; `ThinkMsg("lote", n=1)` enviado; `subtitle.full` = lote 1 + final; total ≤ 6 frases.
- **CA-08** `_tools_node` com 2 ferramentas de leitura de 1 s cada termina em ~1 s; com uma
  `serial` + uma de leitura, a ordem das mensagens `tool` é a pedida.
- **CA-09** Wake no meio da frase de espera cancela envio, tarefa de espera e lotes (R6).
- **CA-10** `[espera] frase = false` e `lotes = false` reproduzem os testes atuais de
  `tests/core/test_stream_speech.py` sem mudança de asserção.
