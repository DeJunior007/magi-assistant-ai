"""R2.B: tag local do turno (sem LLM) e envio ao HUD pelo ``MoodTracker``."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from magi.common.contracts import MoodMsg, TurnContext, TurnTagMsg, WakeSource
from magi.memory.mood import MoodTracker
from magi.memory.turn_tag import classify

T0 = datetime(2026, 10, 9, 15, 0, tzinfo=UTC)


class FakeHud:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, msg: object) -> None:
        self.sent.append(msg)


def ctx() -> TurnContext:
    return TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=T0)


@pytest.mark.parametrize(
    ("frase", "tag"),
    [
        ("Valeu, mandou bem!", "elogio"),
        ("você é muito inteligente, Condessa", "elogio"),
        ("perfeito, era isso", "elogio"),
        ("kkkkkk que isso", "zoeira"),
        ("hahaha para", "zoeira"),
        ("não, eu falei o Spotify", "correcao"),
        ("não foi isso que eu pedi", "correcao"),
        ("para de zoar, sem graça", "correcao"),
        ("kkk mandou bem", "elogio"),
        ("abre o Steam", None),
        ("que horas são?", None),
        ("boa noite, Condessa", None),
        ("", None),
    ],
)
def test_classifica_frases(frase: str, tag: str | None) -> None:
    assert classify(frase) == tag


def test_contrato_valida_tag() -> None:
    assert TurnTagMsg("elogio").to_json() == '{"t":"turn_tag","v":"elogio"}'
    with pytest.raises(ValueError):
        TurnTagMsg("bravo")


def test_tracker_manda_tag_so_com_sinal() -> None:
    hud = FakeHud()
    t = MoodTracker(hud=hud, now=lambda: T0)
    asyncio.run(t.observe("abre o Steam", ctx()))
    assert hud.sent == [MoodMsg(2)]
    asyncio.run(t.observe("valeu, mandou bem", ctx()))
    assert hud.sent[-1] == TurnTagMsg("elogio")
    asyncio.run(t.observe("kkkk", ctx()))
    assert hud.sent[-1] == TurnTagMsg("zoeira")
    assert [m for m in hud.sent if isinstance(m, TurnTagMsg)] == [TurnTagMsg("elogio"), TurnTagMsg("zoeira")]
