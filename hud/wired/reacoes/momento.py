"""Momento da Condessa (spec §3, acordo §3). Dono: V0.3 (esqueleto: V0.1).

Função pura ``decidir`` com prioridade e histerese, e os ``filtros`` por cima.
"""

from __future__ import annotations

from .vida import Filtro, Momento

GRUPOS: dict[Momento, tuple[str, ...]] = {}  # V0.3: grupos de passivas por momento (acordo §3)
MEDIA_MIN: dict[Momento, float] = {}  # V0.3: do [vida.passiva_media_min]


def decidir(ctx: dict, anterior: Momento | None, agora: float) -> Momento:
    """Momento pela prioridade da tabela; troca só depois de ``momento_estavel_s`` estável."""
    raise NotImplementedError


def filtros(ctx: dict) -> set[Filtro]:
    """Madrugada (22h–04h) e Pedro mal (humor do Pedro 0–1 do núcleo)."""
    raise NotImplementedError
