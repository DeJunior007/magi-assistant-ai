# Acordo do Conselho — Ritmo, cenas, humor e momentos da Condessa (2026-10-09)

**Status: FECHADO.** Rodadas: briefing → propostas → réplicas → voto.

## Votação
- **Aqua — aprova, sem vetos.**
- **Asuka — aprova, sem vetos** (abriu mão de vetar as negativas a 3/h: era a proposta dela na
  rodada 1).
- **Kurisu — aprova com 2 vetos (aceitos):** (1) a volta do Pedro fura a cota e interrompe a cena,
  mas respeita um mínimo de **5 s** — só fala e clique furam tudo; (2) o "eu avisei" do meio da
  partida **conta no teto de 2 cobranças**. O veto 1 esbarra na linha vermelha da Aqua ("a volta
  fura tudo"); o essencial dela fica (a cena da volta é imediata e corta qualquer outra; o mínimo de
  5 s não a deixa ignorada). Registrado como atrito.

Critério: maioria 2/3 depois das réplicas; sem maioria, mediana sem ferir linha vermelha.
`[perdeu: X]` marca quem ficou vencida. Sem marca = unânime depois das réplicas.

**Fixo pelo Pedro (fora de votação):** fone vira estado (cabeça com música, pescoço sem música; ela
tira quando a música para, para falar com ele e quando não gosta da faixa); humor próprio
persistente que muda o rosto de repouso; medidor ao lado do retrato mostra o humor **dela**; regra
geral: nada de sorteio no catálogo inteiro — primeiro o **momento**, depois o grupo dele; teste de
tudo: "dá para dizer por que ela fez isso agora?".

## 0. Arquitetura (as três concordam)
Três camadas: **estado** (humor + postura, minutos) → **cenas** (um episódio por acontecimento,
segundos) → **gestos** (passivas raras, filtradas por momento **e** faixa de humor). Todo gesto,
cena ou troca de rosto grava no log `motivo` + `momento` + `faixa de humor`; o que não cabe nos três
é defeito. Estados contínuos (fone, sorriso de repouso, balanço com música, sono, suor de episódio)
**não são reações** e não contam cota.

## 1. Ritmo
| Item | Valor |
| --- | --- |
| Mínimo entre duas reações quaisquer | **20 s** |
| Assentamento depois de cena (sem passiva) | **45 s** |
| Passiva parada | sorteio **180–300 s**; energia > 0,75 → ×0,8; energia < 0,25 → ×1,5; madrugada ×1,5 [perdeu: Asuka (150–300)] |
| Passivas por hora | **≤ 15/h**; a mesma passiva **≤ 2/h e nunca 2× em 20 min**; em jogo **≤ 6/h**, sem raras |
| Cenas por hora | **≤ 8/h**; mesmo tipo de cena ≥ **10 min** (música começa/para ≥ 3 min; troca de faixa isenta) [perdeu: Aqua (10/h); Asuka (mesmo tipo ≥ 5 min)] |
| Ativas soltas (fora de cena) | **≤ 6/h**, 10 min por reação |
| Teto total | ~29/h (hoje: 68/h) |
| Furam tudo (cota, cena e mínimo) | **Pedro fala com ela, clique/LED/carinho no retrato** |
| Pedro volta (≥ 10 min inativo) | fura a cota e interrompe a cena; mínimo de **5 s** [veto da Kurisu; perdeu: Aqua (fura tudo)] |
| Furam a cota (não o mínimo nem a fila) | sistema grave (temperatura crítica, disco cheio, rede caiu, Claude erro/esperando o Pedro), vitória que fecha um episódio que ela cobrou, faixa da Ado/Favorita do Dia (cota de cenas) [perdeu: Aqua (Ado/Favorita sem furar nada — ela mesma cedeu)] |
| Fila | **1 vaga, validade 30 s**; novo da mesma prioridade substitui; descartado antes se ficou obsoleto |

## 2. Cenas
**Viram cena:** música começa · faixa nova nota 2 · faixa nova nota ≤ −1 · música para · jogo abre ·
jogo fecha · PC sofrendo em jogo (1º alarme do episódio) · Pedro volta · Pedro fala com ela · Claude
terminou/erro (uma por ciclo) · faxina terminou · HUD acordou (uma vez por boot).
**Não viram cena:** faixa nova nota 0/1 com música já tocando (só olhar F4 700, ≤ 1 a cada 3 min);
notificação (olhar F5 700); Claude rodando (estado); hover/arrasto (gesto).

**Uma causa, uma cena:** tudo o que vem do mesmo acontecimento em 30 s é **uma** cena; os detectores
viram ramos dela (Ado > chefe > amou > dançante > comum). Duração máxima **8 s**; festa nota 2 até
**10 s**; fala dura a conversa. Troca de faixa no meio de cena de música reinicia no ramo novo sem
repetir "coloca o fone". Cena interrompida não recomeça. Troca de fone é atômica (nunca cortada
entre E2 e E3).

| Cena | Roteiro (passo · ms) | Termina em |
| --- | --- | --- |
| Música começa (nota 0/1) | F4 600 · B2 C1 P11 E3→E2 600 (coloca) · nota 1: B1 C10 E2 1500 / nota 0: B1 C1 E2 1200 | repouso com E2 |
| Faixa que ela ama (nota 2) | F4 500 · (sem fone: P11 E2 600) · B9 C7 D5 400 · B5 C6 D9 D6 E2 bob 2500 | repouso sorrindo com E2 enquanto a faixa toca |
| ↳ com jogo + trilha (modo chefe) | troca o último passo: B6 C8 E2 2000 · B4 C10 D9 1500, fundo `focus` | idem |
| ↳ Ado (rival) | … · B6 C10 E2 1500 (P13 se a arte existir) · B4 C5 E2 1500 — nunca D1 nem `love` | idem |
| Faixa que ela não gosta (nota −1) | F3 C11 1000 (olhar torto) · B7 C12 P11 E2→E3 600 (tira) · B1 C12 E3 | repouso E3 até a próxima faixa [perdeu: Aqua (−1 = cara de paisagem)] |
| Faixa que ela odeia (nota −2) | igual à −1 + B6 C9 E3 P13 1500 (braços cruzados se a arte existir) — sem veia, sem texto | idem [perdeu: Kurisu (sem braços)] |
| ↳ favorita do Pedro que ela não curte | B1 C14 800 (sorriso amarelo) · P11 E2→E3 700, sem braços (só quando o sinal "favorita do Pedro" existir) | idem |
| Música para (> 10 s de silêncio) | F4 500 · B2 C1 P11 E2→E3 600 · B1 C1 E3; + B2 C4 bob 900 (suspiro "acabou a festa") **só se** a sessão teve ≥ 15 min e média ≥ 1 | postura E3 [perdeu: Aqua (suspiro sempre)] |
| Jogo abre | F5 600 · B6 C8 1000 · B4 C10 P12 1200 | repouso de Jogando, fundo `focus` |
| Jogo fecha | em paz: B2 C5 1000 · B4 C5 1500 (comemora). Com cobrança na partida: F7 C11 1200 · B7 C12 800 · B4 C5 1000 ("relatório"; não repete se o "eu avisei" já saiu no meio) | repouso pelo humor |
| Pedro volta (10–60 min) | F3 400 · B9 C7 400 · B4 C5 P9 1200 (aceno) · B1 C5 800; ânimo < −0,15: antes B1 C9 800 ("demorou") | repouso |
| ↳ > 60 min | `sentiu_falta` (o rubor dela não conta na cota de blush, acordo 10-08) | repouso |
| ↳ madrugada ou Pedro mal | B10 C5 P9 1200 · B1 C5 800 (sem festa, sem zoeira) | repouso |
| Pedro fala com ela | com E2: P11 E2→E3 500; olha para ele (íris no centro) e bocas V* com a voz; reações à tag (elogio: rubor + B4 C5; zoeira: B6 C10; correção: B7 C12 → B6 C10 D1 "foi de propósito"; sussurro: B4 C5); **3 s** depois do fim, se a música continua: P11 E3→E2 600 | estado anterior [perdeu: Asuka (5 s); Kurisu (na hora)] |
| PC sofrendo em jogo | ver §5 | estado de cobrança |

**Interrupção:** (1) **interrompe na hora**: Pedro fala, clique no retrato, Pedro volta (respeitando 5 s), sistema
grave — a cena sai por B1 C1 200 ms; (2) **espera na fila**: jogo abre/fecha, música começa/para,
ama/odeia, Claude terminou/erro, faxina; (3) **absorvido** (não anima, só mexe no humor/estado):
notificação, rede oscilando, FPS/calor repetido, Claude trabalhando, LED comum, pulo de faixa durante
cena. Passivas e ativas comuns durante cena são descartadas.

## 3. Humor dela
Ânimo −1..+1, energia 0..1. **Base:** ânimo **+0,1**; energia **0,6** (08h–22h), **0,35** (22h–03h),
**0,2** (03h–08h), **0,65** com jogo aberto [perdeu: Asuka (0,5 de dia)]. **Meia-vida** rumo à
base: ânimo **20 min**, energia **15 min** [perdeu: Asuka (20)]. **Teto por evento ±0,3.** Mesmo
evento repetido em **30 min** vale metade, depois um quarto. Faixa de humor só troca com
**histerese de 0,1 e 2 min** na faixa nova (o rosto não pisca).

| Evento | Δânimo | Δenergia |
| --- | --- | --- |
| Faixa nota 2 | +0,25 | +0,10 [perdeu: Asuka (+0,15)] |
| Ado | +0,30 | +0,15 |
| Favorita do Dia | +0,30 | +0,15 [perdeu: Asuka (+0,25/+0,10) — mantém a linha vermelha da Aqua] |
| Faixa nota 1 | +0,10 | +0,05 |
| Cada 15 min de música com média ≥ 1 (até +0,3 somado) | +0,10 | 0 |
| Faixa nota −1 / −2 | −0,10 / −0,20 | 0 / +0,05 |
| 3 pulos em 2 min | −0,05 | +0,05 |
| Música parou | 0 | −0,05 |
| Silêncio longo (sem música e Claude parado), a cada 20 min; piso desta causa **−0,3** | −0,05 | −0,10 |
| Jogo abre | +0,05 | +0,25 |
| Jogo fechou em paz | +0,10 | −0,10 |
| 1º alarme do episódio de FPS/calor | −0,10 | +0,10 |
| Episódio recuperado (só se ela cobrou) | +0,10 | 0 |
| Faxina terminou / commit | +0,10 | 0 / +0,05 |
| Claude terminou / erro | +0,05 / −0,05 | 0 / +0,05 |
| Rede caiu / voltou | −0,10 / +0,05 | 0 |
| Pedro volta | +0,20 | +0,15 |
| Pedro fala com ela | +0,10 | +0,10 |
| Tag elogio / zoeira / correção | +0,30 / +0,05 / −0,05 | +0,10 / +0,15 / +0,05 |
| Carinho no retrato | +0,10 | 0 |
| Humor do Pedro em 0–1 | −0,10 uma vez; enquanto durar: positivos ×0,5 e **teto do ânimo +0,3** | 0 [perdeu: Asuka (sem o −0,10)] |

**Faixas de humor** (limiares **±0,15** e ±0,5):
| Faixa | Rosto de repouso | Fundo | Passivas permitidas | Proibidas |
| --- | --- | --- | --- | --- |
| **Radiante** ≥ +0,5 | B1 C10; energia ≥ 0,75: B4 C5; **com música nota ≥ 1: B4 C10** (sorriso com olhos pela faixa) | `happy` (`focus` em jogo) | sorriso de canto, piscada de gato, presilha, cantarolando*, rindo sozinha, cabeça no ritmo*, corando (1/dia) | suspiro, beicinho, franja |
| **Bem** +0,15..+0,5 | B1 C10 leve | `calm` → `happy` com música nota ≥ 1 | respirar, piscadas, sacada, presilha, sorriso de canto, cabeça no ritmo*/ajeitando o fone* | suspiro, beicinho |
| **Neutra** −0,15..+0,15 | B1 C1 | `calm` | respirar, piscadas, sacada, observando o HUD, presilha | rindo sozinha, cantarolando |
| **Irritada** −0,5..−0,15, energia > 0,5 | B1 C12 | `stress` | beicinho, franja, encarando, observando o HUD (com causa, §4) | sorriso de canto, cantarolando, rindo |
| **Abatida** −0,5..−0,15, energia ≤ 0,5 | B1 C4 | `calm` | suspiro (com causa, §4), observando o HUD, respirar | sorriso, cantarolando, franja [perdeu: Kurisu (B2 C1)] |
| **Baixa** ≤ −0,5 | B10 C9 | `sad` | respirar, suspiro (≤ 1/h), olhar para o Pedro | toda zoeira e festa |
| Energia < 0,25 (qualquer ânimo) | olhos B2 (B14 nas regras de sono) | `sleepy` só 22h–04h, sem jogo/Claude/música nota ≥ 1 | bocejo, cabeça pesada (regras de sono do acordo 10-08) | dançante, cabeça no ritmo |

\* só com música tocando, nota ≥ 0 e fone E2. `love` e `surprise` nunca vêm do humor, só de cena.
[Radiante: perdeu Aqua (B4 C10 sempre) — atendida na parte "com música nota ≥ 1".]

**Medidor ao lado do retrato:** ânimo em 0–4 = `round((ânimo + 1) × 2)`, na cor do fundo da faixa;
energia como brilho/altura da barra.

## 4. Passivas negativas (suspiro, beicinho, franja)
Ficam, amarradas a causa **dos últimos 2 min** e à faixa de humor; **≤ 3/h somadas, cada ≤ 2/h**
[perdeu: Asuka (2/h somadas)]; nunca 22h–04h (beicinho/franja), nunca com Pedro mal. O silêncio
**não gera gesto** (só mexe no humor).
- **Suspiro:** faixa Abatida/Baixa com silêncio longo ou Claude demorando; ou dentro da cena "música
  para" (condição da §2).
- **Beicinho:** pulo da faixa que ela ama, faixa nota −1 nos últimos 2 min, ou Irritada + "ignorada"
  (Pedro ativo ≥ 15 min sem música nem conversa).
- **Soprando a franja:** **calor** fora de jogo ("ufa"), ou Irritada + "ignorada".

## 5. Enxurrada em jogo
**Episódio** = do 1º alarme até 3 min abaixo do limiar; FPS e calor juntos são **um** episódio.
Limiares: FPS < 75% da média da partida por ≥ 5 s; calor com histerese de 3 °C.
- **1º alarme do episódio = cena** de cobrança (F3 C11 1200 · B6 C8 D2 1500).
- **2º em diante = estado:** rosto de repouso B6 C8 + suor D2 parado + fundo `stress` enquanto durar.
  Nada de micro-reação [perdeu: Aqua].
- **Nova cena só se piorar de nível** (temperatura +5 °C acima do limiar, ou FPS < metade do normal →
  `vergonha de FPS`).
- **"Eu avisei" no meio:** no máximo **1 por partida**, só se o episódio passa de 10 min, e **conta
  dentro do teto de 2 cenas de cobrança por partida**; se saiu, a cena "jogo fecha" não repete a
  cobrança [veto da Kurisu; perdeu: Asuka (só no fecha)].
- **Recuperou:** 1 por episódio, só se ela cobrou aquele episódio.
- **Teto por partida:** 2 cenas de cobrança + 1 de recuperação. Só temperatura crítica (risco ao
  hardware) fura.

## 6. Momentos
O diretor decide o momento pelos sinais (determinístico), reavaliado a cada acontecimento e a cada
30 s; troca só se o novo vale por **≥ 30 s** (Conversa e Jogando entram na hora). A passiva é
sorteada **só** no grupo do momento, já filtrado pela faixa de humor (vale a interseção; vazia =
ela fica no rosto de repouso — ficar parada também é coerente). Troca de momento não gera reação.

| Prio | Momento | Reconhecido por | Rosto de repouso | Grupo de passivas |
| --- | --- | --- | --- | --- |
| 1 | **Conversa** | Magui ouvindo/falando, ou turno do Pedro há < 60 s | olhando para ele, B1 C1, E3 | nenhuma (só a cena) |
| 2 | **Jogando** | jogo aberto | B6 C8 com episódio aberto ou trilha nota 2 (modo chefe, E2); senão B1 C10 | sacada de olhar, observando o HUD (FPS/temp.), respirar, piscada dupla; cabeça no ritmo só com trilha nota ≥ 1 |
| 3 | **Estudando** | Learning ligado (`lm_mode` on) | B1 C1, olhar F7 (lendo junto) | respirar, piscada lenta, sacada, mão no queixo P10 (≤ 2/h, se a arte existir). Sem cantarolar, sem negativas |
| 4 | **No flow** | Claude rodando, ou Pedro ativo ≥ 10 min sem pausa > 2 min | com música: F7 C1 E2 (bob leve); sem: B1 C1 | respirar, piscadas, sacada, observando o HUD, cabeça no ritmo*. Sem raras, sem negativas |
| 5 | **Curtindo** | música nota ≥ 1 (Ado/Favorita incluídas) e ânimo ≥ +0,15 | B1 C10 E2 (Radiante: B4 C10) com balanço | cabeça no ritmo, ajeitando o fone, sorriso de canto, piscada de gato, presilha, cantarolando/rindo sozinha (raras), cantando junto (≤ 1 por faixa, só nota 2) |
| 6 | **Aturando** | música nota ≤ −1 (fone já no pescoço) | B1 C12 E3 | beicinho (§4), observando o HUD, encarando (1×), respirar [perdeu: Asuka (sem esse momento)] |
| 7 | **Ouvindo** | música nota 0 (ou ≥ 1 com ânimo < +0,15) | B1 C1 E2 | respirar, piscadas, sacada, presilha, cabeça no ritmo |
| 8 | **Madrugada** | 22h–04h e nada acima | B2 C1 | respirar, piscada lenta; bocejo/cabeça pesada pelas regras de sono |
| 9 | **Esperando** | Pedro inativo 10–30 min, sem música | B1 C1 E3 | observando o HUD, sacada para a tela, respirar, falando sozinha (rara) |
| 10 | **Tédio ("ignorada")** | Pedro ativo ≥ 15 min sem música, jogo, Claude nem conversa | B1 C1 E3 (energia < 0,3: B2) | respirar, observando o HUD, presilha, falando sozinha (rara); franja/beicinho/suspiro só pelas regras da §4 |
| 11 | **Ausente** | Pedro inativo > 30 min | B14 C1 E3 | só respirar, ≤ 2/h (não se encena para sala vazia); a cena da volta continua valendo |
| 12 | **À toa** | nada acima | o da faixa de humor | as da faixa de humor |

\* só com música e fone E2.
**Ociosa feliz:** com a faixa Radiante, Esperando, Tédio e À toa viram **Ociosa feliz** (rosto
B4 C10; grupo: sorriso de canto, presilha, piscada de gato, rindo sozinha) — ela não fica entediada
logo depois de uma vitória [perdeu: Asuka].
**Filtros por cima de qualquer momento:** **Madrugada** (22h–04h): sem zoeira, intervalo ×1,5, olhos
B2 no repouso; **Pedro mal** (0–1): tira zoeira e festa, troca beicinho/franja por respirar; faixa
**Baixa**: o rosto B10 C9 sobrepõe o do momento (o grupo continua o do momento).

## 7. O que muda fora da ata
- Persona (`persona/condessa.md`): seção "Como ela vive" (resumo das regras acima) e atualização da
  seção "Reações no rosto".
- Gosto (`persona/condessa-gosto.toml`): tabela `[vida]` com os números de ritmo, humor e limiares
  (lidos pelo código novo).
- Persona falada (`magi/agent/persona.md`): **sem mudança** (é rosto, não fala).
- Código: SDD novo `specs/condessa-vida/` (estado de humor, diretor de cenas e momentos, fone como
  estado, as 19 antigas sob o governador, contagem que sobrevive ao HUD reiniciar, "HUD acordou"
  único) — implementado em tarefas.

## Orçamento usado
Aqua ~80 mil, Kurisu ~86 mil, Asuka ~85 mil tokens no assunto inteiro (teto: 128 mil por delegada).
