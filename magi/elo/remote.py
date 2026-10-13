"""``RemoteLink``: o celular como satélite do núcleo pela Ayanami (spec §6.3, design §7.2; R8.1).

Segundo implementador de ``SatelliteLink`` (o primeiro é o ``WyomingLink``). Em vez de Wyoming,
fala por quadros binários do elo (§1.4) na WS do PC:

- ``AUDIO_IN`` do turno atual → ``entrada()`` (PCM 16 kHz; fila de até 400 quadros = 32 s, o
  excedente é descartado com log) até o ``AUDIO_FIM``;
- ``play`` → ``AUDIO_OUT`` em PCM 24 kHz mono (outro formato é reamostrado) + ``AUDIO_FIM``. O
  celular não manda ``playback-done``: o link o injeta no ``TurnMachine`` ao fim (S6);
- ``send``: ``StopPlayback`` → ``AUDIO_FIM``; ``ListenRequest`` e o resto são ignorados (não há
  escuta aberta pela WS).

Sem turno ativo (``turno == ""``) a saída é descartada: nada vai ao celular fora de um ``Turno``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any, Final

import numpy as np

from magi.common.contracts import (
    CoreToSatellite,
    PcmFormat,
    PlaybackDone,
    SatelliteHello,
    StopPlayback,
)
from magi.elo.cliente import ConexaoFechada
from magi.elo.quadros import Quadro, QuadroTipo

log = logging.getLogger(__name__)

SATELITE: Final = "celular"
ENTRADA_FMT: Final = PcmFormat(rate=16_000, width=2, channels=1)
SAIDA_FMT: Final = PcmFormat(rate=24_000, width=2, channels=1)
QUADRO_MS: Final = 80
MAX_QUADROS_ENTRADA: Final = 400  # 32 s de áudio de 80 ms
_QUADRO_SAIDA: Final = SAIDA_FMT.bytes_for_ms(QUADRO_MS)  # 3840 bytes


class Reamostrador:
    """PCM s16le de qualquer taxa/canais → 24 kHz mono, por blocos, sem emenda entre blocos
    (interpolação linear com estado: posição fracionária e última amostra)."""

    def __init__(self, fmt: PcmFormat, rate: int = SAIDA_FMT.rate) -> None:
        if fmt.width != 2:
            raise ValueError(f"só PCM de 16 bits (largura {fmt.width})")
        self.fmt = fmt
        self.passo = fmt.rate / rate  # avanço na entrada por amostra de saída
        self._pos = 0.0  # posição da próxima saída, relativa a ``_prev``
        self._prev: np.ndarray = np.zeros(0, dtype=np.float32)
        self._resto = b""

    def __call__(self, bloco: bytes) -> bytes:
        dado = self._resto + bloco
        quadro = 2 * self.fmt.channels
        corte = len(dado) - len(dado) % quadro
        dado, self._resto = dado[:corte], dado[corte:]
        x = np.frombuffer(dado, dtype="<i2").astype(np.float32)
        if self.fmt.channels > 1:
            x = x.reshape(-1, self.fmt.channels).mean(axis=1)
        x = np.concatenate([self._prev, x])
        if len(x) < 2:
            self._prev = x
            return b""
        n = int(np.floor((len(x) - 1 - self._pos) / self.passo)) + 1
        if n <= 0:
            self._prev = x
            return b""
        idx = self._pos + self.passo * np.arange(n)
        y = np.interp(idx, np.arange(len(x)), x)
        prox = self._pos + self.passo * n
        base = int(np.floor(prox))
        base = min(base, len(x) - 1)
        self._prev = x[base:]
        self._pos = prox - base
        return np.clip(np.rint(y), -32768, 32767).astype("<i2").tobytes()


class RemoteLink:
    """``SatelliteLink`` do celular. Um por ``TurnMachine``; ``novo_turno`` troca o turno ativo."""

    def __init__(self, cliente: Any, turno: str = "") -> None:
        self.hello = SatelliteHello(SATELITE, name="Celular", capabilities=("ptt", "playback"))
        self.cliente = cliente  # ``EloCliente`` (só ``enviar_quadro``)
        self.machine: Any = None  # ``TurnMachine``; recebe o ``PlaybackDone`` injetado
        self.turno = ""
        self.quadros_out = 0  # ``AUDIO_OUT`` mandados no turno atual
        self._fila: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._na_fila = 0
        self._descartados = 0
        self._tarefas: set[asyncio.Task[None]] = set()
        self.novo_turno(turno)

    # --- entrada --------------------------------------------------------------------------------

    def novo_turno(self, turno: str) -> None:
        """Começa um turno (ou ``""`` = nenhum): fila de entrada e contadores zerados."""
        self.turno = turno
        self.quadros_out = 0
        self._fila = asyncio.Queue()
        self._na_fila = 0
        self._descartados = 0

    def receber_quadro(self, q: Quadro) -> None:
        """Quadro vindo da Ayanami. De outro turno: ignorado."""
        if not self.turno or q.turno != self.turno:
            return
        if q.tipo is QuadroTipo.AUDIO_FIM:
            self._fila.put_nowait(None)
        elif q.tipo is QuadroTipo.AUDIO_IN:
            if self._na_fila >= MAX_QUADROS_ENTRADA:
                if not self._descartados:
                    log.warning("celular: mais de %d quadros no turno; resto descartado",
                                MAX_QUADROS_ENTRADA)
                self._descartados += 1
                return
            self._na_fila += 1
            self._fila.put_nowait(q.pcm)

    async def entrada(self) -> AsyncIterator[bytes]:
        """PCM dos ``AUDIO_IN`` do turno atual, na ordem, até o ``AUDIO_FIM``."""
        fila = self._fila
        while (pcm := await fila.get()) is not None:
            yield pcm

    # --- saída (SatelliteLink) ------------------------------------------------------------------

    async def send(self, msg: CoreToSatellite) -> None:
        if isinstance(msg, StopPlayback):
            await self._quadro(QuadroTipo.AUDIO_FIM)

    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
        conv = None if fmt == SAIDA_FMT else Reamostrador(fmt)
        buf = b""
        try:
            async for bloco in audio:
                buf += conv(bloco) if conv is not None else bloco
                while len(buf) >= _QUADRO_SAIDA:
                    await self._quadro(QuadroTipo.AUDIO_OUT, buf[:_QUADRO_SAIDA])
                    buf = buf[_QUADRO_SAIDA:]
            if len(buf) >= 2:
                await self._quadro(QuadroTipo.AUDIO_OUT, buf[: len(buf) - len(buf) % 2])
            await self._quadro(QuadroTipo.AUDIO_FIM)
        finally:
            self._playback_done()

    async def _quadro(self, tipo: QuadroTipo, pcm: bytes = b"") -> None:
        if not self.turno:
            return  # fora de um Turno: nada vai ao celular
        try:
            await self.cliente.enviar_quadro(Quadro(tipo, self.turno, pcm))
        except ConexaoFechada:
            log.info("celular: WS da Ayanami fora; quadro %s perdido", tipo.name)
            return
        if tipo is QuadroTipo.AUDIO_OUT:
            self.quadros_out += 1

    def _playback_done(self) -> None:
        """O celular não confirma o fim da reprodução: injeta ``PlaybackDone`` (senão o turno fica
        em ``speaking``)."""
        machine = self.machine
        if machine is None:
            return
        t = asyncio.get_running_loop().create_task(machine.handle(PlaybackDone(SATELITE)))
        self._tarefas.add(t)
        t.add_done_callback(self._tarefas.discard)
