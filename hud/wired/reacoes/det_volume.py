"""Detector `det_volume` (spec §5): cond. D: 31 e a variante de pico do 26.
Dono: R2.D. Stub de R0.1."""

from __future__ import annotations

from typing import Any

from .contratos import Disparo


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return []
