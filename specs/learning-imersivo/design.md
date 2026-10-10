# Design — Learning imersivo (entrevista pela vaga)

Implementa [requirements.md](requirements.md). Seções citadas por `§`. Base: `specs/learning-mode/`
(LM design/spec) e o código de LM1.8/LM1.9 (`magi/learning/topic.py`, `wiring.py`, `persona.py`,
`hud/wired/learning_topic.py`).

## 1. Onde mora hoje

```
HUD: chip TOPIC ▾ (learning_topic.TopicPicker) ──lm_topic──▶ wiring._on_topic ──▶ TopicBuilder.build
                                                                         │ (sem LLM, sem rede)
                                     session.set_topic(ctx) ◀── TopicContext(block ≤ 1500) ◀┘
turno (voz ou lm_say) ──▶ persona.install: compose(base, block(), <topic_context>) ──▶ GraphAgent
wiring._schedule_opening ──▶ 1 turno interno "open this topic…" quando o estado volta a listening
```
- `Topic.INTERVIEW` = `prompts/topics/interview.md` com `{role}` (`interview_role` ou `DEFAULT_ROLE`).
- `LearningModel.complete(system, user, schema) -> (dict, custo)` (LM3.1) já existe, com orçamento,
  `FakeModel` e erros `ModelError` (`timeout|budget|model|invalid`).
- O campo de texto é `QLineEdit` de uma linha (`gamerhud.make_learning_entry`, `LM_SAY_MAX = 2000`).
- O socket aceita linha de até 64 KiB nos dois lados (LM design §9 nota LM0.2).

## 2. Princípio: o tema `interview` ganha uma vaga; o resto não muda

Nada de `Topic` novo. A entrevista com vaga é `Topic.INTERVIEW` **mais** uma `InterviewRun` ativa na
sessão. Sem run, `interview` é o genérico de hoje (R8). Isso mantém o enum, a coluna
`learning_sessions.topic`, os intents `learning.topic.*` e o seletor como estão.

O bloco `<topic_context>` da entrevista passa a ser **regerado a cada turno** a partir do estado da
run (perfil compacto + etapa atual + o que já foi perguntado), sempre ≤ 1500 caracteres. O texto
bruto da vaga nunca vai ao prompt de conversa (R7.2).

## 3. Pacote novo `magi/learning/interview/`

| Módulo | Papel | Dono (tarefa) |
| --- | --- | --- |
| `contracts.py` | `JobPost`, `JobProfile`, `Stage`, `InterviewPlan`, `InterviewRun`, `Coverage`, `InterviewDebrief`, enums | LI0.1 |
| `jobtext.py` | normalizar texto colado (quebras, bullets, cortes), hash, recusa curta/longa (R1.5); puro | LI0.1 |
| `extract.py` | `async extract(post, model) -> JobProfile` (1 chamada, schema spec §2); prompt `prompts/interview/extract.md` | LI1.1 |
| `plan.py` | `build_plan(profile, minutes) -> InterviewPlan`; puro, sem LLM (spec §4) | LI1.2 |
| `run.py` | máquina da simulação: etapa, contagem, relógio injetado, comandos (spec §5); `block(run) -> str` | LI1.3 |
| `debrief.py` | `async debrief(run, messages, observations, model) -> InterviewDebrief` (spec §6) | LI2.3 |
| `store.py` | gravação de vagas/runs/retornos no `LearningRepo` (Postgres + JSONL) | LI0.2 |
| `prompts/interview/{extract,conduct,debrief}.md` | textos dos três prompts | LI1.1 / LI1.3 / LI2.3 |

`wiring.py` só ganha handlers novos (`lm_job`, `lm_interview`) na tabela `_handlers` (regra do
próprio módulo) e o gancho por turno; `persona.py` não muda (a run fornece o `topic()`).

**Paralelismo:** LI0.1 cria todos os módulos com assinaturas finais e corpo stub (`raise
NotImplementedError` ou retorno vazio), mais os `Fake*` de teste. Cada tarefa depois só edita o
próprio módulo + o próprio teste.

## 4. Fluxo: da vaga à primeira pergunta

1. HUD: `[ PASTE JOB ]` (seletor ou chip) → `QClipboard.text()` → `jobtext.check` local (vazio/curto)
   → `lm_job {"text","source":"clipboard"}`. Arquivo: `lm_job {"file"}` (o núcleo lê o arquivo, D2).
   Voz (D1): intent `learning.interview.job` → núcleo manda `lm_job_req` → HUD responde `lm_job`.
2. Núcleo (`wiring._on_job`): `jobtext.normalize` → hash → `lm_interview {"state":"preparing"}`.
   Se o hash já tem perfil (R2.6), pula o passo 3.
3. `extract.extract(post, model)` (tarefa `learning_job`, D8) → `JobProfile`. Erro → `lm_interview
   {"state":"error","error":code}` (botão retry na tela reenvia o mesmo `job_id`).
4. `plan.build_plan(profile, cfg.interview_minutes)` → `InterviewPlan`.
5. `store` grava `learning_jobs` + `learning_interviews`; `session.set_topic(TopicContext(INTERVIEW,
   label="INTERVIEW // <CARGO>", block=run.block()))`; `lm_topic` + `lm_interview {"state":"ready"}`.
6. Abertura (P11 do LM): `_schedule_opening` com o prompt interno da etapa 1.

## 5. Fluxo de um turno da simulação

1. Antes do turno: `persona.install(topic=...)` chama `wiring._topic_block()`, que com run ativa
   devolve `run.block(now)` (spec §5.2) em vez do `TopicContext.block` fixo.
2. Turno normal (voz ou `lm_say`); a persona do Learning continua valendo (R3.5).
3. Depois do turno (`on_turn`/`_say`, já existe para gravar mensagens): `run.observe(pedro, condessa,
   now)` → conta pergunta (a fala da Condessa termina com `?` ou contém `?`), conta resposta do Pedro,
   avança etapa por cota ou tempo (spec §5.1). Mudou algo → `lm_interview` (etapa/contagem) e grava.
4. Comandos (R3.4) entram antes do turno: intents `learning.interview.*` (voz) e o botão; o texto
   digitado "next question" também casa (mesmas frases, `run.command_of(text)`), sem LLM.
5. Última etapa fechada ou "end" → §6.

## 6. Retorno

`wiring._finish_interview(reason)`: congela a run (`state = debriefing`), manda `lm_interview`,
roda `debrief.debrief(...)` em tarefa própria (não segura o turno), grava, publica `lm_debrief` e uma
`lm_msg` curta da Condessa (R4.2). As observações de inglês vêm de `repo.observations(session_id)`
filtradas pelo intervalo de mensagens da run — nenhuma chamada nova (R4.3). Depois do retorno a run
fecha e o tema volta a `interview` genérico com o perfil ainda como contexto? **Não**: volta a
`free` (o Pedro escolhe de novo), para a Condessa não continuar entrevistando.

## 7. HUD

| Peça | Arquivo | O que muda |
| --- | --- | --- |
| Seletor | `hud/wired/learning_topic.py` | linha Tech interview ganha sublinhas: `[ PASTE JOB ]` e até 3 vagas recentes (de `lm_session.jobs`) |
| Clipboard | `hud/gamerhud.py` | `learning_paste_job()` lê `QApplication.clipboard().text()`; responde `lm_job_req`; intercepta colagem longa no `QLineEdit` (R1.2) |
| Chip + etapa | `hud/wired/learning_interview.py` (novo, puro + pintura) | `InterviewView` (estado do `lm_interview`), chip `INTERVIEW // CARGO · EMPRESA`, linha `STAGE 3/6 · …  12:40`, `[ END INTERVIEW ]`, painel do perfil |
| Retorno | `hud/wired/learning_debrief.py` (novo) | painel no lugar do drawer de observações; rolável; fecha em `✕`/Esc |
| Modelo | `hud/wired/learning_model.py` | guarda `interview`, `debrief`, `jobs` vindos do núcleo |
| Ponte | `hud/hud_bridge.py` | decodificadores `lm_interview`, `lm_debrief`, `lm_job_req`; `send_lm("lm_job", …)` aceita até `JOB_MAX` |
| Tela | `hud/wired/learning_screen.py` | grupos `interview` e `debrief` (chave/pintura delegadas aos módulos novos) |

A interceptação da colagem longa (R1.2): `QLineEdit` não tem `insertFromMimeData` (é do
`QTextEdit`) e achata as quebras de linha; o caminho é um `eventFilter` no campo que pega
`QKeySequence.Paste`, olha o clipboard antes de deixar colar e, se for longo/multilinha, mostra a
pergunta do rodapé (menu de contexto do campo desligado na view learning). Se o eventFilter não pegar o Ctrl+V no Wayland, R1.2 cai para
"só o botão" (anotar em *Sobras*).

## 8. Persistência

Migração aditiva `magi/memory/migrations/004_learning_jobs.sql` (spec §8): `learning_jobs`,
`learning_interviews`. JSONL: `~/.local/share/magi/learning/jobs.jsonl` e linhas `interview` no
arquivo da sessão. O `LearningRepo` (Protocol) ganha métodos; `JsonlRepo` e `PostgresRepo`
implementam. Nada de `DROP`/`down` (LM-010).

## 9. Temas de roleplay (D5 — proposta, só com "ok")

Se aprovado: `Topic.ROLEPLAY` novo (o único tema novo), com cenários em
`magi/learning/prompts/scenarios/*.md` (cabeçalho `title`/`role`/`setting`/`goal`/`twist` + texto),
lidos pelo `TopicBuilder` sem LLM; o seletor ganha a linha "Roleplay ▸" com os cenários; voz
"let's roleplay a hotel check-in". Sem roteiro de etapas nem retorno (conversa, LM-013 regra 9 vale).

## 10. Riscos

| Risco | Mitigação |
| --- | --- |
| Persona ("short turns, no jargon") briga com entrevista técnica | `conduct.md` diz explicitamente que dentro da simulação jargão técnico da vaga é esperado; a regra de não corrigir continua |
| Contagem de perguntas por `?` erra (pergunta retórica, duas perguntas num turno) | cota é teto, não meta; tempo da etapa também avança; comando "next" sempre funciona |
| Bloco > 1500 com stack grande | `run.block` corta por prioridade (etapa atual > requisitos da etapa > resto do perfil), teste de tamanho |
| Extração inventa requisito | schema exige `evidence` (trecho literal da vaga) por item; item sem trecho achado no texto é descartado (`extract` confere) |
| Clipboard vazio/imagem | HUD recusa local com linha curta; nada vai ao núcleo |
| Linha do socket > 64 KiB | `JOB_MAX = 12000` caracteres no HUD **e** no núcleo (≤ ~48 KiB em UTF-8 + JSON) |
| Mexer no `gamerhud` em uso | só na view learning; `tests/hud` antes e depois |
