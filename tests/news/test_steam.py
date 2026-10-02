"""Tarefa 6.2: coletor Steam News com catálogo falso e ``httpx.MockTransport`` (sem rede)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from magi.common.contracts import Game
from magi.news import sources as S
from magi.news.collect import steam
from magi.news.collect.steam import SteamNewsCollector, make_collector, to_text

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
SRC = S.SourceConfig("Steam News", "steam", URL, 3, id=7)

HADES = Game(1145360, "Hades")
CELLS = Game(588650, "Dead Cells")
PROTON = Game(1493710, "Proton Experimental")


class FakeCatalog:
    def __init__(self, games: list[Game]) -> None:
        self.games = games

    def all(self) -> list[Game]:
        return list(self.games)


def _item(appid: int, n: int, title: str, contents: str = "", date: int = 1790000000) -> dict:
    return {
        "gid": f"{appid}{n}",
        "title": title,
        "url": f"https://store.steampowered.com/news/app/{appid}/view/{n}",
        "contents": contents,
        "date": date + n,
        "feedname": "steam_community_announcements",
        "feed_type": 1,
        "appid": appid,
    }


NEWS = {
    HADES.appid: [
        _item(HADES.appid, 1, "Patch 1.2 &amp; balance",
              "[h1]Novidades[/h1][img]{STEAM_CLAN_IMAGE}/1/abc.png[/img]"
              "[list][*]Novo [b]chefe[/b][*]Leia [url=https://x.example]aqui[/url][/list]"),
        _item(HADES.appid, 2, "Hades: trilha sonora", "<p>Disco <b>novo</b></p>"),
    ],
    CELLS.appid: [_item(CELLS.appid, 1, "Update 35", "Texto simples")],
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ok(request: httpx.Request) -> httpx.Response:
    appid = int(request.url.params["appid"])
    items = NEWS.get(appid, [])[: int(request.url.params["count"])]
    return httpx.Response(200, json={"appnews": {"appid": appid, "newsitems": items, "count": len(items)}})


async def _collect(collector: SteamNewsCollector, handler, src: S.SourceConfig = SRC):
    async with _client(handler) as http:
        return await collector.collect(src, S.CollectContext(http=http, now=NOW))


def test_plugs_into_registry():
    assert S.collector_factory("steam") is make_collector
    assert isinstance(make_collector(None), S.Collector)


def test_collects_installed_games_skipping_tools():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ok(request)

    raws = asyncio.run(_collect(SteamNewsCollector(FakeCatalog([HADES, CELLS, PROTON])), handler))

    assert sorted(int(r.url.params["appid"]) for r in calls) == sorted([HADES.appid, CELLS.appid])
    params = calls[0].url.params
    assert params["count"] == "5" and params["feeds"] == "steam_community_announcements"
    assert params["format"] == "json"
    assert len(raws) == 3 and all(r.source_id == 7 and r.fetched_at == NOW for r in raws)
    by_url = {r.url: r for r in raws}
    patch = by_url[f"https://store.steampowered.com/news/app/{HADES.appid}/view/1"]
    assert patch.title == "Hades: Patch 1.2 & balance"
    assert patch.body == "Novidades • Novo chefe • Leia aqui"
    assert patch.published_at == datetime.fromtimestamp(1790000001, UTC)
    disc = by_url[f"https://store.steampowered.com/news/app/{HADES.appid}/view/2"]
    assert disc.title == "Hades: trilha sonora"
    assert "Dead Cells: Update 35" in {r.title for r in raws}
    assert raws == sorted(raws, key=lambda r: r.published_at, reverse=True)


def test_options_count_and_all_feeds():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ok(request)

    src = S.SourceConfig("Steam News", "steam", URL, 3, options={"count": 1, "feeds": ""}, id=7)
    raws = asyncio.run(_collect(SteamNewsCollector(FakeCatalog([HADES])), handler, src))
    assert len(raws) == 1
    assert calls[0].url.params["count"] == "1" and "feeds" not in calls[0].url.params


def test_to_text():
    assert to_text("") == ""
    assert to_text("[previewyoutube=abc;full][/previewyoutube]Oi [i]mundo[/i]") == "Oi mundo"
    assert to_text("<ul><li>um</li><li>dois &amp; três</li></ul>") == "um dois & três"
    assert to_text("[EN] versão 2 [u]já[/u]") == "[EN] versão 2 já"
    long = to_text("a" * 5000)
    assert len(long) == steam.MAX_BODY_CHARS and long.endswith("…")


def test_concurrency_is_limited():
    games = [Game(1000 + i, f"Jogo {i}") for i in range(12)]
    state = {"now": 0, "max": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        return _ok(request)

    src = S.SourceConfig("Steam News", "steam", URL, 3, options={"concurrency": 3}, id=7)
    asyncio.run(_collect(SteamNewsCollector(FakeCatalog(games)), handler, src))
    assert state["max"] == 3


def test_deadline_returns_partial_results():
    async def handler(request: httpx.Request) -> httpx.Response:
        if int(request.url.params["appid"]) == CELLS.appid:
            await asyncio.sleep(5)
        return _ok(request)

    src = S.SourceConfig("Steam News", "steam", URL, 3, options={"deadline_s": 0.3}, id=7)
    raws = asyncio.run(_collect(SteamNewsCollector(FakeCatalog([HADES, CELLS])), handler, src))
    assert {r.title.split(":")[0] for r in raws} == {"Hades"}


def test_one_game_failing_does_not_drop_others():
    def handler(request: httpx.Request) -> httpx.Response:
        appid = int(request.url.params["appid"])
        if appid == CELLS.appid:
            return httpx.Response(500)
        if appid == 1:
            return httpx.Response(404)
        return _ok(request)

    raws = asyncio.run(_collect(SteamNewsCollector(FakeCatalog([HADES, CELLS, Game(1, "Sem notícias")])),
                                handler))
    assert len(raws) == 2


def test_all_failing_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_collect(SteamNewsCollector(FakeCatalog([HADES, CELLS])), handler))


def test_no_games_and_missing_id():
    assert asyncio.run(_collect(SteamNewsCollector(FakeCatalog([PROTON])), _ok)) == []
    with pytest.raises(ValueError):
        asyncio.run(_collect(SteamNewsCollector(FakeCatalog([HADES])), _ok,
                             S.SourceConfig("Steam News", "steam", URL, 3)))
