"""Testes do ``MusicSignalsRepo`` e do peso efetivo (tarefa 2.4), num schema temporário."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import MusicSignal, MusicSignalValue, TasteEntry
from magi.common.contracts import MusicSignalsRepo as MusicSignalsProto
from magi.core.music import import_taste as it
from magi.memory import migrate as mig
from magi.memory.music_signals_repo import MusicSignalsRepo
from magi.memory.taste_repo import TasteRepo

pytestmark = pytest.mark.db
V = MusicSignalValue
T0 = datetime(2026, 10, 2, 20, tzinfo=UTC)


@pytest.fixture
async def conn():
    name = f"test_sig_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=name, memories_dim=3, news_dim=2)
        aconn = await psycopg.AsyncConnection.connect(mig.dsn_from_env(), autocommit=True)
        await aconn.execute("SELECT set_config('search_path', %s, false)", [f'"{name}", public'])
        try:
            yield aconn
        finally:
            await aconn.close()
    finally:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


def sig(uri, artist, value, minutes=0, **ctx):
    return MusicSignal(uri, artist, value, T0 + timedelta(minutes=minutes), ctx)


async def test_add_recent_banned(conn):
    repo = MusicSignalsRepo(conn)
    assert isinstance(repo, MusicSignalsProto)
    await repo.add(sig("spotify:track:1", "A", V.SKIPPED, 0, picked=True, hour=20))
    await repo.add(sig("spotify:track:2", "B", V.NEVER, 1))
    await repo.add(sig("spotify:track:3", "A", V.LIKED, 2))
    assert await repo.banned_tracks() == {"spotify:track:2"}
    rec = await repo.recent()
    assert [r.track_uri[-1] for r in rec] == ["3", "2", "1"]
    assert rec[2].signal == V.SKIPPED and rec[2].context == {"picked": True, "hour": 20}
    assert len(await repo.recent(limit=1)) == 1


async def test_reimport_preserves_signals(conn):
    taste, signals = TasteRepo(conn), MusicSignalsRepo(conn)
    await taste.upsert([TasteEntry("A", "", 1.0), TasteEntry("B", "", 0.5)])
    await signals.add(sig("spotify:track:1", "A", V.LIKED))  # +0.15
    await signals.add(sig("spotify:track:2", "A", V.SKIPPED))  # -0.05
    await signals.add(sig("spotify:track:3", "B", V.FINISHED))  # +0.02
    await signals.add(sig("spotify:track:4", "Z", V.LIKED))  # artista fora do taste
    await taste.adjust("B", 0.1)

    class Api:
        async def get(self, path, params=None):
            if path == "/me/top/artists" and params["time_range"] == "short_term":
                return {"items": [{"name": "B"}, {"name": "A"}]}
            return {"items": []}

    # reimportação (2.3): B vira 1.0 e A 0.98; sinais e ajuste continuam valendo
    rep = await it.import_taste(Api(), taste)
    assert {e.artist: e.weight for e in rep.entries} == {"B": 1.0, "A": 0.98}
    top = {e.artist: e.weight for e in await taste.top()}
    assert top["A"] == pytest.approx(0.98 + 0.10, abs=1e-4)
    assert top["B"] == pytest.approx(1.0 + 0.1 + 0.02, abs=1e-4)
    assert top["Z"] == pytest.approx(0.15, abs=1e-4)
    assert [e.artist for e in await taste.top()] == ["B", "A", "Z"]
    assert await taste.count() == 2  # sinais não viram linhas do taste
