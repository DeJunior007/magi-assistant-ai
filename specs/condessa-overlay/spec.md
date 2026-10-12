# Spec — Overlay da Condessa

Contratos, números e casos de borda. Implementa [requirements.md](requirements.md) segundo o
[design.md](design.md).

## 1. Módulo puro `hud/wired/overlay.py` (assinaturas finais)

Os caminhos são lidos na hora da chamada (padrão `None`), para os testes trocarem as constantes
com `monkeypatch` (o `tests/hud/conftest.py` isola todas).

```python
CONFIG_FILE = Path.home() / ".config/magi/overlay.toml"
LOCK_FILE = Path.home() / ".cache/gamerhud/overlay.lock"
HUD_LOCK = Path.home() / ".cache/gamerhud/hud.lock"
REGISTRO_FILE = Path.home() / ".local/state/magi/reacoes-overlay.jsonl"
ATIVIDADE_FILE = Path.home() / ".local/state/magi/atividade-overlay.json"

@dataclass
class Config:
    tamanho: int = 220            # lado do quadro em px lógicos, preso em 120..480
    tela: str | None = None       # QScreen.name(); None = principal
    canto: str = "sup_dir"        # sup_esq | sup_dir | inf_esq | inf_dir      (D6)
    margem: int = 24              # px da borda da tela até o quadro
    fundo: bool = False           # True = desenha o fundo de hexágonos do retrato
    estilo: str = "card"          # "card" | "solto" (O4.1; no card o fundo é sempre True)
    renderer: str = "cpu"         # "cpu" | "gl" (sobrepõe o portrait.toml só no overlay)
    em_jogo: str = "oposto"       # "oposto" | "esconde" | "fica"  (D3)
    tela_jogo: str | None = None  # monitor do jogo (QScreen.name()); None = principal
    com_hud: str = "esconde"      # "esconde" | "independente"     (D2)
    ligado: bool = True           # False = o autostart sai na hora
    x: int | None = None          # só na recaída XWayland (D4 = b)
    y: int | None = None
    @classmethod
    def ler(cls, caminho: Path | None = None) -> "Config": ...   # None = CONFIG_FILE; ausente/inválido → padrões; chave desconhecida ignorada
    def gravar(self, caminho: Path | None = None) -> None: ...   # escrita atômica (tmp + rename)

def canto_para_posicao(cfg: Config, tela: QRect) -> QPoint: ...   # topo-esquerdo do quadro

@dataclass(frozen=True)
class Lugar:                                   # o que a janela faz agora (D2/D3)
    visivel: bool
    tela: str | None = None                    # monitor onde mostrar; None = principal
    motivo: str = ""                           # "normal" | "hud" | "jogo" | "jogo_oposto"

def decidir_lugar(cfg: Config, telas: Sequence[str], principal: str | None,
                  gaming: bool, hud: bool) -> Lugar: ...

class Gestos:                                  # relógio injetado; sem Qt de verdade
    DBL_MS = 250; LONG_S = 0.6; DRAG_PX = 18   # mesmos valores do gamerhud (FACE_*), copiados
    def __init__(self, enviar_click: Callable[[str, float], None],
                 enviar_hover: Callable[[str, float], None]): ...
    def press(self, x: float, y: float, alto: bool, agora: float) -> None: ...   # alto = metade de cima do rosto
    def move(self, x: float | None, y: float | None, dentro: bool, agora: float) -> None: ...
    def release(self, agora: float) -> None: ...
    def tick(self, agora: float) -> None: ...     # vence a espera do duplo → on_click("face")

def regiao_entrada(img: QImage, limiar: int = 76, grade: int = 8) -> list[QRect]: ...
def snapshot_leve(magui: str, mouth: float, mood: int | None, turn_tag, track, gaming: bool) -> Snapshot: ...
def hud_aberto(lock: Path | None = None) -> bool: ... # None = HUD_LOCK; flock LOCK_EX|LOCK_NB; conseguiu → solta e False
def jogo_aberto() -> bool: ...                          # steam_game() or mango_game() do gamerhud-watch.py
DETECTORES_OVERLAY: tuple                               # spec §3
```

`regiao_entrada`: alfa da imagem do retrato já no tamanho da janela, reduzida a uma grade de
`grade` px; célula com alfa máximo ≥ `limiar` (≈ 30%) entra; dilata 1 célula (o cabelo balança);
junta as células em retângulos por linha (≤ 64 retângulos). Imagem vazia → `[]` (o chamador então
usa o quadro inteiro, para nunca ficar "inclicável").

`decidir_lugar` (ordem): 1) `hud` e `com_hud == "esconde"` → `Lugar(False, motivo="hud")`;
2) `gaming` e `em_jogo == "esconde"` → `Lugar(False, motivo="jogo")`; 3) `gaming` e
`em_jogo == "oposto"`: monitor do jogo = `tela_jogo` se ligado, senão `principal`; alvo = `cfg.tela`
se ligado e ≠ do jogo, senão o primeiro de `telas` ≠ do jogo → `Lugar(True, alvo, "jogo_oposto")`;
nenhum → `Lugar(False, motivo="jogo")`; 4) normal → `Lugar(True, cfg.tela se ligado senão
principal, "normal")`. A posição no monitor é `canto_para_posicao(cfg, geometria_do_monitor)`.

## 2. `overlay.toml`

```toml
[overlay]
tamanho = 220
canto = "sup_dir"
margem = 24
fundo = false
estilo = "card"
renderer = "cpu"
em_jogo = "oposto"
# tela_jogo = "DP-1"   # opcional; sem a chave = monitor principal
com_hud = "esconde"
ligado = true
```
Valores fora da faixa são presos (`tamanho`) ou voltam ao padrão (texto inválido). O menu
"Tamanho ±" muda 20 px e grava.

## 3. Reações no overlay

`DETECTORES_OVERLAY` = `det_tempo`, `det_musica`, `det_entrada`, `det_conversa` (de
`hud/wired/reacoes/`). Ficam de fora `det_sistema`, `det_claude`, `det_volume`, `det_notif`,
`det_extras` (precisam dos sensores e threads do HUD). Passivas seguem pelo sorteio do `Reactor`.
`Reactor(detectores=DETECTORES_OVERLAY, registro_file=REGISTRO_FILE, atividade=Atividade(ATIVIDADE_FILE))`.

`snapshot_leve` preenche só: `magui_state`, `mouth_level`, `mood`, `turn_tag`, `track` (de um
`data.NowPlaying` próprio, `poll = 3 s`), `gaming`. O resto fica no padrão do `Snapshot`.
`gaming` = `jogo_aberto()` a cada 5 s (carrega `hud/gamerhud-watch.py` por
`importlib.util.spec_from_file_location`, sem executar o `main`).

| Situação | Overlay |
| --- | --- |
| `com_hud = "esconde"` e `hud_aberto()` (teste a cada 5 s) | `hide()`; volta ao fechar o HUD (D2; ganha do jogo) |
| `em_jogo = "oposto"`, `gaming` e há monitor ≠ `tela_jogo` | vai para esse monitor, mesmo `canto`/`margem` (D3) |
| `em_jogo = "oposto"`, `gaming` e um monitor só | `hide()`; volta ao lugar de antes quando o jogo fecha |
| `em_jogo = "esconde"` e `gaming` | `hide()` |
| jogo fechou | volta ao monitor e à posição de antes (guardada pela janela antes de sair) |
| núcleo fora (`connectedChanged(False)`) | dormindo, `portrait.glitch = 0.4` por 2 s e depois 0 |
| menu "Esconder 1 h" | `hide()`; `QTimer` de 3600 s mostra de novo |

## 4. Regra do KWin (`condessa-overlay-rule` no `~/.config/kwinrulesrc`)

Mesmo jeito da `gamerhud-rule` do `install.sh` (`kreadconfig6`/`kwriteconfig6`, acrescenta o nome
em `[General] rules` e acerta `count`):

```
Description=Condessa (overlay pequeno por cima do desktop)
wmclass=condessa-overlay
wmclassmatch=1
types=1
above=true
aboverule=2
acceptfocus=false
acceptfocusrule=2
skippager=true
skippagerrule=2
skipswitcher=true
skipswitcherrule=2
skiptaskbar=true
skiptaskbarrule=2
noborder=true
noborderrule=2
position=<x>,<y>
positionrule=4
```
`positionrule=4` = "Lembrar": o KWin atualiza `position` quando a janela fecha. `<x>,<y>` vem de
`canto_para_posicao` rodado pelo `install.sh` (`python3 -c` com o módulo puro) e só é escrito se a
regra ainda não existir (reinstalar não apaga a posição lembrada). Sem chamadas D-Bus novas.

## 5. Janela (`OverlayWindow(QWidget)`)

- Flags: `FramelessWindowHint | WindowStaysOnTopHint | WindowDoesNotAcceptFocus | Tool`;
  atributos `WA_TranslucentBackground`, `WA_ShowWithoutActivating`; `setMouseTracking(True)`.
- Quadro: `QRectF(0, 0, tamanho, tamanho * 1.15)` (o retrato é `TALL`); `paintEvent` limpa com
  transparente e chama `portrait.paint(p, rect, accent, now)`.
- **O4.1 card** (`estilo = "card"`, padrão): mesmo quadro, com painel chanfrado + scanlines, borda
  fina e cantos marcados na cor do humor (`Reactor.medidor` → `estado.COR_FAIXA`, recaída
  `#b392f0`), retrato recortado com cantos arredondados e fundo ligado, placa `CONDESSA` + estado
  (ouvindo/pensando/falando/dormindo); as camadas ficam em cache e só são refeitas quando
  tamanho/humor/estado mudam. Máscara = retângulo todo; esquerdo arrastado ≥ `DRAG_PX` →
  `startSystemMove` (recusado → move manual); posição gravada ao soltar em `POS_FILE`.
- `portrait.fundo = fundo_efetivo(cfg)` (`cfg.fundo` no solto); com `renderer = "cpu"`, `PartsAssets.renderer` é sobrescrito.
- Máscara: `regiao_entrada` de um quadro desenhado num `QImage` fora da tela, refeita no `show`,
  no resize, ao mudar `react` (início/fim de reação com `corpo` de braço) e no máximo 1×/s.
- Mouse: esquerdo → `Gestos` (alto = `y < centro do rosto`); meio pressionado →
  `windowHandle().startSystemMove()`; direito → `QMenu` (Mover, Tamanho +, Tamanho −,
  Esconder 1 h, Sair). Roda do mouse: ignorada (atravessa só fora da máscara).
- Fechar (`closeEvent`, SIGTERM, SIGINT): `bridge.stop()`, `now_playing` para, solta a trava.

## 6. Comando e autostart

- `hud/system/bin/condessa-overlay`: como `hud/system/bin/gamerhud` (`pkill -f` no padrão
  `^python3 .*/condessa_overlay\.py$`; senão `nohup python3 …/condessa_overlay.py &`).
- `hud/system/autostart/condessa-overlay.desktop`: `Exec=python3 @HOME@/.local/share/gamerhud/condessa_overlay.py`,
  `X-KDE-autostart-after=panel`, `NoDisplay=true`. Com `ligado = false` o processo sai na hora.
- `hud/system/applications/condessa-overlay.desktop`: entrada de menu "Condessa (overlay)".

## 7. Critérios de aceite (testes)

- **CA-O1** `Config.ler`: ausente, inválido, faixa e chave desconhecida (4 casos).
- **CA-O2** `Gestos`: simples (vence 250 ms → `on_click("face")`), duplo (2º press na espera →
  `on_hover("dbl")`, sem clique), longo (≥ 0,6 s → `long`), arrasto (alto e ≥ 18 px → `arrasto`
  uma vez; baixo não arrasta), hover `in`/`move`/`out`. Nunca emite nada que ligue escuta.
- **CA-O3** `regiao_entrada`: imagem sintética com um círculo opaco → retângulos cobrem o círculo
  dilatado e não cobrem os cantos; imagem vazia → `[]`.
- **CA-O4** `canto_para_posicao` nos 4 cantos com margem; padrão = superior direito, 24 px (D6).
- **CA-O9** `decidir_lugar`: HUD aberto → escondido (e ganha do jogo); jogo com 2 monitores → o
  outro (o principal quando `tela_jogo` é o outro); jogo com 1 monitor → escondido; `"esconde"` e
  `"fica"`; sem jogo nem HUD → `cfg.tela` se ligada, senão o principal.
- **CA-O5** `snapshot_leve` + `Reactor(detectores=DETECTORES_OVERLAY)` dispara uma reação de
  `det_entrada` com cliques sintéticos e grava em `REGISTRO_FILE` (caminho do `tmp_path`).
- **CA-O6** janela offscreen (`QT_QPA_PLATFORM=offscreen`): abre, pinta 10 quadros sem erro com
  arte de teste, aplica máscara, `close` solta a trava; segunda instância sai com 0.
- **CA-O7** `grep` em `hud/condessa_overlay.py`, `hud/wired/overlay.py`, `hud/system/bin/condessa-overlay`:
  nenhum `qdbus`, `gdbus`, `kglobalaccel`, `org.kde.KWin`.
- **CA-O8** `install.sh --dry-run` (ou função isolada com `HOME` falso) escreve a regra uma vez;
  segunda rodada não duplica o nome em `rules` nem sobrescreve `position`.
