"""Retorno e aprendizado das notícias (tarefa 6.11; design §7 ``news_feedback``/``franchise_prefs``,
§8 passo 4; R19.7, R19.8).

O retorno mexe em ``franchise_prefs.weight``, que é o ``gosto`` da fórmula de
``magi.news.priority`` (peso 0,45). Obra sem preferência pontua com ``DEFAULT_TASTE``; o primeiro
retorno parte desse valor. O efeito aparece na próxima pontuação (``score_pending``) dos itens
novos da obra.

- **"não curti" / "não quero saber disso"** (``news.dislike``): sobre a última notícia entregue
  (até ``recent_h`` horas) → sinal ``-1`` em ``news_feedback`` e ``weight -= step``;
- **"mais disso" / "curti essa notícia"** (``news.more``) → sinal ``+1`` e ``weight += step``;
- **ignorado** (:func:`apply_ignored`, roda no ``magi-news`` antes de pontuar): as últimas
  ``ignored_after`` entregas da mesma obra sem nenhum retorno, todas entregues há mais de
  ``grace_h`` horas → sinal ``0`` nelas (a sequência recomeça) e ``weight -= ignored_step``;
- **obra largada** (``news.drop``, "larguei X"; R19.8) → ``dropped = true``. Quem filtra é a
  6.10 (nota 0, nunca entregue); o AniList ``DROPPED`` já vira ``dropped`` na 6.8.

Pesos ficam em 0..1. Idempotência: o mesmo sinal repetido sobre o mesmo item não mexe de novo no
peso; itens já marcados como ignorados têm retorno e não contam numa nova sequência.

Itens sem obra só gravam o sinal (servem de exemplo para a classificação, §8 passo 3): o gosto
da fórmula é por obra.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from magi.common.config import ConfigError
from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    ActionResult,
    FranchisePref,
    IntentId,
    NewsItem,
)
from magi.news.priority import DEFAULT_TASTE, Prefs
from magi.news.spoiler import norm

log = logging.getLogger(__name__)

SIGNAL_MORE = 1
SIGNAL_DISLIKE = -1
SIGNAL_IGNORED = 0

SAY_DISLIKE = "Anotado, menos disso."
SAY_MORE = "Anotado, mais disso."
SAY_SAME = "Já tinha anotado."
SAY_NO_ITEM = "Não te mostrei notícia nenhuma agora há pouco."
SAY_NO_DB = "Tô sem o banco das notícias agora."
SAY_DROP = "Beleza, paro de acompanhar {franchise}."
SAY_NO_FRANCHISE = "Não entendi qual obra."


class FeedbackRepo(Protocol):
    """Parte do ``PgNewsRepo`` usada aqui (``delivered_recent`` e ``feedback_signals`` estão fora
    do contrato ``NewsRepo``)."""

    async def franchise_prefs(self) -> list[FranchisePref]: ...

    async def set_franchise_pref(self, pref: FranchisePref) -> None: ...

    async def add_feedback(self, item_id: int, signal: int, at: datetime) -> None: ...

    async def delivered_recent(self, limit: int = 50) -> list[NewsItem]: ...

    async def feedback_signals(self, item_ids: Sequence[int]) -> dict[int, list[int]]: ...


@dataclass(frozen=True, slots=True)
class FeedbackConfig:
    """Seção ``[news.feedback]``."""

    step: float = 0.25
    ignored_step: float = 0.1
    ignored_after: int = 3
    grace_h: float = 2.0
    recent_h: float = 6.0
    max_age_h: float = 48.0  # igual a ``[news.delivery] max_age_h``: entregas silenciosas de velhos

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any] | None) -> FeedbackConfig:
        raw = dict(raw or {})
        kw: dict[str, Any] = {}
        try:
            for name in ("step", "ignored_step", "grace_h", "recent_h", "max_age_h"):
                if name in raw:
                    kw[name] = float(raw[name])
            if "ignored_after" in raw:
                kw["ignored_after"] = int(raw["ignored_after"])
        except (TypeError, ValueError) as e:
            raise ConfigError(f"[news.feedback] inválido: {e}") from e
        cfg = cls(**kw)
        if not (0 < cfg.step <= 1 and 0 <= cfg.ignored_step <= 1) or cfg.ignored_after < 1:
            raise ConfigError("[news.feedback]: step em (0, 1], ignored_step em [0, 1], ignored_after ≥ 1")
        return cfg


def _utcnow() -> datetime:
    return datetime.now(UTC)


def adjust(prefs: Prefs, franchise: str, delta: float) -> FranchisePref:
    """Nova preferência com ``weight`` somado de ``delta`` e limitado a 0..1 (mantém o nome já
    gravado da obra, se houver)."""
    pref = prefs.get(franchise) or FranchisePref(franchise, weight=DEFAULT_TASTE)
    weight = round(max(0.0, min(1.0, min(pref.weight, 1.0) + delta)), 4)
    return replace(pref, weight=weight)


def _shown(item: NewsItem, max_age_h: float) -> bool:
    """Entregue de fato: a entrega marca sem aviso os itens velhos (``first_seen`` além de
    ``max_age_h`` na hora da entrega)."""
    if item.delivered_at is None:
        return False
    if item.first_seen is None:
        return True
    return item.delivered_at - item.first_seen <= timedelta(hours=max_age_h)


class NewsFeedback:
    def __init__(
        self, repo: FeedbackRepo | None = None, cfg: FeedbackConfig | None = None, *, now: Any = _utcnow
    ) -> None:
        self.repo = repo
        self.cfg = cfg or FeedbackConfig()
        self._now = now

    async def last_delivered(self) -> NewsItem | None:
        assert self.repo is not None
        now = self._now()
        for item in await self.repo.delivered_recent(10):
            if _shown(item, self.cfg.max_age_h):
                assert item.delivered_at is not None
                return item if now - item.delivered_at <= timedelta(hours=self.cfg.recent_h) else None
        return None

    async def signal(self, sig: int) -> tuple[NewsItem | None, bool]:
        """Grava ``sig`` (±1) sobre a última notícia entregue. Devolve (item, mudou)."""
        assert self.repo is not None
        item = await self.last_delivered()
        if item is None or item.id is None:
            return None, False
        old = (await self.repo.feedback_signals([item.id])).get(item.id, [])
        if old and old[-1] == sig:
            return item, False
        await self.repo.add_feedback(item.id, sig, self._now())
        if item.franchise:
            prefs = Prefs.of(await self.repo.franchise_prefs())
            pref = adjust(prefs, item.franchise, sig * self.cfg.step)
            await self.repo.set_franchise_pref(pref)
            log.info("retorno %+d em %s: peso de %s → %.2f", sig, item.id, pref.franchise, pref.weight)
        return item, True

    async def drop(self, franchise: str) -> FranchisePref:
        """Obra largada (R19.8)."""
        assert self.repo is not None
        prefs = Prefs.of(await self.repo.franchise_prefs())
        pref = replace(prefs.get(franchise) or FranchisePref(franchise, weight=DEFAULT_TASTE), dropped=True)
        await self.repo.set_franchise_pref(pref)
        return pref

    async def apply_ignored(self, *, limit: int = 100) -> list[str]:
        """Obras com ``ignored_after`` entregas seguidas sem retorno: peso cai. Devolve as obras."""
        assert self.repo is not None
        now, n = self._now(), self.cfg.ignored_after
        grace = timedelta(hours=self.cfg.grace_h)
        items = [i for i in await self.repo.delivered_recent(limit)
                 if i.id is not None and i.franchise and _shown(i, self.cfg.max_age_h)]
        signals = await self.repo.feedback_signals([i.id for i in items if i.id is not None])
        by_franchise: dict[str, list[NewsItem]] = {}
        prefs = Prefs.of(await self.repo.franchise_prefs())
        for item in items:  # mais recentes primeiro
            assert item.franchise is not None
            by_franchise.setdefault(norm(item.franchise), []).append(item)
        hit: list[str] = []
        for group in by_franchise.values():
            last = group[:n]
            if len(last) < n or any(signals.get(i.id or 0) for i in last):
                continue
            if any(now - (i.delivered_at or now) < grace for i in last):
                continue
            for i in last:
                assert i.id is not None
                await self.repo.add_feedback(i.id, SIGNAL_IGNORED, now)
            franchise = last[0].franchise or ""
            if prefs.dropped(last[0]):
                continue
            pref = adjust(prefs, franchise, -self.cfg.ignored_step)
            await self.repo.set_franchise_pref(pref)
            prefs = Prefs.of([*prefs.by_name.values(), pref])
            hit.append(pref.franchise)
            log.info("%s ignorada %d× seguidas: peso → %.2f", pref.franchise, n, pref.weight)
        return hit


class NewsFeedbackHandler:
    """``news.dislike``, ``news.more`` e ``news.drop`` para o ``Registry``. Sem banco, recusa."""

    intents = frozenset({IntentId.NEWS_DISLIKE.value, IntentId.NEWS_MORE.value, IntentId.NEWS_DROP.value})

    def __init__(self, feedback: NewsFeedback) -> None:
        self.feedback = feedback

    async def run(self, req: ActionRequest) -> ActionResult:
        if self.feedback.repo is None:
            return ActionResult(ok=False, speech=SAY_NO_DB)
        if req.intent.id == IntentId.NEWS_DROP.value:
            slot = req.intent.slot("franchise")
            name = (slot.display or slot.value or slot.raw).strip() if slot else ""
            if not name:
                return ActionResult(ok=False, speech=SAY_NO_FRANCHISE)
            pref = await self.feedback.drop(name)
            return ActionResult(ok=True, speech=SAY_DROP.format(franchise=pref.franchise))
        sig = SIGNAL_MORE if req.intent.id == IntentId.NEWS_MORE.value else SIGNAL_DISLIKE
        item, changed = await self.feedback.signal(sig)
        if item is None:
            return ActionResult(ok=False, speech=SAY_NO_ITEM)
        if not changed:
            return ActionResult(ok=True, speech=SAY_SAME)
        return ActionResult(ok=True, speech=SAY_MORE if sig > 0 else SAY_DISLIKE)


def handlers(feedback: NewsFeedback | None = None) -> list[ActionHandler]:
    return [NewsFeedbackHandler(feedback or NewsFeedback())]
