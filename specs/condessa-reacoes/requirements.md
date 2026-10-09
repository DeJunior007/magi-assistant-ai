# Requisitos — Reações da Condessa

Fonte: planilha `reacoes_condessa.xlsx` do Pedro e o acordo do Conselho
(`persona/conselho/atas/2026-10-08-reacoes/acordo.md`, citado como **acordo §n**). Este arquivo é o
**PRD**. Arquitetura em [design.md](design.md); contratos, números e a tabela de gatilhos em
[spec.md](spec.md); implementação em [tasks.md](tasks.md). Critérios em EARS:

- **O HUD DEVE …** — sempre vale. **QUANDO** gatilho, **o HUD DEVE** … — reação a evento.
- **ENQUANTO** estado, **o HUD DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

## Problema

O rosto da Condessa tem 19 reações (`hud/wired/reactions.py`), cada uma um rosto parado só. A
planilha pede 110, com sequências de até 4 passos, reações passivas sem evento, cotas e regras de
convivência. Parte dos gatilhos depende de sinais que o HUD ainda não tem.

## Objetivo

Implementar as 110 reações do acordo, em ondas, sem quebrar as 19 atuais nem o retrato: primeiro
o motor (sequências, cotas, passivas), depois os detectores com sinais que já existem (87 reações,
piso de 80 cumprido), depois os sinais novos A–F e o resto.

## Critérios de sucesso

1. As 87 reações "rodam hoje" do acordo §6 disparam em teste com o `Snapshot` sintético do gatilho.
2. Nenhuma cota do acordo §3 é furada em teste de 24 h simuladas (relógio falso), exceto pelas
   classes que o acordo manda furar.
3. CPU do HUD continua ≤ 10% de um núcleo (medida de `docs/PROXIMOS-PASSOS.md` §7).
4. Uma semana de uso real sem o Pedro achar o rosto "poluído" (log de reações por hora ≤ 8 ativas).
5. Nenhuma reação condicionada entra no código antes do sinal dela (acordo §3 regra 6).

## Requisitos

**R1 — Sequências.** O HUD DEVE tocar uma reação como sequência de 1 a 4 passos, cada passo com
olhos, boca, olhar, efeitos, extras de corpo e duração em ms (spec §2). As 19 atuais viram reações
de 1 passo, com o mesmo resultado visual de hoje.
- R1.1 QUANDO um passo usa asset que não existe (ex.: P13 antes da arte), o HUD DEVE pular só
  aquele extra e manter o resto do passo.
- R1.2 QUANDO a Magui sai de parada (ouvindo/pensando/falando), o HUD DEVE descartar a reação em
  curso, como hoje.

**R2 — Cotas e prioridade (acordo §3 regras 1, 2, 5).** O HUD DEVE aplicar, num único governador:
passiva ≤ 1 a cada 40 s; raras ≤ 1/h; Corando sozinha ≤ 1/dia; cooldown de 10 min por ativa; teto
de 8 ativas/h; prioridade sistema > Pedro > música > tempo > passiva; fila de 1 slot de 30 s só
para volta do Pedro e vitória; blush ≤ 1/h (74, 87, 62 fora da conta); lágrima só 22h–04h e
≤ 1/dia. Sistema, vitória e volta do Pedro furam a cota de ativas.

**R3 — Bloqueios de contexto (acordo §3 regra 4).**
- R3.1 ENQUANTO o humor do Pedro estiver em 0–1 ou for 22h–04h, o HUD NÃO DEVE tocar reação da
  classe `zoeira` e DEVE trocar a boca de cobrança (C8/C11) por C9.
- R3.2 ENQUANTO houver jogo aberto, Claude Code rodando ou música nota ≥ 1, o HUD NÃO DEVE tocar
  reação da classe `sono` (17, 18, 19).
- R3.3 ENQUANTO houver jogo aberto, o HUD NÃO DEVE tocar passiva rara.

**R4 — Passivas com humor.** O HUD DEVE sortear as passivas pelos fatores e pesos de humor do
acordo §4, recalculados a cada 10 s a partir do `Snapshot`.

**R5 — Variantes, não clones (acordo §3 regra 3).** Gatilho que já pertence a uma das 19 reações
DEVE virar variante dela (mesma chave de cooldown), nunca reação paralela.

**R6 — Madrugada visível.** ONDE a reação for marcada `noturna`, o HUD DEVE mostrá-la também com a
Magui dormindo de noite (hoje `portrait._resting()` só deixa reagir de dia).

**R7 — Detectores com sinais existentes.** O HUD DEVE detectar os gatilhos da spec §5 que só usam
o `Snapshot`, cliques do HUD, horário e arquivos de estado já existentes.

**R8 — Sinais novos.** Cada sinal A–F (spec §6) DEVE ser implementado e testado antes das reações
que dependem dele; sem o sinal, a reação não existe no catálogo ativo.

**R9 — Honestidade.** Nenhuma fala de reação DEVE afirmar o que o gatilho não mede (spec §7).

**R10 — Registro.** O HUD DEVE gravar cada reação tocada (hora, chave, motivo, se furou cota) em
`~/.local/state/magi/reacoes.jsonl` (gira em 5 MB), para a validação da semana.

**R11 — Gosto do Pedro vence.** ONDE `~/.config/magi/condessa-gosto.toml` tiver
`[reacoes] desligadas = ["chave", ...]`, o HUD NÃO DEVE tocar essas reações.

## Decisões em aberto (precisam do Pedro)

- **D1 — Clique no retrato.** Hoje clique simples no rosto = push-to-talk. Para 69 (duplo) e 70
  (longo): (a) PTT espera 250 ms para ver se vem o 2º clique; (b) duplo/longo só com o botão do
  meio; (c) só hover e arrasto (69/70 ficam fora). **Padrão da spec até ele decidir: (a).**
- **D2 — Hooks do Claude Code (sinal C)** mexem no `~/.claude/settings.json` dele: a tarefa entrega
  o script e as instruções; quem instala é o Pedro.
- **D3 — Arte nova** (D1/D2/D6/D8, E3, B16, D7, P9, P10, B17, P12, P13): o Pedro gera; as tarefas
  funcionam sem ela (R1.1).
