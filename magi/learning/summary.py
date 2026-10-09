"""Resumo ao sair (tarefa LM4.5; spec §10.2, LM-011). Puro, sem I/O e sem LLM.

``summarize(session, messages_stats, observations, saved, ...)`` monta o ``SessionSummary`` do
cartão LAST SESSION a partir do que o repositório devolve em ``session_stats``:

- ``duration_s`` = última mensagem − ``started_at`` (a cauda ociosa não conta); sem mensagem,
  ``ended_at − started_at``.
- ``obs_count`` = observações distintas por (``category``, ``label``), igual ao ``lm_obs``
  (spec §9 item 5).
- ``practiced`` = labels distintos de ``recurring`` (primeiro) e depois ``grammar``, na ordem de
  primeira ocorrência, até ``PRACTICED_MAX``; o resto vai a ``more_practiced``.
- ``new_words`` = labels distintos de ``vocabulary`` + palavras salvas na sessão que não estejam
  lá, até ``WORDS_MAX``; o resto vai a ``more_words``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import NamedTuple

from magi.learning.contracts import ObsCategory, Observation, SavedWord, SessionSummary
from magi.learning.repo import SessionInfo, SessionStats

PRACTICED_MAX = 5
WORDS_MAX = 8


class MessageStats(NamedTuple):
    """Contagem de ``learning_messages`` da sessão (total, do Pedro) e a última mensagem."""

    n_msgs: int
    n_you: int
    last_msg_at: datetime | None


def _key(text: str) -> str:
    return " ".join(text.casefold().split())


def _distinct(labels: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for label in labels:
        k = _key(label)
        if k and k not in seen:
            seen.add(k)
            out.append(label)
    return out


def session_number(session_id: str) -> int:
    """``NN`` de ``LS-AAAAMMDD-NN`` (0 se o ID não segue o formato)."""
    tail = session_id.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def obs_count(observations: Iterable[Observation]) -> int:
    """Itens distintos por (``category``, ``label``) — o mesmo ``count`` do ``lm_obs``."""
    return len({(o.category, _key(o.label)) for o in observations})


def summarize(
    session: SessionInfo,
    messages_stats: MessageStats,
    observations: Sequence[Observation],
    saved: Sequence[SavedWord],
    *,
    ended_at: datetime,
    end_reason: str,
) -> SessionSummary:
    """Resumo da sessão inteira (spec §10.2 item 3)."""
    last = messages_stats.last_msg_at
    end = last if last is not None else ended_at
    duration_s = max(0, int((end - session.started_at).total_seconds()))

    by_cat = {c: [o.label for o in observations if o.category is c] for c in ObsCategory}
    practiced_all = _distinct(by_cat[ObsCategory.RECURRING] + by_cat[ObsCategory.GRAMMAR])
    saved_terms = _distinct(w.term for w in saved)
    words_all = _distinct(by_cat[ObsCategory.VOCABULARY] + saved_terms)

    topics = [str(t) for t, _ in session.topics] or [str(session.topic)]
    return SessionSummary(
        session_id=session.id,
        n=session_number(session.id),
        started_at=session.started_at,
        ended_at=ended_at,
        duration_s=duration_s,
        end_reason=end_reason,
        n_msgs=messages_stats.n_msgs,
        n_you=messages_stats.n_you,
        obs_count=obs_count(observations),
        practiced=practiced_all[:PRACTICED_MAX],
        new_words=words_all[:WORDS_MAX],
        saved=saved_terms,
        more_practiced=max(0, len(practiced_all) - PRACTICED_MAX),
        more_words=max(0, len(words_all) - WORDS_MAX),
        topics=topics,
    )


def from_stats(stats: SessionStats, *, ended_at: datetime, end_reason: str) -> SessionSummary:
    """Atalho: ``summarize`` direto do ``SessionStats`` do repositório."""
    return summarize(
        stats.session,
        MessageStats(stats.n_msgs, stats.n_you, stats.last_msg_at),
        stats.observations,
        stats.saved,
        ended_at=ended_at,
        end_reason=end_reason,
    )
