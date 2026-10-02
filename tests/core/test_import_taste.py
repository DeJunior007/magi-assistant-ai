"""Importação do gosto (2.3): Spotify falso (MockTransport), keyring falso, repo em memória."""

from __future__ import annotations

import httpx
import pytest

from magi.common.contracts import TasteEntry
from magi.core.actions import spotify_api as sa
from magi.core.music import import_taste as it

NOW = 1_000_000.0


class MemTaste:
    def __init__(self):
        self.d: dict[tuple[str, str], float] = {}
        self.upserts = 0

    async def upsert(self, entries):
        self.upserts += 1
        for e in entries:
            self.d[(e.artist, e.genre)] = e.weight

    async def top(self, limit=50, genre=None):
        rows = [TasteEntry(a, g, w) for (a, g), w in self.d.items() if genre is None or g == genre]
        return sorted(rows, key=lambda e: -e.weight)[:limit]

    async def adjust(self, artist, delta):
        self.d[(artist, "")] = self.d.get((artist, ""), 0.0) + delta

    async def count(self):
        return len(self.d)


def _art(name, genres=None):
    d = {"name": name, "id": name, "uri": f"spotify:artist:{name}"}
    if genres is not None:
        d["genres"] = genres
    return d


def _track(*artists):
    return {"name": "t", "artists": [{"name": a} for a in artists]}


def _secrets():
    tok = sa.Token("A1", "R1", NOW + 3600, "user-top-read").to_json()
    d = {sa.CLIENT_ID_KEY: "cid", sa.TOKEN_KEY: tok}
    return sa.TokenStore(get=d.get, set=d.__setitem__)


def _api(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return sa.SpotifyApi(store=_secrets(), client=client, clock=lambda: NOW)


def handler(forbid=()):
    calls = []

    def h(req: httpx.Request):
        path, q = req.url.path.removeprefix("/v1"), dict(req.url.params)
        calls.append((path, q.get("time_range")))
        assert req.method == "GET"
        if path in forbid:
            return httpx.Response(403, json={"error": {"status": 403, "message": "Forbidden"}})
        rng = q.get("time_range")
        if path == "/me/top/artists":
            items = {
                "short_term": [_art("A", []), _art("B")],  # gêneros vazios/ausentes (app novo)
                "medium_term": [_art("B", ["rock"]), _art("A")],
                "long_term": [_art("C")],
            }[rng]
        elif path == "/me/top/tracks":
            items = {"short_term": [_track("A", "D")], "medium_term": [], "long_term": [_track("C")]}[rng]
        elif path == "/me/player/recently-played":
            items = [{"track": _track("E")}, {"track": _track("E")}, {"track": {}}]
        else:
            return httpx.Response(404)
        return httpx.Response(200, json={"items": items})

    h.calls = calls
    return h


async def test_import_weights_and_idempotent():
    h = handler()
    api, repo = _api(h), MemTaste()
    rep = await it.import_taste(api, repo)
    assert len(h.calls) == 7
    w = {e.artist: e for e in rep.entries}
    assert set(w) == {"A", "B", "C", "D", "E"}
    assert rep.entries[0].artist == "A" and rep.entries[0].weight == 1.0  # 1º no curto + faixa
    assert w["B"].genre == "rock" and w["A"].genre == ""
    assert w["A"].weight > w["B"].weight > w["C"].weight > w["D"].weight > w["E"].weight > 0
    assert w["E"].weight == pytest.approx(round(2 * it.RECENT_PLAY / (1.0 + 0.98 * 0.7 + 0.5), 4))
    first = dict(repo.d)
    await it.import_taste(api, repo)
    assert repo.d == first  # rodar de novo não duplica nem acumula
    await api.aclose()


async def test_degrades_when_endpoints_forbidden():
    h = handler(forbid={"/me/top/artists", "/me/player/recently-played"})
    api, repo = _api(h), MemTaste()
    rep = await it.import_taste(api, repo)
    assert set(rep.data.failed) == {f"artists/{r}" for r in it.RANGES} | {"recent"}
    assert {e.artist for e in rep.entries} == {"A", "C", "D"}
    assert all(e.genre == "" for e in rep.entries)
    await api.aclose()


async def test_nothing_fetched_writes_nothing():
    h = handler(forbid={"/me/top/artists", "/me/top/tracks", "/me/player/recently-played"})
    api, repo = _api(h), MemTaste()
    rep = await it.import_taste(api, repo)
    assert rep.entries == [] and repo.upserts == 0
    await api.aclose()


async def test_import_if_empty():
    h = handler()
    repo = MemTaste()
    rep = await it.import_if_empty(repo, _api(h))
    assert rep is not None and repo.d
    n = len(h.calls)
    assert await it.import_if_empty(repo, _api(h)) is None  # já tem gosto: não chama a API
    assert len(h.calls) == n
    # sem Spotify conectado: adia, sem levantar
    off = sa.SpotifyApi(store=sa.TokenStore(get=lambda k: None, set=lambda k, v: None))
    assert await it.import_if_empty(MemTaste(), off) is None


async def test_auth_error_propagates_from_import():
    off = sa.SpotifyApi(store=sa.TokenStore(get=lambda k: None, set=lambda k, v: None))
    with pytest.raises(sa.SpotifyAuthError):
        await it.import_taste(off, MemTaste())
