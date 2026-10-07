"""Grafo do agente (3.4, §4.3, R9-R14, R5.3, R11.3, R16.4).

LangGraph com dois nós em padrão ReAct: ``model`` chama o ``ChatProvider`` do registro (que já
aplica KeyPool e orçamento) e ``tools`` executa as ferramentas pedidas. No máximo
``MAX_STEPS`` chamadas ao modelo; na última as ferramentas não são oferecidas, para forçar a
resposta final. O ``ChatProvider`` não é um ChatModel do LangChain, então os nós chamam o
protocolo direto e o estado leva ``ChatMessage`` de ``contracts.py``.

Ferramenta que devolve ``needs_confirmation`` encerra o grafo: o resultado sobe como está e o
núcleo entra em ``confirming``. A resposta final passa por ``magi.core.compose`` (fala ≤ 2
frases, ``full_text``, cards).

Fala por frase (1.24): com um ``EarlySpeech`` do turno em ``EARLY_SPEECH`` e um chat com
``chat_stream``, o modelo responde em streaming e cada frase falada que fecha (``SpeechDraft``)
já vai para o TTS enquanto o resto ainda é gerado. O texto que vem antes de uma chamada de
ferramenta vira frase de espera (falada na hora, fora do limite da resposta: ``EarlySpeech``):
"deixa eu ver…" ou a parte do pedido que já dá para responder. Na primeira chamada (em paralelo
com a busca de memórias) as frases ficam retidas até a busca decidir: se ela traz memórias, a
chamada é refeita e o rascunho, descartado.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
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
    TurnRecord,
)
from magi.core.compose import SpeechDraft, compose, short_speech
from magi.core.early import EARLY_SPEECH, EarlySpeech

log = logging.getLogger(__name__)

MAX_STEPS = 4
#: Quanto a primeira resposta do modelo espera pelas memórias depois de chegar (1.23; RNF-05).
MEMORY_GRACE_S = 0.3
HISTORY_TURNS = 2
#: Turnos do agente mais velhos que isso não voltam ao histórico quando o núcleo reinicia.
HISTORY_MAX_AGE = timedelta(hours=1)

SAY_BUDGET = "Bati o teto do mês, só comandos locais agora."
SAY_PROVIDER_FAILED = "Não consegui falar com a nuvem agora, tenta de novo daqui a pouco."
SAY_GAVE_UP = "Me enrolei aqui, tenta pedir de outro jeito."
SAY_UNKNOWN_TOOL = "Ferramenta desconhecida."

__all__ = ["GraphAgent", "history_from_turns", "short_speech"]


def history_from_turns(
    turns: Sequence[TurnRecord], now: datetime, max_age: timedelta = HISTORY_MAX_AGE
) -> list[ChatMessage]:
    """Histórico do agente a partir de ``turns`` do banco (mais novo primeiro, como ``recent``).

    Só entram turnos que foram ao agente (sem intenção local) com resposta, que não sejam as falas
    de falha, com no máximo ``max_age``; os ``HISTORY_TURNS`` mais novos, em ordem cronológica.
    """
    failures = {SAY_BUDGET, SAY_PROVIDER_FAILED, SAY_GAVE_UP}
    picked: list[TurnRecord] = []
    for t in turns:
        if t.intent is not None or t.routed_local or not t.reply.strip() or t.reply in failures:
            continue
        if not t.text_final.strip() or now - t.at > max_age:
            continue
        picked.append(t)
        if len(picked) == HISTORY_TURNS:
            break
    messages: list[ChatMessage] = []
    for t in reversed(picked):
        messages.append(ChatMessage(role="user", content=t.text_final))
        messages.append(ChatMessage(role="assistant", content=t.reply))
    return messages


class _State(TypedDict, total=False):
    messages: list[ChatMessage]
    steps: int
    reply: ChatReply | None
    results: list[ActionResult]
    pending: ActionResult | None
    chat: ChatProvider
    ctx: TurnContext
    text: str
    memories: asyncio.Task[list[Any]] | None
    remake: Callable[[list[Any]], list[ChatMessage]]
    final: bool


class GraphAgent:
    """Implementação do protocolo ``Agent`` (R9-R14).

    ``providers``: registro de provedores; ``providers.chat(ProviderTask.AGENT)`` é pedido a cada
    turno. ``tools``: ferramentas oferecidas ao modelo. ``game``: devolve o jogo em foco (ou
    ``None``). ``profile``: perfil compacto (ou ``None``). ``persona``: substitui ``persona.md``.
    ``about``: seção "Sobre você" (3.9, ``SelfModel.about_section``), lida a cada turno.
    ``memory``: ``MemoryStore`` (4.1); busca até 5 memórias para o prompt. A busca (embeddings +
    banco) corre em paralelo com a primeira chamada do modelo, que sai sem memórias (1.23): se a
    busca não acha nada (o caso comum), a resposta segue; se acha, a chamada é refeita com elas.
    Depois que o modelo responde, a busca tem só ``MEMORY_GRACE_S`` para terminar.
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
        memory: Any = None,
        max_steps: int = MAX_STEPS,
    ) -> None:
        self._providers = providers
        self._tools = {t.name: t for t in tools}
        self._specs = tuple(t.spec for t in tools)
        self._game = game
        self.profile = profile  # público: o núcleo liga o perfil (4.2) depois de criar o agente
        self._persona = persona
        self._about = about
        self.memory = memory
        self.max_steps = max_steps
        self._history: deque[ChatMessage] = deque(maxlen=2 * HISTORY_TURNS)
        self._graph = self._build()

    def seed_history(self, messages: Sequence[ChatMessage]) -> None:
        """Repõe o histórico curto ao subir (ver ``history_from_turns``); só vale se ainda vazio."""
        if not self._history:
            self._history.extend(messages)

    def add_tools(self, tools: Sequence[Tool]) -> None:
        """Acrescenta ferramentas depois de montado (memória, 4.1)."""
        for t in tools:
            self._tools[t.name] = t
        self._specs = tuple(t.spec for t in self._tools.values())

    def tool(self, name: str) -> Tool | None:
        """Ferramenta pelo nome (ex.: ``search`` para o fallback de novidades, 6.12)."""
        return self._tools.get(name)

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
        messages = state["messages"]
        mem_task = state.get("memories")
        if step == 1 and mem_task is not None:
            messages, reply = await self._first_reply(state, mem_task, tools)
        else:
            reply = await _call(state["chat"], messages, tools, _Voice.current())
        msg = ChatMessage(role="assistant", content=reply.text, tool_calls=reply.tool_calls)
        return {"messages": [*messages, msg], "steps": step, "reply": reply}

    async def _first_reply(
        self, state: _State, mem_task: asyncio.Task[list[Any]], tools: Sequence[Any]
    ) -> tuple[list[ChatMessage], ChatReply]:
        """Primeira chamada do modelo em paralelo com a busca de memórias (1.23)."""
        chat, messages = state["chat"], state["messages"]
        voice = _Voice.current(held=True)
        first = asyncio.ensure_future(_call(chat, messages, tools, voice))
        try:
            await asyncio.wait((mem_task, first), return_when=asyncio.FIRST_COMPLETED)
            if not mem_task.done():
                await asyncio.wait((mem_task,), timeout=MEMORY_GRACE_S)
            memories = _task_result(mem_task)
            if memories:
                try:
                    with_mem = state["remake"](memories)
                except PromptTooLarge:
                    log.warning("agente: memórias não cabem no prompt; seguindo sem elas")
                else:
                    first.cancel()
                    if voice is not None:
                        voice.discard()
                    return with_mem, await _call(chat, with_mem, tools, _Voice.current())
            if voice is not None:
                voice.release()  # frase de espera antes da ferramenta também sai (já marcada)
            return messages, await first
        finally:
            for task in (first, mem_task):
                if not task.done():
                    task.cancel()
                elif not task.cancelled():
                    task.exception()  # marca como lida (erro da chamada descartada não vira aviso)

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
        final = True
        for call in reply.tool_calls:
            tool = self._tools.get(call.name)
            if tool is None:
                final = False
                content = result_payload(ActionResult(ok=False, speech=SAY_UNKNOWN_TOOL))
            else:
                result = await tool.run(call.arguments, state["ctx"], state.get("text", ""))
                if result.needs_confirmation:
                    return {"pending": result}
                results.append(result)
                final = final and result.ok and getattr(tool, "final", False)
                content = result_payload(result)
            messages.append(ChatMessage(role="tool", content=content, tool_call_id=call.id))
        return {"messages": messages, "results": results, "final": final}

    def _after_tools(self, state: _State) -> Literal["model", "__end__"]:
        # Ferramenta "final" (ex.: screenshot, 3.7) já traz a resposta pronta: poupa uma volta.
        if state.get("pending") is not None or state.get("final"):
            return END
        return "model"

    # -- protocolo Agent ----------------------------------------------------------------------

    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        profile = self.profile() if self.profile else None
        game = self._game() if self._game else None
        history = tuple(self._history)
        about = self._about_text()

        def remake(memories: list[Any]) -> list[ChatMessage]:
            prompt = build_prompt(
                mood=ctx.mood,
                profile=profile,
                game=game,
                memories=memories,
                history=history,
                persona=self._persona,
                about=about,
            )
            return prompt.with_user(text)

        try:
            messages = remake([])
        except PromptTooLarge:
            log.exception("prompt do agente não cabe no limite")
            return ActionResult(ok=False, speech=SAY_GAVE_UP, expression=Expression.CONFUSED)
        mem_task = asyncio.ensure_future(self.memory.relevant(text)) if self.memory is not None else None
        try:
            return await self._run(text, ctx, messages, mem_task, remake)
        finally:
            if mem_task is not None and not mem_task.done():
                mem_task.cancel()

    async def _run(
        self,
        text: str,
        ctx: TurnContext,
        messages: list[ChatMessage],
        mem_task: asyncio.Task[list[Any]] | None,
        remake: Callable[[list[Any]], list[ChatMessage]],
    ) -> ActionResult:
        state: _State = {
            "messages": messages,
            "memories": mem_task,
            "remake": remake,
            "steps": 0,
            "reply": None,
            "results": [],
            "pending": None,
            "final": False,
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
        full = "" if state.get("final") else (reply.text if reply else "").strip()
        # Cards e listas completas das ferramentas (ex.: self_info) seguem para o HUD.
        cards = tuple(c for r in results for c in r.cards)
        if full:
            extra = [r.full_text for r in results if r.cards and r.full_text and r.full_text != r.speech]
            text = "\n\n".join([full, *extra]) if extra else full
            return compose(ActionResult(ok=True, speech=full, full_text=text, cards=cards))
        if last is not None and last.speech:
            return compose(
                ActionResult(
                    ok=last.ok,
                    speech=last.speech,
                    full_text=last.full_text or last.speech,
                    expression=last.expression,
                    cards=cards,
                )
            )
        return ActionResult(ok=False, speech=SAY_GAVE_UP, expression=Expression.CONFUSED)


class _Voice:
    """Frases de uma chamada do modelo a caminho do ``EarlySpeech`` (1.24). ``held``: retém as
    frases até ``release`` (primeira chamada, enquanto a busca de memórias não decide)."""

    def __init__(self, early: EarlySpeech, *, held: bool = False) -> None:
        self._early = early
        self._held: list[str] | None = [] if held else None
        self._dead = False
        self._interim = False
        self.said: list[str] = []
        self.draft = SpeechDraft()

    @classmethod
    def current(cls, *, held: bool = False) -> _Voice | None:
        early = EARLY_SPEECH.get()
        return cls(early, held=held) if early is not None else None

    def push(self, delta: str) -> None:
        self._say(self.draft.push(delta))

    def finish(self, text: str) -> None:
        self._say(self.draft.finish(text))

    def release(self) -> None:
        held, self._held = self._held, None
        self._say(held or [])

    def discard(self) -> None:
        self._dead = True

    def interim(self) -> None:
        """Esta chamada terminou em ferramenta: o que ela falou (e o que ainda falar) é de espera."""
        self._interim = True
        self._early.mark_interim(self.said)

    def _say(self, found: list[str]) -> None:
        if self._dead:
            return
        if self._held is not None:
            self._held.extend(found)
            return
        for sentence in found:
            self._early.say(sentence)
            self.said.append(sentence)
        if self._interim:
            self._early.mark_interim(found)


async def _call(
    chat: ChatProvider, messages: list[ChatMessage], tools: Sequence[Any], voice: _Voice | None
) -> ChatReply:
    """Uma chamada do modelo; com ``voice`` e ``chat_stream``, em streaming falando por frase."""
    stream = getattr(chat, "chat_stream", None)
    if voice is None or stream is None:
        return await chat.chat(messages, tools=tools, personal=True)
    reply = await stream(messages, tools=tools, personal=True, on_text=voice.push)
    if reply.tool_calls:
        voice.interim()  # antes do finish: a frase sem ponto final também conta como de espera
    voice.finish(reply.text)
    return reply


def _task_result(task: asyncio.Task[list[Any]]) -> list[Any]:
    """Memórias de uma busca terminada; ``[]`` se não terminou, foi cancelada ou falhou."""
    if not task.done() or task.cancelled() or task.exception() is not None:
        return []
    return list(task.result() or [])
