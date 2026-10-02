"""Prioridade e nível das notícias (tarefa 6.10; design §8 passo 4; R18.5, R19.4, R19.8).

``priority = 0,45·gosto + 0,25·tamanho + 0,15·confiança + 0,15·novidade``, cada termo em 0..1:

- ``gosto``: ``weight`` de ``franchise_prefs`` da obra do item (limitado a 0..1); obra sem
  preferência ou item sem obra → :data:`DEFAULT_TASTE`;
- ``tamanho``: "tamanho do fato" da classificação (``spoiler["size"]``, 6.7);
- ``confiança``: ``max_trust / 3`` (fontes 1..3, R18.4);
- ``novidade``: 1 ao aparecer, caindo em linha reta até 0 em :data:`FRESH_H` horas
  (``first_seen``; sem data = 1).

Níveis: bomba ≥ 0,85 **e** ≥ 2 fontes distintas com pelo menos uma de confiança 3 (R18.5; sem
isso cai para alta); alta ≥ 0,65; normal ≥ 0,4; abaixo, guardada. Obra largada (R19.8,
``dropped``) → nota 0 e guardada: nunca é entregue nem aparece em "novidades?".

:func:`score_pending` é o passo 4 da execução do ``magi-news``: pontua os itens classificados
ainda sem nível (``PgNewsRepo.unscored``) e grava com ``update_item``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from magi.common.contracts import FranchisePref, NewsItem, NewsLevel, NewsRepo
from magi.news.spoiler import norm

log = logging.getLogger(__name__)

W_TASTE, W_SIZE, W_TRUST, W_FRESH = 0.45, 0.25, 0.15, 0.15
BOMBA, ALTA, NORMAL = 0.85, 0.65, 0.4
BOMBA_MIN_SOURCES = 2
BOMBA_TRUST = 3
DEFAULT_TASTE = 0.3
FRESH_H = 72.0


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _size(item: NewsItem) -> float:
    try:
        return _clamp(float((item.spoiler or {}).get("size", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def freshness(item: NewsItem, now: datetime, fresh_h: float = FRESH_H) -> float:
    if item.first_seen is None or fresh_h <= 0:
        return 1.0
    age_h = (now - item.first_seen).total_seconds() / 3600
    return _clamp(1.0 - age_h / fresh_h)


def is_bomb_eligible(item: NewsItem) -> bool:
    """R18.5: pelo menos 2 fontes distintas, uma delas de confiança 3."""
    return item.sources >= BOMBA_MIN_SOURCES and item.max_trust >= BOMBA_TRUST


def level_for(priority: float, item: NewsItem) -> NewsLevel:
    if priority >= BOMBA and is_bomb_eligible(item):
        return NewsLevel.BOMBA
    if priority >= ALTA:
        return NewsLevel.ALTA
    if priority >= NORMAL:
        return NewsLevel.NORMAL
    return NewsLevel.GUARDADA


@dataclass(frozen=True, slots=True)
class Prefs:
    """``franchise_prefs`` indexado pelo nome normalizado."""

    by_name: Mapping[str, FranchisePref]

    @classmethod
    def of(cls, prefs: Iterable[FranchisePref]) -> Prefs:
        return cls({norm(p.franchise): p for p in prefs})

    def get(self, franchise: str | None) -> FranchisePref | None:
        return self.by_name.get(norm(franchise)) if franchise else None

    def dropped(self, item: NewsItem) -> bool:
        pref = self.get(item.franchise)
        return pref is not None and pref.dropped


def taste(item: NewsItem, prefs: Prefs, default: float = DEFAULT_TASTE) -> float:
    pref = prefs.get(item.franchise)
    return default if pref is None else _clamp(pref.weight)


def score(item: NewsItem, prefs: Prefs, now: datetime, *, default_taste: float = DEFAULT_TASTE) -> float:
    if prefs.dropped(item):
        return 0.0
    total = (
        W_TASTE * taste(item, prefs, default_taste)
        + W_SIZE * _size(item)
        + W_TRUST * _clamp(item.max_trust / 3)
        + W_FRESH * freshness(item, now)
    )
    return round(total, 4)


def rate(item: NewsItem, prefs: Prefs, now: datetime, **kw: Any) -> NewsItem:
    """``item`` com ``priority`` e ``level`` preenchidos."""
    p = score(item, prefs, now, **kw)
    level = NewsLevel.GUARDADA if prefs.dropped(item) else level_for(p, item)
    return replace(item, priority=p, level=level)


@dataclass(frozen=True, slots=True)
class ScoreReport:
    by_level: Mapping[NewsLevel, int]

    def summary(self) -> str:
        parts = ", ".join(f"{lv.value} {n}" for lv, n in self.by_level.items() if n)
        return f"{sum(self.by_level.values())} pontuados" + (f" ({parts})" if parts else "")


async def score_pending(repo: NewsRepo, now: datetime, *, limit: int = 200) -> ScoreReport:
    """Passo 4 do §8: pontua os classificados sem nível. Exige ``repo.unscored`` (Pg)."""
    items = await repo.unscored(limit)  # type: ignore[attr-defined]
    prefs = Prefs.of(await repo.franchise_prefs())
    counts = dict.fromkeys(NewsLevel, 0)
    for item in items:
        rated = rate(item, prefs, now)
        await repo.update_item(rated)
        counts[rated.level] += 1  # type: ignore[index]
    return ScoreReport(counts)
