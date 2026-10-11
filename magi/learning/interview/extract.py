"""Extração do ``JobProfile`` a partir da vaga (dona: **LI1.1**; spec §2–§3, R2.2, R2.5, R7.1).

Stub da LI0.1: assinaturas finais, corpo por fazer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from magi.learning.interview.contracts import EXTRACT_TIMEOUT_S, JobPost, JobProfile
from magi.learning.model import LearningModel

PROMPT = Path(__file__).parent.parent / "prompts" / "interview" / "extract.md"
#: Nome da tarefa própria (D8); ausente no config → ``learning_actions``.
TASK_JOB = "learning_job"


async def extract(
    post: JobPost, model: LearningModel, *, timeout_s: float = EXTRACT_TIMEOUT_S
) -> JobProfile:
    """Uma chamada ao modelo (schema da spec §2) + pós-checagem de ``evidence``/stack/senioridade.
    Erros viram ``ModelError`` (``timeout|budget|model|invalid``)."""
    raise NotImplementedError("LI1.1")


def build_job_model(config: Any, **kwargs: Any) -> LearningModel:
    """Modelo da tarefa ``learning_job`` ou, sem ela, de ``learning_actions`` (D8)."""
    raise NotImplementedError("LI1.1")
