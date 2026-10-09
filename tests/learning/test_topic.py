"""LM1.8 / CA-23: tema da sessão no núcleo (design §5.1; spec §10.1; LM-013).

- ``topic.build``: free sem bloco; interview com o texto fixo; game com ``GameWatcher``/Steam
  falsos traz nome e horas; sem jogo → último jogo das últimas 6 h (P12) ou fallback; news com
  repo falso traz títulos e **não** chama ``mark_delivered``; bloco ≤ 1500.
- Persona continua no prompt e o tema entra depois, em ``<topic_context>``.
- ``lm_topic`` (botão): grava na sessão, confirma a todos; mesmo tema só confirma.
- Abertura (P11): um turno do agente quando o estado fica livre; cancelada se o Pedro falar antes.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from magi.common.config import parse_config
from magi.common.contracts import (
    ActionResult,
    HudMessage,
    LmMsgMsg,
    LmSayMsg,
    LmTopicMsg,
    NewsItem,
    TurnContext,
)
from magi.core import actions
from magi.core.game_context import GameEvent, RunningGame
from magi.core.router import LocalRouter
from magi.core.steam_local import Achievement, GameStats
from magi.core.turn import TurnDeps, TurnPipeline
from magi.learning import persona
from magi.learning.config import LearningConfig
from magi.learning.contracts import Author, Topic
from magi.learning.intent_action import builder_of, wire
from magi.learning.repo import JsonlRepo
from magi.learning.topic import BLOCK_MAX, LABELS, NO_GAME, NO_NEWS, TopicBuilder
from magi.learning.wiring import OPENING_PROMPT, install

NOW = 1_800_000_000.0
NOW_DT = datetime.fromtimestamp(NOW, UTC)


class FakeWatcher:
    def __init__(self, game: RunningGame | None = None) -> None:
        self.game = game
        self.listeners: list = []

    def running(self) -> RunningGame | None:
        return self.game

    def subscribe(self, listener) -> None:
        self.listeners.append(listener)


class FakeSteam:
    def stats(self, appid: int, name: str) -> GameStats:
        ach = [Achievement("a", "First Blood", "x", got=True, unlocked_at=NOW - 3600),
               Achievement("b", "Second", "y")]
        return GameStats(appid=appid, name=name, minutes=125 * 60, achievements=ach)


class FakeNews:
    def __init__(self, items: list[NewsItem]) -> None:
        self.items = items
        self.marked: list[int] = []

    async def undelivered(self, levels, limit: int = 5) -> list[NewsItem]:
        return [i for i in self.items if i.delivered_at is None][:limit]

    async def delivered_recent(self, limit: int = 50) -> list[NewsItem]:
        return [i for i in self.items if i.delivered_at is not None][:limit]

    async def mark_delivered(self, item_id: int, at: datetime) -> None:  # nunca deve ser chamado
        self.marked.append(item_id)

    async def franchise_prefs(self) -> list:
        return []


def _item(i: int, title: str, hours_ago: float, *, delivered: bool = False,
          spoiler: dict | None = None) -> NewsItem:
    return NewsItem(title=title, summary=f"Summary of {title}. More text.", id=i,
                    spoiler={"has": False} if spoiler is None else spoiler,
                    first_seen=NOW_DT - timedelta(hours=hours_ago),
                    delivered_at=NOW_DT if delivered else None)


def _builder(**kw) -> TopicBuilder:
    return TopicBuilder(clock=lambda: NOW, now=lambda: NOW_DT, **kw)


# ---------------------------------------------------------------------------------------------
# topic.build (CA-23)
# ---------------------------------------------------------------------------------------------


async def test_free_sem_bloco() -> None:
    ctx = await _builder().build(Topic.FREE)
    assert ctx.topic is Topic.FREE and ctx.requested is Topic.FREE
    assert ctx.block is None and ctx.detail is None and ctx.label == "FREE TALK"


async def test_interview_texto_fixo_e_vaga() -> None:
    ctx = await _builder().build("interview")
    assert ctx.topic is Topic.INTERVIEW and ctx.label == LABELS[Topic.INTERVIEW]
    assert ctx.block is not None and "software engineering" in ctx.block and "{role}" not in ctx.block
    ctx = await _builder(interview_role="a Rust embedded role").build(Topic.INTERVIEW)
    assert ctx.block is not None and "a Rust embedded role" in ctx.block


async def test_game_aberto_traz_nome_e_horas() -> None:
    game = RunningGame(name="Elden Ring", pid=1, since=NOW - 50 * 60, appid=1245620)
    ctx = await _builder(game=FakeWatcher(game), steam=FakeSteam()).build(Topic.GAME)
    assert ctx.topic is Topic.GAME and ctx.detail is None
    assert ctx.block is not None and "Elden Ring" in ctx.block
    assert "50 minutes" in ctx.block and "125 horas" in ctx.block


async def test_game_sem_jogo_usa_o_ultimo_das_6h_senao_fallback() -> None:
    watcher = FakeWatcher(None)
    b = _builder(game=watcher, steam=FakeSteam())
    ctx = await b.build(Topic.GAME)
    assert ctx.topic is Topic.FREE and ctx.requested is Topic.GAME and ctx.detail == NO_GAME
    assert ctx.block is None

    closed = RunningGame(name="Hades", pid=2, since=NOW - 9000, appid=1145360)
    (listener,) = watcher.listeners
    listener(GameEvent("closed", closed, NOW - 2 * 3600))
    ctx = await b.build(Topic.GAME)
    assert ctx.topic is Topic.GAME and ctx.block is not None
    assert "you were playing Hades" in ctx.block

    listener(GameEvent("closed", closed, NOW - 7 * 3600))
    ctx = await b.build(Topic.GAME)
    assert ctx.topic is Topic.FREE and ctx.detail == NO_GAME


async def test_news_traz_titulos_sem_marcar_entregue() -> None:
    repo = FakeNews([
        _item(1, "Silksong release date announced", 2),
        _item(2, "New Ghibli film", 5, delivered=True),
        _item(3, "Old story", 30),
        _item(4, "Unclassified leak", 1, spoiler={}),
    ])
    ctx = await _builder(news=repo).build(Topic.NEWS)
    assert ctx.topic is Topic.NEWS and ctx.block is not None
    assert "Silksong release date announced" in ctx.block and "New Ghibli film" in ctx.block
    assert "Old story" not in ctx.block and "Unclassified leak" not in ctx.block
    assert "Summary of New Ghibli film." in ctx.block
    assert repo.marked == []


async def test_news_sem_item_ou_sem_banco_cai_em_free() -> None:
    for b in (_builder(news=FakeNews([_item(1, "Old", 48)])), _builder()):
        ctx = await b.build(Topic.NEWS)
        assert ctx.topic is Topic.FREE and ctx.requested is Topic.NEWS and ctx.detail == NO_NEWS


async def test_bloco_no_maximo_1500() -> None:
    repo = FakeNews([_item(i, "Very long headline " * 30, 1) for i in range(1, 6)])
    ctx = await _builder(news=repo).build(Topic.NEWS)
    assert ctx.block is not None and len(ctx.block) <= BLOCK_MAX


def test_persona_continua_e_tema_vem_depois() -> None:
    out = persona.compose("BASE", active=True, topic="x" * 3000)
    assert out.startswith("BASE") and persona.block() in out
    assert out.index(persona.block()) < out.index("<topic_context>")
    inner = out.split("<topic_context>\n", 1)[1].split("\n</topic_context>", 1)[0]
    assert len(inner) <= BLOCK_MAX
    assert persona.compose("BASE", active=False, topic="x") == "BASE"


# ---------------------------------------------------------------------------------------------
# lm_topic no núcleo e abertura (P11)
# ---------------------------------------------------------------------------------------------


class SinkHud:
    def __init__(self) -> None:
        self.sent: list[HudMessage] = []
        self.on_learning = None

    async def send(self, msg: HudMessage) -> None:
        self.sent.append(msg)

    def of(self, kind: type) -> list:
        return [m for m in self.sent if isinstance(m, kind)]


class FakeAgent:
    def __init__(self) -> None:
        self._persona = "BASE"
        self.asked: list[tuple[str, str | None]] = []

    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        self.asked.append((text, self._persona))
        return ActionResult(ok=True, speech="So, what are you up to in Elden Ring?")


def _clock() -> datetime:
    return NOW_DT


@pytest.fixture
def rig(tmp_path):
    agent = FakeAgent()
    deps = TurnDeps(router=LocalRouter(None), agent=agent)
    game = RunningGame(name="Elden Ring", pid=1, since=NOW - 600, appid=1245620)
    found = wire(parse_config({}), deps, [], topics=_builder(game=FakeWatcher(game), steam=FakeSteam()))
    deps.actions = actions.Registry(found)
    from magi.learning.intent_action import wire_persona

    assert wire_persona(parse_config({}), deps)
    pipeline = TurnPipeline(deps)
    hud = SinkHud()
    w = install(LearningConfig(storage="jsonl"), hud, pipeline, repo=JsonlRepo(tmp_path),
                clock=_clock, start=False)
    assert w is not None
    w.opening_poll_s = 0.01
    return w, hud, agent


async def test_botao_grava_confirma_e_abre_o_tema(rig) -> None:
    w, hud, agent = rig
    await w.set_mode(True)
    assert hud.of(LmTopicMsg)[-1].topic is Topic.FREE
    free = [False]
    w.listening = lambda: free[0]

    await w.on_learning(LmTopicMsg(Topic.GAME))
    (msg,) = [m for m in hud.of(LmTopicMsg) if m.topic is Topic.GAME]
    assert msg.requested is Topic.GAME and msg.label == LABELS[Topic.GAME] and msg.detail is None
    info = await w.repo.get_session(w.session.id)
    assert info is not None and info.topic is Topic.GAME
    assert builder_of(w.pipeline.deps) is w.topics

    await asyncio.sleep(0.05)
    assert agent.asked == []  # espera o estado livre
    free[0] = True
    await w.wait_idle()
    ((prompt, used),) = agent.asked
    assert prompt == OPENING_PROMPT and used is not None
    assert "<topic_context>" in used and "Elden Ring" in used
    her = hud.of(LmMsgMsg)[-1]
    assert her.author is Author.CONDESSA and "Elden Ring" in her.text

    n = len(hud.of(LmTopicMsg))
    await w.on_learning(LmTopicMsg(Topic.GAME))  # mesmo tema: só confirma
    await w.wait_idle()
    assert len(hud.of(LmTopicMsg)) == n + 1 and len(agent.asked) == 1


async def test_abertura_cancelada_se_o_pedro_fala_antes(rig) -> None:
    w, _, agent = rig
    await w.set_mode(True)
    w.listening = lambda: False
    await w.on_learning(LmTopicMsg(Topic.INTERVIEW))
    await w.on_learning(LmSayMsg("hi there"))
    await w.wait_idle()
    assert [t for t, _ in agent.asked] == ["hi there"]


async def test_fallback_de_jogo_confirma_detail(tmp_path) -> None:
    hud = SinkHud()
    deps = TurnDeps(router=LocalRouter(None), agent=FakeAgent())
    w = install(LearningConfig(storage="jsonl"), hud, TurnPipeline(deps), repo=JsonlRepo(tmp_path),
                clock=_clock, start=False)
    assert w is not None
    await w.set_mode(True)
    await w.on_learning(LmTopicMsg(Topic.GAME))
    last = hud.of(LmTopicMsg)[-1]
    assert last.topic is Topic.FREE and last.requested is Topic.GAME and last.detail == NO_GAME
    assert w.session.topic_block is None
    await w.wait_idle()
    assert deps.agent.asked == []
