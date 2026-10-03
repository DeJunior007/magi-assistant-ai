"""Retorno e aprendizado das notícias (6.11): fakes + ``PgNewsRepo`` em schema temporário."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from magi.common.config import ConfigError
from magi.common.contracts import (
    ActionRequest,
    FranchisePref,
    Intent,
    IntentId,
    NewsItem,
    NewsLevel,
    Slot,
    TurnContext,
    WakeSource,
)
from magi.news.feedback import (
    SAY_NO_DB,
    SAY_NO_ITEM,
    SAY_SAME,
    FeedbackConfig,
    NewsFeedback,
    NewsFeedbackHandler,
)
from magi.news.priority import score_pending

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


class FakeRepo:
    def __init__(self) -> None:
        self.items: dict[int, NewsItem] = {}
        self.prefs: dict[str, FranchisePref] = {}
        self.feedback: list[tuple[int, int, datetime]] = []
        self.updated: dict[int, NewsItem] = {}

    def add(self, iid, franchise="Silksong", *, delivered_h: float | None = 0.5, level=None):
        deliv = None if delivered_h is None else NOW - timedelta(hours=delivered_h)
        self.items[iid] = NewsItem(
            title=f"n{iid}", first_seen=NOW - timedelta(hours=(delivered_h or 0) + 1), sources=2,
            max_trust=3, franchise=franchise, kind="data", spoiler={"size": 1.0},
            level=level, delivered_at=deliv, id=iid,
        )

    async def delivered_recent(self, limit=50):
        got = [i for i in self.items.values() if i.delivered_at is not None]
        got.sort(key=lambda i: (i.delivered_at, i.id), reverse=True)
        return got[:limit]

    async def feedback_signals(self, ids):
        out: dict[int, list[int]] = {}
        for iid, sig, _ in self.feedback:
            if iid in ids:
                out.setdefault(iid, []).append(sig)
        return out

    async def add_feedback(self, item_id, signal, at):
        self.feedback.append((item_id, signal, at))

    async def franchise_prefs(self):
        return list(self.prefs.values())

    async def set_franchise_pref(self, pref):
        self.prefs[pref.franchise] = pref

    async def unscored(self, limit=100):
        return [i for i in self.items.values() if i.level is None]

    async def update_item(self, item):
        self.items[item.id] = item
        self.updated[item.id] = item


def ctx() -> TurnContext:
    return TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=NOW)


def req(intent: IntentId, *slots: Slot) -> ActionRequest:
    return ActionRequest(intent=Intent(intent.value, slots=tuple(slots)), ctx=ctx())


def fb(repo, **kw) -> NewsFeedback:
    return NewsFeedback(repo, FeedbackConfig(**kw), now=lambda: NOW)


async def test_tema_rejeitado_cai_de_nivel_na_execucao_seguinte():
    repo = FakeRepo()
    repo.add(1, delivered_h=None)
    await score_pending(repo, NOW)
    assert repo.items[1].level is NewsLevel.ALTA  # gosto padrão 0,3

    repo.items[1] = replace(repo.items[1], delivered_at=NOW - timedelta(minutes=5))
    res = await NewsFeedbackHandler(fb(repo)).run(req(IntentId.NEWS_DISLIKE))
    assert res.ok
    assert repo.feedback == [(1, -1, NOW)]
    assert repo.prefs["Silksong"].weight == pytest.approx(0.05)

    repo.add(2, delivered_h=None)  # próxima notícia da mesma obra
    await score_pending(repo, NOW)
    assert repo.items[2].level is NewsLevel.NORMAL


async def test_mais_disso_sobe():
    repo = FakeRepo()
    repo.prefs["Silksong"] = FranchisePref("Silksong", weight=0.6)
    repo.add(1)
    res = await NewsFeedbackHandler(fb(repo)).run(req(IntentId.NEWS_MORE))
    assert res.ok and repo.feedback == [(1, 1, NOW)]
    assert repo.prefs["Silksong"].weight == pytest.approx(0.85)
    repo.add(2, delivered_h=None)
    await score_pending(repo, NOW)
    assert repo.items[2].level is NewsLevel.BOMBA
    # limite 1
    await fb(repo).signal(-1)
    await fb(repo, step=1.0).signal(1)
    assert repo.prefs["Silksong"].weight == 1.0


async def test_idempotente_e_sem_noticia_recente():
    repo = FakeRepo()
    h = NewsFeedbackHandler(fb(repo))
    assert (await h.run(req(IntentId.NEWS_DISLIKE))).speech == SAY_NO_ITEM
    repo.add(1, delivered_h=10)  # fora de recent_h
    assert (await h.run(req(IntentId.NEWS_DISLIKE))).speech == SAY_NO_ITEM
    repo.add(2)
    await h.run(req(IntentId.NEWS_DISLIKE))
    assert (await h.run(req(IntentId.NEWS_DISLIKE))).speech == SAY_SAME
    assert len(repo.feedback) == 1
    assert repo.prefs["Silksong"].weight == pytest.approx(0.05)
    assert (await NewsFeedbackHandler(NewsFeedback()).run(req(IntentId.NEWS_MORE))).speech == SAY_NO_DB


async def test_ignorado_3x_cai():
    repo = FakeRepo()
    repo.prefs["Silksong"] = FranchisePref("Silksong", weight=0.5)
    for iid, h in ((1, 30), (2, 20), (3, 10)):
        repo.add(iid, delivered_h=h)
    repo.add(4, "Frieren", delivered_h=5)
    repo.add(5, "Frieren", delivered_h=4)
    f = fb(repo)
    assert await f.apply_ignored() == ["Silksong"]
    assert repo.prefs["Silksong"].weight == pytest.approx(0.4)
    assert "Frieren" not in repo.prefs  # só 2 entregas
    assert sorted(i for i, s, _ in repo.feedback if s == 0) == [1, 2, 3]
    assert await f.apply_ignored() == []  # idempotente: a sequência recomeça
    assert repo.prefs["Silksong"].weight == pytest.approx(0.4)

    repo.add(6, delivered_h=3)
    repo.add(7, delivered_h=2.5)
    repo.add(8, delivered_h=0.5)  # dentro da carência: ainda pode reagir
    assert await f.apply_ignored() == []


async def test_ignorado_com_interacao_nao_conta():
    repo = FakeRepo()
    for iid, h in ((1, 30), (2, 20), (3, 10)):
        repo.add(iid, delivered_h=h)
    repo.feedback.append((2, 1, NOW))
    assert await fb(repo).apply_ignored() == []


async def test_obra_largada_some():
    repo = FakeRepo()
    repo.prefs["Frieren"] = FranchisePref("Frieren", weight=0.9)
    res = await NewsFeedbackHandler(fb(repo)).run(
        req(IntentId.NEWS_DROP, Slot("franchise", "frieren", raw="frieren", display="frieren"))
    )
    assert res.ok and repo.prefs["Frieren"].dropped and repo.prefs["Frieren"].weight == 0.9
    repo.add(1, "Frieren", delivered_h=None)
    await score_pending(repo, NOW)
    assert repo.items[1].level is NewsLevel.GUARDADA and repo.items[1].priority == 0.0
    assert not (await NewsFeedbackHandler(fb(repo)).run(req(IntentId.NEWS_DROP))).ok


def test_config():
    assert FeedbackConfig.from_raw({"step": 0.1, "ignored_after": 4}).ignored_after == 4
    with pytest.raises(ConfigError):
        FeedbackConfig.from_raw({"step": 0})


# --- Postgres (schema temporário) -------------------------------------------------------------


@pytest.fixture
def schema():
    from magi.memory import migrate as mig

    name = f"test_fb_{uuid.uuid4().hex[:10]}"
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


@pytest.mark.db
async def test_pg_retorno(schema):
    from magi.memory import migrate as mig
    from magi.news.repo import PgNewsRepo

    repo = await PgNewsRepo.connect(mig.dsn_from_env(), schema=schema)
    try:
        ids = []
        for h in (30, 20, 10):
            cur = await repo.conn.execute(
                "INSERT INTO news_items (title, first_seen, kind, franchise, level, priority, delivered_at)"
                " VALUES ('x', %s, 'data', 'Silksong', 'alta', 0.7, %s) RETURNING id",
                [NOW - timedelta(hours=h + 1), NOW - timedelta(hours=h)],
            )
            ids.append((await cur.fetchone())[0])
        assert [i.id for i in await repo.delivered_recent()] == ids[::-1]
        f = fb(repo)
        assert await f.apply_ignored() == ["Silksong"]
        assert (await repo.feedback_signals(ids)) == {i: [0] for i in ids}
        (pref,) = await repo.franchise_prefs()
        assert pref.weight == pytest.approx(0.2)
        assert await f.apply_ignored() == []
    finally:
        await repo.close()
