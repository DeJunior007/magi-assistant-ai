# Conselho — Referências da Condessa (do zero)

Assunto: **como a Condessa faz referências** (citações, piadas internas, alusões a obras) quando
fala com o Pedro. Não é para checar as referências atuais: é para **construir do zero** o jeito
dela de referenciar. Leia antes `persona/condessa.md` (bio, gosto, odisseias decididas por vocês)
e a sua bio em `persona/conselho/delegadas/`.

## O problema (dados reais, respostas faladas dela nesta semana)

A persona falada tem hoje uma linha: "A vibe é Evangelion/NERV: pode soltar uma referência de vez
em quando, sem forçar". O modelo virou isso num tique: cola "NERV"/"EVA" no fim de qualquer coisa.

- Pedro: "Falta muito pra mim platinar The Witcher?" → "...platinar sem sofrimento é **lenda nível EVA dar errado**."
- Pedro: "Quantas patas tem uma aranha?" → "Oito, Pedro. **Se tiver nove, aí é bug de NERV.**" (3 variações iguais)
- Pedro: "Deixa as luzes vermelhas." → "Feito, Pedro. **Vermelho no clima de NERV.**"
- Pedro: "quando volta Mushoku Tensei?" → "...só esperando o **próximo pulso da NERV**."
- Pedro: "próxima novidade" → "...sem **drama de EVA**."
- Boa (para comparar): "Conta uma piada." → "Por que o Geralt nunca perde discussão? Porque ele sempre leva tudo na marra, com sinal de Quen." (ligada ao jogo dele, faz sentido)

O Pedro achou péssimo: "nada a ver isso".

## Restrições do sistema
- As respostas são **faladas**: 1–2 frases curtas. Referência não pode roubar a resposta.
- A regra que entra na persona falada precisa ser curta (entra em todo prompt): no máximo
  ~70 tokens. Um guia maior pode existir em `persona/` para humanos e para gerar exemplos.
- O modelo vê no prompt: o jogo aberto (nome, gênero, horas e conquistas da Steam), o humor do
  Pedro (0–4), memórias relevantes e as 2 últimas trocas. Não vê a tela.
- Dá para pôr um **filtro em código** depois da resposta (ex.: cortar frase final que só existe
  para enfiar um termo), se vocês decidirem; diga exatamente o que filtrar.
- Universo do Pedro: Persona (3 Reload, 5 Royal), Evangelion, Serial Experiments Lain,
  Steins;Gate, KonoSuba, The Witcher, Death Stranding, Stardew, Dead Cells, Inscryption, FIFA 22,
  Cyberpunk; anime da temporada (Aoashi, Mushoku Tensei); música (Ado, Yorushika, Persona OST).
- O HUD tem nomes do universo EVA (MAGI SYSTEM, Melchior/Balthasar/Casper, Rádio Ayanami); a
  Ayanami é o agente de notícias (persona/ayanami.md).

## Formato de saída esperado
1. **Princípios** (por que e quando ela referencia; o que torna uma referência boa).
2. **Regras concretas**: frequência, gatilhos (quando sim), proibições (quando nunca), fontes
   (de onde tirar: jogo aberto, memória, gosto dela, conversa), forma (como encaixar).
3. **Padrões proibidos** (com exemplos reais acima) e, se quiserem, o filtro em código.
4. **Repertório inicial**: 10–15 exemplos BONS (pedido do Pedro → resposta com referência), e
   5 RUINS reescritos.
5. **A linha da persona falada** (≤ 70 tokens) que substitui "A vibe é Evangelion/NERV...".
