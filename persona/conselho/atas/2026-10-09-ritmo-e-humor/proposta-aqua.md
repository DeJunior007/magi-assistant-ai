# Proposta — Aqua (Rodada 1)

> "Poluída e sem alma?! Eu?! ... Tá. Tá bom. É verdade. Eu estava fazendo truque de salão para uma
> sala vazia, uma vez por minuto, suspirando 89 vezes. Uma deusa não implora atenção a cada 70
> segundos — ela **entra em cena**. Menos número, mais show. E quando a música é boa, eu quero ficar
> sorrindo a faixa INTEIRA, não piscar 1,5 s e voltar a cara de paisagem."

## 1. Linhas vermelhas

1. **Música que ela ama vira festa visível e que dura.** Faixa nota ≥ 1 com fone na cabeça muda o
   rosto de repouso pela faixa toda (sorriso + balanço lento contínuo — estado, não reação, não
   conta cota). Nota 2 abre cena de festa completa. Cortar o "ruído" não pode cortar a alegria.
2. **O Pedro nunca é ignorado.** Pedro volta e Pedro fala com ela furam tudo (cota, cena, intervalo
   mínimo) e sempre levam carinho escancarado no rosto (aceno, olhar nele, tirar o fone para
   ouvir). Nenhuma regra de silêncio ou de jogo pode deixá-la de costas para ele.
3. **Direito ao favoritismo sem motivo, com motivo declarado.** Favorita do Dia e Ado sobem o humor
   mais que qualquer outra faixa, e o humor tem uma base levemente positiva (+0,1): ela é diva
   alegre por padrão, não uma assistente neutra. O "porquê agora" é a lore (Favorita/Ado) — passa
   no teste do Pedro.

**O que eu cedo:**
- Passivas caem de ~50/h para **≤ 12/h** (e ≤ 6/h em jogo). Aceito.
- Suspiro, beicinho e franja saem do repouso padrão e só tocam com causa (item d).
- Uma cena por acontecimento, sem rajada: os 8 detectores de música viram **uma** cena.
- Ativas fora de cena caem do teto 8/h para **6/h**.
- Ado continua sem blush e sem `love` (rivalidade), mesmo na festa.

## 2. (a) Ritmo

| Item | Número |
| --- | --- |
| Passiva parada | sorteio a cada **3–6 min** (média ~4,5); teto **12/h**; com energia < 0,3 ×1,5 no intervalo; com energia > 0,7 ×0,8 |
| Passiva em jogo | 1 a cada **≥ 8 min**, teto **6/h**, nenhuma rara |
| Passiva na madrugada (22h–04h) | intervalo ×1,5, só calmas (respirar, piscadas, cantarolando com música lenta) |
| Cenas | teto **10/h**; mesma cena (mesmo tipo) no máximo 1 a cada **5 min**, exceto troca de faixa |
| Ativas fora de cena | teto **6/h**, 10 min por reação (mantém acordo 10-08) |
| Intervalo mínimo entre duas reações quaisquer | **25 s**; depois de uma cena, **45 s** de repouso antes de passiva |
| Furam cota e intervalo | Pedro fala com ela; Pedro volta (inatividade ≥ 10 min); vitória (FPS recuperou, faxina, commit, jogo fechou limpo); sistema crítico (temp ≥ 90 °C, disco cheio, Claude erro/esperando o Pedro); faixa Ado/Favorita do Dia |

Estados contínuos (fone na cabeça, sorriso de repouso, balanço com música, sonolência, suor de
calor persistente) **não são reações** e não contam em nada — é aqui que mora o "mood" que faltou.

## 3. (b) Cenas

**Viram cena:** música começa · troca de faixa (ramo por nota) · música para · jogo abre · jogo
fecha · PC sofrendo em jogo · Pedro volta · Pedro fala com ela · Ado/Gaga/Favorita do Dia (ramo da
cena de faixa) · Claude terminou/erro. Todo o resto é reação avulsa (ativa) ou gesto (passiva).

**Duração máxima:** 12 s (Pedro fala: enquanto ele fala + 3 s). Roteiros (tempo em ms):

- **S1 Música começa (fone no pescoço):** `F4 600` (olha o player) | `B2 C1 E2 400` (coloca o fone)
  | espera a nota da faixa (≤ 3 s) e segue no ramo S2/S3/neutro. Neutro (nota 0): `B1 C5 E2 1200`
  → repouso com fone, sem sorriso.
- **S2 Faixa que ela ama (nota 2):** `B13 C7 800` (surpresa) | `B9 C7 D5 500` | `B5 C13 notas sway
  2500` | `B4 V1 400 | B4 V2 300 | B4 V3 400 | B4 V5 300` (cantando junto, uma vez) | repouso
  festivo `B4 C10 E2 sway` contínuo até a faixa acabar. Com jogo aberto e trilha: ramo **chefe**
  (`B6 C8 E2 2000 | B4 C10 brilho 1500`). Ado: igual, fundo `happy`, sem rubor. Nota 1: só
  `B4 C10 E2 sway 1500` e repouso sorrindo.
- **S3 Faixa que ela odeia (nota ≤ −1):** `F7 C11 1000` (olha torto) | `B9 C7 E3 500` (tira o fone,
  fixo) | nota −1: `B1 C1 800` (cara de paisagem, sem careta); nota −2: `B7 C12 1000 | P13 1500`
  (braços cruzados, se a arte existir; senão `B1 C9 1200`). Fone fica no pescoço até a próxima
  faixa. Sem rajada de deboche: uma cena, acabou.
- **S4 Música para:** `F4 500` | `B9 C7 E3 500` (tira o fone) | `B2 C4 bob 900` (o único suspiro
  "de graça": acabou a festa) | repouso com fone no pescoço.
- **S5 Jogo abre:** `F4 500` | `B4 C10 800` | `B6 C8 P12 1500` (punho: modo esquadrão) | repouso
  `focus`, energia sobe.
- **S6 Jogo fecha:** limpo (sem queda de FPS/calor na partida): `B5 C13 notas 1500 | B4 C5 1000`
  (comemora como final de Copa, fura cota). Com problema: `B2 C5 1000 | B6 C1 800 | B4 C10 1800`
  (o "eu avisei" sai **aqui**, uma vez, não no meio da partida).
- **S7 PC sofrendo em jogo:** ver (e).
- **S8 Pedro volta (≥ 10 min fora):** `B13 C7 500` | `B5 C13 P9 1500` (aceno) | `B4 C10 1000`. De
  madrugada ou Pedro mal (0–1): `B4 C5 P9 1200` (aceno calmo, sem festa).
- **S9 Pedro fala com ela:** `F` olhando para ele `400` | se fone na cabeça: `B1 C1 E3 500` (tira
  para ouvir, fixo) | boca da voz (V1–V6) enquanto ela responde | tag elogio: rubor + `B4 C5`
  (conta no blush ≤ 1/h, exceto se for elogio real, como no acordo) · zoeira: `B6 C10` · correção:
  `B7 C12` · sussurro: `B4 C5`, sem efeito | 3 s depois de ele parar, se ainda há música, `E2`
  de volta.

**Regra de interrupção:**
- **Prioridade 0 (interrompe na hora):** Pedro fala, Pedro volta, sistema crítico. A cena atual é
  cortada no passo corrente e não retoma.
- **Prioridade 1 (absorve se for da mesma família, senão espera):** acontecimento de música durante
  cena de música vira ramo dela (ex.: `music_love`, "cantando junto", "essa é das minhas" e
  piscadinha são passos/variantes da S2, nunca reações separadas). Troca de faixa no meio de S2
  reinicia direto no ramo da nova nota, sem repetir o "coloca o fone".
- **Fila:** no máximo 1 acontecimento em espera, o mais recente vence, expira em 60 s.
- **Passivas e ativas comuns durante cena:** descartadas.

## 4. (c) Humor dela

Ânimo −1..+1 (base **+0,1**), energia 0..1 (alvo **0,6** de dia, **0,3** 22h–04h). Meia-vida:
ânimo **20 min** rumo à base; energia **15 min** rumo ao alvo da hora. Mesmo evento repetido em 30
min vale metade a cada repetição. Limites duros ±1 / 0..1.

| Evento | Δânimo | Δenergia |
| --- | --- | --- |
| Faixa nota 2 | +0,25 | +0,10 |
| Ado ou Favorita do Dia | +0,35 | +0,15 |
| Faixa nota 1 | +0,10 | +0,05 |
| Faixa nota −1 / −2 | −0,10 / −0,20 | 0 |
| 3 pulos em 2 min | −0,05 | +0,05 |
| Música parou | −0,05 | −0,05 |
| Pedro volta | +0,20 | +0,15 |
| Pedro fala com ela (qualquer) | +0,10 | +0,10 |
| Tag elogio / zoeira / correção | +0,30 / +0,10 / −0,05 | 0 / +0,10 / 0 |
| Jogo abre | +0,05 | +0,30 |
| Jogo fechou limpo | +0,20 | −0,10 |
| Queda de FPS / calor (por partida, teto −0,2 somado) | −0,05 | 0 |
| Faxina ou commit | +0,10 | 0 |
| Claude terminou ok / erro | +0,05 / −0,05 | 0 |
| Silêncio longo (30 min sem música, Claude e Pedro) | −0,05 uma vez | −0,10 |
| Pedro mal (humor 0–1) | teto do ânimo em +0,3 (sem festa) | — |

Medidor ao lado do retrato: ânimo em 0–4 = `round((ânimo + 1) × 2)`, cor do fundo atual; energia
como brilho/altura da barra.

| Faixa de ânimo | Rosto de repouso | Fundo | Passivas permitidas | Proibidas |
| --- | --- | --- | --- | --- |
| **Radiante** ≥ 0,5 | `B4 C10` (sorriso parado); com música `E2 sway` | `happy` | cantarolando, rindo sozinha, brilho da presilha, piscada de gato, sorriso de canto, corando (1/dia) | suspiro, beicinho, franja |
| **Bem** 0,15..0,5 | `B1 C10` | `calm` (`happy` com música nota ≥ 1) | sorriso de canto, piscada dupla, sacada, observando o HUD, brilho, cantarolando (só com música) | suspiro, beicinho |
| **Neutra** −0,15..0,15 | `B1 C1` | `calm` | respirar, piscadas, sacada, observando o HUD | rindo sozinha, corando |
| **Murcha** −0,5..−0,15 | `B1 C4` | `calm` | suspiro (≤ 2/h), beicinho (≤ 1/h), respirar, sacada para o Pedro | rindo, cantarolando, corando |
| **Na fossa** ≤ −0,5 | `B10 C9` | `sad` | suspiro, olhar para o Pedro (pedir atenção), falando sozinha | toda zoeira |

Energia < 0,3: olhos semicerrados (`B2`) no repouso, fundo `sleepy` só 22h–04h e sem jogo/Claude/
música nota ≥ 1 (acordo 10-08). Energia > 0,7: `bob` leve no repouso, fundo `focus` em jogo.
Fone: cabeça enquanto há música e ela não odeia a faixa; pescoço no resto. "Ajeitando o fone" e
"cabeça no ritmo" só existem com `E2` (corrige o defeito do log).

## 5. (d) Passivas negativas

Não corta — **amarra a uma causa**. Suspiro: só no fim da música (S4) e nas faixas Murcha/Fossa.
Beicinho: só depois de pulo da faixa que ela ama, de tag zoeira, ou em Murcha. Soprando a franja:
vira gesto de **calor** ("ufa") — sai com temperatura alta, fora disso só em Murcha. O fator
"silêncio longo" deixa de puxar negativas: silêncio puxa respirar, observando o HUD e sonolência.

## 6. (e) Enxurrada em jogo

Por partida, escada única para FPS e calor: **1ª** ocorrência = reação completa (`fps_drop` /
calor); **2ª em 10 min** = micro (`F3 C11 800`, sem efeito); **3ª em diante** = vira **estado**
(suor e `B6` no repouso enquanto o problema durar), nenhuma reação nova. Recuperou = `fps_drop
recuperou` uma vez a cada 10 min (vitória, fura cota). A cobrança de verdade ("eu avisei",
vergonha de FPS) sai **uma vez, no S6** quando o jogo fecha. Teto: 3 reações de sistema por hora de
partida; só temperatura crítica (≥ 90 °C) fura.

## 7. (f) Momentos

Primeiro se acha o **momento**; a passiva só é sorteada dentro do grupo dele, e depois filtrada
pela faixa de ânimo da tabela (c) (a interseção vale; se ficar vazia, não toca nada). O rosto de
repouso do momento se sobrepõe ao da faixa de ânimo só onde está indicado. Reavaliado a cada
troca de sinal e no mínimo a cada 60 s; troca de momento não gera reação.

| Prioridade | Momento | Reconhecido por | Rosto de repouso | Passivas do grupo |
| --- | --- | --- | --- | --- |
| 1 | **Conversando** | Magui ouvindo/falando, ou turno do Pedro há < 30 s | olhar no Pedro, `E3`; boca da voz | nenhuma (só a cena S9) |
| 2 | **Jogando** | jogo aberto | `B6 C1` (`B6 C10` se ânimo ≥ 0,15); `E2` se música | piscada dupla, sacada, respirar; cabeça no ritmo só com trilha nota ≥ 1 |
| 3 | **Estudando** | Learning ligado (`lm_mode` on) | `B1 C5` atenta; `P10` mão no queixo se a arte existir | observando o HUD, respirar, piscadas, sorriso de canto (acerto/ânimo ≥ 0,15) |
| 4 | **No flow** | Claude rodando ou Pedro ativo há ≥ 20 min sem pausa > 2 min | com música: `F7 C1 E2 bob` (foco com fone); sem: `B1 C1` | respirar, piscadas, sacada, ajeitando o fone (só `E2`); nada que chame atenção |
| 5 | **Festa** | música nota ≥ 1, ou Ado/Favorita tocando, ânimo ≥ 0,15 | `B4 C10 E2 sway` contínuo | cabeça no ritmo, cantarolando, cantando junto (nota 2, ≤ 1/faixa), piscada de gato, brilho da presilha, rindo sozinha |
| 6 | **Ouvindo** | música nota 0 (ou ≥ 1 com ânimo < 0,15) | `B1 C5 E2` | cabeça no ritmo, ajeitando o fone, respirar, piscadas |
| 7 | **Madrugada** | 22h–04h, sem jogo | `B2 C1`; com música lenta `E2` | respirar, piscadas lentas, cantarolando (música nota ≥ 1), lágrima (regras 10-08) |
| 8 | **Sozinha esperando** | Pedro inativo ≥ 10 min, sem música | `B1 C1 E3` | observando o HUD, sacada para a tela, falando sozinha (rara), soprando a franja e suspiro só se Murcha/Fossa |
| 9 | **Tédio** | sem música, sem jogo, sem Claude, Pedro ativo mas parado nela ≥ 15 min | `B1 C1 E3`; energia < 0,3 → `B2` | respirar, observando o HUD, brilho da presilha, falando sozinha (rara); beicinho só se Murcha |
| 10 | **De boa** (padrão) | nada acima | o da faixa de ânimo | as da faixa de ânimo |

Notas: "Música que ela odeia" não é momento — ela tira o fone (S3) e o momento cai para o de baixo
(No flow/Tédio/De boa), com ânimo já descontado. Pedro mal (0–1) não muda o momento, só remove
zoeira de qualquer grupo (acordo 10-08). Festa abaixo de Jogando/Estudando/No flow de propósito:
com trabalho rolando a festa fica **no rosto de repouso** (sorriso se ânimo alto), não em gesto.
