"""Transcrição enquanto fala (1.25) com cliente Realtime falso: texto final sem reenviar o áudio,
queda para o caminho antigo, orçamento e fechamento da sessão em silêncio/interrupção."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from wyoming.audio import AudioChunk, AudioStart

from magi.common.config import parse_config
from magi.common.contracts import (
    AudioEnd,
    AudioEndReason,
    BudgetStatus,
    PcmFormat,
    ProviderTask,
    SatelliteHello,
    TurnContext,
    TurnState,
    Usage,
    WakeSource,
)
from magi.core.stt import HintedStt
from magi.core.turn import TurnDeps, TurnMachine, TurnPipeline
from magi.providers.openai_provider import OpenAIBackend, PcmResampler
from magi.providers.registry import Registry

FMT = PcmFormat(rate=16_000, width=2, channels=1)
CHUNK = b"\x01\x00" * 1280  # 80 ms
AUDIO = CHUNK * 3


class FakeConn:
    def __init__(self, *, on_commit: dict[str, Any] | None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.events: asyncio.Queue[bytes] = asyncio.Queue()
        self.on_commit = on_commit
        self.closed = False

    async def send_raw(self, data: str) -> None:
        ev = json.loads(data)
        self.sent.append(ev)
        if ev["type"] == "input_audio_buffer.commit" and self.on_commit is not None:
            await self.events.put(json.dumps({"type": "input_audio_buffer.committed"}).encode())
            await self.events.put(json.dumps(self.on_commit).encode())

    async def recv_bytes(self) -> bytes:
        return await self.events.get()

    async def close(self) -> None:
        self.closed = True

    def kinds(self) -> list[str]:
        return [e["type"] for e in self.sent]


class FakeClient:
    """``realtime.connect(...).enter()`` e ``audio.transcriptions.create`` (caminho antigo)."""

    def __init__(self, *, on_commit: dict[str, Any] | None, connect_error: Exception | None = None) -> None:
        self.conn = FakeConn(on_commit=on_commit)
        self.connect_error = connect_error
        self.queries: list[dict[str, Any]] = []
        self.file_calls: list[dict[str, Any]] = []
        self.realtime = SimpleNamespace(connect=self._connect)
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))

    def _connect(self, *, extra_query: dict[str, Any]) -> Any:
        self.queries.append(extra_query)

        async def enter() -> FakeConn:
            if self.connect_error is not None:
                raise self.connect_error
            return self.conn

        return SimpleNamespace(enter=enter)

    async def _create(self, **kwargs: Any) -> Any:
        self.file_calls.append(kwargs)
        return SimpleNamespace(text="texto do arquivo")


class FakeBudget:
    def __init__(self) -> None:
        self.usages: list[Usage] = []
        self.checks: list[ProviderTask] = []

    async def ensure_allowed(self, task: ProviderTask) -> None:
        self.checks.append(task)

    async def record(self, usage: Usage) -> None:
        self.usages.append(usage)

    async def status(self) -> BudgetStatus:
        return BudgetStatus(0.0, 5.0)


COMPLETED = {"type": "conversation.item.input_audio_transcription.completed", "transcript": " abre o  jogo "}


def _setup(client: FakeClient, *, streaming: bool = True) -> tuple[TurnPipeline, FakeBudget]:
    cfg = parse_config(
        {
            "providers": {"openai": {"keys": ["openai-1"]}},
            "tasks": {"stt": {"provider": "openai", "model": "gpt-transcribe", "streaming": streaming}},
        }
    )
    budget = FakeBudget()
    reg = Registry(
        cfg,
        budget,
        backends={"openai": lambda c: OpenAIBackend(c, client_factory=lambda key: client)},
        get_secret=lambda name: "sk-test",
    )
    return TurnPipeline(TurnDeps(stt=HintedStt(reg.stt))), budget


def _ctx() -> TurnContext:
    return TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime.now(UTC))


async def _stream_turn(pipeline: TurnPipeline) -> str:
    stream = pipeline.open_stream(FMT)
    assert stream is not None
    for _ in range(3):
        stream.feed(CHUNK)
        await asyncio.sleep(0)
    return (await pipeline.transcribe(AUDIO, FMT, _ctx(), stream=stream)).final


async def test_texto_final_sem_reenviar_o_audio() -> None:
    client = FakeClient(on_commit=COMPLETED)
    pipeline, budget = _setup(client)
    assert await _stream_turn(pipeline) == "abre o jogo"
    assert client.file_calls == []  # o áudio não foi mandado de novo
    assert client.queries == [{"intent": "transcription"}]
    conn = client.conn
    appends = ["input_audio_buffer.append"] * 3
    assert conn.kinds() == ["session.update", *appends, "input_audio_buffer.commit"]
    tr = conn.sent[0]["session"]["audio"]["input"]
    assert tr["format"] == {"type": "audio/pcm", "rate": 24_000}
    assert tr["turn_detection"] is None
    assert tr["transcription"]["model"] == "gpt-transcribe"
    assert "Condessa" in tr["transcription"]["prompt"]  # dica de vocabulário mantida
    pcm = b"".join(base64.b64decode(e["audio"]) for e in conn.sent[1:4])
    assert abs(len(pcm) - len(AUDIO) * 3 // 2) <= 4  # 16 kHz -> 24 kHz
    # orçamento: checado antes e segundos de áudio registrados no modelo do streaming
    assert budget.checks == [ProviderTask.STT]
    assert [(u.model, round(u.input_units, 2)) for u in budget.usages] == [("gpt-transcribe", 0.24)]
    await asyncio.sleep(0)
    assert conn.closed


@pytest.mark.parametrize(
    "client",
    [
        FakeClient(on_commit={"type": "error", "error": {"message": "buffer too small"}}),
        FakeClient(on_commit=None, connect_error=OSError("sem rede")),
        FakeClient(on_commit={**COMPLETED, "transcript": "  "}),
    ],
    ids=["erro", "conexao", "vazio"],
)
async def test_falha_da_sessao_cai_no_caminho_antigo(client: FakeClient) -> None:
    pipeline, budget = _setup(client)
    assert await _stream_turn(pipeline) == "texto do arquivo"
    assert len(client.file_calls) == 1
    assert client.file_calls[0]["model"] == "gpt-transcribe"
    assert "Condessa" in client.file_calls[0]["prompt"]


async def test_estouro_do_tempo_cancela_e_devolve_none() -> None:
    client = FakeClient(on_commit=None)  # nunca chega o texto final
    pipeline, _ = _setup(client)
    stream = pipeline.open_stream(FMT)
    stream.feed(CHUNK)
    assert await stream.finish(timeout=0.05) is None
    assert stream.failed
    await asyncio.sleep(0)
    assert client.conn.closed


async def test_streaming_desligado_nao_abre_sessao() -> None:
    client = FakeClient(on_commit=COMPLETED)
    pipeline, _ = _setup(client, streaming=False)
    assert pipeline.open_stream(FMT) is None
    assert (await pipeline.transcribe(AUDIO, FMT, _ctx())).final == "texto do arquivo"
    assert client.queries == []


def test_reamostragem_continua_entre_pedacos() -> None:
    r = PcmResampler(FMT, 24_000)
    out = b"".join(r.feed(CHUNK) for _ in range(10))
    assert abs(len(out) - len(CHUNK) * 10 * 3 // 2) <= 4
    assert set(out[i : i + 2] for i in range(0, len(out), 2)) == {b"\x01\x00"}


# -- máquina de turno: silêncio e interrupção fecham a sessão -------------------------------


class FakeStream:
    def __init__(self) -> None:
        self.fed: list[bytes] = []
        self.cancelled = False
        self.finished = False

    def feed(self, chunk: bytes) -> None:
        self.fed.append(chunk)

    async def finish(self, timeout: float = 1.5) -> Any:
        self.finished = True
        return None

    async def cancel(self) -> None:
        self.cancelled = True


class StreamingStt:
    name, model, free_tier = "fake", "fake", False

    def __init__(self) -> None:
        self.streams: list[FakeStream] = []

    def open_stream(self, fmt: PcmFormat, *, personal: bool) -> FakeStream:
        self.streams.append(s := FakeStream())
        return s

    async def transcribe(self, audio: bytes, fmt: PcmFormat, **kw: Any) -> Any:
        raise AssertionError("não deveria transcrever")


class Sink:
    def __init__(self) -> None:
        self.hello = SatelliteHello(satellite="pc")
        self.sent: list[Any] = []

    async def send(self, msg: Any) -> None:
        self.sent.append(msg)


async def _record(machine: TurnMachine) -> None:
    await machine.wake()
    await machine.handle(AudioStart(rate=16_000, width=2, channels=1))
    await machine.handle(AudioChunk(rate=16_000, width=2, channels=1, audio=CHUNK))


async def test_no_speech_fecha_a_sessao() -> None:
    stt = StreamingStt()
    link = Sink()
    machine = TurnMachine(link, Sink(), TurnPipeline(TurnDeps(stt=stt)))  # type: ignore[arg-type]
    await _record(machine)
    assert stt.streams[0].fed == [CHUNK]
    await machine.handle(AudioEnd(reason=AudioEndReason.NO_SPEECH))
    assert machine.state is TurnState.SLEEPING
    assert stt.streams[0].cancelled and not stt.streams[0].finished


async def test_desconexao_fecha_a_sessao() -> None:
    stt = StreamingStt()
    machine = TurnMachine(Sink(), Sink(), TurnPipeline(TurnDeps(stt=stt)))  # type: ignore[arg-type]
    await _record(machine)
    await machine.close()
    assert stt.streams[0].cancelled
