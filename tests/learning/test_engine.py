"""Learning Engine — fila de ações (tarefa LM3.3; CA-12, CA-13, cache; spec §5 "Ciclo").

Só ``FakeModel`` e ``JsonlRepo`` (regras 6 e 7): nada de rede nem de banco compartilhado.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from magi.common.contracts import HudMessage, LmActionMsg, LmModeMsg, LmResultMsg
from magi.core.budget import MonthlyBudget
from magi.learning.budget import LearningBudget
from magi.learning.config import LearningConfig
from magi.learning.contracts import ActionKind, Author, Source
from magi.learning.engine import UNAVAILABLE_ERROR, LearningEngine
from magi.learning.model import FakeModel, ModelFailure, ModelTimeout
from magi.learning.repo import JsonlRepo
from magi.learning.wiring import LearningWiring

PEDRO = "yesterday I make a new authentication system"
CONDESSA = "That sounds splendid. Did you build it on your own?"
EXPLAIN = {"question": "Why make?", "answer": "Here the past tense is needed."}
IMPROVE = {"original": PEDRO, "improved": "yesterday I built a new authentication system",
           "kind": "both", "why": "Past tense: yesterday → built."}


class MemCosts:
    def __init__(self, preset: float = 0.0) -> None:
        self.rows: list[Any] = []
        self.preset = preset

    async def add(self, usage: Any, at: datetime) -> int:
        self.rows.append(usage)
        return len(self.rows)

    async def month_total(self, year: int, month: int) -> float:
        return self.preset + sum(u.usd for u in self.rows)


def _budget(cap: float = 5.0, spent: float = 0.0) -> tuple[LearningBudget, MemCosts]:
    costs = MemCosts(spent)
    now = lambda: datetime(2026, 10, 7, 21, 0, tzinfo=UTC)  # noqa: E731
    return LearningBudget(MonthlyBudget(costs, cap_usd=cap, prices={}, now=now), now=now), costs


async def _repo(tmp_path) -> tuple[JsonlRepo, int, int]:
    repo = JsonlRepo(tmp_path)
    info = await repo.open_session(level="B2", track="CONVERSATION")
    you = await repo.add_message(info.id, Author.YOU, Source.VOICE, PEDRO)
    her = await repo.add_message(info.id, Author.CONDESSA, Source.VOICE, CONDESSA)
    return repo, you.id, her.id


def _act(mid: int, piece: str, text: str, kind: ActionKind = ActionKind.EXPLAIN,
         aid: str = "ACT-00000001") -> LmActionMsg:
    start = text.index(piece)
    return LmActionMsg(aid, kind, mid, start, start + len(piece))


async def test_ok_grava_e_cache_nao_chama_o_modelo(tmp_path) -> None:
    repo, you, _ = await _repo(tmp_path)
    model = FakeModel({"explain:*": EXPLAIN}, cost_usd=0.002)
    eng = LearningEngine(model, repo)
    r = await eng.handle(_act(you, "make", PEDRO))
    assert r is not None and r.ok and r.data == EXPLAIN and not r.cached and r.cost_usd == 0.002
    assert len(model.calls) == 1
    # contexto: só a mensagem selecionada (não há anteriores)
    assert f'<selection message="{you}"' in model.calls[0][1]
    stored = await repo.get_action("ACT-00000001")
    assert stored is not None and stored.result.data == EXPLAIN

    again = await eng.handle(_act(you, "make", PEDRO, aid="ACT-00000002"))
    assert again is not None and again.ok and again.cached
    assert again.id == "ACT-00000002" and again.data == EXPLAIN and again.cost_usd == 0.0
    assert len(model.calls) == 1  # 2ª ação igual não chama o modelo

    other = await eng.handle(_act(you, "make", PEDRO, ActionKind.IMPROVE, "ACT-00000003"))
    assert other is not None and not other.ok  # outro kind = sem cache (sem resposta gravada)
    assert len(model.calls) == 2
    await eng.aclose()


async def test_falhas(tmp_path) -> None:
    """CA-12: timeout → ``timeout``; JSON inválido 2× → ``invalid``; sem gravação."""
    repo, you, her = await _repo(tmp_path)

    model = FakeModel({"explain:*": ModelTimeout("8 s")})
    r = await LearningEngine(model, repo).handle(_act(you, "make", PEDRO))
    assert r is not None and not r.ok and r.error == "timeout" and r.data is None
    assert len(model.calls) == 1  # timeout não tenta de novo

    slow = FakeModel({"explain:*": EXPLAIN}, delay_s=1.0)
    r = await LearningEngine(slow, repo, timeout_s=0.05).handle(_act(you, "new", PEDRO, aid="ACT-0000000a"))
    assert r is not None and r.error == "timeout"

    bad = FakeModel({"explain:*": "isso não é JSON"})
    r = await LearningEngine(bad, repo).handle(_act(you, "system", PEDRO, aid="ACT-0000000b"))
    assert r is not None and not r.ok and r.error == "invalid"
    assert len(bad.calls) == 2  # 1 nova tentativa só em invalid

    schema = FakeModel({"improve:*": {"original": PEDRO}})  # campo obrigatório faltando
    act = _act(you, "make", PEDRO, ActionKind.IMPROVE, "ACT-0000000c")
    r = await LearningEngine(schema, repo).handle(act)
    assert r is not None and r.error == "invalid" and len(schema.calls) == 2

    flaky = FakeModel({"improve:*": IMPROVE})
    answers = iter(["{oops", IMPROVE])
    flaky._lookup = lambda *a: next(answers)  # type: ignore[method-assign]
    r = await LearningEngine(flaky, repo).handle(_act(you, "make", PEDRO, ActionKind.IMPROVE, "ACT-0000000d"))
    assert r is not None and r.ok and r.data["improved"].endswith("built a new authentication system")

    down = FakeModel({"explain:*": ModelFailure("500")})
    r = await LearningEngine(down, repo).handle(_act(her, "splendid", CONDESSA, aid="ACT-0000000e"))
    assert r is not None and r.error == "model" and len(down.calls) == 1

    assert await repo.get_action("ACT-00000001") is None
    assert await repo.get_action("ACT-0000000e") is None


async def test_budget(tmp_path) -> None:
    """CA-13: teto estourado → ``budget`` sem chamar o modelo; custo gravado em ``costs``."""
    repo, you, _ = await _repo(tmp_path)
    budget, costs = _budget(cap=1.0)
    model = FakeModel({"explain:*": EXPLAIN}, cost_usd=1.0, budget=budget, label="learning_actions")
    eng = LearningEngine(model, repo, budget=budget)
    r = await eng.handle(_act(you, "make", PEDRO))
    assert r is not None and r.ok and r.cost_usd == 1.0
    assert [(str(u.task), u.usd) for u in costs.rows] == [("learning_actions", 1.0)]

    # o gasto (US$ 1,00) chegou ao teto: próxima ação é recusada antes do modelo
    r = await eng.handle(_act(you, "new", PEDRO, aid="ACT-00000002"))
    assert r is not None and not r.ok and r.error == "budget"
    assert len(model.calls) == 1 and len(costs.rows) == 1
    # o cache continua valendo com o teto estourado (não chama modelo)
    r = await eng.handle(_act(you, "make", PEDRO, aid="ACT-00000003"))
    assert r is not None and r.ok and r.cached
    await eng.aclose()
    # sem pré-checagem no engine, a recusa do próprio modelo (ModelBudget) também vira budget
    r = await LearningEngine(model, repo).handle(_act(you, "system", PEDRO, aid="ACT-00000004"))
    assert r is not None and r.error == "budget" and len(model.calls) == 1


async def test_indisponivel_responde_model_sem_retry(tmp_path) -> None:
    repo, you, her = await _repo(tmp_path)
    model = FakeModel({"*": IMPROVE})
    eng = LearningEngine(model, repo)
    cases = [
        _act(her, "splendid", CONDESSA, ActionKind.IMPROVE),  # Improve na Condessa (P7)
        LmActionMsg("ACT-00000002", ActionKind.EXPLAIN, 999, 0, 3),  # mensagem desconhecida
        LmActionMsg("ACT-00000003", ActionKind.EXPLAIN, you, 0, 999),  # fora do texto
        LmActionMsg("ACT-00000004", ActionKind.VOCABULARY, you, 0, len(PEDRO)),  # > 4 palavras
    ]
    for msg in cases:
        r = await eng.handle(msg)
        assert r is not None and not r.ok and r.error == UNAVAILABLE_ERROR and r.id == msg.id
    assert model.calls == []


async def test_semaforo_e_cancelamento_da_anterior(tmp_path) -> None:
    repo, you, her = await _repo(tmp_path)
    model = FakeModel({"explain:*": EXPLAIN, "translate:*": {"translation": "esplêndido"}}, delay_s=0.05)
    eng = LearningEngine(model, repo)
    running = asyncio.create_task(eng.handle(_act(you, "make", PEDRO, aid="ACT-00000001")))
    await asyncio.sleep(0.01)  # a 1ª já está no modelo
    queued = asyncio.create_task(eng.handle(_act(you, "new", PEDRO, aid="ACT-00000002")))
    await asyncio.sleep(0)
    other = asyncio.create_task(eng.handle(_act(her, "splendid", CONDESSA, ActionKind.TRANSLATE,
                                                "ACT-00000003"), client="outro"))
    await asyncio.sleep(0)
    newest = asyncio.create_task(eng.handle(_act(you, "system", PEDRO, aid="ACT-00000004")))
    r1, r2, r3, r4 = await asyncio.gather(running, queued, other, newest)
    assert r1 is not None and r1.ok  # já rodava: termina e grava
    assert r2 is None  # cancelada ainda na fila
    assert r3 is not None and r3.ok  # outro cliente não é cancelado
    assert r4 is not None and r4.ok
    assert len(model.calls) == 3  # a cancelada não chegou ao modelo
    assert eng.actions_pending == 0
    await eng.aclose()


async def test_semaforo_uma_chamada_por_vez(tmp_path) -> None:
    repo, you, her = await _repo(tmp_path)
    active = peak = 0

    class Probe(FakeModel):
        async def complete(self, system: str, user: str, schema: dict) -> tuple[dict, float]:
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return await super().complete(system, user, schema)

    eng = LearningEngine(Probe({"explain:*": EXPLAIN}), repo)
    rs = await asyncio.gather(*(
        eng.handle(_act(m, w, t, aid=f"ACT-0000000{i}"), client=f"c{i}")
        for i, (m, w, t) in enumerate([(you, "make", PEDRO), (you, "new", PEDRO), (her, "build", CONDESSA)])
    ))
    assert all(r is not None and r.ok for r in rs) and peak == 1
    await eng.aclose()


class SinkHud:
    def __init__(self) -> None:
        self.sent: list[HudMessage] = []

    async def send(self, msg: HudMessage) -> None:
        self.sent.append(msg)


async def test_wiring_lm_action_vira_lm_result(tmp_path) -> None:
    repo = JsonlRepo(tmp_path)
    hud = SinkHud()
    eng = LearningEngine(FakeModel({"explain:*": EXPLAIN}), repo)
    w = LearningWiring(LearningConfig(storage="jsonl"), repo, hud, None, engine=eng)  # type: ignore[arg-type]
    await w.on_learning(_act(1, "make", PEDRO))  # fora do modo: ignorada
    await w.wait_idle()
    assert not [m for m in hud.sent if isinstance(m, LmResultMsg)]

    await w.on_learning(LmModeMsg(True))
    msg = await w.session.add_message(Author.YOU, Source.VOICE, PEDRO)
    assert msg is not None
    await w.on_learning(_act(msg.id, "make", PEDRO))
    await w.wait_idle()
    results = [m for m in hud.sent if isinstance(m, LmResultMsg)]
    assert len(results) == 1 and results[0].result.ok and results[0].result.data == EXPLAIN
    assert results[0].to_dict()["t"] == "lm_result"

    no_engine = LearningWiring(LearningConfig(storage="jsonl"), repo, hud, None)  # type: ignore[arg-type]
    await no_engine.on_learning(LmModeMsg(True))
    await no_engine.on_learning(_act(msg.id, "make", PEDRO, aid="ACT-00000009"))
    await no_engine.wait_idle()
    last = [m for m in hud.sent if isinstance(m, LmResultMsg)][-1].result
    assert last.id == "ACT-00000009" and not last.ok and last.error == UNAVAILABLE_ERROR
    await w.aclose()
    await no_engine.aclose()
