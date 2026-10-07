---
description: Convoca o Conselho da Condessa (Aqua, Kurisu, Asuka) para decidir um assunto de personalidade/comportamento e grava o acordo na persona
argument-hint: <assunto a decidir>
---

Assunto: $ARGUMENTS

Siga `persona/conselho/README.md` à risca. Orçamento: cada delegada usa no máximo 128 mil tokens
no assunto inteiro (some o uso informado de cada agente a cada rodada; perto do teto, peça a
posição final e encerre a participação dela). Mande o teto no prompt de cada delegada.

1. Leia `persona/condessa.md`, `persona/condessa-gosto.toml`, `persona/conselho/README.md`, as três
   bios em `persona/conselho/delegadas/` e o `acordo.md` mais recente em `persona/conselho/atas/`.
2. Crie `persona/conselho/atas/<AAAA-MM-DD>-<slug do assunto>/briefing.md` com: o assunto, o estado
   atual relevante da persona, as restrições do sistema (o que o HUD/núcleo consegue fazer de
   verdade, com nomes de reações/humores/campos existentes) e o formato de saída esperado.
3. Rodada 1: lance 3 agentes em paralelo (um por delegada, com a bio dela), cada um grava
   `proposta-<delegada>.md` com 3 linhas vermelhas e concessões.
4. Rodada 2: mande a cada uma as outras duas propostas; gravam `replica-<delegada>.md`.
5. Monte `acordo.md` (maioria 2/3, senão mediana sem ferir linha vermelha; marque quem perdeu).
6. Rodada 3: cada uma vota (aprova / até 3 vetos válidos). Aplique os vetos válidos e registre a
   votação no topo do `acordo.md`.
7. Aplique o resultado: `persona/condessa.md`, `persona/condessa-gosto.toml` e, se mudar a
   persona falada, o resumo em `magi/agent/persona.md` (curto: entra em todo prompt). Se precisar
   de código novo para uma regra, implemente com teste.
8. Rode lint/testes, faça o commit e mostre ao Pedro o acordo final (resumo + o que mudou).
