"""Testes do ``CorrectionsRepo`` em Postgres (tarefa 1.6), num schema temporário."""

from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import CorrectionsRepo as CorrectionsRepoProto
from magi.memory import migrate as mig
from magi.memory.corrections_repo import CorrectionsRepo

pytestmark = pytest.mark.db


@pytest.fixture
async def repo():
    name = f"test_corr_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=name, memories_dim=3, news_dim=2)
        conn = await psycopg.AsyncConnection.connect(mig.dsn_from_env())
        await conn.execute("SELECT set_config('search_path', %s, false)", [f'"{name}", public'])
        await conn.commit()
        try:
            yield CorrectionsRepo(conn)
        finally:
            await conn.close()
    finally:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


async def test_crud(repo):
    assert isinstance(repo, CorrectionsRepoProto)
    a = await repo.add(" valoran ", "Valorant")
    assert (a.heard, a.correct, a.uses) == ("valoran", "Valorant", 0)
    assert a.id is not None and a.created_at is not None
    b = await repo.add("dota dois", "Dota 2")

    await repo.bump(a.id)
    await repo.bump(a.id)
    rows = await repo.all()
    assert [(r.heard, r.uses) for r in rows] == [("valoran", 2), ("dota dois", 0)]

    # mesmo heard e mesmo correct: mantém uses
    assert (await repo.add("valoran", "Valorant")).uses == 2
    # mesmo heard, correct novo: atualiza o par (mesmo id) e zera uses
    c = await repo.add("valoran", "VALORANT")
    assert (c.id, c.correct, c.uses) == (a.id, "VALORANT", 0)
    assert len(await repo.all()) == 2

    await repo.delete(b.id)
    assert [r.heard for r in await repo.all()] == ["valoran"]
    with pytest.raises(ValueError):
        await repo.add(" ", "x")
