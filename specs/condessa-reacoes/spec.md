# Spec — Reações da Condessa

Contratos, números e a tabela de gatilhos. Implementa [requirements.md](requirements.md) segundo o
[design.md](design.md). Gatilho exato de cada reação: **acordo §1** (Nº da planilha) e **acordo §2**
(ideias novas, citadas aqui como **I1–I20**), em `persona/conselho/atas/2026-10-08-reacoes/acordo.md`.
Sequências (passos e ms): `persona/conselho/atas/2026-10-08-reacoes/reacoes.md` e a tabela do acordo §2.

## 1. Chaves

- Reação nova: `snake_case` curto em português, único (`piscada_dupla`, `duelo_ado`). `Def.n` guarda
  o Nº da planilha (1–90) ou `"I7"`.
- Variante de uma das 19 atuais: **mesma chave** + `variante` (`hot` / `alivio`; `fps_drop` /
  `recuperou`, `vergonha`; `game_on`; `game_off`; `led` / `cutucada2`, `cutucada3`, `fone`;
  `long_session` / `pausa`; `claude` / `terminou`, `demorando`, `pesado`, `com_musica`;
  `music_new` / `amou`; `music_love` / `chefe`; `skips` / `tontura`; `cleanup`).

## 2. Contratos (`hud/wired/reacoes/contratos.py`)

```python
EFEITO = {"D1": "blush", "D2": "sweat", "D3": "zz", "D4": "question", "D5": "bang",
          "D6": "notes", "D7": "tear", "D8": "vein", "D9": "sparkle"}

@dataclass(frozen=True)
class Passo:
    ms: int                         # duração
    eyes: str | None = None         # B*/F* (None = do estado)
    mouth: str | None = None        # C*/V*
    look: str | None = None         # painel (LOOK_DIRS) ou None
    efeitos: tuple[str, ...] = ()   # nomes de EFEITO
    corpo: tuple[str, ...] = ()     # "bob", "sway", "tails", "fone_on", "fone_off", "braco:P9", "iris:<olhar>"

class Classe(StrEnum):  # uma reação pode ter várias
    PASSIVA, RARA, DIARIA, SONO, ZOEIRA, COBRANCA, SISTEMA, VITORIA, VOLTA, MUSICA, TEMPO, PEDRO, NOTURNA

@dataclass(frozen=True)
class Def:
    chave: str; n: int | str; nome: str
    passos: tuple[Passo, ...]       # 1..4
    classes: frozenset[Classe]
    mood: str = "calm"              # fundo
    prio: int = 1                   # dentro da mesma classe
    cooldown_s: float = 600.0
    sinal: str | None = None        # "A".."F", "fan", "restart", "capturas", "datas", "P13"; None = já roda
    fala: str | None = None         # chave em [falas.*] do gosto; None = só rosto

@dataclass(frozen=True)
class Disparo:
    chave: str; motivo: str; variante: str | None = None; fmt: dict = field(default_factory=dict)
```

`Reaction` (atual) ganha só `efeitos: tuple[str, ...] = ()` e `corpo: tuple[str, ...] = ()`; o
campo `effect` continua (primeiro efeito) para não quebrar o retrato.

## 3. Governador (números do acordo §3)

| Regra | Valor |
| --- | --- |
| Passiva: intervalo mínimo | 40 s (respirar/piscar/olhar solto não contam) |
| Raras (10, 11, 13) | ≤ 1/h cada |
| Diária (12 Corando, I16, I20) | ≤ 1/dia cada (I16 ≤ 1/noite) |
| Ativa: cooldown padrão | 600 s por chave (24: 180 s; cutucada: 3 s; `Def.cooldown_s` manda) |
| Ativas por hora | ≤ 8; `SISTEMA`, `VITORIA`, `VOLTA` não contam nem são barradas |
| Prioridade no mesmo tick | SISTEMA > PEDRO > MUSICA > TEMPO > PASSIVA; empate → `prio` maior |
| Fila | 1 slot, validade 30 s, só `VOLTA` e `VITORIA`, quando a Magui não está parada |
| Blush (passo com `blush`) | ≤ 1 reação/h; 62, 74, 87 fora da conta e nunca barrados |
| Lágrima (`tear`) | só 22h–04h, ≤ 1/dia; fora disso o efeito é removido do passo (a reação toca) |
| `ZOEIRA` | barrada com humor do Pedro ≤ 1 ou 22h–04h |
| `COBRANCA` | com humor ≤ 1 ou 22h–04h: C8/C11 → C9 em todos os passos |
| `SONO` | barrada com jogo, Claude rodando ou música nota ≥ 1 |
| `RARA` | barrada com jogo aberto |
| Ado | reação com `blush` ou mood `love` nunca dispara para faixa da Ado |
| `[reacoes] desligadas` (gosto do Pedro) | barradas sempre (R11) |

**Classes por reação** (as não listadas: só a classe do detector):
- ZOEIRA: 8, 16, 78, 83, 84, 85, I14, I15. COBRANCA: 34, 36, 41, 80, 84, I4, I5.
- SONO: 17, 18, 19. RARA: 10, 11, 13. DIARIA: 12, I16, I20. NOTURNA: 29 (lágrima), I2, I12, I16.
- VITORIA: 35, 37, 39, 53, 75, I6. VOLTA: 20, 57, 62. Blush fora da conta: 62, 74, 87.

## 4. Fatores de humor (acordo §4)

`humor.fatores(ctx) -> dict[nome, peso]` com os 12 fatores da tabela do acordo §4. Peso de uma
passiva = 1 + Σ pesos dos fatores ativos que a favorecem; fator que **bloqueia** zera. Sorteio
ponderado com `rng` injetado. Fonte das condições: `ctx` (§4 do design).

## 5. Gatilhos por detector

Cada linha: Nº/ideia → módulo. Gatilho e sequência: acordo §1/§2. *(cond. X)* = só com o sinal X.

| Módulo | Reações |
| --- | --- |
| `passivas.py` | 1–4, 6–14, 16, 21, 22, 23 |
| `det_tempo.py` | 17, 18, 19, 20, 57, 58, 59, 60, 61, 62, I1, I2, I16, I17, I19 |
| `det_musica.py` | 24–30, 32, 33, 78, 81, 83, 85, 89, I3, I7–I15 (26: 60 s sem pulo) |
| `det_sistema.py` | 34–42 (sem 43), 44, 45, 48, 80, 84, I4, I5, I6 |
| `det_claude.py` | 52, 53, 56, 75, 82, 90 · *(cond. C)* 54, 55 |
| `det_entrada.py` | 5, 64, 66 · *(cond. A)* 15, 65, 67, 69, 70, 77 |
| `det_conversa.py` | 71, 72, 73, 79, I18 · *(cond. B)* 74, 76, 86, 87 · *(cond. F)* 88 |
| `det_volume.py` | *(cond. D)* 31 e a variante de pico do 26 |
| `det_notif.py` | *(cond. E)* 46, 47 |
| `det_extras.py` | *(cond. fan)* 43 · *(cond. restart)* 50 · *(cond. capturas)* 51 · *(cond. datas)* 63 · *(cond. P13)* I20 |

Substituídas sem detector: 49, 68 (as substitutas são I1, I2, I3).

**"Evento real" do Pedro** (`atividade.py`, usado por 17–20, 57, 62, I1, I2, I16, I17): clique no
HUD, faixa nova, Claude Code passou a rodar, Magui ouvindo, jogo abriu. Persistido em
`~/.local/state/magi/condessa-atividade.json` (`ultimo`, `dia`, `primeiro_do_dia`).

**Campos novos do `Snapshot`/`ctx`** (cada tarefa adiciona o seu): `git_head` (R1.5, em
`GitStatus`), `turn_tag` (R2.B), `volume` (R2.D), `notif` (R2.E), `fan_rpm`, `restart_needed`,
`capturas_mtime` (R2.G), `claude.last_event` (R2.C).

## 6. Sinais novos

- **A — retrato.** `gamerhud.py` liga `setMouseTracking`; área = rect do rosto devolvido por
  `main_screen.mascot_tick`. Eventos: `hover_in`, `hover_parado(s)` (3 s → 77, 10 s → 15),
  `face:dbl` (2 cliques ≤ 300 ms), `face:long` (≥ 800 ms), `face:drag` (arrasto ≥ 40 px na metade
  de cima). Clique simples continua push-to-talk; com D1 = (a), o PTT espera 250 ms.
- **B — tag do turno.** Núcleo: `turn_tag ∈ {elogio, zoeira, correcao, sussurro}` por turno, só
  com sinais locais (mesmas regras de palavras do `mood.py`), sem LLM. `TurnTagMsg` em
  `magi/common/contracts.py` (validação como `MoodMsg`); HUD guarda a última tag com hora; o
  detector só reage a tag com ≤ 10 s.
- **C — hooks.** `hud/tools/claude_hook.py <evento>` lê o JSON do hook no stdin e grava 1 linha em
  `~/.cache/magi/claude-events.jsonl` (`{"t": epoch, "ev": "fail"|"notify"|"stop", "proj": ...}`,
  gira em 1 MB). `ClaudeStats` lê a última linha nova. Instalação: trecho de `settings.json` em
  `docs/design/CONDESSA-REACOES.md` para o Pedro colar (D2).
- **D — volume.** Thread de 1 s com `wpctl get-volume @DEFAULT_AUDIO_SINK@`; ausência do `wpctl`
  → `volume = None` e o 31 nunca dispara.
- **E — notificações.** Subprocesso `dbus-monitor --session "interface='org.freedesktop.Notifications',member='Notify'"`
  lido numa thread; extrai urgência (`byte 2` = crítica). Morre com o HUD. Nada de `qdbus`/`gdbus`.
- **F — voz baixa.** Vem como tag `sussurro` no sinal B (tom com volume abaixo do limiar do satélite).
- **Extras.** `fan*_input` do hwmon (≥ 30% acima da média de 5 min); `dnf needs-restarting -r` a
  cada 6 h numa thread (rc 1 = precisa); mtime de `~/Imagens/Capturas de tela` (ou `xdg-user-dir
  PICTURES` + "Capturas de tela"); `[datas]` do gosto (`"MM-DD" = "nome"`) e data do 1º commit.

## 7. Falas

Reação nova é só rosto, salvo as que o acordo já previa com texto (nenhuma nova). Fala existente de
uma variante continua. Nenhuma fala contém "refrão", "download", "elogio", "notificação" (teste
varre o `[falas]` do gosto).

## 8. Critérios de aceite

- **CA-01** As 19 reações atuais: todos os testes de `tests/hud/test_wired_reactions.py` e
  `test_wired_portrait.py` verdes sem mudar asserção.
- **CA-02** Sequência de 4 passos: `active()` devolve o passo certo em 0, meio e fim de cada passo.
- **CA-03** Governador: 24 h simuladas com disparos aleatórios → nenhuma regra do §3 violada.
- **CA-04** Cada reação do §5 sem *(cond.)* dispara com um `Snapshot` sintético do gatilho
  (um teste por linha, no teste do módulo).
- **CA-05** Reação com sinal ausente nunca aparece em `catalogo.ATIVAS`.
- **CA-06** Reação `NOTURNA` aparece no retrato às 23h com a Magui dormindo.
- **CA-07** `reacoes.jsonl` tem uma linha por reação tocada, com `furou_cota`.
- **CA-08** Observe de 1 tick com todos os detectores ≤ 2 ms (média de 1000 ticks, máquina do Pedro).
