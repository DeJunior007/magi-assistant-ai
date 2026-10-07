# Spec — Condessa Learning Mode

Comportamento, contratos/schemas, casos de borda e critérios de aceite. Implementa
[requirements.md](requirements.md) segundo o [design.md](design.md). Seções citadas por `spec §`.
Todo valor marcado *(config)* fica em `[learning]` do `~/.config/magi/config.toml`, com o padrão
dado. Itens marcados **FUTURE** estão aqui só para o contrato não fechar a porta; não são
implementados no MVP.

## 1. IDs

| Objeto | Formato | Exemplo |
| --- | --- | --- |
| Sessão | `LS-` + `AAAAMMDD` + `-` + n do dia | `LS-20261007-01` |
| Mensagem | bigint do banco; na UI, `m` + n na sessão | `m3` |
| Ação | `ACT-` + uuid curto (8 hex) | `ACT-1f9a02c4` |
| Observação | bigint do banco | |
| Requisitos | IDs do PDF (`SEL-001`…) e `LM-nnn` | |
| Critério de aceite | `CA-nn` (§12) | `CA-07` |

## 2. Config

```toml
[learning]
enabled = true
level = "B2"                    # UI-002, P3 (manual no MVP)
track = "CONVERSATION"
explain_language = "en"         # "en" | "pt-br"  (LM-008, P5)
translate_to = "pt-br"          # TRA-001
speak_replies = true            # LM-004: a Condessa fala a resposta
idle_end_min = 20               # P9
observe = true                  # liga o background (Fase 4)
observe_daily_max = 200         # chamadas de observação por dia (LM-006)
storage = "postgres"            # "postgres" | "jsonl" (P4)

[tasks]
learning_actions = { provider = "openai", model = "gpt-5.4-mini", reasoning_effort = "none", timeout_s = 8 }
learning_observe = { provider = "openai", model = "gpt-5.4-mini", reasoning_effort = "none", timeout_s = 20 }
# futuro (P2): learning_observe = { provider = "ollama", model = "qwen2.5:7b-instruct" }
```

## 3. Contratos (`magi/learning/contracts.py`)

```python
class Author(StrEnum):   YOU = "you"; CONDESSA = "condessa"
class Source(StrEnum):   VOICE = "voice"; TEXT = "text"
class ActionKind(StrEnum): IMPROVE = "improve"; EXPLAIN = "explain"; TRANSLATE = "translate"; VOCABULARY = "vocabulary"
                           # ASK = "ask"  -> FUTURE (ASK-001)
class ObsCategory(StrEnum): VOCABULARY = "vocabulary"; GRAMMAR = "grammar"; RECURRING = "recurring"

@dataclass(frozen=True)
class LearningMessage:
    id: int; session_id: str; author: Author; source: Source
    text: str                 # o que aparece e é selecionável (heard p/ voz do Pedro)
    at: datetime

@dataclass(frozen=True)
class Selection:
    message_id: int; start: int; end: int   # [start, end) em caracteres de text
    text: str                               # = message.text[start:end], validado

@dataclass(frozen=True)
class ActionRequest:
    id: str; kind: ActionKind; selection: Selection
    context: list[LearningMessage]          # a mensagem + até 2 anteriores

@dataclass(frozen=True)
class ActionResult:
    id: str; kind: ActionKind; ok: bool
    data: dict | None                       # schema por kind (§5)
    error: str | None                       # "timeout" | "budget" | "model" | "invalid"
    cached: bool; ms: int; cost_usd: float

@dataclass(frozen=True)
class Observation:
    id: int | None; session_id: str; message_id: int
    category: ObsCategory
    rule_key: str             # estável, ex. "grammar.past_simple.irregular" (MEM-002)
    label: str                # o que a UI mostra: "Past tense", "repository"
    span: str | None          # trecho de origem
    suggestion: str | None
```

`LearningModel` (protocolo): `async def complete(self, system: str, user: str, schema: dict) ->
tuple[dict, float]` (dados, custo). Implementações: `OpenAIModel` (providers atuais), `FakeModel`
(testes), `OllamaModel` (FUTURE/P2).

## 4. Conversa (CNV-*, LM-001..LM-004)

1. Voz: ao fim de `TurnPipeline.respond`, **depois** de entregar a resposta ao TTS/HUD, o núcleo
   grava e publica duas `LearningMessage`: Pedro (`text = transcript.heard`, `source = voice`) e
   Condessa (`text = result.speech`).
2. Texto: `lm_say` → `Transcript.raw(text)` → `respond` (sem STT, sem wake). Mensagem do Pedro com
   `source = text`. Texto vazio ou > 2000 caracteres é recusado na UI.
3. `speak_replies = false` → a resposta não vai ao TTS; vai só `lm_msg`.
4. Persona: com sessão ativa, o system prompt do agente ganha o bloco de `prompts/persona.md`:
   inglês britânico natural, perguntas abertas sobre o que o Pedro contou, **nunca** apontar erro
   nem dizer "you should say"/"the correct form is"; pode usar a forma correta naturalmente na
   resposta (recast). Pedido explícito do Pedro ("is that correct?") pode ser respondido.
5. Mensagem da Condessa em fala: `lm_msg` com `speaking = true`; a UI revela por `speech`/`dur`
   (lógica de `speech_caption.py`). No `state` seguinte diferente de `speaking`, mostra inteira.

## 5. Ações (SEL-*, IMP-*, EXP-*, TRA-*, VOC-*)

### Disponibilidade no menu

| Ação | Mensagem do Pedro | Mensagem da Condessa | Tamanho do trecho |
| --- | --- | --- | --- |
| Improve | sim | desabilitada (P7) | 1+ palavra; contexto = frase inteira |
| Explain | sim | sim | qualquer |
| Translate | sim | sim | qualquer (até 400 caracteres) |
| Vocabulary | sim | sim | 1 a 4 palavras; acima, desabilitada |

Seleção é normalizada para palavras inteiras (expande até o limite de palavra mais próximo) e
recortada à mensagem de início. Seleção só de espaços/pontuação não abre menu.

### Schemas de saída (`data`)

**improve** (IMP-001..003)
```json
{"original": "yesterday I make a new authentication system",
 "improved": "yesterday I built a new authentication system",
 "kind": "both",
 "why": "\"Built\" sounds more natural when talking about something you created. Past tense: yesterday → built."}
```
`kind ∈ {grammar, naturalness, both, none}`; `none` ⇒ `improved == original` e `why` diz que está
bom. `why` ≤ 240 caracteres. O balão mostra `YOUR SENTENCE:` / `MORE NATURAL:` / `WHY?` (mockup) e
uma etiqueta `GRAMMAR` / `NATURALNESS`.

**explain** (EXP-001)
```json
{"question": "Why \"built\" instead of \"made\"?",
 "answer": "Both are possible. For software, \"built\" is generally more natural because it emphasizes creating or developing a system."}
```
`answer` de 1 a 4 frases, ≤ 400 caracteres.

**translate** (TRA-001)
```json
{"translation": "eu fiz", "note": "Here 'make' should be past: 'made/built'."}
```
`note` opcional, só para trecho ≤ 3 palavras, ≤ 100 caracteres; para frase, `note = null`.

**vocabulary** (VOC-001, VOC-002)
```json
{"term": "authentication", "meaning": "the process of proving who a user is",
 "in_context": "the login system you built", "pos": "noun", "cefr": "B2",
 "examples": ["We added two-factor authentication."], "synonyms": ["verification"]}
```
Balão: `term · pos · CEFR` + `meaning` + `in_context`; `examples`/`synonyms` atrás de "more ▸".
`examples` 1–3, `synonyms` 0–4.

### Prompts

Cada analisador tem `prompts/<kind>.md`. O texto das mensagens entra **só** dentro de um bloco
delimitado `<conversation>` como dado; o prompt avisa que mensagens `source = voice` são
transcrição (ignorar pontuação/maiúsculas) e que o objetivo é preservar a intenção (IMP-003).
Saída sempre JSON no schema; parser rejeita campo extra obrigatório faltando → `invalid`.

### Ciclo de uma ação

`lm_action` → resultado em cache? devolve (`cached = true`) → senão orçamento ok? → fila de ações
→ `LearningModel` (timeout *(config)*) → valida schema → grava `learning_action_results` →
`lm_result`. Falha: 1 nova tentativa só em `invalid`; `timeout`/`model`/`budget` voltam direto
com `ok = false` (LM-007). Nova `lm_action` do mesmo cliente cancela a anterior ainda na fila.

## 6. Mensagens do socket (`lm_*`)

| Tipo | Direção | Campos |
| --- | --- | --- |
| `lm_hello` | UI → núcleo | `{}` — a conexão se identifica como Learning; só ela recebe `lm_*` |
| `lm_mode` | ambos | `{"on": bool}` — UI pede; núcleo confirma |
| `lm_session` | núcleo → UI | `{"id","started_at","level","track","n_msgs","obs_count"}` |
| `lm_say` | UI → núcleo | `{"text"}` |
| `lm_msg` | núcleo → UI | `{"id","author","source","text","at","speaking"}` |
| `lm_action` | UI → núcleo | `{"id","kind","message_id","start","end"}` |
| `lm_result` | núcleo → UI | `ActionResult` em JSON |
| `lm_obs` | núcleo → UI | `{"items":[Observation…],"count"}` — lista inteira da sessão (idempotente) |
| `lm_cfg` | UI → núcleo | `{"speak_replies": bool}` e mudo (`mic_muted`) |

Mensagens existentes (`state`, `speech`, `subtitle`, `mouth`) continuam indo a todos os clientes.

## 7. Estado da Condessa (UI-001)

| Estado do núcleo | Sessão ativa | Ação rodando | Rótulo | Cor |
| --- | --- | --- | --- | --- |
| `sleeping` / `followup` | sim | não | `TEACHING 教育中` | `GPU #5fd38d` |
| `listening` | sim | — | `LISTENING 聴取中` | `FOCUS #5fd0e0` |
| `thinking` | sim | — | `THINKING 思考中` | `FOCUS` |
| `speaking` | sim | — | `SPEAKING 発話中` | `CPU #b392f0` |
| qualquer ocioso | sim | sim | `ANALYZING 分析中` (discreto) | `TEXT_DIM` |
| qualquer | não | — | `STANDBY` | `TEXT_DIM` |
| sem conexão | — | — | `OFFLINE` | `HOT #e5695b` |

No bloco esquerdo: `SPEAKING ● ACTIVE/OFF` reflete `speak_replies`; `LISTENING ● READY/MUTED`
reflete o mudo.

## 8. Banco — `magi/memory/migrations/003_learning.sql`

Aditiva, idempotente pelo `schema_migrations`. **Sem** `DROP`, sem `vector` (DAT-003).

```sql
CREATE TABLE learning_sessions (
    id           text PRIMARY KEY,                -- LS-20261007-01
    started_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    end_reason   text,                            -- user | idle | shutdown
    level        text,                            -- B2 (exibido)
    track        text
);
CREATE TABLE learning_messages (
    id           bigserial PRIMARY KEY,
    session_id   text NOT NULL REFERENCES learning_sessions(id),
    author       text NOT NULL CHECK (author IN ('you','condessa')),
    source       text NOT NULL CHECK (source IN ('voice','text')),
    text         text NOT NULL,
    text_final   text,                            -- após Corrector (voz), se diferente
    turn_id      bigint,                          -- turns.id, se houver
    at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX learning_messages_session_idx ON learning_messages (session_id, id);
CREATE TABLE learning_observations (
    id           bigserial PRIMARY KEY,
    session_id   text NOT NULL REFERENCES learning_sessions(id),
    message_id   bigint NOT NULL REFERENCES learning_messages(id),
    category     text NOT NULL CHECK (category IN ('vocabulary','grammar','recurring')),
    rule_key     text NOT NULL,
    label        text NOT NULL,
    span         text,
    suggestion   text,
    model        text,
    at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX learning_observations_rule_idx ON learning_observations (rule_key, at);  -- MEM-001 futuro
CREATE TABLE learning_action_results (
    id           text PRIMARY KEY,                -- ACT-…
    message_id   bigint NOT NULL REFERENCES learning_messages(id),
    kind         text NOT NULL,
    sel_start    int NOT NULL,
    sel_end      int NOT NULL,
    ok           boolean NOT NULL,
    data         jsonb,
    error        text,
    model        text,
    cost_usd     numeric(12,6) NOT NULL DEFAULT 0,
    at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (message_id, kind, sel_start, sel_end)    -- cache
);
```

Custos também entram na tabela `costs` existente (mesma rotina do núcleo), com rótulo
`learning_actions` / `learning_observe` (LM-006). Backend `jsonl` (P4): um arquivo por sessão em
`~/.local/share/magi/learning/LS-….jsonl`, linhas `{"kind":"msg"|"obs"|"act",…}`.

## 9. Observações (ENG-*, OBS-*)

1. Gatilho: cada `LearningMessage` do Pedro, se `observe = true` e abaixo de `observe_daily_max`.
2. Espera o gate de estado (design §6); entra na fila de baixa prioridade.
3. Prompt `prompts/observe.md` devolve `{"items":[{category: vocabulary|grammar, rule_key, label,
   span, suggestion}]}` — 0 a 3 itens; vocabulário = palavra B2+ usada corretamente ou nova.
4. `recurring` é derivado, não vem do modelo: quando um `rule_key` de `grammar` aparece pela 2ª vez
   na sessão, cria-se (uma vez) uma observação `recurring` com o `label` da família (ex.: `rule_key`
   `grammar.prepositions.*` → "Prepositions").
5. Após gravar, `lm_obs` com a lista inteira e `count` = itens distintos por (`category`,
   `label`).
6. Nada de observação é mostrado no fluxo da conversa (CNV-002, PRN-004).

## 10. Sessão

`lm_mode on` sem sessão aberta cria `LS-` novo; com sessão aberta há menos de `idle_end_min`,
retoma. Fecha por `lm_mode off`, voz "end session"/"encerrar sessão", inatividade, ou desligamento
do núcleo (`end_reason`). Reabrir a janela com sessão aberta recarrega as últimas 200 mensagens
do banco.

## 11. Casos de borda

| Caso | Comportamento |
| --- | --- |
| Seleção atravessa mensagens | recorta na mensagem de início (SEL-001) |
| Seleção na mensagem em fala | menu não abre até terminar |
| Selecionar dentro do balão | não abre outro menu (sem aninhamento no MVP) |
| Janela fecha com ação pendente | ação continua e grava; resultado vai ao cache |
| Duas janelas Learning abertas | ambas recebem `lm_*`; ações são por janela (`id`) |
| STT detecta português (listen=auto) | mensagem entra no histórico; observação marca `rule_key = "lang.portuguese"` só se `observe` — não corrige |
| Mensagem do Pedro mista PT/EN | Improve trata só a parte em inglês; Translate funciona nos dois sentidos |
| Banco cai no meio | mensagens ficam em memória (até 500) e são gravadas na volta; ações sem cache |
| Orçamento estoura no meio da sessão | ações → `budget`; observações pausadas; conversa continua (a do agente segue a regra atual) |
| Trecho com dado sensível | vai ao modelo cloud igual à conversa já vai (RNF-08); nenhum dado extra |

## 12. Critérios de aceite

`tests/learning/` é a pasta. Testes de banco usam `migrate.py --schema learning_test`.

| ID | Requisito | Critério | Verifica |
| --- | --- | --- | --- |
| CA-01 | ENG-001, RNF-01 | 200 turnos falsos: p95 com engine ligado ≤ 1,05 × desligado; nenhum `await` de rede antes da entrega | [test `test_latency.py`] |
| CA-02 | ENG-001 | `publish` com fila cheia não bloqueia e descarta o mais antigo | [test `test_bus.py`] |
| CA-03 | ENG-001 | observação não inicia em `thinking`/`speaking`; inicia ao voltar a `listening` | [test `test_engine.py::test_gate`] |
| CA-04 | ENG-002 | trocar `[tasks] learning_actions` muda o modelo sem mudar código (FakeModel por config) | [test `test_model.py`] |
| CA-05 | LM-001, LM-002 | `lm_say` gera duas `lm_msg`; voz grava `heard` em `text` e `final` em `text_final` | [test `test_conversation.py`] |
| CA-06 | CNV-002 | com 10 frases erradas gravadas, a resposta do agente (FakeModel de persona) não contém "you should say"/"correct form"; prompt contém o bloco de persona | [test `test_persona.py`] |
| CA-07 | IMP-001..003 | schema improve validado; `kind=none` aceito; `why` > 240 é cortado | [test `test_analyzers.py::test_improve`] |
| CA-08 | EXP-001, TRA-001 | explain 1–4 frases; translate com `note` só para ≤ 3 palavras | [test `test_analyzers.py`] |
| CA-09 | VOC-001, VOC-002 | vocabulary tem os 6 campos; > 4 palavras desabilitado | [test `test_analyzers.py::test_vocab`, `test_selection.py`] |
| CA-10 | SEL-001..003 | seleção normalizada para palavras, recortada, menu com 4 ações e Improve desabilitado em mensagem da Condessa | [test `test_selection.py`] |
| CA-11 | SEL-002 | posição do menu dentro da coluna central em 3440×1440 e 1920×1080, nunca cobre a seleção | [test `test_layout.py`] |
| CA-12 | LM-007 | timeout do FakeModel → `ok=false, error=timeout`; JSON inválido 2× → `invalid` | [test `test_engine.py::test_falhas`] |
| CA-13 | LM-006 | teto estourado → `budget`, sem chamada ao modelo; custo gravado em `costs` | [test `test_engine.py::test_budget`] |
| CA-14 | OBS-001, OBS-002 | agrupamento em 3 categorias; `recurring` criado na 2ª ocorrência do mesmo `rule_key` | [test `test_observations.py`] |
| CA-15 | DAT-003, LM-010 | `003_learning.sql` não contém `DROP`, `vector` nem `ALTER … DROP`; aplicar 2× não faz nada | [test `test_migration.py`] |
| CA-16 | MEM-002 | toda observação gravada tem `rule_key` não vazio e `session_id` | [test `test_repo.py`] |
| CA-17 | UI-001 | tabela §7 coberta por teste puro de mapeamento | [test `test_state_label.py`] |
| CA-18 | LM-005 | com Learning fechado, `gamerhud` recebe as mesmas mensagens de antes e nenhum `lm_*` | [test `test_socket.py`] |
| CA-19 | PRN-001..004, SYS-* | revisão visual: captura 3440×1440 do estado padrão (sem balão, drawer fechado) aprovada pelo Pedro | [manual] |
