"""Sugestão de música ao abrir jogo (5.4)."""

from __future__ import annotations

from dataclasses import dataclass

from magi.common.contracts import ActionResult
from magi.core.game_context import GameEvent, RunningGame
from magi.core.proactive.music import GameClass, MusicSuggester, classify
from magi.core.proactive.sink import Outcome

RACING = RunningGame(
    "Horizon Chase",
    1,
    0.0,
    389140,
    ("Racing",),
    ("Single-player", "Online PvP"),
    ("Racing", "Arcade", "Retro"),
)
RPG = RunningGame("Elden Ring", 2, 0.0, 1245620, ("Action", "RPG"), ("Single-player",), ("Souls-like", "RPG"))
CS = RunningGame(
    "Counter-Strike 2", 3, 0.0, 730, ("Action",), ("Multi-player", "Online PvP"), ("FPS", "Shooter")
)
PVP_TAG = RunningGame("Rocket League", 4, 0.0, 252950, ("Racing", "Sports"), (), ("Racing", "Competitive"))


@dataclass
class State:
    playing: bool


class FakeSink:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.call = False

    def in_call(self) -> bool:
        return self.call

    async def deliver(self, kind, speech, card=None, priority=None, *, expression=None, offer=None):
        self.calls.append((kind, speech, offer))
        return Outcome.QUEUED


class FakePlayer:
    def __init__(self, playing: bool = False, fail: bool = False) -> None:
        self.playing, self.fail = playing, fail

    async def state(self) -> State:
        if self.fail:
            raise RuntimeError("Spotify fechado")
        return State(self.playing)


class FakePicker:
    def __init__(self) -> None:
        self.picks = 0

    async def pick(self) -> ActionResult:
        self.picks += 1
        return ActionResult(ok=True, speech="Coloquei uma.")


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _make(player=None):
    sink, picker, clock = FakeSink(), FakePicker(), Clock()
    return MusicSuggester(sink, picker, player or FakePlayer(), clock=clock), sink, picker, clock


def opened(game: RunningGame) -> GameEvent:
    return GameEvent("opened", game, 0.0)


def closed(game: RunningGame) -> GameEvent:
    return GameEvent("closed", game, 0.0)


def test_classifica_pelas_tags() -> None:
    assert classify(RACING) is GameClass.CASUAL
    assert classify(RPG) is GameClass.IMMERSIVE
    assert classify(CS) is GameClass.COMPETITIVE
    assert classify(PVP_TAG) is GameClass.COMPETITIVE
    assert classify(RunningGame("x", 5, 0.0)) is GameClass.UNKNOWN


async def test_jogo_de_corrida_sugere() -> None:
    s, sink, _, _ = _make()
    assert await s.on_game(opened(RACING))
    kind, speech, offer = sink.calls[0]
    assert kind == "music" and speech == "Quer um som pra acompanhar o Horizon Chase?"
    assert offer is not None


async def test_rpg_e_competitivo_nunca() -> None:
    s, sink, _, _ = _make()
    for game in (RPG, CS, PVP_TAG, RunningGame("Sem tags", 9, 0.0)):
        assert not await s.on_game(opened(game))
    assert sink.calls == []


async def test_uma_vez_por_sessao_e_intervalo_global() -> None:
    s, sink, _, clock = _make()
    s.interval_s = 0.0
    assert await s.on_game(opened(RACING))
    assert not await s.on_game(opened(RACING))  # mesma sessão
    await s.on_game(closed(RACING))
    s.interval_s = 3 * 3600.0
    clock.t += 3600
    assert not await s.on_game(opened(RACING))  # nova sessão, mas sugeri há 1 h
    clock.t += 3 * 3600
    assert await s.on_game(opened(RACING))
    assert len(sink.calls) == 2


async def test_musica_tocando_ou_call_nao_sugere() -> None:
    s, sink, _, _ = _make(FakePlayer(playing=True))
    assert not await s.on_game(opened(RACING))
    s.player = FakePlayer(fail=True)  # Spotify fechado = nada tocando
    sink.call = True
    assert not await s.on_game(opened(RACING))
    sink.call = False
    assert await s.on_game(opened(RACING))


async def test_aceitar_chama_o_picker_e_recusa_segura() -> None:
    s, sink, picker, clock = _make()
    await s.on_game(opened(RACING))
    offer = sink.calls[0][2]
    result = await offer.accept()
    assert picker.picks == 1 and result.speech == "Coloquei uma."

    offer.decline()
    await s.on_game(closed(RACING))
    clock.t += 4 * 3600  # passou o intervalo global, mas a recusa (12 h) ainda vale
    assert not await s.on_game(opened(RACING))
    clock.t += 9 * 3600
    assert await s.on_game(opened(RACING))
