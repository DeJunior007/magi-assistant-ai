"""Testes do executor de migrações (tarefa 0.3).

Os marcados com ``db`` usam o Postgres de desenvolvimento (deploy/docker-compose.yml) num schema
temporário por teste, apagado no fim; sem banco no ar eles são pulados.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import sql

from magi.memory import migrate as mig

TABLES = {
    "turns", "corrections", "vocab", "profile", "memories", "help_log", "mood_events", "costs",
    "music_signals", "taste", "news_sources", "news_raw", "news_items", "news_item_sources",
    "franchise_prefs", "progress", "news_feedback", "schema_migrations",
}


# --- sem banco ---------------------------------------------------------------


def test_lista_migracoes():
    found = mig.available_migrations()
    assert [m.version for m in found][:1] == ["001"]
    assert found[0].name == "init"


def test_render_troca_dimensoes():
    text = mig.available_migrations()[0].render({"MEMORIES_DIM": 1024, "NEWS_DIM": 384})
    assert "vector(1024)" in text
    assert "vector(384)" in text
    assert "{{" not in text


def test_render_sem_valor_falha(tmp_path):
    p = tmp_path / "001_x.sql"
    p.write_text("SELECT {{OUTRO}};")
    with pytest.raises(ValueError):
        mig.Migration("001", "x", p).render({"MEMORIES_DIM": 1})


def test_dimensoes_padrao_env_e_parametro(monkeypatch):
    monkeypatch.delenv("MAGI_EMBED_DIM_MEMORIES", raising=False)
    monkeypatch.delenv("MAGI_EMBED_DIM_NEWS", raising=False)
    assert mig.embedding_dims() == {"MEMORIES_DIM": 1536, "NEWS_DIM": 768}
    monkeypatch.setenv("MAGI_EMBED_DIM_MEMORIES", "1024")
    assert mig.embedding_dims()["MEMORIES_DIM"] == 1024
    assert mig.embedding_dims(memories_dim=512)["MEMORIES_DIM"] == 512
    with pytest.raises(ValueError):
        mig.embedding_dims(memories_dim=3072)
    with pytest.raises(ValueError):
        mig.embedding_dims(news_dim=0)


def test_dsn_padrao(monkeypatch):
    monkeypatch.delenv("MAGI_DB_DSN", raising=False)
    assert mig.dsn_from_env() == "postgresql://magi:magi@127.0.0.1:54329/magi"
    monkeypatch.setenv("MAGI_DB_DSN", "postgresql://x@h/y")
    assert mig.dsn_from_env() == "postgresql://x@h/y"


# --- com banco ---------------------------------------------------------------


@pytest.fixture
def schema():
    name = f"test_migrate_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    try:
        yield name
    finally:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


@pytest.fixture
def conn():
    with psycopg.connect(mig.dsn_from_env(), connect_timeout=3) as c:
        yield c


def _tables(conn, schema):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", [schema]
    ).fetchall()
    return {r[0] for r in rows}


def _dim(conn, schema, table):
    return conn.execute(
        """
        SELECT a.atttypmod FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND a.attname = 'embedding'
        """,
        [schema, table],
    ).fetchone()[0]


@pytest.mark.db
def test_cria_esquema_e_e_idempotente(schema, conn):
    assert mig.migrate(conn, schema=schema) == ["001"]
    assert _tables(conn, schema) == TABLES
    assert _dim(conn, schema, "memories") == 1536
    assert _dim(conn, schema, "news_items") == 768
    hnsw = conn.execute(
        "SELECT tablename FROM pg_indexes WHERE schemaname = %s AND indexdef ILIKE '%%USING hnsw%%'",
        [schema],
    ).fetchall()
    assert sorted(r[0] for r in hnsw) == ["memories", "news_items"]

    assert mig.migrate(conn, schema=schema) == []
    rows = conn.execute("SELECT version, params FROM schema_migrations").fetchall()
    assert rows == [("001", {"MEMORIES_DIM": 1536, "NEWS_DIM": 768})]


@pytest.mark.db
def test_dimensao_por_parametro_e_busca_vetorial(schema, conn):
    mig.migrate(conn, schema=schema, memories_dim=3, news_dim=2)
    assert _dim(conn, schema, "memories") == 3
    assert _dim(conn, schema, "news_items") == 2
    with conn.transaction():
        conn.execute(
            "INSERT INTO memories (kind, body, embedding) VALUES"
            " ('fato', 'gosta de Zelda', '[1,0,0]'), ('fato', 'odeia fila', '[0,1,0]')"
        )
    best = conn.execute(
        "SELECT body FROM memories ORDER BY embedding <=> '[0.9,0.1,0]' LIMIT 1"
    ).fetchone()[0]
    assert best == "gosta de Zelda"
    with pytest.raises(psycopg.errors.DataException):
        with conn.transaction():
            conn.execute("INSERT INTO memories (kind, body, embedding) VALUES ('x', 'y', '[1,2]')")


@pytest.mark.db
def test_restricoes_basicas(schema, conn):
    mig.migrate(conn, schema=schema, memories_dim=3, news_dim=2)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("INSERT INTO profile (id, body) VALUES (2, 'x')")
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("INSERT INTO news_sources (name, kind, url, trust) VALUES ('a', 'rss', 'u', 4)")
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute("INSERT INTO music_signals (track_uri, signal) VALUES ('t', 5)")


@pytest.mark.db
def test_cli(schema, capsys):
    assert mig.main(["--schema", schema, "--memories-dim", "4", "--news-dim", "4"]) == 0
    assert "001" in capsys.readouterr().out
    assert mig.main(["--schema", schema]) == 0
    assert "atualizado" in capsys.readouterr().out
