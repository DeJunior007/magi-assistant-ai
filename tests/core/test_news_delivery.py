from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from magi.common.config import ConfigError
from magi.common.contracts import (
    CardLevel,
    CardMsg,
    FranchisePref,
    NewsItem,
    NewsLevel,
    Progress,
    SubtitleMsg,
)
from magi.core.proactive.news import DeliveryConfig, NewsDelivery
from magi.core.proactive.sink import ProactiveSink
from magi.news.spoiler import ReleaseStore

T0 = datetime(2026, 10, 2, 12, tzinfo=UTC)
SECRET = "himmel volta"


class Hud:
    def __init__(self):
        self.msgs = []

    async def send(self, msg):
        self.msgs.append(msg)


class Sat:
    def __init__(self, in_call=False):
        self.in_call = in_call
        self.spoken = []

    async def announce(self, text, expression=None):
        self.spoken.append(text)
        return True


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


class Repo:
    def __init__(self, items, prefs=(), progress=()):
        self.items = {i.id: i for i in items}
        self.prefs = list(prefs)
        self.rows = list(progress)
        self.marks = []

    async def undelivered(self, levels, limit=5):
        out = [i for i in self.items.values() if i.level in levels and i.delivered_at is None]
        out.sort(key=lambda i: (i.level is not NewsLevel.BOMBA, -(i.priority or 0)))
        return out[:limit]

    async def mark_delivered(self, item_id, at):
        self.marks.append(item_id)
        it = self.items[item_id]
        if it.delivered_at is None:
            self.items[item_id] = replace(it, delivered_at=at)

    async def item_links(self, ids):
        return {i: [f"https://news.example.com/{i}/{SECRET.replace(' ', '-')}"] for i in ids}

    async def franchise_prefs(self):
        return self.prefs

    async def set_franchise_pref(self, pref):
        pass

    async def progress(self, franchise):
        return [p for p in self.rows if p.franchise == franchise]


def news(iid, level, *, title="Silksong ganha data de lançamento", spoiler=None, franchise="Silksong",
         trust=3, age_h=1.0, prio=0.9):
    return NewsItem(
        title=title, franchise=franchise, kind="data", sources=2, max_trust=trust, id=iid,
        first_seen=T0 - timedelta(hours=age_h), priority=prio, level=level,
        spoiler=spoiler or {"has": False, "of": "", "safe_title": "", "size": 0.9},
    )


@pytest.fixture
def setup(tmp_path):
    def make(items, *, in_call=False, sats=True, cfg=None, **repo_kw):
        hud, sat, clock = Hud(), Sat(in_call), Clock()
        sink = ProactiveSink(hud, (lambda: [sat]) if sats else None)
        repo = Repo(items, **repo_kw)
        nd = NewsDelivery(sink, repo, cfg or DeliveryConfig(), now=clock,
                          store=ReleaseStore(tmp_path / "rel.json"))
        return nd, hud, sat, clock, repo, sink
    return make


async def test_bomba_falada_fora_de_call(setup):
    nd, hud, sat, _, repo, sink = setup([news(1, NewsLevel.BOMBA)])
    assert await nd.tick() == [1]
    await sink.drain()
    assert sat.spoken == ["Notícia bomba: Silksong ganha data de lançamento"]
    card = hud.msgs[0]
    assert card == CardMsg(CardLevel.BOMBA, "Silksong ganha data de lançamento",
                           "https://news.example.com/1/himmel-volta")
    assert repo.items[1].delivered_at == T0
    await sink.aclose()


async def test_alta_vira_card_sem_voz(setup):
    nd, hud, sat, *_ = setup([news(2, NewsLevel.ALTA, trust=1)])
    assert await nd.tick() == [2]
    assert sat.spoken == []
    assert hud.msgs == [CardMsg(CardLevel.ALTA, "Rumor: Silksong ganha data de lançamento",
                                "https://news.example.com/2/himmel-volta")]


async def test_em_call_bomba_nao_fala(setup):
    nd, hud, sat, *_ = setup([news(1, NewsLevel.BOMBA)], in_call=True)
    assert await nd.tick() == [1]
    assert sat.spoken == []
    assert [type(m) for m in hud.msgs] == [CardMsg, SubtitleMsg]


async def test_idempotente(setup):
    nd, hud, _, _, repo, sink = setup([news(1, NewsLevel.ALTA)])
    assert await nd.tick() == [1]
    assert await nd.tick() == []
    # banco não marcou (falha): a memória do laço segura a repetição
    repo.items[1] = replace(repo.items[1], delivered_at=None)
    assert await nd.tick() == []
    assert len(hud.msgs) == 1


async def test_limite_por_hora_e_dia(setup):
    items = [news(i, NewsLevel.ALTA, prio=0.7 - i / 100) for i in range(1, 5)]
    cfg = DeliveryConfig(max_per_hour=2, max_per_day=3)
    nd, hud, _, clock, repo, _ = setup(items, cfg=cfg)
    assert await nd.tick() == [1, 2]
    assert await nd.tick() == []  # limite da hora
    clock.t += timedelta(minutes=61)
    assert await nd.tick() == [3]  # limite do dia (3)
    # bomba ignora o limite da hora, não o do dia
    repo.items[9] = news(9, NewsLevel.BOMBA)
    assert await nd.tick() == []
    clock.t += timedelta(hours=24)
    assert await nd.tick() == [9, 4]


async def test_bomba_ignora_limite_da_hora(setup):
    items = [news(1, NewsLevel.ALTA, prio=0.7), news(2, NewsLevel.ALTA, prio=0.69)]
    nd, _, _, _, repo, sink = setup(items, cfg=DeliveryConfig(max_per_hour=2), sats=False)
    assert await nd.tick() == [1, 2]
    repo.items[3] = news(3, NewsLevel.BOMBA)
    assert await nd.tick() == [3]


async def test_velha_e_obra_largada_descartadas(setup):
    items = [news(1, NewsLevel.ALTA, age_h=72), news(2, NewsLevel.BOMBA, franchise="Overlord")]
    nd, hud, _, _, repo, _ = setup(items, prefs=[FranchisePref("overlord", dropped=True)])
    assert await nd.tick() == []
    assert hud.msgs == []
    assert sorted(repo.marks) == [1, 2]


async def test_spoiler_nunca_vaza(setup):
    sp = {"has": True, "of": "Frieren, ep. 20", "safe_title": "Frieren tem episódio novo", "size": 0.5}
    title = f"Frieren ep. 20: {SECRET} como demônio"
    items = [news(1, NewsLevel.BOMBA, title=title, spoiler=sp, franchise="Frieren"),
             news(2, NewsLevel.ALTA, title=title, spoiler=sp, franchise="Frieren", prio=0.7)]
    for progress, expect in (((), "Tem notícia de Frieren com spoiler"),
                             ([Progress("Frieren: Beyond Journey's End", "episode", 10.0, T0)],
                              "Frieren tem episódio novo")):
        nd, hud, sat, _, _, sink = setup(items, progress=progress)
        nd.repo.all_progress = lambda progress=progress: _async(list(progress))
        assert await nd.tick() == [1, 2]
        await sink.drain()
        await sink.aclose()
        assert sat.spoken == [f"Notícia bomba: {expect}"]
        for msg in hud.msgs:
            for f in fields(msg):
                value = getattr(msg, f.name)
                if isinstance(value, str):
                    assert "himmel" not in value.lower() and "demônio" not in value, (f.name, value)


async def _async(value):
    return value


def test_config():
    assert DeliveryConfig.from_raw(None) == DeliveryConfig()
    cfg = DeliveryConfig.from_raw({"max_per_hour": 1, "poll_s": 60, "enabled": False})
    assert (cfg.max_per_hour, cfg.poll_s, cfg.enabled) == (1, 60.0, False)
    for bad in ({"max_per_day": "x"}, {"enabled": "sim"}, {"batch": 0}, {"max_per_hour": 1.5}):
        with pytest.raises(ConfigError):
            DeliveryConfig.from_raw(bad)
