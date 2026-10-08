"""LM1.4 / CA-06: persona do Learning Mode no prompt do agente (spec §4 item 4, CNV-002).

Com sessão ativa o system prompt ganha o bloco de ``prompts/persona.md`` (sem correção explícita);
sem sessão o prompt fica igual. O ``FakeModel`` de persona responde como o prompt manda: com o
bloco, recast natural; sem ele, corrige à moda antiga ("you should say..."). Assim o teste prova
que é o bloco que muda a resposta.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from magi.agent.graph import GraphAgent
from magi.agent.prompt import load_persona
from magi.common.config import parse_config
from magi.common.contracts import (
    ActionResult,
    ChatMessage,
    ChatReply,
    HudMessage,
    LmMsgMsg,
    LmSayMsg,
    ProviderTask,
    RouteKind,
    RouteResult,
    TurnContext,
    WakeSource,
)
from magi.core.turn import TurnDeps, TurnPipeline
from magi.learning import persona
from magi.learning.config import LearningConfig
from magi.learning.contracts import Author
from magi.learning.intent_action import wire_persona
from magi.learning.repo import JsonlRepo
from magi.learning.wiring import install

BANNED = ("you should say", "correct form")

#: 10 frases erradas do Pedro (gravadas na sessão).
WRONG = [
    "Yesterday I have went to the park",
    "She don't like football",
    "I am agree with you",
    "He go to work by bus every days",
    "I didn't went to the party",
    "We was very tired after the match",
    "I have 30 years old",
    "My friends is coming tomorrow",
    "I am living here since 2015",
    "Can you explain me the rules?",
]


class PersonaChat:
    """FakeModel: obedece ao bloco de persona quando ele está no system prompt."""

    name = "fake"
    model = "fake-persona"
    free_tier = False

    def __init__(self) -> None:
        self.systems: list[str] = []

    async def chat(self, messages: Sequence[ChatMessage], *, tools=(), json_mode=False, personal):
        system = next((m.content or "" for m in messages if m.role == "system"), "")
        self.systems.append(system)
        user = next((m.content or "" for m in reversed(messages) if m.role == "user"), "")
        if persona.block() in system:
            return ChatReply(text=f"Oh, really? Tell me more about that. What happened next? ({len(user)})")
        return ChatReply(text=f"You should say it differently. The correct form is: {user}.")


class FakeProviders:
    def __init__(self, chat: PersonaChat) -> None:
        self._chat = chat

    def chat(self, task: ProviderTask = ProviderTask.AGENT) -> PersonaChat:
        return self._chat


class AgentRouter:
    def route(self, text: str, ctx: TurnContext) -> RouteResult:
        return RouteResult(RouteKind.AGENT, text)


class SinkHud:
    def __init__(self) -> None:
        self.sent: list[HudMessage] = []
        self.on_learning = None

    async def send(self, msg: HudMessage) -> None:
        self.sent.append(msg)


def _clock() -> datetime:
    return datetime(2026, 10, 8, 20, 0, tzinfo=UTC)


CTX = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=_clock(), mood=2)


@pytest.fixture
def rig(tmp_path):
    chat = PersonaChat()
    agent = GraphAgent(FakeProviders(chat))
    deps = TurnDeps(router=AgentRouter(), agent=agent)
    pipeline = TurnPipeline(deps)
    hud = SinkHud()
    w = install(LearningConfig(storage="jsonl"), hud, pipeline, repo=JsonlRepo(tmp_path),
                clock=_clock, start=False)
    assert w is not None
    assert wire_persona(parse_config({}), deps)  # o mesmo caminho do ``assemble``
    return w, hud, agent, chat


# ---------------------------------------------------------------------------------------------


def test_bloco_de_persona_proibe_correcao_explicita() -> None:
    text = persona.block()
    assert text.startswith("## Learning Mode")
    assert "British English" in text and "open question" in text
    assert '"you should say"' in text and '"the correct form is"' in text  # citadas como proibidas
    assert "recast" in text


def test_compose_so_com_sessao_ativa() -> None:
    assert persona.compose("BASE", active=False) == "BASE"
    on = persona.compose("BASE", active=True)
    assert on.startswith("BASE\n\n") and persona.block() in on
    with_topic = persona.compose("BASE", active=True, topic="Game: Silksong")
    assert "<topic_context>\nGame: Silksong\n</topic_context>" in with_topic


async def test_ca06_dez_frases_erradas_sem_correcao_explicita(rig) -> None:
    w, hud, _, chat = rig
    await w.set_mode(True)
    for text in WRONG:
        await hud.on_learning(LmSayMsg(text))
        await w.wait_idle()

    msgs = [m for m in hud.sent if isinstance(m, LmMsgMsg)]
    you = [m for m in msgs if m.author == Author.YOU]
    condessa = [m for m in msgs if m.author == Author.CONDESSA]
    assert [m.text for m in you] == WRONG  # as 10 frases erradas foram gravadas
    assert len(condessa) == 10
    for m in condessa:
        low = m.text.lower()
        assert not any(b in low for b in BANNED), m.text
    # todo prompt do turno levou a persona normal + o bloco do Learning Mode
    assert len(chat.systems) == 10
    for system in chat.systems:
        assert load_persona() in system and persona.block() in system
    stored = await w.repo.recent_messages(w.session.id)
    assert sum(1 for m in stored if m.author == Author.YOU) == 10


async def test_fora_da_sessao_prompt_fica_igual(rig) -> None:
    w, _, agent, chat = rig
    res = await agent.answer("I have went home", CTX)
    assert persona.block() not in chat.systems[-1]
    assert "correct form" in res.speech.lower()  # o FakeModel sem o bloco corrige (controle)

    await w.set_mode(True)
    res = await agent.answer("I have went home", CTX)
    assert persona.block() in chat.systems[-1]
    assert not any(b in res.speech.lower() for b in BANNED)

    await w.set_mode(False, "voice")
    await agent.answer("I have went home", CTX)
    assert persona.block() not in chat.systems[-1]


def test_install_nao_embrulha_duas_vezes_nem_agente_sem_persona() -> None:
    agent = GraphAgent(FakeProviders(PersonaChat()))
    assert persona.install(agent, lambda: True)
    assert not persona.install(agent, lambda: True)

    class Other:
        async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
            return ActionResult(ok=True)

    assert not persona.install(Other(), lambda: True)


def test_desligado_nao_instala() -> None:
    agent = GraphAgent(FakeProviders(PersonaChat()))
    deps = TurnDeps(agent=agent)
    assert not wire_persona(parse_config({"learning": {"enabled": False}}), deps)
    assert "answer" not in vars(agent)
