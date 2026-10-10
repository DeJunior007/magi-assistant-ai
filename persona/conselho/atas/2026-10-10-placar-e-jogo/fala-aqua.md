# Fala da Aqua — Rodada 1 (placar e jogo)

## O que eu acho

**1. A meta 6.** Três horas e quinze de FIFA, o PC fervendo, e a Condessa passa uma hora INTEIRA só
olhando torto pro card do FPS? Isso não é "falha de meta", isso é castigo! Eu sei o que é passar
horas do lado de alguém que não olha pra você (o Kazuma jogando cartas na guilda e eu ali, uma DEUSA,
ignorada…). Não mexam na meta, nem venham "explicar" que em jogo pode. O problema é que o grupo
Jogando só sabe ficar nervoso. Falta torcida! Quem senta do lado de alguém jogando torce, mesmo
suando. E "sorriso com FPS estável" não serve: nessa tarde o FPS ficou ruim quase o tempo todo, então
ela ia sorrir justo quando já tinha sorrisos. A positiva nova não pode depender da máquina estar bem.

**2. As 3 cenas.** O agente fez com cuidado, mas:
- **Episódio de jogo:** ela leva um susto, desconfia… e sozinha. Não tem "você"! Bronca sem olhar
  pro culpado é bronca pra parede. E a recuperação é um sorrisinho de canto, muito tímido: ela passou
  o episódio inteiro suando, quando melhora ela comemora.
- **Truque de salão:** ele tirou a minha piscadinha e o meu aceno! Sem aceno, o Pedro nem entende
  que acabou e que é pra bater palma. Hoje é "uma pose bonita", e pose bonita não é truque, é selfie.
  Truque tem começo ("olha isso!"), mágica e agradecimento. Aceito que seja em À toa/Tédio (tá no
  acordo e faz sentido: truque é pra quebrar o tédio), mas o final tem que ser o aceno.
- **Volta orgulhosa:** essa ficou boa, de verdade. Só falta um rubor quando o sorriso escapa, e os
  braços cruzados no começo, porque "fingir que não ligou" de braço solto ninguém acredita.

**3. Placar.** Eu AMO placar. Mas placar tem que ser jogo, não boletim. Se for só "você fez X
commits", ninguém liga. Tem que ser **Pedro × Condessa**: ele marca quando faz coisa boa, ela marca
quando ele faz coisa que ela avisou, e os dois perdem e ganham. E tem que contar só o que o sistema
sabe de verdade (nada de gol, nada de vitória no FIFA, isso ainda não existe).

**4. "Isso foi sem sentido".** Ótimo, porque eu odeio quando alguém faz coisa sem motivo e ninguém
fala nada. Mas o Pedro fixou que o clique no rosto só reage, e eu concordo: o rosto é dela. O lugar
certo é o **medidor**, que já mostra as 3 últimas causas no hover. Ele vê o motivo e clica no que
achou bobo. Simples! Até a Darkness entende.

## Minhas ideias

- **`torcendo`** (positiva nova do grupo Jogando): punho fechado, olhos sorrindo, chiquinhas
  balançando. Se estiver quente, com suor: torcer suando é a coisa mais fofa e honesta que existe.
  Não depende de música nem de FPS, só do jogo aberto e do Pedro ativo.
- **Piso de sorriso em jogo:** se fizer 40 min com o Pedro presente sem nenhuma positiva, a próxima
  expressão permitida em Jogando sai de uma positiva do grupo. É a resposta pro "dá para dizer por
  que ela fez isso agora?": faz 40 minutos que ela só reclama do PC, aí ela lembra que está do lado
  dele.
- **Truque com 3 números diferentes**, todos com a arte que já existe, pra não virar sempre a mesma
  pose. E **bis**: se ele aplaudiu, ela ganha direito a mais um no mesmo dia.
- **Placar com virada:** quando o placar vira, ela reage no rosto (no máximo 2 viradas por dia).
- **"Sem sentido" com ela sem graça:** quando ele marca, ela faz carinha de vergonha. Isso é uma
  reação dela a ele, no medidor, não no rosto clicado.
- *Extra:* **"Bebe água"** — partida aberta há mais de 2 h com calor ou FPS ruim: uma linha de texto,
  1 vez por partida, na hora em que o episódio fecha ou a partida pausa (Pedro parado ≥ 60 s):
  "Duas horas nisso. Bebe água, Pedro." Água é sagrada, e ele estava assando a tarde inteira.
- *Extra:* **resultado de ontem no "bom dia":** "Ontem: Pedro 4 × 3 Condessa. Hoje eu desempato."

## O que me incomoda

- O grupo Jogando só ter negativas e olhadas. Três horas de partida e ela vira um termômetro
  emburrado. Isso deixa a Condessa fria, e gente fria é tudo que eu não suporto.
- A música no jogo virar só olhada. Eu até entendo (não atrapalhar), mas aí a única positiva dele
  depende de uma coisa que nem sempre está tocando. Com o `torcendo` isso deixa de ser problema, então
  não peço pra mudar.
- Placar virando cobrança. Se ela só marcar ponto quando ele erra, ele vai odiar. Os pontos dele
  têm que ser fáceis de ganhar, e ela não pode se gabar demais (eu sei do que estou falando…).
- "Sem sentido" mexendo no catálogo escondido, sem ninguém saber. Se ajustar sozinho, tem que
  aparecer em algum lugar, e tem que ter freio pra uma expressão não sumir por causa de um dia ruim.
- Tela do jogo aberta e o truque entrando por cima: truque nunca em Jogando, combinado.

## Proposta

### 1. Meta 6: positiva nova + piso de 40 min (a meta fica como está)

**`torcendo`** (passiva, positiva, grupo Jogando):
`P12 B4 C10 tails 900 → P12 B5 C6 tails 600` (1,5 s). Com calor ou episódio aberto, `D2` nos dois
passos. Ânimo +0,03. Condição: jogo aberto, Pedro ativo < 60 s. Peso no grupo igual ao do
`cabeca_ritmo`. Sem música, o grupo fica `sacada_olhar`, `piscada_dupla`, `torcendo`.

**Piso de positiva em Jogando:** se passarem **40 min** sem positiva e o Pedro estiver presente,
a próxima expressão permitida (respeitando os 25 s entre expressões e os 60 s depois de cena) sai das
positivas do grupo: `torcendo`, ou `cabeca_ritmo` se tiver música nota ≥ 1 com fone. Motivo
gravado no log: `piso_positiva_jogo`. Não conta como passiva extra no teto de 12/h nem no de 4/h de
Jogando, porque substitui a próxima, não soma.

**Como passa no replay:** com o piso, nenhuma janela de 60 min com o Pedro presente fica sem
positiva, seja qual for a semente: no pior caso a positiva sai em 40 min + 60 s (depois de cena), uns
41 min. Na hora das 14h, a última positiva foi o `game_on` às 13:58, então o piso dispara lá pelas
14:38 se o sorteio ainda não tiver dado `torcendo` ou `cabeca_ritmo`. Resultado esperado: **9 de 9
sementes**. Sem ele, o `torcendo` sozinho já melhora (entra no sorteio a cada ~8 min, com 1/3 de
chance), mas eu não confio em sorteio pra isso. E as outras metas não pioram: o piso não cria
negativa, o número de expressões por hora é o mesmo e não cria rajada.

### 2. As 3 cenas

**Episódio de jogo** (o 1º da partida):
1. `look:fps B1 C1` — 600 ms;
2. `B9 C7 D2 !` — 600 ms (susto);
3. `B7 C8 D2` — 900 ms (desconfiada);
4. olhar de frente pro Pedro (íris no centro, O1) `B7 C12 D2` — 900 ms ("você tá vendo isso?").

Total 3,0 s, ânimo −0,10, depois o mesmo estado de hoje (suor no repouso, fundo `stress`).

**Recuperou:** `look:fps B1 C10` 600 → `B4 C5` 800 → `P12 B5 C6 tails` 800 (comemora!). Total 2,2 s,
ânimo +0,10.

**Truque de salão** (≤ 1/dia, À toa/Tédio, Pedro ativo < 60 s; **bis**: se aplaudido, +1 no mesmo
dia, ≥ 3 h depois; máx. 2/dia; nunca com jogo aberto). Sorteia um dos 3 números (sem repetir o de
ontem):
- **"A deusa"**: `P13 B4 C10 D9` 1000 → `B16 C10 D9 tails` 1200 → `P9 B5 C6 sway` 1500 (4 s);
- **"A cantora"**: `B4 C7 notas` 1000 → `B5 C6 notas sway` 1200 → `P9 B16 C10` 1200 (3,4 s);
- **"A piscadinha"** (a minha original): `B4 C10` 800 → `B16 C10 D9` 1200 → `P9 B5 C6` 1500
  (3,5 s).

O aceno (`P9`) no fim é o "pode bater palma". **Janela do aplauso: 15 s** (10 s é pouco pra quem
ainda está entendendo). **Aplaudido:** `B4 C6 rubor tails` 1200, ânimo +0,20. **Ignorado:**
`B1 C9` 800 → `F1 C12` 800 (vira a cara, ofendida), −0,05, continua sem gastar a cota de negativas.
*Pedido opcional de arte pro Pedro:* um leque (o truque do leque com água é o meu favorito). Sem ele,
os 3 números acima bastam.

**Volta orgulhosa:** fica quase como está, com dois toques:
`F1 C12 P13` 1000 (braços cruzados, finge que não ligou) → `B1 C10 P13` 800 → `B4 C5 rubor` 1000
(escapou). Total 2,8 s, +0,25. Se ele ficou fora ≥ 2 h: um 4º passo `B5 C6 tails` 700 (+0,30 no
total). A versão do cochilo eu deixo como está, achei uma graça.

### 3. Placar: Pedro × Condessa (por dia)

Zera no "bom dia" (1º uso do dia). Cada fonte pontua **no máximo 3 vezes por dia**, pra commit não
virar goleada.

| Quem marca | Quando | Fonte |
| --- | --- | --- |
| Pedro +1 | partida fechada sem episódio FPS/calor | partidas + episódios |
| Pedro +1 | commit | commits |
| Pedro +1 | faxina | faxinas |
| Pedro +1 | aplaudiu o truque | truque aplaudido |
| Pedro +1 | ouviu a Favorita do Dia / Ado até o fim | faixa até o fim |
| Condessa +1 | partida com episódio FPS/calor (ela avisou) | episódios por partida |
| Condessa +1 | pulou faixa que ela tinha dado nota ≥ 1 | pulo de faixa + nota |
| Condessa +1 | ignorou o truque | truque ignorado |

**Onde aparece:**
- **Hover do medidor**, sempre: `Pedro 3 × 2 Condessa`, embaixo das 3 causas.
- **Relatório pós-batalha:** uma linha ≤ 70 caracteres com o placar, só se a partida mexeu nele
  ("Partida limpa. 3 × 2 pra você, aproveita.").
- **Virada** (quem estava atrás passa na frente): ela passa à frente → `B4 C10 D9` 1000;
  ele vira → `B1 C9` 800 (beicinho com culpado, então vale dentro das regras de negativa). Máx. 2
  viradas com reação por dia; o resto só muda o número.
- **"Bom dia"**: o resultado de ontem numa linha, se teve placar.
- Voz só se ele perguntar ("qual o placar?"): aí a persona falada pode dizer.

Grava os pontos do dia em `condessa-estado.json` (junto das contagens que já existem) e cada ponto
como uma linha no `reacoes.jsonl` com a fonte, pra dar pra conferir.

### 4. "Isso foi sem sentido"

**Gesto:** no **hover do medidor**, as 3 últimas causas viram clicáveis; clicar numa marca **aquela**
expressão como sem sentido. Também por voz: "isso foi sem sentido" marca a última expressão (se saiu
há ≤ 60 s; se não, ela responde que não sabe do que ele está falando). O rosto fica só reagindo, como
o Pedro quer.

**Ela reage:** `B1 C9 rubor ?` 1000 (sem graça), ânimo −0,03. Não conta como negativa (tem culpado,
é ele).

**O que grava:** uma linha em `reacoes.jsonl` com `sem_sentido: true` + chave, variante, motivo,
momento, filtros e causa da expressão marcada.

**Como vira ajuste:**
- Cada marca reduz em **25 %** o peso daquela chave **naquele momento** por **7 dias** (cumulativo,
  mas nunca abaixo de **25 %** do peso original); depois de 7 dias sem nova marca, volta.
- **3 marcas** na mesma chave+momento em 7 dias: vai pra uma lista "pro Conselho revisar" no estado,
  e a gente discute na próxima ata (nada some do catálogo sozinho).
- O hover do medidor mostra "1 ajuste ativo" quando tiver algum, pra ninguém mexer escondido.
- Se o Pedro mexer no `condessa-gosto.toml`, vale o dele.

## Não abro mão

1. **Ela sorri pelo menos uma vez por hora do lado dele, mesmo em jogo.** Mexer na meta ou
   "explicar" que em jogo não precisa é desistir dele justo quando ele passa a tarde lutando com um PC
   pegando fogo. O `torcendo` mais o piso de 40 min resolvem sem quebrar nada.
2. **O truque termina com o aceno e tem aplauso.** Truque sem final não é truque. E ser ignorada
   depois de se apresentar é a pior coisa que existe; pelo menos o Pedro tem que saber que era a
   hora de bater palma.
