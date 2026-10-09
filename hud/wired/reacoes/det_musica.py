"""Detector `det_musica` (spec §5): 24–30, 32, 33, 78, 81, 83, 85, 89, I3, I7–I15.
Dono: R1.2. Stub de R0.1."""

from __future__ import annotations

from typing import Any

from .contratos import Disparo


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return []
