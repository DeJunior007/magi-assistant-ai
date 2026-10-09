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
    LmTopicMsg,
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
from magi.learning.contracts import Topic
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


# ---------------------------------------------------------------------------------------------
# Tema por voz (LM1.8, CA-24): só com sessão ativa
# ---------------------------------------------------------------------------------------------

TOPIC_PHRASES = {
    IntentId.LEARNING_TOPIC_FREE: ["conversa livre", "tema livre", "vamos falar de qualquer coisa",
                                   "free talk", "let's just chat", "change the subject"],
    IntentId.LEARNING_TOPIC_INTERVIEW: ["entrevista técnica", "simular entrevista",
                                        "vamos treinar entrevista", "tech interview",
                                        "interview practice", "let's do a mock interview"],
    IntentId.LEARNING_TOPIC_GAME: ["vamos falar do jogo", "falar do jogo que estou jogando",
                                   "conversar sobre o jogo", "let's talk about the game",
                                   "talk about the game I'm playing", "let's talk about my game"],
    IntentId.LEARNING_TOPIC_NEWS: ["vamos falar das notícias", "conversar sobre as notícias de hoje",
                                   "let's talk about the news", "talk about today's news"],
}
#: Frases dos intents de notícias e de jogo que já existiam: nunca viram tema.
OLD_PHRASES = ["novidades", "alguma novidade", "o que tem de novo", "me conta as novidades",
               "proxima noticia", "fecha o jogo"]
TOPIC_IDS = {i.value for i in TOPIC_PHRASES}


def _plain_router() -> LocalRouter:
    """Roteador como antes do LM1.8 (sem as frases de tema)."""
    r = LocalRouter(None)
    r.intents = [s for s in r.intents if s.id not in TOPIC_IDS]
    return r


async def test_tema_casa_so_com_sessao_ativa(rig) -> None:
    pipeline, w, _, _ = rig
    router = pipeline.deps.router
    plain = _plain_router()
    for phrases in TOPIC_PHRASES.values():
        for text in phrases:
            res, old = router.route(text), plain.route(text)
            assert (res.kind, res.intent) == (old.kind, old.intent), text  # fora: caminho antigo
    await _say(pipeline, "modo aula")
    for intent, phrases in TOPIC_PHRASES.items():
        for text in phrases:
            res = router.route(text)
            assert res.kind is RouteKind.LOCAL and res.intent is not None, text
            assert res.intent.id == intent, (text, res)


async def test_frases_antigas_de_noticia_e_jogo_nao_viram_tema(rig) -> None:
    pipeline, w, _, _ = rig
    await _say(pipeline, "english class")
    plain = _plain_router()
    for text in OLD_PHRASES:
        res = pipeline.deps.router.route(text)
        assert res.intent is None or res.intent.id not in TOPIC_IDS, text
        assert (res.kind, res.intent) == (plain.route(text).kind, plain.route(text).intent), text
    for phrases in TOPIC_PHRASES.values():
        for text in phrases:
            res = pipeline.deps.router.route(text)
            assert res.intent is not None and not res.intent.id.startswith(("news.", "game.")), text


def test_fora_da_sessao_vamos_falar_do_jogo_segue_o_caminho_antigo() -> None:
    deps = TurnDeps(router=LocalRouter(None))
    wire(parse_config({}), deps, [])
    assert deps.router is not None
    for text in ("vamos falar do jogo", "let's talk about the news", "free talk"):
        res = deps.router.route(text)
        assert res.intent is None or res.intent.id not in TOPIC_IDS, text


async def test_tema_por_voz_e_a_mesma_acao_do_botao(rig) -> None:
    pipeline, w, hud, agent = rig
    res = await _say(pipeline, "tech interview")  # sem sessão: não é tema
    assert agent.asked == ["tech interview"] and not hud.of(LmTopicMsg)
    await _say(pipeline, "modo aula")
    w.listening = lambda: False  # segura a abertura
    res = await _say(pipeline, "tech interview")
    assert res.ok and res.speech == intent_action.SAY_TOPIC[Topic.INTERVIEW]
    last = hud.of(LmTopicMsg)[-1]
    assert last.topic is Topic.INTERVIEW and last.requested is Topic.INTERVIEW
    assert w.session.topic_block is not None
    # O turno de voz que pediu o tema não cancela a abertura; o próximo (Pedro falou) cancela.
    w.on_turn(Transcript.raw("tech interview"), _ctx(), res)
    assert w._opening is not None and not w._opening.done()
    w.on_turn(Transcript.raw("well, hello"), _ctx(), ActionResult(ok=True, speech="Hi."))
    await w.wait_idle()
    assert w._opening is None and agent.asked == ["tech interview"]

    res = await _say(pipeline, "vamos falar do jogo")  # sem fontes: fallback
    assert res.speech == intent_action.SAY_TOPIC_FALLBACK["no game detected"]
    assert hud.of(LmTopicMsg)[-1].detail == "no game detected"


def test_respostas_de_tema_em_ingles() -> None:
    phrases = [*intent_action.SAY_TOPIC.values(), *intent_action.SAY_TOPIC_FALLBACK.values(),
               intent_action.SAY_TOPIC_FAILED]
    try:
        i18n.configure("en-gb")
        for phrase in phrases:
            assert i18n.tr(phrase) != phrase, phrase
    finally:
        i18n.configure("pt-br")
