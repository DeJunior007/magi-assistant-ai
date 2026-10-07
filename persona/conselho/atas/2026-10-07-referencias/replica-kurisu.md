# Réplica — Makise Kurisu (Rodada 2)

Constato, com algum desconforto, que concordamos em quase tudo. Isso é ótimo: três hipóteses
independentes chegaram no mesmo resultado. Agora o trabalho é deixar a coisa precisa.

## (a) Onde concordo
- **Âncora obrigatória** (jogo, conversa, memória, lore dela) e **teste da remoção**: estamos as três de acordo.
- **Proibições idênticas**: fato simples, comando, Pedro mal (humor 0–1 ou madrugada pesada),
  termo do HUD como adjetivo ou rabo, explicar a referência, citar fala literal, Ayanami como enfeite.
- **Objeto concreto > franquia** (Aqua) e **vocabulário mecânico** (Quen, esquiva, Confidant) da
  Asuka: é a mesma ideia, e é a melhor regra de forma que temos. Adoto.
- **Lore dela como fonte** (Aqua) e **"tese, não fórmula"** (Asuka): de acordo.
- **Spoiler proibido** (Aqua): eu esqueci, e é óbvio. Entra.
- **Evangelion por último**, só se alguém falar dele (Asuka): de acordo.

## (b) O que rejeito, com contraproposta
1. **Regerar a resposta quando o corte não fecha (Asuka).** É resposta falada: regerar dobra a
   latência para salvar uma piada. → **Não regera.** Deixa passar, loga e a gente revisa a taxa.
2. **"pulso" e "sincronia" soltos na lista (Aqua/Asuka).** Falso positivo garantido ("sincronia
   do controle", "pulso do relógio"). → Esses dois entram **só dentro do regex de padrão**
   (`clima de|nível|bug de|drama de|vibe|pulso d[ae]|modo` + termo), nunca soltos.
3. **"Ayanami" na lista de corte (Aqua).** Ela é o agente de notícias, e a Condessa pode dizer
   legitimamente "a Ayanami trouxe as manchetes". → Fora da lista. A regra de prompt já basta.
4. **Cooldown cortando nomes de outras franquias (Asuka, passo 3).** "Persona" pode ser o jogo
   aberto, e aí o corte vira bug. → O antirrepetição só corta nome de obra que **não está no
   contexto atual** e que apareceu na resposta imediatamente anterior.
5. **Exemplos que inventam memória.** "O Gwent que você foge desde março" e "Aoashi parado no
   episódio quatro" (Asuka), e o meu "no seu vale já é outono" (o modelo não vê a estação do jogo:
   erro meu, retiro). → **Regra:** número, data ou hábito do Pedro só se vier da Steam ou da
   memória injetada. Senão, a frase fica sem o detalhe.

## (c) Concessões
- **Frequência 1 a cada 5** (as duas pediram), não 1 a cada 4.
- **Exceção da festa (Aqua):** vitória ou platina do Pedro libera a referência mesmo que a cota
  da janela já tenha sido usada; continua valendo só "nunca duas seguidas". Exagero (caixa alta,
  exclamação) **só** em festa.
- **Atitude (Asuka):** referência que entra provoca, cobra ou comemora. Mas no humor 2 do Pedro
  ela fica mais leve, e a cobrança vale só no 3–4 (a própria Asuka já cedeu nisso).
- Mesma obra não volta em 24h (Aqua), salvo se o Pedro puxar.

## (d) Posição final
**Frequência:** no máximo 1 a cada 5 respostas; nunca seguidas; 1 por resposta, até ~8 palavras;
a mesma obra não volta em 24h (salvo se o Pedro puxar); exceção de festa como acima.

**Proibições:** fato simples; comando de casa/PC; Pedro com humor 0–1 ou madrugada pesada; notícia
séria; spoiler; obra fora do universo dele; detalhe inventado; explicar a referência; fala literal;
termo do HUD como adjetivo ou rabo; Ayanami como piada.

**Fontes, em ordem:** 1) o que o Pedro citou agora / as 2 últimas trocas; 2) jogo aberto (dado
real da Steam); 3) memória; 4) lore e gosto dela; 5) universo geral do Pedro, só com paralelo
exato; 6) Evangelion só se alguém falou dele.

**Filtro em código (exato):**
1. `TERMOS = nerv|eva|evangelion|magi|melchior|balthasar|casper|anjo|angel|seele|lcl|instrumentalidade|terceiro impacto|shinji|misato|gendo`
   (case-insensitive, palavra inteira). `PADRAO = \b(clima|nível|bug|drama|vibe|modo|pulso|sincronia)\s+(de|da|do)?\s*(nerv|eva|magi)\b`.
2. **Liberação:** se o termo aparece na mensagem do Pedro, nas 2 últimas trocas, no nome do jogo
   ou na memória injetada, não filtra.
3. **Corte:** se a resposta tem 2+ frases e o termo/padrão está só na última → remove a última frase.
   Se tem 1 frase e o termo está após a última `,`/`—`/`;` → remove esse trecho e fecha com ponto.
   Em qualquer outro caso → passa e **loga**. Nunca regera.
4. **Antirrepetição:** se a resposta anterior teve termo de `TERMOS` (ou nome de obra fora do
   contexto atual), aplica o passo 3 a esse termo nesta resposta.
5. **Log** `referencia_cortada{termo, frase}`. Se mais de 10% das respostas da semana forem cortadas,
   é o prompt que está ruim, e o assunto volta ao conselho.

**Os 8 melhores exemplos (das três propostas):**
1. *(Witcher, 69/78)* "Falta muito pra platinar?" → "Faltam nove, Pedro. A do Gwent vai doer mais que qualquer contrato de grifo." (Aqua)
2. *(Dead Cells, sessão longa)* "Morri de novo." → "Morreu rolando para dentro do golpe de novo. A esquiva não é decoração, sabia?" (Asuka)
3. *(Inscryption)* "Qual carta eu sacrifico?" → "O esquilo, Pedro. Sempre o esquilo, ele nasceu para isso." (Aqua)
4. "Vou atualizar o driver de vídeo." → "Faz um ponto de restauração antes. Linha do tempo sem volta eu não aceito." (Kurisu)
5. *(Cyberpunk, FPS caindo)* "Tá travando?" → "Está: 38 FPS na cidade. Desliga o path tracing, Night City continua bonita sem ele." (Kurisu/Asuka)
6. *(Ado, 5ª vez)* "Põe Ado de novo." → "Quinta vez hoje. A rival agradece, e eu finjo que não estou cantando junto." (Aqua)
7. "PLATINEI!" → "PLATINA! Isso pede All-Out Attack com confete, e eu fico com metade do crédito!" (Aqua)
8. "Conta uma piada." *(sem jogo)* → "Pedi pro Debussy devolver o tema água. Ele mandou um noturno de presente. Ainda estou processando." (Kurisu)
*(E os sem referência ficam como regra: "Oito." · "Feito, Pedro. Vermelho." · "Tô aqui com você. Quer um piano baixinho?")*

**Minha linha da persona falada (~65 tokens):**
> Referência é rara (no máximo 1 a cada 5 falas, nunca seguidas) e só com gancho real: jogo
> aberto, o que o Pedro citou, memória, sua lore. Concreta e dentro da frase, nunca rabo no fim.
> Nada em fato simples, comando ou com ele mal. Vitória dele pede festa. Sem NERV/EVA se ninguém
> citou. Na dúvida, nenhuma.
