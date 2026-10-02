"""Captura de áudio do satélite: 16 kHz mono PCM16 em blocos de 80 ms (§5, R1.1).

Fontes de áudio (todas são iteradores assíncronos de blocos de ``CHUNK_BYTES`` bytes):

- ``MicSource``: microfone pelo PortAudio/PipeWire (decisão do spike S1). ``sounddevice`` só é
  importado ao abrir o stream, porque precisa da biblioteca de sistema ``portaudio``.
- ``ArraySource``: PCM em memória (testes, medição de CPU).
- ``WavSource``: arquivo WAV (testes com áudio gravado, ``--wav`` na linha de comando).

``ArraySource``/``WavSource`` podem entregar em tempo real (um bloco a cada 80 ms) ou o mais
rápido possível.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

import numpy as np

from magi.common.contracts import AUDIO_RATE, CHUNK_BYTES, CHUNK_MS, CHUNK_SAMPLES

log = logging.getLogger(__name__)

#: Nome dos nossos fluxos no PipeWire (S1): permite achá-los no pulsectl e não "duckar" a Magui.
APP_NAME = "magi"


class AudioSource(Protocol):
    """Fonte de blocos de 80 ms (``CHUNK_BYTES`` bytes de PCM16 mono 16 kHz)."""

    def blocks(self) -> AsyncIterator[bytes]: ...

    async def close(self) -> None: ...


def to_pcm16(samples: np.ndarray) -> np.ndarray:
    """Converte float (-1..1) ou inteiros para ``int16`` mono."""
    a = np.asarray(samples)
    if a.ndim == 2:
        a = a.mean(axis=1)
    if np.issubdtype(a.dtype, np.floating):
        return (np.clip(a, -1.0, 1.0) * 32767.0).astype(np.int16)
    return a.astype(np.int16)


def resample(samples: np.ndarray, src_rate: int, dst_rate: int = AUDIO_RATE) -> np.ndarray:
    """Reamostra PCM16 mono (polifásico). Usado só por arquivos fora de 16 kHz."""
    if src_rate == dst_rate:
        return samples
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(src_rate, dst_rate)
    out = resample_poly(samples.astype(np.float32), dst_rate // g, src_rate // g)
    return np.clip(out, -32768, 32767).astype(np.int16)


def read_wav(path: str | os.PathLike[str]) -> np.ndarray:
    """Lê um WAV PCM16 (qualquer taxa, mono ou estéreo) e devolve ``int16`` mono 16 kHz."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path}: só WAV de 16 bits (largura {w.getsampwidth()})")
        rate, channels = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return resample(data, rate)


def write_wav(path: str | os.PathLike[str], samples: np.ndarray, rate: int = AUDIO_RATE) -> None:
    """Grava PCM16 mono (ferramenta de teste/depuração)."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(to_pcm16(samples).astype("<i2").tobytes())


def iter_blocks(samples: np.ndarray) -> list[bytes]:
    """Divide PCM16 em blocos de ``CHUNK_SAMPLES``; o último é completado com silêncio."""
    pcm = to_pcm16(samples)
    pad = (-len(pcm)) % CHUNK_SAMPLES
    if pad:
        pcm = np.concatenate([pcm, np.zeros(pad, np.int16)])
    raw = pcm.astype("<i2").tobytes()
    return [raw[i : i + CHUNK_BYTES] for i in range(0, len(raw), CHUNK_BYTES)]


class ArraySource:
    """Entrega PCM em memória em blocos de 80 ms.

    ``realtime=True`` espaça os blocos em 80 ms (relógio monotônico, sem deriva).
    ``loop=True`` repete o áudio para sempre (medição de CPU).
    """

    def __init__(self, samples: np.ndarray, *, realtime: bool = False, loop: bool = False) -> None:
        self._blocks = iter_blocks(samples)
        self.realtime = realtime
        self.loop = loop
        self._closed = False

    async def blocks(self) -> AsyncIterator[bytes]:
        period = CHUNK_MS / 1000
        start = time.monotonic()
        n = 0
        while not self._closed:
            for b in self._blocks:
                if self._closed:
                    return
                if self.realtime:
                    # o bloco n só "existe" depois de capturado: fim do bloco = (n+1) * 80 ms
                    delay = start + (n + 1) * period - time.monotonic()
                    if delay > 0:
                        await asyncio.sleep(delay)
                else:
                    await asyncio.sleep(0)
                n += 1
                yield b
            if not self.loop:
                return

    async def close(self) -> None:
        self._closed = True


class WavSource(ArraySource):
    """``ArraySource`` lido de um arquivo WAV (convertido para 16 kHz mono)."""

    def __init__(self, path: str | os.PathLike[str], *, realtime: bool = False, loop: bool = False) -> None:
        self.path = Path(path)
        super().__init__(read_wav(self.path), realtime=realtime, loop=loop)


def pipewire_alsa_props(app_name: str = APP_NAME, target: str | None = None) -> str:
    """Valor de ``PIPEWIRE_ALSA`` (S1): nome do fluxo, papel e, opcionalmente, o source a usar."""
    props = [f'application.name = "{app_name}"', 'media.role = "Assistant"']
    if target:
        props.append(f'target.object = "{target}"')
    return "{ " + " ".join(props) + " }"


class MicSource:
    """Microfone padrão do sistema (ou ``target``, nome de um source do PipeWire), via PortAudio.

    O callback do PortAudio roda numa thread própria; os blocos passam para o loop asyncio por
    uma fila. Se o consumidor atrasar, os blocos mais antigos são descartados (não acumulamos
    atraso no wake word).
    """

    def __init__(
        self,
        *,
        target: str | None = None,
        device: str | int | None = None,
        app_name: str = APP_NAME,
        max_queue: int = 25,
    ) -> None:
        self.target = target
        self.device = device
        self.app_name = app_name
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=max_queue)
        self._stream = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.overflows = 0
        self.dropped = 0

    def _push(self, data: bytes | None) -> None:
        if self._queue.full():
            self.dropped += 1
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._queue.put_nowait(data)

    def _callback(self, indata, frames, time_info, status) -> None:  # thread do PortAudio
        if status and status.input_overflow:
            self.overflows += 1
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self._push, bytes(indata))

    def start(self) -> None:
        # Precisa estar no ambiente antes de abrir o stream (o plugin ALSA do PipeWire lê ao abrir).
        os.environ["PIPEWIRE_ALSA"] = pipewire_alsa_props(self.app_name, self.target)
        try:
            import sounddevice as sd
        except OSError as e:  # PortAudio de sistema ausente (S1)
            raise RuntimeError(
                "PortAudio não encontrado: instale com `sudo dnf install portaudio` (docs/spikes/S1.md)"
            ) from e
        self._loop = asyncio.get_running_loop()
        self._stream = sd.RawInputStream(
            samplerate=AUDIO_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK_SAMPLES,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()
        log.info("microfone aberto (%s)", self.target or "padrão do sistema")

    async def blocks(self) -> AsyncIterator[bytes]:
        if self._stream is None:
            self.start()
        while True:
            b = await self._queue.get()
            if b is None:
                return
            yield b

    async def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._push(None)  # acorda quem espera em blocks()
