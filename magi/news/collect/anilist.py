"""Coletor AniList: temporadas, sequências e episódios das obras da minha lista (tarefa 6.3).

Usa a API GraphQL pública do AniList (``https://graphql.anilist.co``, sem autenticação).

Opções da fonte (campos extras em ``[[news.sources]]``):

- ``username``: usuário do AniList. Com ele, lê a lista de anime (CURRENT, PLANNING e
  COMPLETED) e gera itens de:

  * sequências (relação SEQUEL) ainda não lançadas ou em exibição, com data quando houver;
    sequências que já estão na lista como CURRENT/COMPLETED ficam de fora;
  * próximo episódio das obras CURRENT/PLANNING em exibição que sai em até
    ``episode_window_days`` dias.

  Sem ``username`` ou com a lista vazia, coleta as obras mais populares da temporada atual e
  da seguinte que ainda não terminaram, marcando as que são sequência de outra obra (cobre
  também quem usa MyAnimeList). Usuário inexistente ou com lista privada é erro (HTTP 404).
- ``popular_count`` (padrão 20): obras por temporada no modo sem usuário;
- ``episode_window_days`` (padrão 7);
- ``max_pages`` (padrão 10, 50 entradas cada): teto de páginas da lista do usuário;
- ``rate_per_min`` (padrão 90, o limite do AniList; cai sozinho se o cabeçalho
  ``X-RateLimit-Limit`` vier menor, como os 30/min do modo degradado);
- ``deadline_s`` (padrão 5 s abaixo do teto por fonte): passado esse tempo, devolve o que já
  chegou em vez de perder tudo no corte de :func:`~magi.news.sources.collect_all`.

URLs: a página da obra no AniList (``https://anilist.co/anime/<id>``), estável entre execuções
para a deduplicação. Episódios usam ``?episodio=N`` na mesma página (o fragmento ``#`` some na
normalização). Respostas 429 são tratadas esperando ``Retry-After`` dentro do prazo.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx

from magi.common.config import Config
from magi.common.contracts import NewsRaw
from magi.news.sources import SOURCE_TIMEOUT_S, CollectContext, SourceConfig

log = logging.getLogger(__name__)

DEFAULT_POPULAR_COUNT = 20
DEFAULT_EPISODE_WINDOW_DAYS = 7
DEFAULT_MAX_PAGES = 10
DEFAULT_RATE_PER_MIN = 90
DEFAULT_DEADLINE_S = SOURCE_TIMEOUT_S - 5.0
LIST_PER_PAGE = 50
LIST_STATUSES = ("CURRENT", "PLANNING", "COMPLETED")
UPCOMING = ("NOT_YET_RELEASED", "RELEASING")
MAX_BODY_CHARS = 600
MEDIA_URL = "https://anilist.co/anime/{id}"

SEASONS = ("WINTER", "SPRING", "SUMMER", "FALL")  # jan-mar, abr-jun, jul-set, out-dez
SEASON_PT = {"WINTER": "inverno", "SPRING": "primavera", "SUMMER": "verão", "FALL": "outono"}

_MEDIA = """
  id type format status episodes season seasonYear
  title { romaji english }
  startDate { year month day }
  nextAiringEpisode { episode airingAt }
"""

LIST_QUERY = f"""
query ($user: String, $page: Int, $perPage: Int, $status: [MediaListStatus]) {{
  Page(page: $page, perPage: $perPage) {{
    pageInfo {{ hasNextPage }}
    mediaList(userName: $user, type: ANIME, status_in: $status) {{
      status
      media {{
        {_MEDIA}
        relations {{ edges {{ relationType node {{ {_MEDIA} description(asHtml: false) }} }} }}
      }}
    }}
  }}
}}
"""

SEASON_QUERY = f"""
query ($season: MediaSeason, $year: Int, $perPage: Int) {{
  Page(page: 1, perPage: $perPage) {{
    media(season: $season, seasonYear: $year, type: ANIME, sort: POPULARITY_DESC,
          status_in: [NOT_YET_RELEASED, RELEASING], isAdult: false) {{
      {_MEDIA}
      description(asHtml: false)
      relations {{ edges {{ relationType node {{ {_MEDIA} }} }} }}
    }}
  }}
}}
"""

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class AniListError(RuntimeError):
    """Erro devolvido pela API (campo ``errors`` do GraphQL ou HTTP)."""


# --- formatação ------------------------------------------------------------------------------


def season_of(now: datetime) -> tuple[str, int]:
    return SEASONS[(now.month - 1) // 3], now.year


def next_season(season: str, year: int) -> tuple[str, int]:
    i = SEASONS.index(season)
    return (SEASONS[0], year + 1) if i == 3 else (SEASONS[i + 1], year)


def media_title(media: dict[str, Any]) -> str:
    t = media.get("title") or {}
    return t.get("english") or t.get("romaji") or f"anime {media.get('id')}"


def media_url(media: dict[str, Any]) -> str:
    return MEDIA_URL.format(id=media["id"])


def when(media: dict[str, Any]) -> str:
    """Data de estreia o mais precisa possível: ``05/04/2027``, ``04/2027``, ``primavera 2027``,
    ``2027`` ou ``""``."""
    d = media.get("startDate") or {}
    y, m, day = d.get("year"), d.get("month"), d.get("day")
    if y and m and day:
        return f"{day:02d}/{m:02d}/{y}"
    if y and m:
        return f"{m:02d}/{y}"
    season, sy = media.get("season"), media.get("seasonYear") or y
    if season in SEASON_PT and sy:
        return f"{SEASON_PT[season]} {sy}"
    return str(y) if y else ""


def to_text(desc: str | None, limit: int = MAX_BODY_CHARS) -> str:
    text = _WS.sub(" ", html.unescape(_TAG.sub(" ", desc or ""))).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _body(media: dict[str, Any], extra: str = "") -> str:
    parts = [p for p in (
        extra,
        f"Formato: {media['format']}." if media.get("format") else "",
        f"Episódios: {media['episodes']}." if media.get("episodes") else "",
        f"Estreia: {when(media)}." if when(media) else "",
        to_text(media.get("description")),
    ) if p]
    return " ".join(parts)


def _start(media: dict[str, Any]) -> datetime | None:
    d = media.get("startDate") or {}
    if d.get("year") and d.get("month") and d.get("day"):
        return datetime(d["year"], d["month"], d["day"], tzinfo=UTC)
    return None


def sequel_item(parent: dict[str, Any], seq: dict[str, Any], source_id: int,
                now: datetime) -> NewsRaw:
    date = when(seq)
    if seq.get("status") == "RELEASING":
        title = f"Sequência de {media_title(parent)} em exibição: {media_title(seq)}"
    else:
        title = f"Sequência de {media_title(parent)} anunciada: {media_title(seq)}"
        if date:
            title += f" ({date})"
    return NewsRaw(source_id=source_id, url=media_url(seq), title=title,
                   body=_body(seq, f"Continuação de {media_title(parent)}."),
                   published_at=None, fetched_at=now)


def episode_item(media: dict[str, Any], source_id: int, now: datetime) -> NewsRaw:
    ep = media["nextAiringEpisode"]
    at = datetime.fromtimestamp(ep["airingAt"], UTC)
    title = f"Episódio {ep['episode']} de {media_title(media)} sai em {at:%d/%m %H:%M} UTC"
    return NewsRaw(source_id=source_id, url=f"{media_url(media)}?episodio={ep['episode']}",
                   title=title, body=_body(media), published_at=None, fetched_at=now)


def seasonal_item(media: dict[str, Any], source_id: int, now: datetime) -> NewsRaw:
    prequel = next((e["node"] for e in (media.get("relations") or {}).get("edges") or []
                    if e.get("relationType") == "PREQUEL"
                    and (e.get("node") or {}).get("type") == "ANIME"), None)
    date = when(media)
    suffix = f" ({date})" if date else ""
    if prequel is not None:
        title = f"Sequência de {media_title(prequel)} anunciada: {media_title(media)}{suffix}"
        extra = f"Continuação de {media_title(prequel)}."
    else:
        title = f"Anime da temporada: {media_title(media)}{suffix}"
        extra = ""
    return NewsRaw(source_id=source_id, url=media_url(media), title=title,
                   body=_body(media, extra), published_at=_start(media), fetched_at=now)


def items_from_list(entries: Sequence[dict[str, Any]], source_id: int, now: datetime,
                    episode_window: timedelta = timedelta(days=DEFAULT_EPISODE_WINDOW_DAYS),
                    ) -> list[NewsRaw]:
    """Itens a partir das entradas ``mediaList`` (``status`` + ``media`` com relações)."""
    status_by_id = {e["media"]["id"]: e.get("status") for e in entries if e.get("media")}
    out: dict[str, NewsRaw] = {}
    limit = now + episode_window
    for entry in entries:
        media = entry.get("media")
        if not media:
            continue
        nxt = media.get("nextAiringEpisode")
        if (nxt and entry.get("status") in ("CURRENT", "PLANNING")
                and datetime.fromtimestamp(nxt["airingAt"], UTC) <= limit):
            raw = episode_item(media, source_id, now)
            out.setdefault(raw.url, raw)
        for edge in (media.get("relations") or {}).get("edges") or []:
            seq = edge.get("node") or {}
            if (edge.get("relationType") != "SEQUEL" or seq.get("type") != "ANIME"
                    or seq.get("status") not in UPCOMING
                    or status_by_id.get(seq.get("id")) in ("CURRENT", "COMPLETED")):
                continue
            raw = sequel_item(media, seq, source_id, now)
            out.setdefault(raw.url, raw)
    return list(out.values())


# --- HTTP ------------------------------------------------------------------------------------


class _Deadline(Exception):
    """Prazo da fonte esgotado: devolve o que já chegou."""


class _Client:
    """POST GraphQL com limite de taxa (janela de 60 s), espera em 429 e prazo."""

    def __init__(self, http: httpx.AsyncClient, url: str, rate_per_min: int, deadline: float,
                 sleep: Callable[[float], Awaitable[Any]], clock: Callable[[], float]) -> None:
        self.http, self.url, self.rate = http, url, max(1, rate_per_min)
        self.deadline, self.sleep, self.clock = deadline, sleep, clock
        self.sent: deque[float] = deque()

    async def _wait(self, seconds: float) -> None:
        if self.clock() + seconds > self.deadline:
            raise _Deadline
        if seconds > 0:
            await self.sleep(seconds)

    async def query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        for _attempt in range(3):
            now = self.clock()
            while self.sent and now - self.sent[0] >= 60:
                self.sent.popleft()
            if len(self.sent) >= self.rate:
                await self._wait(60 - (now - self.sent[0]))
            self.sent.append(self.clock())
            resp = await self.http.post(self.url, json={"query": query, "variables": variables},
                                        headers={"Accept": "application/json"})
            if resp.status_code == 429:
                retry = resp.headers.get("Retry-After", "60")
                log.info("anilist: 429, esperando %s s", retry)
                await self._wait(float(retry) if retry.replace(".", "", 1).isdigit() else 60.0)
                continue
            data = _json(resp)
            if data.get("errors") and (resp.is_error or not data.get("data")):
                msg = "; ".join(str(e.get("message")) for e in data["errors"])
                raise AniListError(f"HTTP {resp.status_code}: {msg}")
            resp.raise_for_status()
            limit = resp.headers.get("X-RateLimit-Limit", "")
            if limit.isdigit() and 0 < int(limit) < self.rate:  # AniList baixa o limite às vezes
                self.rate = int(limit)
            if resp.headers.get("X-RateLimit-Remaining") == "0":
                self.sent.extend([self.clock()] * self.rate)  # força espera na próxima
            return data.get("data") or {}
        raise AniListError("429 repetido")


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise AniListError(f"resposta não-JSON (HTTP {resp.status_code})") from None
    return data if isinstance(data, dict) else {}


# --- coletor ---------------------------------------------------------------------------------


class AniListCollector:
    kind: ClassVar[str] = "anilist"

    def __init__(self, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._sleep, self._clock = sleep, clock

    async def collect(self, source: SourceConfig, ctx: CollectContext) -> Sequence[NewsRaw]:
        if source.id is None:
            raise ValueError(f"fonte {source.name!r} sem id (grave antes com upsert_source)")
        opts = source.options
        deadline_s = float(opts.get("deadline_s", DEFAULT_DEADLINE_S))
        client = _Client(ctx.http, source.url, int(opts.get("rate_per_min", DEFAULT_RATE_PER_MIN)),
                         self._clock() + deadline_s, self._sleep, self._clock)
        out: list[NewsRaw] = []
        try:
            user = str(opts.get("username") or "").strip()
            entries = await self._from_user(client, user, source, ctx, out) if user else 0
            if not entries:
                if user:
                    log.info("anilist: lista de %s vazia; usando a temporada", user)
                await self._seasonal(client, source, ctx, out)
        except _Deadline:
            log.warning("anilist: prazo de %.0f s esgotado; devolvendo %d itens", deadline_s,
                        len(out))
            if not out:
                raise TimeoutError("anilist: prazo esgotado sem resposta") from None
        return out

    async def _from_user(self, client: _Client, user: str, source: SourceConfig,
                         ctx: CollectContext, out: list[NewsRaw]) -> int:
        """Itens da lista do usuário em ``out``; devolve quantas entradas a lista tem."""
        opts = source.options
        max_pages = max(1, int(opts.get("max_pages", DEFAULT_MAX_PAGES)))
        window = timedelta(days=float(opts.get("episode_window_days",
                                               DEFAULT_EPISODE_WINDOW_DAYS)))
        entries: list[dict[str, Any]] = []
        try:
            for page in range(1, max_pages + 1):
                data = await client.query(LIST_QUERY, {"user": user, "page": page,
                                                       "perPage": LIST_PER_PAGE,
                                                       "status": list(LIST_STATUSES)})
                pg = data.get("Page") or {}
                entries.extend(pg.get("mediaList") or [])
                if not (pg.get("pageInfo") or {}).get("hasNextPage"):
                    break
        finally:  # no prazo, aproveita as páginas que chegaram
            out.extend(items_from_list(entries, source.id or 0, ctx.now, window))
        return len(entries)

    async def _seasonal(self, client: _Client, source: SourceConfig, ctx: CollectContext,
                        out: list[NewsRaw]) -> None:
        count = max(1, min(50, int(source.options.get("popular_count", DEFAULT_POPULAR_COUNT))))
        season, year = season_of(ctx.now)
        seen: set[str] = set()
        for s, y in ((season, year), next_season(season, year)):
            data = await client.query(SEASON_QUERY, {"season": s, "year": y, "perPage": count})
            for media in (data.get("Page") or {}).get("media") or []:
                raw = seasonal_item(media, source.id or 0, ctx.now)
                if raw.url not in seen:
                    seen.add(raw.url)
                    out.append(raw)


def make_collector(config: Config | None = None) -> AniListCollector:
    return AniListCollector()
