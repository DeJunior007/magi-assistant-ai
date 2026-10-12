"""Relógio injetável da Ayanami (dono: Y0.2).

Todo código com horário, espera ou prazo recebe um :class:`Relogio`; os testes usam
:class:`RelogioFalso` (nada de ``sleep`` real).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Relogio(Protocol):
    def agora(self) -> datetime:
        """Data e hora atual, com fuso (UTC)."""
        ...

    def monotonico(self) -> float:
        """Segundos de um relógio que só anda para frente (para prazos e intervalos)."""
        ...

    async def dormir(self, segundos: float) -> None:
        """Espera ``segundos`` (no falso, só avança o tempo)."""
        ...


class RelogioReal:
    def agora(self) -> datetime:
        return datetime.now(UTC)

    def monotonico(self) -> float:
        return time.monotonic()

    async def dormir(self, segundos: float) -> None:
        await asyncio.sleep(max(0.0, segundos))


class RelogioFalso:
    """Relógio de teste: parado até alguém chamar :meth:`avancar` ou :meth:`dormir`."""

    def __init__(self, inicio: datetime | None = None, monotonico: float = 1000.0) -> None:
        inicio = inicio or datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        if inicio.tzinfo is None:
            raise ValueError("RelogioFalso: inicio precisa de fuso")
        self._agora = inicio
        self._mono = monotonico
        self.dormidas: list[float] = []

    def agora(self) -> datetime:
        return self._agora

    def monotonico(self) -> float:
        return self._mono

    def avancar(self, segundos: float) -> None:
        if segundos < 0:
            raise ValueError("RelogioFalso: não anda para trás")
        self._agora += timedelta(seconds=segundos)
        self._mono += segundos

    async def dormir(self, segundos: float) -> None:
        segundos = max(0.0, segundos)
        self.dormidas.append(segundos)
        self.avancar(segundos)
        await asyncio.sleep(0)
