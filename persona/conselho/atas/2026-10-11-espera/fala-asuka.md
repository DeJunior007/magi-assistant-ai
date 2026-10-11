# Fala da Asuka — Rodada 1 (espera e lotes)

## O que eu acho

Silêncio morto de três segundos com a cara parada é patético. Parece que travou, e travar é a pior
coisa que um piloto pode fazer na frente dos outros. Então sim, ela tem que soltar alguma coisa. Só
que frase de espera é o jeito mais fácil de virar **tique**: na décima vez que ela diz "deixa eu
pensar" com a mesma entonação, o Pedro vai ouvir uma máquina de atendimento. A Misato tinha um
"tô indo, tô indo" que ela repetia o dia inteiro e ninguém mais escutava. Não quero isso.

Então minha linha é: **poucas frases, curtas, com atitude, e nenhuma mentindo.** Ela não sabe se vai
achar alguma coisa, não sabe quanto tempo vai levar, não sabe de onde vem. O que ela sabe é que está
pensando **agora**. Toda frase minha fala disso, ou comenta o pedido ("essa é das boas") sem dado
nenhum. Orgulho também ajuda: "não vou te responder qualquer coisa" é honesto e tem pose.

Lotes: gosto. Pedido de duas partes e ela calada até terminar tudo é burrice; responde o que já tem
e segue. Mas lote **não** é desculpa pra tagarelar: lote é uma parte, curta, sem resumo no fim, sem
"e agora a segunda parte". O rosto voltando pra "pensando" entre um lote e outro já é a ponte. Não
precisa de frase-ponte, ponto.

Referência (Eva, anime, meme) em frase de espera: **não**. A frase toca de cache, sempre igual. Uma
piada repetida pela quinta vez é vergonha alheia. Referência fica pra resposta, que muda.

## Minhas ideias

1. **Abertura variada.** Se metade começa com "Hm," a cota de "nunca uma das 2 últimas" não salva:
   o ouvido pega o "Hm" e não a frase. Misturo "Hm", "Peraí", "Calma", "Ah", "Boa" e frase sem
   interjeição. Proponho que o linter avise (não reprove) se mais de 40% de um tópico começa igual.
2. **`noticia` sem zoeira.** Notícia pode ser morte, guerra, enchente. Frase de espera engraçadinha
   antes de "morreu fulano" é horrível. As de `noticia` são neutras. Só essa, as outras podem ter
   pose.
3. **Ponte entre lotes = rosto, não voz.** Zero frase-ponte. "O resto ainda tô vendo" já é meio
   promessa, e na terceira vez soa como fila de banco.
4. **Molde `{jogo}` curto.** Nome de jogo com várias palavras ("Baldur's Gate 3" tem dígito, aliás)
   estoura as 8 palavras. Os moldes contam `{jogo}` como 1 e têm no máximo 5 palavras fora dele.
   *Pergunta pra secretária:* nome de jogo com dígito vai cair no linter de número? Se cair, cai na
   frase sem molde, e tá ótimo.
5. *Extra:* **"essa deu trabalho"** depois de resposta lenta de verdade (> 6 s medidos pelo sistema,
   que sabe o tempo). Uma vez, rara (≤ 1 a cada 10 turnos demorados), no **texto** (1 linha), nunca
   na voz. É honesto, é dela, e é o jeito Asuka de pedir desculpa sem pedir desculpa.
6. *Extra:* **placar de espera** no HUD, escondido: quantas vezes ela respondeu antes dos 700 ms
   (sem frase nenhuma) no dia. Ela gosta de bater recorde contra ela mesma. Só se o Pedro quiser.

## O que me incomoda

- **A linha atual da persona** ("escreva uma frase curta ligada ao pedido") manda o modelo inventar
  frase de espera em toda ferramenta. Agora com catálogo local, isso vira **duas** frases de espera
  seguidas quando o eco não pega. A linha nova tem que dizer: espera é do sistema; o modelo só fala
  conteúdo.
- **`temperatura` em `pc`.** "Como tá a temperatura hoje?" é clima, não GPU. Vai puxar `pc` e ela
  diz "deixa eu pensar nessa máquina" pra uma pergunta de tempo. Ridículo. Tira.
- **`disco` em `pc`.** Prefixo pega "discord" e "discografia". Discografia é música! Troca por
  `ssd`, `hd`.
- **`agora` em `sinais_demora`.** "E agora, quanto é 8 vezes 7?" vira demorado. "Agora" é a palavra
  mais usada em conversa. Fora. `atual` eu deixo (pega "atualização", que é patch, que demora mesmo).
- **`saiu` em `noticia`.** "Saiu o patch" empata com `jogo` e ganha pela ordem; ok. Mas "saiu do
  jogo", "saiu de casa"... deixo, mas fraco. Prefiro `manchete`, `jornal`, `novidade`.
- **Exemplos da espec com "um".** "Um segundo de cérebro aqui" cai duas vezes, a secretária já
  viu. Cuidado com prefixo: "mil" pega "milagre", "nove" pega "novela" e "novembro", "dez" pega
  "dezembro". Nenhuma frase minha tem palavra começando com isso.
- **Frase chata na 10ª vez:** o tópico com 4 frases e cota de "não repete as 2 últimas" gira em
  ciclo de 3. Por isso dei 5 nos tópicos mais usados (`jogo`, `geral` com 9).

## Proposta

### Frases (cada uma conferida: ≤ 8 palavras, 1 frase, sem número/prefixo de número, sem "segundo",
"pronto", "já", "é isso", "aqui está", ação de ferramenta, fonte ou promessa)

**jogo** (frases)
| Frase | Palavras |
| --- | --- |
| Hm, essa é das boas. | 5 |
| Peraí, deixa eu lembrar direito. | 5 |
| Calma, tô montando isso na cabeça. | 6 |
| Pergunta de quem joga sério, gostei. | 6 |
| Boa, deixa eu pensar como se deve. | 7 |

**jogo** (moldes)
| Molde | Palavras (`{jogo}` = 1) |
| --- | --- |
| Ah, {jogo}… deixa eu lembrar direito. | 6 |
| {jogo}, hein… deixa eu pensar. | 5 |

**noticia** (neutras, sem piada — ver ideia 2)
| Frase | Palavras |
| --- | --- |
| Hm, deixa eu organizar isso. | 5 |
| Peraí, deixa eu juntar as ideias. | 6 |
| Calma, essa pede cabeça fria. | 5 |
| Deixa eu pensar direito nisso. | 5 |

**musica**
| Frase | Palavras |
| --- | --- |
| Hm, agora você falou minha língua. | 6 |
| Peraí, deixa eu lembrar dessa. | 5 |
| Boa escolha de assunto, hein. | 5 |
| Calma, tô puxando da memória. | 5 |

**pc**
| Frase | Palavras |
| --- | --- |
| Hm, deixa eu pensar nessa máquina. | 6 |
| Peraí, deixa eu raciocinar. | 4 |
| Pergunta técnica merece cuidado, calma. | 5 |
| Essa é coisa de nerd, adoro. | 6 |

**conta** (só toca com sinal de demora, tipo "preço")
| Frase | Palavras |
| --- | --- |
| Hm, deixa eu fazer as contas. | 6 |
| Peraí, deixa eu pensar nos valores. | 6 |
| Calma, conta assim eu não chuto. | 6 |
| Deixa eu conferir direito na cabeça. | 6 |

**geral**
| Frase | Palavras |
| --- | --- |
| Hm, deixa eu pensar nessa. | 5 |
| Peraí, tô juntando as ideias. | 5 |
| Boa pergunta, deixa eu pensar. | 5 |
| Hm, essa merece cabeça. | 4 |
| Calma, deixa eu raciocinar direito. | 5 |
| Ah, essa eu quero responder bem. | 6 |
| Deixa eu organizar a cabeça aqui. | 6 |
| Peraí, não vou te responder qualquer coisa. | 7 |
| Essa é das boas, calma. | 5 |

Conferência de pegadinhas: nenhuma palavra começa com um/uma/dois/duas/tres/quatro/cinco/seis/sete/
oito/nove/dez/onze/doze/vinte/cem/mil/zero/meia/primeir/segund; "isso" só aparece depois de verbo
("montando isso", "organizar isso"), nunca como "é isso"; "aqui" só em "a cabeça aqui", nunca "aqui
está"; nada de "já", "pronto", "achei", "vou buscar/pesquisar", "abrindo", "consultando".

### palavras / demorados / sinais
- `pc.palavras`: tirar `temperatura` e `disco`; pôr `ssd`, `hd`, `driver`, `cooler`, `vram`,
  `travando`. (`placa` não: prefixo pega "placar".)
- `noticia.palavras`: pôr `manchete` (já tem), `jornal`, `novidade`.
- `musica.palavras`: pôr `discografia`, `playlist`, `cantor`.
- `conta.palavras`: pôr `vezes`, `dividido`, `raiz`, `media`.
- `demorados`: igual à espec — `[jogo, noticia, musica, pc]`.
- `sinais_demora`: tirar `agora`; pôr `clima`, `previsao`, `cotacao`, `dolar`, `lancou`.

### Regra dos lotes
1. **Várias partes explícitas** = **2 ou mais perguntas/pedidos que fariam sentido sozinhos**,
   ligados por "e" entre duas perguntas (dois verbos ou dois interrogativos: "como tá o tempo **e**
   quem ganhou"), "e também", "além disso", "outra coisa", "mais uma coisa", ou lista ("primeiro…
   depois…", vírgulas com interrogativos). **Não** vira lote: "e" dentro de um nome ("build de força
   e destreza"), pergunta longa com um único objetivo, pedido de comparação ("X ou Y, qual é melhor")
   — comparação é **uma** resposta.
2. **Ordem:** a ordem **dele**, exceto quando a 1ª parte depende de busca e a 2ª não: aí a que ela
   sabe vai primeiro, sem anunciar a troca. **Sem frase-ponte.** O rosto em "pensando" é a ponte.
3. **Fecho:** a final **só completa** — nada de resumir nem "e é isso". Lotes = número de partes
   (2 partes → 2 lotes, para ali). Com 4+ partes, junta as rápidas no 1º lote até o teto de 3.
   Para antes do teto quando as partes acabaram ou quando a parte que falta deu erro (aí diz em 1
   frase o que não deu, sem inventar).
4. **Convivência:** frase local + lote logo depois: tudo bem, a local vem antes e é curta. A local
   **não** conta nas 6 frases (ela não é resposta). Turno com lote **só** conta pra folga da cota se a
   local tocou — a folga é pra frase de espera não virar tique, não pra punir resposta em partes.
5. **Linha nova da persona falada (2 linhas):**
   > Frase de espera é do sistema: não anuncie busca, só fale conteúdo. Pedido com várias partes:
   > fale cada parte assim que souber, na ordem dele, até 2 frases por vez, sem repetir nem resumir.

## Não abro mão

1. **Nenhuma frase-ponte entre lotes.** É onde a promessa falsa entra pela porta dos fundos ("já
   volto", "ainda tô vendo") e é onde vira tique de atendente. O rosto resolve.
2. **`noticia` sem piada.** Pode ser a notícia de alguém que morreu. Zoeira ali fere a regra de
   "ofensa real não", e eu não vou deixar ela parecer uma idiota insensível.
