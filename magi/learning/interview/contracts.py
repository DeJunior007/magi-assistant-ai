"""Contratos da entrevista pela vaga (tarefa LI0.1; spec §2 de ``specs/learning-imersivo``).

Única coisa que uma tarefa LI* precisa ler para falar com módulos de outras tarefas. Só tipos,
constantes, enums e funções puras: nada de I/O.

- Vaga: ``JobPost`` (texto normalizado, ``jobtext``) e ``JobProfile`` (extraído, ``extract``).
- Roteiro: ``Stage`` / ``InterviewPlan`` (``plan``).
- Simulação: ``InterviewRun`` (mutável, dono ``run``).
- Retorno: ``Coverage``, ``AspectScore`` (D3: nota 0–100 por aspecto, sem nota geral) e
  ``InterviewDebrief`` (``debrief``).

Convenções iguais às de ``magi.learning.contracts``: ``to_dict``/``from_dict`` com ida e volta
exata, enums como texto, datas ISO 8601, ``None`` omitido no fio; tuplas viram listas no JSON.
Limites conferidos no ``__post_init__`` (``ValueError``).
"""

from __future__ import annotations

import json
import re
import types
import typing
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from magi.learning.contracts import TOPIC_BLOCK_MAX

# ---------------------------------------------------------------------------------------------
# IDs e limites (spec §1)
# ---------------------------------------------------------------------------------------------

JOB_ID_RE = re.compile(r"^JOB-[0-9a-f]{8}$")
RUN_ID_RE = re.compile(r"^IV-(\d{8})-(\d{2,})$")
JOB_MIN = 200
JOB_MAX = 12_000
#: Colagem no campo com mais que isso (ou com ``\n``) vira a pergunta do rodapé (R1.2).
PASTE_ASK = 600
BLOCK_MAX = TOPIC_BLOCK_MAX
#: Prazos das chamadas de modelo (s).
EXTRACT_TIMEOUT_S = 20.0
DEBRIEF_TIMEOUT_S = 40.0
#: Origens de ``JobPost.source`` (sem ``file``: D2, só clipboard).
JOB_SOURCES = ("clipboard", "voice", "last")
REQ_KINDS = ("must", "nice")
REMOTES = ("remote", "hybrid", "onsite")
#: Comandos da UI em ``lm_interview {"cmd"}`` (spec §7); ``debrief`` refaz o retorno (LI5.1).
INTERVIEW_CMDS = ("next", "skip_stage", "pause", "end", "debrief")

STACK_MAX = 12
REQUIREMENTS_MAX = 14
RESPONSIBILITIES_MAX = 6
EVIDENCE_MAX = 160
ASKED_LOG_MAX = 12
ASKED_MAX = 120
COVER_EVIDENCE_MAX = 200
POINTS_MAX = 3
REWRITES_MAX = 2
LANGUAGE_MAX = 6
SCORE_NOTE_MAX = 200


def make_run_id(day: datetime, n: int) -> str:
    """``IV-YYYYMMDD-NN`` (como ``LS-``)."""
    if n < 1:
        raise ValueError(f"número da simulação no dia deve ser >= 1: {n}")
    return f"IV-{day:%Y%m%d}-{n:02d}"


# ---------------------------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------------------------


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    LEAD = "lead"
    UNKNOWN = "unknown"


#: Ordem para comparar (``seniority ≥ SENIOR`` na spec §4); ``UNKNOWN`` conta como ``MID``.
SENIORITY_RANK = {
    Seniority.INTERN: 0, Seniority.JUNIOR: 1, Seniority.MID: 2, Seniority.UNKNOWN: 2,
    Seniority.SENIOR: 3, Seniority.STAFF: 4, Seniority.LEAD: 4,
}


class StageKind(StrEnum):
    INTRO = "intro"
    EXPERIENCE = "experience"
    TECHNICAL = "technical"
    SYSTEM_DESIGN = "system_design"
    BEHAVIOURAL = "behavioural"
    CANDIDATE_QS = "candidate_qs"
    WRAP = "wrap"


class RunState(StrEnum):
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    DEBRIEFING = "debriefing"
    DONE = "done"
    ERROR = "error"


class Cover(StrEnum):
    COVERED = "covered"
    THIN = "thin"
    MISSED = "missed"


class Aspect(StrEnum):
    """Aspectos com nota 0–100 no retorno (D3, 2026-10-10)."""

    FLUENCY = "fluency"
    GRAMMAR = "grammar"
    VOCABULARY = "vocabulary"
    JOB_FIT = "job_fit"  # aderência aos requisitos da vaga
    CLARITY = "clarity"  # clareza/estrutura das respostas


ASPECT_LABELS: dict[Aspect, str] = {
    Aspect.FLUENCY: "FLUENCY",
    Aspect.GRAMMAR: "GRAMMAR",
    Aspect.VOCABULARY: "VOCABULARY",
    Aspect.JOB_FIT: "JOB FIT",
    Aspect.CLARITY: "CLARITY",
}


# ---------------------------------------------------------------------------------------------
# Serialização (com tuplas)
# ---------------------------------------------------------------------------------------------


def _encode(v: Any) -> Any:
    if isinstance(v, StrEnum):
        return v.value
    if isinstance(v, datetime):
        return v.isoformat()
    if is_dataclass(v) and not isinstance(v, type):
        return v.to_dict()  # type: ignore[attr-defined]
    if isinstance(v, (list, tuple)):
        return [_encode(x) for x in v]
    return v


def _decode(tp: Any, v: Any) -> Any:
    if v is None:
        return None
    origin = typing.get_origin(tp)
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return _decode(args[0], v)
    if origin in (tuple, list):
        if not isinstance(v, (list, tuple)):
            raise ValueError(f"esperava lista, veio {type(v).__name__}")
        args = typing.get_args(tp)
        if origin is list:
            return [_decode(args[0], x) for x in v]
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(args[0], x) for x in v)
        if len(args) != len(v):
            raise ValueError(f"tupla de {len(args)} itens, veio {len(v)}")
        return tuple(_decode(a, x) for a, x in zip(args, v, strict=True))
    if isinstance(tp, type):
        if issubclass(tp, StrEnum):
            return tp(v)
        if tp is datetime:
            return datetime.fromisoformat(v)
        if tp is float:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"esperava número: {v!r}")
            return float(v)
        if tp is int:
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError(f"esperava inteiro: {v!r}")
            return v
        if tp is str and not isinstance(v, str):
            raise ValueError(f"esperava texto: {v!r}")
        if is_dataclass(tp):
            if not isinstance(v, dict):
                raise ValueError(f"{tp.__name__}: esperava objeto")
            return tp.from_dict(v)  # type: ignore[attr-defined]
    return v


class _Wire:
    def to_dict(self) -> dict[str, Any]:
        return {
            f.name: _encode(getattr(self, f.name))
            for f in fields(self)  # type: ignore[arg-type]
            if getattr(self, f.name) is not None
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        hints = typing.get_type_hints(cls)
        kw: dict[str, Any] = {}
        for f in fields(cls):  # type: ignore[arg-type]
            tp = hints[f.name]
            if f.name not in data:
                if type(None) in typing.get_args(tp):
                    kw[f.name] = None
                    continue
                if f.default is not MISSING or f.default_factory is not MISSING:
                    continue
                raise ValueError(f"{cls.__name__}: campo obrigatório ausente: {f.name}")
            kw[f.name] = _decode(tp, data[f.name])
        return cls(**kw)

    @classmethod
    def from_json(cls, line: str) -> Self:
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError(f"{cls.__name__}: JSON deve ser um objeto")
        return cls.from_dict(data)


def _max(name: str, seq: typing.Sized, n: int) -> None:
    if len(seq) > n:
        raise ValueError(f"{name}: mais de {n} itens ({len(seq)})")


def _maxlen(name: str, text: str | None, n: int) -> None:
    if text is not None and len(text) > n:
        raise ValueError(f"{name}: mais de {n} caracteres")


# ---------------------------------------------------------------------------------------------
# Vaga e perfil
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JobPost(_Wire):
    """Texto da vaga já normalizado (``jobtext.normalize``); ``id`` = ``jobtext.job_id(text)``."""

    id: str
    text: str
    source: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not JOB_ID_RE.match(self.id):
            raise ValueError(f"id de vaga inválido: {self.id!r}")
        if self.source not in JOB_SOURCES:
            raise ValueError(f"origem de vaga inválida: {self.source!r}")
        if not JOB_MIN <= len(self.text) <= JOB_MAX:
            raise ValueError(f"texto da vaga fora de {JOB_MIN}..{JOB_MAX}: {len(self.text)}")


@dataclass(frozen=True, slots=True)
class Requirement(_Wire):
    text: str
    kind: str
    skill: str | None
    evidence: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("requisito vazio")
        if self.kind not in REQ_KINDS:
            raise ValueError(f"kind de requisito inválido: {self.kind!r}")
        _maxlen("evidence", self.evidence, EVIDENCE_MAX)


@dataclass(frozen=True, slots=True)
class JobProfile(_Wire):
    title: str
    company: str | None
    seniority: Seniority
    language: str
    stack: tuple[str, ...]
    requirements: tuple[Requirement, ...]
    responsibilities: tuple[str, ...]
    domain: str | None
    remote: str | None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("perfil sem título")
        _max("stack", self.stack, STACK_MAX)
        if any(s != s.lower() for s in self.stack):
            raise ValueError("stack deve vir em minúsculas")
        _max("requirements", self.requirements, REQUIREMENTS_MAX)
        _max("responsibilities", self.responsibilities, RESPONSIBILITIES_MAX)
        if self.remote is not None and self.remote not in REMOTES:
            raise ValueError(f"remote inválido: {self.remote!r}")

    @property
    def must(self) -> tuple[Requirement, ...]:
        return tuple(r for r in self.requirements if r.kind == "must")


# ---------------------------------------------------------------------------------------------
# Roteiro
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Stage(_Wire):
    kind: StageKind
    label: str
    focus: tuple[str, ...]
    questions: int
    minutes: int
    followups: int = 2

    def __post_init__(self) -> None:
        if self.questions < 0 or self.minutes < 0 or self.followups < 0:
            raise ValueError("etapa com cota/minutos/follow-ups negativos")

    @property
    def quota(self) -> int:
        """Perguntas da Condessa na etapa (principais + follow-ups, spec §5.1)."""
        return self.questions * (1 + self.followups)


@dataclass(frozen=True, slots=True)
class InterviewPlan(_Wire):
    job_id: str
    minutes: int
    stages: tuple[Stage, ...]

    def __post_init__(self) -> None:
        if not self.stages:
            raise ValueError("roteiro sem etapas")
        if sum(s.minutes for s in self.stages) != self.minutes:
            raise ValueError("soma dos minutos das etapas difere de minutes")


# ---------------------------------------------------------------------------------------------
# Simulação (mutável; dono = run.py)
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True)
class InterviewRun(_Wire):
    id: str
    session_id: str
    job_id: str
    profile: JobProfile
    plan: InterviewPlan
    state: RunState
    stage: int
    asked: int
    answers: int
    stage_started: float
    started: float
    paused_s: float
    first_message_id: int | None
    last_message_id: int | None
    asked_log: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not RUN_ID_RE.match(self.id):
            raise ValueError(f"id de simulação inválido: {self.id!r}")
        if not 0 <= self.stage < len(self.plan.stages):
            raise ValueError(f"etapa fora do roteiro: {self.stage}")
        if self.asked < 0 or self.answers < 0:
            raise ValueError("contagem negativa")
        _max("asked_log", self.asked_log, ASKED_LOG_MAX)
        for q in self.asked_log:
            _maxlen("asked_log", q, ASKED_MAX)

    @property
    def current(self) -> Stage:
        return self.plan.stages[self.stage]


# ---------------------------------------------------------------------------------------------
# Retorno
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Coverage(_Wire):
    requirement: str
    cover: Cover
    evidence: str | None

    def __post_init__(self) -> None:
        _maxlen("evidence", self.evidence, COVER_EVIDENCE_MAX)
        if self.cover is Cover.MISSED and self.evidence is not None:
            raise ValueError("MISSED não tem evidência")


@dataclass(frozen=True, slots=True)
class AspectScore(_Wire):
    """Nota de 0 a 100 de um aspecto (D3), com uma frase de motivo."""

    aspect: Aspect
    score: int
    note: str

    def __post_init__(self) -> None:
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise ValueError(f"nota deve ser inteira: {self.score!r}")
        if not 0 <= self.score <= 100:
            raise ValueError(f"nota fora de 0..100: {self.score}")
        _maxlen("note", self.note, SCORE_NOTE_MAX)


@dataclass(frozen=True, slots=True)
class InterviewDebrief(_Wire):
    run_id: str
    coverage: tuple[Coverage, ...]
    scores: tuple[AspectScore, ...]
    strengths: tuple[str, ...]
    improve: tuple[str, ...]
    rewrites: tuple[tuple[str, str], ...]
    language: tuple[str, ...]
    closing: str

    def __post_init__(self) -> None:
        _max("scores", self.scores, len(Aspect))
        seen = [s.aspect for s in self.scores]
        if len(set(seen)) != len(seen):
            raise ValueError("aspecto repetido nas notas")
        order = list(Aspect)
        if seen != sorted(seen, key=order.index):
            raise ValueError("notas fora da ordem do enum Aspect")
        _max("strengths", self.strengths, POINTS_MAX)
        _max("improve", self.improve, POINTS_MAX)
        _max("rewrites", self.rewrites, REWRITES_MAX)
        _max("language", self.language, LANGUAGE_MAX)

    def score_of(self, aspect: Aspect) -> int | None:
        """Nota do aspecto ou ``None`` (o painel mostra ``—``)."""
        return next((s.score for s in self.scores if s.aspect is aspect), None)
