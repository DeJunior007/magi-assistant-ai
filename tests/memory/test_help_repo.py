"""``PgHelpLogRepo`` em Postgres (tarefa 4.5), num schema temporário."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import HelpEntry, HelpLogRepo, HelpStep
from magi.memory import migrate as mig
from magi.memory.help import HelpTracker, PgHelpLogRepo
from tests.memory.fake_embed import DIM, FakeEmbed

pytestmark = pytest.mark.db

T0 = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)


@pytest.fixture
async def conn():
    name = f"test_help_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    c = None
    try:
        with psycopg.connect(mig.dsn_from_env()) as m:
            mig.migrate(m, schema=name, memories_dim=DIM, news_dim=2)
        c = await psycopg.AsyncConnection.connect(mig.dsn_from_env(), autocommit=True)
        await c.execute("SELECT set_config('search_path', %s, false)", [f'"{name}", public'])
        yield c
    finally:
        if c is not None:
            await c.close()
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


async def test_help_log_repo_and_next_step(conn):
    repo = PgHelpLogRepo(conn)
    assert isinstance(repo, HelpLogRepo)
    await repo.add(HelpEntry(game_appid=7, topic="boss da lua", step=HelpStep.HINT, at=T0))
    await repo.add(HelpEntry(game_appid=7, topic="mapa", step=HelpStep.HINT, at=T0 + timedelta(minutes=1)))
    assert await repo.last_step(7, "boss da lua") is HelpStep.HINT
    assert await repo.last_step(8, "boss da lua") is None
    assert await repo.topics(7) == ["mapa", "boss da lua"]
    assert await repo.count_since(7, "boss da lua", T0) == 1
    assert [e.step for e in await repo.entries(7, "boss da lua", T0)] == [HelpStep.HINT]

    clock = T0 + timedelta(minutes=5)
    tracker = HelpTracker(repo, FakeEmbed(), now=lambda: clock)
    d = await tracker.decide(7, "boss lua", session_start=T0 - timedelta(minutes=10))
    assert d.topic == "boss da lua" and d.step is HelpStep.DIRECT and d.requests == 2
    await tracker.record(d)
    assert await repo.last_step(7, "boss da lua") is HelpStep.DIRECT
