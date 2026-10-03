"""``PgMemoriesRepo`` e ``PgTurnsRepo`` em Postgres (tarefa 4.1), num schema temporário."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import MemoriesRepo, Memory, TurnRecord, TurnsRepo
from magi.memory import migrate as mig
from magi.memory.memories_repo import MemoryStore, PgMemoriesRepo, PgTurnsRepo
from tests.memory.fake_embed import DIM, FakeEmbed, vector

pytestmark = pytest.mark.db


@pytest.fixture
async def connect():
    name = f"test_mem_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    conns: list[psycopg.AsyncConnection] = []

    async def open_conn() -> psycopg.AsyncConnection:
        conn = await psycopg.AsyncConnection.connect(mig.dsn_from_env(), autocommit=True)
        await conn.execute("SELECT set_config('search_path', %s, false)", [f'"{name}", public'])
        conns.append(conn)
        return conn

    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=name, memories_dim=DIM, news_dim=2)
        yield open_conn
    finally:
        for conn in conns:
            await conn.close()
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


async def test_memories_crud_and_search(connect):
    repo = PgMemoriesRepo(await connect())
    assert isinstance(repo, MemoriesRepo)
    turns = PgTurnsRepo(await connect())
    tid = await turns.add(TurnRecord("pc", "x", "x", datetime.now(UTC)))
    a = await repo.add(
        Memory("game", "Pedro está jogando Elden Ring", turn_id=tid), vector("Pedro está jogando Elden Ring")
    )
    b = await repo.add(Memory("fact", "Pedro gosta de café"), vector("Pedro gosta de café"))

    hits = await repo.search(vector("elden ring"), min_score=0.3)
    assert [h.id for h in hits] == [a] and 0.3 < hits[0].score <= 1.0 and hits[0].turn_id == tid
    assert await repo.search(vector("capital da frança"), min_score=0.3) == []
    assert len(await repo.search(vector("pedro"), limit=1)) == 1
    assert [m.id for m in await repo.recent()] == [b, a]

    assert await repo.delete_by_turn(tid) == 1
    await repo.delete(b)
    assert await repo.recent() == []


async def test_fact_recalled_next_day_and_forgotten(connect):
    day1 = MemoryStore(PgMemoriesRepo(await connect()), FakeEmbed())
    day1.remember("Pedro está jogando Elden Ring", "game")
    await day1.drain()

    day2 = MemoryStore(PgMemoriesRepo(await connect()), FakeEmbed())  # conexão nova = outro dia
    assert [m.body for m in await day2.relevant("qual jogo elden ring?")] == ["Pedro está jogando Elden Ring"]
    gone = await day2.forget_last()
    assert gone is not None and gone.body == "Pedro está jogando Elden Ring"
    assert await day2.relevant("elden ring") == []


async def test_turns_history(connect):
    repo = PgTurnsRepo(await connect())
    assert isinstance(repo, TurnsRepo)
    t0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
    a = await repo.add(TurnRecord("pc", "oi magui", "oi magui", t0, reply="Oi!", mood=3, cost_usd=0.0012))
    b = await repo.add(
        TurnRecord("sala", "abre hades", "abre Hades", t0, intent="game.open", routed_local=True)
    )
    last = await repo.last()
    assert last is not None and (last.id, last.intent, last.routed_local, last.mood) == (
        b,
        "game.open",
        True,
        None,
    )
    pc = await repo.last("pc")
    assert pc is not None and (pc.id, pc.reply, pc.mood, pc.at) == (a, "Oi!", 3, t0)
    assert pc.cost_usd == pytest.approx(0.0012)
    assert [t.id for t in await repo.recent()] == [b, a]
    await repo.delete(b)
    assert [t.id for t in await repo.recent()] == [a]
    assert await repo.delete_all() == 1
    assert await repo.last() is None
