"""Detecção de call do Discord (5.1, R2.1, R2.2) com ``pulsectl`` falso (regra 8)."""

import asyncio
from types import SimpleNamespace

import numpy as np

from magi.common.contracts import SatelliteStatus
from magi.satellite.discord import (
    DiscordCallMonitor,
    call_active,
    find_discord_source_outputs,
)
from magi.satellite.wake import WakeSpotter


def so(index, name="", binary="", corked=False, **extra):
    props = {"application.name": name, "application.process.binary": binary, **extra}
    return SimpleNamespace(index=index, proplist=props, corked=corked)


VOICE = so(10, "WEBRTC VoiceEngine", "Discord")


class FakePulse:
    def __init__(self, script):
        self.script = script  # lista compartilhada: cada leitura consome o primeiro item
        self.closed = False

    def source_output_list(self):
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return list(item)

    def close(self):
        self.closed = True


class FakeDetector:
    def __init__(self):
        self.resets = 0

    def process(self, block):
        return 0.0

    def reset(self):
        self.resets += 1


class Harness:
    def __init__(self, script, *, connected=True, confirm=2):
        self.sent = []
        self.connected = connected
        self.pulses = []
        self.spotter = WakeSpotter(FakeDetector())

        def factory():
            p = FakePulse(script)
            self.pulses.append(p)
            return p

        async def send(msg):
            if not self.connected:
                return False
            self.sent.append(msg)
            return True

        self.mon = DiscordCallMonitor(self.spotter, send, "pc", pulse_factory=factory,
                                      poll_s=0.01, confirm=confirm)

    async def steps(self, n):
        for _ in range(n):
            await self.mon.step()


def run(coro):
    return asyncio.run(coro)


def test_find_and_call_rules():
    other = so(1, "Firefox", "firefox")
    screen = so(11, "discord_capture", "Discord")
    flatpak = so(12, "x", "", **{"pipewire.access.portal.app_id": "com.discordapp.Discord"})
    pulse = FakePulse([[other, VOICE, screen, flatpak]])
    found = find_discord_source_outputs(pulse)
    assert [s.index for s in found] == [10, 11, 12]
    assert call_active([VOICE])
    assert not call_active([so(10, "WEBRTC VoiceEngine", "Discord", corked=True)])
    assert not call_active([screen])  # só compartilhamento de tela não é call
    assert not call_active([])


def test_enter_and_leave_call():
    async def go():
        h = Harness([[], [VOICE], [VOICE], [VOICE], [], [], []])
        await h.steps(1)
        assert h.sent == [] and h.spotter.enabled
        await h.steps(2)  # duas leituras em call
        assert h.mon.in_call and not h.spotter.enabled
        assert h.sent == [SatelliteStatus(satellite="pc", in_call=True, wake_enabled=False)]
        await h.steps(1)  # ainda em call
        await h.steps(2)  # duas leituras fora
        assert not h.mon.in_call and h.spotter.enabled
        assert h.sent[-1] == SatelliteStatus(satellite="pc", in_call=False, wake_enabled=True)
        assert len(h.sent) == 2
        assert h.spotter.detector.resets == 1
        assert h.spotter.feed(np.zeros(1280, dtype=np.int16)) is None  # religado, sem erro
        await h.mon.close()

    run(go())


def test_hysteresis_ignores_single_blips():
    async def go():
        h = Harness([[VOICE], [], [VOICE], [], [VOICE], []])
        await h.steps(6)
        assert not h.mon.in_call and h.spotter.enabled and h.sent == []
        await h.mon.close()

    run(go())


def test_corked_stream_is_not_a_call():
    async def go():
        paused = so(10, "WEBRTC VoiceEngine", "Discord", corked=True)
        h = Harness([[paused]])
        await h.steps(4)
        assert not h.mon.in_call and h.sent == []
        await h.mon.close()

    run(go())


def test_discord_absent():
    async def go():
        h = Harness([[so(1, "magi", ""), so(2, "Firefox", "firefox")]])
        await h.steps(5)
        assert not h.mon.in_call and h.spotter.enabled and h.sent == []
        await h.mon.close()

    run(go())


def test_pulse_error_keeps_running_and_reconnects():
    async def go():
        h = Harness([OSError("pipewire caiu"), [VOICE], RuntimeError("x"), [VOICE], [VOICE]])
        await h.steps(1)
        assert h.pulses[0].closed and not h.mon.in_call
        await h.steps(2)  # [VOICE], erro: o erro não conta nem zera a histerese
        assert not h.mon.in_call
        await h.steps(1)
        assert h.mon.in_call  # [VOICE], erro, [VOICE] => 2 leituras em call
        assert len(h.pulses) == 3  # reconectou depois de cada erro
        await h.mon.close()

    run(go())


def test_factory_error_does_not_crash():
    async def go():
        h = Harness([[]])

        def boom():
            raise ConnectionError("sem servidor")

        h.mon.pulse_factory = boom
        await h.steps(3)
        assert not h.mon.in_call and h.spotter.enabled
        await h.mon.close()

    run(go())


def test_status_resent_until_delivered():
    async def go():
        h = Harness([[VOICE]], connected=False)
        await h.steps(2)
        assert h.mon.in_call and h.sent == []
        h.connected = True
        await h.steps(1)
        assert h.sent == [SatelliteStatus(satellite="pc", in_call=True, wake_enabled=False)]
        await h.steps(2)
        assert len(h.sent) == 1
        await h.mon.close()

    run(go())


def test_run_loop_toggles_and_cancels():
    async def go():
        h = Harness([[VOICE]])
        task = asyncio.create_task(h.mon.run())
        for _ in range(100):
            if h.mon.in_call:
                break
            await asyncio.sleep(0.01)
        assert h.mon.in_call and not h.spotter.enabled
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert h.pulses[-1].closed

    run(go())
