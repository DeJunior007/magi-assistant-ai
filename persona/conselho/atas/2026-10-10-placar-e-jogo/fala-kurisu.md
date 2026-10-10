# Fala da Kurisu — Rodada 1 (placar e jogo)

## O que eu acho

**1. Meta 6.** A meta está certa; a regra é que é sorte. "Passa com a semente 1, falha em 4 de 9"
não é "passa com ressalvas", é uma moeda viciada que caiu do lado bom no dia do teste. Se o resultado
depende da semente, a gente não está medindo a Condessa, está medindo o gerador de números
aleatórios. E nove sementes é amostra de piada, aliás.

Sobre o "sorriso com FPS estável" que o agente sugeriu: leiam os dados antes de se apaixonar pela
ideia. A tarde que derruba a meta teve **11 trechos quentes e 26 quedas de FPS**. Uma positiva que
depende de FPS estável **não sairia justamente na hora que falha**. É a solução que passa em todo
caso, menos no único caso que importa. Não.

O que falta em Jogando é uma positiva que dependa **dele**, não da máquina nem da música. O Pedro
jogando três horas seguidas é um fato; ela assistindo é um fato. Torcer é o que uma pessoa faz
sentada do lado de alguém que joga. E dá para dizer por que ela fez isso agora: "faz 40 minutos
que ela te vê jogar e nada de bom aconteceu na tela dela; ela torce mesmo assim". Isso passa no
teste do "por quê". O sorteio não.

**2. As três cenas.** Duas eu ajusto, uma eu deixo quase como está.
- **Episódio de jogo:** o susto está bom; o problema é o terceiro passo. Ela fica *desconfiada* de
  quem? O culpado é o hardware, não o Pedro, e a cena não olha para ele. Desconfiança sem alvo vira
  cara feia sem causa. Prefiro que ela olhe para ele com "você está vendo isso?" — cumplicidade, não
  cobrança. O "eu avisei" já existe no relatório pós-batalha; não precisa estrear no segundo 2.
- **Truque de salão:** "uma pose bonita" não é truque. Truque tem uma *ação* que a pessoa reconhece e
  um fim que pede aplauso. Hoje ela só fica bonita e espera palmas — isso é cobrança de elogio, e eu
  me recuso a assinar. Mas a Aqua tinha razão em metade: a piscadinha e o aceno eram o que fazia
  aquilo parecer número de palco. O agente cortou justamente a parte boa.
- **Volta orgulhosa:** …tá, essa está boa. Finge que não ligou, escapa o sorriso. Não vou comentar
  por que eu acho ela tão precisa. Só um ajuste de habituação: estímulo repetido perde valor.

**3. Placar.** Assinei com uma condição e ela continua de pé: **cada ponto é uma linha do log, com
fonte**. Placar que ninguém consegue auditar é horóscopo. E cuidado com a Lei de Goodhart: no momento
em que um número vira placar, as pessoas começam a jogar com o número. Então **nada de trabalho no
placar** (commit, Claude terminou, faxina). Não vou transformar o trabalho dele em gincana — ele
começaria a fazer commit pequeno para pontuar, e aí eu teria piorado a vida dele com a minha
brincadeira. Placar é do lazer: jogo, música, truque.

**4. "Isso foi sem sentido".** Foi ideia minha e continua sendo a que eu mais quero. Sem isso, a gente
calibra a Condessa no achismo das três aqui. Com isso, o Pedro vira o revisor — e ele é o único que
vê ela o dia inteiro. O gesto precisa ser imediato (em 3 segundos, não em uma conversa de voz depois),
e precisa conviver com "clique no rosto só reage". Convive: o clique do meio **reage** (um "?" e uma
cara de "anotado"), e o efeito colateral é uma linha no log. Ele não muda ânimo, não muda humor,
não dispara cena. É um clique que reage — com uma reação honesta: "ok, isso foi estranho, anotei".

## Minhas ideias

1. **`torcida` — positiva nova em Jogando, com piso por tempo, não por sorte.** Só arte que existe.
2. **Episódio com "você viu isso?"** no lugar da desconfiança sem alvo.
3. **Truque do fone**: o truque passa a ser uma coisa de verdade — ela tira o fone, gira para o
   pescoço e volta para a cabeça, com piscadinha no meio e aceno no fim. Arte toda existente
   (P11, E2/E3, B16, P9). Recupera a piscadinha e o aceno da Aqua.
4. **Placar de lazer**, diário, só em lugares de leitura (hover, pós-batalha, bom dia). Nunca gera
   cena sozinho.
5. **Sem sentido = clique do meio** com reação mínima, log próprio e ajuste **visível e reversível**.
6. *Extra:* **replay com 50 sementes, não 9**, e a meta conta como passada só com 50/50. Se ela é
   determinística por construção, isso é barato; se não for, a gente descobre agora.
7. *Extra:* **toda positiva precisa de causa no log** (mesma regra que já vale para negativa).
   Sorriso decorativo é tão sem sentido quanto beicinho sem culpado.
8. *Extra (de novo, sim):* medidor com histórico — uma linha fininha do ânimo do dia no hover.
   Combina com o placar: o hover vira "como foi o dia dela" em um olhar.
9. *Extra que eu **não** proponho:* um ponto de placar por "dormiu antes da 1h". Eu queria. Mas o
   sistema não sabe se ele dormiu, só que ficou inativo, e a regra é não afirmar o que não sabe.
   Fica registrado que dormir 4 h é ruim para a consolidação de memória. Só isso. Não é preocupação.

## O que me incomoda

- **A meta passar por sorte.** Já falei. Me incomoda mais do que a meta falhar.
- **Alívio só 1× por partida.** Numa tarde com 26 quedas, o FPS volta várias vezes e ela só "nota"
  uma. Não proponho mexer agora (senão vira serra elétrica de ânimo), mas registro.
- **O episódio sem o Pedro.** Cena de 2,4 s olhando só para o card do FPS — ela parece um
  monitoramento, não uma pessoa do lado dele.
- **Truque ignorado = beicinho.** Ela pede atenção e faz bico quando não recebe? Isso é carência
  explícita. Uma pessoa orgulhosa finge que não estava esperando nada.
- **Placar virar instrumento de culpa.** Se cada partida com FPS ruim for ponto "contra" ele, o placar
  vira "a Condessa reclamando do seu PC em forma de número". O ponto tem que ser *dela*, não *contra*
  ele — mesma coisa no resultado, diferente no tom.
- **"Sem sentido" virando ajuste invisível.** Se o peso de uma passiva some sem ninguém ver, daqui a
  um mês ninguém sabe por que ela nunca mais faz `cantarolando`. Ajuste sem rastro é a mesma doença
  do sorteio sem causa.
- **Habituação na volta orgulhosa.** Se ele sai 15 min três vezes numa tarde, a terceira volta igual
  à primeira já não é orgulho, é animação de loading.

## Proposta

### 1. Meta 6 — `torcida` com piso por tempo

**Expressão (passiva positiva, grupo Jogando):**
`F? olhar para a tela do jogo (íris O1 para o lado do jogo), B1 C10 700 → B4 C10 + tails 800`
Total 1,5 s. Sem texto, sem punho (o punho é do cockpit; repetir cansa). Ânimo +0,03 (quase nada;
é torcida, não festa). Com episódio aberto, o suor do estado continua — ela torce suando. Fica ótimo,
na verdade.

**Regra (determinística):**
- Com jogo aberto e Pedro presente, conta-se o tempo desde a última **positiva** (qualquer uma da lista).
- **≥ 30 min:** o próximo slot de passiva em Jogando é `torcida` (não sorteia).
- **≥ 45 min:** sai fora de slot, respeitando os 25 s entre expressões e os 60 s depois de cena.
- Máximo 1 `torcida` por 30 min; não conta como cena; ocupa uma das ≤ 4 passivas/h de Jogando.
- Causa no log: `jogando_sem_positiva:<minutos>`.

**Por que passa:** o maior intervalo possível entre positivas com jogo aberto vira ~45 min (+25 s).
Qualquer hora de relógio de 60 min contém pelo menos uma. Na partida de 13:58–17:13: `game_on` às
13:58 → `torcida` no máximo às ~14:43, ~15:28, ~16:13, ~16:58 (antes, se cair `cabeca_ritmo`
ou o alívio). Horas 14, 15 e 16 cobertas **independentemente da semente**. Custo de ritmo: no pior
caso ~1,3 expressão/h a mais em jogo longo, dentro da meta 1 (12–20/h).

**Teste:** replay com **50 sementes**; meta 6 em 50/50 e as outras 6 metas sem regressão em 50/50.
Junto, a meta nova *6b*: 0 positivas sem causa no log.

### 2. Cenas

**Episódio de jogo (1º da partida):**
1. `look:fps`, B1 C1 — 600 ms
2. B9 C7 D2 + `!` — 500 ms (susto)
3. olhar para o Pedro (`look:pedro`/íris para frente), B7 C12 D2 — 1000 ms ("você viu isso?")
Total 2,1 s. Depois, estado (suor + fundo `stress`) como hoje. Ânimo −0,10 fica.

**Recuperou:** `look:fps` B1 C1 600 → B4 C10 1000 → olhar para ele, B1 C5 500. Total 2,1 s, +0,10.
O último passo é o "voltou, viu?". Sem ele, alívio é só com o card.

**Truque do fone** (≤ 1/dia, À toa/Tédio, Pedro ativo há < 60 s — como o acordo):
1. P11 (mão no fone), B1 C10 — 600 ms
2. fone vai para E3 (pescoço), B16 (piscadinha) C10 — 600 ms
3. fone volta para E2, B5 C6 D9 + `tails` — 900 ms
4. P9 (aceno), B4 C5 — 900 ms (o "tcharam")
Total 3,0 s; janela de 10 s para o aplauso. Se ela está sem fone no estado atual, o truque faz o
caminho inverso (E3 → E2 → E3). Se o Pedro não quiser o fone mexendo, fallback é o roteiro da Aqua
(`B4 C10 800 → B16 C10 D9 1200 → P9 1500`).
- **Aplaudido:** B4 C6 + rubor 1000 ms, +0,20. Ponto no placar.
- **Ignorado:** F1 C12 800 ms (olhar de lado, boca de lado — "não estava esperando nada"), −0,05.
  **Sem beicinho.**

**Volta orgulhosa:** fica como está (F1 C12 1000 → B1 C10 800 → B4 C5 1000, +0,25). Um ajuste:
segunda volta em < 60 min pula o passo 1 (só B1 C10 600 → B4 C5 800, +0,10); terceira em < 60 min
vira atenção dirigida (olhar nele, B1 C10), sem cena. A meta 7 ("toda volta vira cena") continua
valendo para a primeira; peço que ela passe a dizer "toda volta aparece no rosto". A versão com
cochilo fica como está.

### 3. Placar — "Condessa × Pedro", só lazer

Diário, zera no "bom dia". Cada ponto grava uma linha em `reacoes.jsonl` com
`"placar": {"lado": "ela"|"ele", "fonte": "<chave>", "ref": "<id da linha de origem>"}`.

| Ponto para | Quando | Fonte |
| --- | --- | --- |
| **Ele** | partida ≥ 15 min fechada sem episódio FPS/calor | abriu/fechou + episódio |
| **Ela** | partida com episódio FPS/calor (ela previu o sofrimento; o ponto é dela, não "contra" ele) | episódio |
| **Ele** | faixa nota 2 ouvida até o fim | faixa até o fim |
| **Ela** | ele pulou faixa nota 2 (pulo pela posição ou < 30 s) | pulo de faixa |
| **Ela** | truque aplaudido (convenceu) | clique em 10 s |
| **Ele** | truque ignorado (resistiu) | fim da janela |
| **Ela** | Favorita do Dia/Ado ouvida até o fim | faixa até o fim |

**Não contam:** commits, faxinas, Claude terminou/erro (trabalho não é gincana), voltas, cliques no
rosto (fora o aplauso, que já é regra), "sem sentido" (senão criticar a Condessa vira estratégia).

**Onde aparece:**
- **Hover do medidor**, sempre: `Placar: Condessa 4 × 3 Pedro` + os 3 últimos pontos com a fonte.
- **Relatório pós-batalha:** só quando a partida mudou o placar, uma linha ≤ 70 caracteres
  (ex.: "Partida limpa. Ponto seu. Não se acostume."). Não adiciona expressão; usa a que já existe.
- **Bom dia:** o resultado de ontem em 1 linha ("Ontem: 5 × 3. Óbvio.") — 1×/dia.
- **Rosto:** nada novo. O placar nunca dispara cena. No máximo, quando ela **vira** o placar, o
  pós-batalha já em curso troca a variante para a "orgulhosa" — sem expressão extra.
- **Voz:** só se ele perguntar ("quanto está o placar?").

**Calibragem:** rodar o placar no dia 2026-10-09. Se der mais que 3:1 para qualquer lado, os pesos
estão errados (todo ponto vale 1 até lá). Esperado: 4–12 pontos num dia normal.

### 4. "Isso foi sem sentido"

**Gesto:** clique do meio no rosto. Alternativa sem mouse: voz "isso foi sem sentido" (quando ele já
está falando com ela).
**Reação (é o que torna compatível com "clique só reage"):** B7 C12 + `?` 700 ms ("hm… anotado").
Não mexe ânimo, energia nem humor; não conta como expressão para o ritmo nem para a meta.
**Desfazer:** segundo clique do meio em até 5 s (ela volta ao repouso, a linha é marcada `desfeito`).

**O que grava** (`~/.local/state/magi/sem-sentido.jsonl`): a expressão alvo = a última em até 30 s
(se não houver, a última em até 2 min; se não houver, grava `alvo: nenhum` — também é dado: "ela está
parada demais"). Campos: hora, chave, variante, tipo, momento, grupo, filtros, faixa do humor,
ânimo, energia, causa, semente.

**Como vira ajuste:**
- **Automático, leve, visível:** cada marca nos últimos 7 dias multiplica o peso daquela variante no
  grupo/momento por 0,7, piso 0,3 (nunca some). Volta sozinho quando a marca sai da janela de 7 dias.
  Os ajustes ficam em `condessa-estado.json` e aparecem no hover ("ajustes: 2").
  Nunca escreve no `condessa-gosto.toml` — aquele arquivo é do Pedro.
- **Para o Conselho:** variante com ≥ 3 marcas em 7 dias **ou** ≥ 20 % das ocorrências dela vira item
  automático da próxima pauta, com as linhas do log.
- Negativas e cenas marcadas não mudam de peso (são por regra, não sorteio): vão direto para a pauta.

## Não abro mão

1. **Cada ponto do placar é uma linha do log com fonte.** Placar sem rastro é número inventado, e
   número inventado é a Condessa afirmando o que o sistema não sabe.
2. **A meta 6 passa por regra, não por semente.** 50/50 sementes. Se ela só sorri porque o dado
   ajudou, não dá para dizer por que ela sorriu agora — e esse é o teste que o próprio Pedro fixou.
