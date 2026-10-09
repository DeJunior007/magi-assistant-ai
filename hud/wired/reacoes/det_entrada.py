"""Detector `det_entrada` (spec §5): 5, 64, 66 · cond. A: 15, 65, 67, 69, 70, 77.
Dono: R1.5 (cond. A: R2.A). Stub de R0.1."""

from __future__ import annotations

from typing import Any

from .contratos import Disparo


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return []
