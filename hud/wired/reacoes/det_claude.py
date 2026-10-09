"""Detector `det_claude` (spec §5): 52, 53, 56, 75, 82, 90 · cond. C: 54, 55.
Dono: R1.5 (cond. C: R2.C). Stub de R0.1."""

from __future__ import annotations

from typing import Any

from .contratos import Disparo


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return []
