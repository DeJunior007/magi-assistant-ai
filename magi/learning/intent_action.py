"""Entrar/sair do Learning Mode por voz (tarefa LM1.4; design §10; spec §10; LM-005, P8).

Intents ``learning.start`` / ``learning.stop`` (``magi/core/intents.yaml``, frases PT e EN) →
``LearningIntentAction`` → ``LearningWiring.set_mode(on, reason="voice")``: o mesmo caminho do
``lm_mode`` do botão (cria/retoma ou fecha a sessão e confirma ``lm_mode`` aos clientes). Já no
estado pedido, só confirma, sem efeito. A resposta curta sai em português no código e vira inglês
pelo i18n (``en-gb.yaml``), o idioma da aula.

A ``LearningWiring`` nasce depois do ``assemble`` (``magi.core.service``); a ação a acha em tempo
de execução pelo gancho que a instalação deixa em ``TurnDeps.learning`` (``wiring_of``).

Sem atalho global e sem comando de terminal (P8): voz e botão no HUD são as únicas entradas.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from magi.common.config import ConfigError
from magi.common.contracts import ActionHandler, ActionRequest, ActionResult, IntentId

if TYPE_CHECKING:
    from magi.learning.wiring import LearningWiring

__all__ = [
    "INTENTS",
    "SAY_ALREADY_ON",
    "SAY_FAILED",
    "SAY_NOT_ON",
    "SAY_OFF",
    "SAY_ON",
    "SAY_UNAVAILABLE",
    "LearningIntentAction",
    "enabled",
    "wire",
    "wire_persona",
    "wiring_of",
]

log = logging.getLogger(__name__)

INTENTS = frozenset({IntentId.LEARNING_START.value, IntentId.LEARNING_STOP.value})

# Frases em português (o i18n troca pelo inglês da aula, ``en-gb.yaml``).
SAY_ON = "Modo aula ligado. Bora conversar."
SAY_OFF = "Aula encerrada. Mandou bem."
SAY_ALREADY_ON = "O modo aula já está ligado."
SAY_NOT_ON = "Não tem aula aberta."
SAY_UNAVAILABLE = "Modo aula indisponível agora."
SAY_FAILED = "Não consegui trocar o modo aula."

WiringRef = Callable[[], "LearningWiring | None"]


class LearningIntentAction:
    """``ActionHandler`` de ``learning.start`` / ``learning.stop`` (voz, ``end_reason = "voice"``)."""

    intents = INTENTS

    def __init__(self, wiring: WiringRef) -> None:
        self._wiring = wiring

    async def run(self, req: ActionRequest) -> ActionResult:
        wiring = self._wiring()
        if wiring is None:
            return ActionResult(ok=False, speech=SAY_UNAVAILABLE)
        on = req.intent.id == IntentId.LEARNING_START.value
        was_on = wiring.session.active
        try:
            await wiring.set_mode(on, "voice")
        except Exception:
            log.exception("learning: falha ao %s o modo por voz", "ligar" if on else "desligar")
            return ActionResult(ok=False, speech=SAY_FAILED)
        if on:
            return ActionResult(ok=True, speech=SAY_ALREADY_ON if was_on else SAY_ON)
        return ActionResult(ok=True, speech=SAY_OFF if was_on else SAY_NOT_ON)


def wiring_of(deps: Any) -> LearningWiring | None:
    """``LearningWiring`` instalada no núcleo (``install`` põe ``wiring.on_turn`` em
    ``TurnDeps.learning``), ou ``None`` com o modo desligado/não instalado."""
    from magi.learning.wiring import LearningWiring

    owner = getattr(getattr(deps, "learning", None), "__self__", None)
    return owner if isinstance(owner, LearningWiring) else None


def enabled(config: Any) -> bool:
    """``[learning] enabled`` (config inválida = desligado, como no ``wiring.install``)."""
    from magi.learning.config import learning_config

    try:
        return learning_config(config).enabled
    except (ConfigError, AttributeError, TypeError) as e:
        log.debug("learning: config indisponível (%s); modo desligado", e)
        return False


def wire(config: Any, deps: Any, found: list[ActionHandler]) -> list[ActionHandler]:
    """Registro da ação no núcleo (``assemble``). Com o modo desligado, as frases somem do
    roteador e o núcleo fica como antes (vão ao agente)."""
    if not enabled(config):
        router = getattr(deps, "router", None)
        if router is not None and hasattr(router, "intents"):
            router.intents = [s for s in router.intents if s.id not in INTENTS]
        return found
    if any(INTENTS & set(h.intents) for h in found):
        return found
    return [*found, LearningIntentAction(lambda: wiring_of(deps))]


def wire_persona(config: Any, deps: Any) -> bool:
    """Persona do Learning Mode no agente (``persona.install``), ativa só com sessão aberta."""
    if not enabled(config):
        return False
    from magi.learning import persona

    def active() -> bool:
        wiring = wiring_of(deps)
        return wiring is not None and wiring.session.active

    return persona.install(deps.agent, active)
