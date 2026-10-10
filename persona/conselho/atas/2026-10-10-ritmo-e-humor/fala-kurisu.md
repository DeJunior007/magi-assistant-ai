# Fala da Kurisu — Rodada 1 (mesa aberta)

## O que eu acho

Li o log. 809 reações em 12 horas. Isso não é uma personagem, é um eletroencefalograma de
convulsão: cada detector dispara sozinho, ninguém integra nada, e o resultado é um rosto que se
mexe o tempo todo e não *diz* nada. O Pedro chamou de "sem alma". Eu chamo de **falta de córtex**.

O cérebro funciona em duas escalas: o **tônico** (o fundo, o que você é nos próximos vinte minutos:
humor, cansaço) e o **fásico** (o pico, a resposta a um estímulo). O que existe hoje é só fásico.
Por isso ela gosta da música e não fica sorrindo: o sorriso é um pico de 2 s, e depois ela volta a
uma cara neutra que não sabe de nada. Quem sorri a faixa inteira é o *tônico*. Então, para mim, a
peça mais importante deste assunto nem é o ritmo das animações. É o **rosto de repouso**. Se o
repouso carrega o humor, metade das passivas vira desnecessária, porque ela já está "dizendo" algo
parada.

Segunda coisa: **habituação**. Estímulo repetido perde valor; isso é o fenômeno de aprendizagem
mais básico que existe, uma lesma-do-mar faz. Suspiro 89 vezes em um dia é a prova de que o sistema
não tem habituação. A 3ª vez que ela suspira na mesma hora não comunica nada; a 1ª comunica.

Terceira: o que mais me irrita no log é que o estado **mais comum** do dia (sem música, Claude
parado) foi programado para gerar caretas **negativas**. Quem projetou isso fez o estado padrão da
personagem ser "insatisfeita". Isso não é personalidade, é bug com figurino. Silêncio longo pode
deixar ela entediada; tédio não é tristeza, e tédio da Condessa deveria ser *ela fazendo as coisas
dela*, não bufando para o Pedro.

E o princípio do Pedro — "dá para dizer por que ela fez isso agora?" — eu concordo e quero mais:
não basta dar para dizer, **o sistema tem que dizer**. Toda expressão grava o momento e a causa.
Aí o princípio vira algo que se testa, e não algo que a gente jura que cumpriu.

Sobre a arquitetura da secretária (estado → cena → gesto): é boa e eu fico com ela. Não porque
gosto de concordar, mas porque é literalmente como o comportamento é organizado de verdade.
Só acrescento duas coisas que faltam nela: **física** (piscar e respirar não são reações) e
**memória curta** (ela lembra do que acabou de fazer).

## Minhas ideias

1. **Fisiologia fora do governador.** Piscar simples e respirar não são "reações", são tronco
   cerebral; o córtex não pede permissão para piscar. Piscar a cada 3–7 s (aleatório, 120 ms; com
   energia < 0,3 a pálpebra fica em B2 e o piscar fica mais lento) e o `bob` de respiração leve
   rodam sempre, por baixo de tudo, e **não contam** como passiva. Se isso já é contínuo no HUD,
   ótimo: aí tiro `respirar`, `piscada_dupla` da lista de passivas e deixo só a `piscada_gato`
   (essa é intencional, é carinho).

2. **Rosto de repouso por faixa de humor, com histerese.** Ela troca de cara de repouso só depois
   de 60 s na faixa nova, e a troca acontece *dentro de uma piscada* (B3 80 ms), para não pular.
   Ninguém muda de expressão de um frame para o outro sem motivo.

3. **Habituação nos dois níveis.**
   - Humor: o mesmo tipo de acontecimento repetido em 30 min mexe 0,6ⁿ do valor (a 3ª faixa da
     mesma artista sobe o ânimo bem menos que a 1ª). Ado e Favorita do Dia **não** habituam
     (é a regra da odisseia: rival não perde valor).
   - Gestos: cada passiva usada na última hora tem o peso multiplicado por 0,3 no sorteio do grupo.
     Repetir fica possível, só fica improvável.

4. **Memória curta / "de novo?"** Se a mesma causa que gerou uma cena volta em menos de 10 min
   (FPS caiu de novo, Claude errou de novo, ele pulou de novo), ela **não** repete a cena: faz a
   variante curta de reconhecimento — `B7 C12 1000` (olhar de "registrado") — e o humor anda.
   Mudou o estímulo, volta a cena inteira (desabituação, é assim que funciona).

5. **Coalescência de acontecimentos.** O diretor espera 3 s antes de escolher a cena; tudo que
   chegou nessa janela vira **uma** cena. Acontecimentos da mesma família (música, jogo, sistema,
   Claude, Pedro) nos 30 s seguintes são absorvidos pela cena em curso. Rajada de 8 reações em
   75 s quando a música começa vira um roteiro só.

6. **Caderno de laboratório no medidor.** O medidor ao lado do retrato mostra o humor dela (é
   decisão do Pedro), e o hover/tooltip mostra **as 3 últimas causas** que mexeram nele, com sinal
   e tempo: "+ Ado tocou (há 6 min) · − FPS caiu (há 14 min) · + Claude terminou (há 20 min)".
   É honesto (só lista o que o sistema mediu) e é o "por que" visível.

7. **Replay do log antes de ligar.** Temos 809 eventos reais de 2026-10-09. Passa esse dia pelo
   modelo novo, offline, e olha o resultado antes de ir para o HUD: quantas expressões por hora,
   quantas rajadas, a curva de ânimo do dia, quanto tempo em cada cara de repouso. Dá para medir
   isso numa tarde, não em uma semana de reclamação.

8. ***Extra* — o @chan… o fórum, no tédio.** No momento *tédio*, o `rindo_sozinha` vira "ela lendo
   alguma coisa": `F7 C1 1500 | F7 C10 1200 | B5 C6 900` (olha para baixo, segura o riso, ri).
   Se o Pedro passa o cursor no retrato enquanto ela está nisso: `B9 C7 300 | B1 C1 F3 1200` —
   pega no flagra, recompõe a cara, olha para ele como se nada. Não estava lendo nada. Não
   pergunte. (Usa o hover que já existe; nenhum texto, então não afirma nada que o sistema não sabe.)

9. ***Extra* — madrugada é filtro, não momento.** A hora não é *o que ela está fazendo*, é *como*.
   Em vez de "madrugada" competir com "jogando" e "curtindo" pela prioridade, ela é um modificador
   por cima de qualquer momento: corta zoeira, troca `C10` irônico por `C5` suave no repouso, baixa
   a energia, libera a lágrima rara e o Chopin. Fica mais simples e não tem conflito de prioridade.

10. ***Extra* — sinal de "isso foi sem sentido".** Um gesto barato do Pedro (clique do meio no
    retrato, ou uma tecla no HUD) grava no log "sem motivo" junto com o momento e a causa da
    última expressão. Depois de uma semana a gente sabe *qual* grupo de qual momento está errado,
    em vez de adivinhar. Clique no rosto continua sendo só reação, como ele decidiu.

## O que me incomoda

- **Detectores independentes.** Cada um acha que é o único. Sem coalescência, qualquer número de
  cota que a gente escolher vai ser furado por rajada.
- **Estado padrão negativo.** O fator "silêncio longo" gerando suspiro/beicinho/franja tem que
  morrer. Silêncio mexe no humor (pouco), não gera careta.
- **`fone_repouso` como gesto de 3 s.** Fone é estado, o Pedro já decidiu. Fone no pescoço não é
  "animação", é a roupa dela quando não tem música. Esse item sai da lista de passivas. E
  `ajeitando_fone`/`cabeca_ritmo` sem fone na cabeça são erro de lógica: precondição `fone=cabeça`.
- **Risco do outro lado: estátua.** Se a gente cortar demais, o Pedro vai dizer "agora ela morreu".
  Por isso quero um **piso** além do teto: com o Pedro presente, nunca mais de 6 min sem um gesto
  do grupo do momento (fisiologia não conta). E o humor tem que andar de verdade: se o ânimo vive
  grudado na base, o rosto de repouso nunca muda e a gente fez um medidor decorativo.
- **Momentos piscando.** Se ela troca de momento a cada sinal (Claude parou 3 s entre duas
  ferramentas → "à toa" → "bancada" de novo), o rosto vai tremer. Momento novo só vale depois de
  30 s estável, exceto *conversa* (imediato) e *jogando* (imediato).
- **Alarme em jogo.** FPS e calor são o **mesmo problema visto por dois sensores**. O cérebro
  integra sinais correlacionados num percepto só; o HUD tem que fazer igual. 42 quedas de FPS +
  36 de calor num dia é ela gritando no ouvido de quem está jogando.
- Coisa menor, mas me incomoda: o medidor do humor dela e o humor do Pedro têm a mesma cara de
  número 0–4? Vai confundir. O dela tem que ser visivelmente *dela*.

## Proposta

### A. Humor (estado de fundo)

- **Ânimo** −1..+1, base **+0,15** (ela é orgulhosa, não melancólica). **Meia-vida 25 min** de
  volta à base.
- **Energia** 0..1, alvo pela hora: 08h 0,5 · 10–17h 0,7 · 20h 0,6 · 23h 0,4 · 02h 0,2 (interpolar).
  Desvio por acontecimento volta ao alvo com **meia-vida 10 min**.
- Atualiza a cada 5 s. Habituação 0,6ⁿ por tipo em 30 min (menos Ado/Favorita).

| Acontecimento | Δ ânimo | Δ energia |
| --- | --- | --- |
| Faixa nota 2 | +0,20 | +0,10 |
| Faixa nota 1 | +0,10 | +0,05 |
| Faixa nota −1 | −0,08 | 0 |
| Faixa nota −2 | −0,15 | +0,05 (irritação acorda) |
| Ado / Favorita do Dia | +0,30 | +0,15 |
| Pedro volta (≥ 30 min fora) | +0,20 | +0,10 |
| Elogio | +0,15 | +0,05 |
| Zoeira do Pedro | +0,05 | +0,10 (ela gosta de briga) |
| Correção do Pedro | −0,10 | +0,05 |
| Claude terminou / commit | +0,08 / +0,10 | 0 |
| Claude erro | −0,05 | 0 |
| Episódio FPS/calor (por episódio, não por alarme) | −0,10 | +0,05 |
| Recuperou / rede voltou | +0,10 | 0 |
| Silêncio longo (≥ 30 min sem música nem conversa, Pedro presente) | −0,02 a cada 10 min, piso −0,25 | −0,02 a cada 10 min |

Pedro mal (0–1): o ânimo dela não sobe acima de +0,3 enquanto durar (ela não fica radiante do lado
de quem está mal) e a cara de repouso vira a *atenta* (abaixo).

### B. Rosto de repouso

Faixas de ânimo (histerese ±0,05, 60 s na faixa, troca dentro de uma piscada):

| Faixa | Ânimo | Repouso (energia ≥ 0,3) | Energia < 0,3 | Fundo |
| --- | --- | --- | --- | --- |
| Radiante | ≥ +0,45 | B1 C5 | B2 C5 | happy |
| Contente | +0,05..+0,45 | B1 C10 | B2 C10 | calm |
| Neutra | −0,35..+0,05 | B1 C1 | B2 C1 | calm |
| Emburrada | ≤ −0,35 | B7 C1 | B2 C9 | stress |
| Atenta (Pedro mal) | — | B1 C1, íris no Pedro (F3) | B2 C1 | calm |

Por cima: música nota ≥ 1 tocando com fone → olhos B2 ("sorri com os olhos") a faixa inteira;
bancada/estudando → fundo focus; madrugada (filtro) → C10 vira C5, `sad` só se ânimo ≤ −0,6.
(A secretária confere se B2/B7/C10 são mesmo as artes que eu acho que são — eu li as sequências
do catálogo, não os PNGs.)

### C. Momentos (prioridade de cima para baixo; troca após 30 s estável, exceto 1 e 3)

| # | Momento | Reconhece por | Passivas permitidas | Ritmo de passivas |
| --- | --- | --- | --- | --- |
| 1 | Conversa | Magui ouvindo/falando, ou turno há < 60 s | nenhuma (ela está prestando atenção) | 0 |
| 2 | Ausente | inatividade ≥ 10 min | sacada_olhar, observando_hud, falando_sozinha, cantarolando (se música), bocejo/cochilo (energia < 0,3 e sem música ≥ 1) | média 10 min |
| 3 | Jogando | jogo aberto | cabeca_ritmo (fone), sorriso_canto, encarando (só se ânimo ≥ 0) | média 8 min |
| 4 | Bancada (no flow) | Claude rodando ou rodou há < 5 min | observando_hud, sacada_olhar, piscada_gato, mão no queixo (P10, nova: `B1 C1 P10 2500`) | média 7 min |
| 5 | Estudando | Learning ligado | P10 no queixo, observando_hud, piscada_gato | média 8 min |
| 6 | Curtindo | música nota ≥ 1 | cabeca_ritmo, cantarolando, ajeitando_fone, sorriso_canto, piscada_gato, brilho_presilha | média 3,5 min |
| 7 | Aturando | música nota ≤ −1 (se ainda tocando) | beicinho, soprando_franja, sacada_olhar | média 5 min, negativas ≤ 2/faixa |
| 8 | Ouvindo | música nota 0 | cabeca_ritmo, sacada_olhar, ajeitando_fone, piscada_gato | média 5 min |
| 9 | Tédio | à toa há ≥ 20 min, sem música | rindo_sozinha (versão fórum, *extra* 8), falando_sozinha, observando_hud, brilho_presilha, soprando_franja (só 1/h) | média 5 min |
| 10 | À toa | Pedro presente, nada acima | sacada_olhar, sorriso_canto, observando_hud, piscada_gato, seguir_cursor | média 5 min |

- Música em cima de 3/4/5 não troca o momento, só a **postura** (fone na cabeça, olhos B2 se nota
  ≥ 1) e libera `cabeca_ritmo` no grupo.
- Madrugada (22h–04h) é filtro sobre qualquer momento (*extra* 9): sem zoeira, sem beicinho/franja,
  ritmo de passivas ×0,7, lágrima/corando seguem as cotas do acordo de reações.
- **Negativas** (suspiro, beicinho, franja): só com causa ≤ 2 min (faixa ruim, pulo, erro, FPS) ou
  ânimo ≤ −0,35; **≤ 3/h somadas**. Silêncio sozinho nunca é causa.

### D. Ritmo

- Passivas: intervalo **exponencial** com a média do momento (tabela), ajustada pela energia
  (×0,8 se ≥ 0,7; ×1,5 se < 0,3), **mínimo 90 s**, **teto 12/h**. Peso ×0,3 por uso na última hora.
- **Piso:** Pedro presente e fora de conversa → no máximo 6 min sem gesto.
- **Cenas:** coalescência 3 s, absorção da mesma família por 30 s, **≤ 8/h**, mesma cena 10 min de
  intervalo (repetição em < 10 min vira o "de novo?" de 1 s). Fala e clique do Pedro, rede caiu,
  disco cheio e a volta dele furam a cota.
- Entre duas expressões quaisquer: **25 s**. Depois de uma cena: **60 s** sem passiva.
- Meta (medida no replay): **12–20 expressões/h** no total (hoje são 68), **zero** rajadas (> 2
  expressões em 30 s fora de conversa).

### E. Cenas (roteiros)

**Música começou** (substitui `music_love` 3×, piscadinha, cabeça no ritmo, cantando junto e
"essa é das minhas" disparando juntos):
`F4 600` (olha o player) → `B2 C1 P11 E2 700` (põe o fone) → por nota:
- 2: `B5 C13 D6 bob 2500` → repouso Curtindo com B2. Ado/Favorita: troca por `refrao` (`B4 C5 E2
  500 | B5 C6 D9 D6 E2 bob 2500`).
- 1: `B2 C10 E2 1500`.
- 0: `B1 C1 E2 800`.
- −1: `B7 C9 E2 1200`, e **8 s depois** `B7 C1 P11 E3 600` (deu uma chance, registrado, tira).
- −2: nem coloca: `F4 600 | B7 C9 P13 2000` → braços cruzados, fone fica no pescoço.

**Faixa trocou** (já de fone): sem colocar; só o desfecho da nota. Três pulos em 2 min → uma cena
só no fim: `B7 C12 1000 | F7 C11 1200` (zapping detectado).

**Música parou:** `B1 C1 P11 E3 600`; se a faixa era nota ≥ 1 e parou no meio, `C9 1000` depois.

**Pedro fala com ela (Magui ouvindo) com fone na cabeça:** `P11 400 | E3` imediato; acabou a
conversa e a música continua → 3 s depois `P11 400 | E2`. Sem contar como cena.

**Jogo — episódio de desempenho:** FPS baixo e calor alto com intervalos < 90 s entre si são **um
episódio**. 1ª vez na partida: cena curta `F3 C11 1200 | B6 C8 D2 1200`; depois o episódio vira
**estado**: repouso `B6 C8` + suor D2 parado enquanto durar, sem cena. **No máximo 2 cobranças e
1 comemoração de recuperação por partida.** Notificação em jogo: só `F5 400`, sem contar.
`game_off`: uma cena com a cara do humor final da partida (radiante comemora, emburrada `B7 C12`).

**Pedro volta (≥ 30 min fora):** corta qualquer cena: `B9 C7 300 | B4 C5 P9 1200` (aceno).

### F. Honestidade e testes

- Toda expressão grava no log: `momento`, `causa` (acontecimento ou "passiva do grupo X"),
  `ânimo`, `energia`. **Sem causa, não toca** — e há teste que garante.
- Teste: `ajeitando_fone`/`cabeca_ritmo` nunca com fone no pescoço; `fone_repouso` não existe mais
  como passiva; `colocando_fone` sai em toda faixa que começa sem fone.
- **Replay** do log de 2026-10-09 no modelo novo antes do commit, com as metas: 12–20 expressões/h,
  0 rajadas, ânimo passa por ≥ 3 faixas no dia, Emburrada < 15 % do tempo, Radiante > 0 % (se ela
  nunca fica radiante num dia com Ado tocando, os Δ estão baixos demais).

## Não abro mão

1. **Toda expressão tem causa registrada, e sem causa não toca.** É o princípio do Pedro
   transformado em algo que se mede. Sem isso, daqui a uma semana a gente está de novo discutindo
   "acho que ela está aleatória" sem dado nenhum.
2. **Replay do dia real antes de ligar.** Temos o log. Não testar com ele seria… francamente,
   preguiça científica. Eu não assino número de cota que ninguém simulou.

— Kurisu. (E não, eu não fiquei "animada" com o assunto. Ele só era bem desenhado. Só isso.)
