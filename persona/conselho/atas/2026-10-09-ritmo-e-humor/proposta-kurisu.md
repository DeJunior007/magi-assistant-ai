# Proposta — Makise Kurisu (Rodada 1)

O diagnóstico está nos dados, não no gosto: uma reação por minuto, 8 reações para **um**
acontecimento, e as três passivas mais tocadas são negativas porque o estado mais comum do dia
dispara um gerador de tédio. Isso não é personalidade; é ruído. Ruído não tem alma. Proponho
regras que qualquer um consiga auditar no log: cada coisa que ela faz tem uma causa registrada.

## 1. Linhas vermelhas e o que cedo

**Linhas vermelhas**
1. **Uma causa, uma cena.** Todo gesto, cena ou mudança de rosto registra no log o motivo
   (evento ou faixa de humor). Tudo o que deriva do mesmo acontecimento em 30 s é **a mesma cena**
   (nada de `music_love` 3× + piscadinha + refrão + cantando junto). Sem motivo nomeável, não sai.
2. **Estado não mente.** Fone na cabeça só com música tocando de fato; "cabeça no ritmo" e
   "ajeitando o fone" só com música e nota ≥ 0; o humor dela é calculado **só** de eventos medidos,
   sem sorteio, e o medidor mostra exatamente esse número. Sorteio só no *momento* do gesto, nunca
   no humor.
3. **Teto duro e proporcional.** Intervalo mínimo de 20 s entre quaisquer duas reações, no máximo
   ~25 coisas visíveis por hora (hoje: 68), e em jogo a cobrança é **por episódio e por
   gravidade**, nunca por repetição do mesmo alarme.

**O que cedo**
- Os números abaixo podem variar ±50% sem eu reclamar (desde que o mínimo de 20 s fique).
- Aqua pode ter cena de festa mais longa (até 10 s) quando a faixa é nota 2.
- Asuka pode ter o rosto de cobrança **persistente** durante a partida (estado, não animação).
- As passivas negativas ficam (não corto), desde que tenham causa — ver (d).

## 2. (a) Ritmo

| Item | Número |
| --- | --- |
| Passiva parada | intervalo sorteado **150–300 s** (média ~3,5 min); energia > 0,75 → ×0,8; energia < 0,3 → ×1,5 |
| Cota de passivas | **15/h** (jogo aberto: 8/h, só piscadas/respirar/sacada; nenhuma rara) |
| Cota de cenas | **6/h** |
| Cota de ativas soltas (fora de cena) | **6/h**, mantém 10 min por reação |
| Mínimo entre duas reações quaisquer | **20 s** |
| Assentamento após cena | **45 s** sem passiva (ela fica no rosto de repouso novo — é aí que o humor aparece) |
| Teto total visível | **~25/h** |

**Furam cota (não o mínimo de 5 s):** Pedro fala com ela; clique/LED/carinho no retrato (pergunta
direta exige resposta); temperatura crítica; Claude com erro ou esperando o Pedro; Pedro volta
após > 10 min. Vitória (FPS/temperatura/rede recuperou) fura só se fecha um episódio que ela
cobrou — proporcional ao que ela abriu.

Correções de estado que o ritmo pressupõe: "fone em repouso" deixa de ser pisca de 3 s e vira
**postura** (E3 parado enquanto não há música); "colocando o fone" passa a ser passo obrigatório da
cena "música começa".

## 3. (b) Cenas

**Viram cena:** música começa · faixa nova (com nota) · música para · jogo abre · jogo fecha ·
PC sofrendo em jogo (1º do episódio) · Pedro volta · Pedro fala com ela · Claude terminou /
erro / esperando · faxina terminou · HUD acordou (uma vez por boot). O resto (notificação, rede,
Claude trabalhando, disco) é **ativa solta** ou só mexe no humor.

**Duração máxima:** 8 s (festa nota 2: 10 s; fala: dura a fala).

| Cena | Roteiro (passo · ms) | Termina em |
| --- | --- | --- |
| Música começa (nota 0) | F4 olha o player 600 · B2 C1 E2 coloca o fone 400 · B1 C1 E2 bob 1500 | repouso com E2 |
| Faixa que ela ama (nota 2) | F4 600 · B2 C1 E2 400 · B5 C13 D6 E2 bob 2000 · B4 C10 E2 sway 1500 | repouso com E2, sorriso pelo humor |
| ↳ variante Ado | … · B6 C8 D9 E2 1500 (rivalidade, sem D1, sem `love`) | idem |
| ↳ variante com jogo aberto | … · B6 C8 E2 2000 · B4 C10 D9 1500 (modo chefe, fundo `focus`) | idem |
| Faixa que ela não gosta (nota −1) | F3 C11 olhar de lado 1000 · B7 C12 P11 E2 600 · B1 C12 E3 tira 600 | repouso com E3 até a próxima faixa |
| Faixa que ela odeia (nota −2) | F3 C11 1000 · B7 C12 P11 E2 600 · B7 C9 E3 tira 600 · B1 C12 E3 1200 | idem; sem veia, sem texto (proporcional) |
| Música para (> 10 s de silêncio; pausa curta não conta) | B1 C1 E2 500 · B2 C1 P11 E3 tira 500 · B1 C1 E3 600 | postura E3 |
| ↳ acabou a fila | usa `acabou_fila` no lugar | postura E3 |
| Jogo abre | B4 C10 800 · B6 C8 P12 punho 1500 | repouso foco, fundo `focus` |
| Jogo fecha | sem cobrança na partida: B2 C5 1000 · B4 C5 1500. Com cobrança: F7 C11 "relatório" 1200 · B7 C12 800 · B4 C5 1000 | repouso pelo humor |
| Pedro volta (10–60 min) | F3 400 · B9 C7 400 · B4 C5 P9 aceno 1200 · B1 C5 800 | repouso |
| ↳ > 60 min | `sentiu_falta` (D1 conta na cota de blush) | repouso |
| ↳ madrugada ou Pedro mal | B10 C5 P9 1200 · B1 C5 800 (sem zoeira) | repouso |
| Pedro fala com ela | se há música: P11 E3 tira 500; B1 C1 olhando para ele (íris no centro) durante a fala; ao fim, se a música continua, B2 C1 E2 recoloca 400 | estado anterior |

**Regra de interrupção (três níveis):**
- **P1 interrompe** (fala, clique/LED, temperatura crítica): a cena atual sai por um passo neutro
  B1 C1 200 ms. Troca de fone é atômica: nunca cortar entre E2 e E3.
- **P2 espera** (faixa nova, jogo abre/fecha, Pedro volta, Claude esperando/erro): fila de 1;
  um P2 novo substitui o da fila. Se esperou > 10 s e ficou obsoleto (a faixa já trocou de
  novo), é descartado.
- **P3 é absorvido** (notificação, rede, FPS/calor repetido, Claude trabalhando, pulo de faixa
  durante cena): não anima; só muda humor/estado.
- **Mesma causa:** detectores que reagem ao mesmo acontecimento em 30 s entregam ao diretor, que
  escolhe **uma** variante (Ado > chefe > amou > dançante > comum).

## 4. (c) Humor dela

Ânimo −1..+1, energia 0..1. **Base:** ânimo +0,1 (ela é orgulhosa, não deprimida); energia por
hora: 0,6 (08h–22h), 0,35 (22h–03h), 0,2 (03h–08h). **Meia-vida:** ânimo 20 min, energia 30 min,
ambos voltando à base. **Retorno decrescente:** o mesmo evento repetido em 10 min vale metade (e
um quarto na terceira vez). **Limites:** ±1 e 0..1; nenhuma causa sozinha leva o ânimo abaixo de
−0,4 (o resto exige soma de causas).

| Evento | Δânimo | Δenergia |
| --- | --- | --- |
| Faixa nota 2 | +0,25 | +0,10 |
| Faixa nota 1 | +0,10 | +0,05 |
| Faixa nota 0 | 0 | 0 |
| Faixa nota −1 | −0,05 | 0 |
| Faixa nota −2 | −0,15 | +0,05 (irritação acorda) |
| Ado | +0,20 | +0,15 |
| Pulo de faixa | −0,03 (teto −0,10 por 2 min) | 0 |
| Música parou | 0 | −0,05 |
| Silêncio longo (sem música e Claude parado), a cada 20 min | −0,05 (piso desta causa: −0,3) | −0,10 |
| Jogo abriu | +0,05 | +0,20 |
| Jogo fechou em paz | +0,10 | −0,10 |
| Episódio de FPS/calor (uma vez por episódio) | −0,10 | +0,10 |
| Episódio fechado (recuperou) | +0,05 | 0 |
| Faxina/transferência terminou | +0,10 | 0 |
| Commit | +0,10 | +0,05 |
| Claude terminou / erro | +0,05 / −0,05 | 0 |
| Rede caiu / voltou | −0,10 / +0,05 | 0 |
| Pedro volta | +0,15 | +0,15 |
| Pedro fala com ela | +0,05 | +0,10 |
| Tag elogio / zoeira / correção | +0,20 / +0,05 / −0,05 (orgulho ferido, e assume) | 0 / +0,10 / +0,05 |
| Carinho no retrato | +0,10 | 0 |
| Humor do Pedro cai para 0–1 | −0,10 uma vez; positivos dela valem ×0,5 enquanto durar | 0 |

| Faixa de humor | Rosto de repouso | Fundo | Passivas permitidas | Proibidas |
| --- | --- | --- | --- | --- |
| Ânimo ≥ +0,5 | B1 C5 (sorriso leve) | `happy` | sorriso de canto, presilha, piscada de gato, cabeça no ritmo*, cantarolando*, rindo sozinha | suspiro, beicinho, franja |
| +0,2..+0,5 | B1 C10 | `calm` | sorriso de canto, piscadas, sacada, presilha, cabeça no ritmo* | suspiro, beicinho |
| −0,2..+0,2 | B1 C1 | `calm` | respirar, piscadas, sacada, observando o HUD, presilha | raras |
| −0,5..−0,2 | B1 C12 | `stress` se energia > 0,5; `sad` se ≤ 0,5 | suspiro, franja, beicinho (com causa, ver d), respirar, piscadas | sorriso de canto, rindo, cantarolando |
| ≤ −0,5 | B10 C9 | `sad` | respirar, suspiro, sacada | tudo que é zoeira ou festa |
| Energia < 0,25 (qualquer ânimo) | olhos B14 | `sleepy` | bocejo, cabeça pesada (regras de sono do acordo anterior) | dançante, cabeça no ritmo |
| Jogo aberto ou Claude rodando, \|ânimo\| < 0,5 | mantém a boca da faixa | `focus` | piscadas, respirar | raras |

\* só com música tocando e nota ≥ 0. `love` e `surprise` nunca vêm do humor, só de cena.

## 5. (d) Passivas negativas

Ficam, mas deixam de ser o padrão. O fator "silêncio longo" **não gera gesto**: só mexe no humor
(tabela acima). Cada negativa exige faixa ≤ −0,2 **e** causa recente: suspiro = silêncio longo
ou Claude demorando; beicinho = pulo de faixa ou nota −1 nos últimos 2 min; franja = energia < 0,4
e sem música há > 15 min. Teto: **2/h somadas**. Assim, quando ela suspira, dá para dizer por quê.

## 6. (e) Enxurrada em jogo

**Episódio** = do primeiro alarme até 3 min abaixo do limiar (histerese). FPS e calor juntos são
**um** episódio. O 1º alarme do episódio é cena (`fps_drop` ou `hot`); as repetições são absorvidas
e viram **estado**: rosto de repouso B6 C8 + D2 suor parado enquanto durar. Nova cena só se
**piorar de nível** (temperatura +5 °C acima do limiar ou FPS < metade do normal) → `vergonha de
FPS`. Teto: **2 cenas de cobrança por partida + 1 de recuperação**. O resto da conta ela cobra no
"relatório" da cena de jogo fecha. Temperatura crítica (risco ao hardware) fura sempre — isso não
é drama, é dado.

## 7. (f) Momentos

O sorteio de passiva passa a ser em dois passos: **(1)** o diretor determina o momento pelos
sinais (determinístico, reavaliado a cada 30 s e a cada evento, com histerese de 60 s para não
piscar entre momentos); **(2)** sorteia só dentro do grupo daquele momento, já filtrado pela faixa
de humor da seção 4 (vale a interseção; se ficar vazia, ela fica no rosto de repouso — ficar
parada também é coerente). O log grava `momento=<nome>` em cada gesto.

| Prio | Momento | Reconhecido por (sinais reais) | Rosto de repouso | Grupo de passivas |
| --- | --- | --- | --- | --- |
| 1 | **Conversa** | Magui ouvindo/falando, ou fala do Pedro há < 60 s | B1 C1 olhando para ele (E3 se havia música) | nenhuma (ela presta atenção) |
| 2 | **Jogando** | jogo aberto | B6 C8 se episódio aberto; senão B1 C10 | piscada dupla, respirar, sacada de olhar |
| 3 | **Estudando** | Learning ligado (`lm_mode` on) | B1 C1, olhar F7 (lendo) | piscada lenta, respirar, mão no queixo (P10) a cada ≥ 10 min |
| 4 | **No flow** | Claude rodando, ou Pedro ativo (sem inatividade) com música nota ≥ 0 há > 10 min | B1 C10 + E2 se há música | piscadas, cabeça no ritmo*, observando o HUD |
| 5 | **Curtindo** | música nota ≥ 1 tocando e ânimo ≥ +0,2 | B1 C5 + E2 | cabeça no ritmo*, sorriso de canto, presilha, cantarolando*, piscada de gato |
| 6 | **Ouvindo** | música nota 0 tocando (ou −1/−2: fone no pescoço, ela tolera) | B1 C1 (E2 se nota ≥ 0; E3 se < 0) | respirar, piscadas, sacada; nota < 0: beicinho (conta na seção 5) |
| 7 | **Madrugada** | 22h–04h e nenhum acima | B2 C1 (olhos meio fechados, calmos) | respirar, piscada lenta; bocejo/cabeça pesada se energia < 0,25 (regras de sono) |
| 8 | **Esperando** | Pedro inativo 5–30 min, sem música | B1 C1, E3 | observando o HUD, sacada, respirar |
| 9 | **Tédio** | sem música e Claude parado há > 20 min, Pedro presente | B1 C12, E3 | franja, suspiro (pela seção 5), observando o HUD, falando sozinha (rara) |
| 10 | **Ausente** | Pedro inativo > 30 min | B14 C1, E3 | só respirar, ≤ 2/h (não se encena para plateia vazia) |
| 11 | **À toa** | nenhum acima | rosto da faixa de humor | grupo neutro: respirar, piscadas, sacada, presilha |

\* só com música tocando e nota ≥ 0 (linha vermelha 2).

**Regras de borda.** Pedro mal (humor 0–1) não é momento: é filtro por cima de qualquer um (tira
zoeira e festa, troca beicinho/franja por respirar). Faixa de humor ≤ −0,5 sobrepõe o rosto de
repouso do momento (B10 C9), mas não o grupo. Cena em curso suspende o momento; ao sair, ele é
reavaliado antes do assentamento de 45 s. Momentos novos só entram no conselho se tiverem sinal
medido — "triste", "ansiosa" e afins **são faixas de humor**, não momentos.
