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

Sem I/O fora do repositório. O relógio é injetável (testes).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from magi.learning.config import LearningConfig
from magi.learning.contracts import END_REASONS, Author, LearningMessage, Source, Topic
from magi.learning.repo import RECENT_DEFAULT, LearningRepo, SessionInfo

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LearningSession:
    """Sessão atual do Learning Mode (spec §10). ``active`` = modo ligado no núcleo."""

    def __init__(self, repo: LearningRepo, cfg: LearningConfig, *, clock: Clock = _utcnow) -> None:
        self.repo = repo
        self.cfg = cfg
        self.clock = clock
        self.speak_replies = cfg.speak_replies
        self._info: SessionInfo | None = None
        self._last_activity: datetime | None = None
        self._n_msgs = 0

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
        log.info("learning: sessão %s aberta", info.id)
        return info, False

    async def end(self, reason: str) -> SessionInfo | None:
        """Fecha a sessão aberta (``reason`` em ``END_REASONS``). Sem sessão: ``None``."""
        if reason not in END_REASONS:
            raise ValueError(f"end_reason inválido: {reason!r}")
        info, self._info = self._info, None
        self._last_activity = None
        self._n_msgs = 0
        if info is None:
            return None
        await self.repo.end_session(info.id, reason, at=self.clock())
        log.info("learning: sessão %s fechada (%s)", info.id, reason)
        return info

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
        self._n_msgs += 1
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
