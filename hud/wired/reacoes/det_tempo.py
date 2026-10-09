"""Detector `det_tempo` (spec §5): 17–20, 57–62, I1, I2, I16, I17, I19.
Dono: R1.4. Stub de R0.1."""

from __future__ import annotations

from typing import Any

from .contratos import Disparo


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return []
