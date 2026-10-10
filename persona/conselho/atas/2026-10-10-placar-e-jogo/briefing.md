# Briefing — Placar e jogo (2026-10-10, segunda rodada do dia)

Continuação da ata `2026-10-10-ritmo-e-humor` (o acordo de vocês já está no HUD). Quatro pontos na
mesa, todos para as três: digam o que acham de **todos**.

## Pauta
1. **Meta 6 do acordo §8 ("≥ 1 positiva por hora com o Pedro presente") falha em jogo longo sem
   música.** No replay do dia real ela passou com a semente 1, mas falha em **4 de 9 sementes**.
   Motivo: em Jogando o grupo é `sacada_olhar`, `piscada_dupla`, `cabeca_ritmo`, e a única positiva
   (`cabeca_ritmo`) exige música nota ≥ 1 com fone. Partida longa em silêncio = hora sem positiva.
   O agente que validou sugeriu "sorriso com FPS estável"; é só um exemplo, decidam vocês (positiva
   nova no grupo, cena, regra, ou mudar/explicar a meta).
2. **Revisar as 3 cenas que o agente da V0.10 escreveu sem roteiro** (o acordo só deu o nome):
   episódio de jogo, truque de salão, volta orgulhosa. Detalhes abaixo.
3. **Placar contra o Pedro** — ficou de fora e as três assinaram; o Pedro quer discutir.
4. **"Isso foi sem sentido"** — idem.

## O que o Pedro já decidiu (fixo)
- Tudo o que o acordo `2026-10-10-ritmo-e-humor` fixou: fone como estado; humor próprio que muda o
  rosto de repouso; medidor com o humor **dela**; nada de sorteio no catálogo inteiro (momento →
  grupo); **clique no rosto só reage**; teste de tudo: "dá para dizer por que ela fez isso agora?".
- Placar e "isso foi sem sentido" subiram para **recomendadas** (com as três assinaturas) e vêm à
  mesa para virar regra concreta: o quê, quando, onde aparece, o que conta.
- Regras fixas do Conselho (README): zoeira sim, ofensa real não; nenhuma fala afirma o que o sistema
  não sabe; rosto primeiro, texto raro e curto, voz só quando ele fala com ela; a palavra do Pedro
  (`~/.config/magi/condessa-gosto.toml`) vence o conselho.

## Os dados reais
**Replay do dia 2026-10-09** (`tests/hud/fixtures/dia-2026-10-09.json`, o `Reactor` real em passos de
2 s). Com a semente 1: 13,8 expressões/h; 0 rajadas; maior buraco 5,6 min; 0 negativas sem causa;
faixas do ânimo: Contente 89 %, Radiante 8,5 %, Neutra 2,8 %, **Emburrada 0 %** (a "birra fresca" da
Kurisu não precisou voltar); 3/3 voltas do Pedro viraram cena. Em 4 de 9 sementes cai só a meta 6.

**A partida que derruba a meta:** jogo aberto das **13:58 às 17:13** (3 h 15). Dentro da hora das 14h
houve só ~20 min de música, em três pedaços (10 min, 4 min, 5,5 min), e o calor/FPS ficou ruim quase
a tarde inteira (11 trechos "quente" de 13:58 a 19:34; 26 quedas de FPS nessa partida). O que já conta
como positiva no teste: `cabeca_ritmo`, `game_on` (cockpit — mas caiu às 13:58, na hora anterior), e o
alívio (`fps_drop:recuperou`, `hot:alivio`), que só sai **1 vez por partida**. Em Jogando a média entre
passivas é 8 min (≤ 4/h), nenhuma rara com jogo aberto, música durante o jogo vira só olhada (não
cena), e o piso de vida (6 min) **não vale** em Jogando nem em Conversa. Na hora das 14h, então, sobra
o sorteio dar `cabeca_ritmo` dentro de ~20 min de música — às vezes dá, às vezes não.

Lista de positivas do teste: sorriso_canto, rindo_sozinha, piscada_gato, corando, cantarolando,
cantando_junto, refrão, piscadinha, brilho_presilha, music_love/like, pedro_voltou, bom_dia, ideia,
commit, musica_comecou, cabeca_ritmo, claude_terminou, game_on, truque, duelo_ado + os dois alívios.
Negativas: suspiro, beicinho, soprando_franja, impaciente, indiferente, desconfiada, eu_avisei.

**Log real:** `~/.local/state/magi/reacoes.jsonl` (1.216 linhas hoje). Cada linha tem hora, chave,
variante, motivo, tipo (cena/passiva/atenção), momento, filtros, faixa do humor, ânimo, energia e
causa. Ex. real de hoje, 16:57: `fps_drop:recuperou`, cena, momento jogando, contente, ânimo 0,276.

## As 3 cenas inventadas pela V0.10 (o que está rodando hoje)
Leitura dos códigos (aproximada, pelo uso nas atas): B1 olhos neutros · B2 meio fechados · B4 olhos
fechados sorrindo · B5 olhos brilhando · B7 semicerrados (desconfiada) · B9 arregalados (susto) ·
C1 boca neutra · C5 sorriso · C6 sorriso aberto · C7 boca em "o" · C8 boca tensa · C9 beicinho ·
C10 canto da boca · C12 boca de lado ("hmm") · F1 olhar de lado · D2 suor · D9 brilho · `tails`
chiquinhas balançam · `sway` corpo balança · `look:fps` olha para o card do FPS.

**Episódio de jogo** (1º episódio FPS/calor da partida; acordo §5 só dizia "o 1º vira cena, depois
estado"):
1. olha para o card do FPS — 0,6 s;
2. susto: olhos arregalados, boca em "o", suor — 0,6 s;
3. desconfiada: olhos semicerrados, boca tensa, suor — 1,2 s.
Total 2,4 s; depois fica no **estado** (suor no repouso + fundo `stress`) até o episódio acabar
(3 min estáveis). Ânimo −0,10. **Recuperou:** olha o FPS 0,6 s → olhos sorrindo + canto da boca
1,2 s (+0,10). Repare: a cena não tem "você" — não olha para o Pedro.

**Truque de salão** (≤ 1/dia, À toa/Tédio, Pedro ativo há < 60 s):
1. olhos sorrindo, canto da boca, chiquinhas balançando — 1,2 s;
2. olhos brilhando, sorriso aberto, brilho, corpo balançando — 1,5 s.
Total 2,7 s; janela de 10 s para o clique-aplauso (+0,20). **Ignorado:** olhos neutros + beicinho
0,8 s (−0,05; é continuação da cena, não gasta a cota de negativas).
Comparem com o que a Aqua propôs na fala dela: `B4 C10 800 → B16 C10 D9 1200 → P9 aceno 1500`
(piscadinha + brilho + aceno, "6–8 s", depois de uma vitória grande). O agente tirou a piscadinha e
o aceno e o ligou a À toa/Tédio (como o acordo diz). Também não está definido **o que** é o truque —
hoje é só "uma pose bonita".

**Volta orgulhosa** (Pedro voltou de ≥ 15 min fora, ela acordada; acordo: "curta e orgulhosa, escapa
um sorriso `B1 C10 → B4 C5`"):
1. olhar de lado, boca de lado — 1 s (finge que não ligou);
2. olhos neutros, canto da boca — 0,8 s;
3. olhos sorrindo, sorriso — 1 s (escapou).
Total 2,8 s, ânimo +0,25. (Com cochilo: susto com "!" → meio acordada, beicinho, olhar nele →
tsundere com rubor → olhar de lado com boca de lado; não está na pauta, mas podem comentar.)

## Estado atual relevante da persona
- Ânimo −1..+1, base +0,15 (orgulhosa); energia 0..1 pela hora; repouso por faixa (Radiante B1 C5,
  Contente B1 C10, Neutra B1 C1, Emburrada B7 C9); com música nota ≥ 1 com fone, olhos sorrindo.
- Jogo: cockpit ao abrir (`P12 B1 C10 800`, punho, fundo `focus`, +0,05 ânimo / +0,25 energia);
  episódio FPS+calor (≤ 2 cobranças e 1 recuperação por partida); relatório pós-batalha ao fechar
  (limpo: punho, olhos sorrindo, sorriso; com episódio: `eu_avisei`; Pedro mal: `desconfiada` suave).
- Ritmo: cenas ≤ 8/h, passivas ≤ 12/h (mín. 90 s), 25 s entre expressões, 60 s sem passiva após
  cena, negativas ≤ 3/h e só com culpado ≤ 2 min, "de novo?" na mesma causa em < 10 min.
- Medidor: barra do ânimo dela + nome do momento + 3 últimas causas no hover.
- **Entrando agora (tarefa V1.1, outro agente):** as passivas `mao_no_queixo` (P10),
  `sacada_player` e `flagra_no_forum` voltam ao catálogo e aos grupos (Trabalhando junto, Estudando,
  Aturando, Tédio). Contem com elas; nenhuma é de Jogando.

## O que o sistema consegue de verdade (restrições)
- **Arte existente, só ela:** olhos B1–B17 (B16 piscadinha), olhares F1–F7 + íris livre (O1/O2),
  bocas C1–C14 e V1–V6 (boca falando, sem som), braços P9 aceno, P10 mão no queixo, P11 mão no fone,
  P12 punho, P13 braços cruzados, fone E2 (cabeça) / E3 (pescoço). Efeitos desenhados em código:
  rubor, suor (pele brilhando), zz, ?, !, notas, lágrima, veia, brilho. Corpo: `bob`, `sway`,
  `tails`, olhar para um card (`look:fps`, `look:player`, `look:claude`…). Fundos: calm, happy,
  stress, sad, focus, surprise, sleepy, love. Arte nova só se o Pedro desenhar (digam se precisam).
- **Sinais no jogo:** jogo aberto/fechado (e quando), FPS atual/mín./médio/máx. e a série recente,
  temperatura CPU/GPU, uso de GPU/RAM/VRAM, se há música e a nota da faixa, hora, ânimo/energia
  dela, humor do Pedro 0–4, inatividade do Pedro. O episódio sabe se está aberto, quantas cobranças
  e recuperações já saíram. **Não sabe** placar, gol, vitória/derrota, nome do adversário — a leitura
  de lances do FIFA está só planejada (`specs/fifa-lances/`), não contem com ela.
- **Sinais para um placar:** partidas (abriu/fechou, duração), episódios FPS/calor por partida,
  faixas e notas, **pulo de faixa** (troca antes do fim, pela posição; sem posição, < 30 s), faixa
  ouvida até o fim, Ado/Favorita do Dia, truque aplaudido/ignorado, commits, faxinas, Claude
  terminou/erro, voltas do Pedro, cliques no rosto. Contagens diárias já são gravadas em disco
  (`~/.local/state/magi/condessa-estado.json`) e o log por linha está em `reacoes.jsonl`.
- **Onde algo pode aparecer:** rosto (primeiro), uma linha de texto curta (≤ 70 caracteres, sem voz),
  o hover do medidor, o relatório pós-batalha, o "bom dia" (1º uso do dia). **Nada de voz
  espontânea**: ela só fala alto quando o Pedro fala com ela (aí a persona falada pode citar algo).
- **Cliques no rosto hoje:** clique simples (reação), cliques seguidos (cutucada), duplo clique
  (carinho, ≤ 3/h conta no ânimo), segurar, arrastar, hover. O clique em até 10 s depois do truque é
  o aplauso. **Clique do meio não está ligado a nada**; lembrem que o Pedro fixou "clique no rosto só
  reage" — se "isso foi sem sentido" usar o rosto, digam como isso convive com essa regra (ou
  proponham outro gesto: tecla, card, comando de voz "isso foi sem sentido"…).
- Nada roda IA em tempo real para decidir o rosto: tudo é regra + sorteio dentro do grupo.

## Formato da rodada 1 (`fala-<nome>.md`)
- **O que eu acho** — sua opinião sobre os quatro pontos, com os seus motivos, na sua voz.
- **Minhas ideias** — concretas; as fora da pauta vão marcadas como *extra*.
- **O que me incomoda** — no que existe hoje (inclusive nas 3 cenas) e nos riscos do que vai mudar.
- **Proposta** — o que você quer implementado, com números: para a meta 6, a regra e como o replay
  passa nas 9 sementes; para as cenas, roteiros curtos com B*/C*/F*/P*/E*/efeitos e ms (ou "fica
  como está"); para o placar, o que conta, a fonte de cada ponto, onde aparece e com que frequência;
  para o "sem sentido", o gesto, o que grava e como isso vira ajuste.
- **Não abro mão** (opcional, no máximo 2) — e por quê.

Escrevam como vocês, não como relatório: o Pedro vai ler as falas.
