"""Envio da fala ao núcleo Wyoming falso: frase inteira, corte por silêncio, 15 s, ``magi-listen``."""

import asyncio
from pathlib import Path

import numpy as np
import pytest
from wyoming.audio import AudioChunk, AudioStart
from wyoming.event import async_read_event, async_write_event

from magi.common.contracts import (
    CHUNK_BYTES,
    CHUNK_SAMPLES,
    VAD_SILENCE_MS,
    AudioEnd,
    AudioEndReason,
    ListenRequest,
    SatelliteHello,
    WakeEvent,
)
from magi.common.events import from_event, to_event
from magi.satellite.__main__ import CoreClient, listen_handler, wake_loop
from magi.satellite.capture import ArraySource, iter_blocks, read_wav
from magi.satellite.stream import PREROLL_BLOCKS, PreRoll, ToneMeter, UtteranceStream, count_syllables
from magi.satellite.vad import Endpointer, load_vad
from magi.satellite.wake import WakeSpotter

DATA = Path(__file__).parent / "data"
FALA = read_wav(DATA / "fala_ptbr.wav")


def silence(seconds):
    return np.zeros(int(16000 * seconds), np.int16)


class FakeCore:
    """Núcleo Wyoming falso: guarda o que chega e manda eventos ao satélite."""

    def __init__(self):
        self.received: asyncio.Queue = asyncio.Queue()
        self.writer = None

    async def _handle(self, reader, writer):
        self.writer = writer
        while (ev := await async_read_event(reader)) is not None:
            await self.received.put(from_event(ev))
        writer.close()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        if self.writer:
            self.writer.close()
        self.server.close()

    async def send(self, msg):
        await async_write_event(to_event(msg), self.writer)
        await self.writer.drain()

    async def turn(self, timeout=5.0):
        """Lê até o ``audio-stop``; devolve (eventos antes do áudio, AudioStart, PCM, AudioEnd)."""
        before, start, pcm = [], None, bytearray()
        while True:
            msg = await asyncio.wait_for(self.received.get(), timeout)
            if isinstance(msg, AudioStart):
                start = msg
            elif isinstance(msg, AudioChunk):
                assert start is not None
                pcm += msg.audio
            elif isinstance(msg, AudioEnd):
                assert start is not None
                return before, start, bytes(pcm), msg
            else:
                before.append(msg)


class Scripted:
    """Wake word falso: nota alta no bloco ``hit``."""

    def __init__(self, hit):
        self.hit, self.i = hit, 0

    def process(self, block):
        self.i += 1
        return 0.9 if self.i - 1 == self.hit else 0.0

    def reset(self):
        pass


class QueueSource:
    """Fonte alimentada pelo teste (para ``magi-listen``)."""

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


@pytest.fixture(scope="module")
def vad():
    try:
        return load_vad()
    except FileNotFoundError:
        pytest.skip("Silero VAD não baixado (uv run magi-satellite --download-models)")


async def wake_turn(vad, audio, hit):
    async with FakeCore() as core:
        client = CoreClient(SatelliteHello(satellite="pc"), "127.0.0.1", core.port)
        client.start()
        await client.wait_connected(3)
        spotter = WakeSpotter(Scripted(hit), gate_dbfs=None)
        await wake_loop(ArraySource(audio), spotter, client, "pc", vad=vad)
        result = await core.turn()
        await client.stop()
    return result


async def test_frase_falada_chega_inteira_com_pre_rolo(vad):
    lead = 6  # blocos de silêncio antes da fala; o wake dispara no último deles
    audio = np.concatenate([silence(lead * 0.08), FALA, silence(2)])
    raw = np.ascontiguousarray(audio).astype("<i2").tobytes()
    before, start, pcm, end = await wake_turn(vad, audio, hit=lead - 1)

    assert isinstance(before[0], SatelliteHello) and isinstance(before[1], WakeEvent)
    assert (start.rate, start.width, start.channels) == (16000, 2, 1)
    # o envio começa 400 ms (5 blocos) antes da ativação e é o áudio original, sem buracos
    first = lead - PREROLL_BLOCKS
    assert pcm == raw[first * CHUNK_BYTES : first * CHUNK_BYTES + len(pcm)]
    fala_end = lead * CHUNK_BYTES + FALA.nbytes
    assert len(pcm) >= fala_end - first * CHUNK_BYTES  # a frase inteira chegou
    assert end.reason is AudioEndReason.VAD


async def test_corte_por_silencio_e_tom(vad):
    audio = np.concatenate([silence(0.48), FALA, silence(3)])
    _, _, pcm, end = await wake_turn(vad, audio, hit=5)
    sent_ms = len(pcm) // 32
    assert end.reason is AudioEndReason.VAD
    assert end.timestamp == sent_ms
    # termina ~1 s depois da última voz, bem antes do fim dos 3 s de silêncio
    assert sent_ms <= PREROLL_BLOCKS * 80 + len(FALA) // 16 + VAD_SILENCE_MS + 100
    tone = end.tone
    assert -40 < tone.energy_db < -10
    assert 2.0 < tone.speech_rate < 9.0
    assert 3500 < tone.duration_ms < 5200


async def test_corte_em_15s(vad):
    audio = np.concatenate([silence(0.48), *[FALA] * 4, silence(1)])
    _, _, pcm, end = await wake_turn(vad, audio, hit=5)
    assert end.reason is AudioEndReason.MAX_LENGTH
    recorded_ms = len(pcm) // 32 - PREROLL_BLOCKS * 80
    assert 15_000 <= recorded_ms < 15_080


async def listen_turn(vad, samples, timeout_ms):
    async with FakeCore() as core:
        listens: asyncio.Queue = asyncio.Queue()
        client = CoreClient(SatelliteHello(satellite="pc"), "127.0.0.1", core.port,
                            on_event=listen_handler(listens))
        client.start()
        await client.wait_connected(3)
        src = QueueSource()
        loop = asyncio.create_task(
            wake_loop(src, WakeSpotter(Scripted(-1), gate_dbfs=None), client, "pc", vad=vad, listens=listens)
        )
        assert isinstance(await asyncio.wait_for(core.received.get(), 3), SatelliteHello)
        await core.send(ListenRequest(timeout_ms=timeout_ms))
        for _ in range(100):
            if not listens.empty():
                break
            await asyncio.sleep(0.01)
        src.push(samples)
        result = await core.turn()
        await src.close()
        await loop
        await client.stop()
    return result


async def test_listen_com_fala(vad):
    before, _, pcm, end = await listen_turn(vad, np.concatenate([silence(0.5), FALA, silence(2)]), 3000)
    assert before == []  # sem magi-wake na escuta pedida pelo núcleo
    assert end.reason is AudioEndReason.VAD
    assert FALA.astype("<i2").tobytes() in pcm
    assert end.tone.duration_ms > 3500


async def test_listen_sem_fala_devolve_no_speech(vad):
    before, _, pcm, end = await listen_turn(vad, silence(3), 1000)
    assert before == []
    assert end.reason is AudioEndReason.NO_SPEECH
    assert 1000 <= len(pcm) // 32 < 1080 and end.tone.duration_ms == 0


async def test_conexao_caida_abandona_a_gravacao():
    sent = []

    async def send(ev):
        sent.append(ev.type)
        return len(sent) < 3

    class Always:
        def process(self, b):
            return 0.9

        def reset(self):
            pass

    stream = UtteranceStream(send, Endpointer(Always()))
    assert await stream.start()
    assert await stream.feed(b"\0" * CHUNK_BYTES) is None
    end = await stream.feed(b"\0" * CHUNK_BYTES)
    assert end.reason is AudioEndReason.CANCELLED and stream.done
    assert sent == ["audio-start", "audio-chunk", "audio-chunk"]


def test_pre_rolo_guarda_os_ultimos_300ms():
    pr = PreRoll()
    for i in range(10):
        pr.push(bytes([i]))
    assert pr.take() == [bytes([i]) for i in range(10 - PREROLL_BLOCKS, 10)]
    assert pr.take() == []


def test_tom_so_conta_blocos_com_voz():
    meter = ToneMeter()
    loud = (np.ones(CHUNK_SAMPLES) * 3277).astype(np.int16)  # -20 dBFS
    meter.feed(loud, True)
    meter.feed(np.zeros(CHUNK_SAMPLES, np.int16), False)
    tone = meter.result()
    assert tone.duration_ms == 80 and abs(tone.energy_db + 20) < 0.2
    assert ToneMeter().result().duration_ms == 0


def test_silabas_de_hey_jarvis():
    assert count_syllables(read_wav(DATA / "hey_jarvis.wav")) == 3
