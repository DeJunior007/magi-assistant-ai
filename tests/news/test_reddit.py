"""Tarefa 6.4: coletor Reddit (OAuth app-only e fallback RSS), sem rede e com keyring falso."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import keyring
import pytest
from keyring.backend import KeyringBackend

from magi.common import secrets
from magi.news import sources as S
from magi.news.collect import reddit as R

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ANIME = S.SourceConfig("r/anime", "reddit", "https://www.reddit.com/r/anime/", 1, id=7)
GAMES = S.SourceConfig("r/Games", "reddit", "https://www.reddit.com/r/Games/", 1, id=8)


class FakeKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture
def ring():
    old = keyring.get_keyring()
    fake = FakeKeyring()
    keyring.set_keyring(fake)
    yield fake
    keyring.set_keyring(old)


@pytest.fixture
def creds(ring):
    secrets.set_secret(R.CLIENT_ID_KEY, "cid")
    secrets.set_secret(R.CLIENT_SECRET_KEY, "csecret")
    return ring


def _post(pid, title, **kw):
    data = {"id": pid, "title": title, "permalink": f"/r/Games/comments/{pid}/slug/",
            "created_utc": 1790000000.0, "is_self": False, "url": f"https://news.example/{pid}",
            "link_flair_text": None, "selftext": "", "stickied": False, "over_18": False}
    data.update(kw)
    return {"kind": "t3", "data": data}


LISTING = {"kind": "Listing", "data": {"children": [
    _post("a1", "Silksong ganha data", link_flair_text="Industry News"),
    _post("a2", "O que vocês estão jogando?", is_self=True, link_flair_text="Discussion",
          url="https://www.reddit.com/r/Games/comments/a2/slug/"),
    _post("a3", "Anúncio oficial", is_self=True, link_flair_text="Official Announcement",
          selftext="Detalhes aqui"),
    _post("a4", "Sem flair, link externo"),
    _post("a5", "Sem flair, self", is_self=True,
          url="https://www.reddit.com/r/Games/comments/a5/slug/"),
    _post("a6", "Imagem", url="https://i.redd.it/x.png"),
    _post("a7", "NSFW", over_18=True, link_flair_text="News"),
    _post("a8", "Megathread", stickied=True),
]}}


def _entry(pid, title, link, text=""):
    perma = f"https://www.reddit.com/r/anime/comments/{pid}/slug/"
    md = f'<div class="md"><p>{text}</p></div>' if text else ""
    html = (f'{md} submitted by <a href="https://www.reddit.com/user/foo"> /u/foo </a><br/>'
            f'<span><a href="{link or perma}">[link]</a></span> '
            f'<span><a href="{perma}">[comments]</a></span>')
    from xml.sax.saxutils import escape
    return (f'<entry><id>t3_{pid}</id><title>{title}</title><link href="{perma}"/>'
            f'<updated>2026-10-01T10:00:00+00:00</updated>'
            f'<content type="html">{escape(html)}</content></entry>')


ATOM = ('<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<title>anime</title>'
        + _entry("b1", "Frieren temporada 2 anunciada", "https://anime.example/frieren")
        + _entry("b2", "Episode discussion", None, "Comentem aqui")
        + _entry("b3", "Fanart", "https://i.redd.it/y.jpg")
        + "</feed>").encode()


def _ctx(handler) -> S.CollectContext:
    return S.CollectContext(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                            now=NOW)


async def _nosleep(_s: float) -> None:
    return None


def test_filtro_listing():
    raws = R.parse_listing(LISTING, GAMES, NOW)
    titles = [r.title for r in raws]
    assert titles == ["Silksong ganha data", "Anúncio oficial", "Sem flair, link externo"]
    first = raws[0]
    assert first.url == "https://www.reddit.com/r/Games/comments/a1/slug/"
    assert first.body.startswith("Link: https://news.example/a1")
    assert "Flair: Industry News" in first.body
    assert first.source_id == 8 and first.fetched_at == NOW
    assert "Detalhes aqui" in raws[1].body


def test_flairs_configuraveis():
    src = S.SourceConfig("x", "reddit", GAMES.url, 1, options={"flairs": ["Discussion"]})
    assert [r.title for r in R.parse_listing(LISTING, src)][:1] == ["O que vocês estão jogando?"]


def test_parse_atom():
    raws = R.parse_atom(ATOM, ANIME, NOW)
    assert [r.title for r in raws] == ["Frieren temporada 2 anunciada"]
    raw = raws[0]
    assert raw.url == "https://www.reddit.com/r/anime/comments/b1/slug/"
    assert raw.body == "Link: https://anime.example/frieren"
    assert raw.published_at == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    src = S.SourceConfig("x", "reddit", ANIME.url, 1, options={"allow_self": True})
    self_post = [r for r in R.parse_atom(ATOM, src) if r.title == "Episode discussion"][0]
    assert "Comentem aqui" in self_post.body and "Link:" not in self_post.body


def test_subreddit_of():
    assert R.subreddit_of(GAMES) == "Games"
    assert R.subreddit_of(S.SourceConfig("x", "reddit", "https://x/", 1,
                                         options={"subreddit": "r/manga"})) == "manga"
    with pytest.raises(R.RedditError):
        R.subreddit_of(S.SourceConfig("x", "reddit", "https://x/", 1))


async def test_rss_sem_credenciais(ring):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=ATOM)

    raws = await R.RedditCollector(sleep=_nosleep, batch_window_s=0).collect(ANIME, _ctx(handler))
    assert len(raws) == 1 and raws[0].source_id == 7
    assert len(seen) == 1
    assert seen[0].url.path == "/r/anime/.rss"
    assert seen[0].headers["User-Agent"].startswith("linux:magi-assistant.news")


async def test_rss_junta_fontes_num_so_feed(ring):
    games_entry = _entry("c1", "Novo trailer", "https://games.example/trailer").replace(
        "/r/anime/", "/r/Games/")
    atom = ATOM.replace(b"</feed>", games_entry.encode() + b"</feed>")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=atom)

    col, ctx = R.RedditCollector(batch_window_s=0.01), _ctx(handler)
    anime, games = await asyncio.gather(col.collect(ANIME, ctx), col.collect(GAMES, ctx))
    assert len(seen) == 1
    assert seen[0].url.path == "/r/anime+Games/.rss"
    assert seen[0].url.params["limit"] == "100"
    assert [r.title for r in anime] == ["Frieren temporada 2 anunciada"]
    assert [r.title for r in games] == ["Novo trailer"] and games[0].source_id == 8


async def test_oauth_com_credenciais(creds):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/api/v1/access_token":
            assert req.headers["Authorization"].startswith("Basic ")
            assert b"grant_type=client_credentials" in req.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert req.url.host == "oauth.reddit.com"
        assert req.headers["Authorization"] == "bearer tok"
        return httpx.Response(200, json=LISTING)

    col = R.make_collector()
    ctx = _ctx(handler)
    raws = await col.collect(GAMES, ctx)
    assert len(raws) == 3
    await col.collect(ANIME, ctx)  # token reaproveitado
    assert [r.url.path for r in seen] == ["/api/v1/access_token", "/r/Games/hot", "/r/anime/hot"]
    assert seen[1].url.params["limit"] == "50"


async def test_oauth_recusado_cai_no_rss(creds):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/access_token":
            return httpx.Response(401, json={"error": 401})
        return httpx.Response(200, content=ATOM)

    raws = await R.RedditCollector(batch_window_s=0).collect(ANIME, _ctx(handler))
    assert [r.title for r in raws] == ["Frieren temporada 2 anunciada"]


async def test_429_espera_e_tenta_de_novo(ring):
    waits: list[float] = []
    calls = {"n": 0}

    async def sleep(s: float) -> None:
        waits.append(s)

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        if calls["n"] == 2:
            return httpx.Response(429, headers={"Retry-After": "999"})
        return httpx.Response(200, content=ATOM)

    raws = await R.RedditCollector(sleep=sleep, batch_window_s=0).collect(ANIME, _ctx(handler))
    assert len(raws) == 1
    assert waits == [3.0, R.MAX_WAIT_S]


async def test_429_persistente_levanta(ring):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    with pytest.raises(httpx.HTTPStatusError):
        await R.RedditCollector(sleep=_nosleep, batch_window_s=0).collect(ANIME, _ctx(handler))


def test_registrado_pelo_kind():
    factory = S.collector_factory("reddit")
    col = factory(None)
    assert isinstance(col, S.Collector) and col.kind == "reddit"
    assert json.dumps(R.NEWS_FLAIRS)  # lista serializável (vai para docs/config)
