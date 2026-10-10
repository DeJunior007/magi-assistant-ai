"""Rosto de repouso (spec §4, acordo §2, §3, §5). Dono: V0.4 (esqueleto: V0.1)."""

from __future__ import annotations

from .estado import Postura
from .vida import Faixa, Filtro, Momento, Repouso


def rosto(momento: Momento, faixa: Faixa, filtros: set[Filtro], postura: Postura, ctx: dict) -> Repouso:
    """O rosto parado pela tabela de faixas, fone, energia, música e episódio de jogo."""
    raise NotImplementedError
