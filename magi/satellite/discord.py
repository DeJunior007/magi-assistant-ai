"""Detecção de call do Discord no satélite (§3.2, R2.1, R2.2).

A cada ``POLL_S`` segundos lista os ``source-output``s do PipeWire (``pulsectl``, numa thread
própria para não bloquear o laço) e procura um fluxo de captura do Discord ativo (não ``corked``).
Em call, desliga o "Ei Magui" (``WakeSpotter.enabled = False``) e manda
``SatelliteStatus(in_call=True, wake_enabled=False)`` ao núcleo; ao sair, religa e manda o status.
Histerese: o estado só muda depois de ``confirm`` leituras iguais seguidas (2 × 2 s ≤ 5 s, R2.2).
Erro do ``pulsectl`` não derruba o satélite: a leitura é ignorada e a conexão é refeita na próxima.

Aqui só se LÊ o PipeWire. O mudo do Discord no atalho (R2.3, R2.4) é a tarefa 5.2 e usa
``find_discord_source_outputs``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

from magi.common.contracts import SatelliteStatus, SatelliteToCore
from magi.satellite.wake import WakeSpotter

log = logging.getLogger("magi.satellite.discord")

POLL_S = 2.0
CONFIRM_READS = 2

#: Trechos de ``application.process.binary`` (minúsculos) que identificam o Discord e clientes dele.
DISCORD_BINARIES = ("discord", "vesktop", "webcord")
#: ``application.name`` da captura de voz da call no Discord (S1).
DISCORD_VOICE_NAME = "WEBRTC VoiceEngine"
#: ``application.name`` da captura de compartilhamento de tela: sozinha não indica call (S1).
DISCORD_SCREEN_CAPTURE_NAME = "discord_capture"
DISCORD_FLATPAK_ID = "com.discordapp.Discord"


class PulseLike(Protocol):
    """O pedaço de ``pulsectl.Pulse`` usado aqui (o falso dos testes implementa só isto)."""

    def source_output_list(self) -> list[Any]: ...

    def close(self) -> None: ...


def is_discord_source_output(so: Any) -> bool:
    """``True`` se o ``source-output`` é do Discord (qualquer captura dele, inclusive tela)."""
    props = getattr(so, "proplist", None) or {}
    binary = str(props.get("application.process.binary", "")).lower()
    if any(b in binary for b in DISCORD_BINARIES):
        return True
    if props.get("application.name") == DISCORD_VOICE_NAME:
        return True
    return props.get("pipewire.access.portal.app_id") == DISCORD_FLATPAK_ID


def find_discord_source_outputs(pulse: PulseLike) -> list[Any]:
    """Todos os ``source-output``s do Discord, em pausa ou não (a 5.2 muta todos eles)."""
    return [so for so in pulse.source_output_list() if is_discord_source_output(so)]


def call_active(outputs: Iterable[Any]) -> bool:
    """Há call: alguma captura do Discord ativa (não ``corked``) que não seja só a de tela."""
    for so in outputs:
        props = getattr(so, "proplist", None) or {}
        if getattr(so, "corked", False):
            continue
        if props.get("application.name") == DISCORD_SCREEN_CAPTURE_NAME:
            continue
        return True
    return False


def _default_pulse() -> PulseLike:
    import pulsectl

    return pulsectl.Pulse("magi-satellite-discord")


Sender = Callable[[SatelliteToCore], Awaitable[bool]]


class DiscordCallMonitor:
    """Liga/desliga o wake word conforme a call do Discord e avisa o núcleo (R2.1, R2.2).

    ``send`` é ``CoreClient.send``; se o envio falhar (sem conexão), o status é reenviado na
    próxima leitura até chegar. ``pulse_factory`` cria a conexão ``pulsectl`` (testes: falso).
    """

    def __init__(
        self,
        spotter: WakeSpotter,
        send: Sender,
        satellite: str,
        *,
        pulse_factory: Callable[[], PulseLike] = _default_pulse,
        poll_s: float = POLL_S,
        confirm: int = CONFIRM_READS,
    ) -> None:
        self.spotter = spotter
        self.send = send
        self.satellite = satellite
        self.pulse_factory = pulse_factory
        self.poll_s = poll_s
        self.confirm = max(1, confirm)
        self.in_call = False
        self._candidate: bool | None = None
        self._streak = 0
        self._pending: SatelliteStatus | None = None
        self._pulse: PulseLike | None = None
        self._failing = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="magi-discord")

    # --- leitura (thread do executor; a conexão pulsectl fica sempre na mesma thread) ---

    def _read_blocking(self) -> bool:
        if self._pulse is None:
            self._pulse = self.pulse_factory()
        try:
            return call_active(find_discord_source_outputs(self._pulse))
        except Exception:
            self._close_blocking()
            raise

    def _close_blocking(self) -> None:
        p, self._pulse = self._pulse, None
        if p is not None:
            try:
                p.close()
            except Exception:  # noqa: BLE001 - fechar nunca derruba o satélite
                pass

    async def read(self) -> bool | None:
        """Uma leitura; ``None`` se o ``pulsectl`` falhou (estado fica como está)."""
        loop = asyncio.get_running_loop()
        try:
            active = await loop.run_in_executor(self._executor, self._read_blocking)
        except Exception as e:  # noqa: BLE001 - qualquer erro do PipeWire vira "sem leitura"
            if not self._failing:
                log.warning("não consegui ler os fluxos do PipeWire (%s); tento de novo", e)
            self._failing = True
            return None
        if self._failing:
            log.info("leitura do PipeWire voltou")
        self._failing = False
        return active

    # --- decisão ---

    async def step(self) -> None:
        """Lê uma vez, aplica a histerese e, se mudou, alterna o wake word e avisa o núcleo."""
        active = await self.read()
        if active is not None:
            if active == self.in_call:
                self._candidate, self._streak = None, 0
            elif active == self._candidate:
                self._streak += 1
            else:
                self._candidate, self._streak = active, 1
            if self._candidate is not None and self._streak >= self.confirm:
                self._candidate, self._streak = None, 0
                self._set_in_call(active)
        if self._pending is not None and await self.send(self._pending):
            self._pending = None

    def _set_in_call(self, in_call: bool) -> None:
        self.in_call = in_call
        if not in_call:
            self.spotter.detector.reset()  # não reaproveita áudio de antes da call
        self.spotter.enabled = not in_call
        log.info("call do Discord %s: wake word %s", "começou" if in_call else "acabou",
                 "desligado" if in_call else "religado")
        self._pending = SatelliteStatus(satellite=self.satellite, in_call=in_call,
                                        wake_enabled=not in_call)

    async def run(self) -> None:
        """Laço de verificação; termina quando a tarefa é cancelada."""
        try:
            while True:
                await self.step()
                await asyncio.sleep(self.poll_s)
        finally:
            await self.close()

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._executor, self._close_blocking)
        finally:
            self._executor.shutdown(wait=False)
