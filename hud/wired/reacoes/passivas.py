"""Passivas (spec §5): 1–4, 6–14, 16, 21, 22, 23, sorteadas pelo humor. Dono: R1.1. Stub de R0.1."""

from __future__ import annotations

import random

from .contratos import Disparo


def sortear(ctx: dict, agora: float, rng: random.Random) -> Disparo | None:
    """A cada 10 s pode devolver 1 disparo passivo, pesado por ``humor.fatores(ctx)``."""
    return None
