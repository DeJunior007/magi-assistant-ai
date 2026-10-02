"""Adaptador genérico entre ferramentas do agente e as ações locais (3.4, R5.3, R9-R14).

Uma ferramenta é um ``ToolSpec`` (o que o modelo vê) mais um *mapper* que converte os
argumentos do modelo num ``Mapped`` (intent + slots + args). A execução passa sempre por
``ActionRegistry.run(ActionRequest(...))``, reaproveitando as ações da fase 1 sem duplicar lógica.

Ferramenta perigosa (``danger=True``) nunca executa direto: devolve ``needs_confirmation`` com
``on_confirm`` = o mesmo pedido já confirmado, e o núcleo entra em ``confirming`` (R5.3).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from magi.common.contracts import (
    ActionRegistry,
    ActionRequest,
    ActionResult,
    Expression,
    Intent,
    Slot,
    ToolSpec,
    TurnContext,
)

SAY_CONFIRM = "Tem certeza? Diz confirma."


class ToolArgsError(ValueError):
    """Argumentos do modelo inválidos para a ferramenta. A mensagem vira a fala/resultado."""


@dataclass(frozen=True, slots=True)
class Mapped:
    """Tradução dos argumentos do modelo para uma ação local."""

    intent_id: str
    slots: tuple[Slot, ...] = ()
    args: Mapping[str, Any] = field(default_factory=dict)
    confirm_speech: str | None = None


class Tool(Protocol):
    """Ferramenta executável pelo grafo do agente."""

    spec: ToolSpec
    danger: bool

    @property
    def name(self) -> str: ...

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult: ...


Mapper = Callable[[Mapping[str, Any]], Mapped]


class ActionTool:
    """Ferramenta que executa uma ação local via ``ActionRegistry``."""

    def __init__(
        self,
        spec: ToolSpec,
        mapper: Mapper,
        registry: ActionRegistry,
        *,
        danger: bool = False,
    ) -> None:
        self.spec = spec
        self.mapper = mapper
        self.registry = registry
        self.danger = danger

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        try:
            m = self.mapper(args)
        except ToolArgsError as e:
            return ActionResult(ok=False, speech=str(e), expression=Expression.CONFUSED)
        intent = Intent(id=m.intent_id, slots=m.slots, danger=self.danger)
        req = ActionRequest(intent=intent, ctx=ctx, text=text, args=dict(m.args))
        if self.danger:
            return ActionResult(
                ok=True,
                speech=m.confirm_speech or SAY_CONFIRM,
                needs_confirmation=True,
                dangerous=True,
                on_confirm=replace(req, confirmed=True),
            )
        return await self.registry.run(req)


def result_payload(result: ActionResult) -> str:
    """Resumo JSON do resultado de uma ferramenta, devolvido ao modelo como mensagem ``tool``."""
    out: dict[str, Any] = {"ok": result.ok}
    if result.speech:
        out["speech"] = result.speech
    if result.full_text:
        out["text"] = result.full_text
    if result.needs_confirmation:
        out["needs_confirmation"] = True
    return json.dumps(out, ensure_ascii=False)


def arg_str(args: Mapping[str, Any], key: str) -> str:
    """Argumento textual (vazio se ausente)."""
    v = args.get(key)
    return "" if v is None else str(v).strip()


def arg_int(args: Mapping[str, Any], key: str) -> int | None:
    """Argumento inteiro (aceita "50", 50.0); ``None`` se ausente, ``ToolArgsError`` se inválido."""
    v = args.get(key)
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise ToolArgsError(f"{key} inválido.")
    try:
        return int(round(float(str(v).strip().rstrip("%").replace(",", "."))))
    except ValueError as e:
        raise ToolArgsError(f"{key} inválido.") from e
