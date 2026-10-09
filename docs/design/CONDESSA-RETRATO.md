# Retrato da Condessa — arte em camadas

O HUD já sabe animar um retrato em camadas (`hud/wired/portrait.py`): pisca, olha para os lados,
mexe a boca com a voz, respira de leve acordada e troca de expressão. Falta só a arte. Enquanto a
pasta não tiver as camadas obrigatórias, o HUD continua com o rostinho vetorial.

## Montagem atual (2.5D em partes)

```
python3 hud/tools/condessa_build.py ~/Downloads/Condessa      # gera ~/.local/share/magi/condessa
```

Lê as imagens nomeadas pelo ID da checklist (fundo verde, qualquer tamanho quadrado), recorta pelo
verde, gera as partes (cabelo de trás, marias-chiquinhas, braços, corpo, cabeça até a gola, franja),
os remendos de olhos e bocas e o fone, e um `portrait.toml` com `mode = "parts"` (estado → olhos,
boca e piscada; fala pelo volume; olhares). O HUD usa `wired.portrait.PartsPortrait`: respiração,
cabelo em pêndulo, olhar com parallax e efeitos em código (rubor, zz, ?, !). Reabra o HUD depois de
remontar.

## Arte nova das reações (R3.1) — o que falta gerar

O código já aceita estes IDs; basta pôr a imagem na pasta de origem (`~/Downloads/Condessa`) com o
nome `<ID>.png` (ou `.jpg`/`.webp`, maiúsculo ou minúsculo), fundo verde, mesmo enquadramento da A1,
e rodar o `condessa_build.py` de novo. Cada um é opcional: sem ele o efeito continua desenhado em
código (D*), o braço da reação não aparece (P*) e o fone some (E3). Pode ser **só o detalhe** no
verde ou o **busto inteiro com o detalhe** (inpainting): se a imagem cobrir mais de 60% do busto da
A1, o build guarda só o que difere da A1.

**Decisão do Pedro (2026-10-09): os detalhes D1–D9 ficam em código**, porque a animação própria (zz subindo, notas flutuando, lágrima escorrendo) se perde com um PNG parado. O build continua aceitando `D*.png`, mas não é para gerar.

| Prio | ID | O que é | Arquivo de origem | Gera |
| --- | --- | --- | --- | --- |
| 1 | E3 | fone no pescoço (tirando o fone) | `E3.png` | `extra/E3.png` |
| 1 | B16 | olhos/sobrancelhas novos | `B16.png` | `eyes/B16.png` |
| 2 | P9, P10, P12 | braços das reações (`braco:P*`) | `P9.png` … | `extra/P9.png` … |
| 2 | B17 | olhos/sobrancelhas novos | `B17.png` | `eyes/B17.png` |
| 2 | P13 | braços cruzados — **ativa a I20** | `P13.png` | `extra/P13.png` |
| 3 | P11 | braço da reação | `P11.png` | `extra/P11.png` |

Os efeitos D* são desenhados no quadro inteiro (1024) acompanhando a cabeça, com o mesmo
esmaecer do fim da reação. A I20 (Braços cruzados) entra em `catalogo.ATIVAS` quando
`extra/P13.png` existe na pasta montada (`~/.local/share/magi/condessa` ou `$MAGI_PORTRAIT_DIR`),
checado ao abrir o HUD: depois do build, reabra o HUD. Remover a imagem de origem e remontar apaga
o `extra/<ID>.png` antigo.

## Lista completa estilo Persona 3 Reload (rosto solo, camadas)

O retrato do P3R é **uma pose só** (busto de frente ou levemente 3/4, enquadramento fixo) e o que
muda são olhos, sobrancelhas e boca por cima, mais detalhes soltos (rubor, suor). A vida vem de
piscar, mexer a boca com a voz, respirar e trocar de expressão — nunca de trocar a pose inteira.

**Como pedir a arte (o jeito mais fácil):** gere a **base** e depois cada variação **na mesma
imagem, mudando só a região** (inpainting de olhos ou de boca, mesma semente/personagem). Me
entregue as imagens **inteiras**, todas do mesmo tamanho e alinhadas; eu extraio as camadas pela
diferença com a base. Quadro sugerido: **1200 × 900**, fundo liso ou transparente, cabeça ocupando
~50% da altura, nada cortado nas laterais (cabelo inteiro dentro do quadro).

### A. Base (1)
| Arquivo | O que é |
| --- | --- |
| `base` | busto neutro, olhos abertos e boca fechada (é a referência de todas as outras) |

### B. Olhos + sobrancelhas (cada linha = um conjunto; piscar precisa de aberto, meio e fechado)
| Conjunto | aberto | meio | fechado | Uso |
| --- | --- | --- | --- | --- |
| neutro | ✔ | ✔ | ✔ | ouvindo, falando, padrão |
| feliz (olhos sorrindo, sobrancelha relaxada) | ✔ | – | ✔ (arco "^ ^") | feliz |
| sério (sobrancelha baixa, olhar firme) | ✔ | ✔ | ✔ | alerta |
| surpresa (olhos arregalados, sobrancelha alta) | ✔ | – | – | confusa/susto (pisca usando o fechado neutro) |
| preocupada (sobrancelhas inclinadas para cima no meio) | ✔ | ✔ | ✔ | confusa, "não peguei" |
| pensativa (olhar para cima/lado) | ✔ | – | – | pensando |
| sonolenta (pálpebra a meio) | ✔ | – | ✔ | dormindo |
| olhar à esquerda / à direita (neutro, só íris) | ✔ / ✔ | – | – | olhares quando parada |

### C. Boca
| Arquivo | Uso |
| --- | --- |
| fechada neutra | parada, falando em silêncio |
| entreaberta | fala baixa (sílabas fracas) |
| aberta | fala alta |
| bem aberta | opcional: fala animada/gritinho |
| sorriso fechado | feliz parada |
| sorriso aberto | feliz falando / risada |
| "o" pequeno | surpresa, pensando |
| linha reta / bico | séria, emburrada |
| sorriso de canto | zoeira (humor alto) |

### D. Detalhes por cima (PNG só com o detalhe)
rubor nas bochechas · gota de suor · "zz" · "?" · "!" · (opcional) lágrima, veia de raiva.

### E. Opcional (mais vida, estilo P3R)
- **cabelo da frente separado** (mechas que balançam de leve) e **cabelo de trás** — dá o
  balanço sutil do P3R;
- **cabeça levemente inclinada** (mesma arte, 3–5°) para "pensando".

### F. Olhares para o HUD (olhos + leve giro de cabeça, mesma pose)
Ela olha para onde algo aconteceu na tela (ver `CONDESSA-PERSONA.md`):
esquerda · esquerda-baixo · direita-cima · direita-baixo · para cima · para baixo (lendo).
Cada um: olhos abertos e meio (para piscar olhando).

### G. Reações à música (gosto próprio, de −2 a +2)
| Afinidade | Olhos | Boca | Extra |
| --- | --- | --- | --- |
| +2 favorito | fechados curtindo / brilhando | sorriso aberto · cantarolando ("o" pequeno) | notas musicais ♪ · **cabeça balançando: 3 quadros** (centro, inclina esq., inclina dir.) |
| +1 gosta | relaxados, meio fechados | sorriso fechado | — |
| 0 aceita | neutros | neutra | — |
| −1 não é a praia | olhar de lado | "hm" (boca torta) | sobrancelha levantada |
| −2 aversão leve | semicerrados | careta discreta | gota de suor |
| descoberta | arregalados de leve | "o" | "?" pequeno |
| tolerando (favorita do Pedro) | sorriso de olhos | sorriso amarelo | — |

Com fone: **fone de ouvido** como camada separada (ela coloca quando a música começa e curte).

### H. Reações ao HUD/PC
preocupada (temperatura) · concentrada (Claude Code / pensando) · orgulhosa (faxina feita,
"fiz") · sonolenta (sessão longa / madrugada) · surpresa leve (clique no LED) · emburrada leve
(PC travou / jogo caiu — rara e curta).

**Mínimo para funcionar bem:** A + B (neutro com 3, feliz, sério, surpresa, pensativa,
sonolenta) + C (fechada, entreaberta, aberta, sorriso fechado, sorriso aberto, "o") + D (rubor,
"zz") ≈ **20 imagens**. Com F, G e H (olhares, música e HUD) ≈ **45**; tudo, com cabelo
separado, fone e balanço de cabeça, ≈ **55**.

## Atalho: folha de expressões (quadros inteiros)

Em vez de camadas, dá para usar uma **folha N×N de expressões** (rostos inteiros, poses
diferentes):

```
python3 hud/tools/portrait_sheet.py FOLHA.png            # grade 4x4 por padrão
```

Ela recorta a grade, tira o fundo liso (ou só recorta, se a folha já vier transparente — um
removedor de fundo dedicado deixa a borda do cabelo melhor), grava `frames/01.png…16.png` em
`~/.local/share/magi/condessa/` e um `portrait.toml` com `mode = "frames"` e o mapeamento
estado → quadro (fala alterna `[speaking] closed/open`; parada, olha para os lados com
`[idle] glances`; dormindo, cara de sono só das 22 h às 7 h). Edite os números à vontade.

## Onde colocar

`~/.local/share/magi/condessa/` (ou outra pasta em `MAGI_PORTRAIT_DIR`). Depois de copiar,
confira com:

```
uv run python -m hud.tools.portrait_check            # diz o que falta
uv run python -m hud.tools.portrait_check prancha.png  # e salva uma prancha com todos os estados
```

e reabra o HUD (o retrato é carregado ao abrir).

## Quadro

- **Todas as camadas com o mesmo tamanho: 1300 × 750 px**, PNG com fundo transparente.
  A proporção (~1,73:1) é a do espaço do rosto no painel e na tela de espera; outra proporção
  funciona, mas sobra espaço dos lados (ou use `fit = "cover"` no `portrait.toml`).
- **Busto anime**, do peito para cima, de frente ou levemente de 3/4, centrado, com a cabeça
  ocupando ~45% da altura e um pouco de respiro em cima.
- Cada camada fica **no lugar exato** dentro do quadro (sem recortar e reposicionar): olhos e boca
  são desenhados por cima da base nas mesmas coordenadas.

## Camadas

| Arquivo | O que é | |
| --- | --- | --- |
| `base.png` | busto inteiro **sem olhos e sem boca** (pele lisa nesses lugares) | obrigatório |
| `eyes/open.png` | só os olhos abertos (íris, cílios, sobrancelhas) | obrigatório |
| `eyes/half.png` | olhos meio fechados (meio da piscada) | opcional |
| `eyes/closed.png` | olhos fechados (piscada e dormindo) | obrigatório |
| `mouth/closed.png` | boca fechada, neutra | obrigatório |
| `mouth/small.png` | boca entreaberta (fala baixa) | opcional |
| `mouth/open.png` | boca aberta (fala alta) | obrigatório |
| `mouth/<expr>.png` | boca parada de uma expressão (ex.: `happy` sorriso, `alert` "o") | opcional |
| `eyes/<expr>/open.png` etc. | olhos de uma expressão (ex.: `happy` fechadinhos em arco) | opcional |
| `base/<expr>.png` | busto de uma expressão (ex.: `confused` com gota de suor, rubor) | opcional |
| `extra/<expr>.png` | por cima de tudo (ex.: `sleeping` "zz", `confused` "?", `alert` "!") | opcional |

Expressões (`<expr>`): `sleeping`, `listening`, `thinking`, `speaking`, `happy`, `confused`,
`alert`. O mínimo para funcionar são as 5 obrigatórias; cada opcional deixa mais viva.

Sobrancelhas mudam com a expressão: deixe-as na camada de olhos (assim `eyes/confused/open.png`
pode ter sobrancelha franzida).

## Estilo

- Combina com o HUD "wired": roxo apagado (Catppuccin lilás), preto azulado, toque Evangelion /
  Serial Experiments Lain. **Nada de brilho em nuvem**: luz suave, linhas limpas.
- Cabelo escuro (preto arroxeado ou prateado), olhos lilás; roupa simples, gola alta ou fone de
  ouvido com fio (casa com os fios do cenário).
- Traço de anime limpo (cel shading de 2 tons), sem fundo, sem texto.

## Gerando numa IA de imagem

1. **Base**: gere o busto com olhos abertos e boca fechada, fundo transparente (ou chapado para
   recortar). Exemplo de prompt:
   > anime bust portrait of a calm young woman, the "Countess", dark purple hair, lilac eyes,
   > high-collar black outfit with a thin headset cable, cel shading, clean line art, muted
   > lavender and near-black palette, Serial Experiments Lain and Evangelion mood, front view,
   > centered, chest up, plain transparent background, no text, 1300x750 canvas
2. Use **essa imagem como referência** (mesma semente/personagem) e faça as variações por
   *inpainting* só na região dos olhos (abertos, meio, fechados, felizes...) e da boca
   (fechada, entreaberta, aberta, sorriso). Assim tudo fica alinhado.
3. Num editor (Krita, GIMP, Photopea), separe: apague olhos e boca da base (pinte com a pele) e
   salve cada variação só com a região dela, no quadro inteiro, fundo transparente.
4. Rode o `portrait_check` e olhe a prancha.

## Ajustes (`portrait.toml`, opcional)

```toml
gaze_px = 6          # quanto os olhos andam ao olhar para o lado (px do quadro)
breath_px = 2        # sobe-e-desce do busto acordada (0 desliga)
breath_period = 4.5  # segundos por respiração
fit = "contain"      # "cover" preenche o espaço e corta as bordas
```
