"""Spotify Web API (2.2): HTTP falso (MockTransport), keyring falso, MPRIS falso. Sem rede."""

from __future__ import annotations

import json
import threading
import urllib.request
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from magi.cli import spotify_login
from magi.common.contracts import ActionRequest, Intent, IntentId, Slot, SlotName
from magi.core.actions import spotify_api as sa
from magi.core.actions import spotify_mpris as sm

NOW = 1_000_000.0


class FakeSecrets:
    def __init__(self, **kv):
        self.d = dict(kv)

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v):
        self.d[k] = v

    def store(self):
        return sa.TokenStore(get=self.get, set=self.set)


def _token(expires_at=NOW + 3600, access="A1"):
    return sa.Token(access, "R1", expires_at, "user-top-read").to_json()


def _item(kind, name, uri, artist=""):
    d = {"name": name, "uri": uri}
    if kind in ("track", "album"):
        d["artists"] = [{"name": artist}]
    if kind == "playlist":
        d["owner"] = {"display_name": artist}
    return d


RESULTS = {
    "tracks": {"items": [
        _item("track", "Numb", "spotify:track:numb", "Linkin Park"),
        _item("track", "In the End", "spotify:track:end", "Linkin Park"),
    ]},
    "artists": {"items": [
        _item("artist", "Linkin Park", "spotify:artist:lp"),
        _item("artist", "Linkin Park Tribute", "spotify:artist:lpt"),
    ]},
    "albums": {"items": [_item("album", "Meteora", "spotify:album:meteora", "Linkin Park")]},
    "playlists": {"items": [None, _item("playlist", "This Is Linkin Park", "spotify:playlist:this")]},
}


class FakeMpris:
    def __init__(self, exc=None):
        self.uris, self.exc = [], exc

    async def open_uri(self, uri):
        if self.exc:
            raise self.exc
        self.uris.append(uri)


def _req(query):
    return ActionRequest(
        intent=Intent(id=IntentId.MUSIC_PLAY, slots=(Slot(SlotName.QUERY, query),)), ctx=None
    )


def _api(secrets, handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return sa.SpotifyApi(store=secrets.store(), client=client, clock=lambda: NOW)


# --- escolha do tipo ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "kind", "text"),
    [
        ("o álbum Meteora", "album", "Meteora"),
        ("a playlist This Is Linkin Park", "playlist", "This Is Linkin Park"),
        ("música Numb", "track", "Numb"),
        ("a banda Linkin Park", "artist", "Linkin Park"),
        ("músicas do Linkin Park", "artist", "Linkin Park"),
        ("Linkin Park", None, "Linkin Park"),
        ("álbum", None, "álbum"),
    ],
)
def test_parse_query(query, kind, text):
    assert sa.parse_query(query) == (kind, text)


@pytest.mark.parametrize(
    ("text", "kind", "uri"),
    [
        ("Linkin Park", None, "spotify:artist:lp"),  # "toca Linkin Park" = artista
        ("linkin park", None, "spotify:artist:lp"),
        ("Numb", None, "spotify:track:numb"),
        ("numb do linkin park", None, "spotify:track:numb"),
        ("Meteora", None, "spotify:album:meteora"),
        ("This Is Linkin Park", None, "spotify:playlist:this"),
        ("Linkin Park", "album", "spotify:album:meteora"),  # tipo citado manda
        ("xyz qualquer coisa", None, "spotify:track:numb"),  # nada parecido: relevância
    ],
)
def test_choose(text, kind, uri):
    results = RESULTS if kind is None else {f"{kind}s": RESULTS[f"{kind}s"]}
    assert sa.choose(results, text, kind).uri == uri


def test_choose_empty():
    assert sa.choose({"tracks": {"items": []}}, "nada") is None


# --- credenciais e tokens ----------------------------------------------------------------------


async def test_play_query_without_credentials():
    def handler(request):
        raise AssertionError("não deve chamar a rede")

    mpris = FakeMpris()
    for secrets in (FakeSecrets(), FakeSecrets(**{sa.CLIENT_ID_KEY: "cid"})):
        player = sa.SpotifyPlayer(mpris, _api(secrets, handler))
        r = await player.play_query(_req("Linkin Park"), "Linkin Park")
        assert not r.ok and r.speech == sa.SAY_LOGIN
    assert mpris.uris == []


async def test_search_refreshes_expired_token():
    secrets = FakeSecrets(**{sa.CLIENT_ID_KEY: "cid", sa.TOKEN_KEY: _token(expires_at=NOW + 10)})
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.host == "accounts.spotify.com":
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["refresh_token"]
            assert form["refresh_token"] == ["R1"] and form["client_id"] == ["cid"]
            return httpx.Response(200, json={"access_token": "A2", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer A2"
        assert request.url.params["type"] == "artist,track,album,playlist"
        return httpx.Response(200, json=RESULTS)

    m = await _api(secrets, handler).find("Linkin Park")
    assert m.uri == "spotify:artist:lp"
    assert seen == ["/api/token", "/v1/search"]
    saved = sa.Token.from_json(secrets.d[sa.TOKEN_KEY])
    assert saved.access_token == "A2" and saved.refresh_token == "R1"  # refresh antigo mantido
    assert saved.expires_at == NOW + 3600


async def test_retries_once_after_401():
    secrets = FakeSecrets(**{sa.CLIENT_ID_KEY: "cid", sa.TOKEN_KEY: _token()})
    calls = []

    def handler(request):
        if request.url.host == "accounts.spotify.com":
            return httpx.Response(200, json={"access_token": "A2", "refresh_token": "R2"})
        calls.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer A1":
            return httpx.Response(401, json={"error": {"status": 401}})
        return httpx.Response(200, json={"items": []})

    assert await _api(secrets, handler).get("/me/top/artists") == {"items": []}
    assert calls == ["Bearer A1", "Bearer A2"]
    assert sa.Token.from_json(secrets.d[sa.TOKEN_KEY]).refresh_token == "R2"


async def test_revoked_refresh_asks_login():
    secrets = FakeSecrets(**{sa.CLIENT_ID_KEY: "cid", sa.TOKEN_KEY: _token(expires_at=NOW)})

    def handler(request):
        return httpx.Response(400, json={"error": "invalid_grant"})

    player = sa.SpotifyPlayer(FakeMpris(), _api(secrets, handler))
    r = await player.play_query(_req("Numb"), "Numb")
    assert not r.ok and r.speech == sa.SAY_LOGIN


# --- play_query --------------------------------------------------------------------------------


def _search_handler(request):
    if request.url.path != "/v1/search":
        raise AssertionError(request.url)
    types = request.url.params["type"].split(",")
    return httpx.Response(200, json={f"{t}s": RESULTS[f"{t}s"] for t in types})


@pytest.mark.parametrize(
    ("query", "uri", "speech"),
    [
        ("Linkin Park", "spotify:artist:lp", "Tocando Linkin Park."),
        ("o álbum Meteora", "spotify:album:meteora", "Tocando o álbum Meteora, de Linkin Park."),
        ("Numb", "spotify:track:numb", "Tocando Numb, de Linkin Park."),
        ("a playlist this is linkin park", "spotify:playlist:this",
         "Tocando a playlist This Is Linkin Park."),
    ],
)
async def test_play_query_opens_uri(query, uri, speech):
    secrets = FakeSecrets(**{sa.CLIENT_ID_KEY: "cid", sa.TOKEN_KEY: _token()})
    mpris = FakeMpris()
    r = await sa.make_play_query(mpris, _api(secrets, _search_handler))(_req(query), query)
    assert r.ok and r.speech == speech
    assert mpris.uris == [uri]


async def test_play_query_via_mpris_handler():
    secrets = FakeSecrets(**{sa.CLIENT_ID_KEY: "cid", sa.TOKEN_KEY: _token()})
    mpris = FakeMpris()
    (handler,) = sm.handlers(mpris, sa.make_play_query(mpris, _api(secrets, _search_handler)))
    r = await handler.run(_req("Linkin Park"))
    assert r.ok and mpris.uris == ["spotify:artist:lp"]


async def test_play_query_errors():
    secrets = FakeSecrets(**{sa.CLIENT_ID_KEY: "cid", sa.TOKEN_KEY: _token()})

    def empty(request):
        return httpx.Response(200, json={"tracks": {"items": []}})

    def boom(request):
        return httpx.Response(503, text="fora")

    r = await sa.SpotifyPlayer(FakeMpris(), _api(secrets, empty)).play_query(_req("x"), "zzz")
    assert not r.ok and "Não achei zzz" in r.speech
    r = await sa.SpotifyPlayer(FakeMpris(), _api(secrets, boom)).play_query(_req("x"), "zzz")
    assert not r.ok and r.speech == sa.SAY_API_FAILED
    mpris = FakeMpris(exc=sm.SpotifyNotRunning("timeout"))
    r = await sa.SpotifyPlayer(mpris, _api(secrets, _search_handler)).play_query(_req("x"), "Numb")
    assert not r.ok and r.speech == sm.SAY_NOT_STARTED


# --- PKCE e login ------------------------------------------------------------------------------


def test_pkce_and_authorize_url():
    v = sa.make_verifier()
    assert 43 <= len(v) <= 128
    # vetor do RFC 7636, apêndice B
    assert sa.code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == (
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    )
    q = parse_qs(urlparse(sa.authorize_url("cid", sa.redirect_uri(), "ch", "st")).query)
    assert q["redirect_uri"] == ["http://127.0.0.1:8765/callback"]
    assert q["code_challenge_method"] == ["S256"] and q["response_type"] == ["code"]
    assert q["scope"] == [" ".join(sa.SCOPES)]


def test_login_flow_saves_token():
    """Callback em 127.0.0.1 (loopback, porta livre); troca do code por HTTP falso."""
    secrets = FakeSecrets(**{sa.CLIENT_ID_KEY: "cid"})
    sent = {}

    def token_handler(request):
        sent.update(parse_qs(request.content.decode()))
        return httpx.Response(200, json={
            "access_token": "A1", "refresh_token": "R1", "expires_in": 3600, "scope": "user-top-read",
        })

    def opener(url):
        q = parse_qs(urlparse(url).query)
        cb = f"{q['redirect_uri'][0]}?code=CODE&state={q['state'][0]}"
        sent["challenge"] = q["code_challenge"][0]
        threading.Thread(target=lambda: urllib.request.urlopen(cb, timeout=5).read()).start()

    client = httpx.AsyncClient(transport=httpx.MockTransport(token_handler))
    rc = spotify_login.main(
        ["--port", "0", "--timeout", "5"], opener=opener, store=secrets.store(), client=client
    )
    assert rc == 0
    assert sent["code"] == ["CODE"] and sent["grant_type"] == ["authorization_code"]
    assert sa.code_challenge(sent["code_verifier"][0]) == sent["challenge"]
    tok = json.loads(secrets.d[sa.TOKEN_KEY])
    assert tok["access_token"] == "A1" and tok["refresh_token"] == "R1"
