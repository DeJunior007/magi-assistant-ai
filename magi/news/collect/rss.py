"""Coletor RSS/Atom com ``feedparser`` (design §8 passo 1; R18.1).

Opções da fonte (campos extras em ``[[news.sources]]``): ``max_items`` (padrão 50).
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

import feedparser
from selectolax.parser import HTMLParser

from magi.common.config import Config
from magi.common.contracts import NewsRaw
from magi.news.sources import CollectContext, SourceConfig

MAX_ITEMS = 50
MAX_BODY_CHARS = 2000
_WS_RE = re.compile(r"\s+")


class FeedError(RuntimeError):
    """Resposta que não é um feed legível."""


def html_to_text(html: str, limit: int = MAX_BODY_CHARS) -> str:
    if not html:
        return ""
    text = HTMLParser(html).text(separator=" ") if "<" in html else html
    text = _WS_RE.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _when(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t: time.struct_time | None = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    return None


def _link(entry: Any) -> str | None:
    link = entry.get("link")
    if not link:
        guid = entry.get("id") or ""
        link = guid if guid.startswith(("http://", "https://")) else None
    return link.strip() if link else None


def _body(entry: Any) -> str:
    content = entry.get("content") or []
    html = (content[0].get("value") if content else None) or entry.get("summary") or ""
    return html_to_text(html)


def parse_feed(data: bytes, source_id: int, now: datetime | None = None,
               max_items: int = MAX_ITEMS) -> list[NewsRaw]:
    """Converte o conteúdo do feed em ``NewsRaw`` (entradas sem link são ignoradas)."""
    feed = feedparser.parse(data)
    if feed.get("bozo") and not feed.entries:
        raise FeedError(f"feed ilegível: {feed.get('bozo_exception')!r}")
    out: list[NewsRaw] = []
    for entry in feed.entries[:max_items]:
        link = _link(entry)
        if not link:
            continue
        title = html_to_text(entry.get("title") or "", limit=500)
        out.append(
            NewsRaw(
                source_id=source_id,
                url=link,
                title=title or link,
                body=_body(entry),
                published_at=_when(entry),
                fetched_at=now,
            )
        )
    return out


class RssCollector:
    kind: ClassVar[str] = "rss"

    async def collect(self, source: SourceConfig, ctx: CollectContext) -> Sequence[NewsRaw]:
        if source.id is None:
            raise ValueError(f"fonte {source.name!r} sem id (grave antes com upsert_source)")
        resp = await ctx.http.get(source.url)
        resp.raise_for_status()
        max_items = int(source.options.get("max_items", MAX_ITEMS))
        return parse_feed(resp.content, source.id, ctx.now, max_items)


def make_collector(config: Config | None = None) -> RssCollector:
    return RssCollector()
