-- Tarefa LI0.2 (R5.1, R2.6): vagas e simulações de entrevista do learning imersivo, spec §8.
--
-- Aditiva e idempotente: só cria tabelas e índice novos (``IF NOT EXISTS``); não altera nem apaga
-- nada das tabelas da 003 (``learning_interviews.session_id`` só referencia ``learning_sessions``).

CREATE TABLE IF NOT EXISTS learning_jobs (
    id          text PRIMARY KEY,                 -- JOB-1a2b3c4d
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_used   timestamptz NOT NULL DEFAULT now(),
    source      text NOT NULL,
    text        text NOT NULL,
    profile     jsonb,                            -- NULL até a extração dar certo
    model       text,
    cost_usd    numeric(10,6)
);
CREATE TABLE IF NOT EXISTS learning_interviews (
    id          text PRIMARY KEY,                 -- IV-20261010-01
    session_id  text NOT NULL REFERENCES learning_sessions(id),
    job_id      text NOT NULL REFERENCES learning_jobs(id),
    plan        jsonb NOT NULL,
    state       text NOT NULL,
    progress    jsonb NOT NULL DEFAULT '{}',      -- stage, asked, answers, asked_log, tempos, ids
    started_at  timestamptz NOT NULL DEFAULT now(),
    ended_at    timestamptz,
    end_reason  text,
    debrief     jsonb,
    debrief_seen boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS learning_interviews_session ON learning_interviews(session_id);
