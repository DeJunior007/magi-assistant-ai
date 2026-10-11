"""LI1.3: máquina da simulação (spec §5; CA-04). Relógio falso, sem LLM."""

from __future__ import annotations

import json

import pytest

from magi.common.contracts import LmInterviewMsg
from magi.learning.interview import run
from magi.learning.interview.contracts import (
    BLOCK_MAX,
    InterviewRun,
    JobProfile,
    Requirement,
    RunState,
    Seniority,
    StageKind,
)
from magi.learning.interview.plan import build_plan

T0 = 1_000.0


def profile(**kw) -> JobProfile:
    base = dict(
        title="Senior Backend Engineer", company="Acme Pay", seniority=Seniority.SENIOR,
        language="en", stack=("python", "postgresql", "kubernetes"),
        requirements=(
            Requirement("5+ years with Python", "must", "python", "5+ years with python"),
            Requirement("PostgreSQL in production", "must", "postgresql", "postgresql"),
            Requirement("Good communication", "must", None, "good communication"),
        ),
        responsibilities=("Build payment APIs",), domain="fintech", remote="remote",
    )
    base.update(kw)
    return JobProfile(**base)


def new_run(p: JobProfile | None = None, minutes: int = 30) -> InterviewRun:
    p = p or profile()
    plan = build_plan(p, minutes, job_id="JOB-1a2b3c4d")
    return run.start(plan, p, "LS-20261011-01", T0, run_id="IV-20261011-01")


def test_start_ready_stage0() -> None:
    r = new_run()
    assert r.state is RunState.READY and r.stage == 0 and r.asked == 0 and r.asked_log == []
    assert InterviewRun.from_dict(r.to_dict()) == r


def test_ca04_thirty_minutes_walk_all_stages() -> None:
    r = new_run()
    kinds = [s.kind for s in r.plan.stages]
    seen = {r.current.kind}
    now, n = T0, 0
    while r.state in (RunState.READY, RunState.RUNNING) and now < T0 + 40 * 60:
        assert len(run.block(r, now)) <= BLOCK_MAX
        if n % 3 == 0:  # turno a cada 90 s: pergunta da Condessa e resposta do Pedro
            run.observe(r, f"Nice. Question number {n}?", pedro_answered=n > 0, now=now)
        else:
            run.tick(r, now)
        if r.state in (RunState.READY, RunState.RUNNING):
            seen.add(r.current.kind)
        now += 30
        n += 1
    assert seen == set(kinds) and r.state is RunState.DEBRIEFING
    assert now - T0 <= 31 * 60


def test_observe_counts_questions_outside_quotes_and_logs() -> None:
    r = new_run()
    assert run.observe(r, 'He said "why?" to me. Fine.', False, T0) is True  # READY → RUNNING
    assert r.state is RunState.RUNNING and r.asked == 0
    run.observe(r, "Great. So, tell me about yourself? Take your time.", True, T0 + 5)
    assert r.answers == 1
    assert r.asked == 1 and r.asked_log == ["So, tell me about yourself?"]


def test_advance_by_quota_and_transition_line() -> None:
    r = new_run()
    intro = r.current  # 1 pergunta × (1 + 2) follow-ups
    for i in range(intro.quota):
        run.observe(r, f"Q{i}?", True, T0 + i)
    assert r.stage == 1 and r.asked == 0 and r.stage_started == T0 + intro.quota - 1
    b = run.block(r, T0 + 10)
    assert b.endswith(run.TRANSITION) and "Stage 2/" in b
    run.observe(r, "Let's move on to your experience. What did you build?", True, T0 + 20)
    assert run.TRANSITION not in run.block(r, T0 + 21)


def test_advance_by_time_and_tick() -> None:
    r = new_run()
    run.observe(r, "Hi?", False, T0)
    mins = r.current.minutes
    assert run.tick(r, T0 + mins * 60 - 1) is False
    assert run.tick(r, T0 + mins * 60) is True and r.stage == 1


def test_main_question_number_in_block() -> None:
    r = new_run()
    run.apply(r, "skip_stage", T0)  # EXPERIENCE: 2 perguntas, 2 follow-ups
    assert r.current.kind is StageKind.EXPERIENCE
    assert "question 1 of 2" in run.block(r, T0)
    for i in range(3):
        run.observe(r, f"Q{i}?", True, T0 + i)
    assert "question 2 of 2" in run.block(r, T0 + 5)


def test_wrap_closes_after_one_condessa_turn() -> None:
    r = new_run()
    while r.current.kind is not StageKind.WRAP:
        run.apply(r, "skip_stage", T0)
    assert run.apply(r, "skip_stage", T0) is False and run.apply(r, "next", T0) is False
    run.observe(r, "Thanks, Pedro. We'll be in touch.", True, T0 + 1)
    assert r.state is RunState.DONE  # só 1 resposta: sem retorno
    assert run.observe(r, "Hello?", True, T0 + 2) is False and r.answers == 1


def test_pause_freezes_stage_clock_and_speech_resumes() -> None:
    r = new_run()
    run.observe(r, "Hi?", False, T0)
    mins = r.current.minutes
    assert run.apply(r, "pause", T0 + 60) is True and r.state is RunState.PAUSED
    assert run.apply(r, "pause", T0 + 61) is False
    assert run.tick(r, T0 + 3600) is False and r.stage == 0
    assert "Time left in stage: 2 min" in run.block(r, T0 + 3600)
    assert run.progress(r, T0 + 3600)["elapsed_s"] == 60.0
    # pausa sobrevive ao JSON
    r = InterviewRun.from_dict(json.loads(json.dumps(r.to_dict())))
    assert run.observe(r, "Anything else?", False, T0 + 3700) is False  # Pedro calado: segue pausada
    assert run.observe(r, "", True, T0 + 4000) is True and r.state is RunState.RUNNING
    assert r.paused_s == 4000 - 60
    assert run.progress(r, T0 + 4010)["elapsed_s"] == 70.0
    assert run.tick(r, T0 + 4000 + mins * 60 - 61) is False
    assert run.tick(r, T0 + 4000 + mins * 60 - 60) is True and r.stage == 1


@pytest.mark.parametrize(("text", "cmd"), [
    ("next question", "next"), ("Next question, please!", "next"), ("Skip this one.", "next"),
    ("Próxima pergunta", "next"), ("pula essa", "next"),
    ("Can you repeat the question?", "repeat"), ("repete a pergunta", "repeat"),
    ("Next stage", "skip_stage"), ("Let's move on", "skip_stage"), ("próxima etapa", "skip_stage"),
    ("Pause the interview.", "pause"), ("pausa a entrevista", "pause"),
    ("End the interview", "end"), ("let's stop here", "end"), ("Encerra a entrevista!", "end"),
    ("How am I doing?", None), ("what's the next question about", None),
    ("I think the next question", None), ("", None),
])
def test_command_of(text: str, cmd: str | None) -> None:
    assert run.command_of(text) == cmd


def test_apply_next_jumps_to_next_main_question() -> None:
    r = new_run()
    run.apply(r, "skip_stage", T0)  # EXPERIENCE: 2 × (1 + 2)
    run.observe(r, "Q?", True, T0 + 1)
    assert run.apply(r, "next", T0 + 2) is True and r.asked == 3 and r.stage == 1
    assert run.apply(r, "next", T0 + 3) is True and r.stage == 2  # fechou a cota
    assert run.apply(r, "repeat", T0 + 4) is False and run.apply(r, "end", T0 + 4) is False


def test_finish_reasons_and_states() -> None:
    r = new_run()
    with pytest.raises(ValueError):
        run.finish(r, "bored", T0)
    for i in range(3):
        run.observe(r, "Hm.", True, T0 + i)
    run.apply(r, "pause", T0 + 10)
    run.finish(r, "voice", T0 + 20)
    assert r.state is RunState.DEBRIEFING and r.paused_s == 10
    run.finish(r, "button", T0 + 30)
    assert r.state is RunState.DEBRIEFING
    assert run.apply(r, "next", T0 + 40) is False and run.tick(r, T0 + 9999) is False


def test_block_layout_and_priority_cut() -> None:
    r = new_run()
    b = run.block(r, T0)
    lines = b.split("\n")
    assert lines[-4].startswith("Role: Senior Backend Engineer at Acme Pay (senior, remote).")
    assert "Domain: fintech." in b and "Stack: python, postgresql, kubernetes" in b
    assert "Must-haves: 5+ years with Python; PostgreSQL in production" in b
    assert "Stage 1/" in b and "Already asked" not in b and run.TRANSITION not in b
    # perfil enorme: corta stack/asked/must antes de etapa e conduct
    big = profile(
        title="T" * 300, company="C" * 300, domain="d" * 200,
        stack=tuple(f"{'s' * 60}{i:02d}" for i in range(12)),
        requirements=tuple(Requirement("r" * 150 + str(i), "must", None, "x") for i in range(14)),
    )
    r = new_run(big)
    for i in range(12):
        r.asked_log.append(f"{'q' * 110} {i}?")
    b = run.block(r, T0)
    assert len(b) <= BLOCK_MAX
    assert b.startswith(run._conduct()) and "Stage 1/" in b
    assert "Role: " + "T" * 300 in b and "Stack: " not in b  # role cortado, stack fora


def test_asked_log_blocks_repetition_and_is_capped() -> None:
    r = new_run()
    run.apply(r, "skip_stage", T0)
    for i in range(14):
        run.observe(r, f"Question {i}: {'x' * 200}?", True, T0 + i)
    assert len(r.asked_log) == 12 and all(len(q) <= 120 for q in r.asked_log)
    assert r.asked_log[-1].startswith("Question 13")
    b = run.block(r, T0 + 20)
    assert "Already asked (do not repeat): Question 13" in b


def test_progress_builds_lm_interview() -> None:
    r = new_run(profile(company=None))
    run.observe(r, "Hi?", False, T0)
    d = run.progress(r, T0 + 12.34)
    assert "company" not in d and d["stage"] == 0 and d["n_stages"] == len(r.plan.stages)
    assert d["quota"] == r.current.quota and d["elapsed_s"] == 12.3 and d["minutes"] == 30
    msg = LmInterviewMsg(**d)
    assert msg.state is RunState.RUNNING and msg.must == ("5+ years with Python",
                                                         "PostgreSQL in production",
                                                         "Good communication")
