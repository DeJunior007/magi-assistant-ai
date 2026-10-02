-- 001_init: esquema inicial da Magui (design §7).
--
-- Dimensão dos vetores: este arquivo NÃO é SQL puro. O executor (magi/memory/migrate.py)
-- troca os marcadores abaixo antes de rodar:
--   {{MEMORIES_DIM}} -> dimensão do modelo de embeddings da memória
--                       (parâmetro memories_dim, env MAGI_EMBED_DIM_MEMORIES, padrão 1536)
--   {{NEWS_DIM}}     -> dimensão dos embeddings das notícias
--                       (parâmetro news_dim, env MAGI_EMBED_DIM_NEWS, padrão 768)
-- A dimensão fica gravada na tabela na criação; trocar de modelo depois exige migração nova.
--
-- As tabelas são criadas no primeiro schema do search_path (o executor o define);
-- a extensão vector fica sempre em public.

CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;

-- conversa e aprendizado ---------------------------------------------------

CREATE TABLE turns (
    id            bigserial PRIMARY KEY,
    at            timestamptz NOT NULL DEFAULT now(),
    satellite     text,
    text_heard    text,
    text_final    text,
    intent        text,
    routed_local  boolean NOT NULL DEFAULT false,
    reply         text,
    mood          text,
    cost_usd      numeric(12, 6) NOT NULL DEFAULT 0
);
CREATE INDEX turns_at_idx ON turns (at);

CREATE TABLE corrections (
    id          bigserial PRIMARY KEY,
    heard       text NOT NULL,
    correct     text NOT NULL,
    uses        integer NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (heard, correct)
);

-- gírias, nomes, apelidos
CREATE TABLE vocab (
    term    text NOT NULL,
    kind    text NOT NULL,
    weight  real NOT NULL DEFAULT 1,
    PRIMARY KEY (term, kind)
);

-- perfil compacto (≤ 300 tokens); linha única
CREATE TABLE profile (
    id          smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    body        text NOT NULL DEFAULT '',
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memories (
    id          bigserial PRIMARY KEY,
    kind        text NOT NULL,
    body        text NOT NULL,
    embedding   public.vector({{MEMORIES_DIM}}),
    turn_id     bigint REFERENCES turns (id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX memories_embedding_hnsw ON memories USING hnsw (embedding public.vector_cosine_ops);

CREATE TABLE help_log (
    id          bigserial PRIMARY KEY,
    game_appid  bigint,
    topic       text,
    step        integer,
    at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX help_log_game_idx ON help_log (game_appid, at);

CREATE TABLE mood_events (
    id      bigserial PRIMARY KEY,
    at      timestamptz NOT NULL DEFAULT now(),
    signal  text NOT NULL,
    value   real
);
CREATE INDEX mood_events_at_idx ON mood_events (at);

CREATE TABLE costs (
    id             bigserial PRIMARY KEY,
    at             timestamptz NOT NULL DEFAULT now(),
    provider       text NOT NULL,
    task           text NOT NULL,
    model          text,
    input_units    bigint NOT NULL DEFAULT 0,
    output_units   bigint NOT NULL DEFAULT 0,
    usd            numeric(12, 6) NOT NULL DEFAULT 0
);
CREATE INDEX costs_at_idx ON costs (at);

-- música --------------------------------------------------------------------

-- signal: -1, +1, +2, -99 (nunca)
CREATE TABLE music_signals (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    track_uri  text,
    artist     text,
    context    jsonb NOT NULL DEFAULT '{}'::jsonb,
    signal     smallint NOT NULL CHECK (signal IN (-99, -1, 1, 2))
);
CREATE INDEX music_signals_artist_idx ON music_signals (artist);

-- '' em artist ou genre = peso só do outro
CREATE TABLE taste (
    artist  text NOT NULL DEFAULT '',
    genre   text NOT NULL DEFAULT '',
    weight  real NOT NULL DEFAULT 0,
    PRIMARY KEY (artist, genre)
);

-- notícias ------------------------------------------------------------------

CREATE TABLE news_sources (
    id     serial PRIMARY KEY,
    name   text NOT NULL,
    kind   text NOT NULL,
    url    text NOT NULL UNIQUE,
    trust  smallint NOT NULL DEFAULT 1 CHECK (trust BETWEEN 1 AND 3)
);

CREATE TABLE news_raw (
    id            bigserial PRIMARY KEY,
    source_id     integer REFERENCES news_sources (id) ON DELETE SET NULL,
    url           text NOT NULL UNIQUE,
    title         text,
    body          text,
    published_at  timestamptz,
    fetched_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX news_raw_source_idx ON news_raw (source_id);

CREATE TABLE news_items (
    id            bigserial PRIMARY KEY,
    title         text NOT NULL,
    summary       text,
    embedding     public.vector({{NEWS_DIM}}),
    first_seen    timestamptz NOT NULL DEFAULT now(),
    sources       integer NOT NULL DEFAULT 1,
    max_trust     smallint,
    franchise     text,
    kind          text,
    spoiler       jsonb,
    priority      real,
    level         text,
    delivered_at  timestamptz
);
CREATE INDEX news_items_embedding_hnsw ON news_items USING hnsw (embedding public.vector_cosine_ops);
CREATE INDEX news_items_first_seen_idx ON news_items (first_seen);
CREATE INDEX news_items_franchise_idx ON news_items (franchise);

CREATE TABLE news_item_sources (
    item_id  bigint NOT NULL REFERENCES news_items (id) ON DELETE CASCADE,
    raw_id   bigint NOT NULL REFERENCES news_raw (id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, raw_id)
);

CREATE TABLE franchise_prefs (
    franchise    text PRIMARY KEY,
    weight       real NOT NULL DEFAULT 1,
    dropped      boolean NOT NULL DEFAULT false,
    spoilers_ok  boolean NOT NULL DEFAULT false
);

-- episódio visto, horas jogadas
CREATE TABLE progress (
    franchise   text NOT NULL,
    kind        text NOT NULL,
    value       text,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (franchise, kind)
);

CREATE TABLE news_feedback (
    id       bigserial PRIMARY KEY,
    item_id  bigint NOT NULL REFERENCES news_items (id) ON DELETE CASCADE,
    at       timestamptz NOT NULL DEFAULT now(),
    signal   smallint NOT NULL
);
CREATE INDEX news_feedback_item_idx ON news_feedback (item_id);
