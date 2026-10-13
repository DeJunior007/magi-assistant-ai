"""Notícias na nuvem (spec §5.1) — stub (dono: Y3.2; corpos chamados por ``ayanami.fila``)."""

from __future__ import annotations

from typing import Any

from procrastinate import JobContext

from ayanami.deps import Deps


async def coletar(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``noticias.coletar`` (cron ``0 */2 * * *`` UTC) (dono: Y3.2)."""
    raise NotImplementedError("coletar: ainda não implementado (dono: Y3.2)")


async def progresso(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``progresso.atualizar``: AniList/Steam, só pontuação local (dono: Y3.2)."""
    raise NotImplementedError("progresso: ainda não implementado (dono: Y3.2)")
