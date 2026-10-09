"""Persona do Learning Mode no prompt do agente (tarefa LM1.4; design §5; spec §4 item 4; CNV-002).

Com sessão ativa, o system prompt do agente ganha o bloco de ``prompts/persona.md`` depois da
persona normal (``magi/agent/persona.md`` + linha de idioma): conversa natural em en-GB, perguntas
abertas, **nunca** correção explícita (recast permitido). Sem sessão, o prompt fica igual.

``install(agent, active)`` liga isso a um ``GraphAgent`` já montado sem mexer no grafo: a cada
``answer`` a persona do turno é escolhida por ``active()`` (lido no começo do turno). O modelo do
agente não muda. LM1.8: o tema da sessão entra **depois** do bloco de persona, dentro de
``<topic_context>`` (tratado como dado, cortado em 1500 caracteres; spec §10.1 item 4).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

from magi.common.contracts import ActionResult, TurnContext
from magi.learning.topic import clip

__all__ = ["PERSONA_PATH", "block", "compose", "install"]

log = logging.getLogger(__name__)

PERSONA_PATH = Path(__file__).parent / "prompts" / "persona.md"
#: Marca no agente de que a persona já foi instalada (não embrulha duas vezes).
_MARK = "_learning_persona"


@cache
def block() -> str:
    """Bloco "Learning Mode" (``prompts/persona.md``)."""
    return PERSONA_PATH.read_text(encoding="utf-8").strip()


def compose(base: str, *, active: bool, topic: str | None = None) -> str:
    """Persona do turno: ``base`` sozinha fora do modo; com sessão, ``base`` + bloco (+ tema)."""
    base = base.strip()
    if not active:
        return base
    parts = [base, block()]
    extra = clip(topic)
    if extra:
        parts.append(f"<topic_context>\n{extra}\n</topic_context>")
    return "\n\n".join(p for p in parts if p)


def install(
    agent: Any,
    active: Callable[[], bool],
    *,
    topic: Callable[[], str | None] | None = None,
) -> bool:
    """Embrulha ``agent.answer`` para usar a persona do Learning Mode quando ``active()``.

    Funciona com o ``GraphAgent`` (persona lida de ``_persona`` a cada montagem do prompt; ``None``
    = ``persona.md``). Agente sem esse campo (dublês, outro agente) não é tocado: devolve ``False``.
    """
    if agent is None or not hasattr(agent, "_persona") or getattr(agent, _MARK, False):
        return False
    original: str | None = agent._persona
    inner = agent.answer

    def base() -> str:
        if original is not None:
            return original
        from magi.agent.prompt import load_persona

        return load_persona()

    async def answer(text: str, ctx: TurnContext) -> ActionResult:
        try:
            on = bool(active())
        except Exception:
            log.exception("learning: estado da sessão indisponível; persona normal")
            on = False
        if on:
            extra = None
            if topic is not None:
                try:
                    extra = topic()
                except Exception:
                    log.exception("learning: tema indisponível; persona sem tema")
            agent._persona = compose(base(), active=True, topic=extra)
        else:
            agent._persona = original
        return await inner(text, ctx)

    agent.answer = answer
    setattr(agent, _MARK, True)
    return True
