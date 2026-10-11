"""LI1.2 — roteiro da simulação (spec §4, CA-03): um teste por linha da tabela e as regras."""

from __future__ import annotations

import pytest

from magi.learning.interview.contracts import JobProfile, Requirement, Seniority, StageKind
from magi.learning.interview.plan import build_plan

JOB = "JOB-0123abcd"
K = StageKind


def req(text: str, skill: str | None = None, kind: str = "must") -> Requirement:
    return Requirement(text=text, kind=kind, skill=skill, evidence=text[:40])


def profile(
    seniority: Seniority = Seniority.MID,
    reqs: tuple[Requirement, ...] = (),
    stack: tuple[str, ...] = ("python", "postgres"),
    domain: str | None = "fintech",
) -> JobProfile:
    return JobProfile(
        title="Backend Engineer", company="Acme", seniority=seniority, language="en",
        stack=stack, requirements=reqs, responsibilities=("build APIs", "on-call"),
        domain=domain, remote="remote",
    )


SENIOR3 = profile(
    Seniority.SENIOR,
    (req("5+ years of Python", "Python"), req("Kafka in production", "Kafka"),
     req("Kubernetes", "kubernetes"), req("Strong communication"), req("Go", "go", "nice")),
)


def kinds(plan):
    return [s.kind for s in plan.stages]


def stage(plan, kind):
    return next(s for s in plan.stages if s.kind is kind)


# --- uma linha da tabela por teste (30 min) -------------------------------------------------


def test_intro_sempre():
    s = stage(build_plan(profile(), job_id=JOB), K.INTRO)
    assert (s.label, s.questions, s.minutes) == ("INTRO", 1, 3)
    assert "tell me about yourself" in s.focus and "motivation: fintech" in s.focus


def test_experience_sempre_com_responsabilidades():
    s = stage(build_plan(SENIOR3, job_id=JOB), K.EXPERIENCE)
    assert (s.label, s.questions) == ("EXPERIENCE", 2)
    assert s.focus == ("build APIs", "on-call")


def test_technical_duas_primeiras_skills_must():
    plan = build_plan(SENIOR3, job_id=JOB)
    tech = [s for s in plan.stages if s.kind is K.TECHNICAL]
    assert [s.label for s in tech] == ["TECHNICAL — Python", "TECHNICAL — Kafka"]
    assert all((s.questions, s.minutes, s.followups) == (2, 5, 2) for s in tech)
    assert tech[0].focus == ("Python",)


def test_system_design_para_senior():
    s = stage(build_plan(SENIOR3, job_id=JOB), K.SYSTEM_DESIGN)
    assert (s.questions, s.followups, s.minutes) == (1, 3, 6)
    assert s.focus == ("fintech",)


def test_system_design_por_palavra_nos_requisitos():
    mid = profile(reqs=(req("Experience with software architecture"),))
    assert K.SYSTEM_DESIGN in kinds(build_plan(mid, job_id=JOB))
    assert K.SYSTEM_DESIGN not in kinds(build_plan(profile(), job_id=JOB))


def test_behavioural_requisito_nao_tecnico_star():
    p = profile(reqs=(req("Mentoring", kind="nice"), req("Strong communication"), req("SQL", "sql")))
    s = stage(build_plan(p, job_id=JOB), K.BEHAVIOURAL)
    assert (s.questions, s.minutes) == (2, 5)
    assert s.focus == ("Strong communication", "STAR")


def test_candidate_qs_sempre():
    s = stage(build_plan(profile(), job_id=JOB), K.CANDIDATE_QS)
    assert (s.questions, s.minutes) == (1, 3)
    assert s.label == "CANDIDATE QUESTIONS"


def test_wrap_sempre_sem_perguntas():
    s = build_plan(profile(), job_id=JOB).stages[-1]
    assert (s.kind, s.questions, s.minutes, s.quota) == (K.WRAP, 0, 1, 0)


# --- regras condicionais ---------------------------------------------------------------------


def test_ordem_completa_senior():
    assert kinds(build_plan(SENIOR3, job_id=JOB)) == [
        K.INTRO, K.EXPERIENCE, K.TECHNICAL, K.TECHNICAL, K.SYSTEM_DESIGN,
        K.BEHAVIOURAL, K.CANDIDATE_QS, K.WRAP,
    ]


def test_sem_must_tecnico_usa_primeiro_da_stack():
    plan = build_plan(profile(reqs=(req("Teamwork"),)), job_id=JOB)
    tech = [s for s in plan.stages if s.kind is K.TECHNICAL]
    assert [s.label for s in tech] == ["TECHNICAL — python"]


def test_skill_repetida_conta_uma_vez():
    p = profile(reqs=(req("Python", "Python"), req("python again", "python"), req("Go", "go")))
    labels = [s.label for s in build_plan(p, job_id=JOB).stages if s.kind is K.TECHNICAL]
    assert labels == ["TECHNICAL — Python", "TECHNICAL — go"]


def test_junior_sem_stack():
    p = profile(Seniority.JUNIOR, reqs=(req("Teamwork"), req("architecture basics")), stack=())
    plan = build_plan(p, job_id=JOB)
    assert kinds(plan) == [K.INTRO, K.EXPERIENCE, K.BEHAVIOURAL, K.CANDIDATE_QS, K.WRAP]
    assert sum(s.minutes for s in plan.stages) == 30


@pytest.mark.parametrize("sen", [Seniority.INTERN, Seniority.JUNIOR])
def test_intern_junior_followups_1_sem_design(sen):
    p = profile(sen, reqs=(req("Python", "python"), req("system design")))
    plan = build_plan(p, job_id=JOB)
    assert K.SYSTEM_DESIGN not in kinds(plan)
    assert stage(plan, K.TECHNICAL).followups == 1


@pytest.mark.parametrize("sen", [Seniority.STAFF, Seniority.LEAD])
def test_acima_de_senior_tem_design(sen):
    assert K.SYSTEM_DESIGN in kinds(build_plan(profile(sen), job_id=JOB))


def test_sem_behavioural_soft_fica_so_star():
    p = profile(reqs=(req("Python", "python"),))
    assert stage(build_plan(p, job_id=JOB), K.BEHAVIOURAL).focus == ("STAR",)


# --- minutos ---------------------------------------------------------------------------------


@pytest.mark.parametrize("prof", [SENIOR3, profile(Seniority.JUNIOR, stack=()), profile()])
@pytest.mark.parametrize("minutes", [20, 30, 45])
def test_soma_exata(prof, minutes):
    plan = build_plan(prof, minutes, job_id=JOB)
    assert plan.minutes == minutes and plan.job_id == JOB
    assert sum(s.minutes for s in plan.stages) == minutes
    assert all(s.minutes >= 1 for s in plan.stages)
    assert all(s.questions >= 1 for s in plan.stages if s.kind is not K.WRAP)


def test_ajuste_vai_para_experience():
    plan = build_plan(SENIOR3, 30, job_id=JOB)  # tabela soma 34 → EXPERIENCE 6 - 4
    assert stage(plan, K.EXPERIENCE).minutes == 2
    junior = build_plan(profile(Seniority.JUNIOR, stack=()), 30, job_id=JOB)  # 18 → +12
    assert stage(junior, K.EXPERIENCE).minutes == 18


def test_escala_45_min():
    plan = build_plan(SENIOR3, 45, job_id=JOB)
    assert stage(plan, K.INTRO).minutes == 5  # 4,5 → 5
    assert stage(plan, K.TECHNICAL).questions == 3
    assert stage(plan, K.INTRO).questions == 2  # 1,5 → 2


def test_piso_de_experience_tira_da_maior_etapa():
    plan = build_plan(SENIOR3, 10, job_id=JOB)
    assert sum(s.minutes for s in plan.stages) == 10
    assert all(s.minutes >= 1 for s in plan.stages)


def test_minutos_demais_poucos():
    with pytest.raises(ValueError):
        build_plan(SENIOR3, 7, job_id=JOB)


def test_deterministico_e_fio():
    a = build_plan(SENIOR3, job_id=JOB)
    assert a == build_plan(SENIOR3, job_id=JOB)
    assert type(a).from_json(a.to_json()) == a
