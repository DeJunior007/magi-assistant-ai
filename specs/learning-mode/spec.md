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
| Palavra salva | bigint do banco; chave lógica `norm` | |
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
default_topic = "free"          # LM-013: free | interview | game | news
topic_picker_s = 10             # seletor fecha sozinho (design §4.5)
summary_show_s = 60             # cartão LAST SESSION (LM-011)

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

class Topic(StrEnum):    FREE = "free"; INTERVIEW = "interview"; GAME = "game"; NEWS = "news"   # LM-013

@dataclass(frozen=True)
class TopicContext:                         # LM-013 (spec §10.1)
    topic: Topic              # o efetivo (pode ser FREE por falta de dados)
    requested: Topic
    label: str                # "FREE TALK" | "TECH INTERVIEW" | "THE GAME I'M PLAYING" | "TODAY'S NEWS"
    block: str | None         # contexto do prompt, ≤ 1500 caracteres; None em FREE
    detail: str | None        # motivo do fallback: "no game detected" | "no news today"

@dataclass(frozen=True)
class SessionSummary:                       # LM-011 (spec §10.2)
    session_id: str; n: int                 # n = número do dia (o NN de LS-…-NN)
    started_at: datetime; ended_at: datetime; duration_s: int
    end_reason: str                         # button | voice | idle | shutdown
    n_msgs: int; n_you: int; obs_count: int
    practiced: list[str]                    # labels de recurring + grammar, ≤ 5
    new_words: list[str]                    # labels de vocabulary + palavras salvas na sessão, ≤ 8
    saved: list[str]                        # palavras salvas nesta sessão
    more_practiced: int; more_words: int    # quantos ficaram de fora ("+N")
    topics: list[str]                       # temas usados, em ordem

@dataclass(frozen=True)
class SavedWord:                            # LM-012 (spec §10.3)
    id: int | None; norm: str; term: str
    meaning: str; pos: str | None; cefr: str | None
    example: str              # frase de origem
    session_id: str; message_id: int; action_id: str
    saved_at: datetime; removed_at: datetime | None
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

Seleção é feita pelo próprio HUD (P1 = A, design §4.2), sempre em palavras inteiras: clique =
palavra sob o ponteiro; arrastar = da palavra inicial até a palavra sob o ponteiro (ponto entre
palavras conta como a mais próxima da linha); duplo clique = frase (até `. ! ?` ou fim da
mensagem); recortada à mensagem de início. O intervalo é `[start, end)` em caracteres da mensagem,
sem espaços/pontuação nas pontas. Seleção só de espaços/pontuação não abre menu. Clique em área sem
texto limpa a seleção.

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
| `lm_hello` | UI → núcleo | `{}` — a conexão se identifica como Learning (com P1 = A, o `hud_bridge` do `gamerhud`); só ela recebe `lm_*` |
| `lm_mode` | ambos | `{"on": bool}` — UI pede (botão); núcleo confirma a todos os clientes Learning (também quando o pedido veio por voz); o `gamerhud` só troca de tela ao receber a confirmação |
| `lm_session` | núcleo → UI | `{"id","started_at","level","track","topic","n_msgs","obs_count"}` |
| `lm_say` | UI → núcleo | `{"text"}` |
| `lm_msg` | núcleo → UI | `{"id","author","source","text","at","speaking"}` |
| `lm_action` | UI → núcleo | `{"id","kind","message_id","start","end"}` |
| `lm_result` | núcleo → UI | `ActionResult` em JSON |
| `lm_obs` | núcleo → UI | `{"items":[Observation…],"count"}` — lista inteira da sessão (idempotente) |
| `lm_cfg` | UI → núcleo | `{"speak_replies": bool}` e mudo (`mic_muted`) |
| `lm_topic` | ambos | UI → núcleo `{"topic"}`; núcleo → UI `{"topic","requested","label","detail"}` (confirmação, também quando veio por voz) |
| `lm_save` | UI → núcleo | `{"action_id","on": bool}` — guardar (`true`) ou desfazer (`false`) a palavra do balão Vocabulary |
| `lm_saved` | núcleo → UI | `{"norm","saved": bool,"id"}` — depois de cada `lm_save` e de cada `lm_result` de vocabulary (inclusive do cache) |
| `lm_summary` | núcleo → UI | `SessionSummary` em JSON; enviado só **depois** de `lm_mode {"on": false}` e só se `n_you > 0` |

Mensagens existentes (`state`, `speech`, `subtitle`, `mouth`) continuam indo a todos os clientes.
Fora do modo nenhum `lm_*` é publicado, **exceto** o `lm_summary` da sessão que acabou de fechar
(§10.2).

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
    track        text,
    topic        text NOT NULL DEFAULT 'free',     -- LM-013: tema atual
    topics       jsonb NOT NULL DEFAULT '[]',      -- [{"topic","at"}] em ordem
    summary      jsonb                            -- LM-011: SessionSummary do último fechamento
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
CREATE TABLE learning_saved_words (                -- LM-012
    id           bigserial PRIMARY KEY,
    norm         text NOT NULL,                   -- minúsculas, sem pontuação nas pontas, espaços simples
    term         text NOT NULL,                   -- como foi selecionado
    meaning      text NOT NULL,
    pos          text,
    cefr         text,
    example      text NOT NULL,                   -- frase de origem (≤ 240)
    session_id   text NOT NULL REFERENCES learning_sessions(id),
    message_id   bigint NOT NULL REFERENCES learning_messages(id),
    action_id    text REFERENCES learning_action_results(id),
    saved_at     timestamptz NOT NULL DEFAULT now(),
    removed_at   timestamptz                      -- desfazer = marca, nunca DELETE
);
CREATE UNIQUE INDEX learning_saved_words_active_idx ON learning_saved_words (norm) WHERE removed_at IS NULL;
```

Custos também entram na tabela `costs` existente (mesma rotina do núcleo), com rótulo
`learning_actions` / `learning_observe` (LM-006). Backend `jsonl` (P4): um arquivo por sessão em
`~/.local/share/magi/learning/LS-….jsonl`, linhas `{"kind":"msg"|"obs"|"act"|"topic"|"summary",…}`; palavras salvas em arquivo próprio (§10.3).

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
retoma. Abre por botão `[ LEARNING ]` ou voz (`learning.start`, frases PT/EN em design §10). Fecha
por `lm_mode off` (botão `[ END SESSION ]`), voz (`learning.stop`: "end session", "encerrar aula",
"sair do modo aula"…), inatividade, ou desligamento do núcleo (`end_reason` = `button` | `voice` |
`idle` | `shutdown`). Reiniciar o `gamerhud` (ou reconectar) com sessão aberta volta direto à tela
learning e recarrega as últimas 200 mensagens do banco.

### 10.1 Tema da sessão (LM-013, LM-014)

1. Padrão `Topic.FREE` (`[learning] default_topic`). Em sessão **nova**, a tela abre o seletor
   (design §4.5); em sessão **retomada**, não abre e mostra o tema atual.
2. `lm_topic {"topic"}` (botão) ou intent de voz (`learning.topic.free|interview|game|news`, frases
   em design §10) → `topic.build(requested)` → `TopicContext` → guarda na sessão, grava em
   `learning_sessions.topic` e acrescenta `{"topic","at"}` em `topics` → confirma `lm_topic` a todos
   os clientes Learning. O mesmo tema de novo só confirma.
3. Contexto (snapshot no momento da escolha; para atualizar, escolher de novo). Nenhum gera chamada
   de LLM nem rede:
   - **free**: `block = None`.
   - **interview**: texto fixo de `prompts/topics/interview.md` (a Condessa faz o papel de
     entrevistadora amigável de vaga de software: uma pergunta por vez sobre experiência, projetos e
     trade-offs, inglês técnico; sem nota nem avaliação).
   - **game**: jogo aberto do `GameWatcher` (`magi/core/game_context.py`: nome, minutos desde
     `since`) + estatística da Steam pelo mesmo caminho do `SteamGameTool` (`describe(GameStats)`:
     horas totais, conquistas) → `prompts/topics/game.md` preenchido. Sem jogo aberto → P12.
   - **news**: até 5 itens das últimas 24 h do `NewsRepo` do Rádio Ayanami (título + 1 frase),
     **só leitura**, sem `mark_delivered` → `prompts/topics/news.md`. Sem item → fallback.
   - Fallback: `topic = FREE`, `requested` = o pedido, `detail` = `"no game detected"` |
     `"no news today"`.
4. O `block` entra no system prompt **depois** do bloco de persona (§4 item 4), dentro de
   `<topic_context>` e tratado como dado; cortado em 1500 caracteres. A persona continua valendo
   (sem correção explícita, conversa primeiro).
5. Troca no meio da aula: vale a partir do próximo turno; histórico e observações seguem iguais.
   Abertura (P11): com tema ≠ `free`, o núcleo roda **um** turno do agente com instrução interna
   "open this topic with one open question" quando o estado voltar a `listening`; se o Pedro falar
   ou digitar antes, a abertura é cancelada. Conta no orçamento como a conversa.

### 10.2 Resumo ao sair (LM-011)

1. Ao fechar a sessão (qualquer `end_reason`), o núcleo **primeiro** confirma `lm_mode off`; o
   resumo roda depois, em tarefa própria, sem LLM (`magi/learning/summary.py`, função pura
   `summarize(session, messages_stats, observations, saved) -> SessionSummary`).
2. Fontes: `learning_sessions` (início, `topics`), contagem de `learning_messages` (total e do
   Pedro), `learning_observations` da sessão e `learning_saved_words` com `session_id` da sessão
   (`removed_at IS NULL`). Leitura com timeout de 2 s; se o banco não responder, usa o buffer em
   memória (§11 "Banco cai").
3. Regras: `duration_s` = última mensagem − `started_at` (a cauda de inatividade não conta; sem
   mensagem = `ended_at − started_at`); `obs_count` igual ao de `lm_obs` (§9 item 5);
   `practiced` = labels distintos de `recurring` (primeiro) e `grammar`, ordem de primeira
   ocorrência, até 5; `new_words` = labels distintos de `vocabulary` + palavras salvas na sessão
   que não estejam lá, até 8; o resto vira `more_*`. Observações que chegarem depois do fechamento
   são gravadas normalmente, mas não mudam o resumo (o Learning Profile pode recalcular a partir
   delas).
4. Persistência: `learning_sessions.summary` (jsonb) é regravado a cada fechamento (sessão retomada
   e fechada de novo → resumo da sessão inteira).
5. Envio: `lm_summary` só se `n_you > 0` e `end_reason ≠ shutdown`. O HUD descarta `lm_summary`
   que chegue mais de 10 s depois do `lm_mode off`.
6. Cartão (design §4.6): `LAST SESSION // NN` + linha `24 MIN · 38 MSGS · 6 OBS · FREE TALK` +
   `PRACTISED …` + `NEW WORDS …` (salvas com ★). Some após `summary_show_s`, ao clicar nele, ou
   ao entrar de novo no modo. Não é guardado no HUD: reiniciar o `gamerhud` não reexibe.

### 10.3 Palavras salvas (LM-012)

1. O balão Vocabulary (`ok = true`) mostra `☆ SAVE` / `★ SAVED`. Clique → `lm_save
   {"action_id","on"}`; a UI marca na hora e desfaz a marca se a confirmação `lm_saved` não vier em
   3 s ou vier com o estado contrário (linha curta "not saved").
2. O núcleo resolve tudo pelo `action_id` (nada de texto livre vindo da UI): `term`/`meaning`/
   `pos`/`cefr` de `learning_action_results.data`; `example` = a frase da mensagem de origem que
   contém a seleção (corte por `.`/`!`/`?`, até 240 caracteres); `norm` = `term` em minúsculas, sem
   pontuação nas pontas, espaços simples.
3. `on = true` com `norm` já ativo → não duplica, só confirma. `on = false` → `removed_at = now()`
   (nunca `DELETE`). Guardar de novo depois de desfazer → linha nova.
4. Depois de cada `lm_result` de vocabulary o núcleo manda `lm_saved` do `norm` do termo, para a
   estrela abrir no estado certo.
5. Backend `jsonl`: `~/.local/share/magi/learning/saved_words.jsonl`, linhas `{"op":"save"|"unsave",…}`.

## 11. Casos de borda

| Caso | Comportamento |
| --- | --- |
| Seleção atravessa mensagens | recorta na mensagem de início (SEL-001) |
| Seleção na mensagem em fala | menu não abre até terminar |
| Selecionar dentro do balão | não abre outro menu (sem aninhamento no MVP) |
| Sai do modo (ou o `gamerhud` cai) com ação pendente | ação continua e grava; resultado vai ao cache |
| Dois clientes com `lm_hello` (ex.: `gamerhud` reiniciado antes da conexão velha cair) | ambos recebem `lm_*`; ações são por cliente (`id`) |
| Voz "end session" dentro de uma frase de conversa ("the session ended late") | não encerra: a frase tem palavras sobrando e o roteador penaliza; coberto em teste |
| `learning.start` com o modo já ligado / `learning.stop` desligado | só confirma, sem efeito |
| Clique entre duas palavras / fim da linha | seleciona a palavra mais próxima na mesma linha |
| Arrastar para fora da coluna da conversa | a seleção para na última palavra alcançada |
| Rolagem do histórico com seleção aberta | menu e balão fecham |
| Botão LEARNING com o núcleo fora | nada muda; rodapé mostra `DISCONNECTED` |
| STT detecta português (listen=auto) | mensagem entra no histórico; observação marca `rule_key = "lang.portuguese"` só se `observe` — não corrige |
| Mensagem do Pedro mista PT/EN | Improve trata só a parte em inglês; Translate funciona nos dois sentidos |
| Banco cai no meio | mensagens ficam em memória (até 500) e são gravadas na volta; ações sem cache |
| Orçamento estoura no meio da sessão | ações → `budget`; observações pausadas; conversa continua (a do agente segue a regra atual) |
| Trecho com dado sensível | vai ao modelo cloud igual à conversa já vai (RNF-08); nenhum dado extra |
| Sessão fechada sem nenhuma mensagem do Pedro | resumo gravado; sem `lm_summary`, sem cartão |
| Encerrar por inatividade | cartão aparece na view guardada (o `gamerhud` já voltou para ela); `duration_s` sem os 20 min ociosos |
| Núcleo desligado com sessão aberta (`shutdown`) | resumo gravado; sem cartão |
| Entrar de novo no modo com o cartão visível | cartão some; sessão nova ou retomada |
| Meta+M com o cartão visível | cartão segue na outra view (painel ↔ espera) com o tempo restante |
| ★ com o banco fora | `lm_saved` com `saved=false` → estrela volta e o balão mostra "not saved" |
| ★ na mesma palavra em duas mensagens | uma entrada ativa (por `norm`); a frase de origem é a primeira |
| Tema "game" sem jogo aberto | P12; sem dado → Free talk + `detail` no seletor |
| Tema "news" sem banco ou sem item em 24 h | Free talk + `detail = "no news today"` |
| "let's talk about the game" fora do modo | não casa intent de tema (só com sessão ativa); vai ao fluxo normal |
| "what's new" / "novidades" dentro do modo | continua indo ao intent de notícias existente (não troca o tema) |
| Trocar o tema enquanto a Condessa fala | troca vale no próximo turno; abertura espera `listening` |
| Seletor aberto e o Pedro já fala ou digita | seletor fecha, tema fica Free talk (ou o já escolhido) |

## 12. Critérios de aceite

`tests/learning/` é a pasta. Testes de banco usam `migrate.py --schema learning_test`.

| ID | Requisito | Critério | Verifica |
| --- | --- | --- | --- |
| CA-01 | ENG-001, RNF-01 | 200 turnos falsos: p95 com engine ligado ≤ 1,05 × desligado; nenhum `await` de rede antes da entrega | [test `test_latency.py`] |
| CA-02 | ENG-001 | `publish` com fila cheia não bloqueia e descarta o mais antigo | [test `test_bus.py`] |
| CA-03 | ENG-001 | observação não inicia em `thinking`/`speaking`; inicia ao voltar a `listening` | [test `test_engine.py::test_gate`] |
| CA-04 | ENG-002 | trocar `[tasks] learning_actions` muda o modelo sem mudar código (FakeModel por config) | [test `test_model.py`] |
| CA-05 | LM-001, LM-002 | `lm_say` gera duas `lm_msg`; voz grava `heard` em `text` e `final` em `text_final` | [test `test_conversation.py`] |
| CA-05b | LM-005 | frases de §10/design §10 em PT e EN casam `learning.start`/`learning.stop` no roteador local; 10 frases de conversa em inglês que contêm "session"/"class"/"lesson" não casam | [test `test_learning_intents.py`] |
| CA-06 | CNV-002 | com 10 frases erradas gravadas, a resposta do agente (FakeModel de persona) não contém "you should say"/"correct form"; prompt contém o bloco de persona | [test `test_persona.py`] |
| CA-07 | IMP-001..003 | schema improve validado; `kind=none` aceito; `why` > 240 é cortado | [test `test_analyzers.py::test_improve`] |
| CA-08 | EXP-001, TRA-001 | explain 1–4 frases; translate com `note` só para ≤ 3 palavras | [test `test_analyzers.py`] |
| CA-09 | VOC-001, VOC-002 | vocabulary tem os 6 campos; > 4 palavras desabilitado | [test `test_analyzers.py::test_vocab`, `test_selection.py`] |
| CA-10 | SEL-001..003 | seleção normalizada para palavras, recortada, menu com 4 ações e Improve desabilitado em mensagem da Condessa | [test `test_selection.py`] |
| CA-10b | SEL-001 | hit-test puro (`learning_text`, medidor falso): clique, arrasto, duplo clique, ponto entre palavras, quebra de linha, arrasto para outra mensagem e para fora da coluna dão o intervalo esperado | [test `test_learning_text.py`] |
| CA-11 | SEL-002 | posição do menu dentro da coluna central em 3440×1440 e 1920×1080 (ou a resolução do monitor do HUD, P10), nunca cobre a seleção | [test `test_menu_layout.py`] |
| CA-12 | LM-007 | timeout do FakeModel → `ok=false, error=timeout`; JSON inválido 2× → `invalid` | [test `test_engine.py::test_falhas`] |
| CA-13 | LM-006 | teto estourado → `budget`, sem chamada ao modelo; custo gravado em `costs` | [test `test_engine.py::test_budget`] |
| CA-14 | OBS-001, OBS-002 | agrupamento em 3 categorias; `recurring` criado na 2ª ocorrência do mesmo `rule_key` | [test `test_observations.py`] |
| CA-15 | DAT-003, LM-010 | `003_learning.sql` não contém `DROP`, `vector` nem `ALTER … DROP`; aplicar 2× não faz nada | [test `test_migration.py`] |
| CA-16 | MEM-002 | toda observação gravada tem `rule_key` não vazio e `session_id` | [test `test_repo.py`] |
| CA-17 | UI-001 | tabela §7 coberta por teste puro de mapeamento | [test `test_state_label.py`] |
| CA-18 | LM-005 | fora do modo, nenhum `lm_*` é publicado (exceto `lm_summary` logo após o fechamento) e os clientes recebem as mesmas mensagens de antes; cliente sem `lm_hello` nunca recebe `lm_*` | [test `test_socket.py`] |
| CA-18b | LM-005 | botão/`lm_mode` troca `full`/`idle` → `learning` e volta para a view guardada; painel e espera sem o modo pintam igual a antes (exceto o botão) e cliques antigos (LED, player, cards, rosto) seguem iguais | [test `test_learning_toggle.py`] |
| CA-19 | PRN-001..004, SYS-* | revisão visual: captura na resolução do monitor do HUD (3440×1440 se for o ultrawide, P10) do estado padrão (sem balão, drawer fechado) e do painel/espera com o botão LEARNING, do seletor de tema aberto, do balão Vocabulary com ★ e do cartão `LAST SESSION` no painel e na espera, aprovada pelo Pedro | [manual] |
| CA-20 | LM-011 | `summarize` com observações de exemplo: `practiced`/`new_words`/`more_*`/`duration_s` (sem cauda ociosa) corretos; `n_you = 0` não envia; com repo lento (2 s) o `lm_mode off` sai em ≤ 50 ms e o `lm_summary` depois; resumo gravado em `learning_sessions.summary` | [test `test_summary.py`] |
| CA-21 | LM-011 | cartão (lógica pura, relógio falso): aparece na view de retorno, some em 60 s, ao clicar e ao `lm_mode on`; `lm_summary` atrasado > 10 s é descartado; sem pontuação/streak no texto | [test `test_summary_card.py`] |
| CA-22 | LM-012 | guardar/desfazer/guardar de novo; um ativo por `norm`; `lm_saved` após `lm_result` de vocabulary (inclusive cache); `lm_save` com `action_id` de outro kind é recusado | [test `test_saved_words.py`] |
| CA-23 | LM-013 | `topic.build`: free sem bloco; game com `GameWatcher`/Steam falsos contém nome e horas; sem jogo → fallback; news com repo falso traz títulos e **não** chama `mark_delivered`; bloco ≤ 1500; persona continua no prompt | [test `test_topic.py`] |
| CA-24 | LM-014 | frases PT/EN dos 4 temas casam só com sessão ativa; frases dos intents de notícias e de jogo existentes não casam tema, e vice-versa | [test `test_learning_intents.py`] |
| CA-25 | LM-013 | seletor (lógica pura): abre em sessão nova e não em retomada; fecha em 10 s/Esc/mensagem; chip mostra o tema confirmado e o `detail` do fallback | [test `test_topic_view.py`] |
| CA-26 | LM-015 | retrato da tela learning com `size() == MASCOT_MAIN.size()` (302 de altura na base 1920) | [test `test_layout.py`] |
