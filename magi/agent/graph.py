"""Grafo do agente (3.4, §4.3, R9-R14, R5.3, R11.3, R16.4).

LangGraph com dois nós em padrão ReAct: ``model`` chama o ``ChatProvider`` do registro (que já
aplica KeyPool e orçamento) e ``tools`` executa as ferramentas pedidas. No máximo
``MAX_STEPS`` chamadas ao modelo; na última as ferramentas não são oferecidas, para forçar a
resposta final. O ``ChatProvider`` não é um ChatModel do LangChain, então os nós chamam o
protocolo direto e o estado leva ``ChatMessage`` de ``contracts.py``.

Ferramenta que devolve ``needs_confirmation`` encerra o grafo: o resultado sobe como está e o
núcleo entra em ``confirming``. A resposta final vira ``speech`` (≤ 2 frases) e ``full_text``.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from magi.agent.prompt import GameContext, PromptTooLarge, build_prompt
from magi.agent.tools.base import Tool, result_payload
from magi.common.contracts import (
    ActionResult,
    BudgetExceeded,
    ChatMessage,
    ChatProvider,
    ChatReply,
    Expression,
    ProviderError,
    ProviderRegistry,
    ProviderTask,
    TurnContext,
)

log = logging.getLogger(__name__)

MAX_STEPS = 4
HISTORY_TURNS = 2
SPEECH_MAX_SENTENCES = 2

SAY_BUDGET = "Bati o teto do mês, só comandos locais agora."
SAY_PROVIDER_FAILED = "Não consegui falar com a nuvem agora, tenta de novo daqui a pouco."
SAY_GAVE_UP = "Me enrolei aqui, tenta pedir de outro jeito."
SAY_UNKNOWN_TOOL = "Ferramenta desconhecida."

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def short_speech(text: str, max_sentences: int = SPEECH_MAX_SENTENCES) -> str:
    """Primeiras ``max_sentences`` frases de ``text`` (fala curta, R12.3)."""
    parts = [p for p in _SENTENCE_END.split(" ".join(text.split())) if p]
    return " ".join(parts[:max_sentences])


class _State(TypedDict, total=False):
    messages: list[ChatMessage]
    steps: int
    reply: ChatReply | None
    results: list[ActionResult]
    pending: ActionResult | None
    chat: ChatProvider
    ctx: TurnContext
    text: str


class GraphAgent:
    """Implementação do protocolo ``Agent`` (R9-R14).

    ``providers``: registro de provedores; ``providers.chat(ProviderTask.AGENT)`` é pedido a cada
    turno. ``tools``: ferramentas oferecidas ao modelo. ``game``: devolve o jogo em foco (ou
    ``None``). ``profile``: perfil compacto (ou ``None``). ``persona``: substitui ``persona.md``.
    ``about``: seção "Sobre você" (3.9, ``SelfModel.about_section``), lida a cada turno.
    """

    def __init__(
        self,
        providers: ProviderRegistry,
        tools: Sequence[Tool] = (),
        *,
        game: Callable[[], GameContext | None] | None = None,
        profile: Callable[[], str | None] | None = None,
        persona: str | None = None,
        about: Callable[[], str | None] | None = None,
        max_steps: int = MAX_STEPS,
    ) -> None:
        self._providers = providers
        self._tools = {t.name: t for t in tools}
        self._specs = tuple(t.spec for t in tools)
        self._game = game
        self._profile = profile
        self._persona = persona
        self._about = about
        self.max_steps = max_steps
        self._history: deque[ChatMessage] = deque(maxlen=2 * HISTORY_TURNS)
        self._graph = self._build()

    # -- grafo --------------------------------------------------------------------------------

    def _build(self) -> Any:
        g = StateGraph(_State)
        g.add_node("model", self._model_node)
        g.add_node("tools", self._tools_node)
        g.add_edge(START, "model")
        g.add_conditional_edges("model", self._after_model, {"tools": "tools", END: END})
        g.add_conditional_edges("tools", self._after_tools, {"model": "model", END: END})
        return g.compile()

    async def _model_node(self, state: _State) -> dict[str, Any]:
        step = state.get("steps", 0) + 1
        tools = self._specs if step < self.max_steps else ()
        reply = await state["chat"].chat(state["messages"], tools=tools, personal=True)
        msg = ChatMessage(role="assistant", content=reply.text, tool_calls=reply.tool_calls)
        return {"messages": [*state["messages"], msg], "steps": step, "reply": reply}

    def _after_model(self, state: _State) -> Literal["tools", "__end__"]:
        reply = state.get("reply")
        if reply is not None and reply.tool_calls and state["steps"] < self.max_steps:
            return "tools"
        return END

    async def _tools_node(self, state: _State) -> dict[str, Any]:
        reply = state["reply"]
        assert reply is not None
        messages = list(state["messages"])
        results = list(state.get("results", []))
        for call in reply.tool_calls:
            tool = self._tools.get(call.name)
            if tool is None:
                content = result_payload(ActionResult(ok=False, speech=SAY_UNKNOWN_TOOL))
            else:
                result = await tool.run(call.arguments, state["ctx"], state.get("text", ""))
                if result.needs_confirmation:
                    return {"pending": result}
                results.append(result)
                content = result_payload(result)
            messages.append(ChatMessage(role="tool", content=content, tool_call_id=call.id))
        return {"messages": messages, "results": results}

    def _after_tools(self, state: _State) -> Literal["model", "__end__"]:
        return END if state.get("pending") is not None else "model"

    # -- protocolo Agent ----------------------------------------------------------------------

    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        try:
            prompt = build_prompt(
                mood=ctx.mood,
                profile=self._profile() if self._profile else None,
                game=self._game() if self._game else None,
                memories=(),
                history=tuple(self._history),
                persona=self._persona,
                about=self._about_text(),
            )
        except PromptTooLarge:
            log.exception("prompt do agente não cabe no limite")
            return ActionResult(ok=False, speech=SAY_GAVE_UP, expression=Expression.CONFUSED)
        state: _State = {
            "messages": prompt.with_user(text),
            "steps": 0,
            "reply": None,
            "results": [],
            "pending": None,
            "chat": self._providers.chat(ProviderTask.AGENT),
            "ctx": ctx,
            "text": text,
        }
        try:
            final = await self._graph.ainvoke(state, {"recursion_limit": 2 * self.max_steps + 2})
        except BudgetExceeded:
            return ActionResult(ok=False, speech=SAY_BUDGET)
        except ProviderError as e:
            log.warning("agente: falha do provedor: %s", e)
            return ActionResult(ok=False, speech=SAY_PROVIDER_FAILED, expression=Expression.CONFUSED)
        if (pending := final.get("pending")) is not None:
            return pending
        result = self._finish(final)
        if result.ok and result.full_text:
            self._history.extend(
                (
                    ChatMessage(role="user", content=text),
                    ChatMessage(role="assistant", content=result.full_text),
                )
            )
        return result

    def _about_text(self) -> str | None:
        if self._about is None:
            return None
        try:
            return self._about()
        except Exception:
            log.exception("seção 'Sobre você' indisponível")
            return None

    @property
    def tool_specs(self) -> tuple[Any, ...]:
        """Specs das ferramentas oferecidas ao modelo (ficha da 3.9)."""
        return self._specs

    def _finish(self, state: _State) -> ActionResult:
        reply = state.get("reply")
        results = state.get("results", [])
        last = results[-1] if results else None
        full = (reply.text if reply else "").strip()
        # Cards e listas completas das ferramentas (ex.: self_info) seguem para o HUD.
        cards = tuple(c for r in results for c in r.cards)
        if full:
            extra = [r.full_text for r in results if r.cards and r.full_text and r.full_text != r.speech]
            text = "\n\n".join([full, *extra]) if extra else full
            return ActionResult(ok=True, speech=short_speech(full), full_text=text, cards=cards)
        if last is not None and last.speech:
            return ActionResult(
                ok=last.ok,
                speech=short_speech(last.speech),
                full_text=last.full_text or last.speech,
                expression=last.expression,
                cards=cards,
            )
        return ActionResult(ok=False, speech=SAY_GAVE_UP, expression=Expression.CONFUSED)
