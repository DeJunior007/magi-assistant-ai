"""Entrar/sair do Learning Mode por voz (tarefa LM1.4; design §10; spec §10; LM-005, P8).

Intents ``learning.start`` / ``learning.stop`` (``magi/core/intents.yaml``, frases PT e EN) →
``LearningIntentAction`` → ``LearningWiring.set_mode(on, reason="voice")``: o mesmo caminho do
``lm_mode`` do botão (cria/retoma ou fecha a sessão e confirma ``lm_mode`` aos clientes). Já no
estado pedido, só confirma, sem efeito. A resposta curta sai em português no código e vira inglês
pelo i18n (``en-gb.yaml``), o idioma da aula.

A ``LearningWiring`` nasce depois do ``assemble`` (``magi.core.service``); a ação a acha em tempo
de execução pelo gancho que a instalação deixa em ``TurnDeps.learning`` (``wiring_of``).

Sem atalho global e sem comando de terminal (P8): voz e botão no HUD são as únicas entradas.

Tema por voz (LM1.8, LM-014): ``learning.topic.{free,interview,game,news}`` →
``LearningTopicAction`` → ``LearningWiring.set_topic(tema, "voice")``, a mesma ação do botão. As
frases só existem no roteador **com sessão ativa** (filtro no ``best`` do roteador, ``_gate``):
fora da aula "vamos falar do jogo" segue o caminho antigo. A ação guarda o ``TopicBuilder`` com as
fontes do núcleo (``GameWatcher``, Steam, ``NewsRepo``); a ``LearningWiring`` o acha por
``builder_of``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from magi.common.config import ConfigError
from magi.common.contracts import ActionHandler, ActionRequest, ActionResult, IntentId
from magi.learning.contracts import Topic
from magi.learning.topic import NO_GAME, NO_NEWS, TopicBuilder

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
    "TOPIC_INTENTS",
    "LearningIntentAction",
    "LearningTopicAction",
    "builder_of",
    "enabled",
    "wire",
    "wire_persona",
    "wiring_of",
]

log = logging.getLogger(__name__)

INTENTS = frozenset({IntentId.LEARNING_START.value, IntentId.LEARNING_STOP.value})
#: Intent de voz → tema (LM1.8).
TOPIC_OF: dict[str, Topic] = {
    IntentId.LEARNING_TOPIC_FREE.value: Topic.FREE,
    IntentId.LEARNING_TOPIC_INTERVIEW.value: Topic.INTERVIEW,
    IntentId.LEARNING_TOPIC_GAME.value: Topic.GAME,
    IntentId.LEARNING_TOPIC_NEWS.value: Topic.NEWS,
}
TOPIC_INTENTS = frozenset(TOPIC_OF)
#: Marca no roteador de que o filtro "só com sessão" já foi instalado.
_GATED = "_learning_topic_gate"

# Frases em português (o i18n troca pelo inglês da aula, ``en-gb.yaml``).
SAY_ON = "Modo aula ligado. Bora conversar."
SAY_OFF = "Aula encerrada. Mandou bem."
SAY_ALREADY_ON = "O modo aula já está ligado."
SAY_NOT_ON = "Não tem aula aberta."
SAY_UNAVAILABLE = "Modo aula indisponível agora."
SAY_FAILED = "Não consegui trocar o modo aula."
SAY_TOPIC: dict[Topic, str] = {
    Topic.FREE: "Conversa livre, então.",
    Topic.INTERVIEW: "Beleza, entrevista técnica.",
    Topic.GAME: "Bora falar do jogo.",
    Topic.NEWS: "Bora falar das notícias.",
}
SAY_TOPIC_FALLBACK: dict[str, str] = {
    NO_GAME: "Não vi jogo nenhum aberto. Conversa livre, então.",
    NO_NEWS: "Não tem notícia de hoje. Conversa livre, então.",
}
SAY_TOPIC_FAILED = "Não consegui trocar o tema."

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


class LearningTopicAction:
    """``ActionHandler`` de ``learning.topic.*`` (voz): mesma ação do botão ``lm_topic``."""

    intents = TOPIC_INTENTS

    def __init__(self, wiring: WiringRef, builder: TopicBuilder | None = None) -> None:
        self._wiring = wiring
        self.builder = builder

    async def run(self, req: ActionRequest) -> ActionResult:
        wiring = self._wiring()
        if wiring is None:
            return ActionResult(ok=False, speech=SAY_UNAVAILABLE)
        if not wiring.session.active:
            return ActionResult(ok=False, speech=SAY_NOT_ON)
        try:
            ctx = await wiring.set_topic(TOPIC_OF[req.intent.id], "voice")
        except Exception:
            log.exception("learning: falha ao trocar o tema por voz")
            return ActionResult(ok=False, speech=SAY_TOPIC_FAILED)
        if ctx is None:
            return ActionResult(ok=False, speech=SAY_NOT_ON)
        if ctx.detail in SAY_TOPIC_FALLBACK:
            return ActionResult(ok=True, speech=SAY_TOPIC_FALLBACK[ctx.detail])
        return ActionResult(ok=True, speech=SAY_TOPIC[ctx.topic])


def builder_of(deps: Any) -> TopicBuilder | None:
    """``TopicBuilder`` deixado pelo ``wire`` na ação de tema (``None`` = sem ação/fontes)."""
    by_intent = getattr(getattr(deps, "actions", None), "_by_intent", None) or {}
    handler = by_intent.get(IntentId.LEARNING_TOPIC_FREE.value)
    builder = getattr(handler, "builder", None)
    return builder if isinstance(builder, TopicBuilder) else None


def _gate(router: Any, active: Callable[[], bool]) -> None:
    """Intents de tema só com sessão ativa: fora dela o ``best`` do roteador não as vê."""
    if router is None or not hasattr(router, "intents") or getattr(router, _GATED, False):
        return
    inner = router.best

    def best(text: str) -> Any:
        if active():
            return inner(text)
        saved = router.intents
        router.intents = [s for s in saved if s.id not in TOPIC_INTENTS]
        try:
            return inner(text)
        finally:
            router.intents = saved

    router.best = best
    setattr(router, _GATED, True)


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


def wire(
    config: Any, deps: Any, found: list[ActionHandler], *, topics: TopicBuilder | None = None,
) -> list[ActionHandler]:
    """Registro das ações no núcleo (``assemble``). Com o modo desligado, as frases somem do
    roteador e o núcleo fica como antes (vão ao agente). ``topics``: fontes do tema (LM1.8)."""
    router = getattr(deps, "router", None)
    if not enabled(config):
        if router is not None and hasattr(router, "intents"):
            router.intents = [s for s in router.intents if s.id not in INTENTS | TOPIC_INTENTS]
        return found

    def active() -> bool:
        wiring = wiring_of(deps)
        return wiring is not None and wiring.session.active

    _gate(router, active)
    if not any(INTENTS & set(h.intents) for h in found):
        found = [*found, LearningIntentAction(lambda: wiring_of(deps))]
    if not any(TOPIC_INTENTS & set(h.intents) for h in found):
        found = [*found, LearningTopicAction(lambda: wiring_of(deps), topics)]
    return found


def wire_persona(config: Any, deps: Any) -> bool:
    """Persona do Learning Mode no agente (``persona.install``), ativa só com sessão aberta."""
    if not enabled(config):
        return False
    from magi.learning import persona

    def active() -> bool:
        wiring = wiring_of(deps)
        return wiring is not None and wiring.session.active

    def topic() -> str | None:
        wiring = wiring_of(deps)
        return wiring.session.topic_block if wiring is not None else None

    return persona.install(deps.agent, active, topic=topic)
