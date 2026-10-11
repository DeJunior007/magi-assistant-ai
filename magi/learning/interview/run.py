"""Máquina da simulação (dona: **LI1.3**; spec §5, R3). Relógio sempre injetado (``now`` em s).

Todas as funções mexem na ``InterviewRun`` recebida (mutável) e devolvem ``True`` quando algo
visível mudou (manda ``lm_interview``).

Pausa sem campo extra (a run precisa sobreviver a JSON/banco): ao pausar em ``t1`` subtrai-se
``t1`` de ``stage_started`` e de ``paused_s``; ao retomar em ``t2`` soma-se ``t2``. O efeito
líquido empurra o começo da etapa e acumula a pausa em ``paused_s`` (``t2 − t1``); durante a pausa
os relógios ficam congelados (``_stage_elapsed``/``_run_elapsed`` sabem ler os dois estados).
"""

from __future__ import annotations

import math
import re
import unicodedata
from functools import cache
from pathlib import Path
from typing import Any, Literal

from magi.learning.interview.contracts import (
    ASKED_LOG_MAX,
    ASKED_MAX,
    BLOCK_MAX,
    InterviewPlan,
    InterviewRun,
    JobProfile,
    RunState,
    StageKind,
)
from magi.learning.interview.debrief import MIN_ANSWERS
from magi.learning.topic import clip

Command = Literal["next", "repeat", "skip_stage", "pause", "end"]
#: Motivos de ``finish`` (``learning_interviews.end_reason``).
END_REASONS = ("done", "voice", "button", "text", "idle", "shutdown", "replaced")

PROMPT = Path(__file__).parent.parent / "prompts" / "interview" / "conduct.md"
TRANSITION = "Move on to this stage now with one transition sentence."

#: Frases da spec §5.3 (normalizadas: minúsculas, sem acento nem pontuação).
PHRASES: dict[Command, tuple[str, ...]] = {
    "next": ("next question", "skip this one", "proxima pergunta", "pula essa"),
    "repeat": ("can you repeat the question", "repete a pergunta"),
    "skip_stage": ("next stage", "lets move on", "proxima etapa"),
    "pause": ("pause the interview", "pausa a entrevista"),
    "end": ("end the interview", "lets stop here", "encerra a entrevista"),
}

#: O que a etapa pede, em uma frase (spec §4).
_HINTS: dict[StageKind, str] = {
    StageKind.INTRO: "Ask him to tell you about himself and why this role/domain.",
    StageKind.EXPERIENCE: "Link the role's responsibilities to projects he has built.",
    StageKind.TECHNICAL: "Probe this skill with concrete, practical questions.",
    StageKind.SYSTEM_DESIGN: "One design problem from the role's domain; dig into trade-offs.",
    StageKind.BEHAVIOURAL: "Behavioural question; let him answer in STAR format.",
    StageKind.CANDIDATE_QS: "Ask if he has questions for you; answer only from the profile.",
    StageKind.WRAP: "Thank him, explain generic next steps and close. No feedback.",
}

_LIVE = (RunState.READY, RunState.RUNNING, RunState.PAUSED)
_QUOTED = re.compile(r'"[^"]*"|“[^”]*”')
_SENTENCE = re.compile(r"[^.!?\n]*\?")


@cache
def _conduct() -> str:
    return PROMPT.read_text(encoding="utf-8").strip()


def start(
    plan: InterviewPlan, profile: JobProfile, session_id: str, now: float, *, run_id: str
) -> InterviewRun:
    """Run nova em ``READY`` na etapa 0."""
    return InterviewRun(
        id=run_id, session_id=session_id, job_id=plan.job_id, profile=profile, plan=plan,
        state=RunState.READY, stage=0, asked=0, answers=0, stage_started=now, started=now,
        paused_s=0.0, first_message_id=None, last_message_id=None, asked_log=[],
    )


# --- relógio ---------------------------------------------------------------------------------


def _stage_elapsed(run: InterviewRun, now: float) -> float:
    if run.state is RunState.PAUSED:
        return -run.stage_started
    return now - run.stage_started


def _run_elapsed(run: InterviewRun, now: float) -> float:
    if run.state is RunState.PAUSED:
        return -run.paused_s - run.started
    return now - run.started - run.paused_s


def _pause(run: InterviewRun, now: float) -> None:
    run.stage_started -= now
    run.paused_s -= now
    run.state = RunState.PAUSED


def _resume(run: InterviewRun, now: float) -> None:
    run.stage_started += now
    run.paused_s += now
    run.state = RunState.RUNNING


# --- avanço ----------------------------------------------------------------------------------


def _last(run: InterviewRun) -> bool:
    return run.stage >= len(run.plan.stages) - 1


def _advance(run: InterviewRun, now: float) -> bool:
    if _last(run):
        return False
    run.stage += 1
    run.asked = 0
    run.stage_started = now
    return True


def _check(run: InterviewRun, now: float) -> bool:
    """Fecha a etapa por cota ou tempo (spec §5.1); WRAP só fecha por tempo, via ``finish``."""
    st = run.current
    if st.kind is StageKind.WRAP:
        if _stage_elapsed(run, now) >= st.minutes * 60:
            finish(run, "done", now)
            return True
        return False
    if run.asked >= st.quota or _stage_elapsed(run, now) >= st.minutes * 60:
        return _advance(run, now)
    return False


def _question(text: str) -> str | None:
    """Última frase com ``?`` fora de citação, ou ``None``."""
    found = _SENTENCE.findall(_QUOTED.sub(" ", text))
    if not found:
        return None
    q = " ".join(found[-1].split())
    return q if len(q) <= ASKED_MAX else q[: ASKED_MAX - 1].rstrip() + "…"


def observe(run: InterviewRun, condessa_text: str, pedro_answered: bool, now: float) -> bool:
    """Conta pergunta (``?`` fora de citação) e resposta; avança por cota ou tempo (spec §5.1)."""
    if run.state not in _LIVE:
        return False
    changed = False
    if run.state is RunState.PAUSED:
        if not pedro_answered:
            return False
        _resume(run, now)
        changed = True
    elif run.state is RunState.READY:
        run.state = RunState.RUNNING
        changed = True
    if pedro_answered:
        run.answers += 1
    if run.current.kind is StageKind.WRAP and condessa_text.strip():
        finish(run, "done", now)
        return True
    q = _question(condessa_text)
    if q is not None:
        run.asked += 1
        run.asked_log.append(q)
        del run.asked_log[:-ASKED_LOG_MAX]
        changed = True
    return _check(run, now) or changed


def tick(run: InterviewRun, now: float) -> bool:
    """Avança a etapa por tempo sem turno novo."""
    if run.state is not RunState.RUNNING:
        return False
    return _check(run, now)


# --- comandos --------------------------------------------------------------------------------


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c)).replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def command_of(text: str) -> Command | None:
    """Frase inteira ou prefixo das frases da spec §5.3 (EN/PT); "how am I doing?" não é comando."""
    t = _norm(text)
    for cmd, phrases in PHRASES.items():
        if any(t == p or t.startswith(p + " ") for p in phrases):
            return cmd
    return None


def apply(run: InterviewRun, cmd: Command, now: float) -> bool:
    """Efeito do comando (spec §5.3); ``end`` não chama ``finish`` — quem chama decide o motivo."""
    if run.state not in _LIVE or cmd in ("repeat", "end"):
        return False
    if cmd == "pause":
        if run.state is RunState.PAUSED:
            return False
        _pause(run, now)
        return True
    if run.current.kind is StageKind.WRAP:
        return False
    if run.state is RunState.PAUSED:
        _resume(run, now)
    elif run.state is RunState.READY:
        run.state = RunState.RUNNING
    if cmd == "skip_stage":
        _advance(run, now)
        return True
    per = 1 + run.current.followups
    run.asked = (run.asked // per + 1) * per
    _check(run, now)
    return True


def finish(run: InterviewRun, reason: str, now: float) -> None:
    """Congela a run (``DEBRIEFING`` ou ``DONE``) com o motivo de ``END_REASONS``.

    ``DEBRIEFING`` quando há respostas para o retorno (``debrief.MIN_ANSWERS``), senão ``DONE``.
    """
    if reason not in END_REASONS:
        raise ValueError(f"motivo de fim inválido: {reason!r}")
    if run.state not in _LIVE:
        return
    if run.state is RunState.PAUSED:
        _resume(run, now)
    run.state = RunState.DEBRIEFING if run.answers >= MIN_ANSWERS else RunState.DONE


# --- bloco do prompt -------------------------------------------------------------------------


def _stage_line(run: InterviewRun, now: float) -> str:
    st = run.current
    head = f"Stage {run.stage + 1}/{len(run.plan.stages)} — {st.label}"
    if st.questions:
        n = min(run.asked // (1 + st.followups) + 1, st.questions)
        head += f" (question {n} of {st.questions}, up to {st.followups} follow-ups)"
    left = math.ceil(max(0.0, st.minutes * 60 - _stage_elapsed(run, now)) / 60)
    line = f"{head}. Time left in stage: {left} min. {_HINTS[st.kind]}"
    if st.focus:
        line += " Focus: " + "; ".join(st.focus) + "."
    return line


def _role_line(p: JobProfile) -> str:
    extra = ", ".join(x for x in (p.seniority.value, p.remote) if x)
    line = f"Role: {p.title} at {p.company or 'the company'} ({extra})."
    return line + (f" Domain: {p.domain}." if p.domain else "")


def _fit(head: str, items: list[str], sep: str, room: int) -> str | None:
    """``head`` + quantos itens couberem em ``room`` (``None`` se nem um cabe)."""
    out = ""
    for it in items:
        cand = f"{out}{sep}{it}" if out else f"{head}{it}"
        if len(cand) > room:
            break
        out = cand
    return out or None


def block(run: InterviewRun, now: float) -> str:
    """Bloco ``<topic_context>`` do turno (spec §5.2), ≤ ``BLOCK_MAX`` com corte por prioridade.

    Prioridade: conduct > etapa > role > must-haves > stack > already asked.
    """
    p = run.profile
    conduct = clip(_conduct(), BLOCK_MAX) or ""
    stage = _stage_line(run, now)
    if run.stage > 0 and run.asked == 0:
        stage += "\n" + TRANSITION  # acabou de mudar de etapa
    stage = clip(stage, max(1, BLOCK_MAX - len(conduct) - 1)) or ""
    parts: dict[str, str] = {}
    room = BLOCK_MAX - len(conduct) - len(stage) - 1

    def take(key: str, text: str | None) -> None:
        nonlocal room
        if text and len(text) + 1 <= room:
            parts[key] = text
            room -= len(text) + 1

    take("role", clip(_role_line(p), room - 1) if room > 1 else None)  # corta, não some
    take("must", _fit("Must-haves: ", [r.text for r in p.must], "; ", room - 1))
    take("stack", _fit("Stack: ", list(p.stack), ", ", room - 1))
    take("asked", _fit("Already asked (do not repeat): ", list(reversed(run.asked_log)),
                       " | ", room - 1))
    stage_line, _, transition = stage.partition("\n")
    lines = [conduct, parts.get("role"), parts.get("stack"), parts.get("must"), stage_line,
             parts.get("asked"), transition]
    return "\n".join(x for x in lines if x)


def progress(run: InterviewRun, now: float) -> dict[str, Any]:
    """Campos do ``lm_interview`` núcleo → UI (spec §7) para ``LmInterviewMsg``.

    ``stage`` é o índice (0-based) em ``plan.stages``; ``None`` fica de fora.
    """
    p, st = run.profile, run.current
    out: dict[str, Any] = {
        "state": run.state, "job_id": run.job_id, "run_id": run.id, "title": p.title,
        "company": p.company, "seniority": p.seniority.value, "stack": p.stack,
        "must": tuple(r.text for r in p.must), "stage": run.stage,
        "n_stages": len(run.plan.stages), "stage_label": st.label, "asked": run.asked,
        "quota": st.quota, "elapsed_s": round(max(0.0, _run_elapsed(run, now)), 1),
        "minutes": run.plan.minutes,
    }
    return {k: v for k, v in out.items() if v is not None}
