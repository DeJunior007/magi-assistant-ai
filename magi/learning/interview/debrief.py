"""Retorno da simulação (dona: **LI2.3**; spec §6, R4) com notas 0–100 por aspecto (D3).

Stub da LI0.1: assinatura final, corpo por fazer.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from magi.learning.contracts import LearningMessage, Observation
from magi.learning.interview.contracts import DEBRIEF_TIMEOUT_S, InterviewDebrief, InterviewRun
from magi.learning.model import LearningModel

PROMPT = Path(__file__).parent.parent / "prompts" / "interview" / "debrief.md"
#: Menos respostas do Pedro que isso → sem retorno (R4.4).
MIN_ANSWERS = 3
#: Transcrição cortada do começo acima disso (spec §6).
TRANSCRIPT_MAX = 24_000


async def debrief(
    run: InterviewRun,
    messages: Sequence[LearningMessage],
    observations: Sequence[Observation],
    model: LearningModel,
    *,
    timeout_s: float = DEBRIEF_TIMEOUT_S,
) -> InterviewDebrief:
    """Uma chamada ao modelo; pós-checagem da cobertura e das notas (spec §6)."""
    raise NotImplementedError("LI2.3")
