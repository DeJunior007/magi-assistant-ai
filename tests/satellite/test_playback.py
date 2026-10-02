"""Reprodução com saída de áudio falsa: nunca abre o dispositivo real."""

import asyncio

import numpy as np
from wyoming.audio import AudioChunk, AudioStart, AudioStop

from magi.common.contracts import CHUNK_SAMPLES, MouthEvent, PcmFormat, PlaybackDone, StopPlayback
from magi.common.events import to_event
from magi.satellite.__main__ import core_handler, wake_loop
from magi.satellite.capture import ArraySource
from magi.satellite.playback import Player, mouth_level
from magi.satellite.wake import WakeSpotter

RATE = 24_000
FMT = PcmFormat(RATE, 2, 1)
STEP = RATE * 2 * 50 // 1000  # bytes de 50 ms


class FakeOutput:
    def __init__(self):
        self.fmt = None
        self.buf = bytearray()
        self.drained = self.aborted = False

    def start(self, fmt):
        self.fmt = fmt

    def write(self, pcm):
        self.buf.extend(pcm)

    def pending(self):  # o "dispositivo" consome 50 ms a cada consulta
        del self.buf[:STEP]
        return len(self.buf)

    def drain(self):
        self.drained = True

    def abort(self):
        self.aborted = True
        self.buf.clear()


class FakeDucker:
    def __init__(self, log):
        self.log = log

    async def duck(self):
        self.log.append("duck")
        return 1

    async def restore(self):
        self.log.append("restore")
        return 1


def tone(ms, amp):
    n = RATE * ms // 1000
    return (np.sin(np.arange(n) * 2 * np.pi * 220 / RATE) * amp * 32767).astype(np.int16).tobytes()


def make_player(sent, outputs):
    async def send(msg):
        sent.append(msg)
        return True

    def factory():
        outputs.append(FakeOutput())
        return outputs[-1]

    return Player(send, "pc", output_factory=factory, ducker=FakeDucker(sent), interval_ms=1)


async def feed(player, pcm, stop=True):
    await player.handle(AudioStart(rate=RATE, width=2, channels=1).event())
    for i in range(0, len(pcm), 4800):
        await player.handle(AudioChunk(rate=RATE, width=2, channels=1, audio=pcm[i:i + 4800]).event())
    if stop:
        await player.handle(AudioStop().event())


async def wait_for(cond, timeout=2.0):
    async def loop():
        while not cond():
            await asyncio.sleep(0.002)
    await asyncio.wait_for(loop(), timeout)


def test_mouth_level():
    assert mouth_level(b"") == 0.0
    assert mouth_level(tone(50, 0.0)) == 0.0
    assert mouth_level(tone(50, 0.05)) < 0.15
    assert mouth_level(tone(50, 0.9)) == 1.0


async def test_toca_ate_o_fim():
    sent, outs = [], []
    player = make_player(sent, outs)
    await feed(player, tone(300, 0.9) + tone(200, 0.0))
    await wait_for(lambda: any(isinstance(m, PlaybackDone) for m in sent))
    assert outs[0].fmt == FMT and outs[0].drained and not outs[0].aborted
    mouths = [m.level for m in sent if isinstance(m, MouthEvent)]
    assert len(mouths) >= 10  # um a cada 50 ms de áudio
    assert max(mouths) > 0.5 and mouths[-1] == 0.0
    assert sent[0] == "duck"
    assert sent[-1] == PlaybackDone(satellite="pc") and sent[-2] == "restore"
    assert not player.playing


async def test_interrupcao_corta_sem_playback_done():
    sent, outs = [], []
    player = make_player(sent, outs)
    await feed(player, tone(5000, 0.5), stop=False)
    await asyncio.sleep(0.02)
    assert player.playing
    assert player.interrupt() is True
    assert outs[0].aborted and not player.playing
    await player.close()
    assert "restore" in sent and MouthEvent(0.0, "pc") in sent
    assert not any(isinstance(m, PlaybackDone) for m in sent)
    # sobras da fala interrompida são descartadas
    await player.handle(AudioChunk(rate=RATE, width=2, channels=1, audio=tone(50, 0.5)).event())
    assert not player.playing and player.interrupt() is False


async def test_magi_stop_e_handler_do_nucleo():
    sent, outs = [], []
    player = make_player(sent, outs)
    listens = asyncio.Queue()
    on_event = core_handler(listens, player)
    await on_event(AudioStart(rate=RATE, width=2, channels=1).event())
    await on_event(AudioChunk(rate=RATE, width=2, channels=1, audio=tone(2000, 0.5)).event())
    await on_event(to_event(StopPlayback()))
    assert outs[0].aborted
    await player.close()
    assert not any(isinstance(m, PlaybackDone) for m in sent)


async def test_wake_word_durante_a_fala_interrompe():
    class Scripted:
        name = "fake"

        def __init__(self):
            self.i = 0

        def process(self, block):
            self.i += 1
            return 0.9 if self.i == 3 else 0.0

        def reset(self):
            pass

    class Client:
        def __init__(self):
            self.sent = []

        async def send(self, msg):
            self.sent.append((player.playing, msg))
            return True

        async def send_event(self, ev):
            return True

    sent, outs = [], []
    player = make_player(sent, outs)
    await feed(player, tone(5000, 0.5), stop=False)
    client = Client()
    src = ArraySource(np.zeros(CHUNK_SAMPLES * 5, np.int16))
    await wake_loop(src, WakeSpotter(Scripted(), gate_dbfs=None), client, "pc", player=player)
    assert outs[0].aborted
    assert client.sent and client.sent[0][0] is False  # cortou antes de mandar o magi-wake
    await player.close()
