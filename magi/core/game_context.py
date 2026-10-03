"""Contexto de jogo: qual jogo está aberto agora (tarefa 1.21; R8.1, R14, R15.3–R15.5).

``GameWatcher`` varre ``/proc`` a cada ~5 s (só leitura, só processos do usuário) e acha o jogo
pela variável ``SteamAppId`` (≠ 0) no environ, ignorando a própria Steam e o ``steamwebhelper``.
Jogos fora da Steam entram por ``known_processes`` (nome do processo → nome do jogo). O environ
de um processo não muda, então cada pid é lido uma vez só (cache por pid); a varredura seguinte
só lista o diretório.

Nome pelo catálogo (ou pela Store), início pelo ``starttime`` do processo, gêneros/tags pela
:class:`~magi.core.steam_tags.SteamTags` (rede em segundo plano, cache em disco).

Saídas: :meth:`GameWatcher.current` (``GameInfo`` do picker), :meth:`GameWatcher.game_context`
(``GameContext`` do agente), :meth:`GameWatcher.running` (tudo) e eventos ``opened``/``closed``
via :meth:`GameWatcher.subscribe` (EventLog/HUD/sugestões futuras).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from magi.agent.prompt import GameContext
from magi.common.contracts import GameCatalog
from magi.core.music.pick import GameInfo
from magi.core.steam_tags import SteamTags

log = logging.getLogger(__name__)

__all__ = ["GameEvent", "GameWatcher", "RunningGame", "scan"]

POLL_S = 5.0
TAGS_WAIT_S = 5.0
# Steam e seus ajudantes podem herdar SteamAppId; nunca são o jogo.
IGNORE_COMM = frozenset({"steam", "steamwebhelper", "steam-runtime-c", "steam-runtime-l", "srt-bwrap"})
IGNORE_APPIDS = frozenset({0, 7, 228980})  # nenhum, cliente Steam, redistribuíveis
_KEY = b"SteamAppId="
RECLASSIFY_EVERY = 12  # varreduras (~1 min) entre releituras completas do environ


@dataclass(frozen=True, slots=True)
class RunningGame:
    name: str
    pid: int
    since: float  # epoch em que o processo do jogo começou
    appid: int | None = None  # None: jogo fora da Steam
    genres: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"steam:{self.appid}" if self.appid is not None else f"proc:{self.name}"


@dataclass(frozen=True, slots=True)
class GameEvent:
    kind: Literal["opened", "closed"]
    game: RunningGame
    at: float


Listener = Callable[[GameEvent], Any]


# ---------------------------------------------------------------------------------------------
# Varredura de /proc


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _steam_appid(environ: bytes) -> int | None:
    env = b"\0" + environ
    i = env.find(b"\0" + _KEY)
    if i < 0:
        return None
    start = i + 1 + len(_KEY)
    end = env.find(b"\0", start)
    value = env[start : end if end >= 0 else None]
    return int(value) if value.isdigit() else None


class _ProcScanner:
    """Varre ``/proc``; guarda por pid o que já leu (o environ inicial não muda)."""

    def __init__(self, root: Path, uid: int | None, known: Mapping[str, str]) -> None:
        self.root = root
        self.uid = os.getuid() if uid is None else uid
        self.known = {k.casefold(): v for k, v in known.items()}
        self._seen: dict[int, tuple[int | None, str | None]] = {}  # pid → (appid, nome não-Steam)
        self._btime: float | None = None
        self._tick = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self._scans = 0

    def _classify(self, d: Path) -> tuple[int | None, str | None]:
        try:
            if d.stat().st_uid != self.uid:
                return None, None
        except OSError:
            return None, None
        comm = (_read(d / "comm") or b"").decode(errors="replace").strip()
        if comm in IGNORE_COMM:
            return None, None
        env = _read(d / "environ")
        appid = _steam_appid(env) if env else None
        if appid is not None and appid not in IGNORE_APPIDS:
            return appid, None
        if self.known and comm.casefold() in self.known:
            return None, self.known[comm.casefold()]
        return None, None

    def started(self, pid: int) -> float | None:
        """Epoch de início do processo (``starttime`` + ``btime``)."""
        raw = _read(self.root / str(pid) / "stat")
        if self._btime is None:
            for line in (_read(self.root / "stat") or b"").splitlines():
                if line.startswith(b"btime "):
                    self._btime = float(line.split()[1])
        if not raw or self._btime is None:
            return None
        try:
            ticks = int(raw.rsplit(b")", 1)[1].split()[19])
        except (IndexError, ValueError):
            return None
        return self._btime + ticks / self._tick

    def scan(self) -> dict[str, tuple[int, int | None, str | None]]:
        """Jogos achados: chave → (pid mais antigo, appid, nome não-Steam)."""
        found: dict[str, tuple[int, int | None, str | None]] = {}
        alive: set[int] = set()
        self._scans += 1
        if self._scans % RECLASSIFY_EVERY == 0:  # um pid pode ter feito exec num jogo
            self._seen.clear()
        try:
            entries = list(os.scandir(self.root))
        except OSError:
            return found
        for e in entries:
            if not e.name.isdigit():
                continue
            pid = int(e.name)
            alive.add(pid)
            hit = self._seen.get(pid)
            if hit is None:
                hit = self._seen[pid] = self._classify(Path(e.path))
            appid, other = hit
            if appid is None and other is None:
                continue
            key = f"steam:{appid}" if appid is not None else f"proc:{other}"
            if key not in found or pid < found[key][0]:
                found[key] = (pid, appid, other)
        for pid in self._seen.keys() - alive:
            del self._seen[pid]
        return found


def scan(proc_root: Path | str = "/proc", known: Mapping[str, str] | None = None) -> list[int | str]:
    """Varredura avulsa (diagnóstico): appids e nomes não-Steam em execução."""
    out = _ProcScanner(Path(proc_root), None, known or {}).scan().values()
    return [appid if appid is not None else str(name) for _, appid, name in out]


# ---------------------------------------------------------------------------------------------
# Observador


class GameWatcher:
    """Observa o jogo aberto. ``poll()`` faz uma varredura; ``run()`` repete a cada ``interval``."""

    def __init__(
        self,
        catalog: GameCatalog | None = None,
        tags: SteamTags | None = None,
        *,
        proc_root: Path | str = "/proc",
        interval: float = POLL_S,
        uid: int | None = None,
        known_processes: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.time,
        tags_wait_s: float = TAGS_WAIT_S,
    ) -> None:
        self.catalog = catalog
        self.tags = tags
        self.interval = interval
        self.clock = clock
        self.tags_wait_s = tags_wait_s
        self._scanner = _ProcScanner(Path(proc_root), uid, known_processes or {})
        self._current: RunningGame | None = None
        self._listeners: list[Listener] = []

    # -- leitura ------------------------------------------------------------------------------

    def running(self) -> RunningGame | None:
        return self._current

    def current(self) -> GameInfo | None:
        """Jogo aberto para o picker de música (tags de usuário + gêneros da Store)."""
        g = self._current
        if g is None:
            return None
        seen: dict[str, str] = {}
        for t in (*g.tags, *g.genres):
            seen.setdefault(t.casefold(), t)
        return GameInfo(name=g.name, tags=tuple(seen.values()))

    def game_context(self) -> GameContext | None:
        """Jogo aberto para o prompt do agente (nome, gênero e minutos de sessão)."""
        g = self._current
        if g is None:
            return None
        genre = ", ".join((g.genres or g.tags)[:3]) or None
        minutes = int(max(self.clock() - g.since, 0) // 60)
        return GameContext(name=g.name, genre=genre, session_minutes=minutes)

    def subscribe(self, listener: Listener) -> None:
        """``listener(GameEvent)``, síncrono ou assíncrono; erros só vão para o log."""
        self._listeners.append(listener)

    # -- varredura ----------------------------------------------------------------------------

    def _name(self, appid: int | None, other: str | None) -> str:
        if appid is None:
            return other or "?"
        game = self.catalog.get(appid) if self.catalog is not None else None
        if game is not None:
            return game.name
        info = self.tags.get(appid) if self.tags is not None else None
        return info.name if info is not None and info.name else f"App {appid}"

    async def _with_tags(self, game: RunningGame) -> RunningGame:
        if game.appid is None or self.tags is None:
            return game
        try:
            info = await asyncio.wait_for(self.tags.fetch(game.appid), self.tags_wait_s)
        except TimeoutError:
            info = self.tags.get(game.appid)
        except Exception:
            log.exception("tags do jogo %s", game.appid)
            info = None
        if info is None:
            return game
        name = game.name if not game.name.startswith("App ") or not info.name else info.name
        return replace(game, name=name, genres=info.genres, categories=info.categories, tags=info.tags)

    async def poll(self) -> RunningGame | None:
        """Uma varredura: atualiza o jogo atual e emite ``closed``/``opened`` quando muda."""
        found = await asyncio.to_thread(self._scanner.scan)
        cur = self._current
        if cur is not None and cur.key in found:
            return cur
        if cur is not None:
            self._current = None
            log.info("jogo fechado: %s", cur.name)
            await self._emit(GameEvent("closed", cur, self.clock()))
        if not found:
            return None
        # mais de um: o que começou por último (o pid mais alto é aproximação barata)
        key, (pid, appid, other) = max(found.items(), key=lambda kv: kv[1][0])
        since = await asyncio.to_thread(self._scanner.started, pid) or self.clock()
        game = await self._with_tags(RunningGame(self._name(appid, other), pid, since, appid))
        self._current = game
        log.info("jogo aberto: %s (%s) tags=%s", game.name, key, ", ".join(game.tags[:5]) or "—")
        await self._emit(GameEvent("opened", game, self.clock()))
        return game

    async def _emit(self, event: GameEvent) -> None:
        for listener in list(self._listeners):
            try:
                result = listener(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                log.exception("ouvinte de jogo falhou (%s)", event.kind)

    async def run(self) -> None:
        while True:
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("varredura de jogo falhou")
            await asyncio.sleep(self.interval)
