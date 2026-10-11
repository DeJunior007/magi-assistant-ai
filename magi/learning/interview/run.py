"""Máquina da simulação (dona: **LI1.3**; spec §5, R3). Relógio sempre injetado (``now`` em s).

Stub da LI0.1: assinaturas finais, corpo por fazer. Todas as funções mexem na ``InterviewRun``
recebida (mutável) e devolvem ``True`` quando algo visível mudou (manda ``lm_interview``).
"""

from __future__ import annotations

from typing import Any, Literal

from magi.learning.interview.contracts import InterviewPlan, InterviewRun, JobProfile

Command = Literal["next", "repeat", "skip_stage", "pause", "end"]
#: Motivos de ``finish`` (``learning_interviews.end_reason``).
END_REASONS = ("done", "voice", "button", "text", "idle", "shutdown", "replaced")


def start(
    plan: InterviewPlan, profile: JobProfile, session_id: str, now: float, *, run_id: str
) -> InterviewRun:
    """Run nova em ``READY`` na etapa 0."""
    raise NotImplementedError("LI1.3")


def observe(run: InterviewRun, condessa_text: str, pedro_answered: bool, now: float) -> bool:
    """Conta pergunta (``?`` fora de citação) e resposta; avança por cota ou tempo (spec §5.1)."""
    raise NotImplementedError("LI1.3")


def tick(run: InterviewRun, now: float) -> bool:
    """Avança a etapa por tempo sem turno novo."""
    raise NotImplementedError("LI1.3")


def command_of(text: str) -> Command | None:
    """Frase inteira ou prefixo das frases da spec §5.3 (EN/PT); "how am I doing?" não é comando."""
    raise NotImplementedError("LI1.3")


def apply(run: InterviewRun, cmd: Command, now: float) -> bool:
    """Efeito do comando (spec §5.3); ``end`` não chama ``finish`` — quem chama decide o motivo."""
    raise NotImplementedError("LI1.3")


def finish(run: InterviewRun, reason: str, now: float) -> None:
    """Congela a run (``DEBRIEFING`` ou ``DONE``) com o motivo de ``END_REASONS``."""
    raise NotImplementedError("LI1.3")


def block(run: InterviewRun, now: float) -> str:
    """Bloco ``<topic_context>`` do turno (spec §5.2), ≤ ``BLOCK_MAX`` com corte por prioridade."""
    raise NotImplementedError("LI1.3")


def progress(run: InterviewRun, now: float) -> dict[str, Any]:
    """Campos do ``lm_interview`` núcleo → UI (spec §7) para ``LmInterviewMsg``."""
    raise NotImplementedError("LI1.3")
