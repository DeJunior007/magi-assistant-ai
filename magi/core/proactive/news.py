"""Entrega de notícias pelo núcleo (tarefa 6.10; design §8 passo 5; R19.5, R19.6, R19.8).

A Ayanami (``magi-ayanami``) grava ``level`` nos itens (``magi.news.priority``); este laço leve, no núcleo, lê
de tempos em tempos as bombas e altas ainda não entregues (``NewsRepo.undelivered``), passa tudo
pelo anti-spoiler (``magi.news.spoiler.present``: só :class:`Shown` é exibido, nunca o item cru)
e entrega pelo :class:`ProactiveSink`:

- **bomba** → card ``bomba`` + frase curta com ``Priority.VOICE`` (falada fora de call; em call,
  ou sem satélite, o sink a põe na legenda — R19.5);
- **alta** → só card ``alta``, sem voz e sem legenda (``Priority.SCREEN``, R19.6).

"Sugere, não sempre": no máximo ``max_per_hour`` entregas por hora (bombas não contam esse
limite) e ``max_per_day`` por 24 h; o que passar do limite fica para a próxima rodada. Itens com
mais de ``max_age_h`` horas, ou de obra largada (R19.8), são marcados como entregues sem aviso.

Idempotência: o item é marcado (``mark_delivered``) **antes** de ir para o sink e os ids já
tratados ficam em memória: se o banco falhar ao marcar, o item não se repete nesta execução do
núcleo. Na pior hipótese um aviso se perde; nunca se repete.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from magi.common.config import ConfigError
from magi.common.contracts import CardLevel, CardMsg, NewsItem, NewsLevel, NewsRepo
from magi.core.proactive.sink import Priority, ProactiveSink
from magi.news.priority import Prefs
from magi.news.spoiler import ReleaseStore, Shown, present

log = logging.getLogger(__name__)

KIND = "news"
LEVELS = (NewsLevel.BOMBA, NewsLevel.ALTA)


@dataclass(frozen=True, slots=True)
class DeliveryConfig:
    """Seção ``[news.delivery]`` (padrões em ``config.example.toml``)."""

    enabled: bool = True
    poll_s: float = 300.0
    max_per_hour: int = 2
    max_per_day: int = 8
    max_age_h: float = 48.0
    batch: int = 5

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any] | None) -> DeliveryConfig:
        raw = dict(raw or {})
        kw: dict[str, Any] = {}
        try:
            if "enabled" in raw:
                if not isinstance(raw["enabled"], bool):
                    raise ConfigError("news.delivery.enabled deve ser true/false")
                kw["enabled"] = raw["enabled"]
            for name in ("poll_s", "max_age_h"):
                if name in raw:
                    kw[name] = float(raw[name])
            for name in ("max_per_hour", "max_per_day", "batch"):
                if name in raw:
                    if isinstance(raw[name], bool) or int(raw[name]) != raw[name]:
                        raise ConfigError(f"news.delivery.{name} deve ser inteiro")
                    kw[name] = int(raw[name])
        except (TypeError, ValueError) as e:
            raise ConfigError(f"[news.delivery] inválido: {e}") from e
        cfg = cls(**kw)
        if cfg.poll_s <= 0 or cfg.batch < 1 or cfg.max_per_hour < 0 or cfg.max_per_day < 0:
            raise ConfigError("[news.delivery]: poll_s > 0, batch ≥ 1, limites ≥ 0")
        return cfg


def _utcnow() -> datetime:
    return datetime.now(UTC)


def render(item: NewsItem, shown: Shown) -> tuple[str, CardMsg, Priority]:
    """Frase, card e prioridade do aviso — só a partir de ``shown`` (anti-spoiler)."""
    title = f"Rumor: {shown.title}" if item.is_rumor else shown.title
    url = shown.links[0] if shown.links else ""
    if item.level is NewsLevel.BOMBA:
        return f"Notícia bomba: {shown.subtitle}", CardMsg(CardLevel.BOMBA, title, url), Priority.VOICE
    return "", CardMsg(CardLevel.ALTA, title, url), Priority.SCREEN


class NewsDelivery:
    def __init__(
        self,
        sink: ProactiveSink,
        repo: NewsRepo,
        cfg: DeliveryConfig | None = None,
        *,
        now: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        store: ReleaseStore | None = None,
    ) -> None:
        self.sink = sink
        self.repo = repo
        self.cfg = cfg or DeliveryConfig()
        self._now = now
        self._sleep = sleep
        self._store = store
        self._done: set[int] = set()
        self._sent: deque[datetime] = deque()
        self._task: asyncio.Task[None] | None = None

    # --- limite de frequência ----------------------------------------------------------------

    def _allowed(self, level: NewsLevel | None, now: datetime) -> bool:
        while self._sent and now - self._sent[0] >= timedelta(days=1):
            self._sent.popleft()
        if len(self._sent) >= self.cfg.max_per_day:
            return False
        if level is NewsLevel.BOMBA:
            return True
        last_hour = sum(1 for t in self._sent if now - t < timedelta(hours=1))
        return last_hour < self.cfg.max_per_hour

    # --- uma rodada --------------------------------------------------------------------------

    async def _mark(self, item_id: int, now: datetime) -> None:
        self._done.add(item_id)
        try:
            await self.repo.mark_delivered(item_id, now)
        except Exception:
            log.exception("não consegui marcar a notícia %s como entregue", item_id)

    async def _links(self, ids: Sequence[int]) -> Mapping[int, Sequence[str]]:
        fetch = getattr(self.repo, "item_links", None)
        if fetch is None or not ids:
            return {}
        try:
            return await fetch(ids)
        except Exception:
            log.exception("links das notícias indisponíveis")
            return {}

    async def tick(self) -> list[int]:
        """Entrega o que couber no limite; devolve os ids entregues ao sink."""
        now = self._now()
        if not self._allowed(NewsLevel.BOMBA, now):
            return []
        items = [i for i in await self.repo.undelivered(LEVELS, self.cfg.batch)
                 if i.id is not None and i.id not in self._done]
        if not items:
            return []
        prefs = Prefs.of(await self.repo.franchise_prefs())
        fresh: list[NewsItem] = []
        for item in items:
            assert item.id is not None
            old = item.first_seen is not None and now - item.first_seen > timedelta(hours=self.cfg.max_age_h)
            if old or prefs.dropped(item):
                log.info("notícia %s descartada (%s)", item.id, "velha" if old else "obra largada")
                await self._mark(item.id, now)
            else:
                fresh.append(item)
        if not fresh:
            return []
        links = await self._links([i.id for i in fresh if i.id is not None])
        shown = await present(self.repo, fresh, now, links=links, store=self._store)
        delivered: list[int] = []
        for item, view in zip(fresh, shown, strict=True):
            assert item.id is not None
            if not self._allowed(item.level, now):
                continue
            await self._mark(item.id, now)
            speech, card, priority = render(item, view)
            self._sent.append(now)
            try:
                await self.sink.deliver(KIND, speech, card, priority)
            except Exception:
                log.exception("entrega da notícia %s falhou", item.id)
                continue
            delivered.append(item.id)
            log.info("notícia %s entregue (%s, %s)", item.id, item.level, view.reason)
        return delivered

    # --- laço --------------------------------------------------------------------------------

    def start(self) -> None:
        if self.cfg.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._loop())

    async def aclose(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _loop(self) -> None:
        while True:
            await self._sleep(self.cfg.poll_s)
            try:
                await self.tick()
            except Exception:
                log.exception("entrega de notícias falhou; tento na próxima rodada")
