"""``TurnMachine.narrate`` (audiolivro A2.2, CA-A7): satélite, HUD, TTS e leitura falsos."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from magi.common.contracts import (
    ARG_NARRATE,
    ActionRequest,
    ActionResult,
    Intent,
    ListenRequest,
    PlaybackDone,
    SatelliteStatus,
    StopPlayback,
    SubtitleMsg,
    TurnContext,
    TurnState,
    WakeSource,
)
from magi.core.turn import READING_CALL_CAPTION, TurnDeps, TurnMachine, TurnPipeline


class Link:
    def __init__(self) -> None:
        self.hello = SimpleNamespace(satellite="pc")
        self.sent: list[Any] = []

    async def send(self, msg: Any) -> None:
        self.sent.append(msg)

    async def play(self, pcm: Any, fmt: Any) -> None:
        async for _ in pcm:
            pass


class Hud:
    def __init__(self) -> None:
        self.msgs: list[Any] = []

    async def send(self, msg: Any) -> None:
        self.msgs.append(msg)


class Speaker:
    """``say_parts`` avisa ``on_sentence`` por parte; ``liberar`` = quantas partes podem tocar."""

    def __init__(self) -> None:
        self.said: list[str] = []
        self.parts_calls: list[Any] = []
        self.liberar = 10**6
        self.andou = asyncio.Event()

    async def say(self, text: str, link: Any, *, personal: bool) -> None:
        self.said.append(text)

    async def say_parts(
        self, parts: Any, link: Any, *, personal: bool, on_sentence: Any, provider: Any
    ) -> None:
        self.parts_calls.append(provider)
        i = 0
        async for texto, _op in parts:
            while i >= self.liberar:
                await asyncio.sleep(0.001)
            on_sentence(texto, None, i)
            i += 1
            self.andou.set()


class FakeLeitura:
    def __init__(self, n: int = 5) -> None:
        self.n = n
        self.estado = "pausada"
        self.tts = object()
        self.tocadas: list[int] = []
        self.pausas = 0

    async def partes(self) -> Any:
        self.estado = "lendo"
        for k in range(self.n):
            yield f"frase {k}", None
        self.estado = "parada"

    def tocando(self, i: int) -> None:
        self.tocadas.append(i)

    def interrompida(self) -> None:
        self.pausas += 1
        self.estado = "pausada"


@pytest.fixture
def rig() -> SimpleNamespace:
    link, hud, speaker = Link(), Hud(), Speaker()
    tm = TurnMachine(link, hud, TurnPipeline(TurnDeps(speaker=speaker)), followup_ms=5000)
    return SimpleNamespace(tm=tm, link=link, hud=hud, speaker=speaker)


async def _ate(cond: Any) -> None:
    for _ in range(500):
        if cond():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("condição não chegou")


def _resultado(tm: TurnMachine, alvo: Any = None) -> ActionResult:
    if alvo is None:
        return ActionResult(ok=True, speech="Beleza.")
    ctx = TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime.now(UTC))
    req = ActionRequest(intent=Intent(id="book.back"), ctx=ctx, args={ARG_NARRATE: alvo})
    return ActionResult(ok=True, speech="Voltei um parágrafo.", on_confirm=req)


async def _responde(r: SimpleNamespace, result: ActionResult) -> None:
    r.tm._state = TurnState.THINKING  # como depois do ``_think``
    await r.tm._deliver(result)
    await r.tm.handle(PlaybackDone())


async def test_wake_pausa_na_frase_e_comando_de_leitura_retoma(rig: SimpleNamespace) -> None:
    leitura = FakeLeitura()
    rig.speaker.liberar = 2
    assert await rig.tm.narrate(leitura)
    assert rig.tm.state is TurnState.SPEAKING
    await _ate(lambda: len(leitura.tocadas) == 2)
    assert rig.speaker.parts_calls == [leitura.tts]  # TTS do livro (Kokoro)

    await rig.tm.wake()
    assert leitura.pausas == 1 and leitura.tocadas == [0, 1]
    assert any(isinstance(m, StopPlayback) for m in rig.link.sent)
    assert rig.tm.state is TurnState.LISTENING
    assert rig.tm._make_ctx(None).reading is leitura

    rig.speaker.liberar = 10**6
    await _responde(rig, _resultado(rig.tm, True))
    assert rig.speaker.said == ["Voltei um parágrafo."]
    await _ate(lambda: len(rig.speaker.parts_calls) == 2)  # retomou sozinha
    assert not any(isinstance(m, ListenRequest) for m in rig.link.sent)  # sem continuação
    await _ate(lambda: leitura.estado == "parada")
    await rig.tm.handle(PlaybackDone())
    assert rig.tm.state is TurnState.SLEEPING
    assert not any(isinstance(m, ListenRequest) for m in rig.link.sent)
    assert rig.tm.reading is None


async def test_outro_assunto_nao_retoma(rig: SimpleNamespace) -> None:
    leitura = FakeLeitura()
    rig.speaker.liberar = 1
    await rig.tm.narrate(leitura)
    await _ate(lambda: leitura.tocadas == [0])
    await rig.tm.wake()
    await _responde(rig, _resultado(rig.tm))
    assert len(rig.speaker.parts_calls) == 1
    assert leitura.estado == "pausada" and rig.tm.reading is leitura
    assert rig.tm.state is TurnState.FOLLOWUP  # turno comum segue normal


async def test_leitura_explicita_no_resultado_abre_narracao(rig: SimpleNamespace) -> None:
    leitura = FakeLeitura(2)
    await _responde(rig, _resultado(rig.tm, leitura))
    await _ate(lambda: leitura.tocadas == [0, 1])
    assert rig.tm.state is TurnState.SPEAKING and rig.tm.reading is None  # já acabou: parada


async def test_aviso_proativo_nao_fala_no_meio(rig: SimpleNamespace) -> None:
    leitura = FakeLeitura()
    rig.speaker.liberar = 1
    await rig.tm.narrate(leitura)
    await _ate(lambda: leitura.tocadas == [0])
    assert await rig.tm.announce("Notícia nova.") is False
    assert rig.speaker.said == []


async def test_call_pausa_e_avisa_por_legenda(rig: SimpleNamespace) -> None:
    leitura = FakeLeitura()
    rig.speaker.liberar = 1
    await rig.tm.narrate(leitura)
    await _ate(lambda: leitura.tocadas == [0])
    await rig.tm.handle(SatelliteStatus(satellite="pc", in_call=True))
    assert leitura.pausas == 1 and rig.tm.state is TurnState.SLEEPING
    assert any(isinstance(m, SubtitleMsg) and m.text == READING_CALL_CAPTION for m in rig.hud.msgs)
    assert rig.speaker.said == []  # só legenda
    assert await rig.tm.narrate(leitura) is False  # em call não começa (A8.4)
    await _responde(rig, _resultado(rig.tm, True))
    assert len(rig.speaker.parts_calls) == 1


async def test_sem_say_parts_nao_narra() -> None:
    tm = TurnMachine(Link(), Hud(), TurnPipeline(TurnDeps(speaker=SimpleNamespace())))
    assert await tm.narrate(FakeLeitura()) is False
    assert tm.state is TurnState.SLEEPING
