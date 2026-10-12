"""Retorno da simulação (dona: **LI2.3**; spec §6, R4) com notas 0–100 por aspecto (D3).

``debrief(run, messages, observations, model)`` faz **uma** chamada ao modelo (prompt
``prompts/interview/debrief.md``, prazo de 40 s) sobre perfil + etapas + transcrição da run e confere
a resposta antes de virar ``InterviewDebrief``:

- notas: aspecto fora do enum cai, duplicata fica a primeira, ``score`` vira inteiro preso em
  0..100, aspecto ausente fica ausente (o painel mostra ``—``), ``note`` cortada em 200; sem nota
  geral;
- cobertura: ``evidence`` precisa estar nas falas do Pedro (normalizado), senão vira ``None`` e
  ``COVERED`` cai para ``THIN``; requisito ``must`` que não veio entra como ``MISSED``;
- ``language`` = labels das observações da run (``recurring`` primeiro, ≤ 6), sem chamada nova.

O idioma do texto segue ``[learning] explain_language`` (D7): inglês simples por padrão.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from magi.learning.contracts import Author, LearningMessage, ObsCategory, Observation
from magi.learning.interview.contracts import (
    COVER_EVIDENCE_MAX,
    DEBRIEF_TIMEOUT_S,
    LANGUAGE_MAX,
    POINTS_MAX,
    REWRITES_MAX,
    SCORE_NOTE_MAX,
    Aspect,
    AspectScore,
    Cover,
    Coverage,
    InterviewDebrief,
    InterviewRun,
)
from magi.learning.model import (
    LearningModel,
    ModelError,
    ModelFailure,
    ModelInvalid,
    ModelTimeout,
)

PROMPT = Path(__file__).parent.parent / "prompts" / "interview" / "debrief.md"
#: Menos respostas do Pedro que isso → sem retorno (R4.4).
MIN_ANSWERS = 3
#: Transcrição cortada do começo acima disso (spec §6).
TRANSCRIPT_MAX = 24_000
#: Teto de cada ponto forte/a melhorar e de cada lado da resposta reescrita.
POINT_MAX = 300
CLOSING_MAX = 300
#: Idioma das explicações (D7) → instrução que vai no fim do prompt.
LANGUAGE_RULES = {
    "en": "Write every text field in simple English (short sentences, common words).",
    "pt-br": ("Write strengths, improve, the score notes and closing in simple Brazilian "
              "Portuguese. Keep evidence and rewrites in English."),
}

_STR = {"type": "string"}
#: Schema da resposta (spec §6): ``InterviewDebrief`` sem ``run_id``/``language``.
SCHEMA: dict[str, Any] = {
    "title": "interview_debrief",
    "type": "object",
    "additionalProperties": False,
    "required": ["coverage", "scores", "strengths", "improve", "rewrites", "closing"],
    "properties": {
        "coverage": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["requirement", "cover", "evidence"],
                "properties": {
                    "requirement": _STR,
                    "cover": {"type": "string", "enum": [c.value for c in Cover]},
                    "evidence": {"type": ["string", "null"]},
                },
            },
        },
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["aspect", "score", "note"],
                "properties": {
                    "aspect": {"type": "string", "enum": [a.value for a in Aspect]},
                    "score": {"type": "integer"},
                    "note": _STR,
                },
            },
        },
        "strengths": {"type": "array", "items": _STR},
        "improve": {"type": "array", "items": _STR},
        "rewrites": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["original", "stronger"],
                "properties": {"original": _STR, "stronger": _STR},
            },
        },
        "closing": _STR,
    },
}

_SPACES = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def _flat(text: str) -> str:
    """Minúsculas, aspas retas e espaços simples (comparação de ``evidence``)."""
    return _SPACES.sub(" ", text.translate(_QUOTES)).strip().lower()


def _text(v: Any, n: int) -> str:
    return _SPACES.sub(" ", v).strip()[:n].strip() if isinstance(v, str) else ""


def _strings(v: Any, n: int, k: int) -> tuple[str, ...]:
    out = [s for s in (_text(x, k) for x in (v if isinstance(v, list) else [])) if s]
    return tuple(out[:n])


def in_run(run: InterviewRun, message_id: int) -> bool:
    """A mensagem está entre ``first_message_id`` e ``last_message_id`` da run."""
    first, last = run.first_message_id, run.last_message_id
    return first is not None and last is not None and first <= message_id <= last


def transcript(run: InterviewRun, messages: Sequence[LearningMessage]) -> str:
    """Autor + texto das mensagens da run; acima de ``TRANSCRIPT_MAX`` corta do começo."""
    lines = [f"{'Pedro' if m.author is Author.YOU else 'Interviewer'}: {m.text.strip()}"
             for m in sorted(messages, key=lambda m: m.id) if in_run(run, m.id)]
    text = "\n".join(lines)
    if len(text) > TRANSCRIPT_MAX:
        text = text[-TRANSCRIPT_MAX:]
        cut = text.find("\n")
        text = text[cut + 1:] if 0 <= cut < 2000 else text
    return text


def scores_of(v: Any) -> tuple[AspectScore, ...]:
    """Pós-checagem das notas (spec §6, D3)."""
    got: dict[Aspect, AspectScore] = {}
    for item in v if isinstance(v, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            aspect = Aspect(str(item.get("aspect", "")).strip().lower())
        except ValueError:
            continue  # aspecto desconhecido cai
        if aspect in got:
            continue  # duplicata: fica a primeira
        raw = item.get("score")
        try:
            if isinstance(raw, bool):
                raise ValueError
            score = round(float(raw))  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            continue
        got[aspect] = AspectScore(aspect, max(0, min(100, score)),
                                  _text(item.get("note"), SCORE_NOTE_MAX))
    return tuple(got[a] for a in Aspect if a in got)


def coverage_of(v: Any, run: InterviewRun, said: str) -> tuple[Coverage, ...]:
    """Pós-checagem da cobertura (spec §6): evidência só das falas do Pedro; ``must`` ausente →
    ``MISSED``."""
    out: list[Coverage] = []
    seen: set[str] = set()
    for item in v if isinstance(v, list) else []:
        if not isinstance(item, dict):
            continue
        req = _text(item.get("requirement"), 300)
        if not req or _flat(req) in seen:
            continue
        try:
            cover = Cover(str(item.get("cover", "")).strip().lower())
        except ValueError:
            cover = Cover.MISSED
        evidence: str | None = _text(item.get("evidence"), COVER_EVIDENCE_MAX) or None
        if cover is Cover.MISSED or (evidence is not None and _flat(evidence) not in said):
            evidence = None
        if evidence is None and cover is Cover.COVERED:
            cover = Cover.THIN
        seen.add(_flat(req))
        out.append(Coverage(req, cover, evidence))
    for r in run.profile.must:
        if _flat(r.text) not in seen:
            seen.add(_flat(r.text))
            out.append(Coverage(r.text, Cover.MISSED, None))
    return tuple(out)


def language_of(run: InterviewRun, observations: Sequence[Observation]) -> tuple[str, ...]:
    """Labels das observações da run, ``recurring`` primeiro, sem repetir, ≤ 6."""
    mine = [o for o in observations if in_run(run, o.message_id)]
    mine.sort(key=lambda o: o.category is not ObsCategory.RECURRING)  # estável
    out: list[str] = []
    for o in mine:
        label = o.label.strip()
        if label and _flat(label) not in {_flat(x) for x in out}:
            out.append(label)
    return tuple(out[:LANGUAGE_MAX])


def _rewrites(v: Any) -> tuple[tuple[str, str], ...]:
    out: list[tuple[str, str]] = []
    for item in v if isinstance(v, list) else []:
        if isinstance(item, dict):
            a, b = _text(item.get("original"), POINT_MAX), _text(item.get("stronger"), POINT_MAX)
            if a and b:
                out.append((a, b))
    return tuple(out[:REWRITES_MAX])


def debrief_of(
    data: dict[str, Any], run: InterviewRun, messages: Sequence[LearningMessage],
    observations: Sequence[Observation],
) -> InterviewDebrief:
    """``InterviewDebrief`` da resposta do modelo com a pós-checagem da spec §6."""
    said = _flat(" ".join(m.text for m in messages if m.author is Author.YOU and in_run(run, m.id)))
    try:
        return InterviewDebrief(
            run_id=run.id,
            coverage=coverage_of(data.get("coverage"), run, said),
            scores=scores_of(data.get("scores")),
            strengths=_strings(data.get("strengths"), POINTS_MAX, POINT_MAX),
            improve=_strings(data.get("improve"), POINTS_MAX, POINT_MAX),
            rewrites=_rewrites(data.get("rewrites")),
            language=language_of(run, observations),
            closing=_text(data.get("closing"), CLOSING_MAX),
        )
    except (ValueError, TypeError) as e:
        raise ModelInvalid(f"retorno fora do contrato: {e}") from e


def _user(run: InterviewRun, messages: Sequence[LearningMessage]) -> str:
    """Perfil, etapas e transcrição como dados (as tags não podem ser fechadas pelo texto)."""
    profile = json.dumps(run.profile.to_dict(), ensure_ascii=False, separators=(",", ":"))
    stages = "\n".join(f"{i + 1}. {s.label} ({s.kind.value})"
                       for i, s in enumerate(run.plan.stages))
    body = re.sub(r"</?\s*transcript\s*>", "", transcript(run, messages), flags=re.IGNORECASE)
    return (f"<profile>\n{profile}\n</profile>\n<stages>\n{stages}\n</stages>\n"
            f"<transcript>\n{body}\n</transcript>")


def system_prompt(explain_language: str = "en") -> str:
    rule = LANGUAGE_RULES.get(explain_language, LANGUAGE_RULES["en"])
    return f"{PROMPT.read_text(encoding='utf-8').rstrip()}\n\n{rule}\n"


async def debrief(
    run: InterviewRun,
    messages: Sequence[LearningMessage],
    observations: Sequence[Observation],
    model: LearningModel,
    *,
    timeout_s: float = DEBRIEF_TIMEOUT_S,
    explain_language: str = "en",
) -> InterviewDebrief:
    """Uma chamada ao modelo; pós-checagem da cobertura e das notas (spec §6). Erros viram
    ``ModelError`` (``timeout|budget|model|invalid``)."""
    try:
        data, _cost = await asyncio.wait_for(
            model.complete(system_prompt(explain_language), _user(run, messages), SCHEMA), timeout_s)
    except TimeoutError as e:
        raise ModelTimeout(f"retorno da entrevista sem resposta em {timeout_s:g} s") from e
    except ModelError:
        raise
    except Exception as e:  # noqa: BLE001 - qualquer falha do modelo vira ModelError (LM-007)
        raise ModelFailure(f"retorno da entrevista: {e}") from e
    if not isinstance(data, dict):
        raise ModelInvalid("resposta do retorno não é um objeto")
    return debrief_of(data, run, messages, observations)
