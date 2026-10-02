"""Controle local do Spotify pelo MPRIS (R7.1, R7.3).

API para outras tarefas (2.2 Web API, 2.4 sinais de música)::

    mpris = SpotifyMpris()                 # barramento de sessão, conecta sob demanda
    await mpris.is_running()               # Spotify está no barramento? (só leitura)
    await mpris.ensure_running()           # abre o flatpak e espera o MPRIS (até 15 s)
    await mpris.play() / pause() / toggle() / next() / previous()
    await mpris.set_volume(0.5)            # 0.0..1.0; get_volume() lê
    await mpris.open_uri("spotify:track:…")  # OpenUri: toca uma URI do Spotify
    st = await mpris.state()               # PlayerState: status, faixa, posição, volume
    await mpris.position()                 # posição atual em segundos

Os comandos (play, pause, ..., open_uri) abrem o Spotify se ele estiver fechado e repetem o
pedido quando o nome ``org.mpris.MediaPlayer2.spotify`` aparecer (R7.3). As leituras
(``state``, ``position``, ``get_volume``) não abrem nada: com o Spotify fechado levantam
``SpotifyNotRunning``. Erros de D-Bus viram ``MprisError``.

Não há assinatura de sinais: quem precisa acompanhar troca de faixa (2.4) consulta
``state()`` periodicamente e compara ``PlayerState.track_id``.

``handlers(mpris=None, play_query=None)`` registra os intents ``music.open``, ``music.play``,
``music.pause``, ``music.next``, ``music.previous`` e ``music.volume``. ``music.play`` com
slot ``query`` (tocar por nome, R7.2) é delegado a ``play_query`` (fornecido pela 2.2); sem
ele, a ação responde que ainda não sabe.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from dbus_next import Message, MessageType, Variant
from dbus_next.aio import MessageBus

from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    ActionResult,
    Expression,
    IntentId,
    SlotName,
)

log = logging.getLogger(__name__)

BUS_NAME = "org.mpris.MediaPlayer2.spotify"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
FLATPAK_CMD = ("flatpak", "run", "com.spotify.Client")
WAIT_S = 15.0  # R7.3
POLL_S = 0.25
_NOT_RUNNING_ERRORS = frozenset(
    {"org.freedesktop.DBus.Error.ServiceUnknown", "org.freedesktop.DBus.Error.NameHasNoOwner"}
)

SAY_OPENING = "Abrindo o Spotify."
SAY_ALREADY_OPEN = "O Spotify já está aberto."
SAY_NOT_STARTED = "O Spotify não abriu a tempo."
SAY_DBUS_FAILED = "Não consegui falar com o Spotify."
SAY_NO_QUERY = "Ainda não sei tocar música pelo nome."
SAY_BAD_VOLUME = "Não entendi o volume."


class MprisError(RuntimeError):
    """Falha numa chamada D-Bus ao Spotify (``args[0]`` = nome do erro D-Bus)."""


class SpotifyNotRunning(MprisError):
    """O Spotify não está no barramento (ou não apareceu em ``wait_s``)."""


@dataclass(frozen=True, slots=True)
class PlayerState:
    """Estado do player lido do MPRIS. Tempos em segundos; ``volume`` 0.0..1.0.

    ``status``: ``"Playing"``, ``"Paused"`` ou ``"Stopped"``. ``track_id``: ``mpris:trackid``
    (no Spotify, ``/com/spotify/track/<id>``); ``url``: ``xesam:url`` (link da faixa).
    """

    status: str
    track_id: str = ""
    title: str = ""
    artists: tuple[str, ...] = ()
    album: str = ""
    url: str = ""
    length_s: float = 0.0
    position_s: float = 0.0
    volume: float | None = None

    @property
    def playing(self) -> bool:
        return self.status == "Playing"


def launch_flatpak() -> None:
    """Abre o Spotify (flatpak) desacoplado do núcleo: nova sessão, sem herdar stdio."""
    subprocess.Popen(
        FLATPAK_CMD,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


async def _session_bus() -> MessageBus:
    return await MessageBus().connect()


def _unwrap(v: Any) -> Any:
    return v.value if isinstance(v, Variant) else v


def _parse_metadata(md: Mapping[str, Any]) -> dict[str, Any]:
    md = {k: _unwrap(v) for k, v in md.items()}
    artists = md.get("xesam:artist") or ()
    if isinstance(artists, str):
        artists = (artists,)
    return {
        "track_id": str(md.get("mpris:trackid") or ""),
        "title": str(md.get("xesam:title") or ""),
        "artists": tuple(str(a) for a in artists),
        "album": str(md.get("xesam:album") or ""),
        "url": str(md.get("xesam:url") or ""),
        "length_s": int(md.get("mpris:length") or 0) / 1e6,
    }


class SpotifyMpris:
    """Cliente MPRIS do Spotify com ``dbus-next`` (async).

    ``bus_factory``: conecta ao barramento (padrão: sessão). ``launcher``: abre o Spotify
    (padrão: ``launch_flatpak``). Ambos injetáveis para testes (barramento privado, runner
    falso). ``wait_s``: quanto esperar o MPRIS aparecer depois de abrir (R7.3).
    """

    def __init__(
        self,
        bus_factory: Callable[[], Awaitable[MessageBus]] = _session_bus,
        launcher: Callable[[], None] = launch_flatpak,
        wait_s: float = WAIT_S,
        poll_s: float = POLL_S,
    ) -> None:
        self._bus_factory = bus_factory
        self._launcher = launcher
        self.wait_s = wait_s
        self.poll_s = poll_s
        self._bus: MessageBus | None = None
        self._lock = asyncio.Lock()

    # -- barramento ---------------------------------------------------------------------------

    async def _get_bus(self) -> MessageBus:
        async with self._lock:
            if self._bus is None or not self._bus.connected:
                self._bus = await self._bus_factory()
            return self._bus

    async def close(self) -> None:
        if self._bus is not None and self._bus.connected:
            self._bus.disconnect()
        self._bus = None

    async def _call(
        self,
        member: str,
        *,
        dest: str = BUS_NAME,
        path: str = OBJECT_PATH,
        iface: str = PLAYER_IFACE,
        signature: str = "",
        body: list[Any] | None = None,
    ) -> list[Any]:
        bus = await self._get_bus()
        reply = await bus.call(
            Message(
                destination=dest,
                path=path,
                interface=iface,
                member=member,
                signature=signature,
                body=body or [],
            )
        )
        if reply is None:
            return []
        if reply.message_type == MessageType.ERROR:
            err = reply.error_name or "unknown"
            if err in _NOT_RUNNING_ERRORS:
                raise SpotifyNotRunning(err)
            detail = reply.body[0] if reply.body else ""
            raise MprisError(err, detail)
        return reply.body

    async def _get_prop(self, name: str) -> Any:
        body = await self._call("Get", iface=PROPS_IFACE, signature="ss", body=[PLAYER_IFACE, name])
        return _unwrap(body[0])

    # -- abrir / esperar ----------------------------------------------------------------------

    async def is_running(self) -> bool:
        """``True`` se o nome MPRIS do Spotify tem dono no barramento (só leitura)."""
        body = await self._call(
            "NameHasOwner",
            dest="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            iface="org.freedesktop.DBus",
            signature="s",
            body=[BUS_NAME],
        )
        return bool(body and body[0])

    async def wait_running(self, timeout_s: float | None = None) -> bool:
        """Espera o nome MPRIS aparecer por até ``timeout_s`` (padrão ``wait_s``)."""
        deadline = time.monotonic() + (self.wait_s if timeout_s is None else timeout_s)
        while True:
            if await self.is_running():
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(self.poll_s)

    async def ensure_running(self) -> bool:
        """Abre o Spotify se preciso e espera o MPRIS. ``False`` se não apareceu a tempo."""
        if await self.is_running():
            return True
        log.info("Spotify fechado: abrindo %s", " ".join(FLATPAK_CMD))
        self._launcher()
        return await self.wait_running()

    # -- comandos (abrem o Spotify se preciso, R7.3) ------------------------------------------

    async def _command(
        self, member: str, signature: str = "", body: list[Any] | None = None, iface: str = PLAYER_IFACE
    ) -> None:
        if not await self.ensure_running():
            raise SpotifyNotRunning("timeout")
        try:
            await self._call(member, iface=iface, signature=signature, body=body)
        except SpotifyNotRunning:
            # Fechou entre a checagem e a chamada: abre de novo e repete uma vez.
            if not await self.ensure_running():
                raise
            await self._call(member, iface=iface, signature=signature, body=body)

    async def play(self) -> None:
        await self._command("Play")

    async def pause(self) -> None:
        await self._command("Pause")

    async def toggle(self) -> None:
        await self._command("PlayPause")

    async def next(self) -> None:
        await self._command("Next")

    async def previous(self) -> None:
        await self._command("Previous")

    async def open_uri(self, uri: str) -> None:
        """Toca uma URI do Spotify (``spotify:track:…``, ``spotify:playlist:…``) pelo OpenUri."""
        await self._command("OpenUri", "s", [uri])

    async def set_volume(self, level: float) -> float:
        """Volume do player (0.0..1.0, limitado). Devolve o valor aplicado."""
        level = min(1.0, max(0.0, float(level)))
        await self._command("Set", "ssv", [PLAYER_IFACE, "Volume", Variant("d", level)], PROPS_IFACE)
        return level

    # -- leituras (não abrem o Spotify) -------------------------------------------------------

    async def get_volume(self) -> float:
        return float(await self._get_prop("Volume"))

    async def position(self) -> float:
        """Posição da faixa atual em segundos."""
        return int(await self._get_prop("Position")) / 1e6

    async def state(self) -> PlayerState:
        """Lê ``PlaybackStatus``, ``Metadata``, ``Position`` e ``Volume`` de uma vez."""
        body = await self._call("GetAll", iface=PROPS_IFACE, signature="s", body=[PLAYER_IFACE])
        props = {k: _unwrap(v) for k, v in (body[0] if body else {}).items()}
        volume = props.get("Volume")
        return PlayerState(
            status=str(props.get("PlaybackStatus") or "Stopped"),
            position_s=int(props.get("Position") or 0) / 1e6,
            volume=None if volume is None else float(volume),
            **_parse_metadata(props.get("Metadata") or {}),
        )


def parse_volume(raw: str, current: float | None) -> float | None:
    """Slot ``volume`` (``"0".."100"`` ou ``"+10"``/``"-10"``) → nível 0.0..1.0.

    Relativo precisa de ``current``. ``None`` se não der para interpretar.
    """
    raw = raw.strip().rstrip("%")
    try:
        n = float(raw)
    except ValueError:
        return None
    if raw[:1] in "+-":
        if current is None:
            return None
        return min(1.0, max(0.0, current + n / 100))
    return min(1.0, max(0.0, n / 100))


PlayQuery = Callable[[ActionRequest, str], Awaitable[ActionResult]]


class SpotifyHandler:
    """``ActionHandler`` dos comandos locais do Spotify (R7.1, R7.3)."""

    intents = frozenset(
        {
            IntentId.MUSIC_OPEN,
            IntentId.MUSIC_PLAY,
            IntentId.MUSIC_PAUSE,
            IntentId.MUSIC_NEXT,
            IntentId.MUSIC_PREVIOUS,
            IntentId.MUSIC_VOLUME,
        }
    )

    def __init__(self, mpris: SpotifyMpris, play_query: PlayQuery | None = None) -> None:
        self.mpris = mpris
        self.play_query = play_query

    async def run(self, req: ActionRequest) -> ActionResult:
        try:
            return await self._run(req)
        except SpotifyNotRunning:
            return ActionResult(ok=False, speech=SAY_NOT_STARTED, expression=Expression.CONFUSED)
        except (MprisError, OSError) as e:
            log.warning("Spotify MPRIS falhou: %r", e)
            return ActionResult(ok=False, speech=SAY_DBUS_FAILED, expression=Expression.CONFUSED)

    async def _run(self, req: ActionRequest) -> ActionResult:
        iid = req.intent.id
        m = self.mpris
        if iid == IntentId.MUSIC_OPEN:
            if await m.is_running():
                return ActionResult(ok=True, speech=SAY_ALREADY_OPEN)
            if not await m.ensure_running():
                raise SpotifyNotRunning("timeout")
            return ActionResult(ok=True, speech=SAY_OPENING)
        if iid == IntentId.MUSIC_PLAY:
            q = req.intent.slot(SlotName.QUERY)
            if q is not None and q.value.strip():
                if self.play_query is None:
                    return ActionResult(ok=False, speech=SAY_NO_QUERY, expression=Expression.CONFUSED)
                return await self.play_query(req, q.value.strip())
            await m.play()
            return ActionResult(ok=True, speech="Tocando.")
        if iid == IntentId.MUSIC_PAUSE:
            await m.pause()
            return ActionResult(ok=True, speech="Pausado.")
        if iid == IntentId.MUSIC_NEXT:
            await m.next()
            return ActionResult(ok=True, speech="Próxima.")
        if iid == IntentId.MUSIC_PREVIOUS:
            await m.previous()
            return ActionResult(ok=True, speech="Voltando.")
        if iid == IntentId.MUSIC_VOLUME:
            s = req.intent.slot(SlotName.VOLUME)
            raw = s.value if s else ""
            current = None
            if raw.strip()[:1] in ("+", "-"):
                if not await m.ensure_running():
                    raise SpotifyNotRunning("timeout")
                current = await m.get_volume()
            level = parse_volume(raw, current)
            if level is None:
                return ActionResult(ok=False, speech=SAY_BAD_VOLUME, expression=Expression.CONFUSED)
            level = await m.set_volume(level)
            return ActionResult(ok=True, speech=f"Volume do Spotify em {round(level * 100)}%.")
        return ActionResult(ok=False, speech=SAY_DBUS_FAILED)


def handlers(
    mpris: SpotifyMpris | None = None, play_query: PlayQuery | None = None
) -> list[ActionHandler]:
    """Handlers deste módulo para o ``Registry``. ``play_query`` vem da 2.2 (tocar por nome)."""
    return [SpotifyHandler(mpris or SpotifyMpris(), play_query)]
