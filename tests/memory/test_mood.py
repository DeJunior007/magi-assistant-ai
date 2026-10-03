"""Termômetro de humor (tarefa 4.3): sinais, suavização, decaimento, comandos e persistência."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from magi.common.contracts import (
    ActionRequest,
    Intent,
    IntentId,
    MoodEvent,
    MoodMsg,
    ToneMetadata,
    TurnContext,
    WakeSource,
)
from magi.core.turn import TurnDeps, TurnPipeline
from magi.memory import mood
from magi.memory.mood import MoodHandler, MoodTracker, read_signals

# 15h em São Paulo (fora da madrugada)
T0 = datetime(2026, 10, 3, 18, 0, tzinfo=UTC)


class Clock:
    def __init__(self, t: datetime = T0) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> None:
        self.t += timedelta(**kw)


class FakeHud:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, msg: object) -> None:
        self.sent.append(msg)


class FakeEvents:
    def __init__(self) -> None:
        self.events: list[MoodEvent] = []

    async def add(self, event: MoodEvent) -> None:
        self.events.append(event)

    async def since(self, at: datetime) -> list[MoodEvent]:
        return [e for e in self.events if e.at >= at]


def ctx(**kw: object) -> TurnContext:
    return TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=T0, **kw)  # type: ignore[arg-type]


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def names(text: str, **kw: object) -> set[str]:
    return {e.signal for e in read_signals(text, kw.pop("at", T0), **kw)}  # type: ignore[arg-type]


# -- sinais ------------------------------------------------------------------------------------


def test_signals_words() -> None:
    assert names("Porra, que merda de boss") == {"swear"}
    assert names("aff") == {"swear"}
    assert names("kkkkk boa") == {"laugh", "thanks"}
    assert names("hahaha") == {"laugh"}
    assert names("valeu, Magui") == {"thanks"}
    assert names("para de zoar") == {"stop_tease"}
    assert names("não, eu falei Hades") == {"correction"}
    assert names("abre o Steam") == set()
    assert names("essa fase é chata") == set()


def test_signals_tone_and_hour() -> None:
    assert names("abre", tone=ToneMetadata(-6.0, 4.0, 900)) == {"loud"}
    assert names("abre", tone=ToneMetadata(-40.0, 2.0, 900)) == {"flat"}
    assert names("abre", tone=ToneMetadata(-20.0, 8.0, 900)) == {"fast"}
    assert names("abre", tone=ToneMetadata(-6.0, 4.0, 0)) == set()  # sem voz: ignora
    assert names("abre", at=datetime(2026, 10, 3, 5, 0, tzinfo=UTC)) == {"late"}  # 2h em SP


def test_signals_repeat() -> None:
    prev = T0 - timedelta(seconds=60)
    assert names("como passa do boss", previous_text="como passa do boss?", previous_at=prev) == {"repeat"}
    old = T0 - timedelta(minutes=10)
    assert names("como passa do boss", previous_text="como passa do boss", previous_at=old) == set()


# -- nota ----------------------------------------------------------------------------------------


def test_bad_signals_lower_and_good_raise_smoothly() -> None:
    clock = Clock()
    t = MoodTracker(now=clock)
    assert t.level() == 2
    run(t.observe("porra, que merda", ctx()))
    first = t.score()
    assert 1.4 < first < 2.0  # suavizado: um palavrão só não derruba de vez
    for _ in range(4):
        run(t.observe("porra, que raiva, não aguento", ctx(tone=ToneMetadata(-5.0, 8.0, 900))))
    assert t.level() == 0
    for _ in range(8):
        run(t.observe("kkkk valeu, mandou bem", ctx()))
    assert t.level() >= 3


def test_neutral_turns_drift_back_and_time_decays() -> None:
    clock = Clock()
    t = MoodTracker(now=clock)
    for _ in range(6):
        run(t.observe("kkkk boa", ctx()))
    high = t.score()
    assert high > 3.0
    clock.advance(hours=1)
    assert abs((t.score() - 2) - (high - 2) / 2) < 1e-9  # meia-vida de 1 h
    clock.advance(hours=6)
    assert t.level() == 2


def test_hud_receives_mood_only_on_change() -> None:
    hud = FakeHud()
    t = MoodTracker(hud=hud, now=Clock())
    run(t.observe("abre o Steam", ctx()))
    run(t.observe("abre o Steam", ctx()))
    assert hud.sent == [MoodMsg(2)]
    for _ in range(5):
        run(t.observe("porra, que merda, que raiva", ctx()))
    assert [m.v for m in hud.sent] == sorted({m.v for m in hud.sent}, reverse=True)
    assert hud.sent[-1] == MoodMsg(t.level())


# -- comandos -----------------------------------------------------------------------------------


def test_soften_caps_for_hours_and_learns() -> None:
    clock = Clock()
    events = FakeEvents()
    t = MoodTracker(events=events, now=clock)
    for _ in range(6):
        run(t.observe("kkkk boa", ctx()))
    assert t.level() >= 3
    assert run(t.soften()) <= mood.SOFT_CAP
    for _ in range(5):
        run(t.observe("kkkk valeu", ctx()))
    assert t.level() <= mood.SOFT_CAP  # teto vale mesmo com risada
    assert events.events[-1].signal == "explicit" and events.events[-1].value == -1.0
    assert t.state.bias == -mood.BIAS_STEP
    clock.advance(seconds=mood.OVERRIDE_S + 1)
    for _ in range(5):
        run(t.observe("kkkk valeu", ctx()))
    assert t.level() >= 2  # passou o prazo: volta a subir


def test_harden_floors_and_replaces_soften() -> None:
    clock = Clock()
    t = MoodTracker(now=clock)
    run(t.soften())
    assert run(t.harden()) >= mood.HARD_FLOOR
    assert t.state.cap is None
    for _ in range(4):
        run(t.observe("porra que merda", ctx()))
    assert t.level() >= mood.HARD_FLOOR
    assert t.state.bias == 0.0  # -0,25 + 0,25


def test_handler_routes_intents() -> None:
    t = MoodTracker(now=Clock())
    h = MoodHandler(t)
    res = run(h.run(ActionRequest(Intent(IntentId.MOOD_SOFTER.value, reply="Tá, vou maneirar."), ctx())))
    assert res.ok and res.speech == "Tá, vou maneirar."
    assert t.level() <= 1
    res = run(h.run(ActionRequest(Intent(IntentId.MOOD_HARDER.value), ctx())))
    assert res.speech == mood.SAY_HARDER and t.level() >= 3


# -- persistência e turno -------------------------------------------------------------------------


def test_state_survives_restart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "mood.json"
    clock = Clock()
    t = MoodTracker(path, now=clock)
    run(t.soften())
    run(t.observe("que merda", ctx()))
    again = MoodTracker(path, now=clock)
    assert again.state == t.state and again.level() == t.level() <= 1
    path.write_text("lixo")
    assert MoodTracker(path, now=clock).level() == 2


def test_pipeline_puts_level_in_ctx() -> None:
    seen: list[int] = []

    class Agent:
        async def answer(self, text: str, c: TurnContext):  # type: ignore[no-untyped-def]
            from magi.common.contracts import ActionResult

            seen.append(c.mood)
            return ActionResult(ok=True, speech="ok")

    from magi.common.contracts import Transcript

    t = MoodTracker(now=Clock())
    t.state = mood.MoodState(score=0.2, at=T0)
    pipe = TurnPipeline(TurnDeps(agent=Agent(), mood=t))  # type: ignore[arg-type]
    run(pipe.respond(Transcript.raw("quem ganhou o jogo?"), ctx()))
    assert seen == [1] == [t.level()]  # 0,7·0,2 + 0,3·2 = 0,74
