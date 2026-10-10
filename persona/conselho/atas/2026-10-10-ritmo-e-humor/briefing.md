# Briefing — Ritmo, cenas, humor e momentos da Condessa (2026-10-10)

> Este assunto já passou pelo Conselho antigo (por funções). O Pedro refez o Conselho para que vocês
> sejam três pessoas inteiras e pediu para decidir de novo. Vocês **não** recebem o acordo antigo:
> pensem do zero.

## Assunto
As 110 reações do acordo `2026-10-08-reacoes` entraram no HUD. Com um dia de uso, o Pedro achou o
rosto **poluído e sem alma**: animações demais, rápidas, que não conversam entre si, e ela "sem
mood" — mesmo gostando da música não fica sorrindo. O Conselho decide como ela **vive** entre os
acontecimentos: o ritmo, as cenas e o humor dela.

## Já decidido pelo Pedro (fixo — não reabrir)
1. **Fone vira estado.** Na cabeça enquanto há música; no pescoço sem música. Ela **tira** o fone
   quando a música para, para falar com ele, e quando **não gosta** da faixa.
2. **Humor próprio.** Ela ganha um humor persistente (ânimo e energia) que sobe e desce com os
   acontecimentos e volta devagar ao normal; ele muda o **rosto de repouso** (ex.: ânimo alto =
   sorriso leve parada). O **medidor ao lado do retrato passa a mostrar o humor DELA** (hoje mostra o
   humor do Pedro, 0–4, estimado pelo núcleo; esse número continua existindo e continua valendo para
   as regras de "Pedro mal = sem zoeira").

3. **Princípio (Pedro, durante o briefing):** "ela fazer algo interessante, mas ela tem que fazer
   algo coerente com o momento." Ou seja: não é para ela ficar apagada; é para cada coisa que ela
   faz ter motivo no que está acontecendo (música, jogo, PC, conversa, hora, humor dela). Toda
   proposta deve passar neste teste: "dá para dizer por que ela fez isso agora?"

4. **Regra geral (Pedro): nada de sortear animações aleatórias do catálogo inteiro.** Primeiro se
   identifica o **momento** em que ela está — ex.: tédio, felicidade, no flow, estudando, jogando
   (e outros que o Conselho definir) — e só se escolhe dentro do **grupo de animações coerentes com
   aquele momento**. O Conselho decide: a lista de momentos, como cada um é reconhecido pelos sinais
   reais (música e nota, jogo aberto, Claude rodando, Learning ligado, hora, inatividade, humor
   dela), a ordem de prioridade quando dois valem ao mesmo tempo, e o grupo de animações de cada um
   (passivas permitidas e o jeito do rosto de repouso).

## O que os dados mostram (log real, 809 reações em 12 h, 2026-10-09 10h–21h)
- **Ritmo:** ~50 passivas/h (≈ uma a cada 70 s) + ~18 ativas/h (pico 46 às 15h). Na prática, uma
  reação por minuto o dia todo.
- **Passivas mais tocadas:** suspiro 89 · beicinho 63 · soprando a franja 56 · observando o HUD 54 ·
  sorriso de canto 51 · fone em repouso 40 · brilho da presilha 38 · cabeça no ritmo 35 · sacada de
  olhar 31 · respirar 31 · ajeitando o fone 28 · piscada dupla 26 · piscada de gato 24 · rindo
  sozinha 8 · cantarolando 8 · falando sozinha 7 · corando 4.
  As três primeiras são negativas: o fator de humor "silêncio longo" (sem música e Claude parado)
  favorece suspiro/beicinho/franja, e isso é o estado mais comum do dia.
- **Ativas mais tocadas:** queda de FPS 42 · calor 36 · notificação 32 · HUD acordou 21 · Claude
  trabalhando 21 · "eu avisei" 13.
- **Rajada:** quando a música começou (21:05) saíram 8 reações em ~75 s — `music_love` 3×,
  piscadinha, cabeça no ritmo, cantando junto, "essa é das minhas" — cada detector reagiu sozinho ao
  mesmo acontecimento.
- **Fone sem música:** "ajeitando o fone" e "cabeça no ritmo" saem sem música (defeito do detector,
  contra o acordo); "fone em repouso" é um pisca de 3 s; "colocando o fone" nunca saiu.
- 58 das 108 reações ativas nunca tocaram (muitas dependem de situação rara: data, Ado, Gaga, notícia
  com palavra-chave…). Isso não é problema por si.
- (Defeitos de código já anotados para o SDD, fora da pauta: "corando" passou de 1/dia porque a
  contagem zera quando o HUD reinicia; "HUD acordou" sai duas vezes; as 19 reações antigas não
  passam pelo governador.)

## O que o sistema consegue fazer (restrições)
- Rosto em camadas: olhos B1–B17, bocas C1–C14 e V1–V6, olhares F1–F7 + íris livre (O1), efeitos
  em código (rubor, suor, zz, ?, !, notas, lágrima, veia, brilho), fone E2 (cabeça) e E3 (pescoço),
  braços P9 aceno, P10 mão no queixo, P11 mão no fone, P12 punho, P13 braços cruzados, piscadinha
  B16. Fundo com cor por humor: calm, happy, stress, sad, focus, surprise, sleepy, love.
- Acontecimentos que o HUD/núcleo enxergam: faixa nova e nota dela (−2..2, gosto do Conselho),
  música parou, pulos, Ado/Gaga/Favorita do Dia, jogo abriu/fechou, FPS, temperatura, rede, disco,
  RAM, faxina, Claude rodando/parou/erro/esperando, commit, notícias, clique/hover/arrasto no
  retrato, LED, tag do turno do Pedro (elogio/zoeira/correção/sussurro), humor do Pedro 0–4,
  horário, inatividade do Pedro, Magui ouvindo/falando.
- **Uma ideia de arquitetura da secretária** (só sugestão; podem propor outra):
  1. **Estado de fundo** (minutos): humor dela (ânimo −1..+1, energia 0..1) com volta lenta ao
     normal; postura (fone cabeça/pescoço, sonolenta); define o rosto de repouso e o medidor.
  2. **Cenas** (dezenas de segundos): um "diretor" transforma acontecimentos em **uma cena por
     vez** (ex.: música começou → olha o player, coloca o fone, reage ao gosto). Dentro da cena só
     cabem variações dela; acontecimento novo espera, é absorvido ou interrompe se for prioritário.
  3. **Gestos** (passivas): raros, filtrados pelo humor e pela cena.

## O que o Pedro quer de vocês
Que digam o que acham de como ela deve **viver** entre os acontecimentos — o ritmo, as cenas, como o
humor dela sobe e desce, os momentos e os grupos de animação de cada um, o que fazer com as passivas
negativas e com a enxurrada de alarmes em jogo — e que tragam ideias próprias, inclusive fora disso.
Ele vai ler as falas: escrevam como vocês, não como relatório.

## Formato da rodada 1 (`fala-<nome>.md`)
- **O que eu acho** — sua opinião sobre o assunto inteiro, com os seus motivos, na sua voz.
- **Minhas ideias** — concretas; as fora do assunto vão marcadas como *extra*.
- **O que me incomoda** — no que existe hoje e nos riscos do que vai mudar.
- **Proposta** — o que você quer implementado, com números (ritmo, cotas, Δ de humor, meia-vida,
  momentos e seus grupos, cenas e roteiros curtos com B*/C*/E*/P*/efeitos e tempo).
- **Não abro mão** (opcional, no máximo 2) — e por quê.
Português. Tamanho livre, mas cada proposta tem que dar para implementar.
