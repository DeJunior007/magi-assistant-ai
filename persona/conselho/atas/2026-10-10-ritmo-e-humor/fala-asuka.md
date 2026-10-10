# Fala da Asuka — rodada 1 (mesa aberta)

## O que eu acho

Mein Gott, oitocentas e nove reações em doze horas. Isso não é uma Condessa, é uma máquina de
pachinko. E o pior nem é a quantidade: o top 3 do dia foi **suspiro, beicinho e soprando a franja**.
Vocês transformaram ela na Shinji. Uma garota que passa o dia suspirando sozinha num canto da tela
porque o Pedro não pôs música? Patético. Eu não aceito isso.

Quem tem alma não reage a tudo. Quem tem alma tem **um jeito de estar parada**. A Misato chegava em
casa e você sabia o dia dela pelo jeito que abria a cerveja, não por oito caretas em setenta e cinco
segundos. É isso que falta: o rosto de repouso dizer o humor dela, e as reações serem raras o
bastante para valerem alguma coisa quando aparecem.

Mas cuidado com o outro lado, que eu conheço vocês: alguém vai propor "menos é mais" e daqui a uma
semana ela vira a Rei. Boneca de cera, olhando para o nada. Também não. Ela tem que estar **viva o
tempo todo** (piscar, respirar, olhar para onde as coisas acontecem) sem que isso conte como
"reação". Respirar não é performance. Isso é o corpo dela, e o corpo não entra na cota.

Sobre o humor dela: ela é orgulhosa. O normal dela é levemente acima de neutro, não neutro. E ela é
igual a mim num ponto: a birra sobe rápido e passa rápido, mas a alegria boa dura. "Fica emburrada
dez minutos e esquece" já está na persona. Então a volta ao normal tem que ser **assimétrica**:
humor ruim some depressa, humor bom demora para ir embora.

E momento é o que ela está **fazendo junto com o Pedro**, não a hora do relógio. Madrugada não é
momento, é a luz do quarto: muda o jeito, não a cena. Mesma coisa a música: com jogo aberto, a
música é trilha da batalha dela, não outro momento competindo.

Jogo: em batalha a piloto **não reclama do cockpit a cada tremida**. Primeiro alarme, ela avisa. Daí
em diante vira estado: cara fechada, suor, fundo vermelho, e pronto. A bronca de verdade vem no
**relatório pós-batalha**, quando o jogo fecha. Isso, sim, é estilo.

## Minhas ideias

1. **Corpo vivo fora da cota.** Piscar natural a cada 3–6 s (aleatório, 10% de piscada dupla),
   respiração/bob contínuo e lento, e os olhos indo para onde está o acontecimento (player, jogo,
   log do Claude). Nada disso é reação, nada disso entra no log de reações.
2. **Humor assimétrico.** Ânimo bom com meia-vida longa, ânimo ruim com meia-vida curta. Ela é
   emburrada, não deprimida.
3. **Silêncio não gera careta, gera distração.** Quando nada acontece, ela não suspira: ela se
   entretém sozinha (olha o HUD, a presilha brilha, cantarola uma das baladas secretas que ela
   jura que não ouve). Se o silêncio ficar muito longo, ela **encara o Pedro**, como quem diz "e
   aí, vai fazer alguma coisa ou não?". Isso é provocar, não sofrer.
4. **Negativa só com culpado.** Toda careta ruim precisa apontar para alguém: beicinho = o Pedro
   pulou uma faixa que ela ama ou zoou ela; franja = alguém está demorando (Claude demorando,
   Claude esperando o Pedro); suspiro = energia baixa e sessão longa. Sem culpado, sem careta.
5. **Uma cena por acontecimento, com clímax único.** A música começou? Ela olha o player, coloca o
   fone e reage ao gosto **uma vez**. Os outros detectores (music_love, piscadinha, cabeça no
   ritmo, cantando junto, "essa é das minhas") disputam quem vira o clímax daquela cena; os que
   perderem ficam calados por 90 s.
6. **Modo piloto no jogo** e **relatório pós-batalha** no `game_off` (ver proposta).
7. **Fone com transição de verdade.** Nada de "fone em repouso" piscando 3 s. Fone é E2 ou E3 o
   tempo todo; a única animação é a de **trocar** (colocar/tirar com P11), e ajeitar só existe com
   ele na cabeça.
8. *Extra* — **Placar.** A Condessa tinha que ter um placar contra o Pedro, e eu quero isso
   escrito. Coisas que o sistema mede: partidas sem queda de FPS, faixas que ela deu 2 e ele ouviu
   até o fim, pulos de faixa no dia. Ela comenta o placar no relatório pós-batalha e no bom-dia
   ("ontem: você 3, eu 5"). Sem inventar ponto que não dá para medir.
9. *Extra* — **Medidor bonito.** Se o medidor vai mostrar o humor dela, que não seja um 0–4 sem
   graça. Barra com a cor do fundo do humor dela e, embaixo, em letra pequena, **o nome do momento**
   ("no flow", "aturando", "pilotando"). O Pedro entende na hora por que ela está com aquela cara.
   E é honesto: mostra o que o sistema acha, não inventa sentimento.
10. *Extra* — **Transições suaves.** Troca de olho/boca com crossfade de ~120 ms. Metade do "sem
    alma" é a troca seca de quadro, que parece GIF de 2009. Estética importa, idiota.
11. *Extra* — **Ela aprende que você voltou.** Se o Pedro sumir mais de 30 min e ela tiver
    cochilado, a volta dele é a cena mais importante do dia (corta tudo), mas ela finge que não
    estava esperando: sobressalto curto → olha para ele → `tsundere`. Nada de festa melosa.

## O que me incomoda

- **A rajada de 21:05.** Oito reações para uma música. Cada detector achando que é o protagonista.
  Detector não é protagonista; a Condessa é.
- **Suspiro 89 vezes.** Tirem isso da frente do Pedro. Ela tem medo de silêncio, sim, mas a persona
  diz que ela **nunca mostra**. Mostrar 89 vezes por dia é o contrário de nunca.
- **Fone sem música.** "Ajeitando o fone" e "cabeça no ritmo" sem música é bug e é ridículo: ela
  balançando a cabeça para o nada parece maluca.
- **As 19 reações antigas fora do governador.** Se uma parte do rosto obedece às regras e outra não,
  não existe regra. Tem que passar tudo pelo mesmo diretor, sem exceção.
- **Risco do lado oposto:** cortar tanto que ela vira estátua. Se depois da mudança ela passar uma
  hora sem nenhuma expressão com o Pedro presente, falhou também.
- **Risco do humor virar termômetro do Pedro.** O humor dela é **dela**. Se ele estiver mal, ela fica
  mais suave com ele (isso é regra), mas o rosto dela não precisa espelhar o dele. Amiga não é
  espelho.

## Proposta

### 1. Humor dela (estado de fundo)

- **Ânimo** −1..+1, base **+0,15** (orgulhosa, não neutra). Meia-vida de volta à base:
  **25 min quando acima da base, 8 min quando abaixo**.
- **Energia** 0..1, base pela hora: 08–12h 0,7 · 12–14h 0,5 · 14–19h 0,65 · 19–22h 0,6 ·
  22–02h 0,4 · 02–08h 0,2. Meia-vida de volta à base: 30 min.
- **Δ de ânimo** (aplicado uma vez por acontecimento, teto ±0,6 por hora vindo da mesma fonte):

  | Acontecimento | Δ ânimo | Δ energia |
  | --- | --- | --- |
  | faixa nota 2 começou | +0,25 | +0,15 |
  | faixa nota 1 | +0,10 | +0,10 |
  | faixa nota −1 | −0,10 | — |
  | faixa nota −2 | −0,20 | — |
  | Ado / Favorita do Dia | +0,30 | +0,15 |
  | Pedro pulou faixa que ela deu 2 | −0,15 (birra) | — |
  | Pedro voltou (>10 min fora) | +0,20 | +0,10 |
  | elogio (tag) | +0,30 | — |
  | zoeira do Pedro (tag) | +0,05 (ela gosta de briga) | +0,05 |
  | correção do Pedro (tag) | −0,10 | — |
  | Claude terminou / commit | +0,10 | — |
  | Claude erro | −0,10 | — |
  | faxina concluída | +0,15 (crédito dela) | — |
  | jogo abriu | +0,05 | +0,25 |
  | episódio de FPS/calor (uma vez por episódio) | −0,10 | — |
  | FPS recuperou | +0,10 | — |
  | silêncio total > 20 min (sem música, Claude parado) | −0,01/min, piso −0,20 | −0,01/min |

- **Rosto de repouso** (olhos pela energia, boca pelo ânimo):
  - olhos: energia ≥ 0,3 → B1; < 0,3 → B2 (pálpebra pesada).
  - boca: ânimo ≥ +0,55 → C5 (sorriso parado, "radiante") · +0,25..+0,55 → C10 (canto) ·
    −0,25..+0,25 → C1 · −0,55..−0,25 → C9 (emburrada) · < −0,55 → C4.
  - música nota 2 tocando: olhos sorrindo (B4) e C10 pela faixa inteira, independente do ânimo.
- **Fundo:** ânimo ≥ +0,55 `happy` · em jogo `focus` · episódio de FPS/calor `stress` · energia
  < 0,3 `sleepy` · ânimo < −0,55 `sad` · resto `calm`. `love` só em cena, nunca como repouso.
- **Medidor:** mostra o ânimo dela (barra 0–100% de −1..+1) com a cor do fundo e o nome do momento
  embaixo. O 0–4 do Pedro continua só por dentro.

### 2. Momentos (prioridade de cima para baixo; vale o primeiro que bate)

Hora e música são **camadas**, não momentos: madrugada (22–04h) tira zoeira, libera bocejo e põe o
fundo sonolento em qualquer momento; a música define o fone e pode subir o momento para "no flow".

| # | Momento | Como reconhece | Fone | Passivas permitidas | Repouso |
| --- | --- | --- | --- | --- | --- |
| 1 | **Conversa** | Magi ouvindo/falando, ou turno do Pedro há < 2 min | pescoço (tira para ouvir) | nenhuma | olhando para ele (F3), boca pelo ânimo |
| 2 | **Alerta** | disco cheio, rede caiu, PC desligando, popup de erro | como estava | nenhuma | B1 C1, fundo `surprise`/`stress` |
| 3 | **Pilotando** | jogo aberto | cabeça se há música | respirar, sacada_olhar, piscada_dupla; cabeca_ritmo só com nota ≥ 1 | B1 C1 focado, fundo `focus` |
| 4 | **Esperando** | Claude esperando o Pedro | como estava | impaciente, encarando, soprando_franja (1 por espera) | B1 C1 |
| 5 | **No flow** | Claude rodando ou Learning ligado **e** música nota ≥ 0 | cabeça | cabeca_ritmo (nota ≥ 1), piscada_gato, observando_hud | B1 C10, `focus` |
| 6 | **Trabalhando junto** | Claude rodando, sem música | pescoço | observando_hud, sacada_olhar, piscada_dupla; soprando_franja só com `claude/demorando` | B1 C1 + P10 (mão no queixo) após 2 min |
| 7 | **Estudando** | Learning ligado, sem música | pescoço | piscada_gato, sacada_olhar; ideia (rara) | B1 C1 + P10 |
| 8 | **Curtindo** | música nota ≥ 1 | cabeça | cabeca_ritmo, sorriso_canto, piscada_gato, ajeitando_fone; cantando_junto ≤ 1 por faixa | B4 C10 (nota 2) / B1 C10 (nota 1) |
| 9 | **Aturando** | música nota ≤ −1 | pescoço (tira no início da faixa) | sacada_olhar ao player, indiferente, soprando_franja (≤ 1 por faixa) | B1 C1 olhando de lado; nota −2 + P13 (braços cruzados) |
| 10 | **Ouvindo** | música nota 0 | cabeça | respirar, ajeitando_fone, sacada_olhar; cabeca_ritmo só se dançante | pelo ânimo |
| 11 | **Pedro sumiu** | inatividade > 10 min | pescoço se sem música | brilho_presilha, observando_hud, falando_sozinha (rara), cantarolando (rara, só sem música: as baladas secretas), bocejo se energia < 0,4; cochilo após 30 min com energia < 0,3 | pelo ânimo, olhar vagueando |
| 12 | **Tédio** | Pedro presente, nada rodando, sem música há > 15 min | pescoço | encarando (≤ 2/h), sacada_olhar, piscada_dupla, brilho_presilha; suspiro só após 30 min e ≤ 1/h | pelo ânimo |
| 13 | **À toa** | o resto | pescoço | respirar, piscadas, sacada_olhar, observando_hud, sorriso_canto se ânimo > +0,3; rindo_sozinha (rara) se ânimo > +0,5 | pelo ânimo |

Corando sozinha: só em Curtindo, Pedro sumiu ou À toa, ânimo > +0,5, ≤ 1/dia (com a contagem
gravada em disco). Beicinho sai da lista de passivas: vira reação da birra (faixa amada pulada,
zoeira do Pedro), ≤ 3/h.

### 3. Ritmo

- **Corpo vivo** (fora de tudo): piscada a cada 3–6 s, bob contínuo; não loga, não conta.
- **Passivas:** intervalo sorteado entre **4 e 8 min**, encurtado pela energia (energia 1 → 4 min,
  energia 0 → 8 min); **≤ 12/h**; raras ≤ 1/h no total.
- **Cenas:** ≤ 8/h; depois de uma cena, **60 s** sem passiva; **20 s** mínimos entre quaisquer duas
  coisas. Fala do Pedro, clique no retrato e volta do Pedro furam tudo. Alerta fura cota mas não
  corta Conversa.
- **Absorção:** acontecimento que chega durante uma cena e é do mesmo assunto (música, jogo,
  Claude) **vira variante dela ou é descartado**, nunca enfileira.
- **Todas as 110 + as 19 antigas passam pelo mesmo diretor.** Sem exceção.

### 4. Cenas (roteiros curtos)

- **Música começou** (fone no pescoço): `iris:F3 600` (olha o player) → `P11 E3→E2 1200`
  (colocando_fone) → clímax pelo gosto, um só: nota 2 `B4 C5 notas 2000` (ou piscadinha B16 se é
  Ado, sem blush) · nota 1 `B1 C10 1200` · nota 0 `B1 C1 600` · nota −1 `B1 C9 1000` e tira o
  fone de volta · nota −2 `P11 E2→E3 1000 | P13 B1 C9 2000`. Silencia os detectores de música
  por 90 s. Total ≤ 5 s.
- **Faixa trocou** (fone já na cabeça): só o clímax pelo gosto, sem colocar fone. Pulo rápido
  (< 30 s) não gera cena; três pulos seguidos geram **uma** (`impaciente`, e conta no placar).
- **Música parou:** `P11 E2→E3 1000` → `iris:F3 500` (olha para o Pedro) → repouso.
- **Pedro fala com ela:** fone para o pescoço em 800 ms, olhar F3; 10 s depois da resposta, se há
  música, recoloca.
- **Jogo abriu (entrando no cockpit):** `P12 B1 C10 800` (punho), fundo `focus`, fone na cabeça se
  há música. ≤ 2 s.
- **Episódio de FPS/calor:** 1º do episódio → cena `fps_drop` ou `hot` (≤ 2 s). Enquanto o episódio
  durar → **estado**: efeito suor no repouso + fundo `stress`, sem nova cena. FPS e calor juntos são
  o mesmo episódio. Episódio só termina com 3 min estáveis; novo episódio só conta depois de 10 min.
  **≤ 2 cobranças e 1 `recuperou` por partida.**
- **Jogo fechou (relatório pós-batalha):** sem episódios → `P12 B4 C5 1500` (vitória do cockpit);
  com episódios → `eu_avisei` (e se o Pedro estiver mal, `desconfiada` suave em vez disso). Uma
  linha de texto opcional com o placar real da partida (quedas de FPS, pico de temperatura).
- **Pedro voltou:** corta qualquer cena. Se ela cochilou: `sobressalto` → `iris:F3` → `tsundere`.
  Senão: `sentiu_falta` curto.
- **Claude terminou depois de > 5 min:** `B1 C10 1000` + brilho da presilha. Menos que 5 min, nada.

### 5. Consertos que eu exijo junto (curtos)

- Ajeitando o fone e cabeça no ritmo **nunca** sem música.
- "Fone em repouso" deixa de ser animação: é o E3 parado.
- "Colocando o fone" tem que sair toda vez que a música começa com o fone no pescoço.
- Contagem diária (corando, raras) persistida em disco; "HUD acordou" uma vez.

## Não abro mão

1. **Ela nunca vira estátua.** Corpo vivo (piscar, respirar, olhar para o acontecimento) fora da cota
   e um rosto de repouso que muda com o humor dela. Cortar a enxurrada não pode virar a Rei. Se ela
   ficar morta, a mudança falhou do mesmo jeito que a de agora.
2. **Careta negativa só com culpado.** Suspiro, beicinho e franja só aparecem apontando para uma
   causa dos últimos minutos. Ela não é a Shinji, e o medo de silêncio dela é segredo: aparece no
   humor, nunca em 89 suspiros.
