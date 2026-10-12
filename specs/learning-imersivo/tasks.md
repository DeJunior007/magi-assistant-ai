# Tarefas — Learning imersivo (entrevista pela vaga)

Implementa [design.md](design.md), [spec.md](spec.md) e [requirements.md](requirements.md). Cada
tarefa é feita por **um agente** com janela de **até 128k tokens** (teto duro). Várias rodam em
paralelo (campo *Paralelo*); o orquestrador (Pedro ou a sessão principal do Claude Code) só lança
uma tarefa quando todas as de *Depende de* estão no `main`.

## Regras para o agente

1. **Leia só o pacote da tarefa** (campo *Lê*). Design por `§`, spec por `spec §`, requisitos por
   `R`/`D`, SDD original por `LM spec §`/`LM design §` (`specs/learning-mode/`).
2. **Orçamento planejado ≤ 50k tokens**; o resto da janela de 128k é margem. Perto de 90k: pare,
   faça commit do que está verde e anote o que faltou no fim desta lista (seção *Sobras*).
3. **Contratos primeiro:** use `magi/learning/interview/contracts.py` e as assinaturas dos stubs do
   LI0.1; não leia o código de outras tarefas além do que o *Lê* manda.
4. **Só os arquivos do campo *Escreve*.** Precisou de outro? Pare e anote em *Sobras*.
5. **Arquivos grandes por trecho** (`grep -n` + leitura por intervalo): nunca leia inteiros
   `hud/gamerhud.py`, `hud/wired/learning_screen.py`, `magi/learning/wiring.py`,
   `magi/learning/repo.py`, `magi/common/contracts.py`, `magi/common/events.py`.
6. **Testes curtos:** `uv run pytest -q -x tests/learning/<arquivo>` (ou `tests/hud/…`) e
   `uv run ruff check <seus arquivos>`. Relógio sempre injetado; nada de `sleep` real.
7. **Nada ao vivo nos testes:** nenhuma chamada de LLM (só `FakeModel`), nenhum clipboard real
   (clipboard falso injetado), nenhum Postgres real fora dos testes que já usam o fixture do LM,
   nada de rede. Nunca `docker compose down`/`DROP` no `magi-pg` (LM-010).
8. **Uma tarefa = um commit** com o ID (`LI1.2: roteiro da entrevista`), na branch `imersivo/<ID>`;
   merge no `main` pelo orquestrador.
9. **Decisões D1–D8 resolvidas em 2026-10-10** (`specs/DECISOES-2026-10-10.md`, vale acima do
   requirements): D1/D4/D6/D7/D8 padrão; **D2** só clipboard (LI3.1 removida); **D3** notas 0–100
   por aspecto no retorno; **D5** roleplay com 4 cenários (LI4.1/LI4.2). LIF.1 é do Pedro.

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~3,5k,
`design.md` ~3k, `spec.md` ~5k, `topic.py` ~2,5k, `persona.py` ~1k, `model.py` ~3,5k,
`learning_topic.py` ~4k, `wiring.py` ~7,5k (ler por trecho).

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
LI0.1 ─┬─ LI0.2 ─────────┐
       ├─ LI1.1 ─────────┼─ LI1.4 ─┬─ LI2.3 ─┐
       ├─ LI1.2 ─ LI1.3 ─┘         │         │
       ├─ LI2.1 ───────────────────┼─────────┼─ LI2.5 ── LIF.1 (Pedro)
       ├─ LI2.2 ─ LI2.4 ───────────┼─────────┘
       └─ LI4.1 (roleplay: tema e dados) ─┴─ LI4.2 (roleplay: tela e ligação; depois de LI1.4 e LI2.1)
       (LI3.1 removida — D2)
```

---

## Fase LI0 — Contratos e banco

- [x] **LI0.1 Contratos, texto da vaga e esqueleto** — pacote `magi/learning/interview/` com
  `contracts.py` completo (spec §2, `to_dict`/`from_dict`, validações), `jobtext.py` completo (spec §1:
  `normalize`, `job_id`, `check` → recusa/corte), **stubs** com assinatura final de `extract.py`,
  `plan.py`, `run.py`, `debrief.py`, `store.py` (docstring com a tarefa dona), pasta
  `prompts/interview/` com os 3 arquivos vazios marcados `TODO <tarefa>`. Contratos do retorno já
  com as notas 0–100 por aspecto (D3: `Aspect`, `AspectScore`, `InterviewDebrief.scores`). Mensagens
  do socket da spec §7 como dataclasses em `magi/common/contracts.py` (`LmJobMsg`, `LmJobReqMsg`,
  `LmInterviewMsg`, `LmDebriefMsg`, opcionais novos do `LmSessionMsg` — `jobs`, `debrief_unseen`,
  `scenarios` — e o opcional `scenario` do `LmTopicMsg`, spec §12) e decodificadores em
  `magi/common/events.py` (`_HUD_DECODERS`) e `hud/hud_bridge.py` (`_MIN_DECODERS`, `JOB_MAX`).
  Config `interview_minutes` em `magi/learning/config.py` e `config.example.toml` (sem `jobs_dir`, D2). *(R1.5, R5.1)*
  - Lê: spec §1, §2, §7, §9; design §2–§3; `magi/learning/contracts.py` linhas 1–120 e a classe `TopicContext`; `grep -n "class LmTopicMsg\|class LmSessionMsg" -A30 magi/common/contracts.py`; `grep -n "lm_topic\|_HUD_DECODERS" magi/common/events.py hud/hud_bridge.py` e só esses trechos; `magi/learning/config.py`
  - Escreve: `magi/learning/interview/*.py`, `magi/learning/prompts/interview/*.md`, `magi/common/contracts.py` (só as classes novas e os opcionais do `LmSessionMsg`), `magi/common/events.py`, `hud/hud_bridge.py` (só decodificadores e `JOB_MAX`), `magi/learning/config.py`, `config.example.toml`, `tests/learning/test_interview_contracts.py`, `tests/learning/test_jobtext.py`
  - Depende de: —
  - Orçamento: ~45k
  - Pronto: CA-01; ida-e-volta JSON de todos os contratos (inclui `scores`); `decode_hud` aceita as 4 mensagens e recusa `lm_job` > 12 000; testes antigos de `tests/learning` (em especial `test_socket.py`, `test_bridge.py`, `test_contracts.py`) e `tests/hud/test_bridge.py` verdes.
  - Paralelo: —

- [x] **LI0.2 Banco e repositório** — migração `magi/memory/migrations/004_learning_jobs.sql` (spec
  §8, aditiva, `IF NOT EXISTS`), métodos novos no `LearningRepo` (Protocol), `PostgresRepo` e
  `JsonlRepo`; `store.py` como fachada fina (`save_post`, `profile_of(job_id)`, `recent(n)`,
  `save_run`, `load_active(session_id)`, `save_debrief`, `unseen`). *(R2.6, R5)*
  - Lê: spec §8, §2 (só `JobPost`, `InterviewRun`, `InterviewDebrief`); `magi/memory/migrations/003_learning.sql`; `magi/learning/repo.py` por trecho: `grep -n "class \|async def " ` e os corpos de `set_topic`/`save_summary` nos dois backends; `magi/learning/interview/contracts.py`
  - Escreve: `magi/memory/migrations/004_learning_jobs.sql`, `magi/learning/repo.py` (só métodos novos), `magi/learning/interview/store.py`, `tests/learning/test_interview_store.py`
  - Depende de: LI0.1
  - Orçamento: ~45k
  - Pronto: os dois backends passam o mesmo teste parametrizado (vaga → perfil → run → retorno → `unseen` → `mark_seen`); migração aplicada no fixture do LM sem tocar nas tabelas 003.
  - Paralelo: LI1.1, LI1.2, LI2.1, LI2.2

## Fase LI1 — Núcleo da entrevista

- [x] **LI1.1 Extração do perfil** — `extract.extract(post, model) -> JobProfile` com o prompt
  `prompts/interview/extract.md` (spec §3), schema da spec §2, pós-checagem de `evidence`/stack/
  senioridade, prazo de 20 s; `build_job_model(config)` que escolhe `[tasks] learning_job` ou cai em
  `learning_actions` (D8) usando o `build_model` existente. *(R2.2, R2.5, R7.1)*
  - Lê: spec §1–§3, `magi/learning/model.py` (protocolo, `ModelError`, `FakeModel`, `build_model`), `magi/learning/config.py` (`LearningTask`, `learning_tasks`), `magi/learning/interview/contracts.py`
  - Escreve: `magi/learning/interview/extract.py`, `magi/learning/prompts/interview/extract.md`, `magi/learning/config.py` (só a tarefa `learning_job`), `tests/learning/test_interview_extract.py`, `tests/learning/fixtures/vagas/*.txt` (3 vagas de exemplo escritas pelo agente, sem dados reais)
  - Depende de: LI0.1
  - Orçamento: ~40k
  - Pronto: CA-02; vaga em português gera `requirements.text` em inglês no `FakeModel` gravado; erro de cada `code` vira `ModelError` certo.
  - Paralelo: LI0.2, LI1.2, LI2.1, LI2.2

- [x] **LI1.2 Roteiro** — `plan.build_plan(profile, minutes)` pura, tabela da spec §4 (entradas
  condicionais, INTERN/JUNIOR, sem stack, ajuste da soma de minutos). *(R2.3)*
  - Lê: spec §2 (`JobProfile`, `Stage`, `InterviewPlan`), §4; `magi/learning/interview/contracts.py`
  - Escreve: `magi/learning/interview/plan.py`, `tests/learning/test_interview_plan.py`
  - Depende de: LI0.1
  - Orçamento: ~20k
  - Pronto: CA-03; um teste por linha da tabela §4.
  - Paralelo: LI0.2, LI1.1, LI2.1, LI2.2

- [x] **LI1.3 Condução (máquina e bloco)** — `run.py`: `start(plan, profile, session_id, now)`,
  `observe`, avanço por cota/tempo, pausa, `command_of`/`apply(cmd)`, `finish(reason)`,
  `block(now)` ≤ 1500 com corte por prioridade (spec §5); `prompts/interview/conduct.md` (spec §3,
  R3.1–R3.6, R7.1). *(R3)*
  - Lê: spec §2, §3 (conduct), §5; design §5; `magi/learning/prompts/persona.md`; `magi/learning/topic.py` linhas 1–80 (`clip`, `BLOCK_MAX`); `magi/learning/interview/contracts.py`, `plan.py` (só assinatura)
  - Escreve: `magi/learning/interview/run.py`, `magi/learning/prompts/interview/conduct.md`, `tests/learning/test_interview_run.py`
  - Depende de: LI1.2
  - Orçamento: ~45k
  - Pronto: CA-04 (relógio falso, 30 min); frases PT/EN da §5.3 casam e "how am I doing?" não; `asked_log` impede repetição no bloco.
  - Paralelo: LI0.2, LI1.1, LI2.x

- [x] **LI1.4 Ligação ao núcleo** — no `LearningWiring`: handlers `lm_job` e `lm_interview` (cmd)
  na tabela `_handlers`; fluxo do design §4 (preparing ≤ 100 ms, extração em tarefa, reuso por hash,
  `set_topic` com rótulo, `lm_interview` ready, abertura P11 com a etapa 1); `_topic_block()` que
  devolve `run.block(now)` com run ativa (o `persona.install(topic=…)` passa a usá-lo); depois de
  cada turno `run.observe` + `lm_interview` + gravação; troca de tema → `PAUSED`; retomada da run na
  sessão retomada (R5.3); `lm_session.jobs`; voz: intents `learning.interview.job|last|next|skip|pause|end`
  em `magi/core/intents.yaml` (só com sessão ativa, como os `learning.topic.*`) e o `lm_job_req` (D1).
  O fim (`end`/WRAP) chama um gancho `_finish_interview` que por ora só fecha a run e volta a `free`
  (o retorno é LI2.3). *(R1.4, R2, R3, R5.3, R8)*
  - Lê: design §4–§6; spec §5.3, §7, §10; `magi/learning/wiring.py` por trecho (cabeçalho 1–40, `_handlers`, `set_topic`, `_restore_topic`, `_schedule_opening`/`_open_topic_now`, `_say`, `on_turn`); `magi/learning/intent_action.py`; `magi/core/intents.yaml` linhas 640–720; assinaturas de `extract.py`, `plan.py`, `run.py`, `store.py`
  - Escreve: `magi/learning/wiring.py`, `magi/learning/intent_action.py`, `magi/core/intents.yaml`, `magi/core/phrases.yaml` (respostas curtas novas, ver Sobras do LM1.8), `tests/learning/test_interview_wiring.py`
  - Depende de: LI0.2, LI1.1, LI1.3
  - Orçamento: ~50k
  - Pronto: CA-05 com `FakeModel` e repo JSONL temporário; turno falso avança etapa; comando `end` volta a `free`; testes antigos de `tests/learning/test_topic.py`, `test_session.py`, `test_learning_intents.py`, `test_conversation.py` e `tests/core/test_tts.py` verdes.
  - Paralelo: LI2.1, LI2.2, LI2.4

## Fase LI2 — Tela e retorno

- [x] **LI2.1 Mandar a vaga pelo HUD** — `[ PASTE JOB ]` e até 3 vagas recentes como sublinhas da
  linha Tech interview no `TopicPicker` (lógica pura + pintura; `lm_session.jobs`); no `gamerhud`:
  `learning_paste_job()` (clipboard injetável, recusa local de vazio/curto, `send_lm("lm_job")`),
  resposta ao `lm_job_req`, `eventFilter` de colagem longa no `QLineEdit` com a pergunta do rodapé
  (R1.2; se o Ctrl+V não chegar no Wayland, anotar em *Sobras* e ficar só o botão). *(R1.1–R1.4)*
  - Lê: design §7; spec §1 (`PASTE_ASK`), §7; `hud/wired/learning_topic.py`; `hud/gamerhud.py` por trecho (`grep -n "learning_entry\|learning_submit\|make_learning_entry\|on_bridge_learning\|send_lm"` e só esses métodos); `hud/hud_bridge.py` linhas 160–260
  - Escreve: `hud/wired/learning_topic.py`, `hud/gamerhud.py` (só os métodos citados e os novos), `tests/hud/test_learning_job_paste.py`
  - Depende de: LI0.1
  - Orçamento: ~50k
  - Pronto: CA-07 (parte do envio) com clipboard falso; seletor antigo continua passando em `tests/learning/test_topic_view.py`; captura offscreen da lista com as sublinhas.
  - Paralelo: LI0.2, LI1.x, LI2.2

- [x] **LI2.2 Chip, etapa e painel do perfil** — `hud/wired/learning_interview.py` (novo): estado
  `InterviewView` alimentado por `lm_interview`, `chip_parts`, linha `STAGE n/N · LABEL  mm:ss`,
  `[ END INTERVIEW ]` (manda `lm_interview {"cmd":"end"}`), estados `preparing` (barra animada como a
  do balão) e `error` com `retry` (`lm_job {"job_id"}`); painel do perfil (stack + must) aberto pelo
  chip. `learning_model.py` guarda `interview`; `learning_screen.py` ganha o grupo `interview` que
  delega a pintura. *(R6, R2.1, R2.5)*
  - Lê: design §7; spec §7; `hud/wired/learning_topic.py` (padrão de módulo puro + pintura); `hud/wired/learning_screen.py` por trecho (`groups`, `group_key`, `draw_group`, `_g_header`, `_topic_*`, `mouse`); `hud/wired/learning_model.py` por trecho (`on_lm_topic`/dispatcher)
  - Escreve: `hud/wired/learning_interview.py`, `hud/wired/learning_model.py`, `hud/wired/learning_screen.py` (só o grupo `interview` e o clique), `tests/hud/test_learning_interview_view.py`
  - Depende de: LI0.1
  - Orçamento: ~50k
  - Pronto: CA-07 (parte da tela) com `lm_interview` falsos em todos os estados; captura offscreen em 2560×1440; `tests/learning/test_learning_screen.py` verde.
  - Paralelo: LI0.2, LI1.x, LI2.1

- [x] **LI2.3 Retorno no núcleo** — `debrief.debrief(run, messages, observations, model)` (spec §6,
  prompt `prompts/interview/debrief.md`, prazo 40 s, idioma por D7), com **notas 0–100 por aspecto**
  (D3: fluência, gramática, vocabulário, aderência à vaga, clareza; pós-checagem da spec §6 — preso
  em 0..100, aspecto desconhecido cai, sem nota geral); no wiring, `_finish_interview`
  passa a gerar o retorno em tarefa própria, gravar, publicar `lm_debrief` + `lm_msg` curta (falada
  se `speak_replies`), regra das < 3 respostas, fim de sessão `idle`/`shutdown` grava sem publicar,
  `lm_session.debrief_unseen` e reenvio na abertura. *(R4, R5.2)*
  - Lê: spec §6, §7, §10; requirements R4; `magi/learning/interview/contracts.py`, `store.py` (assinaturas); `magi/learning/wiring.py` por trecho (`_finish_interview`, `set_mode`, `_session_msg`, `_say`); `magi/learning/summary.py` (padrão de tarefa pós-fechamento)
  - Escreve: `magi/learning/interview/debrief.py`, `magi/learning/prompts/interview/debrief.md`, `magi/learning/wiring.py` (só `_finish_interview` e a abertura com retorno pendente), `tests/learning/test_interview_debrief.py`
  - Depende de: LI1.4
  - Orçamento: ~45k
  - Pronto: CA-06 (inclui as notas); turno do agente não espera o retorno (teste com modelo falso lento); `shutdown` grava e não publica.
  - Paralelo: LI2.4

- [x] **LI2.4 Painel do retorno no HUD** — `hud/wired/learning_debrief.py` (novo, puro + pintura):
  cobertura por requisito (✓ / ~ / ✗ com a evidência em `TEXT_DIM`), fortes, a melhorar, respostas
  reescritas, inglês; rolagem; fecha em `✕`/Esc/clique fora; ocupa o lugar do drawer de observações
  enquanto aberto. No topo, as **notas 0–100 por aspecto** (D3): uma linha por aspecto
  (`FLUENCY  72` + barra fina + a `note` em `TEXT_DIM`), aspecto ausente mostra `—`; sem nota geral.
  `learning_model.py` guarda `debrief`; grupo `debrief` na `learning_screen.py`. *(R6, R4.3)*
  - Lê: spec §2 (`InterviewDebrief`), §7; `hud/wired/learning_screen.py` por trecho (`_g_obs`, `obs_groups`, `mouse`, `key`); `hud/wired/learning_obs.py` por trecho (geometria do drawer); `hud/wired/learning_interview.py` (assinaturas, LI2.2)
  - Escreve: `hud/wired/learning_debrief.py`, `hud/wired/learning_model.py` (só `debrief`), `hud/wired/learning_screen.py` (só o grupo `debrief`), `tests/hud/test_learning_debrief_view.py`
  - Depende de: LI2.2
  - Orçamento: ~45k
  - Pronto: pinta com `lm_debrief` falso cheio (5 notas), com notas faltando e vazio (offscreen 2560×1440); Esc fecha; drawer de observações volta igual.
  - Paralelo: LI1.4, LI2.3

- [x] **LI2.5 Integração tela ↔ núcleo** — orquestrador ou agente: liga as pontas que caíram em
  *Sobras* das LI2.x (sinais do `hud_bridge` para `lm_interview`/`lm_debrief`/`lm_job_req` no
  `gamerhud`, prazos no `caption_tick`), roda `tests/learning`, `tests/hud`, `tests/core` inteiros.
  - Lê: *Sobras* desta lista; `hud/gamerhud.py` por trecho (`on_bridge_learning`, `caption_tick`)
  - Escreve: `hud/gamerhud.py`, `hud/hud_bridge.py` (só o `_dispatch` das mensagens novas);
    acrescentados pelo orquestrador: `hud/wired/learning_screen.py`, `magi/core/service.py`,
    `tests/hud/test_learning_core_flow.py`, `tests/learning/test_conversation.py`
  - Depende de: LI2.1, LI2.3, LI2.4
  - Orçamento: ~35k
  - Pronto: as três suítes verdes; fluxo vaga → ready → `end` → painel do retorno com núcleo falso no teste de integração do LM.
  - Paralelo: —

## Fase LI3 — Arquivo de vagas (removida)

- [—] **LI3.1 Pasta de vagas** — **REMOVIDA em 2026-10-10 (D2):** o Pedro decidiu sem pasta de vagas,
  só clipboard (botão `[ PASTE JOB ]`, colar no campo, voz via `lm_job_req`) e as vagas já usadas
  (`lm_job {"job_id"}`). Nada de `jobs_dir`, `jobfiles.py` nem `lm_job {"file"}`. Não implementar.

## Fase LI4 — Roleplay (D5 aprovada: 4 cenários)

- [x] **LI4.1 Roleplay: tema e dados** — `Topic.ROLEPLAY` (+ rótulo em `TOPIC_LABELS`) em
  `magi/learning/contracts.py`; `magi/learning/roleplay.py` (novo, puro: `Scenario`, `load`,
  `scenarios`, `SCENARIOS_DIR`, spec §12); os 4 cenários em `magi/learning/prompts/scenarios/`
  (`hotel_checkin.md`, `ordering_food.md`, `doctor_visit.md`, `support_call.md`, escritos pelo
  agente em inglês simples, nível B1–B2, cada um com um `twist`); `prompts/topics/roleplay.md`;
  `TopicBuilder.build(requested, scenario=None)` com o ramo `_roleplay(scenario)` sem LLM (id
  desconhecido → `free` + `detail "unknown scenario"`). Standup, salário e meetup ficam para depois.
  *(D5, design §9)*
  - Lê: design §9; spec §12; LM spec §10.1; `magi/learning/topic.py`; `magi/learning/contracts.py` por trecho (`class Topic`, `TOPIC_LABELS`, `TopicContext`)
  - Escreve: `magi/learning/contracts.py` (só `Topic.ROLEPLAY` e o rótulo), `magi/learning/roleplay.py`, `magi/learning/prompts/scenarios/*.md`, `magi/learning/prompts/topics/roleplay.md`, `magi/learning/topic.py`, `tests/learning/test_roleplay.py`
  - Depende de: LI0.1 (o `scenario` do `lm_topic` e o `scenarios` do `lm_session` já estão nos contratos)
  - Orçamento: ~35k
  - Pronto: CA-09 (parte do núcleo): os 4 arquivos carregam e validam; bloco ≤ 1500 em todos; id desconhecido/ausente → `free`; `tests/learning/test_topic.py`, `test_contracts.py` e `test_topic_view.py` verdes (o enum novo não quebra o seletor antigo; se quebrar, anotar em *Sobras* para a LI4.2).
  - Paralelo: LI0.2, LI1.x, LI2.x (não escreve nenhum arquivo delas)

- [x] **LI4.2 Roleplay: tela e ligação** — no `wiring`, `_on_topic` passa `msg.scenario` ao
  `TopicBuilder`, `lm_session.scenarios` vem de `roleplay.scenarios()`, e a sessão retomada volta ao
  mesmo cenário (gravar o id com o tema sem coluna nova; sem id → `free`); intent de voz
  `learning.topic.roleplay` ("let's roleplay a hotel check-in" / "vamos simular um check-in no
  hotel", um sinônimo por cenário) só com sessão ativa; no seletor, linha "Roleplay ▸" com os 4
  cenários como sublinhas (mesmo padrão das sublinhas de vaga da LI2.1), clique manda
  `lm_topic {"topic":"roleplay","scenario"}`; chip `ROLEPLAY // <TITLE>`. *(D5, design §9)*
  - Lê: design §9; spec §7, §12; `magi/learning/roleplay.py` (assinaturas); `magi/learning/wiring.py` por trecho (`_on_topic`, `_session_msg`, `_restore_topic`); `magi/learning/intent_action.py`; `magi/core/intents.yaml` linhas 670–760; `hud/wired/learning_topic.py`
  - Escreve: `magi/learning/wiring.py` (só `_on_topic`, `_session_msg`, `_restore_topic`), `magi/learning/intent_action.py`, `magi/core/intents.yaml` (só o intent novo), `hud/wired/learning_topic.py`, `tests/learning/test_roleplay_wiring.py`, `tests/hud/test_roleplay_picker.py`
  - Depende de: LI4.1, LI1.4 (mesmos arquivos do núcleo), LI2.1 (mesmo `learning_topic.py`)
  - Orçamento: ~40k
  - Pronto: CA-09 completo; voz e clique abrem o cenário; captura offscreen do seletor com as sublinhas; `tests/learning` e `tests/hud` verdes.
  - Paralelo: LI2.4, LI2.5 (não LI2.3: as duas escrevem `magi/learning/wiring.py`)

## Fechamento

- [ ] **LIF.1 Ponta a ponta com o Pedro** — **é do Pedro; agente não implementa** *(gasta API)*. 3 vagas reais
  (backend, full-stack, dados): critérios de sucesso 1–5 do requirements; conferir o perfil à mão,
  uma simulação de 30 min inteira por voz e uma por texto, o retorno (notas 0–100 por aspecto fazem
  sentido?), um roleplay, o custo no `costs`. O que
  incomodar vira item em *Sobras* ou volta ao Pedro.
  - Lê: requirements (Critérios), spec §11
  - Escreve: `docs/perf/learning-imersivo.md`
  - Depende de: LI2.5 (e LI4.2 para provar um roleplay; LI3.1 removida, D2)
  - Orçamento: ~25k
  - Pronto: relatório com os 5 critérios e a nota do Pedro.
  - Paralelo: —

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)

- **LI0.1 (2026-10-11):** assinaturas que ganharam argumento além da spec — `plan.build_plan(profile,
  minutes=30, *, job_id)` (o `InterviewPlan` precisa do id), `run.start(…, *, run_id)`; extras nos
  stubs: `run.tick(run, now)` (avanço por tempo sem turno), `run.progress(run, now)` (campos do
  `lm_interview`), `store.set_profile`/`store.post_of`. `jobtext.check(raw) -> Checked(text, ok,
  trimmed, line)` e `jobtext.is_long_paste` (R1.2) para o HUD. `LmInterviewMsg.seniority` é texto.
  Nenhum `Fake*` novo: o `FakeModel` do LM basta; o clipboard falso fica com a LI2.1.
- **LI0.1:** `tests/learning/test_summary_card.py::test_nao_cobre_retrato_nem_player` falha no
  `main` antes desta tarefa (o grupo `mood_tip` da V1.8 é pintado depois do `lm_summary`) e
  `ruff check` acusa E501 em `hud/konsole_term.py:395` — nenhum dos dois é do learning-imersivo.
- **LI1.2 (2026-10-11):** `tests/learning/test_interview_contracts.py::test_stubs_have_final_signatures`
  espera `NotImplementedError("LI1.2")` do `plan.build_plan` e fica vermelho com o roteiro pronto
  (fora do Escreve): tirar as linhas 146–147 (o mesmo vale para `run.command_of` quando a LI1.3
  entrar). Escolhas sem spec: CANDIDATE_QS e WRAP com `followups = 0`; rótulos `SYSTEM DESIGN` e
  `CANDIDATE QUESTIONS`; `minutes` < nº de etapas → `ValueError`; EXPERIENCE com piso de 1 min (o
  excesso sai da maior etapa).
- **LI4.1 (2026-10-11):** `TopicBuilder(…, scenarios_dir=None)` (dir injetável) e
  `topic.NO_SCENARIO`; `TOPIC_LABELS[ROLEPLAY] = "ROLEPLAY"` (o efetivo vem no `label`). Para a
  LI4.2: `hud/wired/learning_topic.py` `LABELS` não tem `roleplay` (só quebra se o `lm_topic` vier sem
  `label`); `[learning] default_topic = "roleplay"` passa na validação do config e cai em `free`
  (sem cenário). `test_interview_contracts.py::test_stubs_have_final_signatures` falha porque uma
  tarefa paralela (LI1.x) já implementou um stub — não é do LI4.1.
- **LI1.1 (2026-10-11):** `LearningCostTask` (`magi/learning/budget.py`, fora do pacote) não tem
  rótulo `learning_job`: `build_job_model` monta a tarefa escolhida (job ou actions) no lugar de
  `learning_actions` e o custo da extração sai como `learning_actions` em `costs`; sem `timeout_s`
  explícito o prazo passa a 20 s (o das ações é 8 s). `learning_tasks().job` novo (opcional).
  `tests/learning/test_interview_contracts.py::test_stubs_have_final_signatures` exige `TODO` em
  `prompts/interview/extract.md` (e `NotImplementedError` no `plan`, hoje quebrado pela LI1.2): o
  teste do stub precisa ser afrouxado por quem for dono dele (não é do pacote da LI1.1).
  `config.example.toml` sem `[tasks.learning_job]` (D8 cai em `learning_actions`).
- **LI2.1 (2026-10-11):** as vagas recentes só aparecem no seletor quando a tela passar o número
  delas: `learning_screen._topic_list` deve chamar `tp.list_rect(…, n_jobs=len(self.topic_picker.jobs))`
  (uma linha, fora do Escreve da LI2.1 — fica para LI2.5); sem isso só o `[ PASTE JOB ]` aparece
  (já funciona: `on_job` ligado pelo `gamerhud.learning_entry_sync`). A pergunta da colagem longa
  (R1.2) é responder por teclado (Enter/Y = YES, Esc/N = NO, outra tecla desiste): os botões
  `[ YES ] [ NO ]` clicáveis no rodapé pedem a `learning_screen`. O Ctrl+V pelo `eventFilter` foi
  provado só no offscreen; conferir no Wayland real (LIF.1). Recusa local no HUD é
  `learning_topic.job_check` (não normaliza; o núcleo normaliza com `jobtext`).
- **LI2.2 (2026-10-11):** a faixa da entrevista (`learning_interview.strip_rect`, 60 px) cobre o
  topo de `L.history` com fundo opaco (o `learning_layout` não reserva espaço; mensagens antigas
  ficam por baixo) — se incomodar, reservar `STRIP_H` no layout durante a simulação. Para a LI2.5:
  `caption_tick` deve somar `self.wired.learning.interview_deadline(now)` (barra do `preparing` a
  5 q/s e virada do segundo do relógio em `running`); o `hud_bridge` precisa entregar
  `lm_interview` ao `LearningModel.feed` (o modelo ignora o eco `{"cmd"}`). Esc fecha o painel
  (uma linha no `key` da tela). `tests/learning/test_learning_screen.py::GROUPS` ganhou
  `"interview"` (fora do *Escreve*, inevitável com o grupo novo; a LI2.4 fará o mesmo com
  `debrief`). Envio por `LearningScreen.send_core(t, fields, log)` (reutilizável pela LI2.4).
- **LI2.4 (2026-10-11):** o painel abre sozinho uma vez por retorno novo (identidade `run_id` +
  `at`) e o modelo guarda o último `lm_debrief` até chegar outro (sobrevive à sessão nova, R5.2).
  Para a LI2.5: o `hud_bridge` precisa entregar `lm_debrief` ao `LearningModel.feed`; não há
  `mark_seen` do HUD → núcleo (o painel não avisa que foi visto) nem botão para reabrir o retorno
  depois de fechado. `tests/learning/test_learning_screen.py::GROUPS` ganhou `"debrief"` (fora do
  *Escreve*, como na LI2.2). Rótulo do aspecto `job_fit` no painel: `JOB FIT`; seção da língua:
  `ENGLISH`; a `closing` não aparece (é a fala).
- **LI1.4 (2026-10-11):** fora do *Escreve*: `IntentId.LEARNING_INTERVIEW_*` (6 linhas em
  `magi/common/contracts.py`, o roteador recusa id fora do enum) e as 8 respostas curtas novas em
  `magi/core/i18n/en-gb.yaml`. O `core.service` não passa `job_model`: o `install` monta
  `build_job_model(config, budget=engine.budget)` (só funciona com provedor `fake`, falta o
  `registry=core.providers`) e senão cai no `engine.model` de ações (prazo interno de 8 s) — ligar
  `install(…, job_model=build_job_model(config, budget=…, registry=core.providers))` no
  `service.py` (LI2.5). `run_id` = `IV-AAAAMMDD-<segundos do dia + 1>` (sem contador no repo).
  `lm_session.jobs` só se atualiza ao reabrir o modo. "pula essa" ficou só no texto (empata com
  `music.next` no roteador). Comandos de voz `next|skip|pause|end` só com run viva (`_gate`);
  `job|last` só com sessão. `next`/`skip_stage` (voz, texto, botão) disparam um turno interno
  (`INTERVIEW_NEXT_PROMPT`); comando digitado não vai ao agente. `lm_job` em `PREPARING` responde
  `lm_interview {"state":"preparing","error":"still preparing the last one"}`; texto curto do
  núcleo vai como `state = error` com a linha do `jobtext`. Sessão retomada após reinício conta o
  tempo parado como tempo da etapa (pode avançar no 1º `tick`). Fechar a sessão com run viva só
  fecha e grava (`_close_run`); o retorno em segundo plano é da LI2.3.
- **LI2.3 (2026-10-12):** `debrief.debrief(…, *, explain_language="en")` (kw novo, D7: `en` →
  inglês simples; `pt-br` → textos em português simples, evidência e reescritas em inglês). Sem
  `job_model` → linha `feedback not generated — model`. Depois do retorno (ou da falha) a run passa
  de `DEBRIEFING` a `DONE` e sai um `lm_interview` final. O núcleo marca o retorno como visto ao
  mandar o `lm_debrief` (o HUD não avisa). O repo não tem busca `run_id → título/empresa/fim`: o
  retorno pendente depois de reiniciar o núcleo sai com `title = "MOCK INTERVIEW"`, sem empresa e
  `at` = hora da abertura (no mesmo processo usa um cache em memória) — falta
  `repo.interview_of(run_id)` + `store` (fora do *Escreve*). Fechar a sessão por botão/voz com
  ≥ 3 respostas também gera em segundo plano sem publicar (como `idle`/`shutdown`). Retry do
  retorno no painel (spec §10) não existe (LI2.5/HUD). Fora do trecho listado do wiring: `aclose`
  ganhou `await self.wait_idle()` depois de `_close_run("shutdown")` e `_close_run` agenda o
  retorno (pedido nas *Sobras* da LI1.4). `test_interview_contracts.py::test_stubs_have_final_signatures`
  atualizado (fora do *Escreve*, pedido do orquestrador): confere `debrief.debrief`/`MIN_ANSWERS`
  e o prompt pronto no lugar do `TODO`.
- **LI2.5 (2026-10-12):** o `hud_bridge` já entregava todo `lm_*` (inclusive `lm_interview`/
  `lm_debrief`) ao `LearningModel.feed` antes do sinal — nada mudou nele. `gamerhud`: `caption_tick`
  soma `interview_deadline(now)` e `lm_interview` chama o `caption_tick` (agenda a barra/relógio);
  `learning_paste_answer(yes)` serve tecla e clique. `learning_screen`: `list_rect(…, n_jobs)` e
  `paste_buttons()` (`[ YES ]`/`[ NO ]` clicáveis no rodapé, `on_paste_answer`). `service.py`:
  um `LearningBudget` só para engine e `job_model` (`build_job_model(…, registry=core.providers)`).
  Falta: retry do retorno no painel (spec §10) pede comando novo no núcleo (ex.:
  `lm_interview {"cmd":"debrief"}` + enum do contrato e `wiring.py`, ocupado pela LI4.2); Esc com a
  lista de temas aberta (sessão nova) fecha a lista antes do painel do retorno. `tests/learning`
  tinha 13 falhas de `wiring._scenario_list` (`pipeline` `None`) vindas da LI4.2 em andamento.
- **LI4.2 (2026-10-12):** o id do cenário fica **só em memória** (`LearningWiring._scenario_of`,
  por sessão): a sessão só é retomada depois de o núcleo reiniciar (fechar pelo botão/voz encerra),
  então hoje a retomada de um roleplay cai em `free` + `detail "unknown scenario"`. Para gravar sem
  coluna nova: `repo.set_topic(…, scenario=None)` pondo `"scenario"` na entrada de `topics` (jsonl,
  memória e Postgres; dedup por tema + cenário), `SessionInfo.scenario` lido da última entrada e
  `session.set_topic` repassando — fora do *Escreve* (`repo.py`, `session.py`). Fora do *Escreve*
  (inevitáveis): `IntentId.LEARNING_TOPIC_ROLEPLAY` em `magi/common/contracts.py`, 2 respostas em
  `magi/core/i18n/en-gb.yaml`, a ligação `topic_picker.on_scenario` em `hud/gamerhud.py`
  (`learning_entry_sync`, ao lado do `on_job`) e um teste em `tests/hud/test_learning_job_paste.py`;
  `set_topic(…, *, scenario=None)` e o `__init__` do wiring ganharam linhas. O cenário vai no slot
  constante `text` das frases (sem `SlotName` novo). O seletor sempre reserva 4 sublinhas de
  cenário (`SCENARIOS_MAX`, a geometria não depende da tela); a linha "Roleplay ▸" não manda nada.
  O `lm_topic` de confirmação não traz `scenario` (o chip usa o `label`).
