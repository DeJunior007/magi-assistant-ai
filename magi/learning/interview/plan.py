"""Roteiro da simulação (dona: **LI1.2**; spec §4, R2.3). Puro e determinístico, sem LLM.

Stub da LI0.1: assinatura final, corpo por fazer.
"""

from __future__ import annotations

from magi.learning.interview.contracts import InterviewPlan, JobProfile

DEFAULT_MINUTES = 30  # D6


def build_plan(profile: JobProfile, minutes: int = DEFAULT_MINUTES, *, job_id: str) -> InterviewPlan:
    """Etapas e cotas da tabela da spec §4; soma dos minutos = ``minutes`` (ajuste em EXPERIENCE)."""
    raise NotImplementedError("LI1.2")
