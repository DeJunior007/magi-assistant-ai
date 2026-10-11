"""Roteiro da simulação (dona: **LI1.2**; spec §4, R2.3). Puro e determinístico, sem LLM.

A tabela da spec §4 vale para 30 min; outros tempos escalam minutos e cotas (meio para cima,
cota ≥ 1) e a diferença para ``minutes`` vai/sai de EXPERIENCE.
"""

from __future__ import annotations

from magi.learning.interview.contracts import (
    SENIORITY_RANK,
    InterviewPlan,
    JobProfile,
    Seniority,
    Stage,
    StageKind,
)

DEFAULT_MINUTES = 30  # D6
BASE_MINUTES = 30  # tempo da tabela da spec §4
TECHNICAL_MAX = 2
DESIGN_WORDS = ("design", "architecture")
_JUNIORS = (Seniority.INTERN, Seniority.JUNIOR)


def _half_up(x: float) -> int:
    return int(x + 0.5)


def tech_skills(profile: JobProfile) -> tuple[str, ...]:
    """Skills das etapas TECHNICAL: as 2 primeiras dos ``must`` técnicos; senão ``stack[0]``."""
    out: list[str] = []
    for req in profile.must:
        if req.skill and req.skill.strip() and req.skill.lower() not in (s.lower() for s in out):
            out.append(req.skill)
        if len(out) == TECHNICAL_MAX:
            break
    if not out and profile.stack:
        out.append(profile.stack[0])
    return tuple(out)


def wants_design(profile: JobProfile) -> bool:
    """SYSTEM_DESIGN entra com senioridade ≥ SENIOR ou "design"/"architecture" nos requisitos."""
    if profile.seniority in _JUNIORS:
        return False
    if SENIORITY_RANK[profile.seniority] >= SENIORITY_RANK[Seniority.SENIOR]:
        return True
    return any(w in r.text.lower() for r in profile.requirements for w in DESIGN_WORDS)


def _soft_requirement(profile: JobProfile) -> tuple[str, ...]:
    """Um requisito não técnico (``skill is None``), ``must`` antes de ``nice``."""
    soft = [r for r in profile.requirements if r.skill is None]
    soft.sort(key=lambda r: r.kind != "must")
    return (soft[0].text,) if soft else ()


def _table(profile: JobProfile) -> list[Stage]:
    """Etapas para 30 min, na ordem da tabela da spec §4."""
    junior = profile.seniority in _JUNIORS
    motive = profile.domain or profile.title
    stages = [
        Stage(StageKind.INTRO, "INTRO", ("tell me about yourself", f"motivation: {motive}"), 1, 3),
        Stage(StageKind.EXPERIENCE, "EXPERIENCE", profile.responsibilities, 2, 6),
    ]
    stages += [
        Stage(StageKind.TECHNICAL, f"TECHNICAL — {skill}", (skill,), 2, 5,
              followups=1 if junior else 2)
        for skill in tech_skills(profile)
    ]
    if wants_design(profile):
        stages.append(Stage(StageKind.SYSTEM_DESIGN, "SYSTEM DESIGN", (motive,), 1, 6, followups=3))
    stages += [
        Stage(StageKind.BEHAVIOURAL, "BEHAVIOURAL", (*_soft_requirement(profile), "STAR"), 2, 5),
        Stage(StageKind.CANDIDATE_QS, "CANDIDATE QUESTIONS", ("do you have any questions for us?",),
              1, 3, followups=0),
        Stage(StageKind.WRAP, "WRAP", ("thanks", "next steps"), 0, 1, followups=0),
    ]
    return stages


def _scale(stage: Stage, factor: float) -> Stage:
    q = max(1, _half_up(stage.questions * factor)) if stage.questions else 0
    m = max(1, _half_up(stage.minutes * factor))
    return Stage(stage.kind, stage.label, stage.focus, q, m, stage.followups)


def _with_minutes(stage: Stage, minutes: int) -> Stage:
    return Stage(stage.kind, stage.label, stage.focus, stage.questions, minutes, stage.followups)


def build_plan(profile: JobProfile, minutes: int = DEFAULT_MINUTES, *, job_id: str) -> InterviewPlan:
    """Etapas e cotas da tabela da spec §4; soma dos minutos = ``minutes`` (ajuste em EXPERIENCE).

    Se EXPERIENCE ficaria abaixo de 1 min, o resto sai da maior etapa (cada uma fica com ≥ 1).
    ``ValueError`` se ``minutes`` não comporta 1 min por etapa.
    """
    table = _table(profile)
    if minutes < len(table):
        raise ValueError(f"{minutes} min não cabem {len(table)} etapas")
    stages = [_scale(s, minutes / BASE_MINUTES) for s in table]
    exp = next(i for i, s in enumerate(stages) if s.kind is StageKind.EXPERIENCE)
    rest = sum(s.minutes for i, s in enumerate(stages) if i != exp)
    stages[exp] = _with_minutes(stages[exp], max(1, minutes - rest))
    over = sum(s.minutes for s in stages) - minutes
    while over > 0:  # só quando EXPERIENCE bateu no piso
        i = max(range(len(stages)), key=lambda k: stages[k].minutes)
        stages[i] = _with_minutes(stages[i], stages[i].minutes - 1)
        over -= 1
    return InterviewPlan(job_id=job_id, minutes=minutes, stages=tuple(stages))
