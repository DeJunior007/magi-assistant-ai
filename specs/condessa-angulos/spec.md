# Spec — Ângulos do retrato da Condessa

Contratos, números, a lista de imagens e os critérios de aceite. Implementa
[requirements.md](requirements.md) segundo o [design.md](design.md).

## 1. Contratos (`hud/wired/angulos.py`)

```python
FRENTE = "G1"
YAW = {"G1": 0, "G2": -35, "G3": 35, "G4": -90, "G5": 90}        # graus; − = esquerda da tela (D1)
PITCH = {"G6": -20, "G7": 20}                                      # − = para cima

@dataclass(frozen=True)
class Angulo:
    id: str
    pasta: Path                       # <retrato>/angulos/<id>
    yaw: int = 0
    pitch: int = 0
    pisca: bool = False               # tem eyes/B2.png e eyes/B3.png
    fala: bool = False                # tem mouth/C2.png e mouth/C3.png E angulo.toml diz fala = true
    olhos: tuple[int, int, int, int] | None = None   # caixa dos remendos (quadro de 1024)
    boca: tuple[int, int, int, int] | None = None

def carregar(pasta_retrato: Path, desligados: frozenset[str] = frozenset()) -> dict[str, Angulo]: ...
def pedido(reaction) -> str | None: ...           # "angulo:G9" no corpo → "G9"
def lado_do_look(look: str | None, tela: str = "main") -> str | None:  # painel → direção (LOOK_DIRS) → ângulo, spec §3

@dataclass
class Transicao:
    de: str; para: str; inicio: float; dur: float; sentido: int   # sentido −1/0/+1
    def k(self, agora: float) -> float: ...       # 0..1, ease-in-out (smoothstep)
    def camadas(self, agora: float) -> tuple[Camada, Camada]: ...   # (de, para)
    def acabou(self, agora: float) -> bool: ...

@dataclass(frozen=True)
class Camada:
    opacidade: float; dx: float; dy: float; escala: float   # dx/dy em px do quadro de 1024

class Seletor:
    def __init__(self, disponiveis: dict[str, Angulo], cfg: dict | None = None): ...
    def escolher(self, agora: float, estado: str, reacao, reacao_ate: float,
                 pensando_desde: float | None) -> tuple[str, float]: ...   # (id, duração da transição)
```

## 2. Pasta montada e `angulo.toml`

```
<retrato>/angulos/G2/base.png          busto inteiro, olhos abertos, boca fechada   obrigatório
<retrato>/angulos/G2/eyes/B2.png       remendo meio fechado (quadro inteiro)        opcional
<retrato>/angulos/G2/eyes/B3.png       remendo fechado                              opcional
<retrato>/angulos/G2/mouth/C2.png      remendo entreaberta                          opcional (fase 3)
<retrato>/angulos/G2/mouth/C3.png      remendo aberta                               opcional (fase 3)
<retrato>/angulos/G2/angulo.toml
```
```toml
yaw = -35          # do spec §1; o build escreve o padrão da tabela do §6
pitch = 0
fala = false       # só vira true à mão, depois de conferir as bocas
olhos = [330, 300, 700, 480]   # caixa achada pelo build (diferença B2 × base)
boca = [450, 500, 590, 590]
dx = 0             # deslocamento aplicado no alinhamento (informativo)
dy = 0
```
O build só escreve o `angulo.toml` se ele não existir (edições à mão ficam).

## 3. Seletor (números; `cfg` do `[angulos]` do gosto sobrepõe)

| Regra | Valor |
| --- | --- |
| `estado` em `speaking`/`listening` | `G1` (ou o atual, se tiver `fala`), transição de 160 ms |
| passo com `braco:` ou `iris:` no `corpo` | `G1` |
| pedido explícito (`angulo:<ID>` no `corpo`) disponível | o pedido, já |
| `look` do passo (painel; direção por `LOOK_DIRS[tela][painel]`, a tela vem do retrato) + passo dura ≥ 1,2 s | `left`, `up_left`, `down_left` → `G2`; `right`, `up_right`, `down_right` → `G3`; `up` → `G6`; `down` → `G7` |
| `thinking` há ≥ 3 s | `G9` se disponível (D4) |
| tempo mínimo num ângulo (fora a volta forçada) | 1,5 s |
| tempo máximo fora de frente | 6 s; 2,5 s se o ângulo não `pisca` (R5) |
| intervalo mínimo entre giros automáticos | 8 s (pedido explícito e volta a `G1` não contam) |
| teto | 6 giros por minuto (janela móvel) |
| duração da transição | 200 ms; 260 ms entre dois ângulos não frontais (ex.: G2 → G3 direto); 160 ms na volta pela fala |
| `[angulos] ligado = false` | sempre `G1` |

## 4. Transição

`sentido = sinal(yaw(para) − yaw(de))` (ou de `pitch`, para G6/G7, aplicado em `dy`). Com
`k = smoothstep(t / dur)`:

| Camada | opacidade | deslocamento | escala |
| --- | --- | --- | --- |
| de (desenhada primeiro) | 1 se k < 0,5; senão 2 − 2k | `sentido · 12 · k` px | 1 − 0,02·k |
| para (por cima) | min(1, 2k) | `−sentido · 12 · (1 − k)` px | 0,98 + 0,02·k |

Assim o busto nunca fica "fantasma": na 1ª metade o "de" está inteiro; na 2ª, o "para" já está
inteiro. A escala é em volta de `NECK_PIVOT`. O fundo (`_backdrop`) é desenhado uma vez por baixo,
fora da mistura.

## 5. Montagem (`condessa_build.build_angulos`)

- Entrada: `G<n>.<ext>` (busto inteiro no verde) e opcionais `G<n>_B2`, `G<n>_B3`, `G<n>_C2`,
  `G<n>_C3` (inpainting só dos olhos/boca sobre a `G<n>`). `G1` não é lido (a frente é a A1).
- Recorte: `chroma` + `despill` + `defringe` (os mesmos da A1); `bottom_fade` igual ao do corpo.
- Alinhamento: máscara do alfa na faixa dos ombros `y ∈ [820, 1000]` da `G<n>` contra a da A1;
  `best_shift` com alcance ±40 px; aplica `(dx, dy)` à base e a todos os remendos do ângulo.
  Largura do busto na faixa diferente da A1 em > 8% → aviso "G<n>: escala diferente da A1".
- Remendos: `diff_mask(variação, base)` restrita à metade de cima do quadro, maior mancha
  (`only_blobs`), caixa + `FEATHER`; grava o remendo no quadro inteiro e a caixa no `angulo.toml`.
- Ausências: avisa "falta G<n>_B2 (opcional)"; remover a origem e remontar apaga a saída antiga.

## 6. Imagens a gerar (folha de 16 rostos)

Regras para todas: **mesmo personagem e mesma roupa da A1**, mesmo estilo e luz, **mesmo quadro
(quadrado, busto do peito para cima), ombros na mesma altura e do mesmo tamanho da A1**, fundo
verde liso `#00FF00`, nada cortado nas laterais, sem texto. Gere a base de cada ângulo usando a A1
como referência (img2img / referência de personagem) e as variações por **inpainting só na região
dos olhos ou da boca** sobre a base do ângulo (mesma semente). Nomes: `G<n>.png`, `G<n>_B2.png`…

Prefixo comum dos prompts (P0): *"same character as the reference image, the Countess, dark purple
hair in twin tails, lilac eyes, high-collar black outfit with headset, cel shading, clean line art,
same art style and lighting, chest-up bust, same framing and shoulder height as the reference,
plain flat green background #00FF00, nothing cropped at the sides, no text"*.

| Fase | ID | Rosto | Base (P0 + …) | Variações (inpainting) |
| --- | --- | --- | --- | --- |
| — | G1 | frente | é a A1 (já existe) | — |
| **1** | **G2** | 3/4 esquerda | *"head and shoulders turned three-quarters to the left side of the image (about 35°), eyes open looking left, mouth closed, calm"* | **B2** *"eyes half closed, mid-blink"* · **B3** *"eyes fully closed, relaxed eyelids"* |
| **1** | **G3** | 3/4 direita | *"… turned three-quarters to the right side of the image (about 35°), eyes open looking right, mouth closed, calm"* | **B2**, **B3** (mesmos textos) |
| 2 | G9 | mão no queixo (pensando) | *"front view, head slightly tilted, one hand touching the chin, thoughtful eyes looking up and to the side, mouth closed"* | B2, B3 |
| 2 | G6 | olhando para cima | *"front view, chin slightly raised, eyes looking up, mouth closed"* | B2, B3 |
| 2 | G7 | olhando para baixo (lendo) | *"front view, head slightly lowered, eyes looking down as if reading, mouth closed"* | B2, B3 |
| 2 | G10 | susto | *"front view, body pulled slightly back, eyes wide open, eyebrows raised, small open mouth"* | B3 |
| 2 | G11 | sorriso de canto | *"head tilted slightly, one-sided smirk, half-lidded playful eyes"* | B2, B3 |
| 3 | G2, G3 | bocas para falar | — | **C2** *"mouth slightly open, speaking softly"* · **C3** *"mouth open, speaking"* |
| 3 | G4 | perfil esquerda | *"full side profile facing the left side of the image, eye open, mouth closed"* | B2, B3 |
| 3 | G5 | perfil direita | *"full side profile facing the right side of the image, eye open, mouth closed"* | B2, B3 |
| 3 | G8 | mão na boca | *"front view, fingers covering the mouth, amused or embarrassed eyes"* | B2, B3 |
| 3 | G12 | 3/4 esquerda olhando para baixo | *"turned three-quarters to the left, head lowered, eyes down"* | B2, B3 |
| 3 | G13 | 3/4 direita olhando para cima | *"turned three-quarters to the right, chin raised, eyes up"* | B2, B3 |
| 3 | G14 | cabeça inclinada (curiosa) | *"front view, head tilted about 15° to one side, curious eyes"* | B2, B3 |
| 3 | G15 | por cima do ombro | *"body turned away to the left, looking back over the shoulder at the viewer"* | B2, B3 |
| 3 | G16 | bocejo / sono | *"front view, eyes closed, hand near the mouth, yawning"* | — |

G12–G16 são propostas para completar 16 (D2): o Pedro troca pelo que a folha tiver. **Fase mínima
= 6 imagens** (G2, G2_B2, G2_B3, G3, G3_B2, G3_B3).

## 7. Critérios de aceite (testes)

- **CA-A1** `carregar`: pasta sem `angulos/` → `{}`; ângulo sem `base.png` some; `pisca`/`fala`
  conforme os arquivos e o toml; `desligados` respeitado.
- **CA-A2** `Seletor`: uma linha de teste por regra do §3 (relógio falso), incluindo teto de 6/min
  em 10 min de `look` lateral a cada 2 s e máximo de 2,5 s sem piscada.
- **CA-A3** `Transicao`: em 50 amostras de `k`, `opacidade(de) + opacidade(para)·(1 − opacidade(de)) ≥ 0,9`;
  `dx` tem o sinal do `sentido`; `k(inicio) = 0`, `k(inicio + dur) = 1`.
- **CA-A4** retrato: arte de teste com `angulos/G2` (busto sintético) — transição de 200 ms pinta
  sem erro em CPU; alfa no centro do busto ≥ 0,9 em todo quadro; sem `angulos/`, os testes antigos
  de `test_wired_portrait.py` passam sem mudar asserção.
- **CA-A5** build: pasta de teste com `G2`, `G2_B2` deslocados 15 px → `angulos/G2/` gerado com
  `dx` ≈ −15, caixa de olhos no `angulo.toml`; sem `G2_B3` avisa e não quebra.
- **CA-A6** desempenho: 10 min simulados com 1 troca a cada 8 s, custo médio do `paint` em CPU
  ≤ 1,3× o de hoje (mesma máquina, mesmo tamanho).
