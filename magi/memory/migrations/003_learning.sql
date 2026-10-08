-- Tarefa LM1.1 (DAT-001..003, MEM-002, LM-010..LM-013): tabelas do Learning Mode, spec §8.
--
-- Aditiva: só cria tabelas e índices novos com prefixo ``learning_`` (``corrections``, ``vocab`` e
-- ``progress`` já existem e têm outro sentido). Idempotente pelo ``schema_migrations``. Nenhuma
-- coluna de embeddings no MVP (DAT-003). Palavra salva desfeita = ``removed_at``, nunca DELETE.

CREATE TABLE learning_sessions (
    id           text PRIMARY KEY,                -- LS-20261007-01
    started_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    end_reason   text,                            -- button | voice | idle | shutdown
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
