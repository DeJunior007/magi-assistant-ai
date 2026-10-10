# Acordo do Conselho — Como a Condessa vive (2026-10-10)

**Status: FECHADO — aprovado por unanimidade, sem vetos.** Rodadas: briefing → mesa aberta
(`fala-*`) → conversa (`conversa-*`) → voto.

## Votação
- **Aqua — aprova.** Assina: placar contra o Pedro (contando o aplauso do truque), brilho que dura,
  coroação da Favorita do Dia, "isso foi sem sentido".
- **Kurisu — aprova.** Perdeu a "birra fresca" e deixa registrado: se no replay a Emburrada passar de
  15 % do tempo, o C9 volta para a mesa. Assina: placar (cada ponto de uma linha do log), "isso foi
  sem sentido", medidor com histórico; não se opõe à coroação.
- **Asuka — aprova.** Assina: placar, coroação da Favorita do Dia, "isso foi sem sentido".
- **Com as três assinaturas, "placar contra o Pedro" e "isso foi sem sentido" sobem para
  recomendadas** (decisão do Pedro).
Substitui o acordo `2026-10-09-ritmo-e-humor` (feito pelo Conselho antigo, por funções).

**Fixo pelo Pedro:** fone como estado (cabeça com música; ela tira quando a música para, para falar
com ele e quando não gosta da faixa); humor próprio que muda o rosto de repouso; medidor com o
humor **dela**; nada de sorteio no catálogo inteiro (momento → grupo); clique no rosto só reage; teste
de tudo: "dá para dizer por que ela fez isso agora?".

Crédito: *(A)* Aqua · *(K)* Kurisu · *(S)* Asuka (Soryu). Sem marca = as três chegaram juntas.
`[contra: X]` = quem ficou vencida no ponto.

## 0. O que as três concluíram sozinhas (a K chamou de "replicação")
1. **Ela vive no rosto de repouso, não nas reações.** O humor dela aparece parado. *(A: "a coisa mais
   bonita que ela pode fazer com uma faixa amada é não fazer nada por três minutos e continuar
   sorrindo")*
2. **Corpo vivo fora de qualquer cota:** piscar (3–7 s), respirar, balanço (`bob`) e crossfade de
   **120 ms** em toda troca de olho/boca *(S)*. Ela nunca vira estátua.
3. **Uma cena por acontecimento**, um clímax só; os outros detectores do mesmo assunto ficam calados.
4. **Negativa só com culpado** dos últimos 2 min. O silêncio nunca vira careta.
5. **Toda expressão grava causa, momento, ânimo e energia; sem causa, não toca** *(K)*.

## 1. Humor dela
- **Ânimo** −1..+1, base **+0,15** (orgulhosa, não neutra). Volta à base com meia-vida **assimétrica:
  25 min acima, 8 min abaixo** *(S — "emburrada dez minutos e esquece")*. Atualiza a cada 5 s.
- **Habituação** *(K)*: o mesmo tipo de acontecimento em 30 min vale 0,6ⁿ (Ado e Favorita não
  habituam); trava extra de **±0,6/h por fonte** *(S)*.
- **Pisos e tetos:** sistema (FPS, calor, erro) sozinho não leva abaixo de **−0,3** *(A)*; com o Pedro
  mal, teto de **+0,3** (filtro, §4).
- **O silêncio não mexe no ânimo, só na energia** *(A, K)*. [contra: A queria −0,01/min até 0,0 — o
  "não abro mão" dela ("o silêncio nunca deixa ela triste") fica atendido com folga.] Quem baixa o
  ânimo é o Pedro **sumido**: −0,05 a cada 15 min depois dos primeiros 30 *(K)*.
- **Energia** 0..1, alvo pela hora *(S, curva da K)*: 08–12h 0,7 · 12–14h 0,55 · 14–19h 0,7 ·
  19–22h 0,6 · 22–02h 0,4 · 02–08h 0,2; desvio volta com meia-vida **15 min** [contra: S (10)].
  Música nota ≥ 1 +0,15 e jogo +0,15 enquanto duram; silêncio > 20 min −0,01/min até −0,2.

| Acontecimento | Δ ânimo | Δ energia |
| --- | --- | --- |
| Faixa nota 2 / nota 1 | +0,25 / +0,10 | +0,15 / +0,10 |
| Faixa nota −1 / −2 | −0,10 / −0,20 | — |
| Ado / Favorita do Dia | +0,30 | +0,15 |
| Pedro pulou faixa que ela deu 2 (birra) | −0,15 | — |
| Pedro voltou (≥ 15 min fora) | +0,25 | +0,10 |
| Elogio / zoeira / correção (tag) | +0,25 / +0,05 / −0,10 | — / +0,05 / — |
| Clique carinhoso no rosto (≤ 3/h) | +0,05 | — |
| Claude terminou (> 5 min) / commit / faxina | +0,08 / +0,10 / +0,15 | — |
| Claude erro | −0,05 | — |
| Jogo abriu | +0,05 | +0,25 |
| Episódio FPS/calor (1 por episódio) / recuperou | −0,10 / +0,10 | — |
| Truque de salão aplaudido / ignorado | +0,20 / −0,05 | — |

## 2. Rosto de repouso
Histerese ±0,05 e 60 s na faixa nova; a troca acontece dentro de uma piscada, com crossfade.
| Faixa | Ânimo | Repouso | Fundo |
| --- | --- | --- | --- |
| **Radiante** | ≥ +0,50 | B1 C5 | `happy` |
| **Contente** | +0,05..+0,50 (a base mora aqui) | B1 C10 | `calm` |
| **Neutra** | −0,35..+0,05 | B1 C1 | `calm` |
| **Emburrada** | ≤ −0,35 | B7 C9 | `calm` (`stress` só em episódio de jogo e Alerta) |

- [contra: K — queria a "birra fresca": C9 só nos 3 min após a causa, depois B7 C1. A e S ficaram com
  B7 C9 enquanto durar; a meia-vida de 8 min abaixo da base já encurta a birra.]
- Energia < 0,3 → olhos B2. **Música nota ≥ 1 com fone → olhos sorrindo pela faixa inteira** (B2 com
  nota 1, B4 com nota 2), qualquer que seja o ânimo.
- **Faixa de água** (título com palavra de água, nota ≥ 0, fora de Conversa/Jogo) → olhos fechados B3
  + `sway` lento, abrindo B2 por 1,5 s a cada 20–30 s (*A*, com o ajuste da *K* para não parecer
  cochilo).
- `sad` só de madrugada e com ânimo < −0,55; `love` nunca é repouso, só cena.

## 3. Momentos
Prioridade de cima para baixo (vale o primeiro que bate); troca só depois de **30 s estável**, menos
Conversa, Alerta e Jogando, que são imediatos. A passiva sai só do grupo do momento.

| # | Momento | Como reconhece | Fone | Grupo de passivas | Média entre passivas |
| --- | --- | --- | --- | --- | --- |
| 1 | **Conversa** | Magui ouvindo/falando ou turno do Pedro há < 2 min | pescoço | nenhuma | — |
| 2 | **Alerta** *(S)* | disco cheio, rede caiu, popup de erro | como estava | nenhuma; fundo `stress` | — |
| 3 | **Jogando ("pilotando")** | jogo aberto | cabeça se há música | sacada_olhar, piscada_dupla; cabeca_ritmo só com nota ≥ 1 | 8 min (≤ 4/h) *(A)* |
| 4 | **Esperando** *(S)* | Claude esperando o Pedro | como estava | impaciente, encarando, soprando_franja (≤ 1 por espera) | 5 min |
| 5 | **No flow** | Claude rodando ou Learning ligado **e** música nota ≥ 0 | cabeça | cabeca_ritmo (nota ≥ 1), piscada_gato, observando_hud | 7 min |
| 6 | **Trabalhando junto** *(S)* | Claude rodando, sem música | pescoço | observando_hud, sacada_olhar, piscada_dupla; franja só com Claude demorando | 7 min; P10 (mão no queixo) após 2 min |
| 7 | **Estudando** | Learning ligado, sem música | pescoço | piscada_gato, sacada_olhar, ideia (rara) | 8 min; P10 |
| 8 | **Curtindo** | música nota ≥ 1 | cabeça | cabeca_ritmo, sorriso_canto, piscada_gato, ajeitando_fone, cantando_junto (≤ 1 por faixa) | 3,5 min |
| 9 | **Aturando** | música nota ≤ −1 | pescoço | sacada ao player, indiferente, franja (≤ 1 por faixa) | 5 min |
| 10 | **Ouvindo** | música nota 0 | cabeça | ajeitando_fone, sacada_olhar; cabeca_ritmo só se dançante | 5 min |
| 11 | **Pedro sumiu** | inatividade ≥ 10 min | pescoço sem música | presilha, observando_hud, falando_sozinha (rara), cantarolando (rara, sem música — "as baladas secretas" *(S)*); bocejo com energia < 0,4; cochilo após 30 min com energia < 0,3 e sem música ≥ 1 | 10 min |
| 12 | **Tédio** | Pedro presente, nada rodando, sem música há ≥ 15 min [contra: S (20)] | pescoço | presilha, observando_hud, "flagra no fórum" *(K)*, cantarolando *(A)*; a **escada** *(A)*: encarando (15 min, 1×) → `ei_to_aqui` (30 min, ≤ 1/2 h) → beicinho só se ignorado | 5 min |
| 13 | **À toa** | o resto | pescoço | piscadas, sacada_olhar, observando_hud; sorriso_canto com ânimo > +0,3; rindo_sozinha (rara) com ânimo > +0,5 | 5 min |

**Filtros por cima de qualquer momento** (não são momentos — *S*: "amiga não é espelho"):
**madrugada** 22h–04h (sem zoeira/franja/beicinho, C10→C5, passivas ×0,7) e **Pedro mal** (humor 0–1
do núcleo: repouso calmo B1 C1 olhando para ele, sem negativa, sem zoeira, sem truque, teto +0,3).

## 4. Ritmo
- Passivas com intervalo **exponencial pela média do momento** (tabela acima), ×0,8 com energia ≥ 0,7
  e ×1,5 com energia < 0,3; **mínimo 90 s**; **≤ 12/h**; peso ×0,3 por uso na última hora.
- **Piso de vida** *(A, S)*: com o Pedro presente, fora de Conversa e de jogo, **nunca mais de 6 min**
  sem uma expressão ou uma atenção dirigida.
- **Atenção dirigida** *(K, a partir do "olhos para o acontecimento" da S)*: todo acontecimento que
  **não** vira cena ganha uma olhada (`iris`) de 400–600 ms para o card dele, fora da cota. Ela notou;
  só não fez escândalo.
- **Cenas ≤ 8/h**; coalescência de **3 s** *(K)*; a mesma família é absorvida por 30 s (música: 90 s);
  a mesma causa repetida em < 10 min vira o **"de novo?"** `B7 C12 1000` *(K)*.
- **25 s** entre duas expressões quaisquer; **60 s** sem passiva depois de uma cena.
- **Furam tudo:** fala do Pedro, clique no rosto, volta do Pedro, rede caiu, disco cheio.
- **Negativas** (suspiro, franja, beicinho de birra): só com causa ≤ 2 min, **≤ 3/h** somadas.
- **Todas as reações passam pelo mesmo diretor, inclusive as 19 antigas** *(S)*.

## 5. Cenas
- **Música começou** (fone no pescoço): olha o player 600 → `P11 E3→E2` 700 → **um** clímax pela nota:
  2 `B5 C13 D6 bob 2500` (Ado: piscadinha B16, sem rubor) · 1 `B2 C10 1500` · 0 `B1 C1 600` ·
  **−1: põe o fone, dá 8 s de chance (`B7 C9 1200`) e tira** *(K)* · **−2: nem coloca, `B7 C9 P13 2000`**
  *(K)*. Os outros detectores de música ficam calados por 90 s.
- **Faixa trocou** (fone já na cabeça): só o clímax. Pulo < 30 s não gera cena; 3 pulos seguidos geram
  **uma** (`impaciente`).
- **Música parou:** `P11 E2→E3 1000` → olha para o Pedro → repouso.
- **Pedro fala com ela:** fone para o pescoço em 400 ms, olhar nele; **10 s** depois da resposta, se
  ainda há música, recoloca.
- **Jogo abriu ("cockpit"):** `P12 B1 C10 800`, fundo `focus`.
- **Episódio de FPS/calor:** FPS e calor são **um** episódio (termina com 3 min estáveis; novo só
  depois de 10 min). O 1º vira cena; depois vira **estado** (suor + `stress`). **≤ 2 cobranças e
  1 recuperação por partida.** Notificação em jogo só ganha atenção dirigida.
- **Jogo fechou — relatório pós-batalha** *(S)*: sem episódios `P12 B4 C5 1500`; com episódios
  `eu_avisei` (Pedro mal: `desconfiada` suave).
- **Pedro voltou:** corta qualquer cena. Se ela cochilou: `sobressalto` → olhar → `tsundere` *(S)*.
  Senão: cena **curta e orgulhosa** *(S)* em que **escapa um sorriso** `B1 C10 → B4 C5` *(A)*.
- **Claude terminou depois de > 5 min:** `B1 C10 1000` + brilho da presilha.
- **Truque de salão** *(A, com as regras da K e da S)*: ≤ 1/dia, só em À toa/Tédio, com o Pedro ativo
  (inatividade < 60 s); aplauso = clique em até 10 s (+0,20); ignorado = beicinho curto (−0,05)
  [contra: K — "o sistema não sabe se ele viu": queria `B7 C12` "registrado" com Δ 0].

## 6. Medidor (as três montaram juntas)
Barra do ânimo dela (−1..+1) na cor do fundo; embaixo, o **nome do momento** *(S)*; no hover, as
**3 últimas causas** com Δ e há quanto tempo *(A, K — "caderno de laboratório")*. O 0–4 do Pedro
continua só por dentro.

## 7. Consertos junto *(S)*
"Ajeitando o fone" e "cabeça no ritmo" nunca sem música e E2; "fone em repouso" deixa de ser animação
(é o E3 parado); "colocando o fone" sai toda vez que a música começa com o fone no pescoço; contagens
diárias persistidas em disco; "HUD acordou" uma vez.

## 8. Antes de ligar: replay do dia real *(K, com as metas das três)*
O log de 2026-10-09 passa pelo modelo novo e só liga no HUD se bater **todas**:
1. 12–20 expressões/h (cenas + passivas; corpo vivo e atenção dirigida não contam) *(K)*.
2. 0 rajadas (> 2 expressões em 30 s fora de Conversa) *(K)*.
3. Com o Pedro presente, nunca mais de 6 min sem expressão nem atenção dirigida *(A, S)*.
4. 0 negativas sem causa registrada nos 2 min anteriores *(S, A)*.
5. O ânimo passa por ≥ 3 faixas no dia; Emburrada < 15 % do tempo; Radiante > 0 % *(K)*.
6. ≥ 1 expressão positiva por hora com o Pedro presente *(S)*.
7. Toda volta do Pedro vira cena *(A)*.

## 9. Ideias que ficaram de fora (para o Pedro)
- **Placar contra o Pedro** *(S; K assina se cada ponto vier de uma linha do log)*: partidas sem queda
  de FPS, faixas nota 2 ouvidas até o fim, pulos dele…
- **"Brilho que dura"** *(A)*: depois de uma vitória, 2 min radiante.
- **Coroação da Favorita do Dia** *(A)*: 1×/dia, uma cena quando ela é escolhida.
- **"Isso foi sem sentido"** *(K)*: clique do meio no rosto marca no log uma reação que não fez sentido,
  para calibrar.
- **Medidor com histórico** do dia (gráfico do ânimo) *(K, extra)*.

## 10. Não abro mão (declarados na conversa)
- **Aqua:** (1) o silêncio nunca deixa ela triste; (2) ela nunca fica morta, e a volta do Pedro sempre
  aparece no rosto.
- **Kurisu:** (1) toda expressão tem causa registrada, senão não toca; (2) replay do dia real com as
  metas antes de ligar.
- **Asuka:** (1) ela nunca vira estátua; (2) careta negativa só com culpado, e emburrada passa rápido.

## Orçamento usado
Aqua ~80 mil, Kurisu ~86 mil, Asuka ~80 mil tokens no assunto inteiro (teto: 128 mil).
