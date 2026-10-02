"""Tarefa 6.5: coletor de scraping genérico (R18.2). Sem rede: ``httpx.MockTransport``."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from magi.news import sources as S
from magi.news.collect import scrape
from magi.news.collect.scrape import DomainLimiter, RobotsDisallowed, ScrapeCollector

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

PAGE = """<html><head><title>Notícias</title></head><body>
<article class="post">
  <h2><a href="/noticias/1-nova-temporada">Nova temporada anunciada</a></h2>
  <time datetime="2026-09-30T10:00:00Z">30/09/2026 07:00</time>
  <p class="resumo">Estúdio <b>confirma</b> a sequência.</p>
</article>
<article class="post">
  <h2><a href="noticias/2-patch">Patch 1.2 lançado</a></h2>
  <time datetime="ontem">01/10/2026 09:30</time>
</article>
<article class="post">
  <h2><a href="https://outro.com/3">Matéria externa</a></h2>
</article>
<article class="post"><h2>Sem link</h2></article>
<article class="post"><h2><a href="javascript:void(0)">JS</a></h2></article>
<article class="post"><h2><a href="/noticias/1-nova-temporada">Repetida</a></h2></article>
</body></html>"""

OPTIONS = {
    "selector": "article.post",
    "title": "h2",
    "link": "h2 a",
    "date": "time",
    "date_attr": "datetime",
    "summary": "p.resumo",
}


def _source(url: str = "https://exemplo.com/secao/lista", **options) -> S.SourceConfig:
    return S.SourceConfig(name="Exemplo", kind="scrape", url=url, trust=2,
                          options={**OPTIONS, **options}, id=7)


def _client(robots: str | int = "User-agent: *\nAllow: /\n", calls: list[httpx.Request] | None = None,
            pages: dict[str, str] | None = None) -> httpx.AsyncClient:
    pages = pages or {"/secao/lista": PAGE}

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.url.path == "/robots.txt":
            if isinstance(robots, int):
                return httpx.Response(robots, text="")
            return httpx.Response(200, text=robots)
        body = pages.get(request.url.path)
        if body is None:
            return httpx.Response(404, text="não achei")
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class FakeClock:
    """Relógio falso: ``sleep`` só avança o tempo."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _collector(clock: FakeClock | None = None) -> ScrapeCollector:
    clock = clock or FakeClock()
    return ScrapeCollector(limiter=DomainLimiter(clock=clock, sleep=clock.sleep))


async def test_extracao_e_url_relativa():
    calls: list[httpx.Request] = []
    async with _client(calls=calls) as http:
        raws = await _collector().collect(_source(), S.CollectContext(http=http, now=NOW))
    assert [r.url for r in raws] == [
        "https://exemplo.com/noticias/1-nova-temporada",
        "https://exemplo.com/secao/noticias/2-patch",
        "https://outro.com/3",
    ]
    first, second, third = raws
    assert first.title == "Nova temporada anunciada"
    assert first.body == "Estúdio confirma a sequência."
    assert first.published_at == datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    assert first.source_id == 7 and first.fetched_at == NOW
    assert second.published_at is None  # data ilegível vira None
    assert third.body == ""
    assert all(c.headers["user-agent"] == S.USER_AGENT for c in calls)
    assert [c.url.path for c in calls] == ["/robots.txt", "/secao/lista"]


async def test_data_com_formato_max_items_e_base_href():
    page = '<head><base href="https://cdn.exemplo.com/a/"></head>' + PAGE
    opts = {"date_attr": None, "date_format": "%d/%m/%Y %H:%M", "max_items": 2}
    async with _client(pages={"/secao/lista": page}) as http:
        raws = await _collector().collect(_source(**opts), S.CollectContext(http=http, now=NOW))
    assert [r.url for r in raws] == [
        "https://cdn.exemplo.com/noticias/1-nova-temporada",
        "https://cdn.exemplo.com/a/noticias/2-patch",
    ]
    assert raws[0].published_at == datetime(2026, 9, 30, 7, 0, tzinfo=UTC)
    assert raws[1].published_at == datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


async def test_padroes_sem_title_e_link():
    page = '<ul><li><a href="/x">Item X</a></li><li><span>sem link</span></li></ul>'
    src = S.SourceConfig(name="L", kind="scrape", url="https://exemplo.com/l", trust=1,
                         options={"selector": "li"}, id=1)
    async with _client(pages={"/l": page}) as http:
        raws = await _collector().collect(src, S.CollectContext(http=http, now=NOW))
    assert [(r.url, r.title) for r in raws] == [("https://exemplo.com/x", "Item X")]


async def test_robots_proibindo_nao_coleta():
    calls: list[httpx.Request] = []
    robots = "User-agent: magi-news\nDisallow: /secao/\n\nUser-agent: *\nAllow: /\n"
    async with _client(robots=robots, calls=calls) as http:
        with pytest.raises(RobotsDisallowed, match="robots.txt proíbe"):
            await _collector().collect(_source(), S.CollectContext(http=http, now=NOW))
    assert [c.url.path for c in calls] == ["/robots.txt"]  # a página nem foi pedida


@pytest.mark.parametrize("status,allowed", [(404, True), (403, False), (503, False)])
async def test_robots_por_status(status, allowed):
    async with _client(robots=status) as http:
        coro = _collector().collect(_source(), S.CollectContext(http=http, now=NOW))
        if allowed:
            assert len(await coro) == 3
        else:
            with pytest.raises(RobotsDisallowed):
                await coro


async def test_robots_em_cache_e_limitador_1_por_segundo():
    calls: list[httpx.Request] = []
    clock = FakeClock()
    collector = _collector(clock)
    pages = {"/secao/lista": PAGE, "/outra": PAGE}
    async with _client(calls=calls, pages=pages) as http:
        ctx = S.CollectContext(http=http, now=NOW)
        await asyncio.gather(
            collector.collect(_source(), ctx),
            collector.collect(_source("https://exemplo.com/outra"), ctx),
        )
        await collector.collect(_source("https://outro.com/secao/lista"), ctx)
    paths = [(c.url.host, c.url.path) for c in calls]
    assert paths.count(("exemplo.com", "/robots.txt")) == 1  # cache por domínio
    assert len([p for p in paths if p[0] == "exemplo.com"]) == 3
    # exemplo.com: 3 requisições = 2 esperas; outro.com (robots + página) = 1 espera, e a
    # primeira dele não espera pelo outro domínio
    assert clock.sleeps == [1.0, 1.0, 1.0]


async def test_crawl_delay_maior_que_1s():
    clock = FakeClock()
    collector = _collector(clock)
    async with _client(robots="User-agent: *\nCrawl-delay: 3\n") as http:
        await collector.collect(_source(), S.CollectContext(http=http, now=NOW))
    assert clock.sleeps == [3.0]


async def test_limitador_nao_espera_se_ja_passou_o_intervalo():
    clock = FakeClock()
    lim = DomainLimiter(clock=clock, sleep=clock.sleep)
    await lim.wait("https://a.com")
    clock.t += 0.4
    await lim.wait("https://a.com")
    clock.t += 5
    await lim.wait("https://a.com")
    await lim.wait("https://b.com")
    assert clock.sleeps == [pytest.approx(0.6)]


async def test_sem_selector_e_erro_de_config():
    src = S.SourceConfig(name="X", kind="scrape", url="https://exemplo.com/", trust=1, id=1)
    async with _client() as http:
        with pytest.raises(S.SourceError):
            await _collector().collect(src, S.CollectContext(http=http, now=NOW))


def test_fabrica_registrada_pelo_kind():
    assert S.collector_factory("scrape") is scrape.make_collector
    collector = scrape.make_collector(None)
    assert isinstance(collector, S.Collector) and collector.kind == "scrape"
