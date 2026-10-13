"""Tarefas do agente (spec §5.3) — stub (dono: Y3.4; corpos chamados por ``ayanami.fila``)."""

from __future__ import annotations

from typing import Any

from procrastinate import JobContext

from ayanami.deps import Deps


async def pesquisar(deps: Deps, contexto: JobContext, *, tarefa_id: str) -> dict[str, Any] | None:
    """``agente.pesquisar``: pesquisa/resumo com o ``GraphAgent`` (dono: Y3.4)."""
    raise NotImplementedError("pesquisar: ainda não implementado (dono: Y3.4)")


async def lembrete(deps: Deps, contexto: JobContext, *, tarefa_id: str) -> dict[str, Any] | None:
    """``agente.lembrete``: cria o evento lembrete na ``agenda`` (dono: Y3.4)."""
    raise NotImplementedError("lembrete: ainda não implementado (dono: Y3.4)")


async def monitor_passo(deps: Deps, contexto: JobContext, *, tarefa_id: str) -> dict[str, Any] | None:
    """``monitor.passo``: um passo do monitor (dono: Y3.4)."""
    raise NotImplementedError("monitor_passo: ainda não implementado (dono: Y3.4)")


async def monitores_varrer(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``monitores.varrer``: defere ``monitor.passo`` dos vencidos (dono: Y3.4)."""
    raise NotImplementedError("monitores_varrer: ainda não implementado (dono: Y3.4)")
