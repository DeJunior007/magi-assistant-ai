"""Ligação da entrevista pela vaga ao núcleo (LI1.4; design §4–§6, spec §5.3, §7, §10, CA-05).

Só ``FakeModel`` (nenhuma chamada real), repositório JSONL em pasta temporária e relógio injetado.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from magi.common.config import parse_config
from magi.common.contracts import (
    ActionResult,
    HudMessage,
    IntentId,
    LmInterviewMsg,
    LmJobMsg,
    LmJobReqMsg,
    LmSayMsg,
    LmSessionMsg,
    LmTopicMsg,
    RouteKind,
    Transcript,
    TurnContext,
    WakeSource,
)
from magi.core import actions
from magi.core.router import LocalRouter
from magi.core.turn import TurnDeps, TurnPipeline
from magi.learning import intent_action
from magi.learning.config import LearningConfig
from magi.learning.contracts import Topic
from magi.learning.intent_action import wire, wire_persona
from magi.learning.interview.contracts import RunState
from magi.learning.model import FakeModel, ModelBudget
from magi.learning.repo import JsonlRepo
from magi.learning.wiring import (
    INTERVIEW_NEXT_PROMPT,
    INTERVIEW_OPENING_PROMPT,
    STILL_PREPARING,
    install,
)

VAGA = (Path(__file__).parent / "fixtures" / "vagas" / "backend_senior_en.txt").read_text("utf-8")
KEY = "job_profile:*"
LABEL = "INTERVIEW // SENIOR BACKEND ENGINEER (PYTHON)"


def _answer() -> dict:
    return {
        "title": "Senior Backend Engineer (Python)",
        "company": "Quillfeather Payments",
        "seniority": "senior",
        "language": "en",
        "stack": ["Python", "PostgreSQL", "Kafka"],
        "requirements": [
            {"text": "5+ years with Python", "kind": "must", "skill": "python",
             "evidence": "5+ years of experience with Python in production"},
        ],
        "responsibilities": ["Design and build payment APIs"],
        "domain": "fintech",
        "remote": "Remote",
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
        self._persona = "BASE"
        self.asked: list[tuple[str, str | None]] = []

    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        self.asked.append((text, self._persona))
        return ActionResult(ok=True, speech=f"Good. And what about part {len(self.asked)}?")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _make(tmp_path: Path, clock: Clock, model: FakeModel):
    agent = FakeAgent()
    deps = TurnDeps(router=LocalRouter(None), agent=agent)
    deps.actions = actions.Registry(wire(parse_config({}), deps, []))
    assert wire_persona(parse_config({}), deps)
    pipeline = TurnPipeline(deps)
    hud = SinkHud()
    w = install(LearningConfig(storage="jsonl"), hud, pipeline, repo=JsonlRepo(tmp_path),
                clock=clock, start=False, job_model=model)
    assert w is not None
    w.opening_poll_s = 0.01
    return w, hud, agent, pipeline


@pytest.fixture
def rig(tmp_path):
    clock = Clock()
    model = FakeModel({KEY: _answer()})
    w, hud, agent, pipeline = _make(tmp_path, clock, model)
    return w, hud, agent, model, clock, pipeline


async def _ready(w, hud) -> None:
    await w.set_mode(True)
    await w.on_learning(LmJobMsg(text=VAGA, source="clipboard"))
    await w.wait_idle()


def _states(hud) -> list[RunState]:
    return [m.state for m in hud.of(LmInterviewMsg)]


async def test_vaga_preparing_na_hora_depois_ready_tema_e_abertura(rig) -> None:
    """CA-05: ``preparing`` em ≤ 100 ms → ``ready`` + ``lm_topic`` com o rótulo; abertura P11."""
    w, hud, agent, model, _, _ = rig
    await w.set_mode(True)
    t0 = time.perf_counter()
    await w.on_learning(LmJobMsg(text=VAGA, source="clipboard"))
    assert time.perf_counter() - t0 < 0.1
    assert _states(hud) == [RunState.PREPARING]
    await w.wait_idle()

    topic = hud.of(LmTopicMsg)[-1]
    assert topic.topic is Topic.INTERVIEW and topic.label == LABEL
    ready = hud.of(LmInterviewMsg)[1]
    assert ready.state is RunState.READY and ready.title == "Senior Backend Engineer (Python)"
    assert ready.stage == 0 and ready.n_stages and ready.must
    ((prompt, persona),) = agent.asked
    assert prompt == INTERVIEW_OPENING_PROMPT
    assert persona is not None and "Stage 1/" in persona and "Quillfeather" in persona
    assert w.run is not None and w.run.state is RunState.RUNNING and w.run.asked == 1
    assert hud.of(LmInterviewMsg)[-1].asked == 1
    assert len(model.calls) == 1


async def test_mesma_vaga_duas_vezes_uma_chamada_ao_modelo(rig) -> None:
    w, hud, _, model, _, _ = rig
    await _ready(w, hud)
    run_id = w.run.id
    await w.on_learning(LmJobMsg(text=VAGA + "\n\n", source="clipboard"))  # mesmo hash
    await w.wait_idle()
    assert len(model.calls) == 1 and w.run.id == run_id  # retoma a mesma run

    await w.on_learning(LmInterviewMsg(cmd="end"))
    await w.on_learning(LmJobMsg(job_id=hud.of(LmInterviewMsg)[0].job_id))
    await w.wait_idle()
    assert len(model.calls) == 1 and w.run is not None and w.run.id != run_id


async def test_lm_job_durante_preparing_e_ignorado(rig) -> None:
    w, hud, _, model, _, _ = rig
    model.delay_s = 0.05
    await w.set_mode(True)
    await w.on_learning(LmJobMsg(text=VAGA, source="clipboard"))
    await w.on_learning(LmJobMsg(text=VAGA, source="clipboard"))
    assert hud.of(LmInterviewMsg)[-1].error == STILL_PREPARING
    await w.wait_idle()
    assert len(model.calls) == 1


async def test_erro_da_extracao_mantem_o_tema(tmp_path) -> None:
    w, hud, agent, _ = _make(tmp_path, Clock(), FakeModel({KEY: ModelBudget("teto")}))
    await w.set_mode(True)
    await w.on_learning(LmJobMsg(text=VAGA, source="clipboard"))
    await w.wait_idle()
    last = hud.of(LmInterviewMsg)[-1]
    assert last.state is RunState.ERROR and last.error == "budget" and last.job_id
    assert w.run is None and hud.of(LmTopicMsg)[-1].topic is Topic.FREE and agent.asked == []
    assert await w.interviews.post_of(last.job_id) is not None  # a vaga não se perde (R2.5)


async def test_texto_curto_e_recusado(rig) -> None:
    w, hud, _, model, _, _ = rig
    await w.set_mode(True)
    await w.on_learning(LmJobMsg(text="Python dev wanted", source="clipboard"))
    assert hud.of(LmInterviewMsg)[-1].state is RunState.ERROR and model.calls == []


async def test_turno_falso_avanca_etapa(rig) -> None:
    w, hud, _, _, _, _ = rig
    await _ready(w, hud)
    quota = w.run.current.quota
    for i in range(quota + 1):
        await w.on_learning(LmSayMsg(f"My answer number {i}."))
        await w.wait_idle()
        if w.run.stage == 1:
            break
    assert w.run.stage == 1 and w.run.answers >= 1
    assert w.run.first_message_id is not None and w.run.last_message_id is not None
    assert hud.of(LmInterviewMsg)[-1].stage == 1


async def test_tempo_da_etapa_avanca_pelo_bloco(rig) -> None:
    w, hud, agent, _, clock, _ = rig
    await _ready(w, hud)
    clock.now += timedelta(minutes=w.run.current.minutes + 1)
    await w.on_learning(LmSayMsg("Sorry, I was thinking."))
    await w.wait_idle()
    assert "Stage 2/" in agent.asked[-1][1]
    assert any(m.stage == 1 for m in hud.of(LmInterviewMsg))


async def test_comando_digitado_next_sem_turno_do_texto(rig) -> None:
    w, hud, agent, _, _, _ = rig
    await _ready(w, hud)
    per, stage, asked = 1 + w.run.current.followups, w.run.stage, w.run.asked
    await w.on_learning(LmSayMsg("Next question, please"))
    await w.wait_idle()
    assert [t for t, _ in agent.asked] == [INTERVIEW_OPENING_PROMPT, INTERVIEW_NEXT_PROMPT]
    # pulou para a próxima principal (ou fechou a etapa) e ela perguntou
    if w.run.stage == stage:
        assert w.run.asked == (asked // per + 1) * per + 1
    else:
        assert w.run.stage == stage + 1 and w.run.asked == 1
    assert w.run.answers == 0  # o comando não conta resposta


async def test_comando_end_volta_a_free(rig) -> None:
    w, hud, _, _, _, _ = rig
    await _ready(w, hud)
    run = w.run
    await w.on_learning(LmInterviewMsg(cmd="end"))
    await w.wait_idle()
    assert w.run is None and run.state is RunState.DONE  # < 3 respostas: sem retorno
    assert hud.of(LmInterviewMsg)[-1].state is RunState.DONE
    assert hud.of(LmTopicMsg)[-1].topic is Topic.FREE
    assert await w.interviews.load_active(w.session.id) is None


async def test_end_digitado(rig) -> None:
    w, hud, agent, _, _, _ = rig
    await _ready(w, hud)
    await w.on_learning(LmSayMsg("end the interview"))
    await w.wait_idle()
    assert w.run is None and len(agent.asked) == 1
    assert hud.of(LmTopicMsg)[-1].topic is Topic.FREE


async def test_troca_de_tema_pausa_e_volta_retoma(rig) -> None:
    w, hud, agent, _, _, _ = rig
    await _ready(w, hud)
    await w.set_topic(Topic.FREE)
    assert w.run.state is RunState.PAUSED and hud.of(LmInterviewMsg)[-1].state is RunState.PAUSED
    await w.on_learning(LmSayMsg("hello"))
    await w.wait_idle()
    assert w.run.state is RunState.PAUSED and "Stage 1/" not in (agent.asked[-1][1] or "")
    ctx = await w.set_topic(Topic.INTERVIEW)
    assert ctx is not None and ctx.label == LABEL
    await w.wait_idle()
    assert "Stage 1/" in agent.asked[-1][1]


async def test_sessao_retomada_volta_a_run(tmp_path) -> None:
    """R5.3: núcleo reiniciado sem fechar a sessão → mesma etapa e contagem."""
    clock = Clock()
    w, hud, _, _ = _make(tmp_path, clock, FakeModel({KEY: _answer()}))
    await _ready(w, hud)
    await w.on_learning(LmSayMsg("I build payment APIs."))
    await w.wait_idle()
    stage, asked, answers, rid = w.run.stage, w.run.asked, w.run.answers, w.run.id
    flush = getattr(w.repo, "flush", None)
    if flush is not None:
        await flush()

    w2, hud2, _, _ = _make(tmp_path, clock, FakeModel({}))
    await w2.set_mode(True)
    assert w2.run is not None and w2.run.id == rid
    assert (w2.run.stage, w2.run.asked, w2.run.answers) == (stage, asked, answers)
    assert hud2.of(LmTopicMsg)[-1].label == LABEL
    assert hud2.of(LmInterviewMsg)[-1].run_id == rid


async def test_fechar_sessao_fecha_a_run_e_session_traz_jobs(rig) -> None:
    w, hud, _, _, _, _ = rig
    await _ready(w, hud)
    sid = w.session.id
    await w.set_mode(False)
    assert w.run is None and await w.interviews.load_active(sid) is None
    await w.set_mode(True)
    (job,) = hud.of(LmSessionMsg)[-1].jobs
    assert job.title == "Senior Backend Engineer (Python)" and job.company == "Quillfeather Payments"


# ---------------------------------------------------------------------------------------------
# Voz
# ---------------------------------------------------------------------------------------------


def _ctx() -> TurnContext:
    return TurnContext(satellite="sala", source=WakeSource.PTT,
                       started_at=datetime(2026, 10, 11, 9, 0, tzinfo=UTC))


async def _voice(pipeline: TurnPipeline, text: str) -> ActionResult:
    return await pipeline.respond(Transcript.raw(text), _ctx())


async def test_roteador_comandos_so_com_run_viva(rig) -> None:
    w, hud, _, _, _, pipeline = rig
    router = pipeline.deps.router
    assert router.best("next question") is None or router.best("next question").spec.id not in \
        intent_action.INTERVIEW_INTENTS
    await w.set_mode(True)
    hit = router.best("treinar para a vaga que eu copiei")
    assert hit is not None and hit.spec.id == IntentId.LEARNING_INTERVIEW_JOB
    hit = router.best("next question")
    assert hit is None or hit.spec.id not in intent_action.RUN_INTENTS
    await w.on_learning(LmJobMsg(text=VAGA, source="clipboard"))
    await w.wait_idle()
    for text, iid in [("next question", IntentId.LEARNING_INTERVIEW_NEXT),
                      ("próxima etapa", IntentId.LEARNING_INTERVIEW_SKIP),
                      ("pausa a entrevista", IntentId.LEARNING_INTERVIEW_PAUSE),
                      ("end the interview", IntentId.LEARNING_INTERVIEW_END),
                      ("encerra a entrevista", IntentId.LEARNING_INTERVIEW_END),
                      ("encerra a aula", IntentId.LEARNING_STOP),
                      ("pausa", IntentId.MUSIC_PAUSE)]:
        res = router.route(text)
        assert res.kind is RouteKind.LOCAL and res.intent.id == iid, (text, res)


async def test_voz_pede_a_vaga_ao_hud(rig) -> None:
    w, hud, _, _, _, pipeline = rig
    await w.set_mode(True)
    res = await _voice(pipeline, "prepare the interview for the job I copied")
    assert res.ok and res.speech == intent_action.SAY_JOB_ASKED
    assert hud.of(LmJobReqMsg) == [LmJobReqMsg()]


async def test_voz_ultima_vaga_e_comandos(rig) -> None:
    w, hud, agent, model, _, pipeline = rig
    await w.set_mode(True)
    res = await _voice(pipeline, "same job again")
    assert not res.ok and res.speech == intent_action.SAY_NO_LAST_JOB
    await w.on_learning(LmJobMsg(text=VAGA, source="clipboard"))
    await w.wait_idle()
    await w.on_learning(LmInterviewMsg(cmd="end"))
    await w.wait_idle()

    res = await _voice(pipeline, "same job again")
    assert res.ok and res.speech == intent_action.SAY_JOB_LAST
    await w.wait_idle()
    assert w.run is not None and len(model.calls) == 1

    res = await _voice(pipeline, "pause the interview")
    assert res.speech == intent_action.SAY_RUN_CMD["pause"] and w.run.state is RunState.PAUSED
    res = await _voice(pipeline, "end the interview")
    assert res.speech == intent_action.SAY_RUN_CMD["end"] and w.run is None
    res = await _voice(pipeline, "fim da aula")
    assert not w.session.active


def test_respostas_em_ingles() -> None:
    from magi.core import i18n

    try:
        i18n.configure("en-gb")
        for phrase in (intent_action.SAY_JOB_ASKED, intent_action.SAY_JOB_LAST,
                       intent_action.SAY_NO_LAST_JOB, intent_action.SAY_NO_INTERVIEW,
                       intent_action.SAY_INTERVIEW_FAILED, *intent_action.SAY_RUN_CMD.values()):
            assert i18n.tr(phrase) != phrase
    finally:
        i18n.configure("pt-br")
