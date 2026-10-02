"""Coletor de scraping genérico (``kind = "scrape"``; R18.2).

Só para sites sem feed nem API. Baixa uma página HTML (sem JavaScript), acha os itens por
seletor CSS e extrai título, link, data e resumo com seletores relativos ao item.

Regras
------
- ``robots.txt`` é consultado antes de qualquer página (cache por domínio dentro da execução).
  Se proibir a URL, ou não puder ser lido (erro de rede, 5xx, 401/403), a fonte não é coletada e
  :class:`RobotsDisallowed` sobe com o motivo, que :func:`~magi.news.sources.collect_all` grava no
  relatório da fonte. 404 e outros 4xx = sem regras = permitido.
- No máximo 1 requisição por segundo por domínio (ou o ``Crawl-delay`` do ``robots.txt``, se
  maior), contando a do ``robots.txt``. O limitador é do coletor, e ``collect_all`` cria um
  coletor por execução: fontes do mesmo domínio dividem o mesmo limitador.
- User-Agent descritivo (:data:`~magi.news.sources.USER_AGENT`); no ``robots.txt`` vale o
  token :data:`ROBOTS_AGENT` (ou ``*``).
- Links relativos são resolvidos pela URL final da página (ou ``<base href>``); só ``http(s)``.

Configuração (nenhum site escolhido ainda; exemplo para ``config.toml``)::

    [[news.sources]]
    name = "Exemplo Notícias"
    kind = "scrape"
    url = "https://exemplo.com/noticias"
    trust = 2
    selector = "article.post"        # obrigatório: cada item da lista
    title = "h2"                     # relativo ao item; padrão: texto do próprio item
    link = "h2 a"                    # relativo ao item, lê ``href``; padrão: o item se for <a>,
                                     # senão o primeiro a[href] dentro dele
    link_attr = "href"               # opcional
    date = "time"                    # opcional
    date_attr = "datetime"           # opcional: lê o atributo em vez do texto
    date_format = "%d/%m/%Y %H:%M"   # opcional (strptime); sem ele, ISO 8601. Sem fuso = UTC
    summary = "p.resumo"             # opcional
    max_items = 30                   # opcional (padrão 30)
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser, Node

from magi.common.config import Config
from magi.common.contracts import NewsRaw
from magi.news.collect.rss import MAX_BODY_CHARS, html_to_text
from magi.news.sources import USER_AGENT, CollectContext, SourceConfig, SourceError

log = logging.getLogger(__name__)

ROBOTS_AGENT = "magi-news"
MIN_INTERVAL_S = 1.0
MAX_INTERVAL_S = 10.0  # teto para Crawl-delay exagerado (a fonte toda tem ~25 s)
DEFAULT_MAX_ITEMS = 30
MAX_TITLE_CHARS = 300
_HEADERS = {"User-Agent": USER_AGENT}


class RobotsDisallowed(PermissionError):
    """``robots.txt`` proíbe (ou não deixa confirmar) a coleta da URL."""


Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[Any]]


class DomainLimiter:
    """Espaça requisições ao mesmo domínio em pelo menos ``interval`` segundos.

    ``clock`` e ``sleep`` são injetáveis para testes (sem dormir de verdade)."""

    def __init__(self, interval: float = MIN_INTERVAL_S, *, clock: Clock = time.monotonic,
                 sleep: Sleep = asyncio.sleep) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}
        self._intervals: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_interval(self, domain: str, seconds: float) -> None:
        self._intervals[domain] = min(max(self.interval, seconds), MAX_INTERVAL_S)

    async def wait(self, domain: str) -> None:
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            last = self._last.get(domain)
            if last is not None:
                delay = last + self._intervals.get(domain, self.interval) - self._clock()
                if delay > 0:
                    await self._sleep(delay)
            self._last[domain] = self._clock()


@dataclass(frozen=True, slots=True)
class _Robots:
    parser: RobotFileParser | None  # None = tudo permitido
    reason: str | None = None  # motivo para negar tudo (robots ilegível)

    def allowed(self, url: str) -> bool:
        if self.reason:
            return False
        return self.parser is None or self.parser.can_fetch(ROBOTS_AGENT, url)


def _domain(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def _text(node: Node | None) -> str:
    return " ".join(node.text(separator=" ").split()) if node is not None else ""


def _select(item: Node, selector: str | None) -> Node | None:
    if not selector:
        return item
    return item.css_first(selector)


def _parse_date(raw: str, fmt: str | None) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, fmt) if fmt else datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _opt_str(options: Mapping[str, Any], key: str) -> str | None:
    value = options.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise SourceError(f"opção {key!r} precisa ser texto")
    return value


def extract_items(html: str, page_url: str, options: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extrai ``{url, title, body, published_at}`` da página conforme os seletores de ``options``."""
    selector = _opt_str(options, "selector")
    if not selector:
        raise SourceError("fonte scrape precisa da opção 'selector'")
    title_sel = _opt_str(options, "title")
    link_sel = _opt_str(options, "link")
    link_attr = _opt_str(options, "link_attr") or "href"
    date_sel = _opt_str(options, "date")
    date_attr = _opt_str(options, "date_attr")
    date_fmt = _opt_str(options, "date_format")
    summary_sel = _opt_str(options, "summary")
    try:
        max_items = int(options.get("max_items", DEFAULT_MAX_ITEMS))
    except (TypeError, ValueError) as exc:
        raise SourceError("opção 'max_items' precisa ser inteiro") from exc

    tree = HTMLParser(html)
    base = page_url
    base_node = tree.css_first("base[href]")
    if base_node is not None and base_node.attributes.get("href"):
        base = urljoin(page_url, base_node.attributes["href"] or "")

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in tree.css(selector):
        if len(out) >= max_items:
            break
        if link_sel:
            link_node = item.css_first(link_sel)
        elif item.tag == "a":
            link_node = item
        else:
            link_node = item.css_first("a[href]")
        href = (link_node.attributes.get(link_attr) or "").strip() if link_node is not None else ""
        if not href:
            continue
        url = urljoin(base, href)
        if urlsplit(url).scheme not in ("http", "https") or url in seen:
            continue
        title = _text(_select(item, title_sel)) or _text(link_node)
        if not title:
            continue
        published_at = None
        if date_sel:
            date_node = item.css_first(date_sel)
            if date_node is not None:
                raw = (date_node.attributes.get(date_attr) or "") if date_attr else _text(date_node)
                published_at = _parse_date(raw, date_fmt)
        body = ""
        if summary_sel:
            summary_node = item.css_first(summary_sel)
            if summary_node is not None:
                body = html_to_text(summary_node.html or "", MAX_BODY_CHARS)
        seen.add(url)
        out.append({"url": url, "title": title[:MAX_TITLE_CHARS], "body": body,
                    "published_at": published_at})
    return out


class ScrapeCollector:
    """Coletor ``scrape``. Guarda cache de ``robots.txt`` e limitador por domínio da execução."""

    kind: ClassVar[str] = "scrape"

    def __init__(self, config: Config | None = None, *, limiter: DomainLimiter | None = None) -> None:
        self.config = config
        self.limiter = limiter or DomainLimiter()
        self._robots: dict[str, _Robots] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}

    async def _get(self, http: httpx.AsyncClient, url: str) -> httpx.Response:
        await self.limiter.wait(_domain(url))
        return await http.get(url, headers=_HEADERS)

    async def robots(self, http: httpx.AsyncClient, url: str) -> _Robots:
        domain = _domain(url)
        lock = self._robots_locks.setdefault(domain, asyncio.Lock())
        async with lock:
            if domain not in self._robots:
                self._robots[domain] = await self._fetch_robots(http, domain)
            return self._robots[domain]

    async def _fetch_robots(self, http: httpx.AsyncClient, domain: str) -> _Robots:
        robots_url = f"{domain}/robots.txt"
        try:
            resp = await self._get(http, robots_url)
        except httpx.HTTPError as exc:
            return _Robots(None, f"robots.txt ilegível ({type(exc).__name__})")
        if resp.status_code in (401, 403):
            return _Robots(None, f"robots.txt negado (HTTP {resp.status_code})")
        if resp.status_code >= 500:
            return _Robots(None, f"robots.txt indisponível (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            return _Robots(None)  # sem robots.txt: sem restrições
        parser = RobotFileParser(robots_url)
        parser.parse(resp.text.splitlines())
        delay = parser.crawl_delay(ROBOTS_AGENT)
        if delay:
            self.limiter.set_interval(domain, float(delay))
        return _Robots(parser)

    async def collect(self, source: SourceConfig, ctx: CollectContext) -> Sequence[NewsRaw]:
        if source.id is None:
            raise SourceError(f"fonte {source.name!r} sem id")
        if not _opt_str(source.options, "selector"):
            raise SourceError(f"fonte {source.name!r}: scrape precisa da opção 'selector'")
        robots = await self.robots(ctx.http, source.url)
        if not robots.allowed(source.url):
            reason = robots.reason or "robots.txt proíbe"
            log.warning("scrape %s: %s %s; não coletado", source.name, reason, source.url)
            raise RobotsDisallowed(f"{reason}: {source.url}")
        resp = await self._get(ctx.http, source.url)
        resp.raise_for_status()
        items = extract_items(resp.text, str(resp.url), source.options)
        return [
            NewsRaw(source_id=source.id, url=it["url"], title=it["title"], body=it["body"],
                    published_at=it["published_at"], fetched_at=ctx.now)
            for it in items
        ]


def make_collector(config: Config | None = None) -> ScrapeCollector:
    return ScrapeCollector(config)
