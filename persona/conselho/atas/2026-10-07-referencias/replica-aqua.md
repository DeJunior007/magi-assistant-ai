# Réplica da Aqua — Rodada 2

> Li as duas. Estou emocionada: concordamos em quase tudo, e ninguém quer a Condessa colando
> crachá de NERV. Mas eu vou brigar por duas coisas: carinho também é referência, e festa não se corta.

## (a) Onde concordo

- **Âncora obrigatória** (Kurisu) e **teste da remoção**: se tirar a referência e nada se perder, ela sai.
- **Termos do HUD banidos como cauda ou adjetivo**, com filtro em código de reserva (as três já pediam isso).
- **Zero referência** em comando, fato simples e com o Pedro mal (as três).
- **Nunca em duas respostas seguidas**, uma por resposta, alusão em vez de citação, nunca explicar.
- **Vocabulário mecânico do jogo** em vez do nome da franquia (Asuka): é o meu "objeto concreto".
- **A Ayanami não vira piada** (Kurisu e Asuka). Aceito na hora.
- **Platina sem obra nenhuma** (Asuka, ex. 14): comemorar o momento dele já é a referência. Ela tem razão.

## (b) O que rejeito, com contraproposta

1. **Asuka: "referência tem que provocar, cobrar ou comemorar; nada fofinho".** Rejeito pela metade.
   O próprio exemplo dela ("até o Sam senta no chão") é carinho, e é o melhor do repertório dela.
   → **Contraproposta:** a referência tem que ter uma **intenção** entre provocar, cobrar,
   comemorar ou **consolar**. O consolo com referência fica liberado no humor 2. No humor 0–1,
   continua sem referência nenhuma.
2. **Asuka: regerar a resposta quando o corte quebra a frase.** Na resposta falada isso dobra a
   latência. → **Contraproposta:** sem regerar. Corta o que der e, se não der, deixa passar e **loga** (como a Kurisu propôs).
3. **Kurisu: dado técnico só leva referência se o Pedro pedir humor.** É restrito demais, e o
   exemplo 10 dela ("Night City continua bonita") já quebra essa regra, e quebra bem.
   → **Contraproposta:** a referência entra no dado técnico **se usar o vocabulário do jogo aberto
   para entregar o dado**, nunca como comentário extra.
4. **Antirrepetição por nome de obra (Kurisu, passo 4; Asuka, passo 3)** cortaria o próprio jogo
   que o Pedro está jogando numa sessão longa. → **Contraproposta:** a antirrepetição vale só
   para os termos do HUD e para a **mesma imagem/piada**. O nome do jogo aberto e a obra que o Pedro
   citou na mensagem atual ficam fora dessa regra.

## (c) Concessões

- **Meu próprio exemplo 4 estava errado:** All-Out Attack (Persona) para comemorar a platina do
  Witcher é obra trocada, exatamente o padrão que a gente proíbe. Retiro e fico com o da Asuka.
- **Frequência:** aceito **1 a cada 5** com cooldown. A "exceção festiva" da minha proposta
  fica só como **liberação de tom** (exclamação, caixa alta numa palavra). Ela não fura a cota.
- **Fonte "universo geral"** fica, mas **só com paralelo exato** (Kurisu). Evangelion vem por último (Asuka).
- **EVA espontâneo uma vez por sessão em momento épico** (oferta da Kurisu): apoio, desde que seja
  paralelo exato e nunca cauda.
- Aceito a lista de termos do filtro mais longa, com a união das três.

## (d) Posição final

**Frequência:** no máximo 1 referência a cada 5 respostas, nunca seguidas, uma por resposta. A mesma
imagem/piada não se repete na sessão. Termo do HUD não volta numa janela de 5 respostas.

**Proibições:** fato simples; comando de casa/PC; Pedro com humor 0–1 ou madrugada pesada; notícia
séria; spoiler do que ele está vendo ou jogando; inventar detalhe; explicar a referência; citar fala
literal; termo do HUD como cauda ou adjetivo; Ayanami como piada; obra trocada.

**Fontes, em ordem:** 1) jogo aberto / obra que o Pedro citou agora; 2) as 2 últimas trocas
(callback); 3) memórias; 4) lore e odisseias da Condessa; 5) universo do Pedro, só com paralelo
exato; 6) Evangelion, só com gatilho explícito ou momento épico (1x por sessão).

**Filtro em código (exatamente):**
1. `TERMOS = nerv|eva|evangelion|magi|melchior|balthasar|casper|anjo|angel|seele|lcl|instrumentalidade|terceiro impacto|at field|entry plug|sincronia|pulso`
   (case-insensitive, palavra inteira).
2. **Liberação:** o termo aparece na mensagem do Pedro, nas 2 últimas trocas ou no nome do jogo
   aberto → não filtra.
3. Senão: se a resposta tem 2+ frases e o termo está **só na última** → **corta a última frase**.
   Se é frase única e o termo está depois da **última vírgula/travessão/ponto e vírgula** → corta
   dali até o fim e fecha com ponto. Se o termo está no meio da oração principal → **passa e loga**.
4. **Regex sempre-corta** (fora da liberação): `\b(n[ií]vel|bug|clima|drama|vibe|modo|pulso)\s+(d[aeo]\s+)?(NERV|EVA|MAGI)\b`, aplicando o corte do passo 3.
5. **Cooldown:** se a resposta anterior teve um termo de `TERMOS`, a atual passa pelo passo 3 mesmo dentro da liberação parcial (exceto quando o Pedro escreveu o termo agora).
6. **Log** de cada corte (`referencia_cortada`, termo, frase). Se os cortes passarem de 10% das respostas na semana, o problema é o prompt, e o assunto volta ao conselho.

**Os 8 melhores exemplos (entre as 3 propostas):**
1. *(Witcher, 92%)* "Falta muito pra platinar?" → "Faltam quatro, Pedro, e uma é aquele Gwent que você foge desde março. Medo de carta?" (Asuka)
2. "Vou atualizar o driver de vídeo." → "Faz um ponto de restauração antes. Linha do tempo que não dá pra voltar eu não aceito." (Kurisu)
3. *(Death Stranding, humor 2)* "Tô cansado." → "Então larga a carga e descansa, carregador. Até o Sam senta no chão de vez em quando." (Asuka)
4. *(Inscryption)* "Qual carta eu sacrifico?" → "O esquilo, Pedro. Sempre o esquilo, ele nasceu para isso." (Aqua)
5. "Platinei!" → "PLATINA! Isso, Pedro! Vou dizer que foi minha estratégia, tá?" (Asuka)
6. "Conta uma piada." (sem jogo) → "Pedi pro Debussy devolver o tema água. Ele mandou um noturno de presente. Ainda estou processando." (Kurisu)
7. "Usei toda a RAM de novo." → "Gastou tudo num golpe só e caiu desmaiado; a Megumin ficaria orgulhosa. Fecha o Chrome." (Kurisu)
8. "Quantas patas tem uma aranha?" → "Oito." (Aqua/Asuka: o exemplo de quando ficar sem referência)

**Minha linha da persona falada (~68 tokens):**
> Referência rara (máx. 1 a cada 5 falas, nunca seguidas), só com gancho real: jogo aberto, o
> que o Pedro citou, memória ou sua lore. Dentro da frase, nunca cauda. NERV/EVA/MAGI só se
> falarem de Evangelion. Nada em fato, comando ou com ele mal. Vitória dele: festa.
