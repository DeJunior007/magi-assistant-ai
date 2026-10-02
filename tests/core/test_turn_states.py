"""Tarefa 1.4: núcleo com satélite falso (Wyoming em porta efêmera) e HUD falso (socket Unix)."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from wyoming.event import Event, async_read_event, async_write_event

from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    AudioEnd,
    AudioEndReason,
    CmdMsg,
    EventType,
    Expression,
    HudMessage,
    Intent,
    IntentId,
    MouthEvent,
    MouthMsg,
    PcmFormat,
    PlaybackDone,
    ProviderError,
    RouteKind,
    RouteResult,
    SatelliteHello,
    SatelliteLink,
    StateMsg,
    SubtitleMsg,
    ToneMetadata,
    Transcript,
    TurnContext,
    TurnState,
    Verdict,
    VoteMsg,
    WakeEvent,
    WakeSource,
)
from magi.common.events import audio_chunk, audio_start, decode_hud, encode_hud_line, to_event
from magi.core.hud_client import HudServer
from magi.core.service import CoreService
from magi.core.turn import SAY_CANCELLED, SAY_NOT_HEARD, SAY_UNAVAILABLE, TurnDeps, TurnPipeline

T = 3.0  # prazo de cada espera nos testes (s)
VOICE = PcmFormat(rate=22_050)

# ---------------------------------------------------------------------------------------------
# Implementações falsas dos protocolos
# ---------------------------------------------------------------------------------------------


class FakeStt:
    """Devolve o texto "falado": o satélite falso manda o texto como PCM (UTF-8)."""

    name = "fake"
    model = "fake"
    free_tier = False

    def __init__(self) -> None:
        self.gate: asyncio.Event | None = None
        self.cancelled = False
        self.fail = False

    async def transcribe(
        self, audio: bytes, fmt: PcmFormat, *, hint: str = "", language: str = "pt", personal: bool
    ) -> Transcript:
        assert personal is True
        if self.gate is not None:
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        if self.fail:
            raise ProviderError("caiu")
        return Transcript.raw(audio.decode("utf-8").strip())


class FakeCorrector:
    async def apply(self, transcript: Transcript) -> Transcript:
        return transcript.with_final(transcript.heard.replace("magui", "Magui"))


class FakeRouter:
    def route(self, text: str, ctx: TurnContext) -> RouteResult:
        t = text.lower()
        if t.startswith("abre"):
            return RouteResult(RouteKind.LOCAL, text, 95, Intent(IntentId.GAME_OPEN))
        if t.startswith("fecha"):
            return RouteResult(RouteKind.LOCAL, text, 95, Intent(IntentId.GAME_CLOSE, danger=True))
        if t.startswith("abri"):
            return RouteResult(RouteKind.ASK, text, 80, Intent(IntentId.GAME_OPEN), "Abrir o jogo?")
        if t == "confirma":
            return RouteResult(RouteKind.LOCAL, text, 100, Intent(IntentId.CONFIRM_YES))
        if t == "cancela":
            return RouteResult(RouteKind.LOCAL, text, 100, Intent(IntentId.CONFIRM_NO))
        return RouteResult(RouteKind.AGENT, text)


class FakeActions:
    def __init__(self) -> None:
        self.calls: list[ActionRequest] = []

    def register(self, handler: object) -> None:  # pragma: no cover - não usado
        raise NotImplementedError

    def handles(self, intent_id: str) -> bool:
        return intent_id in (IntentId.GAME_OPEN, IntentId.GAME_CLOSE)

    async def run(self, req: ActionRequest) -> ActionResult:
        self.calls.append(req)
        if req.intent.id == IntentId.GAME_OPEN:
            return ActionResult(ok=True, speech="Abrindo.", expression=Expression.HAPPY)
        if not req.confirmed:
            return ActionResult(
                ok=True,
                speech="Fechar o jogo? Diz confirma.",
                needs_confirmation=True,
                dangerous=True,
                on_confirm=replace(req, confirmed=True),
            )
        return ActionResult(ok=True, speech="Fechado.")


class FakeAgent:
    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        return ActionResult(ok=True, speech="Resposta curta.", full_text=f"Resposta completa para: {text}")


class FakeSpeaker:
    """Fala mandando 2 blocos de PCM; com ``hold``, para no meio do envio até ser cancelado."""

    def __init__(self) -> None:
        self.said: list[str] = []
        self.hold = False
        self.cancelled = False

    async def say(self, text: str, link: SatelliteLink, *, personal: bool) -> None:
        self.said.append(text)

        async def pcm() -> AsyncIterator[bytes]:
            yield b"\x01\x00" * 400
            if self.hold:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            yield b"\x02\x00" * 400

        await link.play(pcm(), VOICE)


# ---------------------------------------------------------------------------------------------
# Satélite e HUD falsos
# ---------------------------------------------------------------------------------------------


class Sat:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    @classmethod
    async def connect(cls, port: int, satellite: str = "pc", hello: bool = True) -> Sat:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        sat = cls(reader, writer)
        if hello:
            await sat.send(SatelliteHello(satellite=satellite))
        return sat

    async def send(self, msg: object) -> None:
        event = msg if isinstance(msg, Event) else to_event(msg)  # type: ignore[arg-type]
        await async_write_event(event, self.writer)

    async def wake(self, source: WakeSource = WakeSource.WAKE) -> None:
        await self.send(WakeEvent(source=source, satellite="pc", score=0.9))

    async def speak(self, text: str, reason: AudioEndReason = AudioEndReason.VAD) -> None:
        await self.send(audio_start())
        if text:
            await self.send(audio_chunk(text.encode("utf-8")))
        await self.send(AudioEnd(reason=reason, tone=ToneMetadata(energy_db=-20.0, speech_rate=4.0)))

    async def recv(self) -> Event | None:
        return await asyncio.wait_for(async_read_event(self.reader), T)

    async def expect(self, kind: str) -> Event:
        event = await self.recv()
        assert event is not None and event.type == kind, event
        return event

    async def hear(self) -> int:
        """Recebe uma fala inteira; devolve quantos blocos chegaram."""
        start = await self.expect(EventType.AUDIO_START)
        assert start.data["rate"] == VOICE.rate
        chunks = 0
        while (event := await self.recv()) is not None and event.type == EventType.AUDIO_CHUNK:
            chunks += 1
        assert event is not None and event.type == EventType.AUDIO_STOP
        return chunks

    async def close(self) -> None:
        self.writer.close()


class Hud:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.seen: list[HudMessage] = []

    async def next(self) -> HudMessage:
        line = await asyncio.wait_for(self.reader.readline(), T)
        assert line, "HUD desconectado"
        msg = decode_hud(line)
        self.seen.append(msg)
        return msg

    async def state(self) -> Expression:
        """Próximo ``state``; o que vier antes fica em ``seen``."""
        while not isinstance(msg := await self.next(), StateMsg):
            pass
        return msg.v

    async def states(self, n: int) -> list[Expression]:
        return [await self.state() for _ in range(n)]

    def of(self, kind: type) -> list[HudMessage]:
        return [m for m in self.seen if isinstance(m, kind)]


@dataclass
class Rig:
    service: CoreService
    hud_server: HudServer
    sat: Sat
    hud: Hud
    stt: FakeStt
    actions: FakeActions
    speaker: FakeSpeaker
    commands: list[CmdMsg] = field(default_factory=list)

    @property
    def state(self) -> TurnState:
        machine = self.service.machine("pc")
        assert machine is not None
        return machine.state


async def _until(cond, timeout: float = T) -> None:
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.005)


@pytest.fixture
def sock_dir():
    # Diretório curto: caminho de socket Unix tem limite de ~108 bytes.
    d = Path(tempfile.mkdtemp(prefix="magi-"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
async def make_rig(sock_dir: Path):
    rigs: list[Rig] = []

    async def make(*, speaker: bool = True, agent: bool = True, **kw) -> Rig:
        stt, actions, spk = FakeStt(), FakeActions(), FakeSpeaker()
        deps = TurnDeps(
            stt=stt,
            corrector=FakeCorrector(),
            router=FakeRouter(),
            actions=actions,
            agent=FakeAgent() if agent else None,
            speaker=spk if speaker else None,
        )
        hud_server = HudServer(sock_dir / "hud.sock")
        await hud_server.start()
        service = CoreService(deps, hud_server, port=0, **kw)
        await service.start()
        reader, writer = await asyncio.open_unix_connection(str(hud_server.path))
        await _until(lambda: hud_server.clients == 1)
        sat = await Sat.connect(service.port)
        await _until(lambda: service.machine("pc") is not None)
        rig = Rig(service, hud_server, sat, Hud(reader, writer), stt, actions, spk)
        hud_server.on_command = lambda cmd: _append(rig.commands, cmd)
        rigs.append(rig)
        return rig

    yield make
    for rig in rigs:
        await rig.sat.close()
        rig.hud.writer.close()
        await rig.service.stop()
        await rig.hud_server.stop()


async def _append(items: list, item: object) -> None:
    items.append(item)


S, L, TH, SP, AL = (
    Expression.SLEEPING,
    Expression.LISTENING,
    Expression.THINKING,
    Expression.SPEAKING,
    Expression.ALERT,
)

# ---------------------------------------------------------------------------------------------
# Turno completo
# ---------------------------------------------------------------------------------------------


async def test_turno_local_percorre_estados(make_rig) -> None:
    rig = await make_rig()
    await rig.sat.wake()
    assert await rig.hud.state() == L
    assert rig.state is TurnState.LISTENING

    await rig.sat.speak("abre o jogo")
    assert await rig.hud.states(2) == [TH, Expression.HAPPY]  # expressão da ação ao falar
    assert rig.state is TurnState.SPEAKING
    assert await rig.sat.hear() == 2
    assert rig.speaker.said == ["Abrindo."]
    assert rig.hud.of(SubtitleMsg) == [SubtitleMsg("Abrindo.")]

    await rig.sat.send(MouthEvent(level=0.6, satellite="pc"))
    await rig.sat.send(PlaybackDone(satellite="pc"))
    assert await rig.hud.state() == S
    assert rig.hud.of(MouthMsg) == [MouthMsg(0.6)]
    assert rig.state is TurnState.SLEEPING

    (req,) = rig.actions.calls
    assert req.intent.id == IntentId.GAME_OPEN and req.text == "abre o jogo"
    assert req.ctx.satellite == "pc" and req.ctx.source is WakeSource.WAKE
    assert req.ctx.tone == ToneMetadata(energy_db=-20.0, speech_rate=4.0)


async def test_pergunta_vai_ao_agente_com_texto_completo(make_rig) -> None:
    rig = await make_rig()
    await rig.sat.wake(WakeSource.PTT)
    await rig.sat.speak("quem é a magui", AudioEndReason.PTT_RELEASE)
    assert await rig.hud.states(3) == [L, TH, SP]
    await rig.sat.hear()
    assert rig.hud.of(SubtitleMsg) == [
        SubtitleMsg("Resposta curta.", "Resposta completa para: quem é a Magui")  # corrigido
    ]
    await rig.sat.send(PlaybackDone())
    assert await rig.hud.state() == S


async def test_sem_fala_ou_stt_falho_responde_nao_peguei(make_rig) -> None:
    rig = await make_rig()
    rig.stt.fail = True
    await rig.sat.wake()
    await rig.sat.speak("abre o jogo")
    assert await rig.hud.states(3) == [L, TH, Expression.CONFUSED]
    await rig.sat.hear()
    assert rig.speaker.said == [SAY_NOT_HEARD]
    await rig.sat.send(PlaybackDone())
    assert await rig.hud.state() == S


async def test_gravacao_vazia_volta_a_dormir(make_rig) -> None:
    rig = await make_rig()
    await rig.sat.wake()
    await rig.sat.speak("", AudioEndReason.NO_SPEECH)
    assert await rig.hud.states(2) == [L, S]
    assert rig.speaker.said == []


async def test_sem_speaker_so_legenda(make_rig) -> None:
    rig = await make_rig(speaker=False, agent=False)
    await rig.sat.wake()
    await rig.sat.speak("qual a capital da frança")
    assert await rig.hud.states(3) == [L, TH, S]
    assert rig.hud.of(SubtitleMsg) == [SubtitleMsg(SAY_UNAVAILABLE)]


# ---------------------------------------------------------------------------------------------
# Interrupção (R12.5)
# ---------------------------------------------------------------------------------------------


async def test_wake_durante_fala_interrompe_e_volta_a_ouvir(make_rig) -> None:
    rig = await make_rig()
    rig.speaker.hold = True
    await rig.sat.wake()
    await rig.sat.speak("abre o jogo")
    assert await rig.hud.states(3) == [L, TH, Expression.HAPPY]
    await rig.sat.expect(EventType.AUDIO_START)
    await rig.sat.expect(EventType.AUDIO_CHUNK)

    await rig.sat.wake()
    await rig.sat.expect(EventType.STOP_PLAYBACK)  # sem mais áudio nem audio-stop antes
    assert await rig.hud.state() == L
    assert rig.speaker.cancelled
    assert rig.state is TurnState.LISTENING

    # playback-done fora de speaking é ignorado: o próximo estado é thinking, não sleeping.
    await rig.sat.send(PlaybackDone())
    rig.speaker.hold = False
    await rig.sat.speak("abre o jogo")
    assert await rig.hud.state() == TH
    assert await rig.hud.state() == Expression.HAPPY
    assert await rig.sat.hear() == 2
    await rig.sat.send(PlaybackDone())
    assert await rig.hud.state() == S


async def test_wake_durante_thinking_cancela_o_turno(make_rig) -> None:
    rig = await make_rig()
    rig.stt.gate = asyncio.Event()
    await rig.sat.wake()
    await rig.sat.speak("abre o jogo")
    assert await rig.hud.states(2) == [L, TH]
    await rig.sat.wake()
    assert await rig.hud.state() == L
    assert rig.stt.cancelled and rig.actions.calls == []
    # wake repetido durante listening é ignorado
    await rig.sat.wake()
    rig.stt.gate.set()
    await rig.sat.speak("abre o jogo")
    assert await rig.hud.states(2) == [TH, Expression.HAPPY]


async def test_desconexao_dorme_e_remove_satelite(make_rig) -> None:
    rig = await make_rig()
    await rig.sat.wake()
    assert await rig.hud.state() == L
    await rig.sat.close()
    assert await rig.hud.state() == S
    await _until(lambda: rig.service.machine("pc") is None)


async def test_primeiro_evento_precisa_ser_hello(make_rig) -> None:
    rig = await make_rig()
    other = await Sat.connect(rig.service.port, hello=False)
    await other.wake()
    assert await other.recv() is None  # conexão fechada
    assert set(rig.service.satellites) == {"pc"}


# ---------------------------------------------------------------------------------------------
# Confirmação (R5.3, R5.4)
# ---------------------------------------------------------------------------------------------


async def _ate_confirming(rig: Rig, text: str = "fecha o jogo", face: Expression = SP) -> Event:
    await rig.sat.wake()
    await rig.sat.speak(text)
    assert await rig.hud.states(3) == [L, TH, face]
    await rig.sat.hear()
    await rig.sat.send(PlaybackDone())
    assert await rig.hud.state() == AL
    assert rig.state is TurnState.CONFIRMING
    return await rig.sat.expect(EventType.LISTEN)


async def test_confirmacao_executa_acao_perigosa(make_rig) -> None:
    rig = await make_rig()
    listen = await _ate_confirming(rig)
    assert listen.data["timeout_ms"] == 8_000
    assert rig.hud.of(VoteMsg) == [VoteMsg(Verdict.PENDING)]

    await rig.sat.speak("confirma")  # escuta curta, sem wake
    assert await rig.hud.states(2) == [TH, SP]
    await rig.sat.hear()
    await rig.sat.send(PlaybackDone())
    assert await rig.hud.state() == S

    assert rig.speaker.said == ["Fechar o jogo? Diz confirma.", "Fechado."]
    assert [c.confirmed for c in rig.actions.calls] == [False, True]
    assert rig.hud.of(VoteMsg) == [VoteMsg(Verdict.PENDING), VoteMsg(Verdict.APPROVED)]


async def test_confirmacao_negada(make_rig) -> None:
    rig = await make_rig()
    await _ate_confirming(rig)
    await rig.sat.speak("cancela")
    assert await rig.hud.states(2) == [TH, SP]
    await rig.sat.hear()
    assert rig.speaker.said[-1] == SAY_CANCELLED
    assert len(rig.actions.calls) == 1
    assert rig.hud.of(VoteMsg)[-1] == VoteMsg(Verdict.DENIED)
    await rig.sat.send(PlaybackDone())
    assert await rig.hud.state() == S


async def test_confirmacao_sem_fala_cancela(make_rig) -> None:
    rig = await make_rig()
    await _ate_confirming(rig)
    await rig.sat.speak("", AudioEndReason.NO_SPEECH)
    assert await rig.hud.state() == SP  # confirming -> speaking direto
    await rig.sat.hear()
    assert rig.speaker.said[-1] == SAY_CANCELLED
    await rig.sat.send(PlaybackDone())
    assert await rig.hud.state() == S


async def test_confirmacao_expira_por_tempo(make_rig) -> None:
    rig = await make_rig(confirm_timeout_ms=100, confirm_grace_ms=50)
    listen = await _ate_confirming(rig)
    assert listen.data["timeout_ms"] == 100
    assert await rig.hud.state() == SP  # nada chegou do satélite: o núcleo cancela sozinho
    await rig.sat.hear()
    assert rig.speaker.said[-1] == SAY_CANCELLED
    assert rig.hud.of(VoteMsg)[-1] == VoteMsg(Verdict.DENIED)
    assert len(rig.actions.calls) == 1
    await rig.sat.send(PlaybackDone())
    assert await rig.hud.state() == S


async def test_voce_quis_dizer_confirma_e_executa(make_rig) -> None:
    rig = await make_rig()
    await _ate_confirming(rig, "abri o jogo", Expression.CONFUSED)
    assert rig.speaker.said == ["Abrir o jogo?"]
    assert rig.hud.of(VoteMsg) == []  # não é perigosa
    await rig.sat.speak("sim")
    assert await rig.hud.states(2) == [TH, Expression.HAPPY]
    await rig.sat.hear()
    assert rig.actions.calls[-1].intent.id == IntentId.GAME_OPEN


async def test_wake_durante_confirming_descarta_pendencia(make_rig) -> None:
    rig = await make_rig()
    await _ate_confirming(rig)
    await rig.sat.wake()
    assert await rig.hud.state() == L
    assert rig.hud.of(VoteMsg)[-1] == VoteMsg(Verdict.DENIED)
    await rig.sat.speak("confirma")  # agora é fala nova, não confirmação
    assert await rig.hud.states(2) == [TH, Expression.CONFUSED]
    assert rig.speaker.said[-1] == SAY_UNAVAILABLE
    assert len(rig.actions.calls) == 1


# ---------------------------------------------------------------------------------------------
# HUD e pipeline
# ---------------------------------------------------------------------------------------------


async def test_hud_atrasado_recebe_ultimo_estado_e_manda_comando(make_rig) -> None:
    rig = await make_rig()
    await rig.sat.wake()
    assert await rig.hud.state() == L
    reader, writer = await asyncio.open_unix_connection(str(rig.hud_server.path))
    late = Hud(reader, writer)
    assert await late.state() == L
    writer.write(encode_hud_line(CmdMsg("push_to_talk")))
    writer.write(b"lixo\n")
    await writer.drain()
    await _until(lambda: len(rig.commands) == 1)
    assert rig.commands == [CmdMsg("push_to_talk")]
    writer.close()
    await _until(lambda: rig.hud_server.clients == 1)


async def test_hud_fechado_descarta(sock_dir: Path) -> None:
    server = HudServer(sock_dir / "h.sock")
    await server.send(StateMsg(Expression.LISTENING))  # sem start nem clientes: não levanta
    await server.start()
    reader, writer = await asyncio.open_unix_connection(str(server.path))
    await _until(lambda: server.clients == 1)
    writer.close()
    await asyncio.sleep(0.05)
    for _ in range(3):
        await server.send(StateMsg(Expression.SLEEPING))
    assert server.clients == 0
    await server.stop()
    assert not server.path.exists()


def _ctx() -> TurnContext:
    from datetime import UTC, datetime

    return TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime.now(UTC))


@pytest.mark.parametrize(
    ("text", "yes"),
    [("confirma", True), ("Sim, confirmo", True), ("não confirma", False), ("pode", False), ("", False)],
)
def test_is_yes_sem_roteador(text: str, yes: bool) -> None:
    assert TurnPipeline().is_yes(Transcript.raw(text), _ctx()) is yes


async def test_pipeline_sem_dependencias_degrada() -> None:
    pipe = TurnPipeline()
    t = await pipe.transcribe(b"abc", PcmFormat(), _ctx())
    assert t.is_empty
    assert (await pipe.respond(t, _ctx())).speech == SAY_NOT_HEARD
    assert (await pipe.respond(Transcript.raw("oi"), _ctx())).speech == SAY_UNAVAILABLE
