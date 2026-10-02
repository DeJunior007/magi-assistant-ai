"""Reprodução da fala da Magui no satélite (§5, R12.4, R12.5, R17.2).

O núcleo manda a resposta na mesma conexão Wyoming: ``audio-start`` (formato do TTS),
``audio-chunk``..., ``audio-stop``. O ``Player``:

- toca os chunks conforme chegam pelo PipeWire (``sounddevice``, fluxo ``application.name =
  "magi"`` para não ser abaixado pelo próprio ducking);
- a cada ``MOUTH_INTERVAL_MS`` (50 ms) manda ``magi-mouth`` com o RMS normalizado do trecho que
  o dispositivo consumiu nesse intervalo (o núcleo repassa ao HUD);
- abaixa Spotify e jogo durante a fala (``Ducker``) e restaura ao fim;
- ao terminar de tocar tudo manda ``magi-mouth`` 0 e ``playback-done``;
- ``interrupt()`` (wake word/atalho durante a fala, ou ``magi-stop`` do núcleo) corta o som na
  hora, descarta o resto e NÃO manda ``playback-done`` (contrato de ``EventType``).

O dispositivo fica atrás de ``AudioOutput``; os testes usam um falso (nunca abrem áudio real).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from wyoming.event import Event

from magi.common.contracts import (
    MOUTH_INTERVAL_MS,
    MouthEvent,
    PcmFormat,
    PlaybackDone,
    SatelliteToCore,
    StopPlayback,
)
from magi.common.events import EventDecodeError, from_event
from magi.satellite.capture import APP_NAME, pipewire_alsa_props
from magi.satellite.ducking import Ducker

log = logging.getLogger("magi.satellite.playback")

#: RMS (fração do fundo de escala) que vira boca toda aberta (1,0). Fala de TTS fica ~0,05–0,25.
MOUTH_FULL_RMS = 0.25
#: A cada quantos segundos de fala o ducking é reaplicado (fluxos novos, S1 item 3).
DUCK_REFRESH_S = 1.0

Sender = Callable[[SatelliteToCore], Awaitable[bool]]


def mouth_level(pcm: bytes | bytearray, full_rms: float = MOUTH_FULL_RMS) -> float:
    """RMS de PCM int16 normalizado para 0..1 (``full_rms`` → 1,0). Vazio → 0."""
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    x = np.frombuffer(bytes(pcm[: n * 2]), dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(x * x)))
    return round(min(1.0, rms / full_rms), 4)


class AudioOutput(Protocol):
    """Saída de áudio. ``write`` não bloqueia e pode ser chamado de qualquer thread."""

    def start(self, fmt: PcmFormat) -> None: ...

    def write(self, pcm: bytes) -> None: ...

    def pending(self) -> int:
        """Bytes escritos que o dispositivo ainda não consumiu."""
        ...

    def drain(self) -> None:
        """Bloqueante: espera o dispositivo tocar o que já pegou e fecha."""
        ...

    def abort(self) -> None:
        """Corta já (descarta o que falta) e fecha."""
        ...


class SoundDeviceOutput:
    """``sd.RawOutputStream`` no dispositivo padrão (``pipewire-alsa``, S1), em modo callback.

    O callback do PortAudio puxa de um buffer protegido por lock; falta de dados vira silêncio
    (o TTS chega em fluxo). Abrir por turno custa ~20 ms (S1).
    """

    def __init__(self, device: str | int | None = None, app_name: str = APP_NAME) -> None:
        self.device = device
        self.app_name = app_name
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._stream: Any = None

    def _callback(self, outdata, frames, time_info, status) -> None:  # thread do PortAudio
        n = len(outdata)
        with self._lock:
            chunk = bytes(self._buf[:n])
            del self._buf[:n]
        outdata[: len(chunk)] = chunk
        if len(chunk) < n:
            outdata[len(chunk):] = b"\x00" * (n - len(chunk))

    def start(self, fmt: PcmFormat) -> None:
        if fmt.width != 2:
            raise ValueError(f"formato de TTS não suportado: width={fmt.width} (só int16)")
        # sem target.object: esse é o microfone; a saída vai para o sink padrão
        os.environ["PIPEWIRE_ALSA"] = pipewire_alsa_props(self.app_name)
        try:
            import sounddevice as sd
        except OSError as e:  # PortAudio de sistema ausente (S1)
            raise RuntimeError(
                "PortAudio não encontrado: instale com `sudo dnf install portaudio` (docs/spikes/S1.md)"
            ) from e
        self._stream = sd.RawOutputStream(
            samplerate=fmt.rate,
            channels=fmt.channels,
            dtype="int16",
            blocksize=fmt.rate * 20 // 1000,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def write(self, pcm: bytes) -> None:
        with self._lock:
            self._buf.extend(pcm)

    def pending(self) -> int:
        with self._lock:
            return len(self._buf)

    def drain(self) -> None:
        s, self._stream = self._stream, None
        if s is not None:
            s.stop()  # Pa_StopStream espera o buffer do dispositivo tocar
            s.close()

    def abort(self) -> None:
        with self._lock:
            self._buf.clear()
        s, self._stream = self._stream, None
        if s is not None:
            s.abort()
            s.close()


@dataclass(eq=False)
class _Utterance:
    fmt: PcmFormat
    output: AudioOutput
    unplayed: bytearray = field(default_factory=bytearray)  # cópia do que o dispositivo não consumiu
    ended: bool = False
    started: bool = False
    task: asyncio.Task[None] | None = None


class Player:
    """Toca a resposta do núcleo e fala com ele (``magi-mouth``, ``playback-done``). Ver módulo.

    ``send`` é ``CoreClient.send``. ``ducker`` é opcional (``None`` = sem ducking, ex.: ``--wav``).
    """

    def __init__(
        self,
        send: Sender,
        satellite: str,
        *,
        output_factory: Callable[[], AudioOutput] = SoundDeviceOutput,
        ducker: Ducker | None = None,
        interval_ms: int = MOUTH_INTERVAL_MS,
        full_rms: float = MOUTH_FULL_RMS,
        duck_refresh_s: float = DUCK_REFRESH_S,
    ) -> None:
        self.send = send
        self.satellite = satellite
        self.output_factory = output_factory
        self.ducker = ducker
        self.interval = interval_ms / 1000
        self.full_rms = full_rms
        self.duck_refresh_ticks = max(1, round(duck_refresh_s / self.interval))
        self._utt: _Utterance | None = None
        self._bg: set[asyncio.Task[Any]] = set()

    @property
    def playing(self) -> bool:
        return self._utt is not None

    def _spawn(self, coro: Awaitable[Any], name: str) -> asyncio.Task[Any]:
        t = asyncio.ensure_future(coro)
        t.set_name(name)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)
        return t

    async def handle(self, event: Event) -> bool:
        """Trata um evento do núcleo; ``True`` se era de reprodução (consumido)."""
        if event.type not in ("audio-start", "audio-chunk", "audio-stop", "magi-stop"):
            return False
        try:
            msg = from_event(event)
        except EventDecodeError as e:
            log.debug("evento de áudio inválido: %s", e)
            return True
        if isinstance(msg, StopPlayback):
            self.interrupt()
        elif event.type == "audio-start":
            await self._start(PcmFormat(msg.rate, msg.width, msg.channels))
        elif event.type == "audio-chunk":
            self._chunk(msg)
        else:  # audio-stop
            if self._utt is not None:
                self._utt.ended = True
        return True

    async def _start(self, fmt: PcmFormat) -> None:
        if self._utt is not None:
            log.info("nova fala antes do fim da anterior: corto a anterior")
            self.interrupt()
        utt = _Utterance(fmt, self.output_factory())
        self._utt = utt
        if self.ducker is not None:
            self._spawn(self.ducker.duck(), "duck")
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, utt.output.start, fmt)
        except Exception as e:  # noqa: BLE001 - sem saída de áudio o satélite segue vivo
            log.error("não consegui abrir a saída de áudio: %s", e)
            if self._utt is utt:
                self._utt = None
                self._release(None)
            return
        utt.started = True
        if self._utt is not utt:  # interrompida enquanto abria
            utt.output.abort()
            return
        utt.task = asyncio.create_task(self._monitor(utt), name="playback")

    def _chunk(self, msg: Any) -> None:
        utt = self._utt
        if utt is None:
            return  # sobra de fala interrompida
        if (msg.rate, msg.width, msg.channels) != (utt.fmt.rate, utt.fmt.width, utt.fmt.channels):
            log.warning("chunk com formato diferente do audio-start: ignorado")
            return
        utt.unplayed.extend(msg.audio)
        utt.output.write(msg.audio)

    async def _monitor(self, utt: _Utterance) -> None:
        tick = 0
        while True:
            await asyncio.sleep(self.interval)
            pending = utt.output.pending()
            played = max(0, len(utt.unplayed) - pending)
            level = mouth_level(utt.unplayed[:played], self.full_rms)
            del utt.unplayed[:played]
            await self.send(MouthEvent(level=level, satellite=self.satellite))
            if utt.ended and pending == 0:
                break
            tick += 1
            if self.ducker is not None and tick % self.duck_refresh_ticks == 0:
                self._spawn(self.ducker.duck(), "duck-refresh")
        await asyncio.get_running_loop().run_in_executor(None, utt.output.drain)
        if self._utt is not utt:
            return  # interrompida durante o drain: interrupt() já cuidou de tudo
        self._utt = None
        await self.send(MouthEvent(level=0.0, satellite=self.satellite))
        if self.ducker is not None:
            await self.ducker.restore()
        await self.send(PlaybackDone(satellite=self.satellite))
        log.debug("fala tocada até o fim")

    def _release(self, utt: _Utterance | None) -> None:
        """Fim antecipado: restaura o volume e fecha a boca em segundo plano. O ``restore`` é
        criado antes de qualquer ``duck`` de uma fala seguinte, então roda antes dele."""
        if self.ducker is not None:
            self._spawn(self.ducker.restore(), "duck-restore")
        self._spawn(self._close_mouth(utt), "playback-cleanup")

    async def _close_mouth(self, utt: _Utterance | None) -> None:
        if utt is not None and utt.task is not None:
            utt.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await utt.task
        await self.send(MouthEvent(level=0.0, satellite=self.satellite))

    def interrupt(self) -> bool:
        """Corta a fala agora (R12.5). Sem ``playback-done``. ``True`` se havia fala."""
        utt, self._utt = self._utt, None
        if utt is None:
            return False
        if utt.started:
            try:
                utt.output.abort()
            except Exception as e:  # noqa: BLE001
                log.warning("falha ao cortar a saída de áudio: %s", e)
        log.info("fala interrompida")
        self._release(utt)
        return True

    async def close(self) -> None:
        """Encerra: corta o que estiver tocando e espera restaurar o volume."""
        self.interrupt()
        if self._bg:
            await asyncio.gather(*list(self._bg), return_exceptions=True)
