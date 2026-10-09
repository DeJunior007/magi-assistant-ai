"""Detector `det_conversa` (spec §5): 71–73, 79, I18 · cond. B: 74, 76, 86, 87 · cond. F: 88.
Dono: R1.5 (cond. B: R2.B; cond. F: R2.F). Stub de R0.1."""

from __future__ import annotations

from typing import Any

from .contratos import Disparo


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return []
