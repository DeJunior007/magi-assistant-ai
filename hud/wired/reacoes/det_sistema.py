"""Detector `det_sistema` (spec §5): 34–42, 44, 45, 48, 80, 84, I4–I6.
Dono: R1.3. Stub de R0.1."""

from __future__ import annotations

from typing import Any

from .contratos import Disparo


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return []
