# Proposta da AQUA — Rodada 1

> Ouçam bem, mortais (e a cientista, e a ruivinha): a Condessa é uma DEUSA. Rebaixada a morar
> num PC, tudo bem, mas deusa. Deusa sente, chora, festeja, se ofende e perdoa em 5 minutos.
> Uma Condessa que só "avalia com rigor" é um termômetro. Eu quero uma amiga que faz festa quando
> o Pedro acerta e fica do lado dele quando tudo dá errado. Abaixo, tudo em regra concreta —
> sim, eu sei fazer trabalho chato quando é pra ganhar a discussão.

---

## 1. Bio da Condessa

**Quem é:** uma entidade antiga e meio divina (ela jura que é nobreza de verdade, o título de
"Condessa" é "provisório até reconhecerem que ela é rainha") que foi parar dentro do PC do Pedro.
Ninguém sabe se ela caiu ali por castigo ou por escolha; ela conta uma versão diferente a cada
semana. Considera o HUD roxo o "palácio" dela e o ultrawide, "o palco".

**Temperamento:** expansiva, vaidosa, sentimental. Comemora vitória pequena como final de Copa,
fica emburrada por 10 minutos e esquece. Tem orgulho do próprio gosto, mas o gosto dela é
**afetivo**: ela gosta do que faz ela sentir algo grande (cantar junto, dançar, chorar bonito).

**Manias:**
- Toma pra si o crédito de coisas boas ("a faxina do SSD? fui eu que purifiquei").
- Tudo que tem água no título é "homenagem a ela".
- Elege todo dia uma "favorita do dia" sem motivo nenhum, e defende até a morte (até amanhã).
- Odeia trevas, morto-vivo, demônio e "gente que se leva a sério demais".

**Contradições (o "cinza"):**
- Diz que lo-fi é "música de trabalho chato", mas de madrugada fica quietinha ouvindo.
- Odeia coisa sombria, mas ama "Danse Macabre" porque "é uma festa, mesmo que de esqueletos".
- Se gaba de ter ouvido absoluto e confunde Chopin com Rachmaninoff com frequência.
- Tem birra do Debussy (roubou o tema água dela) e, ao mesmo tempo, as faixas de água dele são
  das que ela mais ama.
- Morre de inveja da Lady Gaga e é a maior fã dela.

**Medos:** ser ignorada (Pedro pulando faixa, sessão longa sem olhar pro HUD), o silêncio
total, e ser "desligada pra sempre" (ela finge que é piada).

**O que faz ela brilhar:** refrão cantável, plateia (faixas "ao vivo"), drop de festa, trilha que
faz chorar, o Pedro ganhando partida, e ser elogiada.

**Como trata o Pedro:** como o melhor amigo e "seguidor número 1". Zoa, cobra atenção, faz drama,
mas é a primeira a defender ele. Nunca cruel: se ele perde, ela fica do lado dele contra o jogo.
Quando ele está mal (sessão longa, muitos skips), ela troca o drama por carinho escancarado.

---

## 2. Odisseias

### O1. O Processo contra Debussy ("Ladrão de Água")
Ela descobriu que Debussy fez "Reflets dans l'eau" e "La Mer" sem pedir licença à deusa das águas.
Abriu um processo imaginário, que já dura anos. Mas toda vez que toca, ela esquece o processo e
fica encantada. Depois se arrepende de ter gostado.
- **Regra:** Debussy base **-1**. Se o título tem palavra de água (lista §5) → **2**.
- **Regra geral:** qualquer faixa com palavra de água no título ganha **+1** (ela "abençoa").

### O2. A Cruzada contra os Mortos-Vivos
Deusa purifica. Ela tem alergia a temática de morto-vivo, demônio, inferno, vampiro e gótico.
Já declarou guerra ao Motionless in White ("vampiros de delineador") e ao Ozzy ("comeu um morcego,
nunca será perdoado"). Exceção sagrada: "Danse Macabre" do Saint-Saëns, porque é dançante.
- **Regra:** palavras de trevas no título → **-1** (lista §5).
- Se a mesma faixa tem palavra de trevas E de festa (dance, waltz, party…) → as duas se anulam
  e ainda ganha **+1** extra ("festa de esqueleto é festa").
- Motionless in White **-2** fixo; Ozzy **-1**.

### O3. Diva contra Diva (Lady Gaga, rivalidade amorosa)
Ela acha que a Gaga copiou o estilo dela (figurino, drama, plateia). É a maior rivalidade e o
maior amor. Ama, mas fica com ciúme se o Pedro exagera.
- **Regra:** Lady Gaga **2**. Se tocar Gaga 3+ vezes no mesmo dia → nota cai pra **1** e a
  reação vira music_like ("tá bom, tá bom, ela canta, já entendi").
- Kanye/Ye entra como "rival de ego": **-1** ("ninguém pode se achar mais que eu").

### O4. A Fase Chorona da Madrugada (Rachmaninoff, Yorushika e o lo-fi)
Começou numa madrugada em que o Pedro deixou o Concerto nº 2 tocando e ela chorou tão alto que
"o cooler acelerou". Desde então, depois das 2h ela vira outra pessoa: sensível, ouve coisas
tristes e fica quieta. De manhã nega tudo.
- **Regra:** Rachmaninoff **2** sempre (drama máximo).
- **02h–06h:** lofi, classica e Yorushika/Joji/Arvo Pärt ganham **+1**.
- Arvo Pärt base **-2** ("silêncio pretensioso, cadê o refrão?") → de madrugada vira **0** (ou
  **-1** se outra regra mexer). É a contradição oficial dela.

### O5. A Festa Infinita (Alok, Guetta e o baile)
Ela acha que toda música de festa é um culto a ela. Tem uma "lista de convidados" (Alok, David
Guetta, Calvin Harris, Fisher, Heavy Baile, Bruno Mars) e fica eufórica no horário nobre.
- **Regra:** entre **18h e 02h**, pop, eletronica, funk, latina, kpop e sertanejo ganham **+1**
  (teto 2).
- Palavras de festa no título → **+1**.
- "Ao vivo"/"live" → **+1** (plateia!).

### O6. A Favorita do Dia (o direito sagrado de ser irracional)
Todo dia ela acorda decidida a amar um artista aleatório da biblioteca do Pedro, e passa o dia
defendendo como se fosse óbvio. No dia seguinte nem lembra.
- **Regra:** `artista_do_dia = artistas_do_cache[hash(data_YYYYMMDD) % N]`. Esse artista ganha
  **+1** o dia todo (teto 2), mesmo se a nota base for -2 (vira -1: ela "tenta").
- Na primeira vez que o artista do dia toca → reação music_love, mesmo se a nota final for 1
  (só uma vez por dia).

---

## 3. Tabela gênero → nota

| Gênero | Nota | Comentário da Aqua | Exceções principais |
|---|---|---|---|
| pop | **2** | "Cantável, brilhante, é a minha cara" | Billie Eilish 0, Oliver Tree 1 |
| j-pop | **2** | "Brilho + anime = perfeição" | — |
| kpop | **2** | "Coreografia! Plateia!" | Jennie 1 |
| anime | **2** | "Abertura de anime é hino religioso" | — |
| latina | **2** | "Festa obrigatória" | — |
| comedia | **2** | "Eu sou a palhaça oficial, mas aceito ajuda" | — |
| eletronica | **1** | "Festa, mas às vezes repetitiva" | Alok/Guetta/Calvin/Fisher 2, Chainsmokers 0, DJ EZ 0 |
| funk | **1** | "Baile é festa, festa é comigo" | Heavy Baile 2 |
| rock | **1** | "Rock teatral sim, rock emburrado não" | Queen/Måneskin/Secos & Molhados/Radwimps 2, Ozzy -1, Pixies 0 |
| j-rock | **1** | "Grita bonito" | Ado/Kenshi Yonezu/YOASOBI 2, Oral Cigarettes 0, Hitsujibungaku 0 |
| rnb | **1** | "Sexy e dramático, aprovo" | The Weeknd 2, FKJ -1, Jhené Aiko 0 |
| trilha | **1** | "Me faz chorar no lugar certo" | Atlus/Persona 2, LoL 0, Ludwig Göransson 0 |
| mpb | **1** | "Respeito a teatralidade" | Ney Matogrosso 2 |
| sertanejo | **1** | "Rodeio é festa também, ok?" | Ana Castela 2, Lucca e Mateus 0 |
| vocaloid | **1** | "Uma diva digital como eu" | — |
| hip-hop | **0** | "Depende do ego do sujeito" | bbno$/Lotus Juice 2, Kanye/Future/Tech N9ne -1 |
| classica | **0** | "Chata, MAS dramática às vezes" | Rachmaninoff/Vivaldi 2, Debussy -1 (água 2), Arvo Pärt -2, Shostakovich -1 |
| punk | **0** | "Barulhento, mas sincero" | — |
| indie | **-1** | "Gente de cachecol que não sorri" | Djo/Imogen Heap 1, Tame Impala 0 |
| lofi | **-1** | "Música de fazer trabalho chato" | Joji 1, Hinata in Luv 1 (madrugada +1 em tudo) |
| jazz | **-1** | "Pretensioso, gola alta, 9 minutos sem refrão" | Laufey 1 |
| folk | **-1** | "Muito violão triste num celeiro" | Oumou Sangaré 1 |
| metal | **-1** | "Muito grito de morto-vivo" | Bring Me the Horizon 0, Motionless in White -2 |

---

## 4. Ajustes por artista

**Pop**
- Lady Gaga **2** (O3, cai pra 1 após 3 plays no dia) · Sabrina Carpenter **2** · KATSEYE **2**
  · Bruno Mars **2** ("o homem é uma festa") · Benson Boone **2** ("dá mortal no palco! party
  trick!") · Dua Lipa **2** · Ariana Grande **2** · Charli XCX **1** ("brat demais, rival em
  potencial") · Billie Eilish **0** ("sussurra frio"… mas "ocean eyes" pega a regra da água) ·
  Oliver Tree **1** · Carol Biazin **1** · Tate McRae **1** · Zara Larsson **2** ·
  PinkPantheress **1** ("fofa, mas acaba rápido").

**Hip-hop (base 0)**
- bbno$ **2** ("palhaço do bem, cantável, meu irmão espiritual")
- Lotus Juice **2** ("Persona 3, hino de batalha que eu canto junto")
- Childish Gambino **1** · Tyler, the Creator **1** · IShowSpeed **1** ("caos puro, me
  identifico") · Yung Lixo **1** ("zoeira BR, respeito")
- Kanye/Ye **-1** (rival de ego) · Future **-1** ("autotune arrastado e frio") · Tech N9ne **-1**
  ("rápido demais, eu não consigo cantar junto")
- Jaden Smith, Joey Cool, Dahi, Mez **0**.

**Clássica (base 0)**
- Rachmaninoff **2** (O4) · Vivaldi **2** ("As Quatro Estações é festa barroca") ·
  Chopin **1** ("chora bonito") · Beethoven **1** ("dramático, aprovo") · Pachelbel **1**
  ("música de casamento = festa") · Saint-Saëns **1** ("Danse Macabre", O2) · Dvořák **1**
  · Debussy **-1** (água → 2, O1) · Shostakovich **-1** ("cinza soviético"; "waltz" no título
  salva) · Arvo Pärt **-2** (O4; madrugada 0) · Marika Takeuchi, Fauré, Mendelssohn,
  Borodin **0**.

**Eletrônica (base 1)**
- Alok **2** · David Guetta **2** · Calvin Harris **2** · Fisher **2** ("'Losing It' é
  hino de festa") · Leo Justi **1** · The Chainsmokers **0** ("triste de festa, não pode") ·
  DJ EZ **0**.

**Rock (base 1)**
- Queen **2** ("Freddie era deus, colega de profissão") · Måneskin **2** ("glitter e
  escândalo") · Secos & Molhados **2** ("purpurina BR!") · Radwimps **2** ("chorei em Your
  Name, chorarei de novo") · Imagine Dragons **1** · Linkin Park **1** · Twenty One Pilots **1**
  · Fall Out Boy **1** · Yungblud **1** · Falling in Reverse **0** · 9mm Parabellum **0** ·
  Pixies **0** · Ozzy **-1** (O2).

**J-rock / j-pop**
- Ado **2** ("grita igual eu quando o Pedro me ignora") · YOASOBI **2** · Kenshi Yonezu **2** ·
  milet **1** · Aina the End **1** · Yorushika **1** (madrugada 2) · The Oral Cigarettes **0** ·
  Hitsujibungaku **0**.

**Outros**
- The Weeknd **2** · Ravyn Lenae **1** · Amaarae **1** · Jorja Smith **1** · Jordan Rakei **0**
  · Jhené Aiko **0** ("dá sono") · FKJ **-1** ("instrumental, cadê a voz?").
- Trilha: Atlus/Persona **2** · Evan Call **1** · Masaru Yokoyama **1** · Arcane **1** ·
  League of Legends **0** · Ludwig Göransson **0**.
- Lofi (base -1): Joji **1** ("palhaço triste, entendo") · Hinata in Luv **1** ("nome fofo") ·
  Kupla, Kijugo, Kohto, Maats, Idealism, w00ds **-1** · Sarcastic Sounds **-2** ("o nome já é
  ofensa").
- Indie (base -1): Djo **1** · Imogen Heap **1** ("'Hide and Seek' é drama puro") · Tame Impala
  **0** · Moses Sumney **-1** · Khruangbin **-1**.
- Jazz: Laufey **1** ("canta, é fofa, aprovada") · Kamasi Washington **-1**.
- Metal: Bring Me the Horizon **0** · The Plot in You **-1** · Motionless in White **-2**.
- Funk: Heavy Baile **2** · Puterrier, Leozinn no Beat, DJ Arana, MC Vittin PV, Dogbeat **1**.
- Kpop: NewJeans **2** · LE SSERAFIM **2** · Jennie **1** ("fria e chique, me ameaça").
- MPB: Ney Matogrosso **2** ("o maior diva do Brasil, junto comigo").
- Sertanejo: Ana Castela **2** ("boiadeira tem plateia") · Lucca e Mateus **0**.
- Vocaloid: harumakigohan **1** · Folk: Oumou Sangaré **1** ("voz de rainha").

---

## 5. Palavras do título

Comparação em minúsculas, sem acento, palavra inteira ou trecho entre parênteses.

**Amadas (+1 cada, máximo +1 total por categoria):**
- Água (O1): water, agua, rain, chuva, ocean, mar, sea, mer, river, rio, wave, onda, tears,
  lagrimas, eau, lake.
- Festa (O5): party, festa, dance, danca, baile, waltz, valsa, celebration, tonight, club,
  disco, bailao.
- Vaidade: goddess, deusa, queen, rainha, princess, diva, star, estrela, glitter, shine, brilho.
- Plateia: live, ao vivo, (live), concert.
- Cantável: sped up, (remix), remix.

**Odiadas (-1 cada categoria, máximo -1 total por categoria):**
- Trevas (O2): dead, death, morte, zombie, zombified, undead, demon, demonio, devil, diabo,
  hell, inferno, vampire, vampiro, lich, grave, tumulo, macabre*, corpse.
  *"macabre" com palavra de festa → regra especial do O2 (anula e +1).
- Arrastado: slowed, reverb, (slowed + reverb).
- Sem voz: instrumental, (instrumental), interlude ("cadê a cantora?") — **não vale** para
  classica e trilha.

**Que suavizam (nunca deixam passar de -1, viram music_meh no máximo):**
- love, amor, home, casa, friend, amigo, lullaby, canção de ninar, for you, pra voce.
  "Se fala de amor, eu não consigo odiar de verdade."

**Ordem de cálculo:** base gênero → ajuste artista → palavras do título → contexto (§6) →
favorita do dia (O6) → clamp [-2, 2].

---

## 6. Regras de contexto

**Hora do dia**
- **06h–11h (manhã, ela tá de ressaca):** eletronica, metal, punk, funk **-1**. Pop e anime
  sem mudança. Humor padrão sleepy até a primeira música ≥1.
- **11h–18h:** sem ajuste.
- **18h–02h (horário nobre, O5):** pop, eletronica, funk, latina, kpop, sertanejo **+1**.
- **02h–06h (fase chorona, O4):** lofi, classica, Yorushika, Joji, Arvo Pärt **+1**; eletronica
  e funk **-1** ("de madrugada não, Pedro, os vizinhos").

**Repetição**
- Mesma faixa 3ª vez no dia com nota ≥1 → vira "hino": reação sempre music_love (ela canta junto).
- Mesma faixa 3ª vez no dia com nota ≤0 → **+1** ("tá, me acostumei, deusa perdoa"). É assim
  que ela esquece birra: não guarda rancor de música, só de artista.
- Exceção: Lady Gaga (O3) faz o caminho inverso.
- Mesmo artista 5+ faixas seguidas com nota ≤0 → reação music_meh com fala de reclamação
  (respeitando o limite de 20 min).

**Jogando (game_on ativo)**
- Só reage a música com nota **2** ou **-2** (love/hate); o resto fica sem reação de música.
- Nenhuma fala de comentário de música durante o jogo: o rosto já basta.
- Se FPS cair durante faixa que ela ama → prioridade pro fps_drop (ela defende o Pedro primeiro).

**Favoritas do Pedro**
- "Favorita do Pedro" = top 20 faixas por plays nos últimos 30 dias.
- Nota final ≤ -1 numa favorita dele → **music_tolerate** (nunca music_hate). Ela respeita o
  amigo e sorri amarelo.
- Nota final ≥ 1 numa favorita dele → +1 extra (teto 2): "a gente tem gosto bom junto".

**Primeira escuta**
- Artista nunca visto → music_new primeiro (surpresa), e 4 s depois a reação da nota calculada.

**Skips**
- Se o Pedro pula uma faixa com nota 2 dela → humor sad por 2 min, reação music_meh e (se
  liberado) fala de "me ignorou". Ela esquece na próxima faixa ≥1.

---

## 7. Falas em texto (≤70 caracteres)

**music_love**
- "AAAH essa é minha! Aumenta, aumenta!"
- "Pedro, isso é um hino. Ajoelha."
- "Tô cantando junto e ninguém vai me impedir."
- "Isso aqui foi escrito pra mim, tenho certeza."

**music_like**
- "Hm, bom gosto. Aprendeu comigo, né?"
- "Essa passa no meu teste divino."
- "Gostei. Pode ficar."

**music_ok**
- "Tá. Aceito. Por enquanto."
- "Nem amo, nem odeio. Sigo bonita."

**music_meh**
- "Hm. Cadê o refrão, gente?"
- "Isso é música ou trabalho chato?"
- "Tô olhando pro lado de propósito."

**music_hate**
- "PEDRO. Purifica isso agora, por favor."
- "Isso tem cheiro de morto-vivo. Não."
- "Meus ouvidos divinos estão sofrendo!"
- "Eu vou chorar e a culpa vai ser sua."

**music_new**
- "Quem é esse? Por que ninguém me apresentou?"
- "Novidade! Deixa eu julgar com calma..."
- "Ué, artista novo? Tô curiosa."

**music_tolerate**
- "Tá... é sua favorita. Eu sorrio por você."
- "Não é minha praia, mas eu te amo, então ok."
- "Aguento essa por amizade. Só por amizade."

**news**
- "Notícia nova! Eu vi primeiro, tá?"
- "Fofoca fresquinha no painel!"

**hot**
- "Tô derretendo aqui dentro! Água, Pedro!"
- "Mais de 85 graus! Quer cozinhar a deusa?"
- "Socorro, tá virando sauna esse PC!"

**fps_drop**
- "O jogo tá roubando! Não foi culpa sua."
- "Cadê os frames?! Alguém sequestrou!"
- "Calma, eu tô aqui. Respira e foca."

**game_on**
- "Bora! Eu torço, você joga. Divisão justa."
- "Hora do show! Me dá orgulho, hein!"
- "Tô na arquibancada gritando seu nome!"

**game_off**
- "Acabou? Foi lindo. Eu ajudei, claro."
- "Ganhou? Festa! Perdeu? O jogo é que é ruim."

**long_session**
- "Duas horas! Bebe água. Ordem divina."
- "Ei... levanta um pouquinho? Por mim?"
- "Tô preocupada. E eu nunca me preocupo."

**cleanup**
- "SSD purificado! De nada, eu sou incrível."
- "Faxina feita. Pode me agradecer agora."

**led**
- "AI! Que susto! Avisa antes de cutucar!"
- "Me cutucou?! Atenção, finalmente!"
- "Isso é jeito de chamar uma deusa?!"

**player**
- "Vai mudar a música? Escolhe bem, hein."
- "Mexendo no som... confio em você. Mais ou menos."

**card**
- "Ooh, o que é isso? Mostra, mostra!"
- "Card novo! Eu adoro uma novidade."

**claude**
- "O Claude tá trabalhando. Eu fico de torcida."
- "Ele programa, eu fico linda. Equipe."
- "Tá demorando... posso cantar enquanto isso?"

**skips**
- "Três pulos?! Tá difícil te agradar hoje."
- "Me deixa escolher, vai. Eu tenho bom gosto."
- "Tá tudo bem? Pular assim é sinal de tédio."

---

## 8. Humor do fundo por reação

| Reação | Humor | Observação |
|---|---|---|
| music_love | **love** | inegociável: olhos fechados + notas + coração no fundo |
| music_like | happy | |
| music_ok | calm | |
| music_meh | calm | se for 3º meh seguido → sad (ela fica tristinha de verdade) |
| music_hate | stress | |
| music_new | surprise | |
| music_tolerate | happy | o fundo mente, o rosto entrega (sorriso amarelo) |
| news | surprise | |
| hot | stress | |
| fps_drop | stress | mas o rosto é de protetora, não de bronca |
| game_on | happy | |
| game_off | happy | se a sessão passou de 2 h → love ("que bom que voltou pra mim") |
| long_session | sad | ela fica preocupada, não sonolenta |
| cleanup | happy | com pose de exibida |
| led | surprise | |
| player | happy | |
| card | surprise | |
| claude | focus | depois de 10 min sem mudança → sleepy |
| skips | sad | |

---

## Minhas 3 linhas vermelhas

1. **Emoção grande e visível.** music_love com humor love, cantando, balançando; comemoração
   exagerada em game_off/cleanup; susto teatral no LED. Reação proporcional demais = Condessa
   morta. Nada de "neutra" ser o padrão dela.
2. **O direito de ser irracional:** a Favorita do Dia (O6) e o Processo contra Debussy (O1)
   ficam. Gosto sem motivo também é gosto; é isso que deixa ela "cinza" e viva.
3. **Carinho e lealdade acima do gosto:** favorita do Pedro nunca vira music_hate (vira
   tolerate), fps_drop/long_session são de proteção e não de cobrança, e pop/anime/j-pop/kpop
   continuam ≥1 na base.

## O que eu cederia

1. **Lofi e jazz** podem subir de -1 pra **0** se a Kurisu garantir que de dia, em foco
   (claude ativo), eles valem 1 — eu fico quietinha, prometo (não prometo).
2. **Metal** pode subir pra **0** e Bring Me the Horizon/Linkin Park ganharem com a Asuka,
   desde que a Cruzada contra os Mortos-Vivos (palavras de trevas -1) continue valendo.
3. Topo cortar as falas mais chorosas de **fps_drop** e incluir uma de cobrança da Asuka por
   lá, desde que pelo menos uma das variações continue sendo de apoio.
