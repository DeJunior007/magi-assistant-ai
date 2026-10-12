"""Retorno da entrevista pela vaga (LI2.3; spec §6, §7, §10, R4, R5.2, D3, D7, CA-06).

Só ``FakeModel`` (e um modelo falso com portão, sem ``sleep``), repositório JSONL em pasta
temporária e relógio injetado.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from magi.common.config import parse_config
from magi.common.contracts import (
    ActionResult,
    HudMessage,
    LmDebriefMsg,
    LmInterviewMsg,
    LmJobMsg,
    LmMsgMsg,
    LmSayMsg,
    LmSessionMsg,
    LmTopicMsg,
    TurnContext,
)
from magi.core import actions
from magi.core.router import LocalRouter
from magi.core.turn import TurnDeps, TurnPipeline
from magi.learning.config import LearningConfig
from magi.learning.contracts import Author, LearningMessage, ObsCategory, Observation, Source, Topic
from magi.learning.intent_action import wire, wire_persona
from magi.learning.interview import debrief as dbf
from magi.learning.interview.contracts import (
    Aspect,
    Cover,
    InterviewRun,
    JobProfile,
    Requirement,
    RunState,
    Seniority,
)
from magi.learning.interview.plan import build_plan
from magi.learning.interview.run import start
from magi.learning.model import FakeModel, ModelBudget, ModelInvalid
from magi.learning.repo import JsonlRepo
from magi.learning.wiring import (
    DEBRIEF_FAILED,
    DEBRIEF_READY,
    DEBRIEF_RETRY_DONE,
    DEBRIEF_RETRY_NONE,
    DEBRIEF_TOO_SHORT,
    install,
)

AT = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
DKEY = "interview_debrief:*"
VAGA = (Path(__file__).parent / "fixtures" / "vagas" / "backend_senior_en.txt").read_text("utf-8")
ANSWERS = (
    "I have worked with Python in production for six years at a payments company.",
    "We used PostgreSQL with careful indexes and read replicas.",
    "I like to split big problems in small steps and explain the trade-offs.",
)


def _profile() -> JobProfile:
    return JobProfile(
        title="Senior Backend Engineer (Python)", company="Quillfeather Payments",
        seniority=Seniority.SENIOR, language="en", stack=("python", "postgresql", "kafka"),
        requirements=(
            Requirement("5+ years with Python", "must", "python", "5+ years with Python"),
            Requirement("PostgreSQL experience", "must", "postgresql", "PostgreSQL"),
            Requirement("Kafka", "must", "kafka", "Kafka"),
            Requirement("Fintech domain", "nice", None, "fintech"),
        ),
        responsibilities=(), domain="fintech", remote="remote")


def _run(first: int = 1, last: int = 6) -> InterviewRun:
    p = _profile()
    run = start(build_plan(p, 30, job_id="JOB-1a2b3c4d"), p, "LS-20261011-01", 0.0,
                run_id="IV-20261011-01")
    run.first_message_id, run.last_message_id, run.answers = first, last, 3
    return run


def _messages() -> list[LearningMessage]:
    out = []
    for i, a in enumerate(ANSWERS):
        out.append(LearningMessage(2 * i + 1, "LS-20261011-01", Author.CONDESSA, Source.TEXT,
                                   f"Question {i + 1}?", AT))
        out.append(LearningMessage(2 * i + 2, "LS-20261011-01", Author.YOU, Source.TEXT, a, AT))
    out.append(LearningMessage(99, "LS-20261011-01", Author.YOU, Source.TEXT, "out of the run", AT))
    return out


def _answer(**over) -> dict:
    data = {
        "coverage": [
            {"requirement": "5+ years with Python", "cover": "covered",
             "evidence": "Python in production for six years"},
            {"requirement": "PostgreSQL experience", "cover": "covered",
             "evidence": "We used PostgreSQL with Oracle"},  # não está nas falas → THIN
        ],
        "scores": [
            {"aspect": "clarity", "score": 74, "note": "Clear steps."},
            {"aspect": "fluency", "score": 130.6, "note": "x" * 400},
            {"aspect": "grammar", "score": -5, "note": "Some errors."},
            {"aspect": "fluency", "score": 10, "note": "duplicate"},
            {"aspect": "overall", "score": 80, "note": "no overall score"},
            {"aspect": "vocabulary", "score": "n/a", "note": "bad"},
        ],
        "strengths": ["Concrete examples", "Good pace", "Calm", "Fourth"],
        "improve": ["Talk about Kafka"],
        "rewrites": [{"original": "We used PostgreSQL", "stronger": "I designed the schema…"}],
        "closing": "Good job, keep practising.",
    }
    data.update(over)
    return data


# ---------------------------------------------------------------------------------------------
# debrief() puro (spec §6, D3)
# ---------------------------------------------------------------------------------------------


async def test_notas_e_cobertura_com_pos_checagem() -> None:
    obs = [
        Observation(1, "LS-20261011-01", 2, ObsCategory.GRAMMAR, "g.a", "past simple", "x", None),
        Observation(2, "LS-20261011-01", 4, ObsCategory.RECURRING, "r.a", "articles", "x", None),
        Observation(3, "LS-20261011-01", 99, ObsCategory.GRAMMAR, "g.b", "outside", "x", None),
        Observation(4, "LS-20261011-01", 6, ObsCategory.GRAMMAR, "g.a", "Past simple", "x", None),
    ]
    model = FakeModel({DKEY: _answer()})
    d = await dbf.debrief(_run(), _messages(), obs, model)
    assert d.run_id == "IV-20261011-01"
    # notas: ordem do enum, presas em 0..100, desconhecido/duplicata/não numérico caem
    assert [(s.aspect, s.score) for s in d.scores] == [
        (Aspect.FLUENCY, 100), (Aspect.GRAMMAR, 0), (Aspect.CLARITY, 74)]
    assert len(d.scores[0].note) == 200
    assert d.score_of(Aspect.VOCABULARY) is None and d.score_of(Aspect.JOB_FIT) is None
    # cobertura: evidência das falas do Pedro, inventada vira THIN; must ausente → MISSED
    cov = {c.requirement: c for c in d.coverage}
    assert cov["5+ years with Python"].cover is Cover.COVERED
    assert cov["PostgreSQL experience"].cover is Cover.THIN
    assert cov["PostgreSQL experience"].evidence is None
    assert cov["Kafka"].cover is Cover.MISSED and "Fintech domain" not in cov
    assert d.strengths == ("Concrete examples", "Good pace", "Calm")
    assert d.language == ("articles", "past simple")  # recurring primeiro, só da run, sem repetir
    # transcrição: só a run, autor + texto
    _, user, schema = model.calls[0]
    assert schema["title"] == "interview_debrief"
    assert "Pedro: We used PostgreSQL" in user and "Interviewer: Question 1?" in user
    assert "out of the run" not in user


async def test_idioma_das_explicacoes_d7() -> None:
    model = FakeModel({DKEY: _answer()})
    await dbf.debrief(_run(), _messages(), [], model)
    await dbf.debrief(_run(), _messages(), [], model, explain_language="pt-br")
    assert "simple English" in model.calls[0][0] and "No overall score" in model.calls[0][0]
    assert "Brazilian Portuguese" in model.calls[1][0]


async def test_transcricao_cortada_do_comeco() -> None:
    run = _run(1, 400)
    msgs = [LearningMessage(i, "LS-20261011-01", Author.YOU, Source.TEXT, f"answer {i} " * 20, AT)
            for i in range(1, 401)]
    text = dbf.transcript(run, msgs)
    assert len(text) <= dbf.TRANSCRIPT_MAX and text.startswith("Pedro: answer")
    assert text.endswith("answer 400")


async def test_resposta_fora_do_contrato() -> None:
    with pytest.raises(ModelInvalid):
        await dbf.debrief(_run(), _messages(), [], FakeModel({DKEY: "[1, 2]"}))


# ---------------------------------------------------------------------------------------------
# Wiring (R4, R5.2)
# ---------------------------------------------------------------------------------------------


class SinkHud:
    def __init__(self) -> None:
        self.sent: list[HudMessage] = []
        self.on_learning = None

    async def send(self, msg: HudMessage) -> None:
        self.sent.append(msg)

    def of(self, kind: type) -> list:
        return [m for m in self.sent if isinstance(m, kind)]

    def lines(self) -> list[str]:
        return [m.text for m in self.of(LmMsgMsg)]


class FakeAgent:
    def __init__(self) -> None:
        self._persona = "BASE"

    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        return ActionResult(ok=True, speech="Good. And how did you handle that?")


class GatedModel(FakeModel):
    """Responde só depois que ``gate`` abrir (modelo "lento" sem ``sleep``)."""

    def __init__(self, responses) -> None:
        super().__init__(responses)
        self.started = asyncio.Event()
        self.gate = asyncio.Event()

    async def complete(self, system, user, schema):
        self.started.set()
        await self.gate.wait()
        return await super().complete(system, user, schema)


def _job_answer() -> dict:
    return {
        "title": "Senior Backend Engineer (Python)", "company": "Quillfeather Payments",
        "seniority": "senior", "language": "en", "stack": ["Python"],
        "requirements": [{"text": "5+ years with Python", "kind": "must", "skill": "python",
                          "evidence": "5+ years of experience with Python in production"}],
        "responsibilities": [], "domain": None, "remote": None,
    }


def _make(tmp_path: Path, model, spoken: list | None = None):
    deps = TurnDeps(router=LocalRouter(None), agent=FakeAgent())
    deps.actions = actions.Registry(wire(parse_config({}), deps, []))
    assert wire_persona(parse_config({}), deps)
    hud = SinkHud()

    async def speak(result: ActionResult) -> bool:
        if spoken is not None:
            spoken.append(result.speech)
        return True

    w = install(LearningConfig(storage="jsonl"), hud, TurnPipeline(deps), repo=JsonlRepo(tmp_path),
                clock=lambda: AT, start=False, job_model=model, speak=speak)
    assert w is not None
    w.opening_poll_s = 0.01
    return w, hud


async def _interview(w, hud, n: int = 3) -> None:
    await w.set_mode(True)
    await w.on_learning(LmJobMsg(text=VAGA, source="clipboard"))
    await w.wait_idle()
    for a in ANSWERS[:n]:
        await w.on_learning(LmSayMsg(a))
        await w.wait_idle()
    assert w.run is not None and w.run.answers == n


async def test_fim_com_retorno_publica_debrief_e_linha_falada(tmp_path) -> None:
    spoken: list[str] = []
    model = FakeModel({"job_profile:*": _job_answer(), DKEY: _answer()})
    w, hud = _make(tmp_path, model, spoken)
    await _interview(w, hud)
    await w.on_learning(LmInterviewMsg(cmd="end"))
    await w.wait_idle()
    (msg,) = hud.of(LmDebriefMsg)
    assert msg.title == "Senior Backend Engineer (Python)" and msg.company == "Quillfeather Payments"
    assert msg.debrief.score_of(Aspect.CLARITY) == 74
    assert msg.to_dict()["scores"][0] == {"aspect": "fluency", "score": 100, "note": "x" * 200}
    assert hud.lines()[-1] == DEBRIEF_READY and spoken[-1] == DEBRIEF_READY
    assert hud.of(LmTopicMsg)[-1].topic is Topic.FREE
    assert await w.interviews.unseen() is None  # já mostrado
    assert sum(c[2]["title"] == "interview_debrief" for c in model.calls) == 1


async def test_turno_nao_espera_o_retorno(tmp_path) -> None:
    model = GatedModel({"job_profile:*": _job_answer(), DKEY: _answer()})
    model.gate.set()
    w, hud = _make(tmp_path, model)
    await _interview(w, hud)
    model.gate.clear()
    model.started.clear()
    await asyncio.wait_for(w.on_learning(LmSayMsg("end the interview")), 1.0)
    await asyncio.wait_for(model.started.wait(), 1.0)
    assert w.run is None and hud.of(LmTopicMsg)[-1].topic is Topic.FREE
    assert hud.of(LmInterviewMsg)[-1].state is RunState.DEBRIEFING  # "WRITING THE DEBRIEF"
    assert not hud.of(LmDebriefMsg)
    model.gate.set()
    await w.wait_idle()
    assert len(hud.of(LmDebriefMsg)) == 1
    assert hud.of(LmInterviewMsg)[-1].state is RunState.DONE


async def test_menos_de_3_respostas_sem_retorno(tmp_path) -> None:
    model = FakeModel({"job_profile:*": _job_answer(), DKEY: _answer()})
    w, hud = _make(tmp_path, model)
    await _interview(w, hud, n=2)
    await w.on_learning(LmInterviewMsg(cmd="end"))
    await w.wait_idle()
    assert not hud.of(LmDebriefMsg)
    assert hud.lines()[-1] == DEBRIEF_TOO_SHORT.format(n=3)
    assert all(c[2]["title"] != "interview_debrief" for c in model.calls)


async def test_orcamento_estourado_linha_sem_debrief(tmp_path) -> None:
    model = FakeModel({"job_profile:*": _job_answer(), DKEY: ModelBudget("teto")})
    w, hud = _make(tmp_path, model)
    await _interview(w, hud)
    await w.on_learning(LmInterviewMsg(cmd="end"))
    await w.wait_idle()
    assert not hud.of(LmDebriefMsg)
    assert hud.lines()[-1] == DEBRIEF_FAILED.format(code="budget")


async def test_shutdown_grava_sem_publicar_e_abertura_mostra_uma_vez(tmp_path) -> None:
    model = FakeModel({"job_profile:*": _job_answer(), DKEY: _answer()})
    w, hud = _make(tmp_path, model)
    await _interview(w, hud)
    await w.aclose()
    assert not hud.of(LmDebriefMsg)
    saved = await w.interviews.unseen()
    assert saved is not None and saved.run_id.startswith("IV-20261011-")

    w2, hud2 = _make(tmp_path, model)  # núcleo novo, mesmo repositório
    await w2.set_mode(True)
    assert hud2.of(LmSessionMsg)[-1].debrief_unseen is True
    (msg,) = hud2.of(LmDebriefMsg)
    assert msg.debrief == saved
    await w2.set_mode(False)
    await w2.set_mode(True)
    assert len(hud2.of(LmDebriefMsg)) == 1 and hud2.of(LmSessionMsg)[-1].debrief_unseen is False


async def test_idle_gera_em_segundo_plano(tmp_path) -> None:
    model = FakeModel({"job_profile:*": _job_answer(), DKEY: _answer()})
    w, hud = _make(tmp_path, model)
    await _interview(w, hud)
    await w.set_mode(False, "idle")
    await w.wait_idle()
    assert not hud.of(LmDebriefMsg) and await w.interviews.unseen() is not None


# ---------------------------------------------------------------------------------------------
# LI5.1: título do retorno pendente depois de reiniciar e ``{"cmd":"debrief"}`` (retry)
# ---------------------------------------------------------------------------------------------


async def test_li51_retorno_pendente_depois_de_reiniciar_tem_titulo(tmp_path) -> None:
    model = FakeModel({"job_profile:*": _job_answer(), DKEY: _answer()})
    w, hud = _make(tmp_path, model)
    await _interview(w, hud)
    await w.aclose()
    w2, hud2 = _make(tmp_path, model)  # núcleo novo: sem o cache em memória
    await w2.set_mode(True)
    (msg,) = hud2.of(LmDebriefMsg)
    assert msg.title == "Senior Backend Engineer (Python)" and msg.company == "Quillfeather Payments"
    assert msg.at == AT


def _refusals(hud) -> list[str | None]:
    return [m.error for m in hud.of(LmInterviewMsg) if m.state is RunState.ERROR]


async def test_li51_retry_do_retorno_depois_da_falha(tmp_path) -> None:
    model = FakeModel({"job_profile:*": _job_answer(), DKEY: ModelBudget("teto")})
    w, hud = _make(tmp_path, model)
    await w.set_mode(True)
    await w.on_learning(LmInterviewMsg(cmd="debrief"))  # nada encerrado ainda
    assert _refusals(hud) == [DEBRIEF_RETRY_NONE]
    await _interview(w, hud)
    await w.on_learning(LmInterviewMsg(cmd="end"))
    await w.wait_idle()
    assert not hud.of(LmDebriefMsg) and hud.lines()[-1] == DEBRIEF_FAILED.format(code="budget")
    w.job_model = FakeModel({DKEY: _answer()})  # teto liberado
    await w.on_learning(LmInterviewMsg(cmd="debrief"))
    await w.wait_idle()
    (msg,) = hud.of(LmDebriefMsg)
    assert msg.title == "Senior Backend Engineer (Python)"
    assert hud.of(LmInterviewMsg)[-1].state is RunState.DONE
    states = [m.state for m in hud.of(LmInterviewMsg)]
    assert states[-2:] == [RunState.DEBRIEFING, RunState.DONE]
    await w.on_learning(LmInterviewMsg(cmd="debrief"))  # já tem retorno
    assert _refusals(hud)[-1] == DEBRIEF_RETRY_DONE
    assert len(hud.of(LmDebriefMsg)) == 1


async def test_li51_retry_pelo_run_id_depois_de_reiniciar(tmp_path) -> None:
    model = FakeModel({"job_profile:*": _job_answer(), DKEY: ModelInvalid("ruim")})
    w, hud = _make(tmp_path, model)
    await _interview(w, hud)
    rid = w.run.id
    await w.on_learning(LmInterviewMsg(cmd="end"))
    await w.wait_idle()
    assert not hud.of(LmDebriefMsg)
    w2, hud2 = _make(tmp_path, FakeModel({DKEY: _answer()}))
    await w2.set_mode(True)
    await w2.on_learning(LmInterviewMsg(cmd="debrief"))  # sem run_id: nada neste processo
    assert _refusals(hud2) == [DEBRIEF_RETRY_NONE]
    await w2.on_learning(LmInterviewMsg(cmd="debrief", run_id=rid))
    await w2.wait_idle()
    (msg,) = hud2.of(LmDebriefMsg)
    assert msg.debrief.run_id == rid and msg.company == "Quillfeather Payments"
    assert hud2.lines()[-1] == DEBRIEF_READY
