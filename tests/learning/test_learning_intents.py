"""LM1.4 / CA-05b: entrar/sair do Learning Mode por voz (design §10, spec §10, LM-005, P8).

- Frases PT e EN da tabela de design §10 casam ``learning.start``/``learning.stop`` no roteador
  local; 10 frases de conversa em inglês com "session"/"class"/"lesson" não casam.
- A ação usa o mesmo caminho do botão (``set_mode``) com ``end_reason = "voice"``; já no estado
  pedido, só confirma. Resposta curta no i18n en-GB.
- ``[learning] enabled = false``: as frases somem do roteador e nada é registrado.
- Sem atalho global nem comando de terminal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from magi.common.config import parse_config
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    HudMessage,
    Intent,
    IntentId,
    LmModeMsg,
    LmSessionMsg,
    RouteKind,
    Transcript,
    TurnContext,
    WakeSource,
)
from magi.core import actions, i18n
from magi.core.router import LocalRouter, load_intents
from magi.core.turn import TurnDeps, TurnPipeline
from magi.learning import intent_action
from magi.learning.config import LearningConfig
from magi.learning.intent_action import LearningIntentAction, wire, wiring_of
from magi.learning.repo import JsonlRepo
from magi.learning.wiring import install

ROOT = Path(__file__).resolve().parents[2]

START_PT = ["modo aula", "modo de estudo", "vamos estudar inglês", "bora estudar inglês",
            "aula de inglês", "começar a aula"]
START_EN = ["learning mode", "english class", "english lesson", "start the lesson", "let's study english"]
STOP_PT = ["encerrar aula", "encerra a aula", "sair do modo aula", "sair do modo de estudo", "fim da aula"]
STOP_EN = ["end session", "end the class", "end the lesson", "exit learning mode", "stop learning mode"]

#: Conversa em inglês com "session"/"class"/"lesson": vai ao agente (spec §11).
CHAT = [
    "the session ended late",
    "I had a long session at the gym",
    "my english class was boring today",
    "we had a lesson about history",
    "the class was cancelled",
    "my session at work ended early",
    "I learned a lesson today",
    "that was a great gaming session",
    "end of the session was weird",
    "she ended the class early",
]


@pytest.fixture(scope="module")
def router() -> LocalRouter:
    return LocalRouter(None)


# ---------------------------------------------------------------------------------------------
# Roteador (CA-05b)
# ---------------------------------------------------------------------------------------------


def test_ids_no_contrato_e_no_yaml() -> None:
    assert IntentId.LEARNING_START == "learning.start" and IntentId.LEARNING_STOP == "learning.stop"
    ids = {s.id for s in load_intents()}
    assert {IntentId.LEARNING_START.value, IntentId.LEARNING_STOP.value} <= ids


@pytest.mark.parametrize("text", START_PT + START_EN + ["Magui, modo aula", "Let's study English."])
def test_frases_de_entrada_casam(router: LocalRouter, text: str) -> None:
    res = router.route(text)
    assert res.kind is RouteKind.LOCAL, (text, res)
    assert res.intent is not None and res.intent.id == IntentId.LEARNING_START


@pytest.mark.parametrize("text", STOP_PT + STOP_EN + ["End session."])
def test_frases_de_saida_casam(router: LocalRouter, text: str) -> None:
    res = router.route(text)
    assert res.kind is RouteKind.LOCAL, (text, res)
    assert res.intent is not None and res.intent.id == IntentId.LEARNING_STOP


@pytest.mark.parametrize("text", CHAT)
def test_conversa_com_session_class_lesson_nao_casa(router: LocalRouter, text: str) -> None:
    res = router.route(text)
    assert res.kind is RouteKind.AGENT, (text, res)


# ---------------------------------------------------------------------------------------------
# Ação (mesmo caminho do botão)
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
        self.asked: list[str] = []

    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        self.asked.append(text)
        return ActionResult(ok=True, speech="Lovely.")


def _clock() -> datetime:
    return datetime(2026, 10, 8, 20, 0, tzinfo=UTC)


def _ctx() -> TurnContext:
    return TurnContext(satellite="sala", source=WakeSource.PTT, started_at=_clock())


@pytest.fixture
def rig(tmp_path):
    """Pipeline real (roteador + registro de ações) com a ação registrada por ``wire``."""
    agent = FakeAgent()
    deps = TurnDeps(router=LocalRouter(None), agent=agent)
    found = wire(parse_config({}), deps, [])
    deps.actions = actions.Registry(found)
    pipeline = TurnPipeline(deps)
    hud = SinkHud()
    w = install(LearningConfig(storage="jsonl"), hud, pipeline, repo=JsonlRepo(tmp_path),
                clock=_clock, start=False)
    assert w is not None and wiring_of(deps) is w
    return pipeline, w, hud, agent


async def _say(pipeline: TurnPipeline, text: str) -> ActionResult:
    return await pipeline.respond(Transcript.raw(text), _ctx())


async def test_voz_entra_e_sai_pelo_mesmo_caminho_do_botao(rig) -> None:
    pipeline, w, hud, agent = rig
    res = await _say(pipeline, "english class")
    assert res.ok and res.speech == intent_action.SAY_ON
    assert w.session.active and hud.of(LmModeMsg) == [LmModeMsg(True)]
    (sess,) = hud.of(LmSessionMsg)
    sid = sess.id

    res = await _say(pipeline, "encerrar aula")
    assert res.ok and res.speech == intent_action.SAY_OFF
    assert not w.session.active and hud.of(LmModeMsg)[-1] == LmModeMsg(False)
    info = await w.repo.get_session(sid)
    assert info is not None and info.end_reason == "voice"
    assert agent.asked == []  # nada foi ao agente


async def test_ja_no_estado_pedido_so_confirma(rig) -> None:
    pipeline, w, hud, _ = rig
    res = await _say(pipeline, "end session")
    assert res.speech == intent_action.SAY_NOT_ON and not w.session.active
    assert hud.of(LmModeMsg) == [LmModeMsg(False)]  # confirma o estado, sem sessão nova

    await _say(pipeline, "modo aula")
    first = w.session.id
    res = await _say(pipeline, "learning mode")
    assert res.speech == intent_action.SAY_ALREADY_ON
    assert w.session.id == first and w.session.active
    assert hud.of(LmModeMsg)[-2:] == [LmModeMsg(True), LmModeMsg(True)]


async def test_conversa_dentro_do_modo_nao_encerra(rig) -> None:
    pipeline, w, _, agent = rig
    await _say(pipeline, "let's study english")
    res = await _say(pipeline, "the session ended late")
    assert res.speech == "Lovely." and agent.asked == ["the session ended late"]
    assert w.session.active


async def test_sem_wiring_responde_indisponivel() -> None:
    action = LearningIntentAction(lambda: None)
    req = ActionRequest(intent=Intent(IntentId.LEARNING_START.value), ctx=_ctx())
    res = await action.run(req)
    assert not res.ok and res.speech == intent_action.SAY_UNAVAILABLE


def test_respostas_em_ingles() -> None:
    try:
        i18n.configure("en-gb")
        assert i18n.tr(intent_action.SAY_ON) == "Learning mode on. Let's talk."
        assert i18n.tr(intent_action.SAY_OFF) == "Session ended. Good job."
        for phrase in (intent_action.SAY_ALREADY_ON, intent_action.SAY_NOT_ON,
                       intent_action.SAY_UNAVAILABLE, intent_action.SAY_FAILED):
            assert i18n.tr(phrase) != phrase
    finally:
        i18n.configure("pt-br")


def test_desligado_nao_registra_e_frases_vao_ao_agente() -> None:
    deps = TurnDeps(router=LocalRouter(None))
    found = wire(parse_config({"learning": {"enabled": False}}), deps, [])
    assert found == []
    assert deps.router is not None
    for text in ("modo aula", "end session"):
        assert deps.router.route(text).kind is RouteKind.AGENT


def test_sem_atalho_global_nem_comando_de_terminal() -> None:
    assert not (ROOT / "magi" / "cli" / "learning.py").exists()
    for f in (ROOT / "magi" / "learning").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "KGlobalAccel" not in text and "kglobalaccel" not in text.lower(), f
