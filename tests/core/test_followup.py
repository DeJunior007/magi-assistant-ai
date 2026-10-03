"""Tarefa 1.20: conversa contínua (janela de continuação) com satélite, HUD e fala falsos."""

from __future__ import annotations

import asyncio

from wyoming.audio import AudioChunk, AudioStart

from magi.common.contracts import (
    CHUNK_SAMPLES,
    ActionResult,
    AudioEnd,
    AudioEndReason,
    Expression,
    ListenRequest,
    PlaybackDone,
    SatelliteHello,
    SatelliteStatus,
    StateMsg,
    ToneMetadata,
    Transcript,
    TurnState,
    WakeEvent,
    WakeSource,
)
from magi.core.turn import (
    SAY_NOT_HEARD,
    TurnDeps,
    TurnMachine,
    TurnPipeline,
    followup_ms_from_config,
    is_dismissal,
)

VOICE = ToneMetadata(energy_db=-20.0, speech_rate=4.0, duration_ms=900)


class Link:
    hello = SatelliteHello(satellite="pc")

    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, msg) -> None:
        self.sent.append(msg)

    async def play(self, audio, fmt) -> None:
        pass

    def listens(self) -> list[ListenRequest]:
        return [m for m in self.sent if isinstance(m, ListenRequest)]


class Hud:
    def __init__(self) -> None:
        self.msgs: list[object] = []

    async def send(self, msg) -> None:
        self.msgs.append(msg)

    def faces(self) -> list[str]:
        return [m.v for m in self.msgs if isinstance(m, StateMsg)]


class Stt:
    """O "áudio" é o próprio texto em UTF-8."""

    name = model = "fake"
    free_tier = False

    async def transcribe(self, audio, fmt, *, hint="", language="pt", personal: bool) -> Transcript:
        return Transcript.raw(audio.decode("utf-8").strip())


class Agent:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def answer(self, text, ctx) -> ActionResult:
        self.asked.append(text)
        return ActionResult(ok=True, speech=f"Resposta {len(self.asked)}.")


class Speaker:
    def __init__(self) -> None:
        self.said: list[str] = []

    async def say(self, text, link, *, personal: bool) -> None:
        self.said.append(text)


class Rig:
    def __init__(self, followup_ms: int | None = 3_000) -> None:
        self.link, self.hud, self.agent, self.speaker = Link(), Hud(), Agent(), Speaker()
        deps = TurnDeps(stt=Stt(), agent=self.agent, speaker=self.speaker)
        self.m = TurnMachine(self.link, self.hud, TurnPipeline(deps), followup_ms=followup_ms,
                             confirm_grace_ms=50, dismiss_face_s=0.01)

    async def settle(self) -> None:
        for _ in range(5):
            await asyncio.sleep(0)
        if self.m._task is not None:
            await asyncio.wait_for(asyncio.shield(self.m._task), 2)

    async def record(self, text: str, reason: AudioEndReason = AudioEndReason.VAD) -> None:
        """Gravação vinda do satélite (após wake/PTT ou dentro da janela)."""
        await self.m.handle(AudioStart(rate=16_000, width=2, channels=1))
        if text:
            await self.m.handle(AudioChunk(rate=16_000, width=2, channels=1, audio=text.encode()))
        await self.m.handle(AudioEnd(reason=reason, tone=VOICE if text else None))
        await self.settle()

    async def turn(self, text: str) -> None:
        """Ativação + fala + fim da reprodução."""
        await self.m.handle(WakeEvent(source=WakeSource.WAKE, satellite="pc"))
        await self.record(text)
        await self.m.handle(PlaybackDone())


async def test_continuacao_aceita_fala_sem_wake_e_reabre() -> None:
    r = Rig()
    await r.turn("que horas são")
    assert r.m.state is TurnState.FOLLOWUP
    assert r.link.listens() == [ListenRequest(timeout_ms=3_000, reason="followup")]
    assert r.hud.faces()[-1] == Expression.LISTENING  # rosto "ouvindo" durante a janela
    # fala na janela, sem WakeEvent: turno normal completo
    await r.record("e amanhã")
    assert r.agent.asked == ["que horas são", "e amanhã"]
    assert r.m.state is TurnState.SPEAKING
    await r.m.handle(PlaybackDone())
    assert r.m.state is TurnState.FOLLOWUP and len(r.link.listens()) == 2
    await r.m.close()


async def test_silencio_na_janela_dorme_calado() -> None:
    r = Rig()
    await r.turn("oi")
    await r.record("", AudioEndReason.NO_SPEECH)
    assert r.m.state is TurnState.SLEEPING
    assert r.speaker.said == ["Resposta 1."]  # nada de "Cancelado." nem "não peguei"
    # ruído que o STT não entende também não fala nada na janela
    await r.turn("oi")
    await r.record("   ")
    assert r.m.state is TurnState.SLEEPING and SAY_NOT_HEARD not in r.speaker.said


async def test_prazo_de_seguranca_sem_satelite() -> None:
    r = Rig(followup_ms=20)
    await r.turn("oi")
    assert r.m.state is TurnState.FOLLOWUP
    await asyncio.sleep(0.2)  # satélite nunca respondeu à escuta
    assert r.m.state is TurnState.SLEEPING


async def test_dispensa_na_janela_e_em_turno_normal() -> None:
    r = Rig()
    await r.turn("oi")
    await r.record("Valeu, Magui!")
    assert r.m.state is TurnState.SLEEPING
    assert r.agent.asked == ["oi"] and r.speaker.said == ["Resposta 1."]
    assert r.hud.faces()[-2:] == [Expression.HAPPY, Expression.SLEEPING]
    await r.m.handle(WakeEvent(source=WakeSource.PTT, satellite="pc"))
    await r.record("só isso")
    assert r.m.state is TurnState.SLEEPING and r.agent.asked == ["oi"]


def test_frases_de_dispensa() -> None:
    for t in ("valeu", "Obrigado.", "só isso", "pode ir", "dispensa", "tchau", "nada não", "esquece",
              "valeu, Condessa", "Valeu, condessa!", "tchau, Magui", "oi condessa, só isso"):
        assert is_dismissal(t), t
    for t in ("valeu a pena?", "esquece isso", "tchau pro jogo", "", "magui", "condessa", "oi condessa"):
        assert not is_dismissal(t), t


async def test_em_call_sem_janela() -> None:
    r = Rig()
    await r.m.handle(SatelliteStatus(satellite="pc", in_call=True))
    await r.turn("oi")
    assert r.m.state is TurnState.SLEEPING and r.link.listens() == []


async def test_desligada_e_aviso_proativo_nao_abrem_janela() -> None:
    r = Rig(followup_ms=None)
    await r.turn("oi")
    assert r.m.state is TurnState.SLEEPING
    r = Rig()
    assert await r.m.announce("CPU quente.")
    await r.settle()
    await r.m.handle(PlaybackDone())
    assert r.m.state is TurnState.SLEEPING and r.link.listens() == []


async def test_nova_ativacao_durante_a_janela() -> None:
    r = Rig()
    await r.turn("oi")
    await r.m.handle(AudioStart(rate=16_000, width=2, channels=1))  # escuta da janela aberta
    # PTT: o satélite cancela a escuta e manda o wake
    await r.m.handle(AudioEnd(reason=AudioEndReason.CANCELLED))
    assert r.m.state is TurnState.SLEEPING
    await r.m.handle(WakeEvent(source=WakeSource.PTT, satellite="pc"))
    assert r.m.state is TurnState.LISTENING
    await r.record("abre o jogo")
    assert r.agent.asked == ["oi", "abre o jogo"]
    # wake direto na janela (sem audio-stop antes) também começa a ouvir
    await r.m.handle(PlaybackDone())
    assert r.m.state is TurnState.FOLLOWUP
    await r.m.handle(WakeEvent(source=WakeSource.WAKE, satellite="pc"))
    assert r.m.state is TurnState.LISTENING
    await r.m.close()


async def test_ativou_e_nao_falou_dorme_calado() -> None:
    r = Rig()
    await r.m.handle(WakeEvent(source=WakeSource.PTT, satellite="pc"))
    await r.m.handle(AudioStart(rate=16_000, width=2, channels=1))
    await r.m.handle(AudioChunk(rate=16_000, width=2, channels=1, audio=bytes(CHUNK_SAMPLES * 2)))
    await r.m.handle(AudioEnd(reason=AudioEndReason.PTT_RELEASE, tone=ToneMetadata(-120.0, 0.0, 0)))
    await r.settle()
    assert r.m.state is TurnState.SLEEPING and r.speaker.said == []


def test_config() -> None:
    assert followup_ms_from_config(None) == 3_000
    assert followup_ms_from_config({"conversation": {"followup_s": 2.5}}) == 2_500
    assert followup_ms_from_config({"conversation": {"followup": False}}) is None
    assert followup_ms_from_config({"conversation": {"followup_s": 0}}) is None
