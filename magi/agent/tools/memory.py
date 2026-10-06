"""Ferramentas de memória do agente e o "esquece isso" local (tarefa 4.1, R11.2, R11.5).

- ``remember(fact, kind)``: o agente decide o que vale guardar (fatos sobre o Pedro, preferências,
  jogos que ele está jogando, coisas que ele pediu para lembrar). Grava em segundo plano.
- ``forget(what)``: apaga a memória mais parecida com ``what`` (vazio = a última gravada).
- ``ForgetHandler``: intent local ``memory.forget`` ("esquece isso") apaga a última memória gravada.

Memória desta conversa (``MemoryStore.is_fresh``) some na hora; uma antiga é lida em voz alta e só
some depois do "sim" (a confirmação volta ao ``ForgetHandler`` com o id no slot ``text``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from magi.agent.tools.base import arg_str
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    Expression,
    Intent,
    IntentId,
    Memory,
    Slot,
    SlotName,
    ToolSpec,
    TurnContext,
)
from magi.memory.memories_repo import MemoryStore

MEMORY_KINDS = ("fact", "preference", "game", "request")

SAY_REMEMBERED = "Guardei."
SAY_FORGOT = "Esquecido."
SAY_NOTHING = "Não tinha nada guardado sobre isso."
SAY_WHAT = "Guardar o quê?"


async def forget_or_ask(store: MemoryStore, target: Memory | None, ctx: TurnContext) -> ActionResult:
    """Apaga ``target`` se for desta conversa; se for antiga, pergunta antes (lendo o que é)."""
    if target is None or target.id is None:
        return ActionResult(ok=False, speech=SAY_NOTHING)
    if store.is_fresh(target):
        await store.delete(target.id)
        return ActionResult(ok=True, speech=SAY_FORGOT, full_text=f"Esqueci: {target.body}")
    intent = Intent(id=IntentId.MEMORY_FORGET.value, slots=(Slot(name=SlotName.TEXT, value=str(target.id)),))
    return ActionResult(
        ok=True,
        speech=f"Isso é antigo: {target.body}. Apago?",
        needs_confirmation=True,
        on_confirm=ActionRequest(intent=intent, ctx=ctx, confirmed=True),
        expression=Expression.CONFUSED,
    )

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
        return await forget_or_ask(self.store, await self.store.similar(arg_str(args, "what")), ctx)


def memory_tools(store: MemoryStore) -> list[RememberTool | ForgetTool]:
    return [RememberTool(store), ForgetTool(store)]


class ForgetHandler:
    """``memory.forget`` local: apaga a última memória gravada e confirma (R11.5)."""

    intents = frozenset({IntentId.MEMORY_FORGET.value})

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def run(self, req: ActionRequest) -> ActionResult:
        slot = req.intent.slot(SlotName.TEXT)
        if req.confirmed and slot is not None and slot.value.isdigit():  # "sim" para uma antiga
            await self.store.delete(int(slot.value))
            return ActionResult(ok=True, speech=SAY_FORGOT)
        res = await forget_or_ask(self.store, await self.store.last_memory(), req.ctx)
        return res if res.ok else ActionResult(ok=True, speech=SAY_NOTHING)
