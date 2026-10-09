"""Detector `det_extras` (spec §5): cond. fan: 43 · restart: 50 · capturas: 51 · datas: 63 · P13: I20.
Dono: R2.G. Stub de R0.1."""

from __future__ import annotations

from typing import Any

from .contratos import Disparo


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return []
