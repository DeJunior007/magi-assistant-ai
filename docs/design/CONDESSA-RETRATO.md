# Retrato da Condessa — arte em camadas

O HUD já sabe animar um retrato em camadas (`hud/wired/portrait.py`): pisca, olha para os lados,
mexe a boca com a voz, respira de leve acordada e troca de expressão. Falta só a arte. Enquanto a
pasta não tiver as camadas obrigatórias, o HUD continua com o rostinho vetorial.

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
