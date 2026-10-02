"""Testes dos sinais de música (tarefa 2.4) com MPRIS falso e relógio falso."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from dbus_next import MessageType

from magi.common.contracts import ActionRequest, Intent, IntentId, MusicSignalValue
from magi.core.actions import Registry
from magi.core.actions.spotify_mpris import PlayerState, SpotifyNotRunning
from magi.core.music import import_taste as it
from magi.core.music import signals as sg

V = MusicSignalValue


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class FakeMpris:
    def __init__(self) -> None:
        self.st: PlayerState | None = None
        self.nexts = 0

    async def state(self) -> PlayerState:
        if self.st is None:
            raise SpotifyNotRunning("x")
        return self.st

    async def next(self) -> None:
        self.nexts += 1


def track(tid: str, status: str = "Playing", length: float = 200.0, pos: float = 0.0) -> PlayerState:
    return PlayerState(
        status=status,
        track_id=f"/com/spotify/track/{tid}",
        title=f"T{tid}",
        artists=(f"A{tid}",),
        length_s=length,
        position_s=pos,
    )


def make():
    clock, mpris, repo = Clock(), FakeMpris(), sg.MemoryMusicSignalsRepo()
    s = sg.MusicSignals(mpris, repo, clock=clock, now=lambda: datetime(2026, 10, 2, 22, tzinfo=UTC))
    return s, clock, mpris, repo


def _req(iid):
    return ActionRequest(intent=Intent(iid), ctx=None)


def test_track_uri():
    assert sg.track_uri(track("abc")) == "spotify:track:abc"
    st = PlayerState(status="Playing", url="https://open.spotify.com/track/xyz?si=1")
    assert sg.track_uri(st) == "spotify:track:xyz"
    assert sg.track_uri(None) == ""


async def test_skip_under_30s_only_for_magui_pick():
    s, clock, _, repo = make()
    s.mark_picked("spotify:track:1", request="toca 1")
    await s.observe(track("1"))
    clock.t += 12
    sig = await s.observe(track("2"))
    assert sig is not None and sig.signal == V.SKIPPED and sig.track_uri == "spotify:track:1"
    assert sig.artist == "A1" and sig.context["picked"] is True and sig.context["request"] == "toca 1"
    # faixa que a Magui não escolheu: pulo não vira sinal (R8.3)
    clock.t += 5
    assert await s.observe(track("3")) is None
    assert [r.signal for r in repo.rows] == [V.SKIPPED]


async def test_pause_does_not_count_and_long_listen_is_not_skip():
    s, clock, _, repo = make()
    s.mark_picked("spotify:track:1")
    await s.observe(track("1"))
    clock.t += 10
    await s.observe(track("1", status="Paused"))
    clock.t += 500  # pausado: não conta
    await s.observe(track("1"))
    clock.t += 10
    assert (await s.observe(track("2"))).signal == V.SKIPPED  # 20 s ouvidos
    s.mark_picked("spotify:track:3")
    clock.t += 1
    await s.observe(track("3"))
    clock.t += 60
    assert await s.observe(track("4")) is None  # 60 s: nem pulo, nem inteira
    assert len(repo.rows) == 1


async def test_finished_any_track():
    s, clock, _, repo = make()
    await s.observe(track("1", length=180))
    clock.t += 179
    sig = await s.observe(track("2"))
    assert sig.signal == V.FINISHED and sig.context["picked"] is False
    # vista pela primeira vez no meio: conta a posição inicial
    clock.t += 1
    await s.observe(track("3", length=200, pos=150))
    clock.t += 45
    assert (await s.observe(None)).signal == V.FINISHED  # Spotify fechou no fim
    assert [r.signal for r in repo.rows] == [V.FINISHED, V.FINISHED]


async def test_album_pick_inherits_while_natural():
    s, clock, _, repo = make()
    s.mark_picked("spotify:album:x")
    clock.t += 3
    await s.observe(track("1", length=100))
    clock.t += 100
    await s.observe(track("2", length=100))  # 1 terminou: 2 também é da Magui
    clock.t += 5
    await s.observe(track("3"))  # 2 pulada
    clock.t += 5
    await s.observe(track("4"))  # 3 não herda (2 foi pulada)
    assert [(r.track_uri[-1], r.signal) for r in repo.rows] == [("1", V.FINISHED), ("2", V.SKIPPED)]


async def test_pick_window_expires():
    s, clock, _, repo = make()
    s.mark_picked("spotify:album:x")
    clock.t += sg.PICK_WINDOW_S + 1
    await s.observe(track("1"))
    clock.t += 5
    await s.observe(track("2"))
    assert repo.rows == []


async def test_like_and_never_via_handler():
    s, clock, mpris, repo = make()
    reg = Registry(sg.handlers(s))
    res = await reg.run(_req(IntentId.MUSIC_LIKE))
    assert not res.ok and res.speech == sg.SAY_NOTHING  # Spotify fechado
    mpris.st = track("9")
    res = await reg.run(_req(IntentId.MUSIC_LIKE))
    assert res.ok and res.speech == sg.SAY_LIKED
    clock.t += 3
    res = await reg.run(_req(IntentId.MUSIC_NEVER))
    assert res.ok and res.speech == sg.SAY_NEVER and mpris.nexts == 1
    assert [r.signal for r in repo.rows] == [V.LIKED, V.NEVER]
    assert await s.banned() == {"spotify:track:9"}
    # a troca de faixa depois do "nunca mais" não grava pulo extra
    clock.t += 1
    assert await s.observe(track("10")) is None
    assert len(repo.rows) == 2


class FakeBus:
    def __init__(self) -> None:
        self.connected = True
        self.handlers = []
        self.calls = []

    def add_message_handler(self, h):
        self.handlers.append(h)

    async def call(self, msg):
        self.calls.append(msg)

    def disconnect(self):
        self.connected = False


class Sig:
    message_type = MessageType.SIGNAL
    member = "PropertiesChanged"
    path = "/org/mpris/MediaPlayer2"
    body = ["org.mpris.MediaPlayer2.Player", {}, []]


async def test_run_subscribes_and_reacts_to_signal():
    bus = FakeBus()
    mpris, repo = FakeMpris(), sg.MemoryMusicSignalsRepo()

    async def factory():
        return bus

    s = sg.MusicSignals(mpris, repo, bus_factory=factory)
    mpris.st = track("1")
    task = asyncio.create_task(s.run(safety_s=30, debounce_s=0))
    for _ in range(20):
        await asyncio.sleep(0)
    assert bus.calls[0].member == "AddMatch" and "PropertiesChanged" in bus.calls[0].body[0]
    assert s.current == "spotify:track:1"
    mpris.st = track("2")
    bus.handlers[0](Sig())
    for _ in range(20):
        await asyncio.sleep(0)
    assert s.current == "spotify:track:2"
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not bus.connected


class FakeTaste:
    def __init__(self, n: int) -> None:
        self.n = n
        self.upserts = 0

    async def count(self) -> int:
        return self.n

    async def upsert(self, entries) -> None:
        self.upserts += 1


class FakeApi:
    async def get(self, path, params=None):
        if path == "/me/top/artists":
            return {"items": [{"name": "X"}]}
        return {"items": []}


async def test_import_if_stale_once_a_day(tmp_path):
    state = tmp_path / "d" / it.STATE_FILE
    repo, t = FakeTaste(5), [100000.0]
    now = lambda: t[0]  # noqa: E731
    assert (await it.import_if_stale(repo, state, FakeApi(), now=now)) is not None  # sem data: importa
    assert json.loads(state.read_text())["last_import"] == t[0]
    t[0] += 3600
    assert await it.import_if_stale(repo, state, FakeApi(), now=now) is None
    t[0] += it.REFRESH_S
    assert await it.import_if_stale(repo, state, FakeApi(), now=now) is not None
    assert repo.upserts == 2
    repo.n = 0  # tabela vazia: importa mesmo com data recente
    assert await it.import_if_stale(repo, state, FakeApi(), now=now) is not None
