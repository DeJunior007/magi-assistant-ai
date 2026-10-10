# Tarefas — Espera viva

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **um agente** com janela de **até 128k tokens** (teto duro). Várias rodam em
paralelo (campo *Paralelo*); o orquestrador (Pedro ou a sessão principal do Claude Code) só lança
uma tarefa quando todas as de *Depende de* estão no `main`.

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*). Design por `§`, spec por `spec §`, requisitos por
   `R`, decisões por `D`.
2. **Orçamento planejado ≤ 50k tokens**; o resto da janela de 128k é margem. Perto de 90k: pare,
   faça commit do que está verde e anote o que faltou no fim desta lista (seção *Sobras*).
3. **Contratos primeiro:** use `ThinkMsg` (`magi/common/contracts.py`), `magi/core/espera.py`,
   `hud/wired/pensando.py` e as assinaturas dos stubs da E0.1; não leia o código de outras tarefas.
4. **Só os arquivos do campo *Escreve*.** Precisou de outro? Pare e anote em *Sobras*.
5. **Arquivos grandes por trecho** (`grep -n` + leitura por intervalo): nunca leia inteiros
   `magi/core/turn.py`, `magi/agent/graph.py`, `hud/gamerhud.py`, `hud/wired/portrait.py`,
   `hud/wired/main_screen.py`, `hud/wired/integration.py`, `magi/common/contracts.py`.
6. **Testes curtos:** `uv run pytest -q -x <arquivo de teste>` e `uv run ruff check <seus arquivos>`.
   Relógio, `rng` e espera do loop sempre injetados/controlados; nada de `sleep` real acima de 50 ms.
7. **Nada ao vivo nos testes:** sem STT/TTS/modelo de verdade (dublês de `tests/core/test_stream_speech.py`
   e `tests/agent/test_graph.py`), sem satélite, sem HUD de verdade, nenhuma chave de API. Nunca
   `qdbus`/`gdbus` para KGlobalAccel/KWin.
8. **Uma tarefa = um commit** com o ID (`E2.3: frase de espera no turno`), na branch `espera/<ID>`;
   merge no `main` pelo orquestrador.
9. **Comportamento de hoje é o piso:** com `[espera] frase = false` e `lotes = false` todos os testes
   atuais de `tests/core/` e `tests/agent/` passam sem mudar asserção (CA-10).

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~3k,
`design.md` ~3k, `spec.md` ~4,5k, `early.py` ~1k, `graph.py` ~5k, `turn.py` ~11k (ler por
trecho), `turn_phase.py` ~1,2k, `persona.md` ~1,5k, `condessa.md` ~4k.

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
E0.1 ─┬─ E1.1 ─────────┐
      ├─ E1.3 ─────────┴─ E1.2 ──────────────┐
      ├─ E1.4 ──────────────────────┐        │
      ├─ E2.1 ─┐                    │        │
      └─ E2.2 ─┴─ E2.3 ─────────────┴─ E3.1 ─┴─ E4.1 (validação, Pedro)
```

---

## Fase E0 — Contratos

- [ ] **E0.1 Contratos e esqueleto** — `ThinkMsg`, `THINK_KINDS`, `THINK_TOOLS` em
  `contracts.py` (spec §1) e no `HudMessage`; decodificador `think` em `events.decode_hud` e em
  `hud_bridge._MIN_DECODERS` (+ sinal Qt `think`, ainda sem ninguém ligado); `magi/core/espera.py`
  com `EsperaCfg.from_raw` **pronto** (spec §5) e stubs de `Catalogo.load`, `topico`, `Cota`,
  `escolher`, `mesma_espera`, `honesta` (assinaturas finais, docstring com a tarefa dona);
  `hud/wired/pensando.py` com `Pose` e stub de `pose`; em `early.py` o `THINK_HUD` (ContextVar) e
  `notify_wait()`, `notify_tool(nome)`, `notify_lote(n)` (no-op sem gancho); em `turn.py` só o
  `_think` abrindo/fechando o `THINK_HUD` junto do `EARLY_SPEECH` (manda pelo `self.hud.send` numa
  tarefa, como `_captions`); `[espera]` comentada em `config.example.toml`. *(R2, R7, design §3–§4)*
  - Lê: design §1–§4, spec §1, §2 (só o bloco `Pose`), §5; `contracts.py` por trecho (`grep -n "class TurnTagMsg\|HudMessage"`); `events.py` por trecho (`grep -n turn_tag`); `hud/hud_bridge.py` linhas 150–230; `early.py` inteiro; `turn.py` por trecho (`_think`, linhas ~812–850)
  - Escreve: `magi/common/contracts.py` (só `ThinkMsg`/constantes/`HudMessage`), `magi/common/events.py` (decodificador), `hud/hud_bridge.py` (decodificador + sinal), `magi/core/espera.py`, `hud/wired/pensando.py`, `magi/core/early.py` (só o gancho), `magi/core/turn.py` (só `_think`), `config.example.toml`, `tests/common/test_think_msg.py`, `tests/core/test_espera_cfg.py`
  - Depende de: —
  - Orçamento: ~40k
  - Pronto: CA-01 verde; `EsperaCfg` com padrões, inválido → `ConfigError`; um `notify_tool` dentro de `_think` com HUD falso chega como `ThinkMsg`; `tests/core/test_stream_speech.py`, `test_turn_states.py` e `tests/hud/test_bridge.py` verdes; `ruff` limpo.
  - Paralelo: —

## Fase E1 — Rosto, chip e aviso de ferramenta

- [ ] **E1.1 Pose de pensar** — `pensando.pose(desde_s, tool, lote, tem)` pela spec §2.1 e §2.3
  (etapas, ciclo filtrado por asset, olhar de painel 1,5 s pela ferramenta, `lote` nunca volta ao
  `hm`). Puro, sem Qt. *(R1, R1.2, R2.1)*
  - Lê: spec §2; `hud/wired/pensando.py`; `portrait.py` linhas 455–466 (`THINK_*`); `reactions.py` linhas 100–105 (`LOOK_DIRS`)
  - Escreve: `hud/wired/pensando.py`, `tests/hud/test_pensando.py`
  - Depende de: E0.1
  - Orçamento: ~25k
  - Pronto: CA-02 verde; tabela §2.3 inteira testada; `ruff` limpo.
  - Paralelo: E1.3, E1.4, E2.1, E2.2

- [ ] **E1.3 Chip da espera** — `TurnPhase.on_think(kind, tool, now)`: rótulo de ferramenta
  (spec §2.4) enquanto a fase é `thinking`; em `lote`, volta a fase mostrada a `thinking` até o
  próximo nível de boca/`speech` (respeitando `MIN_DWELL_S`); `TurnPhase.chip_tool(now)`.
  `Snapshot.chip_tool: str | None` e `chip_label` usando-o (rótulos novos ao lado de
  `CHIP_STATES`). *(R2.2, R5.3)*
  - Lê: spec §2.4; `hud/turn_phase.py` inteiro; `main_screen.py` por trecho (`grep -n "chip\|CHIP_STATES"`, linhas ~140–200)
  - Escreve: `hud/turn_phase.py`, `hud/wired/main_screen.py` (só `Snapshot.chip_tool`, `chip_label`, rótulos), `tests/hud/test_state_chip.py` (casos novos)
  - Depende de: E0.1
  - Orçamento: ~30k
  - Pronto: testes atuais do `TurnPhase` sem mudar asserção; ferramenta → rótulo; lote → `Thinking` até a boca mexer; troca de rótulo sem piscar (< `MIN_DWELL_S`).
  - Paralelo: E1.1, E1.4, E2.1, E2.2

- [ ] **E1.2 Retrato e ponte do HUD** — `PartsPortrait.set_think(kind, tool, now)`; `_think_look`
  e o `tilt` passam a vir de `pensando.pose` (`desde_s` do 1º `thinking` do turno; zera no
  `sleeping`/`listening`); efeito `dots` (spec §2.2) no `_reaction_effect`; corpo `sway`/
  `bob_lento`/`braco:P14` pelo mesmo caminho dos extras das reações (asset ausente → ignora). Ligação:
  `gamerhud.on_bridge_think` → `turn_phase.on_think` + `wired.set_think` e `snap.chip_tool` no
  mesmo ponto em que hoje sai `snap.chip`; `WiredUI.set_think` repassa ao retrato.
  *(R1, R1.1, R1.3, R2, R5.3)*
  - Lê: spec §2; design §4; `pensando.py`; `portrait.py` por trecho (`grep -n "thinking\|_think_look\|_think_k\|THINK_TILT\|_reaction_effect\|def set_expression"` e só esses intervalos); `gamerhud.py` por trecho (`grep -n "turn_phase\|on_bridge_turn_tag\|turnTag"`); `integration.py` por trecho (`grep -n "def set_turn_tag"`)
  - Escreve: `hud/wired/portrait.py`, `hud/gamerhud.py` (só a ligação), `hud/wired/integration.py` (só `set_think`), `tests/hud/test_wired_portrait.py` (casos novos), `tests/hud/test_espera_hud.py`
  - Depende de: E1.1, E1.3
  - Orçamento: ~50k
  - Pronto: testes antigos do retrato sem mudar asserção; etapas trocam nos tempos certos com relógio falso; `dots` desenha com e sem `extra/D10.png`; voz começa → pose sai (R1.3); `ThinkMsg` vinda da ponte muda chip e retrato (teste com `WiredUI` falso, `MAGI_NO_*` como nos testes atuais).
  - Paralelo: E2.3

- [ ] **E1.4 Ferramentas: aviso e paralelo** — `_tools_node` chama `notify_tool(nome)` antes de
  cada ferramenta; `Tool.serial` (spec §7) nas ferramentas de mídia/PC; ferramentas não-`serial`
  da volta em `asyncio.gather` (atrás de `[espera] ferramentas_paralelo`, passado ao `GraphAgent`);
  confirmação e erro como na spec §7; log `espera: ferramentas … em paralelo`. *(R2, R5.5, R8)*
  - Lê: spec §1, §7; `graph.py` por trecho (`_tools_node`, `_after_tools`, `__init__`, linhas ~108–145 e ~221–247); `magi/agent/tools/*.py` só por `grep -n "Tool(\|final="`
  - Escreve: `magi/agent/graph.py` (só `__init__` e `_tools_node`), `magi/agent/tools/*.py` (só `serial=True`), `magi/core/assemble.py` (só as duas linhas `GraphAgent(`, ~283–286; a E2.3 mexe em outro trecho), `tests/agent/test_graph_paralelo.py`
  - Depende de: E0.1
  - Orçamento: ~40k
  - Pronto: CA-08 verde; `tests/agent/test_graph.py` sem mudar asserção; `notify_tool` uma vez por ferramenta, com nome fora de `THINK_TOOLS` → `other`.
  - Paralelo: E1.1, E1.3, E2.1, E2.2

## Fase E2 — Frase de espera

- [ ] **E2.1 Catálogo pelo Conselho** — **precisa do Pedro para revisar.** Rodar `/conselho` com o
  assunto "frases de espera e respostas em lotes" (restrições: spec §3.1 e §4; D2, D3): ata em
  `persona/conselho/atas/<data>-espera/`, `acordo.md` com o catálogo e a regra dos lotes.
  Gravar: `magi/core/espera.yaml` (spec §3.1), as frases em `phrases.yaml` (`lazy`) e os moldes
  (`templates`), a linha "Ferramenta demorada…" de `magi/agent/persona.md` reescrita com a regra
  de lotes (design §5), e a linha "Última decisão" de `persona/condessa.md`. *(R3.1, R4, D1–D4)*
  - Lê: requirements (Problema, R3–R5, Decisões); spec §3.1, §3.4, §4; `magi/agent/persona.md`; `persona/condessa.md` linhas 1–60; `magi/core/phrases.yaml` linhas 1–10 e 140–160
  - Escreve: `persona/conselho/atas/<data>-espera/*`, `magi/core/espera.yaml`, `magi/core/phrases.yaml`, `magi/agent/persona.md` (só a linha da espera), `persona/condessa.md` (só a linha "Última decisão"), `tests/agent/test_prompt.py` (só se a linha mudada quebrar asserção de texto)
  - Depende de: E0.1
  - Orçamento: ~45k
  - Pronto: mínimo da spec §3.1 cumprido; toda frase checada à mão contra a tabela §4 (o linter de verdade é da E2.2); `tests/core/test_tts.py` verde; nota do Pedro na ata.
  - Paralelo: E1.1, E1.3, E1.4, E2.2

- [ ] **E2.2 Seletor da frase** — `espera.py`: `Catalogo.load` (+ vetadas do gosto, caminho
  injetável), `topico` (spec §3.2), `Cota` (§3.3), `escolher`, `mesma_espera` (§3.4), `honesta`
  (§4). Puro, `rng` injetado. Testes com catálogo de teste (não depende do arquivo real).
  *(R3.6, R4, D2)*
  - Lê: spec §3, §4; `magi/core/espera.py`; `magi/core/compose.py` linhas 1–40 (normalização/`sentences`)
  - Escreve: `magi/core/espera.py`, `tests/core/test_espera.py`
  - Depende de: E0.1
  - Orçamento: ~40k
  - Pronto: CA-03 (com frases de teste) e CA-04 verdes; `ruff` limpo.
  - Paralelo: E1.1, E1.3, E1.4, E2.1

- [ ] **E2.3 Frase de espera no turno** — `TurnPipeline.peek_route(text, ctx)` (`route` +
  `_settle`, sem efeito); no `_think`, a tarefa `espera` do design §3 (só rota agente, `frase_apos_ms`,
  `early.started`, cota por satélite); `EarlySpeech.say_wait`, `waits`, `drop_wait_echo`,
  `missing` sem `waits` (spec §6); `_Voice` chama `drop_wait_echo` na 1ª interina; `notify_wait`;
  cancelamento no `finally` do `_think` e em `_cancel_work`; montagem (`assemble.py`: `EsperaCfg`,
  `Catalogo`, `Cota` no `TurnDeps.espera`); logs da spec §8; teste que roda `honesta` no
  `espera.yaml` real e confere que todas as frases (e moldes com 3 jogos falsos) são cacheáveis
  (`Phrases.cacheable`). *(R3, R3.1–R3.5, R6, R8)*
  - Lê: design §3; spec §3.3, §3.4, §6, §8, §9 (CA-05, CA-06, CA-09); `early.py`; `turn.py` por trecho (`TurnDeps`, `respond`/`_respond`/`_settle`, `_think`, `_early_speech`, `_cancel_work`); `graph.py` por trecho (`class _Voice`, `_call`); `assemble.py` por trecho (`grep -n "TurnDeps\|load_config\|cfg.raw"`); `tests/core/test_stream_speech.py` por trecho (dublês)
  - Escreve: `magi/core/turn.py`, `magi/core/early.py`, `magi/agent/graph.py` (só `_Voice`), `magi/core/assemble.py` (só a montagem), `tests/core/test_espera_turno.py`, `tests/core/test_espera_catalogo.py`
  - Depende de: E0.1, E2.1, E2.2
  - Orçamento: ~50k
  - Pronto: CA-05, CA-06, CA-09 verdes; CA-10 (`frase = false`) verde; `test_turn_states.py`, `test_stream_speech.py`, `test_followup.py` sem mudar asserção.
  - Paralelo: E1.2

## Fase E3 — Lotes

- [ ] **E3.1 Respostas em lotes** — `EarlySpeech`: `lotes`, `open_lote`/`close_lote`,
  `say(lote=True)` com os tetos de `[espera]` (spec §5–§6), `missing` sem lotes, `full_text`;
  `_Voice`: classificação lote × interina (spec §6) e `notify_lote(n)` ao fechar um lote;
  `_deliver`: `SubtitleMsg.full` pelo `early.full_text` quando houve lote (R5.4); log de lote.
  *(R5, R5.1–R5.4, R6)*
  - Lê: design §5; spec §5, §6, §8, §9 (CA-07, CA-09, CA-10); `early.py`; `graph.py` por trecho (`_Voice`, `_call`, `_model_node`, `_first_reply`); `turn.py` por trecho (`_deliver`); `compose.py` por trecho (`subtitle`)
  - Escreve: `magi/core/early.py`, `magi/agent/graph.py` (só `_Voice`/`_call`), `magi/core/turn.py` (só `_deliver`), `tests/core/test_lotes.py`
  - Depende de: E1.4, E2.3
  - Orçamento: ~50k
  - Pronto: CA-07 e CA-10 (`lotes = false`) verdes; `tests/agent/test_graph.py` e `tests/core/test_stream_speech.py` sem mudar asserção; turno com 4 voltas nunca passa de `lotes_frases_max`.
  - Paralelo: —

## Fase E4 — Medida e validação

- [ ] **E4.1 Medida e uma semana de uso** — **precisa do Pedro.** `tools/perf.py latency` com
  `primeiro_som` (spec §8); rodar `latency --turns 20` com 3 frases (simples, com ferramenta, de 2
  partes) antes/depois (`[espera] frase/lotes` desligados × ligados); `docs/perf/espera.md` com a
  tabela e os critérios de sucesso 1, 3–6; uma semana de uso com o log `espera:` e a nota do Pedro;
  o que soar falso ou chato volta ao Conselho; `docs/PROXIMOS-PASSOS.md` §2 atualizado.
  - Lê: requirements (Critérios), spec §8; `tools/perf.py` por trecho (`grep -n "def latency\|p90"`); `docs/perf/fase1.md` linhas 221–240
  - Escreve: `tools/perf.py`, `tests/tools/test_perf.py` (casos novos), `docs/perf/espera.md`, `docs/PROXIMOS-PASSOS.md` (só §2)
  - Depende de: E1.2, E3.1
  - Orçamento: ~35k
  - Pronto: medida com dados reais registrada; critério 1 (p90 do primeiro som ≤ 1,8 s; resposta ≤ 3,5 s) conferido; nota do Pedro.
  - Paralelo: —

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)
