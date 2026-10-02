"""Tarefa 6.3: coletor AniList com respostas GraphQL falsas (``httpx.MockTransport``, sem rede)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from magi.news import sources as S
from magi.news.collect import anilist
from magi.news.collect.anilist import AniListCollector, AniListError, make_collector

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
URL = "https://graphql.anilist.co"


def src(**opts) -> S.SourceConfig:
    return S.SourceConfig("AniList", "anilist", URL, 2, options=opts, id=5)


def media(id_, title, status="FINISHED", type_="ANIME", start=None, season=None, year=None,
          next_ep=None, relations=(), description=None):
    y, m, d = (start or (None, None, None))
    return {
        "id": id_, "type": type_, "format": "TV", "status": status, "episodes": 12,
        "season": season, "seasonYear": year, "title": {"romaji": title, "english": None},
        "startDate": {"year": y, "month": m, "day": d}, "nextAiringEpisode": next_ep,
        "description": description,
        "relations": {"edges": [{"relationType": r, "node": n} for r, n in relations]},
    }


class FakeTime:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def run(handler, source, ft: FakeTime | None = None):
    ft = ft or FakeTime()
    coll = AniListCollector(sleep=ft.sleep, clock=ft.clock)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await coll.collect(source, S.CollectContext(http, NOW))

    return asyncio.run(go())


def ok(data, **headers) -> httpx.Response:
    return httpx.Response(200, json={"data": data}, headers=headers)


def test_plugs_into_registry():
    assert S.collector_factory("anilist") is make_collector
    assert make_collector(None).kind == "anilist"


def test_user_list_sequels_and_episodes():
    soon = int((NOW + timedelta(days=2)).timestamp())
    later = int((NOW + timedelta(days=30)).timestamp())
    seq_a = media(200, "Frieren 2", "NOT_YET_RELEASED", start=(2027, 1, None))
    seq_b_done = media(301, "Mob 3")
    seq_b_watched = media(302, "Mob 4", "RELEASING")
    seq_c = media(400, "Dungeon Meshi 2", "RELEASING", start=(2026, 9, 20))
    page1 = [
        {"status": "CURRENT", "media": media(
            100, "Frieren", "RELEASING", next_ep={"episode": 7, "airingAt": soon},
            relations=[("SEQUEL", seq_a), ("PREQUEL", media(99, "Frieren 0", "RELEASING")),
                       ("SEQUEL", media(201, "Frieren manga", "RELEASING", type_="MANGA"))])},
        {"status": "PLANNING", "media": media(
            150, "Longe", "RELEASING", next_ep={"episode": 3, "airingAt": later})},
    ]
    page2 = [
        {"status": "COMPLETED", "media": media(
            300, "Mob", relations=[("SEQUEL", seq_b_done), ("SEQUEL", seq_b_watched)])},
        {"status": "CURRENT", "media": seq_b_watched},
        {"status": "COMPLETED", "media": media(399, "Dungeon Meshi",
                                               relations=[("SEQUEL", seq_c)])},
    ]
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        v = body["variables"]
        seen.append(v)
        assert "mediaList" in body["query"]
        pg = page1 if v["page"] == 1 else page2
        return ok({"Page": {"pageInfo": {"hasNextPage": v["page"] == 1}, "mediaList": pg}})

    raws = run(handler, src(username="DiltoZord"))
    assert [v["page"] for v in seen] == [1, 2]
    assert seen[0]["user"] == "DiltoZord"
    assert seen[0]["status"] == ["CURRENT", "PLANNING", "COMPLETED"]
    by_url = {r.url: r for r in raws}
    assert set(by_url) == {
        "https://anilist.co/anime/100?episodio=7",
        "https://anilist.co/anime/200",
        "https://anilist.co/anime/400",
    }
    assert by_url["https://anilist.co/anime/200"].title == \
        "Sequência de Frieren anunciada: Frieren 2 (01/2027)"
    assert by_url["https://anilist.co/anime/400"].title == \
        "Sequência de Dungeon Meshi em exibição: Dungeon Meshi 2"
    assert "Episódio 7 de Frieren" in by_url["https://anilist.co/anime/100?episodio=7"].title
    assert all(r.source_id == 5 and r.fetched_at == NOW for r in raws)
    # URL estável: a mesma resposta gera as mesmas URLs (dedup entre execuções)
    assert {r.url for r in run(handler, src(username="DiltoZord"))} == set(by_url)


def seasonal_handler(seen):
    fall = [media(10, "Apothecary 3", "NOT_YET_RELEASED", start=(2026, 10, 2),
                  relations=[("PREQUEL", media(9, "Apothecary 2"))],
                  description="<b>Maomao</b> volta &amp; investiga.<br>"),
            media(11, "Original", "RELEASING", season="FALL", year=2026)]
    winter = [media(10, "Apothecary 3", "NOT_YET_RELEASED", start=(2026, 10, 2)),
              media(12, "Novo", "NOT_YET_RELEASED", season="WINTER", year=2027)]

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        v = body["variables"]
        if "mediaList" in body["query"]:
            seen.append(("list", v["user"]))
            return ok({"Page": {"pageInfo": {"hasNextPage": False}, "mediaList": []}})
        seen.append((v["season"], v["year"], v["perPage"]))
        return ok({"Page": {"media": fall if v["season"] == "FALL" else winter}})

    return handler


def test_seasonal_fallback_without_username():
    seen = []
    raws = run(seasonal_handler(seen), src(popular_count=5))
    assert seen == [("FALL", 2026, 5), ("WINTER", 2027, 5)]
    assert [r.url for r in raws] == [f"https://anilist.co/anime/{i}" for i in (10, 11, 12)]
    assert raws[0].title == "Sequência de Apothecary 2 anunciada: Apothecary 3 (02/10/2026)"
    assert "Maomao volta & investiga." in raws[0].body
    assert raws[0].published_at == datetime(2026, 10, 2, tzinfo=UTC)
    assert raws[1].title == "Anime da temporada: Original (outono 2026)"
    assert raws[2].title == "Anime da temporada: Novo (inverno 2027)"


def test_empty_user_list_falls_back_to_season():
    seen = []
    raws = run(seasonal_handler(seen), src(username="DiltoZord"))
    assert seen[0] == ("list", "DiltoZord")
    assert len(raws) == 3


def test_429_waits_retry_after():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, json={"errors": []})
        return ok({"Page": {"media": []}})

    ft = FakeTime()
    assert run(handler, src(), ft) == []
    assert ft.slept == [3.0]
    assert len(calls) == 3  # 1 retry + 2 temporadas


def test_429_beyond_deadline_gives_up():
    def handler(req):
        return httpx.Response(429, headers={"Retry-After": "60"})

    with pytest.raises(TimeoutError):
        run(handler, src(deadline_s=10))


def test_deadline_returns_partial_user_list():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            entry = {"status": "COMPLETED", "media": media(
                1, "A", relations=[("SEQUEL", media(2, "B", "NOT_YET_RELEASED"))])}
            return ok({"Page": {"pageInfo": {"hasNextPage": True}, "mediaList": [entry]}})
        return httpx.Response(429, headers={"Retry-After": "60"})

    raws = run(handler, src(username="x", deadline_s=10))
    assert [r.url for r in raws] == ["https://anilist.co/anime/2"]


def test_rate_limit_spaces_requests_and_follows_header():
    def handler(req):
        return ok({"Page": {"media": []}}, **{"X-RateLimit-Limit": "1"})

    ft = FakeTime()
    run(handler, src(deadline_s=100), ft)  # 2 requisições, limite cai para 1/min pelo cabeçalho
    assert ft.slept == [60.0]


def test_graphql_error_raises():
    def handler(req):
        return httpx.Response(404, json={"errors": [{"message": "Private User", "status": 404}],
                                         "data": {"Page": {"mediaList": None}}})

    with pytest.raises(AniListError, match="Private User"):
        run(handler, src(username="secreto"))


def test_helpers():
    assert anilist.season_of(NOW) == ("FALL", 2026)
    assert anilist.season_of(datetime(2027, 1, 5, tzinfo=UTC)) == ("WINTER", 2027)
    assert anilist.next_season("FALL", 2026) == ("WINTER", 2027)
    assert anilist.next_season("SPRING", 2027) == ("SUMMER", 2027)
    assert anilist.when(media(1, "x", start=(2027, None, None))) == "2027"
    assert anilist.when(media(1, "x")) == ""
