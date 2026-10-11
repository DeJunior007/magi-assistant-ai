"""Ferramentas em paralelo e aviso ao HUD no ``_tools_node`` (espera viva E1.4, spec §7, CA-08)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from magi.agent.graph import SAY_TOOL_ERROR, GraphAgent
from magi.agent.tools.base import ActionTool
from magi.agent.tools.media import media_tools
from magi.agent.tools.memory import ForgetTool, RememberTool
from magi.agent.tools.system import system_tools
from magi.agent.tools.vision import ScreenshotTool
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    ChatReply,
    Intent,
    IntentId,
    ThinkMsg,
    ToolCall,
    ToolSpec,
    TurnContext,
    WakeSource,
)
from magi.core.actions import Registry
from magi.core.early import THINK_HUD

CTX = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC), mood=2)


class Barrier:
    """Só libera quando ``n`` ferramentas estão rodando ao mesmo tempo (sem relógio de verdade)."""

    def __init__(self, n: int) -> None:
        self.n = n
        self.running = 0
        self.event = asyncio.Event()

    async def wait(self) -> bool:
        self.running += 1
        if self.running >= self.n:
            self.event.set()
        try:
            await asyncio.wait_for(self.event.wait(), 0.5)
            return True
        except TimeoutError:
            return False


class FakeTool:
    def __init__(
        self,
        name: str,
        log: list[str],
        *,
        serial: bool = False,
        barrier: Barrier | None = None,
        result: ActionResult | None = None,
        boom: bool = False,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.spec = ToolSpec(name=name, description=name)
        self.danger = False
        self.serial = serial
        self.log = log
        self.barrier = barrier
        self.result = result
        self.boom = boom
        self.gate = gate
        self.cancelled = False

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        self.log.append(f"start:{self.name}")
        try:
            if self.barrier is not None and not await self.barrier.wait():
                return ActionResult(ok=False, speech="sozinha")
            if self.gate is not None:
                await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if self.boom:
            raise RuntimeError("quebrou")
        self.log.append(f"end:{self.name}")
        return self.result or ActionResult(ok=True, speech=f"ok {self.name}")


def agent(tools: list[FakeTool], *, paralelo: bool = True) -> GraphAgent:
    return GraphAgent(object(), tools, persona="x", ferramentas_paralelo=paralelo)  # type: ignore[arg-type]


def calls(*names: str) -> tuple[ToolCall, ...]:
    return tuple(ToolCall(id=f"c{i}", name=n, arguments={}) for i, n in enumerate(names, 1))


async def run_node(a: GraphAgent, *names: str) -> tuple[dict[str, Any], list[ThinkMsg]]:
    seen: list[ThinkMsg] = []
    token = THINK_HUD.set(seen.append)
    try:
        out = await a._tools_node(
            {"reply": ChatReply(text="", tool_calls=calls(*names)), "messages": [], "ctx": CTX, "text": "t"}
        )
    finally:
        THINK_HUD.reset(token)
    return out, seen


async def test_two_read_tools_run_together(caplog: pytest.LogCaptureFixture) -> None:
    log: list[str] = []
    b = Barrier(2)
    a = agent([FakeTool("search", log, barrier=b), FakeTool("news_query", log, barrier=b)])
    with caplog.at_level(logging.INFO, logger="magi.agent.graph"):
        out, seen = await run_node(a, "search", "news_query")
    assert [r.speech for r in out["results"]] == ["ok search", "ok news_query"]
    assert [m.tool_call_id for m in out["messages"]] == ["c1", "c2"]
    assert [(m.v, m.tool) for m in seen] == [("tool", "search"), ("tool", "news_query")]
    assert "espera: ferramentas search,news_query em paralelo" in caplog.text


async def test_flag_off_runs_in_series() -> None:
    log: list[str] = []
    gate = asyncio.Event()
    gate.set()
    a = agent([FakeTool("search", log, gate=gate), FakeTool("news_query", log, gate=gate)], paralelo=False)
    out, seen = await run_node(a, "search", "news_query")
    assert log == ["start:search", "end:search", "start:news_query", "end:news_query"]
    assert len(seen) == 2 and not out.get("pending")


async def test_serial_keeps_requested_order() -> None:
    log: list[str] = []
    b = Barrier(2)
    a = agent(
        [
            FakeTool("volume", log, serial=True),
            FakeTool("search", log, barrier=b),
            FakeTool("steam_game", log, barrier=b),
        ]
    )
    out, seen = await run_node(a, "volume", "search", "steam_game")
    assert [m.tool_call_id for m in out["messages"]] == ["c1", "c2", "c3"]
    assert [r.ok for r in out["results"]] == [True, True, True]
    assert sorted(m.tool for m in seen) == ["search", "steam_game", "volume"]
    assert log.index("end:volume") < log.index("end:search")


async def test_first_confirmation_in_order_wins_and_cancels_rest() -> None:
    log: list[str] = []
    gate = asyncio.Event()  # nunca abre: a segunda fica rodando até ser cancelada
    req = ActionRequest(intent=Intent(id=IntentId.VOLUME_SET.value), ctx=CTX)
    pend = ActionResult(ok=True, speech="Confirma?", needs_confirmation=True, on_confirm=req)
    first = FakeTool("search", log, result=pend)
    slow = FakeTool("news_query", log, gate=gate)
    out, _ = await run_node(agent([first, slow]), "search", "news_query")
    assert out == {"pending": pend}
    await asyncio.sleep(0)
    assert slow.cancelled


async def test_exception_becomes_error_result() -> None:
    log: list[str] = []
    a = agent([FakeTool("search", log, boom=True), FakeTool("news_query", log)])
    out, _ = await run_node(a, "search", "news_query")
    assert [(r.ok, r.speech) for r in out["results"]] == [(False, SAY_TOOL_ERROR), (True, "ok news_query")]


async def test_unknown_think_name_becomes_other_once_per_tool() -> None:
    log: list[str] = []
    a = agent([FakeTool("calc", log)], paralelo=False)
    _, seen = await run_node(a, "calc", "nao_existe")
    assert [(m.v, m.tool) for m in seen] == [("tool", "other")]


def test_media_and_pc_tools_are_serial() -> None:
    reg = Registry([])
    tools = [*system_tools(reg), *media_tools(reg)]
    assert tools and all(getattr(t, "serial", False) for t in tools)
    assert ActionTool.serial and RememberTool.serial and ForgetTool.serial and ScreenshotTool.serial
