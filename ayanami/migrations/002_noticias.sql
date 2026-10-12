-- 002_noticias: tabelas de notícias da Ayanami (spec §3, [DS5], dono: Y0.3).
--
-- Cópia das news_*, franchise_prefs e progress de magi/memory/migrations/001_init.sql, com o mesmo
-- marcador {{NEWS_DIM}} trocado pelo mesmo renderizador (magi.memory.migrate.Migration.render);
-- o valor vem de [noticias] dim do ayanami.toml e tem de ser igual ao NEWS_DIM do PC.
-- Extras da sincronização: news_items.uid (chave natural com o PC), atualizado + índice e gatilho.

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

-- sincronização com o PC ([DS5], spec §5.2) ----------------------------------

ALTER TABLE news_items ADD COLUMN uid uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE;
ALTER TABLE news_items ADD COLUMN atualizado timestamptz NOT NULL DEFAULT now();
CREATE INDEX news_items_atualizado_idx ON news_items (atualizado, id);

CREATE FUNCTION news_items_toca() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.atualizado := now();
    RETURN NEW;
END
$$;
CREATE TRIGGER news_items_toca BEFORE UPDATE ON news_items
    FOR EACH ROW EXECUTE FUNCTION news_items_toca();
