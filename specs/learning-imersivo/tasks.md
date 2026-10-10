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
9. **Decisão em aberto** (requirements, D1–D8): use o padrão; tarefa marcada "precisa do Pedro" só
   roda depois do "ok" registrado aqui.

Estimativa: 1k tokens ≈ 3,5 KB de português ou 4 KB de código. Tamanhos: `requirements.md` ~3,5k,
`design.md` ~3k, `spec.md` ~5k, `topic.py` ~2,5k, `persona.py` ~1k, `model.py` ~3,5k,
`learning_topic.py` ~4k, `wiring.py` ~7,5k (ler por trecho).

Formato: **Lê** · **Escreve** · **Depende de** · **Orçamento** · **Pronto** · **Paralelo**.

## Grafo

```
LI0.1 ─┬─ LI0.2 ─────────┐
       ├─ LI1.1 ─────────┼─ LI1.4 ─┬─ LI2.3 ─┐
       ├─ LI1.2 ─ LI1.3 ─┘         └─ LI3.1 (D2) ··········┐
       ├─ LI2.1 ─────────────────────────────┼─ LI2.5 ─────┴─ LIF.1
       └─ LI2.2 ─ LI2.4 ─────────────────────┘
       (LI4.1 roleplay: bloqueada até D5)
```

---

## Fase LI0 — Contratos e banco

- [ ] **LI0.1 Contratos, texto da vaga e esqueleto** — pacote `magi/learning/interview/` com
  `contracts.py` completo (spec §2, `to_dict`/`from_dict`, validações), `jobtext.py` completo (spec §1:
  `normalize`, `job_id`, `check` → recusa/corte), **stubs** com assinatura final de `extract.py`,
  `plan.py`, `run.py`, `debrief.py`, `store.py` (docstring com a tarefa dona), pasta
  `prompts/interview/` com os 3 arquivos vazios marcados `TODO <tarefa>`. Mensagens do socket da
  spec §7 como dataclasses em `magi/common/contracts.py` (`LmJobMsg`, `LmJobReqMsg`,
  `LmInterviewMsg`, `LmDebriefMsg`, opcionais novos do `LmSessionMsg`) e decodificadores em
  `magi/common/events.py` (`_HUD_DECODERS`) e `hud/hud_bridge.py` (`_MIN_DECODERS`, `JOB_MAX`).
  Config `interview_minutes`/`jobs_dir` em `magi/learning/config.py` e `config.example.toml`. *(R1.5, R5.1)*
  - Lê: spec §1, §2, §7, §9; design §2–§3; `magi/learning/contracts.py` linhas 1–120 e a classe `TopicContext`; `grep -n "class LmTopicMsg\|class LmSessionMsg" -A30 magi/common/contracts.py`; `grep -n "lm_topic\|_HUD_DECODERS" magi/common/events.py hud/hud_bridge.py` e só esses trechos; `magi/learning/config.py`
  - Escreve: `magi/learning/interview/*.py`, `magi/learning/prompts/interview/*.md`, `magi/common/contracts.py` (só as classes novas e os opcionais do `LmSessionMsg`), `magi/common/events.py`, `hud/hud_bridge.py` (só decodificadores e `JOB_MAX`), `magi/learning/config.py`, `config.example.toml`, `tests/learning/test_interview_contracts.py`, `tests/learning/test_jobtext.py`
  - Depende de: —
  - Orçamento: ~45k
  - Pronto: CA-01; ida-e-volta JSON de todos os contratos; `decode_hud` aceita as 4 mensagens e recusa `lm_job` > 12 000; testes antigos de `tests/learning` (em especial `test_socket.py`, `test_bridge.py`, `test_contracts.py`) e `tests/hud/test_bridge.py` verdes.
  - Paralelo: —

- [ ] **LI0.2 Banco e repositório** — migração `magi/memory/migrations/004_learning_jobs.sql` (spec
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

- [ ] **LI1.1 Extração do perfil** — `extract.extract(post, model) -> JobProfile` com o prompt
  `prompts/interview/extract.md` (spec §3), schema da spec §2, pós-checagem de `evidence`/stack/
  senioridade, prazo de 20 s; `build_job_model(config)` que escolhe `[tasks] learning_job` ou cai em
  `learning_actions` (D8) usando o `build_model` existente. *(R2.2, R2.5, R7.1)*
  - Lê: spec §1–§3, `magi/learning/model.py` (protocolo, `ModelError`, `FakeModel`, `build_model`), `magi/learning/config.py` (`LearningTask`, `learning_tasks`), `magi/learning/interview/contracts.py`
  - Escreve: `magi/learning/interview/extract.py`, `magi/learning/prompts/interview/extract.md`, `magi/learning/config.py` (só a tarefa `learning_job`), `tests/learning/test_interview_extract.py`, `tests/learning/fixtures/vagas/*.txt` (3 vagas de exemplo escritas pelo agente, sem dados reais)
  - Depende de: LI0.1
  - Orçamento: ~40k
  - Pronto: CA-02; vaga em português gera `requirements.text` em inglês no `FakeModel` gravado; erro de cada `code` vira `ModelError` certo.
  - Paralelo: LI0.2, LI1.2, LI2.1, LI2.2

- [ ] **LI1.2 Roteiro** — `plan.build_plan(profile, minutes)` pura, tabela da spec §4 (entradas
  condicionais, INTERN/JUNIOR, sem stack, ajuste da soma de minutos). *(R2.3)*
  - Lê: spec §2 (`JobProfile`, `Stage`, `InterviewPlan`), §4; `magi/learning/interview/contracts.py`
  - Escreve: `magi/learning/interview/plan.py`, `tests/learning/test_interview_plan.py`
  - Depende de: LI0.1
  - Orçamento: ~20k
  - Pronto: CA-03; um teste por linha da tabela §4.
  - Paralelo: LI0.2, LI1.1, LI2.1, LI2.2

- [ ] **LI1.3 Condução (máquina e bloco)** — `run.py`: `start(plan, profile, session_id, now)`,
  `observe`, avanço por cota/tempo, pausa, `command_of`/`apply(cmd)`, `finish(reason)`,
  `block(now)` ≤ 1500 com corte por prioridade (spec §5); `prompts/interview/conduct.md` (spec §3,
  R3.1–R3.6, R7.1). *(R3)*
  - Lê: spec §2, §3 (conduct), §5; design §5; `magi/learning/prompts/persona.md`; `magi/learning/topic.py` linhas 1–80 (`clip`, `BLOCK_MAX`); `magi/learning/interview/contracts.py`, `plan.py` (só assinatura)
  - Escreve: `magi/learning/interview/run.py`, `magi/learning/prompts/interview/conduct.md`, `tests/learning/test_interview_run.py`
  - Depende de: LI1.2
  - Orçamento: ~45k
  - Pronto: CA-04 (relógio falso, 30 min); frases PT/EN da §5.3 casam e "how am I doing?" não; `asked_log` impede repetição no bloco.
  - Paralelo: LI0.2, LI1.1, LI2.x

- [ ] **LI1.4 Ligação ao núcleo** — no `LearningWiring`: handlers `lm_job` e `lm_interview` (cmd)
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

- [ ] **LI2.1 Mandar a vaga pelo HUD** — `[ PASTE JOB ]` e até 3 vagas recentes como sublinhas da
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

- [ ] **LI2.2 Chip, etapa e painel do perfil** — `hud/wired/learning_interview.py` (novo): estado
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

- [ ] **LI2.3 Retorno no núcleo** — `debrief.debrief(run, messages, observations, model)` (spec §6,
  prompt `prompts/interview/debrief.md`, prazo 40 s, idioma por D7); no wiring, `_finish_interview`
  passa a gerar o retorno em tarefa própria, gravar, publicar `lm_debrief` + `lm_msg` curta (falada
  se `speak_replies`), regra das < 3 respostas, fim de sessão `idle`/`shutdown` grava sem publicar,
  `lm_session.debrief_unseen` e reenvio na abertura. *(R4, R5.2)*
  - Lê: spec §6, §7, §10; requirements R4; `magi/learning/interview/contracts.py`, `store.py` (assinaturas); `magi/learning/wiring.py` por trecho (`_finish_interview`, `set_mode`, `_session_msg`, `_say`); `magi/learning/summary.py` (padrão de tarefa pós-fechamento)
  - Escreve: `magi/learning/interview/debrief.py`, `magi/learning/prompts/interview/debrief.md`, `magi/learning/wiring.py` (só `_finish_interview` e a abertura com retorno pendente), `tests/learning/test_interview_debrief.py`
  - Depende de: LI1.4
  - Orçamento: ~45k
  - Pronto: CA-06; turno do agente não espera o retorno (teste com modelo falso lento); `shutdown` grava e não publica.
  - Paralelo: LI3.1

- [ ] **LI2.4 Painel do retorno no HUD** — `hud/wired/learning_debrief.py` (novo, puro + pintura):
  cobertura por requisito (✓ / ~ / ✗ com a evidência em `TEXT_DIM`), fortes, a melhorar, respostas
  reescritas, inglês; rolagem; fecha em `✕`/Esc/clique fora; ocupa o lugar do drawer de observações
  enquanto aberto. `learning_model.py` guarda `debrief`; grupo `debrief` na `learning_screen.py`. *(R6, R4.3)*
  - Lê: spec §2 (`InterviewDebrief`), §7; `hud/wired/learning_screen.py` por trecho (`_g_obs`, `obs_groups`, `mouse`, `key`); `hud/wired/learning_obs.py` por trecho (geometria do drawer); `hud/wired/learning_interview.py` (assinaturas, LI2.2)
  - Escreve: `hud/wired/learning_debrief.py`, `hud/wired/learning_model.py` (só `debrief`), `hud/wired/learning_screen.py` (só o grupo `debrief`), `tests/hud/test_learning_debrief_view.py`
  - Depende de: LI2.2
  - Orçamento: ~45k
  - Pronto: pinta com `lm_debrief` falso cheio e vazio (offscreen 2560×1440); Esc fecha; drawer de observações volta igual.
  - Paralelo: LI1.4, LI2.3

- [ ] **LI2.5 Integração tela ↔ núcleo** — orquestrador ou agente: liga as pontas que caíram em
  *Sobras* das LI2.x (sinais do `hud_bridge` para `lm_interview`/`lm_debrief`/`lm_job_req` no
  `gamerhud`, prazos no `caption_tick`), roda `tests/learning`, `tests/hud`, `tests/core` inteiros.
  - Lê: *Sobras* desta lista; `hud/gamerhud.py` por trecho (`on_bridge_learning`, `caption_tick`)
  - Escreve: `hud/gamerhud.py`, `hud/hud_bridge.py` (só o `_dispatch` das mensagens novas)
  - Depende de: LI2.1, LI2.3, LI2.4
  - Orçamento: ~35k
  - Pronto: as três suítes verdes; fluxo vaga → ready → `end` → painel do retorno com núcleo falso no teste de integração do LM.
  - Paralelo: —

## Fase LI3 — Arquivo de vagas

- [ ] **LI3.1 Pasta de vagas** — **precisa do Pedro (D2).** O núcleo lista `jobs_dir` (`.txt`/`.md`,
  mais novos primeiro, ≤ 20, ≤ 64 KB cada) e junta com as vagas já usadas em `lm_session.jobs`;
  `lm_job {"file"}` lê só arquivos dentro de `jobs_dir` (caminho resolvido, sem `..`/symlink para
  fora). Sem pasta → nada muda.
  - Lê: requirements R1.3, D2; spec §7, §9; `magi/learning/interview/store.py`; `magi/learning/wiring.py` por trecho (`_on_job`, `_session_msg`)
  - Escreve: `magi/learning/interview/jobfiles.py`, `magi/learning/wiring.py` (só a origem `file`), `tests/learning/test_interview_jobfiles.py`
  - Depende de: LI1.4
  - Orçamento: ~25k
  - Pronto: teste com pasta temporária (arquivo fora da pasta recusado; arquivo grande recusado; ordem por mtime).
  - Paralelo: LI2.3

## Fase LI4 — Roleplay (proposta)

- [ ] **LI4.1 Tema Roleplay** — **bloqueada até D5 (precisa do Pedro).** Design §9: `Topic.ROLEPLAY`,
  cenários em `magi/learning/prompts/scenarios/*.md` (os escolhidos pelo Pedro), `TopicBuilder`
  lendo o cenário sem LLM, linha "Roleplay ▸" no seletor com os cenários, intents de voz. Sem
  roteiro nem retorno. Dividir em núcleo / HUD se passar de 50k na estimativa feita no "ok".
  - Lê: design §9; LM spec §10.1; `magi/learning/topic.py`; `hud/wired/learning_topic.py`
  - Escreve: definido no "ok"
  - Depende de: LI0.1 e D5
  - Orçamento: ~45k (núcleo) + ~35k (HUD)
  - Pronto: definido no "ok"
  - Paralelo: qualquer LI2.x

## Fechamento

- [ ] **LIF.1 Ponta a ponta com o Pedro** — **precisa do Pedro** *(gasta API)*. 3 vagas reais
  (backend, full-stack, dados): critérios de sucesso 1–5 do requirements; conferir o perfil à mão,
  uma simulação de 30 min inteira por voz e uma por texto, o retorno, o custo no `costs`. O que
  incomodar vira item em *Sobras* ou volta ao Pedro.
  - Lê: requirements (Critérios), spec §11
  - Escreve: `docs/perf/learning-imersivo.md`
  - Depende de: LI2.5 (e LI3.1 se D2 aprovada)
  - Orçamento: ~25k
  - Pronto: relatório com os 5 critérios e a nota do Pedro.
  - Paralelo: —

## Sobras

(agentes anotam aqui o que faltou no pacote ou ficou para depois)
