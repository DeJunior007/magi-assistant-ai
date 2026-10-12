"""LI4.2 / CA-09 (núcleo): roleplay pelo botão (``lm_topic`` com ``scenario``) e pela voz
(``learning.topic.roleplay``, só com sessão), ``lm_session.scenarios`` e troca de cenário."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from magi.common.config import parse_config
from magi.common.contracts import (
    ActionResult,
    HudMessage,
    IntentId,
    LmSessionMsg,
    LmTopicMsg,
    Transcript,
    TurnContext,
    WakeSource,
)
from magi.core import actions, i18n
from magi.core.router import LocalRouter
from magi.core.turn import TurnDeps, TurnPipeline
from magi.learning import intent_action
from magi.learning.config import LearningConfig
from magi.learning.contracts import Topic
from magi.learning.intent_action import wire
from magi.learning.repo import JsonlRepo
from magi.learning.topic import NO_SCENARIO
from magi.learning.wiring import install

PHRASES = {
    "hotel_checkin": ["let's roleplay a hotel check-in", "vamos simular um check-in no hotel"],
    "ordering_food": ["let's roleplay ordering food", "vamos simular um pedido no restaurante"],
    "doctor_visit": ["let's roleplay a doctor visit", "vamos simular uma consulta médica"],
    "support_call": ["let's roleplay a support call", "vamos simular uma ligação pro suporte"],
}


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
    return datetime(2026, 10, 12, 20, 0, tzinfo=UTC)


def _ctx() -> TurnContext:
    return TurnContext(satellite="sala", source=WakeSource.PTT, started_at=_clock())


@pytest.fixture
def rig(tmp_path):
    agent = FakeAgent()
    deps = TurnDeps(router=LocalRouter(None), agent=agent)
    deps.actions = actions.Registry(wire(parse_config({}), deps, []))
    pipeline = TurnPipeline(deps)
    hud = SinkHud()
    w = install(LearningConfig(storage="jsonl"), hud, pipeline, repo=JsonlRepo(tmp_path),
                clock=_clock, start=False)
    assert w is not None
    w.listening = lambda: False  # segura a abertura (sem agente)
    return pipeline, w, hud, agent


async def _say(pipeline: TurnPipeline, text: str) -> ActionResult:
    return await pipeline.respond(Transcript.raw(text), _ctx())


def test_frases_do_roleplay_casam_com_o_cenario() -> None:
    router = LocalRouter(None)
    for sid, phrases in PHRASES.items():
        for text in phrases:
            res = router.route(text)
            assert res.intent is not None and res.intent.id == IntentId.LEARNING_TOPIC_ROLEPLAY, text
            slot = res.intent.slot(intent_action.SCENARIO_SLOT)
            assert slot is not None and slot.value == sid, text


async def test_sessao_lista_os_4_cenarios(rig) -> None:
    _, w, hud, _ = rig
    await w.set_mode(True)
    (sess,) = hud.of(LmSessionMsg)
    assert [s.id for s in sess.scenarios] == ["doctor_visit", "hotel_checkin", "ordering_food",
                                              "support_call"]
    assert sess.to_dict()["scenarios"][1] == {"id": "hotel_checkin", "title": "Hotel check-in"}


async def test_clique_abre_o_cenario_e_troca_de_cenario(rig) -> None:
    _, w, hud, _ = rig
    await w.set_mode(True)
    await w.on_learning(LmTopicMsg(topic=Topic.ROLEPLAY, scenario="hotel_checkin"))
    last = hud.of(LmTopicMsg)[-1]
    assert last.topic is Topic.ROLEPLAY and last.label == "ROLEPLAY // HOTEL CHECK-IN"
    assert "Hotel check-in" in (w.session.topic_block or "")
    assert w._opening is not None  # cena nova abre o assunto
    w._cancel_opening()
    # mesmo cenário: só confirma; outro cenário: refaz o bloco e abre de novo
    ctx = await w.set_topic(Topic.ROLEPLAY, scenario="hotel_checkin")
    assert ctx is w.session.topic_context and w._opening is None
    await w.on_learning(LmTopicMsg(topic=Topic.ROLEPLAY, scenario="doctor_visit"))
    assert hud.of(LmTopicMsg)[-1].label == "ROLEPLAY // DOCTOR VISIT"
    assert w._opening is not None
    w._cancel_opening()


async def test_cenario_desconhecido_ou_ausente_cai_em_free(rig) -> None:
    _, w, hud, _ = rig
    await w.set_mode(True)
    for scenario in ("nope", None):
        await w.on_learning(LmTopicMsg(topic=Topic.ROLEPLAY, scenario=scenario))
        last = hud.of(LmTopicMsg)[-1]
        assert last.topic is Topic.FREE and last.requested is Topic.ROLEPLAY
        assert last.detail == NO_SCENARIO


async def test_retomada_volta_ao_mesmo_cenario(rig) -> None:
    _, w, hud, _ = rig
    await w.set_mode(True)
    await w.set_topic(Topic.ROLEPLAY, scenario="support_call")
    w._cancel_opening()
    w.session._topic = None  # snapshot perdido: refeito pelo tema + cenário guardados
    await w._restore_topic()
    last = hud.of(LmTopicMsg)[-1]
    assert last.topic is Topic.ROLEPLAY and last.label == "ROLEPLAY // SUPPORT CALL"


async def test_li51_cenario_volta_depois_de_reiniciar_o_nucleo(rig, tmp_path) -> None:
    """LI5.1: o id do cenário vai na entrada de ``topics``; o núcleo novo (mesma pasta, sessão
    ainda aberta) retoma o roleplay no mesmo cenário em vez de cair em free."""
    _, w, _, _ = rig
    await w.set_mode(True)
    await w.set_topic(Topic.ROLEPLAY, scenario="doctor_visit")
    w._cancel_opening()
    sid = w.session.id
    hud2 = SinkHud()
    deps = TurnDeps(router=LocalRouter(None), agent=FakeAgent())
    w2 = install(LearningConfig(storage="jsonl"), hud2, TurnPipeline(deps),
                 repo=JsonlRepo(tmp_path), clock=_clock, start=False)
    assert w2 is not None
    w2.listening = lambda: False
    await w2.set_mode(True)
    assert w2.session.id == sid
    last = hud2.of(LmTopicMsg)[-1]
    assert last.topic is Topic.ROLEPLAY and last.label == "ROLEPLAY // DOCTOR VISIT"
    assert last.detail is None
    # o mesmo cenário de novo só confirma (não reabre a cena nem grava outra entrada)
    n = len((await w2.repo.get_session(sid)).topics)
    await w2.set_topic(Topic.ROLEPLAY, scenario="doctor_visit")
    assert len((await w2.repo.get_session(sid)).topics) == n


async def test_voz_so_com_sessao_e_abre_o_cenario(rig) -> None:
    pipeline, w, hud, agent = rig
    await _say(pipeline, "let's roleplay a hotel check-in")  # sem sessão: vai ao agente
    assert agent.asked == ["let's roleplay a hotel check-in"] and not hud.of(LmTopicMsg)
    await _say(pipeline, "modo aula")
    res = await _say(pipeline, "vamos simular uma consulta médica")
    assert res.ok and res.speech == intent_action.SAY_TOPIC[Topic.ROLEPLAY]
    assert hud.of(LmTopicMsg)[-1].label == "ROLEPLAY // DOCTOR VISIT"
    w._cancel_opening()


def test_respostas_do_roleplay_em_ingles() -> None:
    try:
        i18n.configure("en-gb")
        for phrase in (intent_action.SAY_TOPIC[Topic.ROLEPLAY],
                       intent_action.SAY_TOPIC_FALLBACK[NO_SCENARIO]):
            assert i18n.tr(phrase) != phrase, phrase
    finally:
        i18n.configure("pt-br")
