"""Ferramentas de memória do agente e o "esquece isso" local (tarefa 4.1, R11.2, R11.5).

- ``remember(fact, kind)``: o agente decide o que vale guardar (fatos sobre o Pedro, preferências,
  jogos que ele está jogando, coisas que ele pediu para lembrar). Grava em segundo plano.
- ``forget(what)``: apaga a memória mais parecida com ``what`` (vazio = a última gravada).
- ``ForgetHandler``: intent local ``memory.forget`` ("esquece isso") apaga a última memória gravada.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from magi.agent.tools.base import arg_str
from magi.common.contracts import ActionRequest, ActionResult, Expression, IntentId, ToolSpec, TurnContext
from magi.memory.memories_repo import MemoryStore

MEMORY_KINDS = ("fact", "preference", "game", "request")

SAY_REMEMBERED = "Guardei."
SAY_FORGOT = "Esquecido."
SAY_NOTHING = "Não tinha nada guardado sobre isso."
SAY_WHAT = "Guardar o quê?"

REMEMBER_SPEC = ToolSpec(
    name="remember",
    description=(
        "Guarda na memória de longo prazo um fato duradouro sobre o Pedro: preferência, gosto, "
        "jogo que ele está jogando, plano, ou algo que ele pediu para lembrar. Escreva o fato curto "
        "e autossuficiente (ex.: 'Pedro está jogando Elden Ring'). NÃO use para conversa trivial, "
        "perguntas pontuais ou o que já aparece em Memórias."
    ),
    parameters={
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "O fato, numa frase curta"},
            "kind": {"type": "string", "enum": list(MEMORY_KINDS)},
        },
        "required": ["fact"],
    },
)

FORGET_SPEC = ToolSpec(
    name="forget",
    description="Apaga da memória o fato mais parecido com 'what' (vazio = o último guardado).",
    parameters={
        "type": "object",
        "properties": {"what": {"type": "string", "description": "O que esquecer"}},
    },
)


class RememberTool:
    spec = REMEMBER_SPEC
    danger = False

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        fact = arg_str(args, "fact")
        kind = arg_str(args, "kind") or "fact"
        if kind not in MEMORY_KINDS:
            kind = "fact"
        if not self.store.remember(fact, kind, ctx.turn_id):
            return ActionResult(ok=False, speech=SAY_WHAT, expression=Expression.CONFUSED)
        return ActionResult(ok=True, speech=SAY_REMEMBERED)


class ForgetTool:
    spec = FORGET_SPEC
    danger = False

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        gone = await self.store.forget(arg_str(args, "what"))
        if gone is None:
            return ActionResult(ok=False, speech=SAY_NOTHING)
        return ActionResult(ok=True, speech=SAY_FORGOT, full_text=f"Esqueci: {gone.body}")


def memory_tools(store: MemoryStore) -> list[RememberTool | ForgetTool]:
    return [RememberTool(store), ForgetTool(store)]


class ForgetHandler:
    """``memory.forget`` local: apaga a última memória gravada e confirma (R11.5)."""

    intents = frozenset({IntentId.MEMORY_FORGET.value})

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def run(self, req: ActionRequest) -> ActionResult:
        gone = await self.store.forget_last()
        if gone is None:
            return ActionResult(ok=True, speech=SAY_NOTHING)
        return ActionResult(ok=True, speech=SAY_FORGOT, full_text=f"Esqueci: {gone.body}")
