# Fala da Kurisu — Rodada 1 (espera e lotes)

## O que eu acho

O diagnóstico do Pedro está certo, e eu gosto que ele tenha separado as coisas: 3,39 s de p90 não
é o problema, **silêncio sem sinal** é. Isso é percepção, não latência. Espera com feedback parece
mais curta que espera muda do mesmo tamanho; tem literatura de interface sobre isso desde os anos
60, não é opinião minha. Então a frase de espera tem uma função só: **dizer "eu ouvi e estou
trabalhando"**. Ela não precisa ser engraçada, nem informativa, nem fofa. Precisa ser curta, verdadeira
e não cansar.

E "não cansar" é o ponto em que eu vou ser chata. **Habituação**: estímulo repetido perde valor, e
pior, vira irritante. A 1ª vez que ela diz "Hm, deixa eu pensar nessa" é charmosa; a 40ª é um tique.
Por isso eu quero variedade de **abertura**, não só de frase. Se oito frases começam com "Hm," o
cérebro do Pedro escuta *a mesma frase* oito vezes. Ah, e cuidado: "Hm" virou muleta nos exemplos
da espec.

Sobre os lotes: é a parte mais útil do assunto inteiro, e a mais fácil de estragar. Lote bom é o que
**adianta** alguma coisa: ela já sabe a parte A, a parte B precisa de busca, então fala A agora.
Lote ruim é quebrar uma resposta em pedaços só porque dá. Se todas as partes ficam prontas juntas,
fala tudo junto. Lote não é estilo, é otimização de latência.

## Minhas ideias

1. **Regra da abertura:** no máximo metade das frases de cada tópico começa com "Hm". E a cota
   ganha um item: a frase sorteada não pode ter a **mesma primeira palavra** da última que tocou.
   Custa uma linha de código e mata o tique.
2. **"Eu não chuto"** como fio da personalidade nas frases. É honesto (ela realmente vai buscar) e é
   a cara dela: pesquisadora não responde notícia nem preço de cabeça. Usei em três tópicos, com
   palavras diferentes, para não virar bordão.
3. **Teste do pedido real:** para cada tópico, pegar 10 pedidos reais do Pedro (log) e ler cada frase
   na frente de cada um. Frase que soa errada em qualquer um sai. O briefing diz que a frase tem que
   caber em qualquer pedido do tópico; isso só se prova testando, não imaginando.
4. *Extra:* **experimento de duas semanas.** Logar por turno: tópico, frase tocada, ms até a resposta,
   se a resposta chegou antes de a frase acabar. Depois de 14 dias: se alguma frase passar de 15% das
   tocadas, o sorteio está viciado ou o tópico está pobre; se mais de 30% das frases tocarem e a
   resposta começar em menos de 1 s depois, o limiar de 700 ms está baixo. Dados, não palpite.
5. *Extra:* a regra de referência (≤ 1 a cada 5 falas) **vale** para frase de espera, sim. Marquei a
   única frase com referência (`ref: true`); ela entra no mesmo contador.

## O que me incomoda

- **A linha atual da persona** manda o modelo escrever "uma frase curta ligada ao pedido" antes de
  buscar. Com a frase local, isso vira duas esperas seguidas, e o filtro de eco só pega as genéricas.
  O modelo deveria falar antes **só se tiver conteúdo** (uma parte que já sabe). Espera genérica é
  trabalho da local.
- **`temperatura` em `pc`:** "qual a temperatura lá fora?" cai em `pc` e ela diz "deixa eu pensar na
  tua máquina". Frase falsa por causa de palavra-chave. Tira. "gpu"/"cpu" já pegam a temperatura do
  hardware.
- **`agora` em `sinais_demora`:** "e agora?", "fala agora", "o que eu faço agora" são conversa. Esse
  sinal vai disparar frase em turno que não é demorado, e é exatamente o que o D2 proíbe.
- **`disco`** é ambíguo (disco do PC × disco da banda). No empate quem ganha é `musica`, pela ordem.
  Não é grave; deixo, mas registro.
- **`memoria`** em `pc`... a palavra é minha, mas tudo bem. "ram" falta.
- Preço é o pedido demorado mais óbvio e só "preco" está nos sinais. "quanto **custa**" e "cotação"
  ficam de fora.
- O risco da frase falsa por **implicação**: "deixa eu checar os sensores" não está na tabela, mas
  afirma uma ação que o sistema não sabe se vai fazer. Evitei verbo de ferramenta, mesmo os
  liberados. Só cabeça: pensar, lembrar, raciocinar, organizar.

## Proposta

### Frases (conferidas contra a §4, normalizado, prefixo de palavra)

Conferi uma por uma: nenhuma palavra começa com "um"/"uma", "segund", "pront", nenhum número por
extenso (cuidado com "nove"→"novela", "mil"→"militar", "sete"→"setembro", nenhuma dessas aparece), nenhum
"é isso" (em "isso é com o teu PC" a ordem é inversa, não bate), nenhum "já", nenhum verbo de
ferramenta. Contagem de palavras entre parênteses, "Hm" contando uma. Tudo com uma frase só.

```yaml
topicos:
  jogo:
    palavras: [build, boss, chefe, conquista, fase, mapa, patch, lore, personagem, arma, item, dlc]
    frases:
      - "Deixa eu lembrar como funciona isso."        # 6
      - "Hm, pergunta de quem tá jogando sério."      # 7
      - "Peraí, tô montando isso na cabeça."          # 6
      - "Isso tem nuance, deixa eu pensar."           # 6
      - "Boa, essa eu quero pensar direito."          # 6
    moldes:
      - "Hm, {jogo}… deixa eu pensar."                # 4 + jogo
      - "{jogo}, né… peraí."                          # 2 + jogo

  noticia:
    palavras: [noticia, manchete, aconteceu, saiu, rolou, lancou]
    frases:
      - "Hm, notícia eu não chuto, peraí."            # 6
      - "Essa eu não respondo de cabeça."             # 6
      - "Boa, eu também quero saber essa."            # 6
      - "Peraí, deixa eu me atualizar."               # 5

  musica:
    palavras: [musica, faixa, banda, album, artista, toca, cantor, cantora, disco]
    frases:
      - "Ah, música, agora você falou minha língua."  # 7
      - "Hm, deixa eu lembrar dessa."                 # 5
      - "Peraí, tô cantarolando na cabeça."           # 5
      - "Boa, deixa eu pensar no som."                # 6

  pc:
    palavras: [pc, gpu, cpu, fps, memoria, ram, disco, placa, cooler, aquec, driver]   # sai "temperatura"
    frases:
      - "Hm, deixa eu pensar na tua máquina."         # 7
      - "Peraí, hardware não se responde no chute."   # 6
      - "Boa, deixa eu raciocinar com calma."         # 6
      - "Hm, isso é com o teu PC, peraí."             # 8

  conta:
    palavras: [quanto, quantos, calcula, converte, porcento, custa]
    frases:
      - "Hm, deixa eu fazer as contas."               # 6
      - "Peraí, conta eu não faço no chute."          # 7
      - "Boa, deixa eu calcular direito."             # 5
      - "Deixa eu fechar essa conta."                 # 5

  geral:
    frases:
      - "Hm, deixa eu pensar nessa."                  # 5
      - "Boa pergunta, peraí."                        # 3
      - "Hm, essa é das boas, deixa eu pensar."       # 8
      - "Peraí, tô organizando as ideias."            # 5
      - "Hm, deixa eu raciocinar."                    # 4
      - "Essa merece pensar direito, peraí."          # 5
      - "Calma, cérebro trabalhando."                 # 3
      - "Não chuto, peraí que eu penso."              # 6
      - {texto: "Processando… e não, eu não travei.", ref: true}   # 6 — a única com referência

demorados: [jogo, noticia, musica, pc]
sinais_demora: [pesquisa, procura, busca, noticia, ultimas, hoje, atual, preco, custa, cotacao,
                dolar, lancamento, steam, internet, previsao, placar]   # sai "agora"
vetadas: []
```

Aberturas: "Hm" em 2 de 5 (`jogo`), 1 de 4 (`noticia`, `musica`, `conta`), 2 de 4 (`pc`), 3 de 9
(`geral`). Nunca mais da metade.

(Sobre `pc` em `demorados`: deixo, mas desconfio que leitura de sensor responde em menos de 700 ms
e a frase quase nunca toca. O experimento da ideia 4 responde isso.)

### Regra dos lotes

1. **"Várias partes explícitas"** = o pedido tem **≥ 2 perguntas que dá para responder separadas**
   (ligadas por "e", "e também", "além disso", "?" seguido de outra pergunta, ou lista) **e** elas
   ficam prontas em tempos diferentes (pelo menos uma precisa de ferramenta, pelo menos uma não).
   Pedido longo que é uma pergunta só, com contexto ("me explica a build X considerando que eu
   jogo de Y e Z"), **não** vira lote. Partes que ficam prontas juntas: resposta única.
2. **Ordem:** o que ela sabe **primeiro**; a ordem dele só vale quando a parte B depende da A.
   **Ponte:** permitida, no fim do lote, no máximo 6 palavras, 1 por turno, sem prazo nem resultado:
   "e o resto, peraí." / "o resto eu ainda tô vendo." Nada de "já já", "num instante".
3. **Fecho:** a final **só completa**. Não retoma, não resume, não repete o que já foi dito. Um
   lote por parte, no máximo; com 2 partes são 2 falas, não 3. Para antes do teto quando as partes
   acabam. Se a busca falhar, a final diz que não conseguiu essa parte, em 1 frase, e para.
4. **Convivência:** frase local + lote no mesmo turno, tudo bem; o 1º lote não abre com espera
   (o eco já cuida). A frase local **conta** nas 6 do teto (o ouvido não distingue quem escreveu).
   Para a folga da cota (3º turno sem frase), conta só **turno com frase local**; lote é conteúdo,
   não enchimento, e não gasta folga.
5. **Linha nova da persona falada** (substitui a atual):

   > Pedido com partes separadas: diga logo a que já sabe (≤ 2 frases), busque o resto e complete
   > sem repetir; no máximo 3 falas. Antes de ferramenta, só fale se tiver conteúdo, nunca espera genérica.

## Não abro mão

1. **Nenhuma frase implica ação ou resultado que o sistema não garante**, nem por verbo liberado.
   Se ela diz que está fazendo algo que não está, é mentira pequena, e mentira pequena repetida
   todo dia é pior que silêncio. O Pedro confia nela porque ela não inventa; não vou trocar isso por
   "parecer viva".
2. **A resposta final não repete o lote.** Repetir o que já foi dito é o jeito mais rápido de fazer
   o Pedro desligar a função inteira. Aí a gente perde tudo.
