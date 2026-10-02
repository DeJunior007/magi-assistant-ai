"""Envio da fala ao núcleo após a ativação (§5, R1.5, R13.3).

Sequência: ``audio-start``, os ~300 ms anteriores à ativação (``PreRoll``), um ``audio-chunk``
por bloco de 80 ms assim que é capturado, e ``audio-stop`` (``AudioEnd``) com ``reason`` e
``ToneMetadata`` (energia em dBFS e taxa de fala estimada nos blocos com voz).
"""

from __future__ import annotations

import logging
import math
from collections import deque
from collections.abc import Awaitable, Callable, Iterable

import numpy as np
from wyoming.event import Event

from magi.common.contracts import (
    AUDIO_RATE,
    CAPTURE_FORMAT,
    CHUNK_MS,
    AudioEnd,
    AudioEndReason,
    PcmFormat,
    ToneMetadata,
)
from magi.common.events import audio_chunk, audio_start, to_event
from magi.satellite.vad import Endpointer

log = logging.getLogger("magi.satellite.stream")

#: Áudio anterior à ativação incluído no envio, para não cortar o começo da fala.
PREROLL_MS = 300
PREROLL_BLOCKS = math.ceil(PREROLL_MS / CHUNK_MS)  # 4 blocos = 320 ms

#: Envelope para a taxa de fala: quadros de 10 ms, picos (núcleos silábicos) a ≥ 120 ms.
_FRAME = AUDIO_RATE // 100
_MIN_PEAK_GAP = 12
_PEAK_PROMINENCE_DB = 4.0

SendEvent = Callable[[Event], Awaitable[bool]]


class PreRoll:
    """Guarda os últimos blocos antes da ativação (custo: um ``deque`` de 4 referências)."""

    def __init__(self, blocks: int = PREROLL_BLOCKS) -> None:
        self._buf: deque[bytes] = deque(maxlen=blocks)

    def push(self, block: bytes) -> None:
        self._buf.append(block)

    def take(self) -> list[bytes]:
        out = list(self._buf)
        self._buf.clear()
        return out


def _dbfs(power: float) -> float:
    return 10.0 * math.log10(power) if power > 1e-12 else -120.0


def count_syllables(pcm: np.ndarray) -> int:
    """Estima sílabas contando picos do envelope de energia (quadros de 10 ms, suavizado em 50 ms)."""
    n = len(pcm) // _FRAME
    if n < 3:
        return 0
    x = pcm[: n * _FRAME].astype(np.float32).reshape(n, _FRAME) / 32768.0
    env = 10.0 * np.log10(np.maximum((x * x).mean(axis=1), 1e-12))
    env = np.convolve(env, np.ones(5) / 5, mode="same")
    floor = float(np.median(env)) - 6.0
    count = 0
    last = -_MIN_PEAK_GAP
    for i in range(1, n - 1):
        v = env[i]
        if v < floor or v < env[i - 1] or v < env[i + 1] or i - last < _MIN_PEAK_GAP:
            continue
        lo = max(0, i - _MIN_PEAK_GAP)
        hi = min(n, i + _MIN_PEAK_GAP + 1)
        if v - env[lo:i].min() >= _PEAK_PROMINENCE_DB or v - env[i + 1 : hi].min() >= _PEAK_PROMINENCE_DB:
            count += 1
            last = i
    return count


class ToneMeter:
    """Acumula os blocos com voz do turno e calcula ``ToneMetadata`` (R13.3). Só números saem."""

    def __init__(self, block_ms: int = CHUNK_MS) -> None:
        self.block_ms = block_ms
        self._voiced: list[np.ndarray] = []

    def feed(self, block: bytes | np.ndarray, voiced: bool) -> None:
        if voiced:
            pcm = np.frombuffer(block, dtype="<i2") if isinstance(block, bytes | bytearray) else block
            self._voiced.append(pcm)

    def result(self) -> ToneMetadata:
        if not self._voiced:
            return ToneMetadata(energy_db=-120.0, speech_rate=0.0, duration_ms=0)
        pcm = np.concatenate(self._voiced)
        x = pcm.astype(np.float32) / 32768.0
        energy = _dbfs(float(np.dot(x, x)) / len(x))
        duration_ms = len(self._voiced) * self.block_ms
        rate = count_syllables(pcm) / (duration_ms / 1000)
        return ToneMetadata(energy_db=round(energy, 1), speech_rate=round(rate, 2), duration_ms=duration_ms)


class UtteranceStream:
    """Uma gravação enviada ao núcleo: ``start()``, ``feed()`` por bloco, até devolver o ``AudioEnd``.

    ``send`` manda um ``Event`` e devolve ``False`` sem conexão; nesse caso a gravação é
    abandonada (``reason=cancelled``, nada mais é enviado). ``finish()`` encerra por fora
    (ex.: atalho solto, ``ptt_release``). Timestamps em ms desde o início do áudio enviado.
    """

    def __init__(
        self,
        send: SendEvent,
        endpointer: Endpointer,
        *,
        preroll: Iterable[bytes] = (),
        fmt: PcmFormat = CAPTURE_FORMAT,
    ) -> None:
        self.send = send
        self.endpointer = endpointer
        self.fmt = fmt
        self.tone = ToneMeter()
        self._preroll = list(preroll)
        self._sent_ms = 0
        self.end: AudioEnd | None = None

    @property
    def done(self) -> bool:
        return self.end is not None

    def _ms(self, block: bytes) -> int:
        return len(block) * 1000 // (self.fmt.rate * self.fmt.width * self.fmt.channels)

    async def _chunk(self, block: bytes) -> bool:
        ok = await self.send(audio_chunk(block, self.fmt, timestamp=self._sent_ms))
        self._sent_ms += self._ms(block)
        return ok

    def _abort(self) -> AudioEnd:
        log.warning("gravação abandonada: sem conexão com o núcleo")
        self.end = AudioEnd(timestamp=self._sent_ms, reason=AudioEndReason.CANCELLED)
        return self.end

    async def start(self) -> bool:
        """Manda ``audio-start`` e o pré-rolo. ``False`` se a conexão caiu."""
        if not await self.send(audio_start(self.fmt, timestamp=0)):
            self._abort()
            return False
        for b in self._preroll:
            if not await self._chunk(b):
                self._abort()
                return False
        self._preroll.clear()
        return True

    async def feed(self, block: bytes) -> AudioEnd | None:
        """Envia o bloco e consulta o VAD; devolve o ``AudioEnd`` (já enviado) quando acaba."""
        if self.end is not None:
            return self.end
        reason = self.endpointer.feed(block)
        self.tone.feed(block, self.endpointer.voiced)
        if not await self._chunk(block):
            return self._abort()
        if reason is not None:
            return await self.finish(reason)
        return None

    async def finish(self, reason: AudioEndReason) -> AudioEnd:
        """Encerra com ``audio-stop`` (``reason`` + tom). Idempotente."""
        if self.end is not None:
            return self.end
        self.end = AudioEnd(timestamp=self._sent_ms, reason=reason, tone=self.tone.result())
        if not await self.send(to_event(self.end)):
            log.warning("audio-stop não enviado: sem conexão com o núcleo")
        log.info("fim da gravação: %s (%d ms, %s)", reason.value, self._sent_ms, self.end.tone)
        return self.end
