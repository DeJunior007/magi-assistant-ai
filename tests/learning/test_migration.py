"""Migração ``003_learning.sql`` (tarefa LM1.1; spec §8, CA-15; DAT-003, LM-010).

O teste com banco usa só o schema ``learning_test`` (apagado no fim por ele mesmo); nunca o
``public``. Sem Postgres no ar ele é pulado.
"""

from __future__ import annotations

import re

import psycopg
import pytest
from psycopg import sql

from magi.memory import migrate as mig

SCHEMA = "learning_test"
SQL_FILE = mig.MIGRATIONS_DIR / "003_learning.sql"
LEARNING_TABLES = {
    "learning_sessions", "learning_messages", "learning_observations",
    "learning_action_results", "learning_saved_words",
}


# --- sem banco ---------------------------------------------------------------------------------


def test_arquivo_sem_drop_nem_vector():
    text = SQL_FILE.read_text(encoding="utf-8")
    assert not re.search(r"drop|vector", text, re.IGNORECASE)
    assert not re.search(r"\bALTER\b", text, re.IGNORECASE)
    code = re.sub(r"--[^\n]*", "", text)
    assert not re.search(r"\b(DELETE|TRUNCATE)\b", code, re.IGNORECASE)


def test_so_cria_objetos_learning():
    text = SQL_FILE.read_text(encoding="utf-8")
    created = re.findall(r"CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\s+(\w+)", text, re.IGNORECASE)
    assert created and all(name.startswith("learning_") for name in created)
    assert set(re.findall(r"CREATE TABLE (\w+)", text)) == LEARNING_TABLES


def test_esta_na_lista_de_migracoes():
    found = [(m.version, m.name) for m in mig.available_migrations()]
    assert ("003", "learning") in found


# --- com banco (schema learning_test) ----------------------------------------------------------


@pytest.fixture
def conn():
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    drop = sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(SCHEMA))
    admin.execute(drop)
    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            yield c
    finally:
        admin.execute(drop)  # só o schema de teste (regra 6 de tasks.md)
        admin.close()


def _columns(conn, table):
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
        [SCHEMA, table],
    ).fetchall()
    return {r[0] for r in rows}


@pytest.mark.db
def test_aplica_e_e_idempotente(conn):
    applied = mig.migrate(conn, schema=SCHEMA, memories_dim=3, news_dim=2)
    assert "003" in applied
    tables = {
        r[0] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", [SCHEMA]
        ).fetchall()
    }
    assert LEARNING_TABLES <= tables
    assert {"topic", "topics", "summary"} <= _columns(conn, "learning_sessions")
    assert "removed_at" in _columns(conn, "learning_saved_words")
    idx = conn.execute(
        "SELECT indexdef FROM pg_indexes"
        " WHERE schemaname = %s AND indexname = 'learning_saved_words_active_idx'",
        [SCHEMA],
    ).fetchone()
    assert idx is not None and "UNIQUE" in idx[0] and "removed_at IS NULL" in idx[0]

    # aplicar de novo não faz nada
    assert mig.migrate(conn, schema=SCHEMA, memories_dim=3, news_dim=2) == []
    versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions.count("003") == 1
