"""Tarefa 6.1: fontes, coletor RSS, deduplicação por URL e ``magi-news`` (sem rede).

Os feeds são arquivos XML locais servidos por ``httpx.MockTransport``. Os testes ``db`` usam o
Postgres de desenvolvimento num schema temporário (pulados sem banco).
"""

from __future__ import annotations

import asyncio
import itertools
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import NewsRaw, NewsRepo, NewsSource
from magi.memory import migrate as mig
from magi.news import __main__ as news_main
from magi.news import sources as S
from magi.news.collect.rss import FeedError, RssCollector, parse_feed
from magi.news.repo import PgNewsRepo

FEEDS = Path(__file__).with_name("feeds")
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
ANIME = S.SourceConfig("Fake Anime", "rss", "https://anime.example/rss", 3)
GAMES = S.SourceConfig("Fake Games", "rss", "https://games.example/atom", 2)
BROKEN = S.SourceConfig("Broken", "rss", "https://broken.example/rss", 1)


def _transport(calls: list[str] | None = None) -> httpx.MockTransport:
    routes = {ANIME.url: "anime.xml", GAMES.url: "games.xml"}

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        name = routes.get(str(request.url))
        if name is None:
            return httpx.Response(500, text="erro")
        return httpx.Response(200, content=(FEEDS / name).read_bytes())

    return httpx.MockTransport(handler)


class MemRepo:
    """``NewsRepo`` em memória (só fontes e cruas)."""

    def __init__(self) -> None:
        self.src: dict[str, NewsSource] = {}
        self.raw: dict[str, NewsRaw] = {}
        self._ids = itertools.count(1)

    async def sources(self) -> list[NewsSource]:
        return list(self.src.values())

    async def upsert_source(self, source: NewsSource) -> int:
        old = self.src.get(source.url)
        sid = old.id if old else next(self._ids)
        self.src[source.url] = replace(source, id=sid)
        return sid  # type: ignore[return-value]

    async def add_raw(self, raw: NewsRaw) -> int | None:
        if raw.url in self.raw:
            return None
        rid = next(self._ids)
        self.raw[raw.url] = replace(raw, id=rid)
        return rid


# --- fontes ----------------------------------------------------------------------------------


def test_fontes_padrao():
    srcs = S.load_sources()
    kinds = {s.kind for s in srcs}
    assert kinds <= set(S.SOURCE_KINDS)
    assert {"rss", "steam", "anilist", "reddit"} <= kinds
    assert all(1 <= s.trust <= 3 for s in srcs)
    rss = {s.name for s in srcs if s.kind == "rss"}
    assert {"Anime News Network", "Crunchyroll News", "Gematsu", "PC Gamer", "IGN Games"} <= rss
    assert all(s.trust == 1 for s in srcs if s.kind == "reddit")


def test_overrides_da_config():
    cfg = {
        "news": {
            "sources": [
                {"name": "IGN Games", "trust": 1},
                {"name": "Gematsu", "enabled": False},
                {"name": "Meu site", "kind": "scrape", "url": "https://x.example/n", "trust": 2,
                 "selector": "h2 a"},
            ]
        }
    }
    srcs = {s.name: s for s in S.load_sources(cfg)}
    assert srcs["IGN Games"].trust == 1 and srcs["IGN Games"].kind == "rss"
    assert "Gematsu" not in srcs
    assert srcs["Meu site"].options == {"selector": "h2 a"}
    assert "Gematsu" in {s.name for s in S.load_sources(cfg, include_disabled=True)}
    only = S.load_sources({"news": {"defaults": False, "sources": [cfg["news"]["sources"][2]]}})
    assert [s.name for s in only] == ["Meu site"]


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "a", "kind": "rss", "url": "https://a.example", "trust": 4},
        {"name": "a", "kind": "rss", "url": "https://a.example", "trust": True},
        {"name": "a", "kind": "twitter", "url": "https://a.example", "trust": 1},
        {"name": "a", "kind": "rss", "url": "ftp://a.example", "trust": 1},
        {"name": "a", "kind": "rss", "trust": 1},
        {"name": "dup", "kind": "rss", "url": "https://www.gematsu.com/feed#x", "trust": 1},
    ],
)
def test_fonte_invalida(bad):
    with pytest.raises(S.SourceError):
        S.load_sources({"news": {"sources": [bad]}})


def test_normalize_url():
    n = S.normalize_url
    assert n(" https://A.example/x?utm_source=rss&id=3&fbclid=z#top ") == "https://a.example/x?id=3"
    assert n("https://a.example") == "https://a.example/"
    assert n("https://a.example/x?b=2&a=1") == "https://a.example/x?b=2&a=1"


# --- RSS -------------------------------------------------------------------------------------


def test_parse_rss_e_atom():
    anime = parse_feed((FEEDS / "anime.xml").read_bytes(), source_id=7, now=NOW)
    assert len(anime) == 2  # item sem link pulado
    first = anime[0]
    assert first.source_id == 7 and first.fetched_at == NOW
    assert first.title == "Frieren Season 3 announced"
    assert first.body == "The third season of Frieren was announced."
    assert first.published_at == datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    games = parse_feed((FEEDS / "games.xml").read_bytes(), source_id=8)
    assert [g.url for g in games] == ["https://games.example/silksong-dlc", "https://shared.example/story"]
    assert games[0].body == "Team Cherry dated the DLC."
    assert parse_feed((FEEDS / "anime.xml").read_bytes(), 1, max_items=1)[0].url.startswith("https://anime")


def test_feed_ilegivel():
    with pytest.raises(FeedError):
        parse_feed(b"<html><body>nope", source_id=1)


async def test_coletor_rss_usa_http():
    async with httpx.AsyncClient(transport=_transport()) as http:
        ctx = S.CollectContext(http=http, now=NOW)
        raws = await RssCollector().collect(replace(ANIME, id=5), ctx)
    assert len(raws) == 2 and all(r.source_id == 5 for r in raws)


def test_registro_de_coletores():
    assert S.collector_factory("rss") is not None
    assert isinstance(S.collector_factory("rss")(None), S.Collector)


# --- coleta ----------------------------------------------------------------------------------


async def test_coleta_deduplica_e_isola_erros():
    repo = MemRepo()
    calls: list[str] = []
    reddit = S.SourceConfig("r/x", "reddit", "https://reddit.example/r/x", 1)
    async with httpx.AsyncClient(transport=_transport(calls)) as http:
        rep = await S.collect_all(repo, [ANIME, GAMES, BROKEN, reddit], http, now=NOW)
        assert rep.new == 3  # frieren, shared, silksong
        assert rep.duplicates == 1  # shared.example/story nas duas
        assert rep.errors == 1
        by = {s.name: s for s in rep.sources}
        assert "500" in by["Broken"].error
        assert by["r/x"].skipped  # sem coletor reddit ainda (6.4)
        assert "https://anime.example/news/frieren-s3" in repo.raw
        assert all(r.fetched_at == NOW for r in repo.raw.values())
        again = await S.collect_all(repo, [ANIME, GAMES], http, now=NOW)
    assert again.new == 0 and again.duplicates == 4
    assert len(repo.raw) == 3
    assert {s.url for s in await repo.sources()} == {ANIME.url, GAMES.url, BROKEN.url, reddit.url}
    assert "3 novos" in rep.summary()


class SlowCollector:
    kind = "scrape"

    async def collect(self, source, ctx):
        await asyncio.sleep(10)
        return []


async def test_teto_de_tempo():
    S.register_collector("scrape", lambda cfg: SlowCollector())
    try:
        slow = S.SourceConfig("Lenta", "scrape", "https://slow.example", 1)
        async with httpx.AsyncClient(transport=_transport()) as http:
            rep = await S.collect_all(MemRepo(), [slow, ANIME], http, source_timeout_s=0.2)
            assert "tempo esgotado" in rep.sources[0].error
            assert rep.new == 2
            rep = await S.collect_all(MemRepo(), [slow], http, timeout_s=0.2, source_timeout_s=5)
            assert "tempo total" in rep.sources[0].error
            assert rep.seconds < 2
    finally:
        S.unregister_collector("scrape")


# --- banco -----------------------------------------------------------------------------------


@pytest.fixture
def schema():
    name = f"test_news_{uuid.uuid4().hex[:10]}"
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
async def test_pg_repo_fontes_e_cruas(schema):
    repo = await PgNewsRepo.connect(mig.dsn_from_env(), schema=schema)
    try:
        assert isinstance(repo, NewsRepo)
        sid = await repo.upsert_source(ANIME.to_news_source())
        assert await repo.upsert_source(replace(ANIME, trust=2).to_news_source()) == sid
        assert [(s.id, s.trust) for s in await repo.sources()] == [(sid, 2)]
        raw = NewsRaw(source_id=sid, url="https://a.example/1", title="t", published_at=NOW)
        rid = await repo.add_raw(raw)
        assert rid is not None
        assert await repo.add_raw(replace(raw, title="outro")) is None
        got = await repo.ungrouped_raw()
        assert [(r.id, r.url, r.published_at) for r in got] == [(rid, raw.url, NOW)]
        assert got[0].fetched_at is not None
        with pytest.raises(NotImplementedError):
            await repo.unclassified()
    finally:
        await repo.close()


@pytest.mark.db
def test_magi_news_main(schema, tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        f"""
[database]
dsn = "{mig.dsn_from_env()}?options=-csearch_path%3D{schema},public"

[news]
defaults = false
[[news.sources]]
name = "{ANIME.name}"
kind = "rss"
url = "{ANIME.url}"
trust = 3
[[news.sources]]
name = "{GAMES.name}"
kind = "rss"
url = "{GAMES.url}"
trust = 2
"""
    )
    monkeypatch.setattr(news_main, "make_http_client", lambda: httpx.AsyncClient(transport=_transport()))
    assert news_main.main(["--config", str(cfg)]) == 0
    assert news_main.main(["--config", str(cfg)]) == 0
    with psycopg.connect(mig.dsn_from_env()) as c:
        def count(table):
            q = sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table))
            return c.execute(q).fetchone()[0]

        assert count("news_raw") == 3 and count("news_sources") == 2


def test_main_sem_banco(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    dsn = "postgresql://x:y@127.0.0.1:1/z?connect_timeout=1"
    cfg.write_text(f'[database]\ndsn = "{dsn}"\n[news]\ndefaults = false\n')
    assert news_main.main(["--config", str(cfg)]) == 2
