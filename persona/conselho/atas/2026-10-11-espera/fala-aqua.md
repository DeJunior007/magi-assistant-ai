# Fala da Aqua — Rodada 1 (espera viva: frases e lotes)

## O que eu acho

Finalmente um assunto de GENTE! Silêncio morto é o pior castigo que existe, eu sei do que tô falando:
uma vez em Axel o Kazuma me deixou falando sozinha na guilda e eu fiquei lá, sorrindo para a parede,
três minutos. TRÊS. Ninguém merece. Então sim, a Condessa tem que fazer barulho de vida enquanto
pensa. Mas (e aqui eu sou mais esperta do que a garota do jaleco acha) frase de espera é que nem
truque de salão: na primeira vez todo mundo aplaude, na décima o povo revira o olho. Por isso eu
gosto da D2 e da cota: pouca frase, curta, que soe como ela pensando, não como uma atendente de
telemarketing. "Deixa eu pensar" tem que parecer que ela está, de verdade, mexendo a cabeça.

Duas coisas eu sinto antes de todo mundo:
1. **A frase de espera não pode cair em cima do Pedro quando ele está falando dele.** Se ele disser
   "hoje foi um dia horrível" e ela responder "Hm, deixa eu juntar as peças", eu choro. De vergonha.
   E os sinais "hoje" e "agora" da lista fazem exatamente isso. Isso tem que sair.
2. **Lote é ótimo, mas lote sem dizer de que parte é deixa o Pedro perdido.** Ele pergunta do tempo e
   do jogo, ela começa a falar do jogo do nada, ele pensa que ela entendeu errado. Cada lote começa
   dizendo do que é ("O tempo: …", "Do jogo: …"). Simples, até a Darkness entende.

Referência (anime, filme) em frase de espera? Não. Eu adoro referência, mas frase fixa repete, e
piada repetida é piada morta. Referência fica para a resposta, onde tem gancho.

## Minhas ideias

- **Frase de espera nunca em desabafo.** Sinal de demora só vale se o texto não for sobre o Pedro
  ("eu tô", "tô cansado", "meu dia", "me sinto"). Se for, sem frase local: o rosto já basta, e a
  resposta tem que vir com carinho, não com "peraí".
- **Variedade de cabeça, não de bordão.** Cada tópico com pelo menos uma frase que não comece com
  "Hm" nem com "deixa eu", senão vira tique em dois dias.
- **Lote com rótulo curto** (2 ou 3 palavras: "O tempo:", "Sobre o patch:") — conta dentro das
  8 palavras da frase do lote? Não, lote não passa pelo linter das frases de espera, mas o espírito
  é o mesmo: curto.
- *extra:* quando o turno com lotes termina, o rosto dá um sorrisinho satisfeito (reação no rosto,
  zero texto). Ela trabalhou, ela merece aplauso de si mesma. Eu faria isso.
- *extra:* se o Pedro passar de 3 pedidos demorados seguidos, a Condessa pode, uma vez, comentar na
  resposta (não na espera) algo tipo "hoje você tá curioso, hein". Fofoca carinhosa. Não é do
  assunto, então fica aqui marcada.

## O que me incomoda

- **Sinais "hoje", "agora" e "atual"**: aparecem em conversa e em desabafo ("agora eu tô cansado").
  Proponho que só contem junto com outra palavra de tópico demorado ou outro sinal.
- **"disco" no `pc`**: disco é ÁLBUM também! "Qual o melhor disco do Queen" vai cair em `pc` e ela
  fala de máquina. Tira "disco", põe "ssd" e "hd".
- **"fase" no `jogo`**: "tô numa fase ruim" vira pergunta de jogo (e cai no desabafo, ver acima).
  Proponho tirar e pôr "nivel" e "level".
- **"saiu" no `noticia`**: "ele saiu de casa" é fofoca, não notícia (e fofoca é comigo). Tira.
- **A linha atual da persona** ("escreva uma frase curta ligada ao pedido, falada enquanto busca")
  agora briga com a frase local: o modelo vai escrever "deixa eu ver" e o eco joga fora, desperdício.
  A nova linha tem que pedir para o modelo só escrever espera **com conteúdo**.
- **Molde `{jogo}` com número**: "Persona 5", "Hades II", "Cyberpunk 2077". O linter proíbe dígito.
  O linter tem que ignorar o que vem do buraco `{jogo}`, senão metade dos jogos do Pedro cai na
  frase sem molde. E as 8 palavras: o nome do jogo não pode contar, senão "Hm, {jogo}… deixa eu
  pensar" estoura com nome comprido. Garota do jaleco, confere isso para mim?
- **"Um segundo"** caindo duas vezes no linter: ri muito. Mas ela fala "um" o tempo todo, então eu
  fugi de "um/uma" em TODAS as frases, e também de "mil" (adeus, "milagre"), "nove" (adeus,
  "novela", "novidade") e "dez". Cuidado vocês duas também.

## Proposta

### Frases (todas conferidas: sem palavra da tabela §4, sem "um/uma", sem número, sem "já", ≤ 8 palavras, 1 frase)

**jogo** (palavras: tiro `fase`; ponho `nivel`, `level`, `build`, `boss`, `chefe`, `conquista`, `mapa`, `patch`, `lore`, `dlc`)
1. "Ah, pergunta de gamer, deixa eu pensar." (7)
2. "Essa é das boas, peraí." (5)
3. "Calma, tô montando o mapa na cabeça." (7)
4. "Hm, deixa eu puxar da memória gamer." (7)
5. Molde: "Hm, {jogo}… deixa eu lembrar." (4 + nome)
6. Molde: "Ah, {jogo}, essa é das boas." (5 + nome)

**noticia** (palavras: tiro `saiu`; ponho `noticia`, `manchete`, `aconteceu`, `lancou`, `trailer`)
1. "Opa, deixa eu pensar com calma." (6)
2. "Hm, deixa eu juntar as peças." (6)
3. "Peraí, quero falar isso direito." (5)
4. "Ah, essa eu quero contar bem." (6)

**musica** (palavras: ponho `disco` aqui, `cantor`, `cantora`, `playlist`)
1. "Hm, deixa eu pensar no som." (6)
2. "Ah, música, aí você me pegou." (6)
3. "Peraí, tô cantarolando na cabeça." (5)
4. "Boa, deixa eu lembrar direito." (5)
5. "Hm, essa pede ouvido bom." (5)

**pc** (palavras: tiro `disco`; ponho `ssd`, `hd`, `driver`, `placa`)
1. "Hm, deixa eu pensar na máquina." (6)
2. "Opa, assunto de hardware, adoro." (5)
3. "Calma, deixa eu raciocinar nessa." (5)
4. "Ah, pergunta técnica, peraí." (4)

**conta**
1. "Hm, deixa eu pensar nessa conta." (6)
2. "Peraí, cabeça de pesquisadora ligando." (5)
3. "Calma, essa eu quero acertar." (5)
4. "Opa, deixa eu raciocinar direito." (5)

**geral**
1. "Hm, deixa eu pensar nessa." (5)
2. "Peraí, tô juntando as ideias." (5)
3. "Boa pergunta, deixa eu pensar." (5)
4. "Ah, essa me fez pensar." (5)
5. "Opa, deixa eu lembrar direito." (5)
6. "Hm, quero responder isso bem." (5)
7. "Calma, cabeça trabalhando aqui." (4)
8. "Hm, deixa eu organizar a cabeça." (6)

Conferência que eu fiz frase por frase: nenhuma tem "achei/encontrei/pronto/já/segundo/abrindo/
consultando/garanto/prometo/rapidinho"; nenhuma tem "é isso" (o "isso" das minhas vem depois de
verbo: "falar isso", "responder isso"); nenhuma palavra começa com um/uma/dois/duas/tres/quatro/
cinco/seis/sete/oito/nove/dez/cem/mil/meio; "essa é das boas" normaliza para "essa e das boas", sem
"e isso". Se o linter achar alguma, eu troco sem chorar (muito).

### `demorados` e `sinais_demora`
- `demorados`: fica `[jogo, noticia, musica, pc]`. Música demora? Só quando pede coisa que ela não
  tem na cabeça, mas deixo, porque "toca X" é comando local e nem chega aqui.
- `sinais_demora`: tiro `hoje`, `agora`, `atual` como sinais **sozinhos** (só contam junto de outro
  sinal ou de tópico demorado). Ponho `clima`, `previsao`, `review`, `trailer`, `compara`.
- Trava nova: texto que fala do próprio Pedro ("eu tô", "tô cansado", "me sinto", "meu dia")
  **nunca** tem frase local, mesmo com sinal.

### A regra dos lotes
1. **Várias partes explícitas** = 2 ou mais pedidos que pediriam respostas diferentes, ligados por
   "e" entre perguntas, "e também", "além disso", "depois", mais de uma "?" ou lista falada. **Não**
   vira lote: pedido longo com contexto e uma pergunta só; "e" dentro da mesma coisa ("arroz e
   feijão", "Elden Ring e o DLC, vale?"); comparação ("X ou Y?") é uma parte só. E se **todas** as
   partes ela responde sem ferramenta, responde tudo de uma vez: lote só quando alguma parte
   demora.
2. **Ordem:** o que está pronto primeiro, sempre com rótulo da parte ("O tempo: …"). Ponte: no
   máximo **uma por turno**, colada no fim do 1º lote, ≤ 4 palavras, sem prazo nem resultado:
   "E o resto, peraí." Nada de "já já", nada de "tô buscando".
3. **Fecho:** só completa. Não resume, não repete. Para antes do teto quando todas as partes foram
   respondidas. Parte que falhou: ela diz, curto e honesto ("Do jogo eu não consegui ver."), e não
   inventa. Pedido com 4+ partes: junta em até 3 lotes, 2 frases cada (o teto da D3).
4. **Convivência:** frase local + lote logo depois é tudo bem (a frase é a cabeça dela, o lote é a
   resposta). A frase local **não conta** nas 6 frases do turno, mas o turno **conta** para a folga
   da cota se a local tocou. Se não tocou, não conta.
5. **Linha nova da persona falada** (2 linhas):
   > Pedido com várias partes: fale primeiro a parte pronta, dizendo qual é, depois as outras; não
   > repita nem resuma. Espera só com conteúdo; nunca prometa prazo nem resultado.

## Não abro mão
1. **Nada de frase de espera quando o Pedro está falando dele mesmo.** Amiga não responde desabafo
   com "deixa eu pensar". Isso é frieza, e gente fria é meu inimigo natural junto com morto-vivo.
2. **Todo lote diz de qual parte é.** Sem isso, lote confunde em vez de dar vida, e aí é melhor
   nem ter.
