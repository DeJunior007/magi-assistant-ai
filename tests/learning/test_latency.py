"""Latência do turno com o Learning Engine ligado × desligado (tarefa LM4.2; CA-01, ENG-001, RNF-01).

200 turnos falsos pelo ``TurnPipeline`` real (roteador e agente falsos; o agente "pensa" com
``asyncio.sleep``), na ordem do ``TurnMachine._think``: ``respond`` → entrega → ``after_delivery``.
A latência medida é do início do turno até a entrega. Com o engine ligado, cada turno grava a
mensagem (``JsonlRepo``) e publica no bus; a observação (``FakeModel`` com atraso de "rede") fica em
voo enquanto o próximo turno começa — a disputa real que o ENG-001 proíbe de atrasar o turno.

Só ``FakeModel`` e ``JsonlRepo`` (regras 6 e 7). Tempo de parede (``perf_counter``) porque o que se
mede é disputa de CPU/loop; o atraso fixo do agente domina, e a comparação tenta 2 vezes antes de
reprovar (ruído de máquina carregada). Medição real com o núcleo: ``docs/perf/learning.md``.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from datetime import UTC, datetime
from typing import Any

from magi.common.contracts import (
    ActionResult,
    HudMessage,
    RouteKind,
    RouteResult,
    Transcript,
    TurnContext,
    WakeSource,
)
from magi.core.turn import TurnDeps, TurnPipeline
from magi.learning.config import LearningConfig
from magi.learning.engine import LearningEngine
from magi.learning.model import FakeModel
from magi.learning.repo import JsonlRepo
from magi.learning.wiring import install

TURNS = 200
#: "Pensar" do agente (fixo). 50 ms ainda é 10× mais rápido que um turno real (LLM + TTS ≥ 0,5 s);
#: com 20 ms a razão p95 fica ~1,08 (a sobra absoluta é a mesma, ~1,5 ms; ver docs/perf/learning.md).
AGENT_S = 0.050
GAP_S = 0.003  # pausa entre turnos: menor que a observação, que fica em voo no turno seguinte
OBS_S = 0.010  # "rede" da observação (FakeModel.delay_s)
MAX_RATIO = 1.05  # CA-01
MAX_EXTRA_S = 0.003  # sobra absoluta no p95 (independe do tamanho do turno falso)
ATTEMPTS = 2
AT = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)
PAST = {"category": "grammar", "rule_key": "grammar.past_simple.irregular", "label": "Past tense",
        "span": "I make", "suggestion": "I made"}


class SlowAgent:
    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        await asyncio.sleep(AGENT_S)
        return ActionResult(ok=True, speech="Oh, lovely. Tell me more.")


class FakeRouter:
    def route(self, text: str, ctx: TurnContext) -> RouteResult:
        return RouteResult(RouteKind.AGENT, text)


class SinkHud:
    def __init__(self) -> None:
        self.sent: list[HudMessage] = []
        self.on_learning = None

    async def send(self, msg: HudMessage) -> None:
        self.sent.append(msg)


class Core:
    """Estado do núcleo visto pelo gate (``thinking`` durante o turno, ``listening`` fora)."""

    def __init__(self) -> None:
        self.state = "listening"


class SpyModel(FakeModel):
    """``FakeModel`` de observação que anota o estado do núcleo no início de cada chamada de "rede"."""

    def __init__(self, core: Core, **kw: Any) -> None:
        super().__init__({"*": {"items": [PAST]}}, delay_s=OBS_S, **kw)
        self.core = core
        self.states: list[str] = []

    async def complete(self, system: str, user: str, schema: dict) -> tuple[dict, float]:
        self.states.append(self.core.state)  # estado no início da chamada
        return await super().complete(system, user, schema)


def p95(xs: list[float]) -> float:
    return statistics.quantiles(xs, n=100, method="inclusive")[94]


async def _turns(tmp_path, *, engine_on: bool) -> tuple[list[float], list[float], Any]:
    """Roda ``TURNS`` turnos; devolve (latências até a entrega, duração do gancho, modelo espião)."""
    core = Core()
    pipeline = TurnPipeline(TurnDeps(router=FakeRouter(), agent=SlowAgent()))
    model: SpyModel | None = None
    eng: LearningEngine | None = None
    w = None
    if engine_on:
        repo = JsonlRepo(tmp_path)
        model = SpyModel(core)
        eng = LearningEngine(FakeModel(), repo, observe_model=model,
                             gate=lambda: core.state == "listening", gate_poll_s=0.002)
        w = install(LearningConfig(storage="jsonl"), SinkHud(), pipeline, repo=repo, engine=eng,
                    clock=lambda: AT, start=False)
        assert w is not None and pipeline.deps.learning is not None
        await w.set_mode(True)
    else:
        assert pipeline.deps.learning is None

    lat: list[float] = []
    hook: list[float] = []
    for i in range(TURNS):
        transcript = Transcript.raw(f"yesterday I make a new feature number {i}", language="en")
        ctx = TurnContext("pc", WakeSource.WAKE, datetime.now(UTC))
        core.state = "thinking"
        t0 = time.perf_counter()
        result = await pipeline.respond(transcript, ctx)
        lat.append(time.perf_counter() - t0)  # entregue ao TTS/HUD
        core.state = "listening"
        t1 = time.perf_counter()
        pipeline.after_delivery(transcript, ctx, result)
        hook.append(time.perf_counter() - t1)
        await asyncio.sleep(GAP_S)

    if w is not None and eng is not None:
        await w.wait_idle()
        for _ in range(500):
            if eng.observations_idle and not len(eng.bus):
                break
            await asyncio.sleep(0.01)
        await eng.aclose()
        await w.aclose()
    return lat, hook, model


async def test_ca01_p95_com_engine_ligado_ate_5pc_acima_do_desligado(tmp_path) -> None:
    ratios: list[float] = []
    extras: list[float] = []
    for attempt in range(ATTEMPTS):
        off, _, _ = await _turns(tmp_path / f"off{attempt}", engine_on=False)
        on, hook, model = await _turns(tmp_path / f"on{attempt}", engine_on=True)
        ratio = p95(on) / p95(off)
        ratios.append(ratio)
        extras.append(p95(on) - p95(off))
        print(f"CA-01 tentativa {attempt + 1}: p95 off={p95(off) * 1000:.2f} ms "
              f"on={p95(on) * 1000:.2f} ms razão={ratio:.3f}; "
              f"mediana off={statistics.median(off) * 1000:.2f} on={statistics.median(on) * 1000:.2f}; "
              f"gancho máx={max(hook) * 1000:.3f} ms; observações={len(model.states)}")
        # o engine trabalhou de verdade no teste (senão a comparação não mede nada)
        assert model is not None and len(model.states) >= TURNS // 4
        # nenhuma chamada de "rede" do engine começa com o turno em andamento (antes da entrega)
        assert set(model.states) == {"listening"}
        # o gancho é síncrono e só agenda (put_nowait): nada de await de rede nele
        assert max(hook) < 0.005
        if ratio <= MAX_RATIO and extras[-1] <= MAX_EXTRA_S:
            break
    assert min(ratios) <= MAX_RATIO, f"CA-01 reprovado: razões p95 {ratios} (> {MAX_RATIO})"
    assert min(extras) <= MAX_EXTRA_S, f"sobra p95 {[round(e * 1000, 2) for e in extras]} ms"


def test_gancho_vem_depois_da_entrega_no_turn_machine() -> None:
    """Ordem do ``TurnMachine``: ``after_delivery`` só depois de ``_deliver`` (design §6)."""
    import inspect

    from magi.core.turn import TurnMachine

    src = inspect.getsource(TurnMachine)
    calls = src.count("self.pipeline.after_delivery(")
    assert calls >= 1
    # cada chamada do gancho tem uma entrega antes dela no mesmo método
    for chunk in src.split("self.pipeline.after_delivery(")[:-1]:
        method = chunk.rsplit("\n    async def ", 1)[-1]
        assert "_deliver(" in method or "speak" in method
