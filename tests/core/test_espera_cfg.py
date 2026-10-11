"""Espera viva E0.1: ``[espera]`` (spec §5) e o gancho ``THINK_HUD`` (design §4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from magi.common.config import ConfigError
from magi.common.contracts import (
    ActionResult,
    PcmFormat,
    SatelliteHello,
    ThinkMsg,
    Transcript,
    TurnContext,
    TurnState,
    WakeSource,
)
from magi.core.early import THINK_HUD, notify_lote, notify_tool, notify_wait
from magi.core.espera import EsperaCfg
from magi.core.turn import TurnDeps, TurnMachine, TurnPipeline

FMT = PcmFormat(rate=24_000)
CTX = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC))


class FakeStt:
    async def transcribe(self, audio, fmt, *, hint="", language="pt", personal):
        return Transcript.raw("o que saiu de notícia hoje")


class FakeLink:
    hello = SatelliteHello("pc")

    async def send(self, msg: object) -> None:
        pass


class FakeHud:
    def __init__(self) -> None:
        self.msgs: list[object] = []

    async def send(self, msg) -> None:
        self.msgs.append(msg)


def test_padroes_sem_secao() -> None:
    for raw in (None, {}):
        cfg = EsperaCfg.from_raw(raw)
        assert cfg == EsperaCfg()
    cfg = EsperaCfg()
    assert cfg.frase and cfg.so_demorado and cfg.lotes and cfg.ferramentas_paralelo
    assert (cfg.frase_apos_ms, cfg.lotes_max, cfg.lotes_frases_max) == (700, 3, 6)


def test_le_valores() -> None:
    cfg = EsperaCfg.from_raw(
        {"frase": False, "so_demorado": False, "frase_apos_ms": 900, "lotes": False,
         "lotes_max": 2, "lotes_frases_max": 4, "ferramentas_paralelo": False}
    )
    assert cfg == EsperaCfg(False, False, 900, False, 2, 4, False)


@pytest.mark.parametrize(
    ("raw", "chave"),
    [
        ({"frase": "sim"}, "frase"),
        ({"so_demorado": 1}, "so_demorado"),
        ({"frase_apos_ms": -1}, "frase_apos_ms"),
        ({"frase_apos_ms": 7.5}, "frase_apos_ms"),
        ({"frase_apos_ms": True}, "frase_apos_ms"),
        ({"lotes_max": 0}, "lotes_max"),
        ({"lotes_frases_max": 1}, "lotes_frases_max"),
        ({"ferramentas_paralelo": "true"}, "ferramentas_paralelo"),
        ({"frase_depois": 700}, "frase_depois"),
    ],
)
def test_invalido_da_config_error_com_a_chave(raw: dict, chave: str) -> None:
    with pytest.raises(ConfigError, match=chave):
        EsperaCfg.from_raw(raw)


def test_secao_que_nao_e_tabela() -> None:
    with pytest.raises(ConfigError):
        EsperaCfg.from_raw(["frase"])  # type: ignore[arg-type]


def test_avisos_sem_gancho_nao_fazem_nada() -> None:
    assert THINK_HUD.get() is None
    notify_wait()
    notify_tool("search")
    notify_lote(1)


def test_avisos_com_gancho_e_gancho_que_falha() -> None:
    got: list[ThinkMsg] = []
    token = THINK_HUD.set(got.append)
    try:
        notify_wait()
        notify_tool("nao_existe")
        notify_lote(2)
    finally:
        THINK_HUD.reset(token)
    assert got == [ThinkMsg("wait"), ThinkMsg("tool", tool="other"), ThinkMsg("lote", n=2)]

    def boom(msg: ThinkMsg) -> None:
        raise RuntimeError("hud caiu")

    token = THINK_HUD.set(boom)
    try:
        notify_tool("search")  # não propaga
    finally:
        THINK_HUD.reset(token)


async def test_notify_tool_dentro_do_think_chega_ao_hud() -> None:
    hud = FakeHud()
    m = TurnMachine(FakeLink(), hud, TurnPipeline(TurnDeps(stt=FakeStt())))
    m._state = TurnState.THINKING  # como depois do audio-stop
    seen: list[object] = []

    async def respond(transcript, ctx):
        notify_tool("news_query")
        seen.append(THINK_HUD.get())
        return ActionResult(ok=True, speech="Pronto.")

    m.pipeline.respond = respond  # type: ignore[method-assign]
    m._start(m._think(b"\0\0", FMT, CTX))
    await asyncio.wait_for(m._task, 1)
    await asyncio.sleep(0)
    assert seen and seen[0] is not None
    assert ThinkMsg("tool", tool="news_query") in hud.msgs
    assert THINK_HUD.get() is None  # fechado no fim do turno
