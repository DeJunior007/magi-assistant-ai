"""Gravação de vagas, simulações e retornos (dona: **LI0.2**; spec §8, R2.6, R5).

Fachada fina sobre o ``LearningRepo`` (Postgres ou JSONL): só traduz nomes e injeta o relógio.
Tabelas ``learning_jobs``/``learning_interviews`` (migração ``004_learning_jobs.sql``) ou
``jobs.jsonl`` + linhas ``interview``/``debrief``/``seen`` no arquivo da sessão.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from magi.learning.interview.contracts import (
    InterviewDebrief,
    InterviewRun,
    JobPost,
    JobProfile,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InterviewStore:
    def __init__(self, repo: Any, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self.repo = repo
        self._clock = clock

    async def save_post(self, post: JobPost) -> None:
        """Grava a vaga; se já existe (mesmo hash), só atualiza ``last_used``."""
        await self.repo.save_job(post, self._clock())

    async def set_profile(self, job_id: str, profile: JobProfile, model: str | None = None,
                          cost_usd: float | None = None) -> None:
        await self.repo.set_profile(job_id, profile, model=model, cost_usd=cost_usd)

    async def profile_of(self, job_id: str) -> JobProfile | None:
        """Perfil já extraído da vaga (reuso por hash, R2.6)."""
        job = await self.repo.get_job(job_id)
        return job.profile if job is not None else None

    async def post_of(self, job_id: str) -> JobPost | None:
        job = await self.repo.get_job(job_id)
        return job.post if job is not None else None

    async def recent(self, n: int = 3) -> list[tuple[str, JobProfile]]:
        """Vagas mais recentes com perfil, para ``lm_session.jobs``."""
        return await self.repo.recent_jobs(n)

    async def save_run(self, run: InterviewRun, end_reason: str | None = None) -> None:
        """Grava o estado da simulação; ``end_reason`` (ou estado ``done``/``error``) a encerra."""
        await self.repo.save_interview(run, end_reason, self._clock())

    async def load_active(self, session_id: str) -> InterviewRun | None:
        """Run não encerrada da sessão (retomada, R5.3)."""
        return await self.repo.active_interview(session_id)

    async def save_debrief(self, debrief: InterviewDebrief) -> None:
        await self.repo.save_debrief(debrief)

    async def unseen(self) -> InterviewDebrief | None:
        """Retorno gravado e ainda não mostrado (R5.2)."""
        return await self.repo.unseen_debrief()

    async def mark_seen(self, run_id: str) -> None:
        await self.repo.mark_seen(run_id)
