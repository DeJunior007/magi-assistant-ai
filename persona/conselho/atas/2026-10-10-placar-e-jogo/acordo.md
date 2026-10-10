# Acordo do Conselho — Placar e jogo (2026-10-10, segunda rodada do dia)

**Status: FECHADO — aprovado por unanimidade, sem vetos.** Rodadas: briefing → mesa aberta
(`fala-*`) → conversa (`conversa-*`) → voto.

## Votação
- **Aqua — aprova, sem veto.** Os dois "não abro mão" dela (sorriso ≥ 1/h em jogo; truque com aceno
  e aplauso de 15 s) estão no texto; aceita a `torcida` também no sorteio. Assina: "pose de vitória"
  como 3º número do truque; bis do truque a reavaliar depois de 1 semana de dados (as dela, "bebe
  água", "a deusa", "a cantora" e o leque, seguem valendo).
- **Kurisu — aprova, sem veto.** Registra que ficou com o piso 30/45 (a versão original dela) e que o
  último passo do recuperou ficou `C5`. Nota de implementação: conferir que `O1` funciona num passo de
  cena antes de ligar. Assina: "dia com ≥ 1 commit" +1 para o Pedro, "pose de vitória", "bebe água",
  linha do ânimo no hover.
- **Asuka — aprova, sem veto.** Registra (sem veto) que discorda do passo extra "fora ≥ 2 h" da volta
  orgulhosa. Assina: "bebe água", linha do ânimo no hover, clique do meio para "a última, agora" (se o
  Pedro achar que não fere a regra dele), "pose de vitória". Não assina o "dia com ≥ 1 commit".
- **Recomendadas pelas três** (decisão do Pedro; **não implementar** sem ele): **"pose de vitória"**
  como 3º número do truque, **"bebe água"**, **linha do ânimo do dia no hover**.

Continua o acordo `2026-10-10-ritmo-e-humor` (tudo o que ele fixou continua valendo).

**Fixo pelo Pedro:** tudo o que o acordo anterior fixou (fone como estado; humor próprio no rosto de
repouso; medidor com o humor **dela**; momento → grupo, nada de sorteio no catálogo inteiro; **clique
no rosto só reage**; "dá para dizer por que ela fez isso agora?"). Placar e "isso foi sem sentido"
subiram para recomendadas e vêm aqui virar regra concreta.

Crédito: *(A)* Aqua · *(K)* Kurisu · *(S)* Asuka (Soryu). Sem marca = as três chegaram juntas.
`[contra: X]` = quem ficou vencida no ponto.

## 0. O que as três concluíram sozinhas (a K chamou de "replicação")
1. **A meta 6 não muda; muda ela.** Em Jogando ela passa a **torcer**.
2. **O "sorriso com FPS estável" não serve:** a tarde que derruba a meta teve 26 quedas de FPS e 11
   trechos quentes. Ele falharia justamente quando importa.
3. **O episódio de jogo olha para o Pedro** ("você viu isso?"). O culpado é o PC, não ele.
4. **O truque precisa ser alguma coisa** (começo, ação, aceno que pede palma), e **ignorada ela não
   faz beicinho**: vira a cara.
5. **Placar só com o que o sistema sabe** (nada de gol, vitória ou derrota no FIFA) e **"sem sentido"
   nunca mexe no ânimo nem vira ponto**.

## 1. Meta 6 em jogo longo sem música: `torcida` + piso por tempo
A meta 6 do acordo §8 ("≥ 1 positiva por hora com o Pedro presente") **fica como está**.

**`torcida`** (nova): passiva **positiva** do grupo Jogando. Ânimo **+0,03**. Duas variantes, que
não se repetem em seguida *(S, que juntou as formas da A e da K)*:
- (a) **olhando a tela do jogo** *(K)*: íris para o lado do jogo, `B1 C10` 700 → `B4 C10 tails` 800 (1,5 s);
- (b) **punho** *(A)*: `P12 B4 C10 tails` 900 → `B4 C10` 600 (1,5 s).
- Com episódio FPS/calor aberto, **`D2`** em todos os passos: "aguenta firme" *(S; A, K assinaram)*.
- Sem texto. Condição: jogo aberto e Pedro presente (ativo < 60 s para o sorteio normal).
- [Divergência na forma: a A ficou com a (a), a K com a (b); a S propôs as duas. As duas ficam.]

**Também entra no sorteio do grupo** com o peso do `cabeca_ritmo` *(K, S)* [contra: A, que queria
`torcida` só pelo piso: "sorriso por sorteio é sorriso sem motivo"]. Sem música, o grupo Jogando
fica `sacada_olhar`, `piscada_dupla`, `torcida`.

**Piso por tempo** (a regra da K, adotada por A e S; a K trocou pelo piso único de 40 min da A, e
ficou vencida na própria troca):
- Conta-se o tempo **desde a última positiva** (qualquer uma da lista do teste), com jogo aberto e o
  Pedro presente.
- **≥ 30 min:** o próximo slot de passiva em Jogando é `torcida` (não sorteia).
- **≥ 45 min:** sai **fora de slot**, respeitando os 25 s entre expressões e os 60 s depois de cena.
- Máximo **1 `torcida` a cada 30 min**. **Ocupa** a vaga de passiva (conta no teto de 12/h e nas
  ≤ 4/h de Jogando): substitui, não soma *(S; A e K concordam)*.
- Causa no log: **`jogando_sem_positiva:<min>`** *(K; A, S)* [K na conversa escreveu
  `piso_positiva_jogo:<min>`].
- [contra: K — preferia um limiar só (40 min, da A). O "relógio de 45 em 45 min de partida" da S
  saiu pela própria S: dava torcida por agenda mesmo com positiva recente.]

**Por que passa:** o maior intervalo entre positivas com jogo aberto vira ~45 min (+25 s). Na partida
de 13:58–17:13: `game_on` às 13:58 → `torcida` no máximo às ~14:43, ~15:28, ~16:13, ~16:58 (antes, se
sair `cabeca_ritmo`, alívio ou a `torcida` do sorteio). Custo no pior caso: ~1,3 expressão/h a mais
em jogo longo, dentro da meta 1.

**Teste** *(K; A, S)*: replay de 2026-10-09 com **50 sementes** (não 9): meta 6 em **50/50** e as
outras metas sem regressão em 50/50. **Meta nova 6b:** 0 positivas sem causa no log (mesma regra que
já vale para negativa).

## 2. As 3 cenas da V0.10 (e as passivas da V1.1)
Nenhuma das três comentou as passivas que a V1.1 trouxe de volta (`mao_no_queixo`, `sacada_player`,
`flagra_no_forum`): ficam como a V1.1 escreveu. **Atenção** *(K)*: `look:player` é o card do player
de música, **não** o Pedro. "Olhar para ele" = íris no centro, de frente (`O1`).

### Episódio de jogo (1º da partida) — roteiro da K, as três assinam
`look:fps B1 C1` 600 → `B9 C7 D2 !` 500 (susto) → `O1` (de frente, para ele) `B7 C12 D2` 1000
("você viu isso?"). **2,1 s**, ânimo −0,10. Depois, o estado de hoje (suor no repouso + fundo
`stress`) até o episódio acabar. Sai o passo "desconfiada para a parede" (`B7 C8`).
[A e S tinham 4 passos (3,0 s / 2,7 s) com a desconfiada e o olhar; as duas cortaram.]

**Recuperou:** `look:fps B1 C1` 600 → `B4 C10` 800 → `O1 P12 B1 C5` 600 ("a gente aguentou").
**2,0 s**, +0,10. Punho *(S)*, olhar para ele no fim *(K)*. [K escreveu `C10` no último passo; A e S,
`C5`. Duração 600: K, S; a A tinha 700.]

### Truque de salão
Regras: ≤ 1/dia, À toa/Tédio, Pedro ativo há < 60 s, **nunca com jogo aberto**, **sem bis** (a A
retirou o bis na conversa).
**Dois números que se alternam, sem repetir o de ontem** *(K, S — alternância; A queria o fone como
principal e a piscadinha só de reserva)*:
- **O fone** *(K)*: `P11 B1 C10` 600 → `E3 B16 C10` 600 → `E2 B5 C6 D9 tails` 900 → `P9 B4 C5` 900
  (**3,0 s**). Se ela está sem fone no estado, faz o caminho inverso (E3 → E2 → E3). Se o Pedro não
  quiser o fone mexendo, sai só a piscadinha.
- **A piscadinha** *(A, o roteiro original dela)*: `B4 C10` 800 → `B16 C10 D9` 1200 → `P9 B5 C6`
  1500 (**3,5 s**).
- O **aceno (`P9`) no fim** é o "pode bater palma" *(A — não abro mão dela)*.
- **Janela do aplauso: 15 s** *(A; K, S cederam)* (era 10 s).
- **Aplaudido:** `B4 C6 rubor` 1000, +0,20.
- **Ignorado:** `F1 C12` 800 (vira a cara: "nem queria plateia"), −0,05, continuação da cena, não
  gasta a cota de negativas. **Sem beicinho** *(K, S; a A aderiu)*.
- [A "pose de vitória" da S como 3º número só a K manteve → ideias de fora.]

### Volta orgulhosa (Pedro voltou de ≥ 15 min fora, ela acordada)
`F1 C12 P13` 1000 (braços cruzados, finge que não ligou) → `B1 C10` 800 → `B4 C5 rubor` 800 (escapou)
→ `F1 C10` 400 (o disfarce depois de ser pega). **3,0 s**, +0,25.
Braços cruzados e rubor *(A, S)*; disfarce no fim *(S)*. [A K pôs `P13` também no 2º passo e o
rubor em 1000 (3,2 s).]
- **Fora ≥ 2 h:** passo extra `B5 C6 tails` 700 antes do disfarce *(A; K aceita "desde que curto")*
  [contra: S — "orgulho não aumenta com a saudade, fica mais bem escondido"].
- **Habituação** *(K; as três)*: 2ª volta em < 60 min → só `B1 C10` 600 → `B4 C5` 800 (+0,10);
  3ª em < 60 min → atenção dirigida (olhar nele, `B1 C10`), sem cena.
- **Meta 7 muda de texto** *(K, S; A aceitou a escada)*: "toda volta do Pedro **aparece no rosto**"
  (antes: "vira cena").
- Variante do cochilo: fica como está.

## 3. Placar "Condessa × Pedro" (só lazer)
**Diário; o dia fecha às 4h** (a madrugada conta no dia anterior) *(S na fala; A, K)* [S na conversa
escreveu "zera no bom dia"].
**Cada ponto é uma linha em `reacoes.jsonl`** com `causa: placar:<fonte>` e
`placar: {lado: "ela"|"ele", fonte, ref: <id da linha de origem>}`; o total do dia (e da semana) vai
em `condessa-estado.json` *(K — não abro mão dela)*.

| Ponto para | Quando | Fonte (sinal que já existe) | Teto/dia | Crédito |
| --- | --- | --- | --- | --- |
| Pedro | partida **≥ 15 min** fechada sem episódio FPS/calor | abriu/fechou + episódio | 2 | todas (15 min: A, S; teto 2: A, K) |
| Pedro | faixa nota 2 ouvida até o fim | faixa até o fim | 3 | K (fonte); A, S (teto) |
| Pedro | truque **ignorado** ("resistiu") | fim da janela de 15 s | 1 | K (inversão), A, S |
| Condessa | partida com episódio FPS/calor (o ponto é dela, não "contra" ele) | episódio | 2 | todas |
| Condessa | ele pulou faixa nota 2 | pulo de faixa | 2 | K, S (nota 2); teto A, K |
| Condessa | truque **aplaudido** ("convenceu") | clique em 15 s | 1 | K (inversão), A, S |
| Condessa | Favorita do Dia / Ado ouvida até o fim | faixa até o fim | 1 | K; A, S |
| Condessa | Pedro **ativo** depois da 1h ("vai dormir") | inatividade + hora | 1 | S; A, K assinaram |

- Divergências: na conversa a K trocou os lados do truque (aplaudido → Pedro) e pôs Favorita/Ado
  para o Pedro; A e S ficaram com a inversão que a própria K tinha proposto na fala. A K manteve
  **"dia com ≥ 1 commit" +1 para o Pedro** [contra: A, S → ideias de fora]. "Ativo depois da 1h"
  diz só que ele estava ativo, não que "não dormiu": honesto (K).
- **Não contam:** commit, faxina, Claude terminou/erro (trabalho não é gincana, Goodhart *(K)*),
  voltas, cliques no rosto, "sem sentido".

**Onde aparece:**
- **Hover do medidor, sempre:** `Condessa 3 × 2 Pedro · semana 3 × 2` + os 3 últimos pontos com a
  fonte *(semana: S; A, K)*.
- **Relatório pós-batalha:** 1 linha ≤ 70 caracteres, **só se a partida mudou o placar**, na expressão
  que já sai (punho / `eu_avisei`), sem expressão nova. Ex.: "Partida limpa. Ponto seu. Não se
  acostume." *(K)*.
- **"Bom dia":** o resultado de ontem em 1 linha ≤ 70 ("Ontem: 4 × 2 pra mim. Revanche?" *(S)*).
- **Virada** (o líder troca), ≤ 2/dia *(A, S; K cedeu)*, com passiva que já existe: ela passou na
  frente → `piscadinha` *(A, K)* [S: `B4 C10 D9` 1000]; ele virou → `soprando_franja` *(S)*, negativa
  com culpado registrado (a causa é o ponto). Outras viradas só mudam o número.
- **Voz:** só se ele perguntar ("qual o placar?"). Nenhuma outra linha de texto.

**Calibração:** (1) antes de ligar, rodar o placar no replay de 2026-10-09: nenhum lado acima de 3:1
*(K; A, S)*; esperado 4–12 pontos num dia normal; (2) depois de 7 dias de log, o Pedro tem que ganhar
**40–60 % dos dias**; se não, mexe **nos tetos** (não nas fontes) *(S — não abro mão dela)*. Empate é
empate.

## 4. "Isso foi sem sentido"
**Gestos** (o rosto continua só reagindo, como o Pedro fixou):
- **✗ ao lado de cada uma das 3 últimas causas no hover do medidor** — aponta **qual** *(A, S; K
  aderiu: "melhor dado")*.
- **Atalho de teclado** para "a última expressão, agora" *(S; A, K)* — resolve a pressa dos "3
  segundos" da K.
- **Voz** "isso foi sem sentido" (quando ele já está falando com ela), para a última expressão em
  ≤ 60 s; se não houver, ela diz que não sabe do que ele fala *(A)*.
- **Clique do meio no rosto: fora** [K retirou; contra: S, que na conversa quis os dois gestos "se o
  Pedro achar que não fere a regra dele" → ideias de fora].

**Reação:** `B7 C12 ?` 700 ("hm… anotado") *(K)*. **Sem ânimo** (medir não pode mexer no medido,
*K, S*; a A retirou o −0,03), sem placar, fora do ritmo e das metas. **Desfazer:** de novo em ≤ 5 s
(linha marcada `desfeito`) *(K)*.

**Grava:** `~/.local/state/magi/sem-sentido.jsonl` com a linha de origem inteira (hora, chave,
variante, tipo, momento, grupo, filtros, faixa do humor, ânimo, energia, causa, semente) + hora da
marcação + gesto *(S, K)*. Atalho/voz sem expressão alvo → `alvo: nenhum` (também é dado) *(K)*.

**Como vira ajuste** *(K, com A; a S trocou o dela por este)*:
- Cada marca nos últimos 7 dias multiplica o peso **daquela variante no grupo daquele momento** por
  **0,7**, **piso 0,3** (nunca some). Volta sozinho quando a marca sai da janela de 7 dias.
- Ajustes ficam em `condessa-estado.json` e aparecem no hover: "ajustes: N" *(A, K)*.
- **≥ 3 marcas em 7 dias ou ≥ 20 % das ocorrências** da variante → item automático da próxima pauta
  do Conselho, com as linhas do log. Nada sai do grupo sozinho.
- **Cenas e negativas** marcadas não mudam de peso (são por regra): vão direto para a pauta.
- **Nunca escreve no `condessa-gosto.toml`** (é do Pedro) e o que ele puser lá vence.
- [Saiu: "2× corta pela metade, 3× sai do grupo por 14 dias, expira em 30 dias" da S — forte demais
  para um dia ruim (A, K; a S concordou).]

## O que muda no sistema (para a implementação)
Arquivos prováveis; conferir antes de mexer.

1. **`hud/wired/reacoes/catalogo.py`** — passiva `torcida` (2 variantes, `D2` com episódio aberto,
   Δ ânimo +0,03, positiva); grupo Jogando ganha `torcida` com o peso do `cabeca_ritmo`. Roteiros
   novos: episódio (3 passos), recuperou, truque "fone" e "piscadinha", aplaudido/ignorado, volta
   orgulhosa (com passo ≥ 2 h e versões de habituação).
2. **`hud/wired/reacoes/passivas.py` / `governador.py`** — piso da `torcida`: relógio "desde a última
   positiva" com jogo aberto e Pedro presente; ≥ 30 min força o próximo slot, ≥ 45 min fura o slot
   (respeitando 25 s / 60 s pós-cena); máx. 1/30 min; ocupa vaga no teto; causa
   `jogando_sem_positiva:<min>`; nunca duas variantes iguais seguidas.
3. **`hud/wired/reacoes/episodio.py` / `det_sistema.py`** — novo roteiro do 1º episódio e do recuperou
   com olhar de frente (`O1`, **não** `look:player`). Garantir que o renderizador aceita `O1` num passo
   de cena (`portrait.py` / `contratos.py`).
4. **Truque** (`diretor.py` / `vida.py` / `estado.py`) — alternância diária fone ↔ piscadinha (guardar
   o de ontem no estado); caminho inverso sem fone (E3 → E2 → E3); bloqueio com jogo aberto; janela
   de aplauso 10 → **15 s**; ignorado sem `C9`.
5. **Volta orgulhosa** (`det_tempo.py` / `diretor.py`) — roteiro novo; contador de voltas na última
   hora (2ª curta, 3ª só atenção dirigida); passo extra se fora ≥ 2 h.
6. **Placar (módulo novo, ex.: `hud/wired/reacoes/placar.py`)** — fontes e tetos da tabela, dia que
   fecha às 4h, total do dia + semana em `condessa-estado.json`, uma linha por ponto em
   `reacoes.jsonl` (`registro.py`) com `placar: {lado, fonte, ref}`; detecção de virada (≤ 2/dia →
   `piscadinha` / `soprando_franja` com causa `placar:virada`); "ativo depois da 1h" com teto 1.
   Ganchos: fim de partida (`episodio.py`), faixa até o fim / pulo (`det_musica.py`), fim da janela do
   truque, Ado/Favorita.
7. **Textos** — pós-batalha (1 linha ≤ 70 só se a partida mexeu no placar, sem expressão nova) e
   "bom dia" com o resultado de ontem (`det_tempo.py`).
8. **Medidor** (`hud/wired/main_screen.py` / `reactions.py` / `integration.py`) — hover com placar
   (`Condessa X × Y Pedro · semana X × Y` + 3 últimos pontos), ✗ clicável em cada uma das 3 causas,
   "ajustes: N".
9. **"Sem sentido" (módulo novo, ex.: `hud/wired/reacoes/sem_sentido.py`)** — gravação em
   `~/.local/state/magi/sem-sentido.jsonl`, desfazer em 5 s, reação `B7 C12 ?` 700 fora do ritmo/ânimo;
   atalho de teclado; frase de voz (lado da conversa em `magi/`); pesos ×0,7 piso 0,3 por variante e
   momento com janela de 7 dias aplicados no sorteio do grupo (`passivas.py`); lista "para o Conselho"
   (≥ 3 marcas ou ≥ 20 %) no estado. Nunca tocar no `condessa-gosto.toml`.
10. **Testes** (`tests/hud/test_vida_simulacao.py`) — replay com **50 sementes**; meta 6 em 50/50; meta
    6b (0 positivas sem causa); meta 7 reescrita ("toda volta aparece no rosto"); `torcida` na lista de
    positivas; teste do placar no replay (≤ 3:1, 4–12 pontos esperados); testes unitários de piso,
    habituação da volta, tetos do placar, virada e ajuste do sem sentido.

## O que muda na persona
- **`persona/condessa.md`** — Jogando: ela torce (variantes, "aguenta firme" com suor) e o motivo do
  piso; episódio "você viu isso?" olhando para ele; recuperou "a gente aguentou"; o truque (fone e
  piscadinha, aceno = palma, ignorada vira a cara, sem beicinho); volta orgulhosa nova e habituação;
  placar Condessa × Pedro (só lazer, onde aparece, ela pode citar se ele perguntar); "isso foi sem
  sentido" (ela responde "anotado", sem ficar triste); metas 6 (inalterada), 6b (nova) e 7 (novo
  texto).
- **`persona/condessa-gosto.toml`** — chaves comentadas para o Pedro sobrepor: `torcida` (liga/peso,
  limiares 30/45 min), truque (números permitidos, mexer no fone sim/não, janela do aplauso), passo
  ≥ 2 h da volta, placar (liga, fontes, tetos, hora que fecha o dia), "sem sentido" (fator 0,7, piso
  0,3, janela 7 dias, atalho de teclado). O sistema só lê; nunca escreve.

## Ideias que ficaram de fora (para o Pedro)
- **"Bebe água"** *(A; K e S assinaram — **recomendada pelas três**)*: partida aberta > 2 h com calor ou FPS ruim →
  1 linha, 1×/partida, quando o episódio fecha ou ele para ≥ 60 s. Texto: "Duas horas nisso. Bebe
  água." (S tirou o "Pedro" da versão da A).
- **Linha do ânimo do dia no hover** *(K; A e S assinaram — **recomendada pelas três**)*: uma linha fina, sem cor
  de arco-íris.
- **Clique do meio no rosto para "a última, agora"** *(K na fala; S quis manter junto do ✗)*, com
  `B7 C12 ?` e desfazer — só se o Pedro achar que não fere "clique no rosto só reage". Assinada no voto: S.
- **Placar: "dia com ≥ 1 commit" +1 para o Pedro** *(K, como meio-termo do commit da A/S)*. Assinada no voto: K
  [S não assina: Goodhart].
- **"Pose de vitória"** como 3º número do truque *(S; A e K assinaram no voto — **recomendada pelas
  três**)*: `B4 C10 tails` 800 →
  `B16 C6 D9 P9` 1200 → `B5 C6 sway` 1000.
- **"A deusa" e "A cantora"** *(A)*, outros números do truque; e **arte nova: um leque** *(A — só se
  o Pedro desenhar)*.
- **Bis do truque** *(A, retirado)*: reavaliar com 1 semana de dados de aplauso/ignorado *(K)*. Assinada no voto: A.
- **Alívio mais de 1×/partida** *(K, só registro)*: numa tarde de 26 quedas ela só "nota" uma volta do
  FPS; não mexer agora para não virar serra de ânimo.
- **Ponto por "dormiu antes da 1h"** *(K, não proposto)*: o sistema não sabe se ele dormiu.

## Não abro mão (declarados, para a votação)
- **Aqua:** (1) ela sorri pelo menos uma vez por hora do lado dele, mesmo em jogo; (2) o truque
  termina com aceno e tem aplauso.
- **Kurisu:** (1) cada ponto do placar é uma linha do log com fonte; (2) a meta 6 passa por regra, não
  por semente — 50/50.
- **Asuka:** (1) a meta 6 não muda, muda ela, e passa por regra em 50/50; (2) o placar é honesto e o
  Pedro consegue ganhar (40–60 % dos dias).

Todos atendidos neste texto.

## Orçamento usado
Aqua ~70 mil, Kurisu ~79 mil, Asuka ~77 mil tokens no assunto inteiro (teto: 128 mil).
