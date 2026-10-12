"""LI0.1: contratos da entrevista pela vaga (spec §2, §7) e mensagens do socket."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from hud import hud_bridge
from magi.common.contracts import (
    LmDebriefMsg,
    LmInterviewMsg,
    LmJobMsg,
    LmJobRef,
    LmJobReqMsg,
    LmScenarioRef,
    LmSessionMsg,
    LmTopicMsg,
)
from magi.common.events import HudDecodeError, decode_hud
from magi.learning.config import parse_learning
from magi.learning.contracts import Topic
from magi.learning.interview import debrief, extract, plan, run, store
from magi.learning.interview.contracts import (
    JOB_MAX,
    Aspect,
    AspectScore,
    Cover,
    Coverage,
    InterviewDebrief,
    InterviewPlan,
    InterviewRun,
    JobPost,
    JobProfile,
    Requirement,
    RunState,
    Seniority,
    Stage,
    StageKind,
    make_run_id,
)

AT = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def profile() -> JobProfile:
    return JobProfile(
        title="Senior Backend Engineer", company="Acme Pay", seniority=Seniority.SENIOR,
        language="en", stack=("python", "postgresql"),
        requirements=(
            Requirement("5+ years with Python", "must", "python", "5+ years with Python"),
            Requirement("Good communication", "nice", None, "good communication"),
        ),
        responsibilities=("Build payment APIs",), domain="fintech", remote="remote",
    )


def the_plan() -> InterviewPlan:
    return InterviewPlan("JOB-1a2b3c4d", 30, (
        Stage(StageKind.INTRO, "INTRO", (), 1, 3),
        Stage(StageKind.TECHNICAL, "TECHNICAL — PYTHON", ("python",), 2, 26, followups=1),
        Stage(StageKind.WRAP, "WRAP", (), 0, 1),
    ))


def the_run() -> InterviewRun:
    return InterviewRun(
        id=make_run_id(AT, 1), session_id="LS-20261011-01", job_id="JOB-1a2b3c4d",
        profile=profile(), plan=the_plan(), state=RunState.RUNNING, stage=1, asked=2, answers=3,
        stage_started=100.0, started=10.0, paused_s=0.0, first_message_id=4, last_message_id=None,
        asked_log=["Tell me about yourself?"],
    )


def the_debrief(scores: tuple[AspectScore, ...] | None = None) -> InterviewDebrief:
    if scores is None:
        scores = tuple(AspectScore(a, 50 + i * 10, f"note {a}") for i, a in enumerate(Aspect))
    return InterviewDebrief(
        run_id="IV-20261011-01",
        coverage=(Coverage("5+ years with Python", Cover.COVERED, "I used Python for six years"),
                  Coverage("Kubernetes", Cover.MISSED, None)),
        scores=scores,
        strengths=("clear examples",), improve=("use STAR",),
        rewrites=(("Why us?", "Because your payments domain…"),),
        language=("past tense",), closing="Thanks. The feedback is on the screen.",
    )


@pytest.mark.parametrize("obj", [
    JobPost("JOB-1a2b3c4d", "x" * 300, "clipboard", AT),
    profile(), the_plan(), the_run(), the_debrief(), the_debrief(scores=()),
    Coverage("a", Cover.THIN, None), AspectScore(Aspect.JOB_FIT, 0, ""),
])
def test_roundtrip(obj) -> None:
    back = type(obj).from_json(obj.to_json())
    assert back == obj
    assert json.loads(obj.to_json()) == obj.to_dict()


@pytest.mark.parametrize("make", [
    lambda: JobPost("JOB-xyz", "x" * 300, "clipboard", AT),
    lambda: JobPost("JOB-1a2b3c4d", "x" * 300, "file", AT),  # D2: sem pasta
    lambda: JobPost("JOB-1a2b3c4d", "x" * 10, "clipboard", AT),
    lambda: JobPost("JOB-1a2b3c4d", "x" * (JOB_MAX + 1), "clipboard", AT),
    lambda: Requirement("a", "maybe", None, "a"),
    lambda: Requirement("a", "must", None, "e" * 161),
    lambda: JobProfile("", None, Seniority.MID, "en", (), (), (), None, None),
    lambda: JobProfile("T", None, Seniority.MID, "en", ("Python",), (), (), None, None),
    lambda: JobProfile("T", None, Seniority.MID, "en", tuple("abcdefghijklm"), (), (), None, None),
    lambda: JobProfile("T", None, Seniority.MID, "en", (), (), (), None, "mars"),
    lambda: InterviewPlan("JOB-1a2b3c4d", 31, the_plan().stages),
    lambda: Coverage("a", Cover.MISSED, "said something"),
    lambda: AspectScore(Aspect.FLUENCY, 101, ""),
    lambda: AspectScore(Aspect.FLUENCY, -1, ""),
    lambda: AspectScore(Aspect.FLUENCY, True, ""),
    lambda: the_debrief(scores=(AspectScore(Aspect.GRAMMAR, 1, ""), AspectScore(Aspect.GRAMMAR, 2, ""))),
    lambda: the_debrief(scores=(AspectScore(Aspect.CLARITY, 1, ""), AspectScore(Aspect.FLUENCY, 2, ""))),
])
def test_validation(make) -> None:
    with pytest.raises(ValueError):
        make()


def test_run_validation_and_helpers() -> None:
    r = the_run()
    assert r.current.label == "TECHNICAL — PYTHON" and r.current.quota == 4
    assert [q.text for q in profile().must] == ["5+ years with Python"]
    d = r.to_dict()
    d["stage"] = 3
    with pytest.raises(ValueError):
        InterviewRun.from_dict(d)
    d = r.to_dict()
    del d["asked_log"]
    assert InterviewRun.from_dict(d).asked_log == []


def test_debrief_scores_by_aspect_no_overall() -> None:
    d = the_debrief(scores=(AspectScore(Aspect.FLUENCY, 70, "ok"), AspectScore(Aspect.JOB_FIT, 40, "x")))
    assert d.score_of(Aspect.FLUENCY) == 70 and d.score_of(Aspect.GRAMMAR) is None
    assert "score" not in d.to_dict() and "overall" not in d.to_dict()


def test_stubs_have_final_signatures() -> None:
    # Todos os stubs implementados (LI1.1–LI1.3, LI2.3): sobram as constantes e os prompts.
    assert callable(extract.extract) and callable(plan.build_plan) and callable(run.block)
    assert callable(debrief.debrief) and debrief.MIN_ANSWERS == 3
    assert store.InterviewStore(None).repo is None
    assert "No overall score" in (extract.PROMPT.parent / "debrief.md").read_text()


# --- socket (spec §7) ---------------------------------------------------------------------


def wire(msg) -> dict:
    return json.loads(msg.to_json())


@pytest.mark.parametrize("msg", [
    LmJobMsg(text="x" * 300, source="clipboard"),
    LmJobMsg(job_id="JOB-1a2b3c4d"),
    LmJobReqMsg(),
    LmInterviewMsg(cmd="end"),
    LmInterviewMsg(state=RunState.PREPARING),
    LmInterviewMsg(state=RunState.RUNNING, job_id="JOB-1a2b3c4d", run_id="IV-20261011-01",
                   title="Senior Backend", company="Acme", seniority="senior",
                   stack=("python",), must=("5+ years",), stage=1, n_stages=3,
                   stage_label="TECHNICAL — PYTHON", asked=2, quota=4, elapsed_s=61.5, minutes=30),
    LmInterviewMsg(state=RunState.ERROR, job_id="JOB-1a2b3c4d", error="timeout"),
    LmDebriefMsg(debrief=the_debrief(), title="Senior Backend", at=AT, company="Acme"),
    LmDebriefMsg(debrief=the_debrief(scores=()), title="Senior Backend", at=AT),
    LmSessionMsg(id="LS-20261011-01", started_at=AT, level="B2", track="C", topic=Topic.INTERVIEW,
                 jobs=(LmJobRef("JOB-1a2b3c4d", "Backend", "Acme"), LmJobRef("JOB-00000000", "Data")),
                 debrief_unseen=True, scenarios=(LmScenarioRef("hotel_checkin", "Hotel check-in"),)),
    LmTopicMsg(topic=Topic.FREE, scenario="hotel_checkin"),
])
def test_socket_roundtrip(msg) -> None:
    back = decode_hud(msg.to_json())
    assert back == msg
    assert hud_bridge.decode_line(msg.to_json()) == wire(msg)
    assert hud_bridge._decode_min(msg.to_json()) == wire(msg)


def test_session_old_shape_unchanged() -> None:
    m = LmSessionMsg(id="LS-20261011-01", started_at=AT, level="B2", track="C", topic=Topic.FREE)
    assert set(m.to_dict()) == {"t", "id", "started_at", "level", "track", "topic", "n_msgs",
                                "obs_count"}
    assert "scenario" not in LmTopicMsg(topic=Topic.FREE).to_dict()


@pytest.mark.parametrize("line", [
    {"t": "lm_job", "text": "x" * (JOB_MAX + 1), "source": "clipboard"},
    {"t": "lm_job"},
    {"t": "lm_job", "text": "x" * 300, "job_id": "JOB-1a2b3c4d"},
    {"t": "lm_job", "text": "   "},
])
def test_lm_job_refused(line) -> None:
    raw = json.dumps(line)
    with pytest.raises(HudDecodeError):
        decode_hud(raw)
    with pytest.raises(hud_bridge.DecodeError):
        hud_bridge._decode_min(raw)


def test_job_max_edge_and_other_refusals() -> None:
    ok = json.dumps({"t": "lm_job", "text": "x" * JOB_MAX, "source": "clipboard"})
    assert decode_hud(ok).text == "x" * JOB_MAX
    assert hud_bridge.JOB_MAX == JOB_MAX
    for bad in ({"t": "lm_job", "text": "x" * 300, "source": "file"},
                {"t": "lm_interview", "cmd": "dance"},
                {"t": "lm_interview"},
                {"t": "lm_interview", "state": "nope"},
                {"t": "lm_debrief", "title": "T", "at": AT.isoformat()}):
        with pytest.raises(HudDecodeError):
            decode_hud(json.dumps(bad))


def test_encode_lm_from_ui() -> None:
    line = hud_bridge.encode_lm("lm_job", {"text": "x" * 300, "source": "clipboard"})
    assert decode_hud(line) == LmJobMsg(text="x" * 300, source="clipboard")
    assert decode_hud(hud_bridge.encode_lm("lm_interview", {"cmd": "end"})) == LmInterviewMsg(cmd="end")
    with pytest.raises(hud_bridge.DecodeError):
        hud_bridge.encode_lm("lm_job", {"text": "x" * (JOB_MAX + 1)})
    with pytest.raises(hud_bridge.DecodeError):
        hud_bridge.encode_lm("lm_interview", {})


def test_config_interview_minutes() -> None:
    assert parse_learning({}).interview_minutes == 30
    assert parse_learning({"learning": {"interview_minutes": 45}}).interview_minutes == 45
    assert not hasattr(parse_learning({}), "jobs_dir")  # D2
