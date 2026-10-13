"""Backups restic (spec §7) — stub (dono: Y4.2; corpos chamados por ``ayanami.fila``)."""

from __future__ import annotations

from typing import Any

from procrastinate import JobContext

from ayanami.deps import Deps


async def restic(deps: Deps, contexto: JobContext, *, origem: str = "pc") -> dict[str, Any] | None:
    """``backup.restic``: sobe o backup do PC aceito (dono: Y4.2)."""
    raise NotImplementedError("restic: ainda não implementado (dono: Y4.2)")


async def dump_ayanami(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``backup.dump_ayanami`` (dono: Y4.2)."""
    raise NotImplementedError("dump_ayanami: ainda não implementado (dono: Y4.2)")


async def enviar(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``backup.enviar`` (dono: Y4.2)."""
    raise NotImplementedError("enviar: ainda não implementado (dono: Y4.2)")


async def reter(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``backup.reter`` (dono: Y4.2)."""
    raise NotImplementedError("reter: ainda não implementado (dono: Y4.2)")


async def verificar(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``backup.verificar`` (dono: Y4.2)."""
    raise NotImplementedError("verificar: ainda não implementado (dono: Y4.2)")


async def restore_teste(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``backup.restore_teste`` (dono: Y4.2)."""
    raise NotImplementedError("restore_teste: ainda não implementado (dono: Y4.2)")
