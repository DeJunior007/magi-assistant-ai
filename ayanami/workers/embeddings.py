"""Embeddings em lote (spec §5.6; só com [embeddings] ligado) — stub
(dono: Y3.6; corpos chamados por ``ayanami.fila``)."""

from __future__ import annotations

from typing import Any

from procrastinate import JobContext

from ayanami.deps import Deps


async def lote(deps: Deps, contexto: JobContext, *, tarefa_id: str | None = None) -> dict[str, Any] | None:
    """``embeddings.lote`` (dono: Y3.6)."""
    raise NotImplementedError("lote: ainda não implementado (dono: Y3.6)")
