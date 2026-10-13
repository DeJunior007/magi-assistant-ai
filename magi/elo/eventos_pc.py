"""Eventos e confirmações da Ayanami no PC (stub; dono: Y6.6).

O ``NoPc`` (Y6.2) despacha ``evento`` → ``EventosPc.evento`` e ``confirma`` →
``EventosPc.confirma``. A Y6.6 liga ao ``sink`` da proatividade (silêncio/jogo) e ao caminho de
confirmação do core. Até lá: só registra e devolve ``None`` (o ``EloCliente`` responde ``ack``).
"""

from __future__ import annotations

import logging
from typing import Any

from magi.elo.mensagens import Confirma, Envelope

log = logging.getLogger(__name__)


class EventosPc:
    def __init__(self, core: Any = None) -> None:
        """``core``: ``magi.core.assemble.Core`` (``proactive``, ``hud``…), ou ``None``."""
        self.core = core

    async def evento(self, env: Envelope) -> None:
        log.info("ayanami: evento %s ainda sem tratamento (Y6.6)", getattr(env.corpo, "tipo", "?"))

    async def confirma(self, env: Envelope) -> Confirma | None:
        log.info("ayanami: confirmação ainda sem tratamento (Y6.6)")
        return None
