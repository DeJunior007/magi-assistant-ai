"""Memórias do agente sem banco (tarefa 4.1): gravar, lembrar no outro dia, esquecer, limiar, ≤ 5."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from magi.agent.graph import GraphAgent
from magi.agent.tools.memory import SAY_FORGOT, SAY_NOTHING, ForgetHandler, memory_tools
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    ChatReply,
    Intent,
    IntentId,
    MemoriesRepo,
    Memory,
    ToolCall,
    TurnContext,
    TurnRecord,
    WakeSource,
)
from magi.core.turn import TurnDeps, TurnPipeline
from magi.memory.memories_repo import InMemoryMemoriesRepo, MemoryStore
from tests.agent.test_graph import FakeChat, FakeProviders
from tests.memory.fake_embed import FakeEmbed

CTX = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC), mood=2)
PERSONA = "Você é a Magui."


def store(repo=None, **kw) -> MemoryStore:
    return MemoryStore(repo if repo is not None else InMemoryMemoriesRepo(), FakeEmbed(), **kw)


def agent_with(mem: MemoryStore, script) -> tuple[GraphAgent, FakeChat]:
    chat = FakeChat(script)
    agent = GraphAgent(FakeProviders(chat), memory_tools(mem), persona=PERSONA, memory=mem)
    return agent, chat


def system_text(chat: FakeChat, i: int = 0) -> str:
    msgs, _, _ = chat.calls[i]
    return "\n".join(m.content for m in msgs if m.role == "system")


def memory_lines(text: str) -> list[str]:
    if "## Memórias" not in text:
        return []
    block = text.split("## Memórias", 1)[1].split("\n## ", 1)[0]
    return [ln for ln in block.splitlines() if ln.startswith("- ")]


async def test_fact_told_one_day_is_recalled_the_next():
    assert isinstance(InMemoryMemoriesRepo(), MemoriesRepo)
    repo = InMemoryMemoriesRepo()

    # Dia 1: o modelo decide guardar o fato com a ferramenta remember.
    day1 = store(repo)
    remember = ToolCall(
        id="c1", name="remember", arguments={"fact": "Pedro está jogando Elden Ring", "kind": "game"}
    )
    agent, chat = agent_with(
        day1, [ChatReply(text="", tool_calls=(remember,)), ChatReply(text="Boa, anotado.")]
    )
    res = await agent.answer("tô jogando elden ring agora", CTX)
    assert res.ok and res.speech == "Boa, anotado."
    assert "remember" in {t.name for t in chat.calls[0][1]}
    await day1.drain()

    # Dia 2: processo novo (store e agente novos), mesmo repositório.
    day2 = store(repo)
    agent2, chat2 = agent_with(day2, [ChatReply(text="Elden Ring.")])
    await agent2.answer("lembra qual jogo do elden ring eu tava jogando?", CTX)
    assert memory_lines(system_text(chat2)) == ["- Pedro está jogando Elden Ring"]


async def test_remember_does_not_block_and_skips_empty():
    gate = asyncio.Event()
    embed = FakeEmbed()

    async def slow(texts):
        await gate.wait()
        return await embed(texts)

    mem = MemoryStore(InMemoryMemoriesRepo(), slow)
    assert mem.remember("Pedro gosta de café") is True  # volta na hora
    assert mem.remember("   ") is False
    assert await mem.recent() == []
    gate.set()
    await mem.drain()
    assert [m.body for m in await mem.recent()] == ["Pedro gosta de café"]


async def test_forget_this_removes_last_memory():
    mem = store()
    mem.remember("Pedro gosta de café")
    mem.remember("Pedro está jogando Hades")
    await mem.drain()
    handler = ForgetHandler(mem)
    req = ActionRequest(intent=Intent(id=IntentId.MEMORY_FORGET.value), ctx=CTX, text="esquece isso")
    res = await handler.run(req)
    assert res.ok and res.speech == SAY_FORGOT and "Hades" in res.full_text
    assert [m.body for m in await mem.recent()] == ["Pedro gosta de café"]
    assert await mem.relevant("hades") == []
    # "esquece isso" sem nada novo apaga a mais recente; depois não sobra nada.
    assert (await handler.run(req)).speech == SAY_FORGOT
    assert (await handler.run(req)).speech == SAY_NOTHING


async def test_forget_what_removes_most_similar():
    mem = store()
    for fact in ("Pedro gosta de café", "Pedro está jogando Hades", "Pedro torce pro Flamengo"):
        mem.remember(fact)
    await mem.drain()
    agent, chat = agent_with(mem, [])
    tools = {t.name: t for t in memory_tools(mem)}
    res = await tools["forget"].run({"what": "jogando hades"}, CTX)
    assert res.ok and res.speech == SAY_FORGOT
    assert sorted(m.body for m in await mem.recent()) == ["Pedro gosta de café", "Pedro torce pro Flamengo"]
    assert (await tools["forget"].run({"what": "pizza de calabresa"}, CTX)).ok is False


async def test_threshold_keeps_irrelevant_memory_out_of_prompt():
    mem = store()
    mem.remember("Pedro gosta de café sem açúcar")
    await mem.drain()
    assert await mem.relevant("qual a capital da frança") == []
    agent, chat = agent_with(mem, [ChatReply(text="Paris.")])
    await agent.answer("qual a capital da frança", CTX)
    assert memory_lines(system_text(chat)) == []
    hits = await mem.relevant("café com açúcar")
    assert [m.body for m in hits] == ["Pedro gosta de café sem açúcar"] and hits[0].score > mem.min_score


async def test_prompt_gets_at_most_five_memories():
    mem = store(min_score=0.1)
    for i in range(8):
        mem.remember(f"Pedro zerou elden ring na build {i} numero{i}")
    await mem.drain()
    assert len(await mem.relevant("elden ring")) == 5
    agent, chat = agent_with(mem, [ChatReply(text="Várias vezes.")])
    await agent.answer("quantas vezes eu zerei elden ring?", CTX)
    assert len(memory_lines(system_text(chat))) == 5


async def test_near_duplicate_replaces_old_fact():
    mem = store()
    mem.remember("Pedro está jogando Elden Ring")
    await mem.drain()
    mem.remember("pedro esta jogando elden ring")
    await mem.drain()
    assert [m.body for m in await mem.recent()] == ["pedro esta jogando elden ring"]


async def test_search_failure_does_not_break_the_turn():
    async def broken(texts):
        raise RuntimeError("sem rede")

    mem = MemoryStore(InMemoryMemoriesRepo(), broken)
    assert await mem.relevant("oi") == []
    agent, chat = agent_with(mem, [ChatReply(text="Oi!")])
    assert (await agent.answer("oi", CTX)).ok
    mem.remember("Pedro gosta de café")
    await mem.drain()  # falha logada, nada gravado
    assert await mem.recent() == []


class FakeTurns:
    def __init__(self) -> None:
        self.rows: list[TurnRecord] = []

    async def add(self, turn: TurnRecord) -> int:
        self.rows.append(turn)
        return len(self.rows)


class EchoAgent:
    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        return ActionResult(ok=True, speech="ok", full_text=f"resposta: {text}")


async def test_pipeline_records_turn_history_in_background():
    from magi.common.contracts import Transcript

    turns = FakeTurns()
    pipe = TurnPipeline(TurnDeps(agent=EchoAgent(), turns=turns))  # type: ignore[arg-type]
    res = await pipe.respond(Transcript(heard="ola magui", final="olá magui"), CTX)
    assert res.ok
    await asyncio.gather(*pipe._tasks)
    [rec] = turns.rows
    assert (rec.satellite, rec.text_heard, rec.text_final, rec.reply) == (
        "pc",
        "ola magui",
        "olá magui",
        "resposta: olá magui",
    )
    assert rec.intent is None and rec.routed_local is False and rec.mood == 2
    await pipe.respond(Transcript.raw(""), CTX)  # fala vazia não entra no histórico
    assert len(turns.rows) == 1


def test_memory_dataclass_has_score():
    assert Memory(kind="fact", body="x").score is None
