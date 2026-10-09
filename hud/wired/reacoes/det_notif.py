"""Detector `det_notif` (spec §5): cond. E: 46, 47.
Dono: R2.E. Stub de R0.1."""

from __future__ import annotations

from typing import Any

from .contratos import Disparo


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return []
