"""Testes do grafo do agente com ChatProvider falso roteirizado (tarefa 3.4)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from magi.agent.graph import (
    MAX_STEPS,
    SAY_BUDGET,
    SAY_PROVIDER_FAILED,
    GraphAgent,
    short_speech,
)
from magi.agent.prompt import MAX_PROMPT_TOKENS, GameContext, count_message_tokens
from magi.agent.tools.base import ActionTool, Mapped, ToolArgsError
from magi.agent.tools.system import map_hud, map_open_game, map_volume, system_tools
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    BudgetExceeded,
    ChatMessage,
    ChatReply,
    IntentId,
    ProviderError,
    ProviderTask,
    ToolCall,
    ToolSpec,
    TurnContext,
    WakeSource,
)
from magi.core.actions import Registry

CTX = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC), mood=2)


class FakeChat:
    name = "fake"
    model = "fake-1"
    free_tier = False

    def __init__(self, script: Sequence[ChatReply | Exception]) -> None:
        self.script = list(script)
        self.calls: list[tuple[list[ChatMessage], tuple[ToolSpec, ...], bool]] = []

    async def chat(self, messages, *, tools=(), json_mode=False, personal):
        self.calls.append((list(messages), tuple(tools), personal))
        item = self.script.pop(0) if self.script else ChatReply(text="")
        if isinstance(item, Exception):
            raise item
        return item


class FakeProviders:
    def __init__(self, chat: FakeChat) -> None:
        self._chat = chat
        self.tasks: list[ProviderTask] = []

    def chat(self, task: ProviderTask = ProviderTask.AGENT) -> FakeChat:
        self.tasks.append(task)
        return self._chat


class Recorder:
    """Handler falso: registra os pedidos, sem tocar no sistema."""

    def __init__(self, intents: Sequence[str], speech: str = "Feito.") -> None:
        self.intents = frozenset(intents)
        self.speech = speech
        self.reqs: list[ActionRequest] = []

    async def run(self, req: ActionRequest) -> ActionResult:
        self.reqs.append(req)
        return ActionResult(ok=True, speech=self.speech)


def call(name: str, i: int = 1, **args) -> ToolCall:
    return ToolCall(id=f"c{i}", name=name, arguments=args)


def make(script, *, extra_tools=(), game=None):
    chat = FakeChat(script)
    games = Recorder([IntentId.GAME_OPEN], "Abrindo Hades")
    vol = Recorder([IntentId.VOLUME_SET, IntentId.VOLUME_MUTE, IntentId.VOLUME_UNMUTE])
    reg = Registry([games, vol])
    tools = [*system_tools(reg), *extra_tools]
    agent = GraphAgent(FakeProviders(chat), tools, game=game, persona="Você é a Magi. Responda curto.")
    return agent, chat, games, vol, reg


async def test_simple_question():
    text = "O Hades saiu em 2020. É um roguelike da Supergiant. Muito elogiado pela crítica."
    agent, chat, *_ = make([ChatReply(text=text)])
    res = await agent.answer("quando saiu o hades?", CTX)
    assert res.ok and res.full_text == text
    assert res.speech == "O Hades saiu em 2020. É um roguelike da Supergiant."
    assert len(chat.calls) == 1
    msgs, tools, personal = chat.calls[0]
    assert personal is True
    assert {t.name for t in tools} == {"open_game", "hud", "volume"}
    assert msgs[-1] == ChatMessage(role="user", content="quando saiu o hades?")


async def test_tool_use_runs_action_and_feeds_result_back():
    agent, chat, games, *_ = make(
        [
            ChatReply(text="", tool_calls=(call("open_game", game="hades"),)),
            ChatReply(text="Pronto, bom jogo!"),
        ]
    )
    res = await agent.answer("abre aquele do zagreus", CTX)
    assert res.ok and res.speech == "Pronto, bom jogo!"
    assert len(games.reqs) == 1
    req = games.reqs[0]
    assert req.intent.id == IntentId.GAME_OPEN and req.intent.slot("game").raw == "hades"
    assert req.ctx is CTX and not req.confirmed
    second = chat.calls[1][0]
    assert second[-2].role == "assistant" and second[-2].tool_calls[0].name == "open_game"
    assert second[-1].role == "tool" and second[-1].tool_call_id == "c1"
    assert "Abrindo Hades" in second[-1].content


async def test_tool_result_used_when_model_says_nothing():
    agent, _, _, vol, _ = make(
        [ChatReply(text="", tool_calls=(call("volume", delta=-10),)), ChatReply(text="")]
    )
    res = await agent.answer("abaixa um pouco", CTX)
    assert res.ok and res.speech == "Feito."
    assert vol.reqs[0].intent.slot("volume").value == "-10"


async def test_dangerous_tool_needs_confirmation_without_running():
    closer = Recorder([IntentId.GAME_CLOSE])
    reg = Registry([closer])
    spec = ToolSpec("close_game", "Fecha o jogo", {"type": "object"})
    tool = ActionTool(
        spec, lambda a: Mapped(IntentId.GAME_CLOSE.value, confirm_speech="Fecho o jogo?"), reg, danger=True
    )
    agent, chat, *_ = make(
        [ChatReply(text="", tool_calls=(call("close_game"),)), ChatReply(text="não deveria chegar")],
        extra_tools=[tool],
    )
    res = await agent.answer("fecha isso", CTX)
    assert res.needs_confirmation and res.dangerous and res.speech == "Fecho o jogo?"
    assert closer.reqs == []
    assert len(chat.calls) == 1
    assert res.on_confirm is not None and res.on_confirm.confirmed
    assert res.on_confirm.intent.id == IntentId.GAME_CLOSE and res.on_confirm.intent.danger
    # o núcleo executa on_confirm depois do "confirma"
    assert (await reg.run(res.on_confirm)).ok and len(closer.reqs) == 1


async def test_step_limit():
    looping = [ChatReply(text="", tool_calls=(call("volume", i, level=50),)) for i in range(10)]
    agent, chat, _, vol, _ = make(looping)
    res = await agent.answer("fica mexendo no volume", CTX)
    assert len(chat.calls) == MAX_STEPS
    assert len(vol.reqs) == MAX_STEPS - 1
    assert chat.calls[-1][1] == ()  # última chamada sem ferramentas
    assert res.speech


async def test_budget_exceeded():
    agent, *_ = make([BudgetExceeded("teto")])
    res = await agent.answer("me conta uma piada", CTX)
    assert not res.ok and res.speech == SAY_BUDGET == "Bati o teto do mês, só comandos locais agora."


async def test_provider_error():
    agent, *_ = make([ChatReply(text="", tool_calls=(call("hud", action="open"),)), ProviderError("500")])
    res = await agent.answer("abre o hud e me explica", CTX)
    assert not res.ok and res.speech == SAY_PROVIDER_FAILED


async def test_prompt_within_limit_with_game_and_history():
    game = GameContext(name="Elden Ring", genre="soulslike", session_minutes=90)
    agent = GraphAgent(
        FakeProviders(chat := FakeChat([ChatReply(text="Resposta " * 80 + ".")] * 3)), game=lambda: game
    )
    for _ in range(3):
        await agent.answer("como passo da Malenia? " * 5, CTX)
    for msgs, _, _ in chat.calls:
        assert count_message_tokens(msgs) <= MAX_PROMPT_TOKENS
    assert any("Elden Ring" in m.content for m in chat.calls[-1][0] if m.role == "system")
    assert sum(m.role == "assistant" for m in chat.calls[-1][0]) >= 1  # histórico entra


def test_short_speech():
    assert short_speech("Um. Dois! Três? Quatro.") == "Um. Dois!"
    assert short_speech("sem ponto") == "sem ponto"


def test_mappers():
    assert map_open_game({"appid": 1145360}).slots[0].value == "1145360"
    with pytest.raises(ToolArgsError):
        map_open_game({})
    assert map_hud({"action": "idle"}).args == {"view": "idle"}
    assert map_hud({"action": "detail", "detail": "gpu"}).slots[0].value == "gpu"
    assert map_hud({"action": "rgb_sync", "on": False}).slots[0].value == "off"
    assert map_volume({"mute": True}).intent_id == IntentId.VOLUME_MUTE
    assert map_volume({"level": "30"}).slots[0].value == "30"
    assert map_volume({"delta": 10}).slots[0].value == "+10"
    with pytest.raises(ToolArgsError):
        map_volume({"level": 150})


async def test_bad_tool_args_become_failed_result():
    agent, chat, *_ = make(
        [ChatReply(text="", tool_calls=(call("hud", action="dance"),)), ChatReply(text="Ops.")]
    )
    res = await agent.answer("faz o hud dançar", CTX)
    assert res.speech == "Ops."
    assert '"ok": false' in chat.calls[1][0][-1].content
