from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from magi.common.contracts import FranchisePref, NewsItem, NewsLevel
from magi.news import priority as P

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


def item(*, size=1.0, trust=3, sources=2, franchise="Silksong", age_h=0.0, iid=1):
    return NewsItem(
        title="Silksong ganha data", franchise=franchise, kind="data", sources=sources, max_trust=trust,
        first_seen=NOW - timedelta(hours=age_h), id=iid,
        spoiler={"has": False, "of": "", "safe_title": "", "size": size},
    )


PREFS = P.Prefs.of([FranchisePref("Silksong", weight=1.0), FranchisePref("Overlord", dropped=True)])


def test_formula():
    # 0,45·1 + 0,25·1 + 0,15·1 + 0,15·1 = 1
    assert P.score(item(), PREFS, NOW) == pytest.approx(1.0)
    # gosto padrão 0,3, tamanho 0,4, confiança 2/3, novidade 0,5 (36 h de 72)
    got = P.score(item(size=0.4, trust=2, franchise="Outra", age_h=36), PREFS, NOW)
    assert got == pytest.approx(0.45 * 0.3 + 0.25 * 0.4 + 0.15 * 2 / 3 + 0.15 * 0.5, abs=1e-4)
    # nome normalizado casa a preferência
    assert P.taste(item(franchise="SILKSONG"), PREFS) == 1.0


def test_niveis_e_regra_da_bomba():
    assert P.rate(item(), PREFS, NOW).level is NewsLevel.BOMBA
    # nota de bomba, mas 1 fonte só ou nenhuma de confiança 3 → alta (R18.5)
    assert P.level_for(0.9, item(sources=1)) is NewsLevel.ALTA
    assert P.level_for(0.9, item(trust=2)) is NewsLevel.ALTA
    assert P.level_for(0.7, item()) is NewsLevel.ALTA
    assert P.level_for(0.5, item()) is NewsLevel.NORMAL
    assert P.level_for(0.39, item()) is NewsLevel.GUARDADA


def test_obra_largada_guardada():
    rated = P.rate(item(franchise="overlord"), PREFS, NOW)
    assert (rated.priority, rated.level) == (0.0, NewsLevel.GUARDADA)


class Repo:
    def __init__(self, items):
        self.items = items
        self.saved = []

    async def unscored(self, limit=100):
        return self.items[:limit]

    async def franchise_prefs(self):
        return list(PREFS.by_name.values())

    async def update_item(self, it):
        self.saved.append(it)


async def test_score_pending():
    repo = Repo([item(), item(iid=2, size=0.0, trust=1, sources=1, franchise="Outra", age_h=100)])
    report = await P.score_pending(repo, NOW)
    assert [(i.id, i.level) for i in repo.saved] == [(1, NewsLevel.BOMBA), (2, NewsLevel.GUARDADA)]
    assert report.summary() == "2 pontuados (bomba 1, guardada 1)"
    assert replace(repo.saved[0], priority=None, level=None) == repo.items[0]
