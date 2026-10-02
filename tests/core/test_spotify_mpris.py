# ruff: noqa: F821, F722
"""Testes do MPRIS com um dbus-daemon privado e um Spotify falso (regra 8: nada real)."""

import asyncio
import shutil
import subprocess

import pytest
from dbus_next import Variant
from dbus_next.aio import MessageBus
from dbus_next.service import PropertyAccess, ServiceInterface, dbus_property, method

from magi.common.contracts import ActionRequest, Intent, IntentId, Slot, SlotName
from magi.core.actions import Registry
from magi.core.actions import spotify_mpris as sm

pytestmark = pytest.mark.skipif(shutil.which("dbus-daemon") is None, reason="sem dbus-daemon")

_CONFIG = """<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>session</type>
  <listen>unix:dir={dir}</listen>
  <policy context="default">
    <allow send_destination="*" eavesdrop="true"/>
    <allow eavesdrop="true"/>
    <allow own="*"/>
  </policy>
</busconfig>
"""


@pytest.fixture
def bus_address(tmp_path):
    cfg = tmp_path / "bus.conf"
    cfg.write_text(_CONFIG.format(dir=tmp_path))
    proc = subprocess.Popen(
        ["dbus-daemon", f"--config-file={cfg}", "--nofork", "--print-address=1"],
        stdout=subprocess.PIPE,
        text=True,
    )
    addr = proc.stdout.readline().strip()
    yield addr
    proc.terminate()
    proc.wait(5)


class FakePlayer(ServiceInterface):
    def __init__(self):
        super().__init__(sm.PLAYER_IFACE)
        self.calls: list[str] = []
        self.status = "Paused"
        self.volume = 0.5
        self.position_us = 42_000_000

    @method()
    def Play(self):
        self.calls.append("Play")
        self.status = "Playing"

    @method()
    def Pause(self):
        self.calls.append("Pause")
        self.status = "Paused"

    @method()
    def PlayPause(self):
        self.calls.append("PlayPause")

    @method()
    def Next(self):
        self.calls.append("Next")

    @method()
    def Previous(self):
        self.calls.append("Previous")

    @method()
    def OpenUri(self, uri: "s"):
        self.calls.append(f"OpenUri {uri}")

    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> "s":
        return self.status

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> "x":
        return self.position_us

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> "a{sv}":
        return {
            "mpris:trackid": Variant("o", "/com/spotify/track/abc"),
            "xesam:title": Variant("s", "Numb"),
            "xesam:artist": Variant("as", ["Linkin Park"]),
            "xesam:album": Variant("s", "Meteora"),
            "xesam:url": Variant("s", "https://open.spotify.com/track/abc"),
            "mpris:length": Variant("x", 185_000_000),
        }

    @dbus_property()
    def Volume(self) -> "d":
        return self.volume

    @Volume.setter
    def Volume(self, v: "d"):
        self.volume = v


class FakeSpotify:
    """Serviço MPRIS falso no barramento privado + runner falso do flatpak."""

    def __init__(self, address):
        self.address = address
        self.player = FakePlayer()
        self.bus: MessageBus | None = None
        self.launches = 0
        self.start_on_launch = True
        self.delay = 0.2
        self._tasks = []

    async def start(self):
        self.bus = await MessageBus(bus_address=self.address).connect()
        self.bus.export(sm.OBJECT_PATH, self.player)
        await self.bus.request_name(sm.BUS_NAME)

    def stop(self):
        if self.bus:
            self.bus.disconnect()
            self.bus = None

    def launcher(self):
        self.launches += 1
        if self.start_on_launch:

            async def later():
                await asyncio.sleep(self.delay)
                await self.start()

            self._tasks.append(asyncio.get_running_loop().create_task(later()))


@pytest.fixture
async def env(bus_address):
    fake = FakeSpotify(bus_address)

    async def factory():
        return await MessageBus(bus_address=bus_address).connect()

    mpris = sm.SpotifyMpris(bus_factory=factory, launcher=fake.launcher, wait_s=2.0, poll_s=0.05)
    yield fake, mpris
    await mpris.close()
    fake.stop()


def _req(intent_id, *slots):
    return ActionRequest(intent=Intent(id=intent_id, slots=tuple(slots)), ctx=None)


async def test_commands_when_running(env):
    fake, mpris = env
    await fake.start()
    assert await mpris.is_running()
    for m in (mpris.play, mpris.pause, mpris.toggle, mpris.next, mpris.previous):
        await m()
    await mpris.open_uri("spotify:track:abc")
    expected = ["Play", "Pause", "PlayPause", "Next", "Previous", "OpenUri spotify:track:abc"]
    assert fake.player.calls == expected
    assert fake.launches == 0


async def test_opens_and_retries_when_closed(env):
    fake, mpris = env
    assert not await mpris.is_running()
    await mpris.next()  # R7.3: abre, espera o MPRIS e repete
    assert fake.launches == 1
    assert fake.player.calls == ["Next"]


async def test_timeout_when_never_appears(env):
    fake, mpris = env
    fake.start_on_launch = False
    mpris.wait_s = 0.3
    with pytest.raises(sm.SpotifyNotRunning):
        await mpris.play()
    res = await sm.SpotifyHandler(mpris).run(_req(IntentId.MUSIC_PLAY))
    assert not res.ok and res.speech == sm.SAY_NOT_STARTED


async def test_state_and_volume(env):
    fake, mpris = env
    await fake.start()
    st = await mpris.state()
    assert st.status == "Paused" and not st.playing
    assert st.track_id == "/com/spotify/track/abc"
    assert st.title == "Numb" and st.artists == ("Linkin Park",) and st.album == "Meteora"
    assert st.length_s == 185.0 and st.position_s == 42.0 and st.volume == 0.5
    assert await mpris.position() == 42.0
    assert await mpris.set_volume(1.7) == 1.0
    assert fake.player.volume == 1.0
    assert await mpris.get_volume() == 1.0


async def test_reads_do_not_open(env):
    fake, mpris = env
    with pytest.raises(sm.SpotifyNotRunning):
        await mpris.state()
    assert fake.launches == 0


async def test_handler_intents_via_registry(env):
    fake, mpris = env
    reg = Registry(sm.handlers(mpris))
    for iid in ("music.pick", "music.like", "music.never"):
        assert not reg.handles(iid)

    res = await reg.run(_req(IntentId.MUSIC_OPEN))
    assert res.ok and res.speech == sm.SAY_OPENING and fake.launches == 1
    res = await reg.run(_req(IntentId.MUSIC_OPEN))
    assert res.ok and res.speech == sm.SAY_ALREADY_OPEN and fake.launches == 1

    for iid in (IntentId.MUSIC_PLAY, IntentId.MUSIC_PAUSE, IntentId.MUSIC_NEXT, IntentId.MUSIC_PREVIOUS):
        assert (await reg.run(_req(iid))).ok
    assert fake.player.calls == ["Play", "Pause", "Next", "Previous"]

    vol = Slot(name=SlotName.VOLUME, value="30")
    res = await reg.run(_req(IntentId.MUSIC_VOLUME, vol))
    assert res.ok and fake.player.volume == pytest.approx(0.3)
    res = await reg.run(_req(IntentId.MUSIC_VOLUME, Slot(name=SlotName.VOLUME, value="+10")))
    assert res.ok and fake.player.volume == pytest.approx(0.4)
    res = await reg.run(_req(IntentId.MUSIC_VOLUME, Slot(name=SlotName.VOLUME, value="alto")))
    assert not res.ok and res.speech == sm.SAY_BAD_VOLUME


async def test_play_query_delegates(env):
    fake, mpris = env
    q = Slot(name=SlotName.QUERY, value="Linkin Park")
    res = await sm.SpotifyHandler(mpris).run(_req(IntentId.MUSIC_PLAY, q))
    assert not res.ok and res.speech == sm.SAY_NO_QUERY

    seen = []

    async def play_query(req, query):
        seen.append(query)
        return sm.ActionResult(ok=True, speech="ok")

    res = await sm.SpotifyHandler(mpris, play_query).run(_req(IntentId.MUSIC_PLAY, q))
    assert res.ok and seen == ["Linkin Park"] and fake.player.calls == []


def test_parse_volume():
    assert sm.parse_volume("50", None) == 0.5
    assert sm.parse_volume("-20", 0.1) == 0.0
    assert sm.parse_volume("+10", None) is None
    assert sm.parse_volume("x", 0.5) is None


def test_launch_flatpak_detached(monkeypatch):
    seen = {}

    def fake_popen(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw

    monkeypatch.setattr(sm.subprocess, "Popen", fake_popen)
    # nunca carrega script no KWin real nos testes
    monkeypatch.setattr(sm, "kwin_minimize_next_spotify", lambda: seen.setdefault("armed", True))
    sm.launch_flatpak()
    assert seen["armed"] is True  # arma o "abrir minimizado" antes de abrir
    assert seen["cmd"] == ("flatpak", "run", "com.spotify.Client")
    assert seen["kw"]["start_new_session"] is True
    assert seen["kw"]["stdout"] is subprocess.DEVNULL


def test_kwin_minimize_script_loaded_and_run(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    calls = []

    def run(*args):
        calls.append(args)
        return "i 7\n" if args[2] == "loadScript" else ""

    assert sm.kwin_minimize_next_spotify(run)
    assert [c[2] for c in calls] == ["unloadScript", "loadScript", "run"]
    assert calls[2][0] == "/Scripting/Script7"
    js = (tmp_path / "magi" / f"{sm.KWIN_SCRIPT_NAME}.js").read_text()
    assert "w.minimized = true" in js and "workspace.activeWindow = prev" in js


def test_kwin_minimize_failure_is_soft(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    def run(*args):
        raise FileNotFoundError("busctl")

    assert not sm.kwin_minimize_next_spotify(run)
