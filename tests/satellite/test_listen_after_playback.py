"""1.26: escuta do núcleo (``magi-listen``) logo depois da Magui falar recebe o áudio do microfone.

Captura e saída falsas: a fala da Magui toca no ``Player`` enquanto o "microfone" continua
mandando blocos; depois do ``playback-done`` chega o ``magi-listen`` e o que vai ao núcleo tem
que ser o áudio do microfone (não zeros, nem o que estava tocando).
"""

import asyncio
from pathlib import Path

import numpy as np
from wyoming.audio import AudioChunk

from magi.common.contracts import AudioEnd, AudioEndReason, ListenRequest, PlaybackDone
from magi.common.events import from_event, to_event
from magi.satellite.__main__ import core_handler, wake_loop
from magi.satellite.capture import iter_blocks, read_wav
from magi.satellite.stream import UtteranceStream
from magi.satellite.vad import Endpointer
from magi.satellite.wake import WakeSpotter

from .test_playback import feed, make_player, tone, wait_for

FALA = read_wav(Path(__file__).parent / "data" / "fala_ptbr.wav")


class EnergyVad:
    """VAD falso por energia (sem modelo): voz acima de -45 dBFS."""

    def process(self, block):
        x = block.astype(np.float32) / 32768.0
        return 0.9 if float(np.sqrt(np.mean(x * x))) > 10 ** (-45 / 20) else 0.0

    def reset(self):
        pass


class NoWake:
    name = "fake"

    def process(self, block):
        return 0.0

    def reset(self):
        pass


class MicQueue:
    def __init__(self):
        self.q: asyncio.Queue = asyncio.Queue()

    def push(self, samples):
        for b in iter_blocks(samples):
            self.q.put_nowait(b)

    async def blocks(self):
        while (b := await self.q.get()) is not None:
            yield b

    async def close(self):
        self.q.put_nowait(None)


class Client:
    def __init__(self):
        self.events = []

    async def send(self, msg):
        return await self.send_event(to_event(msg))

    async def send_event(self, ev):
        self.events.append(from_event(ev))
        return True


async def test_listen_depois_da_fala_recebe_o_microfone():
    sent, outs = [], []
    player = make_player(sent, outs)
    listens: asyncio.Queue = asyncio.Queue()
    on_event = core_handler(listens, player)
    mic, client = MicQueue(), Client()
    loop = asyncio.create_task(wake_loop(mic, WakeSpotter(NoWake(), gate_dbfs=None), client, "pc",
                                         vad=EnergyVad(), listens=listens, player=player))
    room = (np.random.default_rng(1).normal(0, 30, 16000)).astype(np.int16)  # ruído de -60 dBFS
    mic.push(room)  # microfone ativo enquanto a Magui fala
    await feed(player, tone(300, 0.5))
    await wait_for(lambda: any(isinstance(m, PlaybackDone) for m in sent))
    await on_event(to_event(ListenRequest(timeout_ms=3000, reason="followup")))
    await wait_for(lambda: not listens.empty())
    speech = np.concatenate([room[:4000], FALA, np.zeros(16000 * 2, np.int16) + room[:1]])
    mic.push(speech)
    await wait_for(lambda: any(isinstance(e, AudioEnd) for e in client.events), timeout=5)
    await mic.close()
    await loop
    await player.close()

    pcm = b"".join(e.audio for e in client.events if isinstance(e, AudioChunk))
    end = next(e for e in client.events if isinstance(e, AudioEnd))
    assert end.reason is AudioEndReason.VAD
    assert FALA.astype("<i2").tobytes() in pcm  # o áudio do microfone, inteiro
    assert np.abs(np.frombuffer(pcm, "<i2")).max() > 1000
    assert end.tone.energy_db > -40 and end.tone.duration_ms > 3000


async def test_log_distingue_sem_voz_de_audio_zerado(caplog):
    async def send(ev):
        return True

    caplog.set_level("INFO", logger="magi.satellite.stream")
    quiet = UtteranceStream(send, Endpointer(EnergyVad(), no_speech_ms=400))
    room = (np.random.default_rng(2).normal(0, 30, 16000)).astype(np.int16)
    for b in iter_blocks(room):
        if await quiet.feed(b):
            break
    assert quiet.end.reason is AudioEndReason.NO_SPEECH
    assert quiet.end.tone.energy_db == -120.0  # tom: nenhum bloco com voz
    rms, peak = quiet.level()
    assert -65 < rms < -55 and peak > -50  # mas o microfone mandou áudio de verdade
    assert "silêncio digital" not in caplog.text

    zeros = UtteranceStream(send, Endpointer(EnergyVad(), no_speech_ms=400))
    for b in iter_blocks(np.zeros(16000, np.int16)):
        if await zeros.feed(b):
            break
    assert zeros.level() == (-120.0, -120.0)
    assert "silêncio digital" in caplog.text
