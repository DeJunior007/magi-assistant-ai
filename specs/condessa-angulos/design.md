# Design — Ângulos do retrato da Condessa

Implementa [requirements.md](requirements.md). Seções citadas por `§`.

## 1. Onde mora hoje

```
~/Downloads/Condessa/<ID>.jpg ──condessa_build.py──▶ ~/.local/share/magi/condessa/{parts,eyes,mouth,extra}/ + portrait.toml
PartsAssets(pasta) ──▶ PartsPortrait.tick/paint (por quadro) ──▶ CPU (QPainter) ou GPU (portrait_gl → QImage)
Reactor.active(now) ──Reaction (1 rosto: eyes, mouth, look, efeitos, corpo)──▶ PartsPortrait.react
```
- `hud/tools/condessa_build.py`: tudo no quadro de 1024 (`SIZE`), recorte pelo verde (`chroma`,
  `despill`, `defringe`), remendos de olhos/boca pela região fixa (`EYES_BOX`, `MOUTH_BOX`) ou pela
  diferença com a A1 (`diff_mask`, `detail`), alinhamento de silhuetas por `best_shift`.
- `hud/wired/portrait.py`: `paint` monta as partes com `xform` (inclinação a partir de
  `NECK_PIVOT`, respiração, balanço `sway`, cabeça `_head`), fundo por `_backdrop`, efeitos por
  `_reaction_effect`; extras de passo lidos por `_extra(r, nome)` (`bob`, `sway`, `tails`, `braco:`,
  `iris:`).
- `LOOK_DIRS` (`reactions.py`): painel → `left`/`right`/`up_right`/`down_left`/… por tela.

## 2. Princípio: o ângulo é um "rosto plano com vida", a frente continua em partes

Montar cada ângulo em partes (cabelo, braços, corpo) multiplicaria a arte por 16. Na fase mínima,
um ângulo é **um busto inteiro** + remendos de olhos (piscar) e, depois, de boca (falar). A vida
que sobra nele é a que não precisa de partes: respiração (deslocamento vertical de 2 px e escala
de 0,4% no peito, aplicada ao busto todo), balanço lento, fundo, rim light na GPU e efeitos. A
frente (`G1`) é sempre o `PartsPortrait` de hoje, intocado. A ilusão de giro vem da **transição**
(§4 do spec), não da arte.

## 3. Peças

| Arquivo | Papel | Dono |
| --- | --- | --- |
| `hud/wired/angulos.py` (novo, puro) | `Angulo` (dados do `angulo.toml`), `carregar(pasta) -> dict[str, Angulo]`, `Seletor` (regras do spec §3, relógio injetado), `Transicao` (curvas do spec §4: opacidades, deslocamento, escala por `k`), `pedido(reaction) -> str | None` (`corpo` `angulo:<ID>`) | A0.1, A1.1 |
| `hud/wired/portrait.py` | `PartsAssets.angulos` (lazy); `PartsPortrait.angulo` + `_paint_angulo` + mistura na transição | A1.2 |
| `hud/tools/condessa_build.py` | `build_angulos(src, out, base)`: `angulos/<ID>/base.png`, `eyes/`, `mouth/`, `angulo.toml` | A1.3 |
| `docs/design/CONDESSA-RETRATO.md` | seção "Ângulos (G*)" com a tabela de imagens a gerar (spec §6) | A0.2 |

## 4. Fluxo de um quadro

1. `tick(now)`: `Seletor.escolher(agora, estado, reacao, disponiveis)` → ID desejado. Se mudou e
   não há transição em curso, começa `Transicao(de, para, inicio, dur, sentido)`.
2. `paint`: sem ângulo e sem transição → caminho de hoje (nenhum custo novo). Em ângulo parado →
   `_paint_angulo(p, ang, now)`: fundo, busto com respiração/balanço, olhos do piscar (mesmo
   `eye_frame` do `Mascot`), efeitos. Em transição → desenha o lado "de" e o lado "para" cada um
   num `QPixmap` do tamanho do dispositivo (o da frente pelo `paint` normal com `fundo=False`
   num pintor fora da tela) e mistura conforme o spec §4; o fundo é desenhado uma vez, por baixo.
3. FPS: transição a 60 fps (`_fast` devolve verdadeiro); ângulo parado segue o FPS de parada (40).

## 5. Seletor (por que puro)

As regras de quando girar (lado do `look`, pensando, fala volta à frente, tetos) são a parte que
mais vai mudar depois da semana de uso. Ficam em `angulos.Seletor`, testáveis sem Qt, e o retrato
só pergunta "qual ângulo agora?". Reações do catálogo podem pedir ângulo explícito pelo `corpo`
(`angulo:G9`), sem tocar no contrato `Passo`/`Reaction` (é só mais um texto em `corpo`).

## 6. Convivência

- **Reações (`specs/condessa-reacoes/`):** contrato do retrato igual; o seletor só lê `look` e
  `corpo` da `Reaction` ativa. Extras de braço (`braco:P*`) e íris (`iris:`) só valem em `G1`; com
  eles no passo, o seletor fica em `G1`.
- **Vida (`specs/condessa-vida/`, V0.4 `set_rest`):** a V0.4 também mexe no `paint`. A A1.2 vem
  **depois** da V0.4 no `main` (o orquestrador garante) e só acrescenta ramos novos.
- **Overlay (`specs/condessa-overlay/`):** usa o mesmo `PartsPortrait`; nada a fazer além de a
  máscara de entrada ser recalculada ao fim de cada transição (O1.3 já recalcula ao mudar a pose).

## 7. Riscos

| Risco | Mitigação |
| --- | --- |
| Arte de ângulo não casa com a frente (cor, tamanho, altura dos ombros) | alinhamento pela faixa dos ombros no build (spec §5); prompts com "same framing, shoulders at the same height"; prancha de conferência (`portrait_check`) por ângulo |
| "Troca de foto" em vez de giro | transição em duas metades + deslocamento/escala no sentido do giro (spec §4); A3.2 ajusta números com o Pedro |
| CPU na transição (dois pixmaps por quadro) | só durante ≤ 260 ms; pixmap do ângulo parado em cache por (ID, olhos, tamanho) |
| Piscar ausente deixa o ângulo "morto" | R5: sem B2/B3, máximo 2,5 s no ângulo |
| Muitos giros cansam | `Seletor`: mínimo 8 s entre giros, teto 6/min, R9 desliga |
