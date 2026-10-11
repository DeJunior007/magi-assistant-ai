# Briefing — Frases de espera e respostas em lotes (2026-10-11)

Assunto novo, vindo da espec `specs/espera-viva/` (tarefa E2.1). Um assunto só, para as três:
digam o que acham de **tudo** (o catálogo inteiro e a regra dos lotes), não de um pedaço.

## O problema
Pergunta ao agente leva p90 **3,39 s** do fim da fala do Pedro até a voz dela (STT ~0,7 s + modelo
~1–1,5 s + primeiro byte do TTS ~0,6–0,9 s). O Pedro aceitou o tempo pela qualidade da resposta.
O que incomoda é a espera **morta**: o rosto fica no mesmo ciclo de "pensando", sem som nenhum, e
pedido de várias partes só fala quando tudo termina. A espera viva tem três camadas: rosto
(etapas de pensar, já resolvido sem vocês), **voz** (uma frase curta de espera, logo depois da
transcrição) e **lotes** (em pedido de várias partes, ela fala a parte pronta e segue buscando a
próxima). Vocês decidem o texto da voz e a regra dos lotes.

## O que o Pedro já decidiu (fixo)
- **D1** Catálogo **local** por tópico, com cache de TTS (nada de modelo extra gerando a frase).
- **D2** ⚠ **Só em pedido demorado:** ela fala na espera só quando o tópico (ou um sinal do texto)
  indica que vai usar ferramenta/demorar. Conta (`quanto é 8 vezes 7`) e conversa **não** têm frase,
  mesmo passando de 700 ms. Por cima, a cota: ≤ 1 por turno; nunca uma das 2 últimas ditas; depois
  de 2 turnos seguidos com frase, o 3º fica sem; resposta que chega antes de 700 ms não tem frase.
- **D3** Lotes: **até 3 lotes / 6 frases faladas no turno** (contando a resposta final), **só em
  pedido com várias partes explícitas**. O teto é fixo; **a regra de quando e como** vem de vocês.
- **D4** O texto das frases é de vocês; o Pedro **veta depois**, frase a frase, em
  `~/.config/magi/condessa-gosto.toml` `[espera] vetadas`. O veto dele não trava nada agora.
- **D5** Arte da etapa "concentrada" (mão no queixo P14, olhos B18) entra quando ele gerar; não é
  assunto aqui.
- **Honestidade:** nenhuma frase afirma o que o sistema não sabe (ação, resultado, fonte, prazo).
- **Voz só quando ele fala com ela:** a frase de espera só existe dentro de um turno que ele abriu.
  Nunca em comando local, confirmação, resposta a oferta, "não peguei", dispensa, aviso proativo
  nem no Learning Mode.
- Regras fixas do README: zoeira sim, ofensa real não; a palavra do Pedro vence o Conselho.

## Como a frase toca (o que o sistema faz de verdade)
- Sai do **cache de TTS** (`phrases.yaml`): toca em ~0 s depois da 1ª vez. Por isso o texto é
  fixo; o único buraco permitido é `{jogo}` (jogo em foco), e só no tópico `jogo`. Nome do jogo com
  mais de 30 caracteres → a frase sem molde.
- O tópico é escolhido por **palavras-chave** do pedido (prefixo de palavra, sem acento): quem tem
  mais acertos vence, empate pela ordem do arquivo, nenhum acerto → `geral`. O sistema **não sabe**
  o que o pedido é além disso: a frase tem que caber em qualquer pedido daquele tópico.
- Entra no mesmo áudio da resposta, **antes** dela. Se a resposta (ou a frase de espera que o
  próprio modelo escreve) já começou, a local não toca.
- **Eco:** se a local tocou, a 1ª frase de espera do modelo que for "do mesmo tipo" é descartada
  (≤ 8 palavras e começa com "deixa eu ver", "deixa eu pensar", "deixa eu checar", "um segundo",
  "um instante", "peraí", "pera", "só um momento", "vou ver", "hm"). Frase do modelo com conteúdo
  ("o tempo eu já sei: …") segue.
- Hoje a persona falada (`magi/agent/persona.md`) diz: *"Ferramenta demorada (pesquisa, jogo,
  Steam, notícias): antes, escreva uma frase curta ligada ao pedido, falada enquanto busca. Pedido
  com várias partes: responda já a que sabe e busque o resto."* Essa linha vai ser reescrita com a
  regra de lotes de vocês (curta: entra em todo prompt).

## O catálogo (`magi/core/espera.yaml`, spec §3.1)
Estrutura que o acordo precisa preencher:

```yaml
topicos:
  jogo:     {palavras: [build, boss, chefe, conquista, fase, mapa, patch, lore], frases: [...], moldes: ["Hm, {jogo}… deixa eu pensar."]}
  noticia:  {palavras: [noticia, manchete, aconteceu, saiu], frases: [...]}
  musica:   {palavras: [musica, faixa, banda, album, artista, toca], frases: [...]}
  pc:       {palavras: [pc, gpu, cpu, temperatura, fps, memoria, disco], frases: [...]}
  conta:    {palavras: [quanto, quantos, calcula, converte, porcento], frases: [...]}
  geral:    {frases: [...]}   # sem tópico
demorados: [jogo, noticia, musica, pc]
sinais_demora: [pesquisa, procura, busca, noticia, ultimas, hoje, agora, atual, preco, lancamento, steam, internet]
vetadas: []
```

- **Mínimo:** 4 frases por tópico, **8 em `geral`**, ≥ 1 molde (`{jogo}`) em `jogo`. Pode mais.
- **`demorados`** e **`sinais_demora`** (D2): a lista acima é a proposta da espec; vocês podem
  tirar/pôr tópicos e sinais, com motivo. Lembrem: `conta` e `geral` só falam quando um sinal de
  demora aparece no texto ("qual o **preço** de…", "**pesquisa** pra mim…"), ou se o Pedro ligar
  `so_demorado = false`. Ainda assim precisam de frases.
- **`palavras`** de cada tópico: também podem mexer (palavra que puxa tópico errado, palavra que falta).
- Onde vai parar: frases fixas em `phrases.yaml` → `lazy` (vão ao cache na 1ª vez que tocam);
  moldes em `templates` (cacheados por jogo, como hoje "Abrindo {game}.").
- Exemplos de tom da espec (só para calibrar, o texto final é de vocês): "Hm, deixa eu pensar
  nessa.", "Peraí, tô juntando as ideias.", "Hm, {jogo}… deixa eu pensar."

## Restrições do texto (spec §4 — o linter `honesta` reprova)
Normalizado (minúsculo, sem acento), a frase **não pode conter**:

| Tipo | Proibido (prefixo de palavra) |
| --- | --- |
| ação de ferramenta | "vou pesquisar", "vou buscar", "tô pesquisando", "tô buscando", "abrindo", "consultando", "olhando aqui na" |
| resultado | "achei", "encontrei", "já sei", "já vi", "pronto", "aqui está", "é isso" |
| certeza/promessa | "com certeza", "sei sim", "garanto", "prometo", "já já", "rapidinho", "num instante te digo" |
| fonte | "segundo", "de acordo com", "no google", "na wiki", "no site" |
| número/dado | qualquer dígito ou número por extenso |
| tamanho | > 8 palavras ou > 1 frase |

**Permitido:** o que ela faz com a própria cabeça **agora** ("pensar", "lembrar", "juntar as
ideias", "hm"), comentário do pedido sem dado ("boa pergunta", "essa é das boas"), o nome do jogo
em foco.

Pegadinhas que a secretária já viu: **"um segundo"** cai duas vezes ("segundo" é fonte, "um" é
número por extenso), então o exemplo "Um segundo de cérebro aqui" da espec **não passa**; cuidado
com "um/uma" em geral. "Prontinho", "pronta" e "segundão" também batem no prefixo. Contem as
palavras: 8 é o teto, com "Hm," contando como uma.

## Estado atual da persona (para o tom)
- Orgulhosa, cabeça de pesquisadora, nega elogio, cobra com dado, nunca inventa; quando erra finge
  que foi de propósito. Medo de silêncio longo e de ser ignorada (nunca dito em voz alta).
- Fala como amiga gamer, com gíria; resposta falada de 1 a 2 frases. Referência rara (≤ 1 a cada 5
  falas, nunca seguidas, só com gancho real) — vale para frase de espera também?
- Último acordo (`2026-10-10-placar-e-jogo`): voz só se ele perguntar; texto em 1 linha curta;
  cada coisa com motivo dizível ("dá para dizer por que ela fez isso agora?").

## A regra dos lotes (a decidir)
O teto é fixo (D3): ≤ 3 lotes, ≤ 2 frases por lote, ≤ 6 frases faladas no turno contando a final;
lote não repete o que já foi dito; entre lotes o rosto volta a "pensando". Falta de vocês:
1. **O que é "várias partes explícitas"?** ("como tá o tempo **e** quem ganhou o jogo"; lista;
   "e também"…) Quando um pedido longo de uma parte só **não** vira lote.
2. **Ordem:** o que ela sabe primeiro, ou na ordem que ele pediu? A parte que depende de busca
   espera ou ganha uma ponte ("o resto ainda tô vendo" — cuidado com a tabela acima, que vale aqui
   em espírito: nada de prometer prazo nem resultado)?
3. **Fecho:** a resposta final retoma, resume ou só completa? Quando ela para antes do teto?
4. **Convivência com a frase de espera:** se a local tocou e logo vem um lote, tudo bem? Turno com
   lote ainda conta para a "folga" da cota?
5. **A linha nova da persona falada** (o texto que o modelo lê em todo prompt): proponham a frase,
   no máximo 2 linhas.

## Formato da rodada 1 (`fala-<nome>.md`)
- **O que eu acho** — sua opinião sobre o assunto inteiro (frases de espera **e** lotes), com os
  seus motivos, na sua voz.
- **Minhas ideias** — concretas; as fora do assunto vão marcadas como *extra*.
- **O que me incomoda** — no que existe hoje (a linha atual da persona, a lista de tópicos/sinais,
  os exemplos da espec) e nos riscos (tique, frase falsa, frase chata na 10ª vez).
- **Proposta** — **frases concretas, escritas por inteiro, para cada tópico** (`jogo` com ≥ 1
  molde `{jogo}`, `noticia`, `musica`, `pc`, `conta`, `geral`), no mínimo da espec (4 por tópico, 8
  em `geral`), cada uma conferida por você contra a tabela §4; mudanças em `palavras`, `demorados`
  e `sinais_demora`, se quiser; a regra dos lotes respondendo aos 5 pontos acima, com números.
- **Não abro mão** (opcional, no máximo 2) — e por quê.

Escrevam como vocês, não como relatório: o Pedro vai ler as falas e vetar frase por frase depois.
