"""Web Push (spec §15) — stub (dono: P2.1; corpos chamados por ``ayanami.fila``)."""

from __future__ import annotations

from typing import Any

from procrastinate import JobContext

from ayanami.deps import Deps


async def enviar(deps: Deps, contexto: JobContext, *, evento_id: int) -> dict[str, Any] | None:
    """``push.enviar``: manda o evento aos celulares assinantes (dono: P2.1)."""
    raise NotImplementedError("enviar: ainda não implementado (dono: P2.1)")
