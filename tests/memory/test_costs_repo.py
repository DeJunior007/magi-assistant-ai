"""Testes do ``CostsRepo`` em Postgres (tarefa 3.2), num schema temporário."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import CostsRepo as CostsRepoProto
from magi.common.contracts import ProviderTask, Usage
from magi.memory import migrate as mig
from magi.memory.costs_repo import TZ, CostsRepo, month_bounds

pytestmark = pytest.mark.db


@pytest.fixture
async def repo():
    name = f"test_costs_{uuid.uuid4().hex[:10]}"
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
            yield CostsRepo(conn), conn
        finally:
            await conn.close()
    finally:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


def test_month_bounds():
    assert month_bounds(2026, 12) == (datetime(2026, 12, 1, tzinfo=TZ), datetime(2027, 1, 1, tzinfo=TZ))


async def test_add_and_month_total(repo):
    r, conn = repo
    assert isinstance(r, CostsRepoProto)
    u = Usage("openai", ProviderTask.STT, "stt-m", input_units=12.6, output_units=0, usd=0.25)
    i = await r.add(u, datetime(2026, 10, 15, tzinfo=TZ))
    assert i > 0
    await r.add(
        Usage("openai", ProviderTask.AGENT, "a", 10, 20, usd=0.5), datetime(2026, 10, 31, 23, tzinfo=TZ)
    )
    # 02:00 UTC de 1/10 ainda é 30/9 em São Paulo
    await r.add(Usage("gemini", ProviderTask.SEARCH, "", usd=1.0), datetime(2026, 10, 1, 2, tzinfo=UTC))
    await r.add(Usage("openai", ProviderTask.TTS, "t", usd=2.0), datetime(2026, 11, 1, 0, 0, tzinfo=TZ))

    assert await r.month_total(2026, 10) == pytest.approx(0.75)
    assert await r.month_total(2026, 9) == pytest.approx(1.0)
    assert await r.month_total(2026, 11) == pytest.approx(2.0)
    assert await r.month_total(2025, 1) == 0.0

    cur = await conn.execute(
        "SELECT provider, task, model, input_units, output_units FROM costs WHERE id = %s", [i]
    )
    assert await cur.fetchone() == ("openai", "stt", "stt-m", 13, 0)
    with pytest.raises(ValueError):
        await r.add(u, datetime(2026, 10, 1))
