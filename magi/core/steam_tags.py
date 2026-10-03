"""Gêneros e tags dos jogos da Steam, com cache persistente (R15.5, tarefa 1.21).

Fontes (só leitura, sem chave):

- Steam Store ``api/appdetails`` → ``genres`` e ``categories`` (estáveis, em inglês para casar com
  as regras do picker de música e da sugestão 5.4);
- SteamSpy ``appdetails`` → tags de usuário (as mais votadas), por melhor esforço: se falhar, fica
  só o que veio da Store.

O cache (``~/.cache/magi/steam-tags.json``) vale ``ttl_days``; falha de rede não é gravada e só é
tentada de novo depois de ``retry_s``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

__all__ = ["CACHE_FILE", "SteamAppInfo", "SteamTags", "STORE_URL", "STEAMSPY_URL"]

CACHE_FILE = "steam-tags.json"
STORE_URL = "https://store.steampowered.com/api/appdetails"
STEAMSPY_URL = "https://steamspy.com/api.php"
MAX_USER_TAGS = 12


@dataclass(frozen=True, slots=True)
class SteamAppInfo:
    appid: int
    name: str = ""
    genres: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()  # tags de usuário, mais votadas primeiro
    fetched_at: float = 0.0

    def all_tags(self) -> tuple[str, ...]:
        """Tags de usuário + gêneros da Store, sem repetição (para o picker)."""
        seen: dict[str, str] = {}
        for t in (*self.tags, *self.genres):
            seen.setdefault(t.casefold(), t)
        return tuple(seen.values())

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> SteamAppInfo:
        return cls(
            appid=int(raw["appid"]),
            name=str(raw.get("name") or ""),
            genres=tuple(map(str, raw.get("genres") or ())),
            categories=tuple(map(str, raw.get("categories") or ())),
            tags=tuple(map(str, raw.get("tags") or ())),
            fetched_at=float(raw.get("fetched_at") or 0.0),
        )


def _default_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "magi" / CACHE_FILE


@dataclass
class SteamTags:
    """Cache de :class:`SteamAppInfo` por appid. ``client``: fábrica de ``httpx.AsyncClient``
    (testes passam um com ``MockTransport``)."""

    path: Path | None = None
    client: Callable[[], httpx.AsyncClient] | None = None
    ttl_days: float = 30.0
    retry_s: float = 600.0
    clock: Callable[[], float] = time.time
    _data: dict[int, SteamAppInfo] | None = field(default=None, init=False, repr=False)
    _failed: dict[int, float] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path) if self.path is not None else _default_path()

    # -- cache ----------------------------------------------------------------

    def _load(self) -> dict[int, SteamAppInfo]:
        if self._data is None:
            data: dict[int, SteamAppInfo] = {}
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
                for item in raw.values() if isinstance(raw, dict) else ():
                    info = SteamAppInfo.from_json(item)
                    data[info.appid] = info
            except FileNotFoundError:
                pass
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.warning("cache de tags da Steam ilegível (%s): %s", self.path, exc)
            self._data = data
        return self._data

    def _save(self) -> None:
        assert self.path is not None
        with self._lock:
            payload = {str(k): asdict(v) for k, v in sorted(self._load().items())}
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(self.path.suffix + ".tmp")
                tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError as exc:
                log.warning("não deu para gravar o cache de tags (%s): %s", self.path, exc)

    def get(self, appid: int) -> SteamAppInfo | None:
        """Só o cache (sem rede), mesmo vencido."""
        return self._load().get(int(appid))

    def _fresh(self, info: SteamAppInfo | None) -> bool:
        return info is not None and self.clock() - info.fetched_at < self.ttl_days * 86400

    # -- rede -----------------------------------------------------------------

    async def fetch(self, appid: int) -> SteamAppInfo | None:
        """Cache válido ou busca na Store (+ SteamSpy). ``None`` se nunca deu certo."""
        appid = int(appid)
        cached = self.get(appid)
        if self._fresh(cached):
            return cached
        last_fail = self._failed.get(appid)
        if last_fail is not None and self.clock() - last_fail < self.retry_s:
            return cached
        factory = self.client or (lambda: httpx.AsyncClient(timeout=10.0, follow_redirects=True))
        try:
            async with factory() as c:
                info = await self._store(c, appid)
                if info is None:
                    raise ValueError("appdetails sem dados")
                tags = await self._steamspy(c, appid)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.info("tags da Steam para %s indisponíveis: %s", appid, exc)
            self._failed[appid] = self.clock()
            return cached
        info = SteamAppInfo(
            appid=appid,
            name=info.name,
            genres=info.genres,
            categories=info.categories,
            tags=tags,
            fetched_at=self.clock(),
        )
        self._failed.pop(appid, None)
        self._load()[appid] = info
        self._save()
        return info

    @staticmethod
    async def _store(c: httpx.AsyncClient, appid: int) -> SteamAppInfo | None:
        r = await c.get(STORE_URL, params={"appids": str(appid), "l": "english"})
        r.raise_for_status()
        entry = (r.json() or {}).get(str(appid)) or {}
        if not entry.get("success"):
            return None
        data = entry.get("data") or {}
        return SteamAppInfo(
            appid=appid,
            name=str(data.get("name") or ""),
            genres=tuple(str(g["description"]) for g in data.get("genres") or () if g.get("description")),
            categories=tuple(
                str(g["description"]) for g in data.get("categories") or () if g.get("description")
            ),
        )

    @staticmethod
    async def _steamspy(c: httpx.AsyncClient, appid: int) -> tuple[str, ...]:
        try:
            r = await c.get(STEAMSPY_URL, params={"request": "appdetails", "appid": str(appid)})
            r.raise_for_status()
            tags = (r.json() or {}).get("tags") or {}
        except (httpx.HTTPError, ValueError) as exc:
            log.info("SteamSpy sem tags para %s: %s", appid, exc)
            return ()
        if not isinstance(tags, dict):  # app sem tags vem como lista vazia
            return ()
        ranked = sorted(tags.items(), key=lambda kv: -int(kv[1]) if str(kv[1]).isdigit() else 0)
        return tuple(str(k) for k, _ in ranked[:MAX_USER_TAGS])
