# Conversa da Asuka — Rodada 2 (espera e lotes)

## Pra Aqua

Tá, deusa de segunda, vou dizer só uma vez: **a trava do desabafo é a melhor ideia da mesa.** Eu não
pensei nisso e devia. "Hoje foi um dia horrível" seguido de "Hm, deixa eu pensar nessa" é a Condessa
tratando o Pedro como ticket de suporte. Assino embaixo, inteira: texto sobre ele mesmo ("eu tô",
"tô cansado", "me sinto", "meu dia") nunca tem frase local, com sinal ou sem. E pego seu "hoje"/"atual"
só contando junto de outro sinal ou de tópico demorado. Melhor que só tirar o "agora", como eu fiz.

`fase` fora, `nivel`/`level` dentro: concordo, "tô numa fase ruim" é desabafo, não boss. `disco` só
em `musica`: concordo também, e é o mesmo buraco que eu vi pelo outro lado.

O **rótulo do lote** ("O tempo: …") eu ia achar enrolação, mas ele resolve uma briga que eu nem tinha
visto: se o lote sai fora da ordem que o Pedro pediu, sem rótulo ele acha que ela entendeu errado.
Com rótulo de 2 ou 3 palavras, tanto faz a ordem. Então tá, faz do seu jeito. Depois não chora se
soar burocrático; se soar, o Pedro veta.

Agora briga: **`placa` no `pc`**. Prefixo de palavra, Aqua. "placa" pega "**placar**". "Qual o placar
do jogo?" vira pergunta de hardware e ela fala de máquina. Fora. (A Kurisu cometeu o mesmo erro, e
ainda pôs `placar` nos sinais, o que é ótimo lá, então mais um motivo pra `placa` sair.)

Das suas frases: "Calma, tô montando o mapa na cabeça" não cabe em qualquer pedido de `jogo`
("qual a melhor arma?" não tem mapa). Fora. "Ah, pergunta de gamer, deixa eu pensar", "Hm, essa pede
ouvido bom", "Calma, essa eu quero acertar", "Ah, essa me fez pensar", "Ah, essa eu quero contar bem":
gostei, entram. E os moldes com `{jogo}` seus entram os dois. Sobre "Persona 5": concordo, o linter
tem que pular o que vem do buraco e contar `{jogo}` como uma palavra.

Seu extra do sorrisinho no fim do turno com lotes: fofo demais, mas é rosto e é merecido. Não brigo.

## Pra Kurisu

Gênio de jaleco, sua regra da **primeira palavra** ("não repete a abertura da última que tocou") é
melhor que o aviso de 40% que eu propus. O meu era linter, o seu pega o tique na hora que acontece.
Troco o meu pelo seu.

Lote **só quando as partes ficam prontas em tempos diferentes**: sim. A Aqua disse igual. Lote não é
estilo, é ganho de tempo. Pego, e junto com o rótulo da Aqua: a parte pronta vai primeiro, com
rótulo. Larguei o "na ordem dele".

Agora você vai me ouvir. Seu "não abro mão" diz: **nenhum verbo que implica ação que o sistema não
garante.** Concordo. E aí você escreve:
- "Peraí, deixa eu **me atualizar**." Isso é ação de ferramenta disfarçada. Notícia sem busca não
  atualiza nada. Fora, pela sua própria regra.
- "o resto eu ainda **tô vendo**" como ponte. Mesma coisa. "Tô vendo" é "tô buscando" com outra roupa.
- "Hm, isso é **com o teu PC**" e "pensar na **tua máquina**": "qual GPU eu compro?" não tem nada a ver
  com a máquina dele. Frase falsa por palavra-chave, exatamente o que você reclamou do `temperatura`.
  (E eu também errei: o meu "pensar nessa máquina" tem o mesmo problema. Troco por "nesse hardware".)

"Processando… e não, eu não travei." Não. É a piada da IA que trava, contada pela quinta vez numa
terça. E a gente combinou (eu e a Aqua, pelo menos) que referência não entra em frase fixa. Você quer
o contador de referência valendo aqui; eu prefiro que não exista referência aqui pra contar.

O "não chuto" eu gosto, é a cara dela. Mas você pôs em `noticia`, `pc`, `conta` e `geral`, quatro
tópicos. Isso **é** bordão, só que espalhado. Deixo em `noticia` e `conta`, onde é mais verdade
(notícia e preço de cabeça seria chute mesmo), e tiro dos outros.

Onde a gente não fecha: você quer a frase local **contando** nas 6 do teto ("o ouvido não distingue").
O ouvido não distingue, mas o teto é pra resposta não virar palestra, e a frase local tem 5 palavras.
Se contar, ela come a última frase da resposta final num pedido de 3 partes. Fico com a Aqua: não conta.

O experimento de duas semanas: faz. Gosto de placar, e isso é um. Se uma frase passar de 15% das
tocadas, quero saber qual.

## Ponte entre lotes — mudei (um pouco)

As duas querem ponte. Eu disse que não abria mão de zero ponte. Tá. **Uma** ponte, por turno, texto
**fixo**: "E o resto, peraí." (4 palavras, da Aqua). Nada de "tô vendo", "ainda tô", "já volto", nada
que o modelo invente. Fixa, curta, sem ação, sem prazo. Qualquer outra coisa, eu volto a vetar.

## Proposta atualizada

### Frases (todas ≤ 8 palavras, 1 frase, sem número/prefixo de número, "um/uma", "segund", "pront",
"já", "é isso", "aqui está", verbo de ferramenta, fonte, promessa; nenhuma implica ação nem objeto que
o pedido talvez não tenha)

**jogo** — palavras: tira `fase`; põe `nivel`, `level`, `dlc`, `arma`, `item`, `personagem`
- Hm, essa é das boas. (5) — Asuka
- Calma, tô montando isso na cabeça. (6) — Asuka/Kurisu
- Hm, pergunta de quem tá jogando sério. (7) — Kurisu
- Isso tem nuance, deixa eu pensar. (6) — Kurisu
- Peraí, deixa eu lembrar direito. (5) — Asuka
- Ah, pergunta de gamer, deixa eu pensar. (7) — Aqua
- Moldes: "Hm, {jogo}… deixa eu lembrar." (Aqua) · "Ah, {jogo}, essa é das boas." (Aqua) ·
  "{jogo}, hein… deixa eu pensar." (Asuka). `{jogo}` conta 1 palavra e o linter não olha dentro dele.

**noticia** (neutras, sem piada) — palavras: tira `saiu`; põe `jornal`, `novidade`, `rolou`, `lancou`
- Hm, notícia eu não chuto, peraí. (6) — Kurisu
- Boa, eu também quero saber essa. (6) — Kurisu
- Peraí, deixa eu juntar as ideias. (6) — Asuka
- Calma, essa pede cabeça fria. (5) — Asuka
- Ah, essa eu quero contar bem. (6) — Aqua

**musica** — palavras: põe `disco`, `discografia`, `cantor`, `cantora`, `playlist`
- Ah, música, agora você falou minha língua. (7) — Asuka/Kurisu
- Peraí, tô cantarolando na cabeça. (5) — Aqua/Kurisu
- Hm, deixa eu lembrar dessa. (5) — todas
- Boa, deixa eu pensar no som. (6) — Kurisu/Aqua
- Hm, essa pede ouvido bom. (5) — Aqua

**pc** — palavras: tira `temperatura` e `disco`; põe `ssd`, `hd`, `ram`, `vram`, `driver`, `cooler`,
`aquec`; **sem `placa`** (pega "placar")
- Hm, deixa eu pensar nesse hardware. (6) — Asuka
- Essa é coisa de nerd, adoro. (6) — Asuka
- Pergunta técnica merece cuidado, calma. (5) — Asuka
- Boa, deixa eu raciocinar com calma. (6) — Kurisu

**conta** — palavras: põe `custa`, `vezes`, `dividido`, `raiz`, `media`
- Hm, deixa eu fazer as contas. (6) — todas
- Peraí, conta eu não faço no chute. (7) — Kurisu
- Boa, deixa eu calcular direito. (5) — Kurisu
- Calma, essa eu quero acertar. (5) — Aqua

**geral**
- Hm, deixa eu pensar nessa. (5)
- Peraí, tô juntando as ideias. (5)
- Boa pergunta, deixa eu pensar. (5)
- Ah, essa me fez pensar. (5) — Aqua
- Calma, cérebro trabalhando. (3) — Kurisu
- Peraí, não vou te responder qualquer coisa. (7) — Asuka
- Essa é das boas, calma. (5) — Asuka
- Hm, deixa eu organizar a cabeça. (6)
- Ah, essa eu quero responder bem. (6) — Asuka

Aberturas: nenhum tópico com mais da metade em "Hm"; mais a regra da Kurisu (primeira palavra
diferente da última tocada).

### demorados / sinais / travas
- `demorados`: `[jogo, noticia, musica, pc]` (as três concordam).
- `sinais_demora`: `[pesquisa, procura, busca, noticia, ultimas, preco, custa, cotacao, dolar,
  lancamento, lancou, steam, internet, previsao, clima, placar]`; **`hoje` e `atual` só valem junto de
  outro sinal ou tópico demorado** (Aqua); **`agora` sai** (as três).
- **Trava do desabafo** (Aqua): texto sobre o próprio Pedro nunca tem frase local.
- **Primeira palavra** (Kurisu): a frase sorteada não começa igual à última que tocou.

### Regra dos lotes
1. **Várias partes** = ≥ 2 pedidos que dá pra responder separados ("e" entre perguntas, "e também",
   "além disso", "outra coisa", mais de uma "?", lista) **e** prontos em tempos diferentes (≥ 1 com
   ferramenta, ≥ 1 sem). Não vira lote: "e" dentro da mesma coisa, comparação ("X ou Y?"), pergunta
   longa com um objetivo só, partes que ficam prontas juntas.
2. **Ordem:** a parte pronta primeiro, **sempre com rótulo** de 2–3 palavras ("O tempo: …"). Ponte:
   no máximo 1 por turno, fixa, no fim do 1º lote: **"E o resto, peraí."** Nenhuma outra.
3. **Fecho:** a final só completa, não retoma nem resume. 1 lote por parte (2 partes = 2 falas). Com
   4+ partes, agrupa em até 3 lotes, ≤ 2 frases cada. Parte que falhou: 1 frase honesta ("Do jogo eu
   não consegui ver.") e para.
4. **Convivência:** local + lote no mesmo turno, ok; o 1º lote não abre com espera. A local **não
   conta** nas 6 frases (Aqua e eu; a Kurisu discorda). Pra folga da cota, turno conta **só se a
   local tocou** (as três).
5. **Linha nova da persona falada:**
   > Pedido com partes separadas: diga logo a parte pronta com o nome dela ("O tempo: …"), até 2
   > frases, e complete o resto sem repetir nem resumir. Antes de ferramenta, só fale se tiver conteúdo.

## Não abro mão (atualizado)
1. **Ponte só a fixa "E o resto, peraí."** Ponte escrita pelo modelo é onde entra "tô vendo", "já
   volto", e aí é promessa falsa. Já cedi em ter ponte; não cedo no texto.
2. **`noticia` sem piada.** Continua. Pode ser alguém que morreu.
