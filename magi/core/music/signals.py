"""Sinais de música (tarefa 2.4, R8.3-R8.5, §7 ``music_signals``).

Observa o MPRIS do Spotify e grava sinais de gosto:

- faixa **escolhida pela Magui** pulada com menos de 30 s ouvidos → ``SKIPPED`` (-1, R8.3);
- faixa ouvida até o fim (qualquer uma) → ``FINISHED`` (+1, R8.4);
- "essa é boa" (``music.like``) → ``LIKED`` (+2) na faixa atual (R8.5);
- "nunca mais toca isso" (``music.never``) → ``NEVER`` (-99) e pula; a faixa entra em
  ``banned_tracks()`` e a escolha (2.5) nunca pode tocá-la de novo (R8.5).

Sem polling pesado: assina ``PropertiesChanged`` do player (``AddMatch`` no barramento de sessão,
só leitura) e, a cada sinal, lê o estado uma vez (``GetAll``). Uma leitura de segurança a cada
``SAFETY_POLL_S`` cobre sinais perdidos e o Spotify fechando. O tempo ouvido é contado pelo relógio
enquanto o status é ``Playing`` (somado à posição em que a faixa foi vista pela primeira vez).

Faixas escolhidas pela Magui: quem toca algo chama :meth:`MusicSignals.mark_picked` com a URI
(``play_query`` da 2.2 via ``on_play``; "coloca uma boa" da 2.5 deve fazer o mesmo). URI de faixa
marca só aquela faixa; álbum/playlist/artista marca a próxima faixa que começar em até
``PICK_WINDOW_S`` e as seguintes enquanto cada uma terminar naturalmente. O contexto de cada sinal
leva ``hour``, ``picked``, ``request`` e ``title`` (mais o que ``context`` devolver, ex.: jogo).

API::

    sig = MusicSignals(mpris, repo)        # repo: MusicSignalsRepo (None = em memória)
    sig.mark_picked("spotify:track:…", request="coloca uma boa")
    await sig.like() / await sig.never()   # faixa atual; devolve o PlayerState ou None
    task = asyncio.create_task(sig.run())  # observa o MPRIS até ser cancelada
    handlers(sig)                          # music.like e music.never para o Registry

O peso efetivo do gosto (base importada + sinais) é calculado na view ``taste_effective``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from dbus_next import Message, MessageType
from dbus_next.aio import MessageBus

from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    ActionResult,
    Expression,
    IntentId,
    MusicSignal,
    MusicSignalsRepo,
    MusicSignalValue,
)
from magi.core.actions.spotify_mpris import (
    OBJECT_PATH,
    PLAYER_IFACE,
    PROPS_IFACE,
    MprisError,
    PlayerState,
    SpotifyMpris,
    SpotifyNotRunning,
    _session_bus,
)

log = logging.getLogger(__name__)

SKIP_S = 30.0  # R8.3
FINISH_TAIL_S = 10.0  # faltando até 10 s conta como ouvida inteira
FINISH_FRACTION = 0.9
PICK_WINDOW_S = 20.0  # escolha de álbum/playlist: a faixa precisa começar nesse prazo
SAFETY_POLL_S = 60.0
DEBOUNCE_S = 0.3  # o Spotify manda vários PropertiesChanged juntos na troca de faixa

MATCH_RULE = (
    f"type='signal',interface='{PROPS_IFACE}',member='PropertiesChanged',"
    f"path='{OBJECT_PATH}',arg0='{PLAYER_IFACE}'"
)

SAY_LIKED = "Anotado, essa é das boas."
SAY_NEVER = "Beleza, essa não volta."
SAY_NOTHING = "Não tem nada tocando agora."
SAY_FAILED = "Não consegui ver o que está tocando."


def track_uri(state: PlayerState | None) -> str:
    """URI ``spotify:track:<id>`` da faixa (de ``mpris:trackid`` ou ``xesam:url``); ``""`` sem faixa."""
    if state is None:
        return ""
    tid = state.track_id
    if tid.startswith("spotify:"):
        return tid
    if tid.startswith("/com/spotify/track/"):
        return "spotify:track:" + tid.rsplit("/", 1)[-1]
    if "open.spotify.com/track/" in state.url:
        return "spotify:track:" + state.url.rsplit("/", 1)[-1].split("?", 1)[0]
    return ""


class MemoryMusicSignalsRepo:
    """``MusicSignalsRepo`` em memória (sem banco; também usado nos testes)."""

    def __init__(self) -> None:
        self.rows: list[MusicSignal] = []

    async def add(self, signal: MusicSignal) -> None:
        self.rows.append(signal)

    async def banned_tracks(self) -> set[str]:
        return {s.track_uri for s in self.rows if s.signal == MusicSignalValue.NEVER}

    async def recent(self, limit: int = 100) -> list[MusicSignal]:
        return sorted(self.rows, key=lambda s: s.at, reverse=True)[:limit]


@dataclass
class _Track:
    uri: str
    artist: str
    title: str
    length_s: float
    start_pos: float
    picked: bool
    inherit: bool  # escolha de álbum/playlist: a próxima faixa natural também é da Magui
    request: str = ""
    played_s: float = 0.0
    playing_since: float | None = None
    never: bool = False

    def heard(self) -> float:
        return self.start_pos + self.played_s

    def finished(self) -> bool:
        if self.length_s <= 0:
            return False
        h = self.heard()
        return h >= self.length_s - FINISH_TAIL_S or h >= self.length_s * FINISH_FRACTION


@dataclass
class _Pick:
    uri: str
    at: float
    request: str

    @property
    def is_track(self) -> bool:
        return self.uri.startswith("spotify:track:")


class MusicSignals:
    """Acompanha a faixa atual e grava sinais. ``clock``: segundos monotônicos; ``now``: data do
    sinal; ``context``: extras do contexto (ex.: jogo aberto). Todos injetáveis para testes."""

    def __init__(
        self,
        mpris: SpotifyMpris,
        repo: MusicSignalsRepo | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        context: Callable[[], Mapping[str, Any]] | None = None,
        bus_factory: Callable[[], Awaitable[MessageBus]] = _session_bus,
    ) -> None:
        self.mpris = mpris
        self.repo: MusicSignalsRepo = repo if repo is not None else MemoryMusicSignalsRepo()
        self._clock = clock
        self._now = now
        self._context = context
        self._bus_factory = bus_factory
        self._cur: _Track | None = None
        self._pick: _Pick | None = None
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()

    # -- escolhas da Magui --------------------------------------------------------------------

    def mark_picked(self, uri: str, request: str = "") -> None:
        """A Magui acabou de mandar tocar ``uri`` (faixa, álbum, playlist ou artista)."""
        self._pick = _Pick(uri, self._clock(), request)
        self._wake.set()

    def _consume_pick(self, uri: str, now: float) -> _Pick | None:
        p = self._pick
        if p is None:
            return None
        if now - p.at > PICK_WINDOW_S:
            self._pick = None
            return None
        if p.is_track and p.uri != uri:
            return None
        self._pick = None
        return p

    # -- observação ---------------------------------------------------------------------------

    @property
    def current(self) -> str:
        return self._cur.uri if self._cur else ""

    async def observe(self, state: PlayerState | None) -> MusicSignal | None:
        """Processa um estado lido do MPRIS (``None`` = Spotify fechado). Devolve o sinal gravado
        na troca de faixa, se houver."""
        async with self._lock:
            return await self._observe(state)

    async def _observe(self, state: PlayerState | None) -> MusicSignal | None:
        now = self._clock()
        uri = track_uri(state)
        cur = self._cur
        recorded = None
        prev_natural = False
        if cur is not None:
            self._accumulate(cur, now)
            if uri == cur.uri:
                assert state is not None
                cur.playing_since = now if state.playing else None
                return None
            recorded = await self._judge(cur, changed=bool(uri))
            prev_natural = cur.finished()
            self._cur = None
        if not uri or state is None:
            return recorded
        pick = self._consume_pick(uri, now)
        picked = pick is not None
        inherit = picked and not pick.is_track
        request = pick.request if pick else ""
        if not picked and cur is not None and cur.picked and cur.inherit and prev_natural:
            picked, inherit, request = True, True, cur.request
        self._cur = _Track(
            uri=uri,
            artist=state.artists[0] if state.artists else "",
            title=state.title,
            length_s=state.length_s,
            start_pos=state.position_s,
            picked=picked,
            inherit=inherit,
            request=request,
            playing_since=now if state.playing else None,
        )
        return recorded

    @staticmethod
    def _accumulate(t: _Track, now: float) -> None:
        if t.playing_since is not None:
            t.played_s += max(0.0, now - t.playing_since)
            t.playing_since = now

    async def _judge(self, t: _Track, *, changed: bool) -> MusicSignal | None:
        if t.never:
            return None
        if t.finished():
            return await self._record(t, MusicSignalValue.FINISHED)  # R8.4: qualquer faixa
        if changed and t.picked and t.heard() < SKIP_S:
            return await self._record(t, MusicSignalValue.SKIPPED)  # R8.3: só escolhas da Magui
        return None

    async def _record(self, t: _Track, value: MusicSignalValue) -> MusicSignal:
        at = self._now()
        ctx: dict[str, Any] = {"hour": at.astimezone().hour, "picked": t.picked, "title": t.title}
        if t.request:
            ctx["request"] = t.request
        if self._context is not None:
            try:
                ctx.update(self._context())
            except Exception:
                log.exception("sinais de música: contexto falhou")
        sig = MusicSignal(t.uri, t.artist, value, at, ctx)
        try:
            await self.repo.add(sig)
        except Exception:
            log.exception("sinais de música: gravação falhou")
        log.info("música: %s %s (%s)", value.name, t.title or t.uri, t.artist)
        return sig

    # -- sinais explícitos (R8.5) ---------------------------------------------------------------

    async def _sync(self) -> _Track | None:
        try:
            state = await self.mpris.state()
        except SpotifyNotRunning:
            state = None
        await self._observe(state)
        return self._cur

    async def like(self) -> MusicSignal | None:
        """"Essa é boa": ``LIKED`` na faixa atual. ``None`` se nada toca."""
        async with self._lock:
            t = await self._sync()
            return None if t is None else await self._record(t, MusicSignalValue.LIKED)

    async def never(self) -> MusicSignal | None:
        """"Nunca mais": ``NEVER`` na faixa atual e pula para a próxima."""
        async with self._lock:
            t = await self._sync()
            if t is None:
                return None
            sig = await self._record(t, MusicSignalValue.NEVER)
            t.never = True
        try:
            await self.mpris.next()
        except (MprisError, OSError) as e:  # o bloqueio já foi gravado
            log.warning("sinais de música: não pulei a faixa bloqueada: %r", e)
        return sig

    async def banned(self) -> set[str]:
        return await self.repo.banned_tracks()

    # -- laço do MPRIS ------------------------------------------------------------------------

    def _on_message(self, msg: Message) -> None:
        if (
            msg.message_type == MessageType.SIGNAL
            and msg.member == "PropertiesChanged"
            and msg.path == OBJECT_PATH
            and msg.body
            and msg.body[0] == PLAYER_IFACE
        ):
            self._wake.set()

    async def _poll_once(self) -> None:
        try:
            state = await self.mpris.state()
        except SpotifyNotRunning:
            state = None
        except (MprisError, OSError) as e:
            log.debug("sinais de música: leitura falhou: %r", e)
            return
        await self.observe(state)

    async def run(self, *, safety_s: float = SAFETY_POLL_S, debounce_s: float = DEBOUNCE_S) -> None:
        """Observa até ser cancelada. Nunca levanta por falha de D-Bus (tenta de novo)."""
        bus: MessageBus | None = None
        try:
            while True:
                if bus is None or not bus.connected:
                    try:
                        bus = await self._bus_factory()
                        bus.add_message_handler(self._on_message)
                        await bus.call(
                            Message(
                                destination="org.freedesktop.DBus",
                                path="/org/freedesktop/DBus",
                                interface="org.freedesktop.DBus",
                                member="AddMatch",
                                signature="s",
                                body=[MATCH_RULE],
                            )
                        )
                    except Exception as e:
                        log.warning("sinais de música: sem D-Bus (%r); tento de novo", e)
                        bus = None
                        await asyncio.sleep(safety_s)
                        continue
                await self._poll_once()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), safety_s)
                self._wake.clear()
                await asyncio.sleep(debounce_s)
        finally:
            if bus is not None and bus.connected:
                bus.disconnect()


class MusicSignalsHandler:
    """``ActionHandler`` de ``music.like`` e ``music.never`` (R8.5)."""

    intents = frozenset({IntentId.MUSIC_LIKE, IntentId.MUSIC_NEVER})

    def __init__(self, signals: MusicSignals) -> None:
        self.signals = signals

    async def run(self, req: ActionRequest) -> ActionResult:
        try:
            if req.intent.id == IntentId.MUSIC_LIKE:
                sig = await self.signals.like()
                say = SAY_LIKED
            else:
                sig = await self.signals.never()
                say = SAY_NEVER
        except (MprisError, OSError) as e:
            log.warning("sinal de música falhou: %r", e)
            return ActionResult(ok=False, speech=SAY_FAILED, expression=Expression.CONFUSED)
        if sig is None:
            return ActionResult(ok=False, speech=SAY_NOTHING, expression=Expression.CONFUSED)
        return ActionResult(ok=True, speech=say)


def handlers(signals: MusicSignals) -> list[ActionHandler]:
    return [MusicSignalsHandler(signals)]
