"""Coletor Reddit (tarefa 6.4): r/anime, r/Games etc., fontes de confiança 1.

Dois modos, escolhidos sozinhos a cada execução:

* **OAuth "application only"** (client credentials), se o keyring tiver ``reddit-client-id`` e
  ``reddit-client-secret`` (``magi-keys add reddit-client-id``). Lê a listagem JSON em
  ``oauth.reddit.com``, que traz o *flair* do post.
* **Sem credenciais:** feed Atom público ``https://www.reddit.com/r/<sub>/.rss``. Não tem flair.
  Sem login o Reddit libera ~1 requisição por minuto por IP, então as fontes coletadas juntas
  numa execução viram **uma** requisição ``/r/anime+Games/.rss`` e cada uma fica com os posts
  do seu subreddit.

Filtro: com flair, só passam os de notícia/anúncio (``NEWS_FLAIRS``, por trecho, sem caixa;
a fonte pode trocar a lista com ``flairs = [...]``). Sem flair, descarta self-posts (discussão)
e mídia hospedada no próprio Reddit (``allow_self``/``allow_media`` = true liberam). NSFW e
posts fixados sem flair de notícia também ficam de fora.

A URL do item é sempre o permalink do post no Reddit (a deduplicação é por URL e funciona nos
dois modos); o link externo vai no começo do corpo. 429 espera ``Retry-After`` (até
:data:`MAX_WAIT_S`) e tenta de novo.

Opções da fonte (``sources.toml``/``config.toml``): ``subreddit`` (padrão: tirado da URL),
``listing`` (``hot``/``new``/``rising``, padrão ``hot``), ``limit`` (padrão 50), ``flairs``,
``allow_self``, ``allow_media``, ``user_agent``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import urlsplit

import feedparser
import httpx
from selectolax.parser import HTMLParser

from magi.common import secrets
from magi.common.config import Config
from magi.common.contracts import NewsRaw
from magi.news.collect.rss import FeedError, html_to_text
from magi.news.sources import CollectContext, SourceConfig

log = logging.getLogger(__name__)

CLIENT_ID_KEY = "reddit-client-id"
CLIENT_SECRET_KEY = "reddit-client-secret"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_BASE = "https://oauth.reddit.com"
WWW_BASE = "https://www.reddit.com"
# Formato pedido pelo Reddit: <plataforma>:<app>:<versão> (descrição).
USER_AGENT = "linux:magi-assistant.news:0.1 (personal news digest; reads a few subreddits every 2 h)"
NEWS_FLAIRS = ("news", "official", "announcement", "trailer", "teaser", "patch", "update",
               "release", "rumor", "press", "industry", "key visual")
LISTINGS = ("hot", "new", "rising")
DEFAULT_LIMIT = 50
MAX_BODY_CHARS = 2000
MAX_WAIT_S = 10.0  # teto de espera num 429 (a fonte tem 25 s no total)
MAX_RETRIES = 2
BATCH_WINDOW_S = 0.3  # espera para juntar as fontes da mesma execução num só feed
_MEDIA_HOSTS = {"i.redd.it", "v.redd.it", "preview.redd.it", "i.imgur.com"}
_SUB_RE = re.compile(r"/r/([A-Za-z0-9_]{2,21})")

Sleep = Callable[[float], Awaitable[Any]]


class RedditError(RuntimeError):
    """Resposta inesperada do Reddit."""


# --- regras de filtro --------------------------------------------------------------------------


def subreddit_of(source: SourceConfig) -> str:
    sub = source.options.get("subreddit")
    if sub:
        return str(sub).removeprefix("r/").strip("/")
    m = _SUB_RE.search(source.url)
    if not m:
        raise RedditError(f"fonte {source.name!r}: não achei o subreddit em {source.url!r}")
    return m.group(1)


def _is_reddit_host(host: str) -> bool:
    host = host.lower()
    return host == "reddit.com" or host.endswith(".reddit.com") or host == "redd.it"


def is_media(url: str) -> bool:
    parts = urlsplit(url)
    host = parts.hostname or ""
    return host in _MEDIA_HOSTS or (_is_reddit_host(host) and parts.path.startswith("/gallery/"))


def news_flair(flair: str | None, allowed: Sequence[str] = NEWS_FLAIRS) -> bool:
    low = (flair or "").lower()
    return any(word.lower() in low for word in allowed)


def keep_post(*, flair: str | None, is_self: bool, media: bool, source: SourceConfig,
              stickied: bool = False, nsfw: bool = False) -> bool:
    """Decide se um post entra. Flair manda quando existe; sem flair, heurística."""
    if nsfw:
        return False
    opts = source.options
    if flair and flair.strip():
        return news_flair(flair, opts.get("flairs") or NEWS_FLAIRS)
    if stickied:
        return False
    if is_self and not opts.get("allow_self", False):
        return False
    return not (media and not opts.get("allow_media", False))


def _body(external: str | None, flair: str | None, text: str) -> str:
    lines = []
    if external:
        lines.append(f"Link: {external}")
    if flair:
        lines.append(f"Flair: {flair}")
    text = text.strip()
    if text:
        lines.append(text)
    return "\n".join(lines)[:MAX_BODY_CHARS]


def _limit(source: SourceConfig) -> int:
    try:
        return max(1, min(100, int(source.options.get("limit", DEFAULT_LIMIT))))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def _listing(source: SourceConfig) -> str:
    listing = str(source.options.get("listing", "hot")).lower()
    return listing if listing in LISTINGS else "hot"


# --- JSON (OAuth) ------------------------------------------------------------------------------


def parse_listing(data: Mapping[str, Any], source: SourceConfig,
                  now: datetime | None = None) -> list[NewsRaw]:
    """Listagem JSON do Reddit -> ``NewsRaw`` filtrados."""
    if not isinstance(data, Mapping) or not isinstance(data.get("data"), Mapping):
        raise RedditError("listagem sem 'data'")
    out: list[NewsRaw] = []
    for child in data["data"].get("children") or []:
        post = child.get("data") if isinstance(child, Mapping) else None
        if not isinstance(post, Mapping) or not post.get("permalink") or not post.get("title"):
            continue
        is_self = bool(post.get("is_self"))
        external = None if is_self else (post.get("url_overridden_by_dest") or post.get("url"))
        if external and _is_reddit_host(urlsplit(external).hostname or "") \
                and "/comments/" in external:
            external, is_self = None, True  # crosspost/link para outro post: é discussão
        flair = post.get("link_flair_text") or None
        if not keep_post(flair=flair, is_self=is_self, media=bool(external and is_media(external)),
                         source=source, stickied=bool(post.get("stickied")),
                         nsfw=bool(post.get("over_18"))):
            continue
        created = post.get("created_utc")
        published = datetime.fromtimestamp(float(created), UTC) if created else None
        out.append(NewsRaw(
            source_id=source.id or 0,
            url=WWW_BASE + str(post["permalink"]),
            title=str(post["title"]).strip(),
            body=_body(external, flair, str(post.get("selftext") or "")),
            published_at=published,
            fetched_at=now,
        ))
    return out


# --- Atom (sem credenciais) --------------------------------------------------------------------


def _entry_time(entry: Any) -> datetime | None:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime(*st[:6], tzinfo=UTC) if st else None


def _same_post(a: str, b: str) -> bool:
    pa, pb = urlsplit(a), urlsplit(b)
    return pa.path.rstrip("/") == pb.path.rstrip("/") and _is_reddit_host(pa.hostname or "")


def parse_atom(data: bytes, source: SourceConfig, now: datetime | None = None, *,
               subreddit: str | None = None) -> list[NewsRaw]:
    """Feed ``/r/<sub>/.rss`` -> ``NewsRaw`` filtrados (sem flair: heurística). Com
    ``subreddit``, só os posts dele (feed combinado ``/r/a+b/.rss``)."""
    prefix = f"/r/{subreddit.lower()}/" if subreddit else None
    parsed = feedparser.parse(data)
    if parsed.get("bozo") and not parsed.entries:
        raise FeedError(f"feed ilegível: {parsed.get('bozo_exception')}")
    out: list[NewsRaw] = []
    for entry in parsed.entries:
        permalink, title = entry.get("link"), (entry.get("title") or "").strip()
        if not permalink or not title:
            continue
        if prefix and not urlsplit(permalink).path.lower().startswith(prefix):
            continue
        html = entry.content[0].value if entry.get("content") else entry.get("summary", "")
        tree = HTMLParser(html or "<div></div>")
        external = None
        for a in tree.css("a"):
            if a.text(strip=True) == "[link]":
                external = a.attributes.get("href")
                break
        is_self = not external or _same_post(external, permalink) or (
            _is_reddit_host(urlsplit(external).hostname or "") and "/comments/" in external)
        if is_self:
            external = None
        if not keep_post(flair=None, is_self=is_self,
                         media=bool(external and is_media(external)), source=source):
            continue
        text = html_to_text(html or "")
        text = text.split("submitted by", 1)[0].strip()
        out.append(NewsRaw(
            source_id=source.id or 0,
            url=permalink,
            title=title,
            body=_body(external, None, text),
            published_at=_entry_time(entry),
            fetched_at=now,
        ))
    return out


# --- coletor -----------------------------------------------------------------------------------


def _read_credentials() -> tuple[str, str] | None:
    try:
        cid = secrets.get_secret(CLIENT_ID_KEY)
        secret = secrets.get_secret(CLIENT_SECRET_KEY)
    except Exception as exc:  # keyring sem backend, D-Bus fora etc.
        log.info("reddit: keyring indisponível (%s); usando RSS público", exc)
        return None
    return (cid, secret) if cid and secret else None


def _retry_after(resp: httpx.Response) -> float:
    for header in ("retry-after", "x-ratelimit-reset"):
        value = resp.headers.get(header)
        if value:
            try:
                return max(0.0, float(value))
            except ValueError:
                pass
    return 2.0


class _Batch:
    __slots__ = ("subs", "task")

    def __init__(self) -> None:
        self.subs: dict[str, None] = {}  # ordem de chegada
        self.task: asyncio.Future[bytes] | None = None


class RedditCollector:
    kind: ClassVar[str] = "reddit"

    def __init__(self, config: Config | None = None, *, sleep: Sleep = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 batch_window_s: float = BATCH_WINDOW_S) -> None:
        self.config = config
        self._sleep = sleep
        self._clock = clock
        self._creds: tuple[str, str] | None = None
        self._creds_loaded = False
        self._token: tuple[str, float] | None = None  # (token, expira em clock())
        self._lock = asyncio.Lock()
        self._batch_window_s = batch_window_s
        self._batches: dict[tuple[str, int], _Batch] = {}

    async def credentials(self) -> tuple[str, str] | None:
        if not self._creds_loaded:
            self._creds = await asyncio.to_thread(_read_credentials)
            self._creds_loaded = True
        return self._creds

    async def _request(self, http: httpx.AsyncClient, method: str, url: str,
                       **kwargs: Any) -> httpx.Response:
        for attempt in range(MAX_RETRIES + 1):
            resp = await http.request(method, url, **kwargs)
            if resp.status_code != 429 or attempt == MAX_RETRIES:
                break
            wait = min(_retry_after(resp), MAX_WAIT_S)
            log.warning("reddit: 429 em %s; esperando %.1f s", url, wait)
            await self._sleep(wait)
        resp.raise_for_status()
        return resp

    async def _get_token(self, http: httpx.AsyncClient, ua: str, *, force: bool = False) -> str:
        async with self._lock:
            if self._token and not force and self._clock() < self._token[1]:
                return self._token[0]
            creds = await self.credentials()
            assert creds is not None
            resp = await self._request(http, "POST", TOKEN_URL, auth=creds,
                                       data={"grant_type": "client_credentials"},
                                       headers={"User-Agent": ua})
            data = resp.json()
            token = data.get("access_token") if isinstance(data, Mapping) else None
            if not token:
                raise RedditError(f"token OAuth não veio: {data!r}"[:200])
            ttl = float(data.get("expires_in") or 3600)
            self._token = (str(token), self._clock() + max(ttl - 60, 30))
            return self._token[0]

    async def _collect_oauth(self, sub: str, source: SourceConfig, ctx: CollectContext,
                             ua: str) -> list[NewsRaw]:
        url = f"{OAUTH_BASE}/r/{sub}/{_listing(source)}"
        params = {"limit": _limit(source), "raw_json": 1}
        token = await self._get_token(ctx.http, ua)
        for refreshed in (False, True):
            headers = {"User-Agent": ua, "Authorization": f"bearer {token}"}
            try:
                resp = await self._request(ctx.http, "GET", url, params=params, headers=headers)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401 and not refreshed:
                    token = await self._get_token(ctx.http, ua, force=True)
                    continue
                raise
            return parse_listing(resp.json(), source, ctx.now)
        raise RedditError("token OAuth recusado")  # pragma: no cover - o laço sempre retorna

    async def _fetch_feed(self, batch: _Batch, key: tuple[str, int], ctx: CollectContext,
                          ua: str) -> bytes:
        await asyncio.sleep(self._batch_window_s)
        self._batches.pop(key, None)  # quem chegar depois abre outro lote
        listing, limit = key
        subs = "+".join(batch.subs)
        path = f"/r/{subs}/.rss" if listing == "hot" else f"/r/{subs}/{listing}/.rss"
        resp = await self._request(ctx.http, "GET", WWW_BASE + path,
                                   params={"limit": min(100, limit * len(batch.subs))},
                                   headers={"User-Agent": ua})
        return resp.content

    async def _collect_rss(self, sub: str, source: SourceConfig, ctx: CollectContext,
                           ua: str) -> list[NewsRaw]:
        key = (_listing(source), _limit(source))
        batch = self._batches.get(key)
        if batch is None:
            batch = self._batches[key] = _Batch()
            batch.task = asyncio.ensure_future(self._fetch_feed(batch, key, ctx, ua))
        batch.subs[sub] = None
        assert batch.task is not None
        data = await asyncio.shield(batch.task)  # um timeout de fonte não cancela o lote
        return parse_atom(data, source, ctx.now, subreddit=sub)

    async def collect(self, source: SourceConfig, ctx: CollectContext) -> Sequence[NewsRaw]:
        sub = subreddit_of(source)
        ua = str(source.options.get("user_agent") or USER_AGENT)
        if await self.credentials():
            try:
                return await self._collect_oauth(sub, source, ctx, ua)
            except (httpx.HTTPStatusError, RedditError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status not in (400, 401, 403) and not isinstance(exc, RedditError):
                    raise
                log.warning("reddit: OAuth falhou (%s); usando RSS público", exc)
        return await self._collect_rss(sub, source, ctx, ua)


def make_collector(config: Config | None = None) -> RedditCollector:
    return RedditCollector(config)
