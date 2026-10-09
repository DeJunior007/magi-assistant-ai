"""Governador (spec §3): cotas, cooldown, prioridade, fila, bloqueios, blush/lágrima, Ado e as
desligadas do Pedro. Puro, relógio injetado. Dono: R0.2. Stub de R0.1."""

from __future__ import annotations

from .contratos import Def, Disparo, Passo


def escolher(disparos: list[Disparo], agora: float, ctx: dict) -> Def | None:
    """No máximo 1 reação aprovada neste tick (ou a que estava na fila)."""
    return None


def aplicar_bloqueios(d: Def, ctx: dict) -> tuple[Passo, ...]:
    """Passos de ``d`` com os bloqueios aplicados (C8/C11 -> C9; tira ``tear`` fora de hora)."""
    return d.passos
