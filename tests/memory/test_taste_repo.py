"""Testes do ``TasteRepo`` em Postgres (tarefa 2.3), num schema temporário."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import TasteEntry
from magi.common.contracts import TasteRepo as TasteRepoProto
from magi.memory import migrate as mig
from magi.memory.taste_repo import TasteRepo

pytestmark = pytest.mark.db


@pytest.fixture
async def repo():
    name = f"test_taste_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=name, memories_dim=3, news_dim=2)
        conn = await psycopg.AsyncConnection.connect(mig.dsn_from_env(), autocommit=True)
        await conn.execute("SELECT set_config('search_path', %s, false)", [f'"{name}", public'])
        try:
            yield TasteRepo(conn)
        finally:
            await conn.close()
    finally:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


async def test_upsert_idempotent_top_adjust(repo):
    assert isinstance(repo, TasteRepoProto)
    entries = [TasteEntry("A", "", 1.0), TasteEntry("B", "rock", 0.5), TasteEntry("C", "", 0.2)]
    await repo.upsert(entries)
    await repo.upsert(entries)
    assert await repo.count() == 3
    await repo.upsert([TasteEntry("B", "rock", 0.9), TasteEntry("", "", 5.0)])  # sem artista: ignora
    assert await repo.count() == 3
    assert [e.artist for e in await repo.top()] == ["A", "B", "C"]
    assert await repo.top(genre="rock") == [TasteEntry("B", "rock", pytest.approx(0.9))]
    assert len(await repo.top(limit=1)) == 1

    await repo.adjust("C", 1.0)
    await repo.adjust("Novo", -0.5)
    top = {e.artist: e.weight for e in await repo.top()}
    assert top["C"] == pytest.approx(1.2) and top["Novo"] == pytest.approx(-0.5)
    await repo.upsert([])
