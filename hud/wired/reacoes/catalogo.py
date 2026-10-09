"""Catálogo das 110 reações (90 da planilha + I1–I20): só dados, sem lógica. Dono: R0.4. Stub de R0.1.

``DEFS``: todas, por chave. ``ATIVAS``: só as sem sinal pendente e não substituídas (R8).
"""

from __future__ import annotations

from .contratos import Def

DEFS: dict[str, Def] = {}
ATIVAS: frozenset[str] = frozenset()
