"""Web Push (spec §15) — job ``push.enviar`` (dono: P2.1; corpo chamado por ``ayanami.fila``).

A lógica toda mora em :mod:`ayanami.push`; aqui só se acha a fila (``deps.extras["fila"]`` nos
testes, ``contexto.app`` no worker) para os reagendamentos (acumulados e repetições 429/5xx).
"""

from __future__ import annotations

from typing import Any

from procrastinate import JobContext

from ayanami import push
from ayanami.deps import Deps


async def enviar(deps: Deps, contexto: JobContext, *, evento_id: int, assinatura: int | None = None,
                 tentativa: int = 0, payload: dict[str, Any] | None = None, urgencia: str | None = None,
                 ttl: int | None = None) -> dict[str, Any] | None:
    """``push.enviar``: manda o evento aos celulares assinantes (ou repete um envio; dono: P2.1)."""
    app = deps.extras.get("fila") or getattr(contexto, "app", None)
    return await push.processar(deps, app, evento_id, assinatura=assinatura, tentativa=tentativa,
                                payload=payload, urgencia=urgencia, ttl=ttl)
