"""Progresso do usuário nas obras, para o anti-spoiler (tarefa 6.8, R19.1).

Grava na tabela ``progress`` (via ``NewsRepo.set_progress``):

- **AniList** (``kind="episode"``): para cada obra da lista do usuário (qualquer status), o
  último episódio visto. Obras COMPLETED/REPEATING contam como vistas até o fim (``episodes``
  da obra, se a API souber). Obras DROPPED viram ``franchise_prefs.dropped = true`` (R19.8);
  a volta de DROPPED para outro status **não** desmarca, porque o usuário também larga obras
  por voz e as duas origens não se distinguem na tabela. Nome da obra: o mesmo do coletor
  (:func:`~magi.news.collect.anilist.media_title`, inglês ou romaji). Reaproveita o cliente
  GraphQL do coletor (limite de taxa, espera em 429 e prazo).
- **Steam** (``kind="hours"``): horas jogadas por jogo instalado, lidas só do disco: campo
  ``Playtime`` (minutos) de ``Software/Valve/Steam/apps/<appid>`` em
  ``<steam>/userdata/<id>/config/localconfig.vdf`` (o mais recente, se houver várias contas).
  O arquivo só é lido. Jogo instalado sem registro conta como 0 h; sem ``localconfig.vdf``, a
  Steam fica de fora (sem dado não é 0 h). Conquistas (``kind="achievements"``) ficam de fora:
  a Web API da Steam pede chave e o cache local (``appcache/stats/*.bin``) é binário e sem
  formato público.

Cada sincronização regrava todas as linhas com ``updated_at`` = agora; a Ayanami (``magi-ayanami``) usa o
maior ``updated_at`` para rodar no máximo uma vez a cada ``progress_interval_h`` (padrão 6 h).
Opções em ``[news]``: ``progress`` (padrão ``true``), ``progress_interval_h``, ``steam_root``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from magi.common.contracts import FranchisePref, NewsRepo, Progress
from magi.core.catalog import default_steam_root, parse_vdf, scan_games
from magi.news.collect.anilist import (
    DEFAULT_RATE_PER_MIN,
    LIST_PER_PAGE,
    AniListError,
    _Client,
    _Deadline,
    media_title,
)
from magi.news.sources import SourceConfig

log = logging.getLogger(__name__)

ANILIST_URL = "https://graphql.anilist.co"
DEFAULT_INTERVAL = timedelta(hours=6)
ANILIST_DEADLINE_S = 30.0
ANILIST_MAX_PAGES = 20
KIND_EPISODE, KIND_HOURS = "episode", "hours"
FINISHED = ("COMPLETED", "REPEATING")

PROGRESS_QUERY = """
query ($user: String, $page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage }
    mediaList(userName: $user, type: ANIME) {
      status progress
      media { id episodes title { romaji english } }
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class AnimeEntry:
    franchise: str
    status: str  # CURRENT | PLANNING | COMPLETED | DROPPED | PAUSED | REPEATING
    episode: int


@dataclass(slots=True)
class ProgressReport:
    anime: int = 0
    games: int = 0
    dropped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s = f"progresso: {self.anime} animes, {self.games} jogos"
        if self.dropped:
            s += f", {len(self.dropped)} largados"
        return s + (f", erros: {'; '.join(self.errors)}" if self.errors else "")


# --- AniList ---------------------------------------------------------------------------------


def anime_entry(row: Mapping[str, Any]) -> AnimeEntry | None:
    media = row.get("media") or {}
    if not media:
        return None
    status = str(row.get("status") or "")
    episode = int(row.get("progress") or 0)
    if status in FINISHED:
        episode = max(episode, int(media.get("episodes") or 0))
    return AnimeEntry(franchise=media_title(media), status=status, episode=episode)


async def fetch_anilist(
    http: httpx.AsyncClient,
    user: str,
    *,
    url: str = ANILIST_URL,
    rate_per_min: int = DEFAULT_RATE_PER_MIN,
    deadline_s: float = ANILIST_DEADLINE_S,
    max_pages: int = ANILIST_MAX_PAGES,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[AnimeEntry]:
    """Lista inteira de anime do usuário. Lista vazia é normal; usuário inexistente ou lista
    privada levanta :class:`AniListError`; prazo esgotado levanta ``TimeoutError``."""
    client = _Client(http, url, rate_per_min, clock() + deadline_s, sleep, clock)
    out: list[AnimeEntry] = []
    try:
        for page in range(1, max_pages + 1):
            data = await client.query(PROGRESS_QUERY,
                                      {"user": user, "page": page, "perPage": LIST_PER_PAGE})
            pg = data.get("Page") or {}
            out.extend(e for e in map(anime_entry, pg.get("mediaList") or []) if e)
            if not (pg.get("pageInfo") or {}).get("hasNextPage"):
                break
    except _Deadline:
        raise TimeoutError(f"anilist: prazo de {deadline_s:.0f} s esgotado") from None
    return out


# --- Steam -----------------------------------------------------------------------------------


def _ci(d: Any, *keys: str) -> Any:
    """Caminho no VDF sem diferenciar maiúsculas; ``None`` se faltar algo."""
    for key in keys:
        if not isinstance(d, Mapping):
            return None
        low = key.lower()
        d = next((v for k, v in d.items() if k.lower() == low), None)
    return d


def find_localconfig(steam_root: Path) -> Path | None:
    """``localconfig.vdf`` modificado por último (a conta em uso)."""
    try:
        found = [(p.stat().st_mtime, p) for p in (steam_root / "userdata").glob("*/config/localconfig.vdf")]
    except OSError:
        return None
    return max(found)[1] if found else None


def read_playtime(path: Path) -> dict[int, int]:
    """Minutos jogados por appid. Arquivo ilegível ou malformado devolve o que deu para ler."""
    try:
        data = parse_vdf(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        log.warning("steam: não li %s (%s)", path, exc)
        return {}
    apps = _ci(data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps")
    out: dict[int, int] = {}
    for appid, entry in (apps or {}).items():
        minutes = _ci(entry, "Playtime")
        if appid.isdigit() and isinstance(minutes, str) and minutes.strip().isdigit():
            out[int(appid)] = int(minutes)
    return out


def steam_progress(steam_root: Path, now: datetime) -> list[Progress]:
    """Horas por jogo instalado; vazio se não houver ``localconfig.vdf``."""
    path = find_localconfig(steam_root)
    if path is None:
        log.info("steam: sem localconfig.vdf em %s", steam_root)
        return []
    minutes = read_playtime(path)
    return [Progress(franchise=g.name, kind=KIND_HOURS,
                     value=round(minutes.get(g.appid, 0) / 60, 2), updated_at=now)
            for g in scan_games(steam_root)]


# --- sincronização ---------------------------------------------------------------------------


async def update_progress(
    repo: NewsRepo,
    http: httpx.AsyncClient | None,
    now: datetime,
    *,
    anilist_user: str | None = None,
    anilist_url: str = ANILIST_URL,
    steam_root: Path | None = None,
) -> ProgressReport:
    """Atualiza AniList (se houver usuário) e Steam. Erro numa fonte não impede a outra."""
    report = ProgressReport()
    if anilist_user and http is not None:
        try:
            entries = await fetch_anilist(http, anilist_user, url=anilist_url)
        except (AniListError, httpx.HTTPError, TimeoutError) as exc:
            log.warning("progresso anilist: %s", exc)
            report.errors.append(f"anilist: {exc}")
        else:
            prefs = {p.franchise: p for p in await repo.franchise_prefs()}
            for e in entries:
                await repo.set_progress(Progress(e.franchise, KIND_EPISODE, float(e.episode), now))
                report.anime += 1
                pref = prefs.get(e.franchise) or FranchisePref(e.franchise)
                if e.status == "DROPPED" and not pref.dropped:
                    await repo.set_franchise_pref(replace(pref, dropped=True))
                    report.dropped.append(e.franchise)
    try:
        games = steam_progress(steam_root or default_steam_root(), now)
    except OSError as exc:
        log.warning("progresso steam: %s", exc)
        report.errors.append(f"steam: {exc}")
        games = []
    for p in games:
        await repo.set_progress(p)
    report.games = len(games)
    return report


def anilist_source(sources: Sequence[SourceConfig]) -> SourceConfig | None:
    """Primeira fonte AniList ativa com ``username``."""
    return next((s for s in sources if s.kind == "anilist" and s.enabled
                 and str(s.options.get("username") or "").strip()), None)


async def update_if_due(
    repo: NewsRepo,
    http: httpx.AsyncClient,
    sources: Sequence[SourceConfig],
    settings: Mapping[str, Any],
    now: datetime,
) -> ProgressReport | None:
    """Passo de progresso da Ayanami (``magi-ayanami``): ``None`` se desligado ou ainda no intervalo."""
    if not settings.get("progress", True):
        return None
    hours = settings.get("progress_interval_h")
    interval = timedelta(hours=float(hours)) if hours is not None else DEFAULT_INTERVAL
    last_fn = getattr(repo, "progress_updated_at", None)
    last = await last_fn() if last_fn else None
    if last is not None and now - last < interval:
        log.debug("progresso: última atualização %s, dentro do intervalo", last)
        return None
    src = anilist_source(sources)
    root = settings.get("steam_root")
    return await update_progress(
        repo, http, now,
        anilist_user=str(src.options["username"]).strip() if src else None,
        anilist_url=src.url if src else ANILIST_URL,
        steam_root=Path(root).expanduser() if root else None,
    )
