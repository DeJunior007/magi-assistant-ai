-- 001_base: esquema base da Ayanami (spec §3, dono: Y0.3).
-- Aplicada por `ayanami migrar` (ayanami/migrar.py), numa transação, registrada em schema_migracoes.
-- Migrações da Ayanami são só aditivas.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;              -- gen_random_uuid

CREATE TABLE dispositivos (
    id         serial PRIMARY KEY,
    nome       text NOT NULL UNIQUE CHECK (nome ~ '^[a-z0-9][a-z0-9-]{0,31}$' AND nome <> 'ayanami'),
    tipo       text NOT NULL CHECK (tipo IN ('pc','casa','celular','mcp')),
    escopos    text[] NOT NULL,
    hash       text NOT NULL UNIQUE,                 -- sha256 hex do token
    prefixo    text NOT NULL,
    criado     timestamptz NOT NULL DEFAULT now(),
    ultimo_uso timestamptz,
    visto      timestamptz,                          -- último ola/bate
    revogado   timestamptz,
    preferencias jsonb NOT NULL DEFAULT '{}'         -- celular: §16.1 (PUT /v1/dispositivo/preferencias)
);
CREATE UNIQUE INDEX dispositivos_pc_unico ON dispositivos (tipo) WHERE tipo = 'pc' AND revogado IS NULL;

CREATE TABLE pareamentos (
    codigo_hash text PRIMARY KEY, criado_por integer NOT NULL REFERENCES dispositivos (id),
    nome_sugerido text, expira timestamptz NOT NULL, usado timestamptz, erros smallint NOT NULL DEFAULT 0
);

CREATE TABLE tarefas (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id      bigint,                              -- procrastinate_jobs.id (sem FK: tabela da lib)
    tipo        text NOT NULL CHECK (tipo IN ('pesquisa','resumo','lembrete','monitor','stt','sistema')),
    titulo      text NOT NULL CHECK (length(titulo) <= 120),
    chave       text,                                -- idempotência (R2.2)
    estado      text NOT NULL DEFAULT 'na_fila'
                CHECK (estado IN ('na_fila','rodando','ok','falhou','cancelada')),
    progresso   smallint CHECK (progresso BETWEEN 0 AND 100),
    frase       text,
    origem      integer REFERENCES dispositivos (id),
    params      jsonb NOT NULL DEFAULT '{}',
    pessoal     boolean NOT NULL DEFAULT false,      -- R3.5: true → nunca provedor free_tier
    avisar      boolean NOT NULL DEFAULT true,
    resultado   jsonb,                               -- {"texto": str, "dados": {...}}
    erro        text,                                -- código + frase, sem segredo
    agenda      timestamptz,                         -- lembrete / próximo passo do monitor
    expira      timestamptz,                         -- monitor: padrão criada + 30 dias
    criada      timestamptz NOT NULL DEFAULT now(),
    atualizada  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX tarefas_chave_viva ON tarefas (chave) WHERE estado IN ('na_fila','rodando');
CREATE INDEX tarefas_estado_idx ON tarefas (estado, atualizada DESC);

CREATE TABLE eventos (
    id        bigserial PRIMARY KEY,                 -- = Evento.seq e id do SSE
    tipo      text NOT NULL, titulo text NOT NULL, resumo text NOT NULL DEFAULT '',
    ref       text, para text[] NOT NULL DEFAULT '{pc,celular}',
    criado    timestamptz NOT NULL DEFAULT now(),
    entregue_pc timestamptz, push_enviado timestamptz
);

CREATE TABLE auditoria (
    id bigserial PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(),
    dispositivo integer REFERENCES dispositivos (id), tipo text NOT NULL,   -- casa|mcp|dispositivo|backup|tarefa|push
    alvo text, resumo text NOT NULL CHECK (length(resumo) <= 300), ok boolean NOT NULL
);
CREATE INDEX auditoria_ts_idx ON auditoria (ts);

CREATE TABLE push_assinaturas (
    id serial PRIMARY KEY, dispositivo integer NOT NULL REFERENCES dispositivos (id) ON DELETE CASCADE,
    endpoint text NOT NULL UNIQUE, p256dh text NOT NULL, auth text NOT NULL,
    criada timestamptz NOT NULL DEFAULT now(), falhas smallint NOT NULL DEFAULT 0
);

CREATE TABLE confirmacoes (
    id text PRIMARY KEY,                             -- ULID
    origem integer REFERENCES dispositivos (id), descricao text NOT NULL,
    pedido jsonb NOT NULL, expira timestamptz NOT NULL, resposta boolean, respondida timestamptz
);

CREATE TABLE nuvem_turnos (
    uid uuid PRIMARY KEY DEFAULT gen_random_uuid(), ts timestamptz NOT NULL DEFAULT now(),
    dispositivo integer REFERENCES dispositivos (id), texto_usuario text NOT NULL,
    texto_resposta text NOT NULL, ferramentas text[] NOT NULL DEFAULT '{}', sincronizado timestamptz
);

CREATE TABLE costs (                                 -- mesmo esquema do magi-pg + uid/source
    id bigserial PRIMARY KEY, uid uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    at timestamptz NOT NULL DEFAULT now(), provider text NOT NULL, task text NOT NULL, model text,
    input_units bigint NOT NULL DEFAULT 0, output_units bigint NOT NULL DEFAULT 0,
    usd numeric(12, 6) NOT NULL DEFAULT 0, source text NOT NULL DEFAULT 'nuvem'
);
CREATE INDEX costs_at_idx ON costs (at);
CREATE TABLE custos_pc (mes date PRIMARY KEY, usd numeric(12, 6) NOT NULL, visto timestamptz NOT NULL);

CREATE TABLE backups (
    id serial PRIMARY KEY, origem text NOT NULL CHECK (origem IN ('pc','ayanami')),
    data date NOT NULL, bytes bigint NOT NULL, sha256 text NOT NULL, manifesto jsonb NOT NULL,
    recebido timestamptz NOT NULL DEFAULT now(), snapshot text, enviado timestamptz,
    UNIQUE (origem, data)
);
CREATE TABLE restore_testes (
    id serial PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(), snapshot text,
    verde boolean NOT NULL, detalhes jsonb NOT NULL
);
CREATE TABLE workers_batimento (fila text PRIMARY KEY, host text NOT NULL, visto timestamptz NOT NULL);
