# Design — Reações da Condessa

Implementa [requirements.md](requirements.md). Seções citadas por `§`.

## 1. Onde mora hoje

```
gamerhud.py ──clique──▶ integration.WiredHud.on_click ──▶ Reactor.on_click
integration._react (1 Hz) ──Snapshot──▶ Reactor.observe ──▶ Reactor.active(now) ──▶ mascot.react ──▶ portrait
```
- `hud/wired/reactions.py` (531 linhas): `Reaction` (1 rosto), `REACTIONS` (19), `Taste` (gosto do
  conselho + Pedro), `Reactor` (detecção, cooldown, falas).
- `hud/wired/portrait.py`: `_reacting()` usa `reaction.eyes/mouth/look/mood/effect/bob` só se
  `_resting()` (dormindo **de dia**). Efeitos em código: sweat, notes, question, bang, blush; zz só
  no estado `sleeping` de noite.

## 2. Princípio: o retrato não muda de contrato

O `Reactor` resolve a sequência por tempo e entrega ao retrato **um `Reaction` de 1 rosto** (o
passo atual), como hoje. O retrato só ganha: efeitos novos, extras de corpo opcionais e a regra
noturna (§6). Assim os detectores e o motor podem ser feitos sem tocar no retrato, e vice-versa.

## 3. Pacote novo `hud/wired/reacoes/`

| Módulo | Papel | Dono (tarefa) |
| --- | --- | --- |
| `contratos.py` | `Passo`, `Def` (definição de reação), `Disparo` (evento de detector), `Classe`, enums | R0.1 |
| `catalogo.py` | as 110 `Def` (dados, sem lógica), `ATIVAS` (só as com sinal disponível) | R0.4 |
| `governador.py` | cotas, cooldown, prioridade, fila, bloqueios, blush/lágrima; puro, relógio injetado | R0.2 |
| `humor.py` | fatores e pesos (acordo §4) → pesos das passivas | R1.1 |
| `passivas.py` | sorteio de passivas pelo `humor` | R1.1 |
| `atividade.py` | "evento real" do Pedro, último uso, primeiro do dia (arquivo de estado) | R1.4 |
| `det_musica.py`, `det_sistema.py`, `det_tempo.py`, `det_claude.py`, `det_entrada.py`, `det_conversa.py`, `det_extras.py` | detectores: `(anterior, snap, ctx) -> list[Disparo]` | R1.x / R2.x |
| `registro.py` | log `reacoes.jsonl` (R10) | R0.2 |

`reactions.py` continua sendo a porta de entrada (`Reactor`, `Taste`, `REACTIONS`, `LOOK_DIRS`,
`MOOD_OF_STATE` não mudam de nome). `Reactor.observe` passa a: (1) rodar os detectores
registrados em `reacoes/__init__.DETECTORES`; (2) mandar os `Disparo` ao governador; (3) tocar o
vencedor. A lógica de música atual (`_music`, `_decide`) fica em `reactions.py` e só emite
`Disparo`; a nova (det_musica) cobre o resto.

**Paralelismo:** R0.1 cria **todos** os módulos `det_*.py` como stubs (`def detectar(...) ->
list: return []`) já registrados em `DETECTORES`. Cada tarefa de detector edita só o próprio
arquivo e o próprio teste: zero conflito de merge entre elas.

## 4. Fluxo de um tick (1 Hz)

1. `ctx` = hora, humor do Pedro, jogo, Claude, música (nota pelo `Taste`), madrugada, estado da
   Magui, `atividade`.
2. Cada detector devolve `Disparo(chave, motivo, variante=None, fmt={})`.
3. A cada 10 s, `passivas.sortear(ctx)` pode devolver 1 `Disparo` passivo.
4. `governador.escolher(disparos, agora, ctx)` → no máximo 1 aprovado (ou o que estava na fila).
5. `Reactor` instancia a sequência, guarda `inicio`; `active(agora)` devolve o passo atual como
   `Reaction` de 1 rosto (bloqueio R3.1 já aplicado: C8/C11 → C9).
6. `registro.gravar(...)`.

## 5. Sinais novos (spec §6)

| Sinal | Onde nasce | Como chega ao `Reactor` |
| --- | --- | --- |
| A retrato hover/clique | `gamerhud.py` (mouse tracking na área do rosto de `main_screen.mascot_tick`) | `on_click("face:dbl"/"face:long"/"face:drag")`, `on_hover(entrou/parado_s)` |
| B tag do turno | núcleo (`magi/memory/mood.py` já detecta elogio, riso, correção) | `TurnTagMsg {"t":"turn_tag","v":"elogio"}` → `snap.turn_tag` |
| C hooks Claude Code | script `hud/tools/claude_hook.py` chamado pelos hooks do usuário | `~/.cache/magi/claude-events.jsonl` → `ClaudeView.last_event` |
| D volume | `wpctl get-volume @DEFAULT_AUDIO_SINK@` a cada 1 s numa thread | `snap.volume` |
| E notificações | `dbus-monitor --session` filtrando `org.freedesktop.Notifications.Notify` (subprocesso) | `snap.notif` (contador + urgência) |
| F voz baixa | `ToneMetadata` do satélite no núcleo | tag `sussurro` no sinal B |
| extras | hwmon `fan*_input`; `dnf needs-restarting -r` (6 h); mtime da pasta de capturas; `[datas]` | campos no `Snapshot` / `ctx` |

**Proibido:** qualquer `qdbus`/`gdbus` para o KGlobalAccel/KWin (derruba a sessão KDE). O sinal E só
**escuta** o barramento de sessão.

## 6. Retrato (R6 e extras)

- `Def.noturna = True` → `portrait._reacting()` aceita também `sleeping` de noite. A pose de
  dormir (B14/B15) volta sozinha no fim.
- Efeitos novos em código no `_reaction_effect`: `zz` (D3), `tear` (D7), `vein` (D8), `sparkle`
  (D9); `Reaction.effect` passa a aceitar tupla (até 3 efeitos no mesmo passo).
- Extras de corpo por passo: `sway` (corpo), `tails` (chiquinhas mais fortes), `bob` (já existe),
  `fone` (`on`/`off`: E2/E3), `braco` (P9–P13 se o asset existir), `iris` (sacada do O1 para um
  olhar nomeado). Asset ausente → extra ignorado (R1.1).

## 7. Riscos

| Risco | Mitigação |
| --- | --- |
| CPU do HUD sobe com 7 detectores | detectores são comparações simples a 1 Hz; humor a cada 10 s; teste de tempo (R0.2) |
| Merge entre tarefas paralelas | stubs pré-registrados (§3); cada tarefa só no próprio arquivo |
| Rosto poluído | governador único + log R10 + validação de 1 semana (R3.2) |
| Retrato quebra | contrato do retrato não muda (§2); testes atuais de `test_wired_portrait.py` seguem verdes |
