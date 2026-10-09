"""R2.B: tag local do turno (sem LLM) e envio ao HUD pelo ``MoodTracker``."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from magi.common.contracts import MoodMsg, ToneMetadata, TurnContext, TurnTagMsg, WakeSource
from magi.memory.mood import MoodTracker
from magi.memory.turn_tag import SUSSURRO_DB, classify

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


# -- R2.F: voz baixa ------------------------------------------------------------------------------

BAIXO = ToneMetadata(energy_db=SUSSURRO_DB - 5, speech_rate=4.0, duration_ms=1200)
NORMAL = ToneMetadata(energy_db=-20.0, speech_rate=4.0, duration_ms=1200)


def test_voz_baixa_vira_sussurro() -> None:
    assert classify("abre o Steam", BAIXO) == "sussurro"
    assert classify("", BAIXO) == "sussurro"
    assert classify("abre o Steam", NORMAL) is None
    assert classify("abre o Steam", ToneMetadata(SUSSURRO_DB, 4.0, 1200)) is None  # no limiar não
    assert classify("abre o Steam", ToneMetadata(-60.0, 4.0, 0)) is None  # sem voz medida
    assert classify("abre o Steam", None) is None


def test_palavra_vale_mais_que_o_tom() -> None:
    assert classify("valeu, mandou bem", BAIXO) == "elogio"
    assert classify("kkkk", BAIXO) == "zoeira"
    assert classify("não foi isso", BAIXO) == "correcao"


def test_tracker_manda_sussurro() -> None:
    hud = FakeHud()
    t = MoodTracker(hud=hud, now=lambda: T0)
    c = TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=T0, tone=BAIXO)
    asyncio.run(t.observe("que horas são", c))
    assert hud.sent[-1] == TurnTagMsg("sussurro")


def test_88_dispara_com_a_tag() -> None:
    from types import SimpleNamespace

    from hud.wired.reacoes import det_conversa
    from hud.wired.reacoes.catalogo import ATIVAS, DEFS

    snap = SimpleNamespace(turn_tag=("sussurro", 100.0))
    out = det_conversa.detectar(None, snap, {"agora": 101.0})
    assert [d.chave for d in out] == ["sussurro"]
    assert "sussurro" in ATIVAS and DEFS["sussurro"].sinal is None
