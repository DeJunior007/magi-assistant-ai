"""Coletor Steam News: notícias dos jogos instalados (design §8 passo 1; R18.1; tarefa 6.2).

Usa a API pública ``ISteamNews/GetNewsForApp/v2`` (sem chave), uma requisição por jogo do
:class:`~magi.core.catalog.SteamCatalog` (ferramentas como Proton e runtimes ficam de fora).
O conteúdo vem em BBCode (anúncios da Steam) ou HTML (feeds externos) e vira texto simples.

Opções da fonte (campos extras em ``[[news.sources]]``):

- ``count`` (padrão 5): notícias por jogo;
- ``feeds`` (padrão ``"steam_community_announcements"``, só os anúncios oficiais, coerente com a
  confiança 3); ``""`` traz também os feeds externos que a Steam agrega;
- ``concurrency`` (padrão 4): requisições simultâneas;
- ``deadline_s`` (padrão 5 s abaixo do teto por fonte): passado esse tempo, devolve o que já
  chegou em vez de perder tudo no corte de :func:`~magi.news.sources.collect_all`;
- ``steam_root``: raiz da Steam, se não for a padrão.

Erro num jogo só é registrado no log; a fonte só falha se todas as requisições falharem.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

from selectolax.parser import HTMLParser

from magi.common.config import Config
from magi.common.contracts import Game, GameCatalog, NewsRaw
from magi.core.catalog import MemoryAliasStore, SteamCatalog, is_tool
from magi.news.sources import SOURCE_TIMEOUT_S, CollectContext, SourceConfig

log = logging.getLogger(__name__)

DEFAULT_COUNT = 5
DEFAULT_FEEDS = "steam_community_announcements"
DEFAULT_CONCURRENCY = 4
DEFAULT_DEADLINE_S = SOURCE_TIMEOUT_S - 5.0
MAX_BODY_CHARS = 2000

# --- BBCode/HTML -> texto ------------------------------------------------------------------------

# Blocos sem texto útil: imagens, vídeos e embeds somem com o conteúdo.
_DROP_BLOCKS = re.compile(
    r"\[(img|previewyoutube|video|dynamiclink)\b[^\]]*\].*?\[/\1\]", re.IGNORECASE | re.DOTALL
)
_BBCODE_TAGS = (
    "b|i|u|s|strike|h[1-6]|url|img|list|olist|quote|code|spoiler|noparse|hr|table|tr|th|td|"
    "previewyoutube|video|dynamiclink|expand|p|c|carousel|section|center|color|size|emoticon"
)
_BBCODE_TAG = re.compile(rf"\[/?(?:{_BBCODE_TAGS})\b[^\]]*\]", re.IGNORECASE)
_BULLET = re.compile(r"\[\*\]")
_PLACEHOLDER = re.compile(r"\{STEAM_[A-Z_]+\}\S*")
_WS = re.compile(r"\s+")


def to_text(content: str, limit: int = MAX_BODY_CHARS) -> str:
    """BBCode da Steam e/ou HTML em texto simples de uma linha, cortado em ``limit``."""
    if not content:
        return ""
    text = _DROP_BLOCKS.sub(" ", content)
    text = _BULLET.sub(" • ", text)
    text = _BBCODE_TAG.sub(" ", text)
    text = _PLACEHOLDER.sub(" ", text)
    if "<" in text and ">" in text:
        text = HTMLParser(f"<div>{text}</div>").text(separator=" ")
    else:
        text = html.unescape(text)
    text = _WS.sub(" ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _title(game: Game, title: str) -> str:
    """Prefixa o nome do jogo quando o título não o cita (``"Patch 1.2"`` sozinho não diz nada)."""
    title = to_text(title, 300) or "(sem título)"
    return title if game.name.casefold() in title.casefold() else f"{game.name}: {title}"


def parse_news(data: Any, game: Game, source_id: int, now: datetime | None = None,
               count: int = DEFAULT_COUNT) -> list[NewsRaw]:
    """Converte a resposta JSON de ``GetNewsForApp`` em ``NewsRaw``."""
    items = (data or {}).get("appnews", {}).get("newsitems") or []
    out: list[NewsRaw] = []
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        date = item.get("date")
        published = datetime.fromtimestamp(int(date), UTC) if date else None
        out.append(NewsRaw(
            source_id=source_id,
            url=url,
            title=_title(game, str(item.get("title") or "")),
            body=to_text(str(item.get("contents") or "")),
            published_at=published,
            fetched_at=now,
        ))
        if len(out) >= count:
            break
    return out


# --- coletor -------------------------------------------------------------------------------------


class SteamNewsCollector:
    kind: ClassVar[str] = "steam"

    def __init__(self, catalog: GameCatalog | None = None) -> None:
        self._catalog = catalog  # None: SteamCatalog lido a cada coleta (jogos mudam)

    def _games(self, source: SourceConfig) -> list[Game]:
        cat = self._catalog
        if cat is None:
            cat = SteamCatalog(source.options.get("steam_root"), aliases=MemoryAliasStore())
        return [g for g in cat.all() if not is_tool(g)]

    async def collect(self, source: SourceConfig, ctx: CollectContext) -> Sequence[NewsRaw]:
        if source.id is None:
            raise ValueError(f"fonte {source.name!r} sem id (grave antes com upsert_source)")
        source_id = source.id
        opts = source.options
        count = max(1, int(opts.get("count", DEFAULT_COUNT)))
        feeds = str(opts.get("feeds", DEFAULT_FEEDS))
        concurrency = max(1, int(opts.get("concurrency", DEFAULT_CONCURRENCY)))
        deadline_s = float(opts.get("deadline_s", DEFAULT_DEADLINE_S))

        started = time.monotonic()
        games = await asyncio.to_thread(self._games, source)
        if not games:
            log.info("steam: nenhum jogo instalado encontrado")
            return []
        sem = asyncio.Semaphore(concurrency)
        params: dict[str, Any] = {"count": count, "maxlength": 0, "format": "json"}
        if feeds:
            params["feeds"] = feeds

        async def one(game: Game) -> list[NewsRaw]:
            async with sem:
                resp = await ctx.http.get(source.url, params={**params, "appid": game.appid})
            if resp.status_code in (403, 404):  # app sem página de notícias
                return []
            resp.raise_for_status()
            return parse_news(resp.json(), game, source_id, ctx.now, count)

        tasks = {asyncio.create_task(one(g), name=f"steam:{g.appid}"): g for g in games}
        remaining = max(0.1, deadline_s - (time.monotonic() - started))
        done, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            log.warning("steam: prazo de %.0f s esgotado; %d de %d jogos sem resposta",
                        deadline_s, len(pending), len(tasks))

        out: list[NewsRaw] = []
        errors: list[BaseException] = []
        for task in done:
            exc = task.exception()
            if exc is not None:
                errors.append(exc)
                log.warning("steam: %s (%d): %s", tasks[task].name, tasks[task].appid, exc)
            else:
                out.extend(task.result())
        if errors and len(errors) == len(tasks):
            raise errors[0]
        out.sort(key=lambda r: r.published_at or ctx.now, reverse=True)
        return out


def make_collector(config: Config | None = None) -> SteamNewsCollector:
    return SteamNewsCollector()
