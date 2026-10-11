"""Gravação de vagas, simulações e retornos (dona: **LI0.2**; spec §8, R5).

Fachada fina sobre o ``LearningRepo`` (Postgres ou JSONL). Stub da LI0.1: assinaturas finais.
"""

from __future__ import annotations

from typing import Any

from magi.learning.interview.contracts import (
    InterviewDebrief,
    InterviewRun,
    JobPost,
    JobProfile,
)


class InterviewStore:
    def __init__(self, repo: Any) -> None:
        self.repo = repo

    async def save_post(self, post: JobPost) -> None:
        raise NotImplementedError("LI0.2")

    async def set_profile(self, job_id: str, profile: JobProfile, model: str | None = None,
                          cost_usd: float | None = None) -> None:
        raise NotImplementedError("LI0.2")

    async def profile_of(self, job_id: str) -> JobProfile | None:
        """Perfil já extraído da vaga (reuso por hash, R2.6)."""
        raise NotImplementedError("LI0.2")

    async def post_of(self, job_id: str) -> JobPost | None:
        raise NotImplementedError("LI0.2")

    async def recent(self, n: int = 3) -> list[tuple[str, JobProfile]]:
        """Vagas mais recentes com perfil, para ``lm_session.jobs``."""
        raise NotImplementedError("LI0.2")

    async def save_run(self, run: InterviewRun, end_reason: str | None = None) -> None:
        raise NotImplementedError("LI0.2")

    async def load_active(self, session_id: str) -> InterviewRun | None:
        """Run não encerrada da sessão (retomada, R5.3)."""
        raise NotImplementedError("LI0.2")

    async def save_debrief(self, debrief: InterviewDebrief) -> None:
        raise NotImplementedError("LI0.2")

    async def unseen(self) -> InterviewDebrief | None:
        """Retorno gravado e ainda não mostrado (R5.2)."""
        raise NotImplementedError("LI0.2")

    async def mark_seen(self, run_id: str) -> None:
        raise NotImplementedError("LI0.2")
