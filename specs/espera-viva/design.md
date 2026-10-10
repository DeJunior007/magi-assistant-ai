# Design — Espera viva

Implementa [requirements.md](requirements.md). Seções citadas por `§`.

## 1. O que já existe

```
satélite ─audio-stop─▶ TurnMachine._audio_end ─▶ _go(THINKING) ─▶ _think
   _think: pipeline.transcribe (STT) ─▶ EARLY_SPEECH.set(EarlySpeech(play)) ─▶ pipeline.respond
           respond: _observe_mood ─▶ route ─▶ _settle ─▶ _dispatch ─▶ agent.answer (GraphAgent)
           ─▶ _deliver(result, early) ─▶ compose ─▶ subtitle/cards ─▶ early.finish(missing) | speaker.say
```

| Peça | Onde | O que faz hoje |
| --- | --- | --- |
| Estados | `magi/common/contracts.py` `TurnState` | `sleeping → listening → thinking → (confirming) → speaking → (followup)`; HUD recebe `{"t":"state","v":...}` (`StateMsg`) |
| Pré-aquecimento (1.23) | `TurnPipeline.prewarm` ← `TurnMachine.wake` | abre HTTP do STT/TTS/agente enquanto o Pedro fala |
| Memória em paralelo (1.23) | `GraphAgent._first_reply` | 1ª chamada do modelo corre junto com a busca; frases ficam **retidas** (`_Voice(held=True)`) até a busca decidir (+`MEMORY_GRACE_S` 0,3 s) |
| Fala por frase (1.24) | `magi/core/early.py` `EarlySpeech`; `graph._Voice`, `_call` | cada frase que fecha no streaming vai ao TTS; 1ª abre o envio (`play` → `_go(SPEAKING)` → `speaker.say_stream`), as outras entram na fila; `_deliver` completa com `missing()` |
| Frase de espera do modelo (1.24) | `persona.md` linha "Ferramenta demorada…"; `_Voice.interim` / `EarlySpeech.mark_interim` | texto antes de uma `tool_call` é falado e marcado como de espera (`INTERIM_MAX = 2`, fora do limite de 2 frases) |
| "Várias partes" | `persona.md`: "responda já a que sabe e busque o resto" | **já é um lote**, mas cai na cota de 2 frases de espera e é tratado como espera |
| STT em streaming (1.25) | `magi/core/stt.py` `SttStream` | existe, **desligado** (ganho de ~70 ms) |
| Cache de voz | `magi/core/tts.py` `PhraseSpeaker`, `phrases.yaml` (`fixed`/`lazy`/`templates`) | frase conhecida toca do disco, sem rede |
| Limite da fala | `magi/core/compose.py` `SPEECH_MAX_SENTENCES = 2` | resposta final ≤ 2 frases; o resto vai à legenda |
| Ferramentas | `GraphAgent._tools_node` | roda as `tool_calls` de uma volta **em série** (`for … await tool.run`) |
| Rosto pensando | `hud/wired/portrait.py` `thinking()`, `_think_look`, `THINK_CYCLE`/`THINK_STEP` 1,3 s/`THINK_TILT`/`PONDER_AFTER` 1 s, `_think_k`; `mood()` → `focus`; `mouth_id` → C1 | um ciclo único de 6 olhares + cabeça inclinada, igual do 1º ao 10º segundo |
| Chip | `hud/turn_phase.py` `TurnPhase`; `main_screen.chip_label`/`CHIP_STATES` | `Thinking · 思考中` até o 1º som (ou `AUDIO_WAIT_S` 1 s); `speaking` depois, mesmo no silêncio entre frases |
| Ponte | `hud/hud_bridge.py` `_MIN_DECODERS`; `magi/common/events.py` `decode_hud` | um decodificador por `t`; tipo desconhecido é recusado |

## 2. O que falta

1. **HUD não sabe nada além de `thinking`**: nem há quanto tempo, nem se roda ferramenta, nem se
   está entre lotes. → mensagem nova `ThinkMsg` (spec §1) e etapas no retrato (§4).
2. **Nada soa antes do 1º token do modelo** (~1,7–2,2 s após o fim da fala, + TTS). → frase local
   logo após a transcrição (§3).
3. **Lote é tratado como espera** (cota 2, mesmo limite) e a legenda final só tem a resposta
   final. → classe "lote" no `EarlySpeech` (§5).
4. **Ferramentas em série**: com 2 ferramentas, a 2ª espera a 1ª. → `asyncio.gather` (§5).
5. **Chip** volta a `Speaking` entre lotes. → `TurnPhase` ouve `ThinkMsg` (§4).

## 3. Frase de espera (núcleo)

Módulo novo **`magi/core/espera.py`** (puro, sem I/O):
- `EsperaCfg.from_raw(raw)` lê `[espera]` (spec §5).
- `Catalogo.load(path)` lê **`magi/core/espera.yaml`** (tópicos → frases e moldes, spec §3).
- `topico(texto, ctx) -> str` por palavras-chave (sem acento, prefixo de palavra) + jogo em foco.
- `Cota` guarda as últimas frases e quantos turnos seguidos tiveram frase (R3.6), por satélite.
- `escolher(texto, ctx, cota, rng) -> str | None` devolve a frase já preenchida ou `None`.
- `mesma_espera(frase) -> bool` (R3.4): a frase do modelo é só "espera vazia"?
- `honesta(frase) -> list[str]` (R4): violações do linter (spec §4); usada no teste do catálogo.

Ligação no turno (`TurnMachine._think`), sem mexer no `TurnPipeline.respond`:
1. Depois do `transcribe`, se `transcript` não é vazio/dispensa/resposta a confirmação velha:
   `rota = self.pipeline.peek_route(text, ctx)` (novo, sem efeito: `route` + `_settle`).
2. Se `rota.kind is AGENT`, `cfg.frase` e `early` existe: cria a tarefa `espera` que dorme
   `frase_apos_ms` e, se `not early.started`, chama `early.say_wait(frase)`.
3. A tarefa é cancelada no `finally` do `_think` e no `_cancel_work` (R6).
4. `say_wait` abre o envio como `say` (mesmo `play`), entra em `early.waits` (fora de todas as
   cotas), e manda `ThinkMsg("wait")` ao HUD pelo gancho de §4.

O caminho do modelo segue igual; o `_Voice` só pergunta `early.drop_wait_echo(frase)` antes de
falar a 1ª frase marcada como espera (R3.4). Frases do catálogo entram em `phrases.yaml` `lazy`
(fixas) e `templates` (moldes com `{jogo}`), então o teste que confere `SAY_*` ganha uma checagem
de que todo o catálogo é cacheável (R3.1).

## 4. Rosto e chip (HUD)

Gancho do núcleo: `THINK_HUD: ContextVar[Callable[[ThinkMsg], None] | None]` em
`magi/core/early.py`, aberto pelo `_think` junto do `EARLY_SPEECH` (manda via `self.hud.send` numa
tarefa, como `_captions`). O `GraphAgent._tools_node` chama `notify_tool(nome)` antes de cada
ferramenta; o `_Voice` chama `notify_lote(n)` quando um lote fecha (§5).

Ponte: `ThinkMsg` → `events.decode_hud` → `hud_bridge._MIN_DECODERS["think"]` → sinal `think` →
`gamerhud.on_bridge_think` → `TurnPhase.on_think(...)` (chip) e `WiredUI.set_think(...)` →
`PartsPortrait.set_think(kind, tool, now)`.

Módulo novo **`hud/wired/pensando.py`** (puro, sem Qt): `pose(desde_s, tool, lote, tem) -> Pose`
com `eyes` (ciclo da etapa), `dx/dy`, `tilt`, `efeitos`, `corpo`, `look` (painel) — tabela na spec
§2. O retrato só troca `_think_look` e o `tilt` por essa `Pose`, e desenha o efeito novo `dots`
(reticências animadas, em código, mesma família de `notes`/`zz` no `_reaction_effect`).
`desde_s` conta do 1º `thinking` do turno; `lote` faz voltar à etapa **pensando** sem passar pelo
**hm**. Contrato das reações não muda; a pose de pensar continua vencendo as reações (o retrato já
só reage em repouso).

Chip: `TurnPhase.on_think(kind, tool, now)` guarda o rótulo da ferramenta e, em `lote`, volta a
fase mostrada para `thinking` até o próximo nível de boca/`speech`. `chip_label` usa
`snap.chip_tool` quando a fase é `thinking` (spec §2.4).

## 5. Lotes (agente)

`EarlySpeech` passa a ter três classes de frase falada: **espera** (`waits`, do catálogo),
**interina** (`interim`, de hoje: texto antes de ferramenta na 1ª volta) e **lote** (`lotes`: texto
antes de ferramenta numa volta que já tem resultado de ferramenta **e** responde algo — decidido
pelo `_Voice` com `lote=True` quando `steps ≥ 2`, ou quando o texto passa de 1 frase na 1ª volta).
Limites na spec §5. `finish(rest)` continua igual; `missing()` também tira lotes. `full_text()`
devolve lotes + resposta final para o `_deliver` montar `SubtitleMsg.full` (R5.4).

Prompt (`magi/agent/persona.md`, linha da "Ferramenta demorada"): pedido de várias partes →
"responda em até 2 frases a parte que já tem e chame a ferramenta da próxima; depois, não repita o
que já disse". Só muda com o acordo da E2.1 (D3).

`_tools_node`: `asyncio.gather` das ferramentas da volta; se alguma pedir confirmação, devolve
`pending` da **primeira na ordem pedida** e cancela as outras ainda rodando (R5.5); a ordem das
mensagens `tool` fica a do pedido.

## 6. Riscos

| Risco | Mitigação |
| --- | --- |
| Frase de espera vira tique ou soa falsa | cota R3.6, catálogo do Conselho, linter R4, veto do Pedro (D4), validação de 1 semana (E4.1) |
| Duas esperas seguidas ("Hm, deixa eu pensar. Deixa eu ver…") | `drop_wait_echo` (R3.4); o modelo segue livre para espera **com conteúdo** |
| Frase toca e a resposta é instantânea ("Oito.") | limiar de 700 ms só conta depois da transcrição; se o 1º token chegar antes, `early.started` barra |
| `peek_route` diverge do `respond` | mesma função (`route` + `_settle`) e teste que compara os dois |
| Lotes estouram a fala | tetos da spec §5 + D3; `lotes = false` volta ao de hoje |
| Ferramentas em paralelo brigam (ex.: duas no Spotify) | `paralelo = false` por ferramenta (`Tool.serial`) para as de mídia/PC; padrão paralelo só em leitura (search, news, steam, game_help, self_info) |
| Conflito de arquivos entre tarefas | `turn.py`/`early.py` só nas tarefas em série (E2.3 → E3.1); HUD em pacote próprio (`pensando.py`) |
| CPU do HUD | `dots` em código simples; a 60 fps já roda durante o `thinking` hoje |
