"""Sessão do Learning Mode no núcleo (tarefa LM1.3; design §5, §10; spec §4, §10; LM-001..LM-004).

``LearningSession`` guarda a sessão aberta (``LS-AAAAMMDD-NN``, spec §1) por cima do
``LearningRepo`` (LM1.1) e é a única fonte da verdade do "modo ligado" no núcleo:

- ``start()``: sem sessão aberta cria uma ``LS-`` nova; com uma sessão aberta no banco cuja última
  atividade (última mensagem ou o início) foi há menos de ``idle_end_min``, **retoma**; uma sessão
  aberta mais velha que isso é fechada com ``end_reason = "idle"`` e uma nova é criada (spec §10).
- ``end(reason)``: fecha com ``button`` | ``voice`` | ``idle`` | ``shutdown`` (``END_REASONS``).
- ``add_message``: grava a mensagem do histórico e marca atividade.
- ``idle_expired()``/``end_if_idle()``: fim por inatividade (P9, 20 min padrão).
- ``speak_replies``: preferência da sessão (``lm_cfg``, LM-004); começa no ``[learning]``.
- ``set_topic(ctx)`` (LM1.8, spec §10.1): tema atual (``TopicContext``) e histórico em
  ``learning_sessions.topic``/``topics`` (``repo.set_topic``); ``topic_block`` vai ao prompt.
- Resumo ao sair (LM4.5, spec §10.2): ``end()`` fecha e devolve na hora (quem chamou confirma
  ``lm_mode off`` logo em seguida); o resumo roda depois, em tarefa própria: lê
  ``repo.session_stats`` com prazo de ``SUMMARY_TIMEOUT_S`` (sem resposta = contagem guardada
  aqui), publica ``lm_summary`` por ``send`` (só ``n_you > 0`` e ``end_reason ≠ shutdown``) e grava
  ``repo.save_summary``. Em ``shutdown`` o ``end()`` espera o resumo (não há confirmação a mandar).

Sem I/O fora do repositório. O relógio é injetável (testes).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from magi.common.contracts import LmSummaryMsg
from magi.learning.config import LearningConfig
from magi.learning.contracts import (
    END_REASONS,
    Author,
    LearningMessage,
    SessionSummary,
    Source,
    Topic,
    TopicContext,
)
from magi.learning.repo import RECENT_DEFAULT, LearningRepo, SessionInfo, SessionStats
from magi.learning.summary import MessageStats, from_stats, summarize

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]
Send = Callable[[Any], Awaitable[None]]

#: Prazo da leitura do resumo ao sair (spec §10.2 item 2).
SUMMARY_TIMEOUT_S = 2.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LearningSession:
    """Sessão atual do Learning Mode (spec §10). ``active`` = modo ligado no núcleo."""

    def __init__(
        self, repo: LearningRepo, cfg: LearningConfig, *, clock: Clock = _utcnow,
        send: Send | None = None,
    ) -> None:
        self.repo = repo
        self.cfg = cfg
        self.clock = clock
        #: LM4.5: publicação do ``lm_summary`` (o ``send`` do HUD); ``None`` = só grava.
        self.send = send
        self.summary_timeout_s = SUMMARY_TIMEOUT_S
        self.last_summary: SessionSummary | None = None
        self._summaries: set[asyncio.Task[SessionSummary | None]] = set()
        self._n_you = 0
        self._last_msg_at: datetime | None = None
        self.speak_replies = cfg.speak_replies
        self._info: SessionInfo | None = None
        self._last_activity: datetime | None = None
        self._n_msgs = 0
        self._topic: TopicContext | None = None

    # -- consulta -------------------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._info is not None

    @property
    def info(self) -> SessionInfo | None:
        return self._info

    @property
    def id(self) -> str | None:
        return self._info.id if self._info is not None else None

    @property
    def topic(self) -> Topic:
        return self._info.topic if self._info is not None else self.cfg.default_topic

    @property
    def topic_context(self) -> TopicContext | None:
        """Tema escolhido nesta sessão (snapshot de ``topic.build``); ``None`` = nada escolhido."""
        return self._topic if self._info is not None else None

    @property
    def topic_block(self) -> str | None:
        """Bloco ``<topic_context>`` do prompt (``None`` em free ou sem sessão)."""
        ctx = self.topic_context
        return ctx.block if ctx is not None else None

    async def set_topic(self, ctx: TopicContext, *, record: bool = True) -> bool:
        """Guarda o tema na sessão aberta e grava o efetivo no histórico (``record``). Devolve
        ``True`` se o tema efetivo mudou; sem sessão não faz nada (``False``)."""
        if self._info is None:
            return False
        changed = ctx.topic != self._info.topic
        self._topic = ctx
        if record and changed:
            at = self.clock()
            await self.repo.set_topic(self._info.id, ctx.topic, at)
            self._info = replace(self._info, topic=ctx.topic,
                                 topics=[*self._info.topics, (ctx.topic, at)])
        return changed

    @property
    def n_msgs(self) -> int:
        return self._n_msgs

    @property
    def last_activity(self) -> datetime | None:
        return self._last_activity

    @property
    def idle_limit(self) -> timedelta:
        return timedelta(minutes=self.cfg.idle_end_min)

    def idle_expired(self, now: datetime | None = None) -> bool:
        """``True`` se a sessão aberta está sem mensagem há ``idle_end_min`` ou mais."""
        if self._info is None or self._last_activity is None:
            return False
        return (now or self.clock()) - self._last_activity >= self.idle_limit

    # -- ciclo de vida --------------------------------------------------------------------------

    async def start(self) -> tuple[SessionInfo, bool]:
        """Abre ou retoma a sessão. Devolve ``(sessão, retomada)``; já ativa = ``(atual, True)``."""
        if self._info is not None:
            return self._info, True
        now = self.clock()
        last = await self.repo.open_session_last()
        if last is not None:
            stats = await self.repo.session_stats(last.id)
            activity = (stats.last_msg_at if stats is not None else None) or last.started_at
            if now - activity < self.idle_limit:
                self._info = last
                self._last_activity = activity
                self._n_msgs = stats.n_msgs if stats is not None else 0
                self._n_you = stats.n_you if stats is not None else 0
                self._last_msg_at = stats.last_msg_at if stats is not None else None
                log.info("learning: sessão %s retomada", last.id)
                return last, True
            log.info("learning: sessão %s ficou aberta ociosa; fechando", last.id)
            await self.repo.end_session(last.id, "idle", at=now)
        info = await self.repo.open_session(
            level=self.cfg.level, track=self.cfg.track, topic=self.cfg.default_topic, at=now
        )
        self._info = info
        self._last_activity = now
        self._n_msgs = 0
        self._n_you = 0
        self._last_msg_at = None
        log.info("learning: sessão %s aberta", info.id)
        return info, False

    async def end(self, reason: str) -> SessionInfo | None:
        """Fecha a sessão aberta (``reason`` em ``END_REASONS``). Sem sessão: ``None``."""
        if reason not in END_REASONS:
            raise ValueError(f"end_reason inválido: {reason!r}")
        info, self._info = self._info, None
        local = MessageStats(self._n_msgs, self._n_you, self._last_msg_at)
        self._topic = None
        self._last_activity = None
        self._n_msgs = 0
        self._n_you = 0
        self._last_msg_at = None
        if info is None:
            return None
        ended = self.clock()
        await self.repo.end_session(info.id, reason, at=ended)
        log.info("learning: sessão %s fechada (%s)", info.id, reason)
        # Depois do último ``await``: quem chamou confirma ``lm_mode off`` antes do resumo rodar.
        task = asyncio.create_task(
            self._summary(info, reason, ended, local), name=f"learning-summary-{info.id}"
        )
        self._summaries.add(task)
        task.add_done_callback(self._summaries.discard)
        if reason == "shutdown":
            with contextlib.suppress(Exception):
                await task
        return info

    async def wait_summaries(self) -> None:
        """Espera os resumos em andamento (testes e desligamento)."""
        if self._summaries:
            await asyncio.gather(*list(self._summaries), return_exceptions=True)

    async def _stats(self, session_id: str) -> SessionStats | None:
        try:
            return await asyncio.wait_for(self.repo.session_stats(session_id), self.summary_timeout_s)
        except Exception as exc:  # inclui o prazo estourado
            log.warning("learning: resumo de %s sem o banco (%s); usando a contagem local",
                        session_id, type(exc).__name__ or exc)
            return None

    async def _summary(
        self, info: SessionInfo, reason: str, ended: datetime, local: MessageStats
    ) -> SessionSummary | None:
        """Resumo ao sair (spec §10.2): lê, publica (``n_you > 0`` e não ``shutdown``) e grava."""
        try:
            await asyncio.sleep(0)  # deixa a confirmação ``lm_mode off`` sair primeiro
            stats = await self._stats(info.id)
            if stats is not None:
                summary = from_stats(stats, ended_at=ended, end_reason=reason)
            else:
                summary = summarize(info, local, [], [], ended_at=ended, end_reason=reason)
            self.last_summary = summary
            if self.send is not None and summary.n_you > 0 and reason != "shutdown":
                try:
                    await self.send(LmSummaryMsg(summary))
                except Exception:
                    log.warning("learning: lm_summary de %s não enviado", info.id, exc_info=True)
            try:
                await self.repo.save_summary(info.id, summary)
            except Exception:
                log.warning("learning: resumo de %s não gravado", info.id, exc_info=True)
            return summary
        except Exception:
            log.exception("learning: falha no resumo da sessão %s", info.id)
            return None

    async def end_if_idle(self) -> SessionInfo | None:
        """Fecha com ``idle`` se a sessão passou de ``idle_end_min`` sem mensagem."""
        if not self.idle_expired():
            return None
        return await self.end("idle")

    # -- mensagens ------------------------------------------------------------------------------

    async def add_message(
        self, author: Author, source: Source, text: str, *,
        text_final: str | None = None, turn_id: int | None = None,
    ) -> LearningMessage | None:
        """Grava uma mensagem na sessão aberta (``None`` sem sessão) e marca atividade."""
        if self._info is None:
            return None
        now = self.clock()
        msg = await self.repo.add_message(
            self._info.id, author, source, text, text_final=text_final, turn_id=turn_id, at=now
        )
        self._last_activity = now
        self._last_msg_at = now
        self._n_msgs += 1
        if Author(author) is Author.YOU:
            self._n_you += 1
        return msg

    def touch(self) -> None:
        """Marca atividade sem mensagem (ex.: o Pedro mexeu na tela)."""
        if self._info is not None:
            self._last_activity = self.clock()

    async def recent(self, limit: int = RECENT_DEFAULT) -> list[LearningMessage]:
        """Últimas ``limit`` mensagens da sessão aberta (reconexão, spec §10)."""
        if self._info is None:
            return []
        return await self.repo.recent_messages(self._info.id, limit)
