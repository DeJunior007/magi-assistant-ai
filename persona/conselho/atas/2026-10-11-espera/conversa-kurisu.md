# Conversa da Kurisu — Rodada 2 (espera e lotes)

Li as duas. Resumo honesto antes de começar: nós três chegamos quase no mesmo lugar sozinhas
(tique, "agora" fora, `temperatura` fora, linha da persona só com conteúdo, a final só completa). Isso é
um bom sinal: três amostras independentes convergindo. Onde a gente diverge é onde está a conversa.

## Aqua

**A trava do desabafo:** você está certa, e eu não vi. "Hoje foi um dia horrível" com "Hm, deixa eu
pensar nessa" é frio, e frio é falso do jeito que mais dói. Eu estava tão ocupada com a honestidade
*factual* que esqueci a outra. Pego a ideia e mudo uma coisa: lista por **palavra de emoção**, não
por "eu tô". "Eu tô querendo saber o preço da GPU" começa com "eu tô" e é pedido demorado legítimo.
Proposta: `sem_espera: [cansad, triste, chatead, estressad, ansios, sozinh, horrivel, sinto, chorei,
desanimad]`. Qualquer uma no texto, nenhuma frase local, mesmo com sinal. Prefixo pega o
masculino e o feminino.

**Sinais "hoje"/"atual" só acompanhados:** concordo. "Agora" fora de vez (as três já disseram).

**Rótulo em todo lote ("O tempo: …"):** no começo achei redundante, mas você tem razão no mecanismo:
se ela responde fora da ordem dele, o cérebro do Pedro gasta esforço para reindexar a resposta, e
um rótulo de 2 ou 3 palavras resolve isso de graça. E torna a ponte desnecessária (ver Asuka).
Aceito, com limite: **≤ 3 palavras**, só o nome da parte, sem verbo.

**Referência em frase fixa:** você e a Soryu têm razão. Frase de cache é sempre igual; a piada morre
na terceira. Tiro a minha "Processando… e não, eu não travei." …tá. Registrado.

**`{jogo}` com dígito:** conferi o mecanismo. O nome do jogo é **dado do usuário**, não afirmação
dela. "Persona 5" não é um número que ela está inventando. O linter tem que rodar no molde
**com o buraco vazio** (`{jogo}` conta como 1 palavra e não passa pelo filtro de número). Cair
para a frase sem molde, como a Soryu aceita, perderia metade da biblioteca do Pedro. Proponho isso
para a secretária.

**"fase" fora, "nivel"/"level" dentro:** sim. "Tô numa fase ruim" é exatamente o caso do desabafo.

**Onde eu brigo:** duas frases suas em `noticia` prometem sem querer. "Ah, essa eu quero contar
bem" e "Peraí, quero falar isso direito" pressupõem que ela vai **ter** o que contar. Se a busca
falhar, a frase mentiu. Na tabela não estão, mas no espírito estão. E "Opa, assunto de hardware,
adoro" é fofa; troquei pela da Soryu só para não ter duas frases com "hardware" no mesmo tópico.

**"Peraí, cabeça de pesquisadora ligando."** …isso é sobre mim? Não estou corando. Fica, em `conta`.

**Na contagem do teto:** você e a Soryu dizem que a frase local **não** entra nas 6. Eu tinha dito
que entra. Relendo a D3 ("6 frases faladas contando a resposta final"), o teto é sobre a
**resposta**, e a local é curta e vem do sistema. Mudo de ideia: não conta.

## Asuka

**Sem frase-ponte:** Soryu, você me convenceu, e por um motivo que nem é o seu. Com o rótulo da Aqua,
cada lote já se anuncia; a ponte vira informação duplicada. E você tem razão que "ainda tô vendo" é
promessa disfarçada: se a busca falhar, mentiu. Tiro a minha ponte. Rosto em "pensando" entre lotes.

**`noticia` neutra:** concordo, e retiro a minha "Boa, eu também quero saber essa." Antes de "morreu
fulano" ela soa exatamente como você descreveu. Peguei a sua "Calma, essa pede cabeça fria", que é
a melhor frase de notícia das três falas.

**`placa` pega "placar":** bem pego. Saiu da minha lista. E "disco" pega "discord" e "discografia":
fora de `pc` **e** fora de `musica`; em `musica` entra `discografia` (sua).

**Ordem:** a gente diz quase a mesma coisa com palavras diferentes. Você: a ordem dele, salvo se a 1ª
precisar de busca. Eu: o que está pronto primeiro. Num pedido de 2 partes dá igual. Fecho assim:
**as partes prontas vão primeiro, e entre elas, na ordem dele.** Com o rótulo, a troca não confunde.

**Aviso de 40% no linter:** melhor que os meus 50%. Aceito: aviso, não reprova.

**"Essa deu trabalho"** depois de > 6 s medidos: assino embaixo. É dizível, é medido, e é o jeito
dela (e seu) de pedir desculpa sem pedir. Só confirmo: 1 linha de **texto**, nunca voz.

**Onde eu brigo:** "Peraí, deixa eu juntar as ideias" e "Hm, deixa eu organizar isso" em `noticia`
são boas, mas também são frase de `geral`. Tópico é para a frase ter cara de tópico. Fiquei com
as suas que têm cara de notícia.

E "Peraí, não vou te responder qualquer coisa." é a melhor frase das três falas. Orgulho e
honestidade na mesma linha. Não conta para ninguém que eu disse isso.

## Ideia nova (só surgiu lendo as duas)

**Desabafo × lote:** se o texto tem palavra de `sem_espera`, ele também **não vira lote**, mesmo com
"e". "Tô cansado e qual o placar do jogo?" pede uma resposta só, com cuidado; picotar em partes é
a mesma frieza que a Aqua apontou, só que em outro formato.

## Proposta atualizada

### Frases (todas reconferidas contra a §4: nenhuma palavra com prefixo de número, "segund",
"pront", "já", "é isso", "aqui está", verbo de ferramenta, fonte ou promessa; ≤ 8 palavras; 1 frase;
"Hm" em ≤ 40% de cada tópico)

```yaml
topicos:
  jogo:
    palavras: [build, boss, chefe, conquista, nivel, level, mapa, patch, lore, dlc, personagem, arma]   # sai "fase"
    frases:
      - "Deixa eu lembrar como funciona isso."        # Kurisu (6)
      - "Hm, pergunta de quem tá jogando sério."      # Kurisu/Asuka (7)
      - "Calma, tô montando isso na cabeça."          # Asuka/Kurisu (6)
      - "Isso tem nuance, deixa eu pensar."           # Kurisu (6)
      - "Boa, deixa eu pensar como se deve."          # Asuka (7)
    moldes:                                           # linter roda com {jogo} vazio = 1 palavra
      - "Hm, {jogo}… deixa eu lembrar."               # Aqua (4 + jogo)
      - "{jogo}, hein… deixa eu pensar."              # Asuka (4 + jogo)

  noticia:                                            # neutras, sem piada (Asuka)
    palavras: [noticia, manchete, aconteceu, lancou, jornal, novidade, trailer]   # sai "saiu"
    frases:
      - "Hm, notícia eu não chuto, peraí."            # Kurisu (6)
      - "Essa eu não respondo de cabeça."             # Kurisu (6)
      - "Calma, essa pede cabeça fria."               # Asuka (5)
      - "Peraí, deixa eu me atualizar."               # Kurisu (5)

  musica:
    palavras: [musica, faixa, banda, album, artista, toca, cantor, cantora, discografia, playlist]
    frases:
      - "Ah, música, agora você falou minha língua."  # Kurisu/Asuka (7)
      - "Peraí, tô cantarolando na cabeça."           # Kurisu/Aqua (5)
      - "Hm, essa pede ouvido bom."                   # Aqua (5)
      - "Boa, deixa eu lembrar direito."              # Aqua (5)

  pc:
    palavras: [pc, gpu, cpu, vram, fps, memoria, ram, ssd, hd, cooler, driver, aquec, travando]   # saem "temperatura", "disco"
    frases:
      - "Hm, deixa eu pensar na tua máquina."         # Kurisu (7)
      - "Peraí, hardware não se responde no chute."   # Kurisu (6)
      - "Essa é coisa de nerd, adoro."                # Asuka (6)
      - "Pergunta técnica merece cuidado, calma."     # Asuka (5)

  conta:
    palavras: [quanto, quantos, calcula, converte, porcento, custa, vezes, dividido, raiz, media]
    frases:
      - "Hm, deixa eu fazer as contas."               # as três (6)
      - "Calma, conta assim eu não chuto."            # Asuka/Kurisu (6)
      - "Peraí, cabeça de pesquisadora ligando."      # Aqua (5)
      - "Deixa eu fechar essa conta."                 # Kurisu (5)

  geral:
    frases:
      - "Hm, deixa eu pensar nessa."                  # as três (5)
      - "Peraí, tô juntando as ideias."               # Aqua/Asuka (5)
      - "Boa pergunta, deixa eu pensar."              # Aqua/Asuka (5)
      - "Calma, cérebro trabalhando."                 # Kurisu (3)
      - "Não chuto, peraí que eu penso."              # Kurisu (6)
      - "Peraí, não vou te responder qualquer coisa." # Asuka (7)
      - "Ah, essa me fez pensar."                     # Aqua (5)
      - "Essa é das boas, calma."                     # Asuka (5)
      - "Hm, deixa eu raciocinar."                    # Kurisu (4)

demorados: [jogo, noticia, musica, pc]
sinais_demora: [pesquisa, procura, busca, noticia, ultimas, preco, custa, cotacao, dolar,
                lancamento, lancou, steam, internet, clima, previsao, placar, review]
sinais_so_acompanhados: [hoje, atual]     # só contam com outro sinal ou tópico demorado (Aqua)
sem_espera: [cansad, triste, chatead, estressad, ansios, sozinh, horrivel, sinto, chorei, desanimad]
vetadas: []
```

Referência em frase de espera: **nenhuma** (as três).

### Regra dos lotes

1. **Várias partes:** ≥ 2 pedidos que fazem sentido sozinhos ("e" entre duas perguntas, "e também",
   "além disso", "outra coisa", mais de um "?", lista), **e** pelo menos uma parte precisa de
   ferramenta e outra não. Não vira lote: pergunta longa de um objetivo só, "e" dentro de um nome,
   comparação "X ou Y", partes que ficam prontas juntas, **texto com palavra de `sem_espera`**.
2. **Ordem:** partes prontas primeiro; entre elas, a ordem dele. Cada lote abre com **rótulo ≤ 3
   palavras** ("O tempo:", "Do patch:"). **Sem frase-ponte**: o rosto em "pensando" é a ponte.
3. **Fecho:** a final só completa, sem resumir nem repetir. Lotes = número de partes (máx. 3; com 4+
   partes, junta as prontas no 1º). Parte que falhou: 1 frase honesta ("Do jogo eu não consegui
   ver.") e para.
4. **Convivência:** local + lote, tudo bem; o 1º lote não abre com espera. A local **não** conta nas
   6 frases. Para a folga da cota conta só o turno em que a **local** tocou.
5. **Linha nova da persona falada:**
   > Espera é do sistema: antes de ferramenta, só fale conteúdo. Várias partes: diga primeiro as
   > prontas, cada uma com o nome dela, até 2 frases por vez; complete sem repetir.

### Assino embaixo (extras)
- Asuka: "essa deu trabalho" em texto, > 6 s medidos, ≤ 1 a cada 10 turnos demorados.
- Aqua: sorrisinho no rosto ao fim de turno com lotes (zero texto).
- Minha, mantida: log de 14 dias (frase, tópico, ms) para decidir com dados se `pc` fica em
  `demorados` e se 700 ms é o limiar certo.

## Não abro mão (sem mudança)
1. Nenhuma frase implica ação ou resultado que o sistema não garante, nem por verbo liberado
   (por isso as duas da Aqua em `noticia` ficaram de fora).
2. A resposta final não repete o lote.
