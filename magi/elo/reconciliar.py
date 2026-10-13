"""Reconciliação ``resumo_nuvem`` no PC (stub; dono: Y6.5).

O ``NoPc`` (Y6.2) despacha ``resumo_nuvem`` → ``Reconciliador.gravar_resumo`` e responde
``Ack(ids=…)`` com o que ele devolver. A Y6.5 grava em ``turns`` (satélite ``celular``, marcado
``nuvem``), passa pelo extrator de memória e ignora ``uid`` já gravado. Até lá não grava nada e
devolve ``()`` (a Ayanami reenvia no próximo ``ola``).
"""

from __future__ import annotations

import logging
from typing import Any

from magi.elo.mensagens import ResumoNuvem

log = logging.getLogger(__name__)


class Reconciliador:
    def __init__(self, core: Any = None) -> None:
        """``core``: ``magi.core.assemble.Core`` (``repos``, ``memory``…), ou ``None``."""
        self.core = core

    async def gravar_resumo(self, resumo: ResumoNuvem) -> tuple[str, ...]:
        log.info("ayanami: resumo_nuvem com %d turnos ainda sem gravação (Y6.5)", len(resumo.turnos))
        return ()
