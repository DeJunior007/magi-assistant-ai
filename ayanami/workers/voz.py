"""Cache de frases Kokoro (spec §5.4) — stub (dono: Y3.5; corpos chamados por ``ayanami.fila``)."""

from __future__ import annotations

from typing import Any

from procrastinate import JobContext

from ayanami.deps import Deps


async def cache_frases(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``voz.cache_frases`` (dono: Y3.5)."""
    raise NotImplementedError("cache_frases: ainda não implementado (dono: Y3.5)")
