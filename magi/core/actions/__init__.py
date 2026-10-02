"""Ações locais do núcleo (R5–R8).

Cada módulo deste pacote (games, hud, system, spotify_mpris, ...) define um ou mais
``ActionHandler`` e uma função ``handlers(...) -> list[ActionHandler]``. O núcleo monta um
``Registry`` e registra os handlers; o turno só fala com o ``Registry``.
"""

from __future__ import annotations

import logging

from magi.common.contracts import ActionHandler, ActionRequest, ActionResult

log = logging.getLogger(__name__)

SAY_NO_HANDLER = "Isso eu ainda não sei fazer."
SAY_FAILED = "Deu ruim aqui, não consegui."


class DuplicateIntent(ValueError):
    """Dois handlers registrados para o mesmo intent."""


class Registry:
    """Implementação de ``ActionRegistry``: despacha pelo ``intent.id``."""

    def __init__(self, handlers: list[ActionHandler] | None = None) -> None:
        self._by_intent: dict[str, ActionHandler] = {}
        for h in handlers or ():
            self.register(h)

    def register(self, handler: ActionHandler) -> None:
        for intent_id in handler.intents:
            if intent_id in self._by_intent:
                raise DuplicateIntent(intent_id)
        for intent_id in handler.intents:
            self._by_intent[intent_id] = handler

    def handles(self, intent_id: str) -> bool:
        return intent_id in self._by_intent

    async def run(self, req: ActionRequest) -> ActionResult:
        handler = self._by_intent.get(req.intent.id)
        if handler is None:
            return ActionResult(ok=False, speech=SAY_NO_HANDLER)
        try:
            return await handler.run(req)
        except Exception:  # erro inesperado de um handler não derruba o turno
            log.exception("ação %s falhou", req.intent.id)
            return ActionResult(ok=False, speech=SAY_FAILED)
