"""STT assíncrono (spec §5.5) — stub (dono: Y3.6; corpos chamados por ``ayanami.fila``)."""

from __future__ import annotations

from typing import Any

from procrastinate import JobContext

from ayanami.deps import Deps


async def transcrever(deps: Deps, contexto: JobContext, *, tarefa_id: str) -> dict[str, Any] | None:
    """``stt.transcrever``: faster-whisper; áudio apagado no fim (dono: Y3.6)."""
    raise NotImplementedError("transcrever: ainda não implementado (dono: Y3.6)")
