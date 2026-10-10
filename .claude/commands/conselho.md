---
description: Convoca o Conselho da Condessa (Aqua, Kurisu, Asuka) para decidir um assunto de personalidade/comportamento e grava o acordo na persona
argument-hint: <assunto a decidir>
---

Assunto: $ARGUMENTS

Siga `persona/conselho/README.md` à risca. Orçamento: cada delegada usa no máximo 128 mil tokens
no assunto inteiro (some o uso **real** de cada agente a cada rodada; perto do teto, peça a
posição final e encerre a participação dela). Mande o teto no prompt de cada delegada.

1. Leia `persona/condessa.md`, `persona/condessa-gosto.toml`, `persona/conselho/README.md`, as três
   bios em `persona/conselho/delegadas/` e o `acordo.md` mais recente em `persona/conselho/atas/`.
2. Crie `persona/conselho/atas/<AAAA-MM-DD>-<slug do assunto>/briefing.md` com: o assunto, o que o
   Pedro já decidiu (fixo), os dados reais, o estado atual relevante da persona, as restrições do
   sistema (o que o HUD/núcleo consegue fazer de verdade) e o formato da rodada 1. **Não divida o
   assunto entre elas nem atribua papel** ("a Aqua cuida da emoção"): todas opinam sobre tudo.
3. Rodada 1 (mesa aberta): lance 3 agentes em paralelo, cada um com a bio dela e a instrução "você é
   ela, não um papel: opine sobre tudo, traga ideias suas, diga o que acha de verdade, na sua voz";
   cada um grava `fala-<nome>.md` no formato do README.
4. Rodada 2 (conversa): mande a cada uma as falas das outras duas; ela responde a cada uma pelo nome
   e grava `conversa-<nome>.md`.
5. Monte `acordo.md` como no README (apoio 2 de 3; crédito por ideia; quem pensa o quê; "Ideias que
   ficaram de fora").
6. Rodada 3: cada uma vota (aprova / até 3 vetos válidos / assina ideias de fora). Aplique os vetos
   válidos e registre a votação no topo do `acordo.md`.
7. Aplique o resultado: `persona/condessa.md`, `persona/condessa-gosto.toml` e, se mudar a
   persona falada, o resumo em `magi/agent/persona.md` (curto: entra em todo prompt). Se precisar
   de código novo para uma regra, implemente com teste.
8. Rode lint/testes, faça o commit e mostre ao Pedro o acordo final (resumo + o que mudou + as ideias
   que ficaram de fora).
