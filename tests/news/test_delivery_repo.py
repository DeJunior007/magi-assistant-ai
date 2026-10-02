"""``PgNewsRepo``: pontuação e entrega (6.10). Só em schema temporário (Postgres compartilhado)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import NewsLevel, NewsRaw, NewsSource, Progress
from magi.memory import migrate as mig
from magi.news.repo import PgNewsRepo

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


@pytest.fixture
def schema():
    name = f"test_deliv_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=name)
        yield name
    finally:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


async def _item(repo, title, *, kind="data", level=None, prio=None, age_h=0):
    cur = await repo.conn.execute(
        "INSERT INTO news_items (title, first_seen, kind, level, priority) VALUES (%s, %s, %s, %s, %s)"
        " RETURNING id",
        [title, NOW - timedelta(hours=age_h), kind, level, prio],
    )
    return (await cur.fetchone())[0]


@pytest.mark.db
async def test_pontuacao_e_entrega(schema):
    repo = await PgNewsRepo.connect(mig.dsn_from_env(), schema=schema)
    try:
        alta = await _item(repo, "alta", level="alta", prio=0.7)
        bomba = await _item(repo, "bomba", level="bomba", prio=0.9, age_h=5)
        await _item(repo, "normal", level="normal", prio=0.5)
        sem_nivel = await _item(repo, "sem nível")
        await _item(repo, "não classificado", kind=None)
        assert [i.id for i in await repo.unscored()] == [sem_nivel]

        got = await repo.undelivered([NewsLevel.BOMBA, NewsLevel.ALTA])
        assert [i.id for i in got] == [bomba, alta]
        await repo.mark_delivered(bomba, NOW)
        await repo.mark_delivered(bomba, NOW + timedelta(hours=1))  # idempotente
        got = await repo.undelivered([NewsLevel.BOMBA, NewsLevel.ALTA])
        assert [i.id for i in got] == [alta]
        cur = await repo.conn.execute("SELECT delivered_at FROM news_items WHERE id = %s", [bomba])
        assert (await cur.fetchone())[0] == NOW

        low = await repo.upsert_source(NewsSource("blog", "rss", "https://blog.example/feed", 1))
        high = await repo.upsert_source(NewsSource("oficial", "rss", "https://ofc.example/feed", 3))
        r1 = await repo.add_raw(NewsRaw(low, "https://blog.example/a", "a"))
        r2 = await repo.add_raw(NewsRaw(high, "https://ofc.example/a", "a"))
        await repo.attach_raw(alta, r1)
        await repo.attach_raw(alta, r2)
        assert await repo.item_links([alta, bomba]) == {
            alta: ["https://ofc.example/a", "https://blog.example/a"]
        }

        await repo.set_progress(Progress("Frieren: Beyond Journey's End", "episode", 28.0, NOW))
        await repo.set_progress(Progress("Hollow Knight", "hours", 80.0, NOW))
        assert [p.franchise for p in await repo.all_progress()] == [
            "Frieren: Beyond Journey's End", "Hollow Knight"
        ]
    finally:
        await repo.close()
