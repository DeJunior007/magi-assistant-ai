"""Custos da nuvem no PC (stub; dono: Y6.6).

A Y6.6 puxa ``GET /v1/custos?desde=`` a cada ``ola`` e 15 min (``rodar``), insere em ``costs``
com ``origem_uid`` sem duplicar e dá o total do mês para o ``Bate`` (``total_mes``). Até lá:
``rodar`` volta já e ``total_mes`` é ``None`` (o ``NoPc`` usa o ``Budget`` local).
"""

from __future__ import annotations

from typing import Any


class CustosPc:
    def __init__(self, core: Any = None, cliente: Any = None) -> None:
        """``core``: ``magi.core.assemble.Core``; ``cliente``: ``EloCliente`` (``http``, token)."""
        self.core = core
        self.cliente = cliente

    async def rodar(self) -> None:
        return None

    def total_mes(self) -> float | None:
        return None
