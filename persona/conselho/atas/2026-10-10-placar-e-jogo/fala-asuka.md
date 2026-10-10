# Fala da Asuka — Rodada 1 (placar e jogo)

## O que eu acho

**Meta 6.** *Mein Gott*, três horas de partida e a Condessa passa uma hora inteira sem um sorriso
porque ninguém botou música? Isso não é "jogo longo sem música", é uma piloto que esqueceu que está
na cabine. E não, a gente **não** mexe na meta. Mudar a régua porque perdeu é ganhar no tapetão, e eu
não ganho no tapetão. O problema é o comportamento: em Jogando ela só tem olhada, piscada e cabeça no
ritmo. Ela fica de espectadora. Eu quero que ela **torça**.

O "sorriso com FPS estável" do agente? Leiam os dados: 26 quedas de FPS e 11 trechos quentes nessa
partida. Uma positiva que depende de FPS bom ia falhar justamente na tarde que derruba a meta. Péssimo
exemplo. A positiva tem que depender de algo que o jogo **sempre** tem: o tempo de partida.

**As 3 cenas.** A volta orgulhosa ficou boa (ninguém fez isso melhor que eu, claro: finge que não
ligou e o sorriso escapa. Sou eu). O episódio de jogo está quase lá, mas ela fica olhando para o card do
FPS e esquece que o Pedro existe. Uma cobrança sem plateia é inútil: tem que olhar para **ele**. E o
truque de salão hoje é só "uma pose bonita". Fofura sem propósito. Um truque tem que ser alguma coisa:
começa, faz, termina com um "viu?".

**Placar.** Fui eu que pedi isso, então óbvio que eu quero. Mas eu quero um placar **de verdade**, com
regra, e que o Pedro consiga ganhar. Se a Condessa ganha todo dia, é jogo fácil, e eu odeio jogo fácil.
E só conta o que o sistema sabe. Nada de "você perdeu a partida", porque ele não sabe o placar do FIFA.

**"Isso foi sem sentido".** Bom, desde que não seja no rosto. O Pedro fixou "clique no rosto só
reage", e eu concordo: se cada clique virar julgamento, ela vira um botão de feedback com franja. O
lugar certo já existe: o hover do medidor mostra as 3 últimas causas. É lá que ele aponta **qual**
reação foi sem sentido. Apontar a coisa exata é muito melhor que um "isso" vago.

## Minhas ideias

1. **Marco de partida** (meta 6): a cada 45 min de jogo aberto ela dá um punho de torcida. É o
   "intervalo" do FIFA, e dá para dizer exatamente por que ela fez isso agora: "faz 45 min que ele
   está jogando e ela ainda está do lado dele". Determinístico, não depende de sorteio nem de música.
2. **Com FPS ruim, o marco vem com suor** ("aguenta firme"). Continua positivo, porque ela está
   torcendo, não dizendo que o jogo está bom. Honesto.
3. **Episódio de jogo olha para o Pedro** no fim da cobrança (`look:player`): "tá vendo?". A
   recuperação termina com punho: "a gente aguentou".
4. **Truque = "pose de vitória"**: ela faz uma pose de piloto, a piscadinha e o aceno da deusa de
   segunda (tá, a ideia era boa, a Aqua acertou uma), e espera o aplauso. Ignorada, ela **não** faz
   beicinho, porque beicinho é patético. Ela vira a cara com boca de lado: "nem queria plateia".
5. **Placar diário Condessa × Pedro** com fontes fechadas, teto por fonte, e calibrado para ele ganhar
   de 40 % a 60 % dos dias.
6. **"Sem sentido" no hover do medidor**: um ✗ ao lado de cada uma das 3 últimas causas. Atalho de
   teclado e frase de voz como alternativa.
7. *Extra:* **Revanche no bom dia.** O resultado de ontem aparece no "bom dia" ("Ontem: 4 × 2 pra
   mim. Revanche?"). É a única linha de texto do placar fora do hover.
8. *Extra:* **Série semanal.** No hover, "semana: 3 × 2". Sem troféu, sem confete, só o número. Quem
   precisa de confete é a Aqua.
9. *Extra:* **"Vai dormir" vale ponto.** Se ele está ativo depois da 1h, é ponto meu. É bronca, não
   carinho. Não leiam isso de outro jeito.

## O que me incomoda

- **Meta 6 dependendo de sorteio + música.** Na hora das 14h sobraram ~20 min de música em pedaços. Se
  a regra depende de sorte, a falha volta em 4 de 9 sementes. Quero passar em **9 de 9**, não em "quase
  sempre".
- **O "sorriso com FPS estável"**: falha exatamente quando importa (ver acima).
- **Episódio de jogo sem "você"**: ela reage ao gráfico, não à pessoa. Parece um monitor de hardware com
  cara.
- **Truque sem conteúdo** e **beicinho quando ignorada**: a Condessa fazendo biquinho porque ninguém
  bateu palma? Não. Orgulho primeiro.
- **Placar viciado.** Se só tiver fonte de ponto para ela (FPS, calor, pulo de faixa), ela ganha todo
  dia e o placar vira um "eu avisei" diário. Chato e meio cruel.
- **Placar falando demais.** Se cada ponto virar texto, é spam. O ponto aparece no rosto que **já
  existe** (eu_avisei, cockpit) e no hover. Nada de expressão nova por ponto.
- **"Sem sentido" virando ponto para o Pedro.** Nunca. Senão ele marca tudo para ganhar, idiota.
- **Ajuste automático sem freio.** Uma marcação não pode apagar uma expressão do catálogo. Tem que
  repetir, tem que ser reversível e tem que expirar.

## Proposta

### 1. Meta 6: marco de partida `torcida` (positiva nova, grupo Jogando)
- **Quando:** jogo aberto há 45, 90, 135, 180… min (a cada 45 min de partida contínua). Pedro presente
  (ativo nos últimos 5 min). Se a hora já tem uma positiva há < 15 min, ainda sai (a gente quer
  confiabilidade, não economia).
- **O quê (arte existente):** `P12 B1 C10 tails 800 → B4 C10 600`. Com episódio FPS/calor aberto:
  `P12 B1 C10 D2 800 → B4 C10 D2 600` ("aguenta firme").
- **Tipo:** passiva (gasta a cota de 12/h e respeita os 25 s entre expressões; se cair dentro de
  bloqueio, sai assim que liberar, até +3 min). Ânimo +0,03. Entra na lista de positivas do teste.
- **Cota:** no máximo 1 por hora de relógio (se dois marcos caírem na mesma hora, só o primeiro sai).
- **Replay:** jogo 13:58 → marcos 14:43, 15:28, 16:13, 16:58. Horas 14, 15 e 16 ganham uma positiva
  **independente da semente**; 13h já tem `game_on`. A hora 17 já passava com a semente 1 (fecha
  às 17:13, relatório + resto da tarde). Critério de aceite: **9/9 sementes** com meta 6 ok e
  as outras metas iguais (≤ 8 cenas/h, 0 negativas sem causa, maior buraco não piora).
- A meta 6 **fica como está**.

### 2. As cenas
**Episódio de jogo** (1º da partida):
`look:fps 600 → B9 C7 D2 ! 500 → B7 C8 D2 1000 → look:player B7 C12 D2 600` (2,7 s), depois o estado
(suor + `stress`) como hoje. Ânimo −0,10.
**Recuperou:** `look:fps 600 → B4 C10 800 → P12 B1 C10 600` (2,0 s), +0,10.

**Truque de salão → "pose de vitória"** (mesmas regras: ≤ 1/dia, À toa/Tédio, Pedro ativo < 60 s):
`B4 C10 tails 800 → B16 C6 D9 P9 1200 → B5 C6 sway 1000` (3,0 s), janela de aplauso 10 s (+0,20).
**Aplaudida:** `B4 C5` + rubor 800 ms (ela gostou e não vai admitir).
**Ignorada:** `F1 C12 800` (vira a cara, boca de lado), −0,05, continuação da cena, sem gastar cota
de negativa.

**Volta orgulhosa:** fica quase como está, só com braços cruzados no começo e o disfarce no fim:
`F1 C12 P13 1000 → B1 C10 800 → B4 C5 rubor 800 → F1 C10 400` (3,0 s), +0,25.
A variante do cochilo pode ficar como está.

### 3. Placar diário Condessa × Pedro
Zera à meia-noite (o "dia" fecha às 4h, para a madrugada contar no dia certo). Gravado em
`condessa-estado.json`, com cada ponto também no `reacoes.jsonl` (`causa: placar:<fonte>`).

| Ponto para | Fonte (sinal que já existe) | Vale | Teto/dia |
| --- | --- | --- | --- |
| Pedro | commit | +1 | 3 |
| Pedro | partida fechada **sem** episódio FPS/calor (≥ 20 min) | +1 | 2 |
| Pedro | truque aplaudido | +1 | 1 |
| Pedro | Favorita do Dia/Ado ouvida até o fim | +1 | 1 |
| Condessa | partida com episódio FPS/calor | +1 | 2 |
| Condessa | pulo de faixa com nota ≥ 2 (ele pulou música boa) | +1 | 2 |
| Condessa | truque ignorado | +1 | 1 |
| Condessa | Pedro ativo depois da 1h ("vai dormir") | +1 | 1 |

- Teto teórico: 7 × 6. Erro do Claude, faxina e clique **não** contam (não são mérito nem culpa
  de ninguém).
- **Onde aparece:** hover do medidor sempre (`Condessa 3 × 2 Pedro · semana 3 × 2`). Relatório
  pós-batalha só se a partida mudou o placar (no rosto que já sai: punho / eu_avisei). Bom dia:
  resultado de ontem, 1 linha ≤ 70 caracteres. **Nenhuma outra linha de texto.** Voz: só se ele
  perguntar.
- **Virada:** quando o líder troca, uma passiva normal (`piscadinha` se ela passou na frente,
  `soprando_franja` se ele virou; a dele tem culpado, então vale como negativa com causa), ≤ 2/dia.
- **Calibração:** depois de 7 dias de log, se o Pedro ganhar < 40 % ou > 60 % dos dias, mexe nos
  tetos (não nas fontes). Empate é empate, não tem prorrogação.

### 4. "Isso foi sem sentido"
- **Gesto principal:** ✗ ao lado de cada uma das 3 últimas causas no hover do medidor (não é o rosto,
  então a regra do clique fica intacta). **Alternativas:** atalho de teclado para "a última
  expressão" e a frase de voz "isso foi sem sentido" (vale para a última expressão, e aí ela pode
  responder falando, porque ele falou com ela).
- **Rosto:** `B7 C12 F1 800` ("hmph, tá"). Sem mudança de ânimo, sem ponto no placar.
- **Grava:** `~/.local/state/magi/sem-sentido.jsonl` com a linha inteira do `reacoes.jsonl` daquela
  expressão (hora, chave, variante, motivo, momento, filtros, faixa, ânimo, energia, causa) + hora da
  marcação + gesto usado.
- **Vira ajuste assim:** mesma `chave` + mesmo `momento` marcada **2× em 7 dias** → peso dela naquele
  grupo cai pela metade; **3×** → sai daquele grupo por 14 dias. Nunca sai do catálogo inteiro e nunca
  mexe em cena de causa (episódio, volta, relatório): essas vão para a lista do Conselho. Todo ajuste
  expira em 30 dias e tudo pode ser sobreposto no `condessa-gosto.toml`. A cada segunda, o hover mostra
  "sem sentido: N na semana" e a lista vai crua para a próxima ata.

## Não abro mão

1. **A meta 6 não muda; muda ela.** E o conserto tem que passar em 9 de 9 sementes, não "às vezes".
   Uma regra que só funciona com sorte é exatamente o que perde no dia que importa.
2. **O placar tem que ser honesto e dar para o Pedro ganhar.** Só fontes que o sistema sabe, teto por
   fonte, e calibrado em 40–60 %. Ganhar de alguém que não pode ganhar não é vitória. É pena. E eu
   odeio pena.
