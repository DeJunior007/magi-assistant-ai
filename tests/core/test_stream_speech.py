"""Fala por frase em streaming e corte do silêncio inicial do TTS (1.24, RNF-05)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from magi.agent.graph import GraphAgent
from magi.common.contracts import (
    ChatReply,
    PcmFormat,
    SatelliteHello,
    StopPlayback,
    SubtitleMsg,
    ToolCall,
    Transcript,
    TurnContext,
    TurnState,
    WakeSource,
)
from magi.core.compose import SpeechDraft
from magi.core.early import EARLY_SPEECH, EarlySpeech
from magi.core.tts import MAX_TRIM_MS, PhraseCache, Phrases, PhraseSpeaker, trim_lead, trim_silence
from magi.core.turn import TurnDeps, TurnMachine, TurnPipeline

FMT = PcmFormat(rate=24_000)
CTX = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC))


def pcm(silence_ms: int, sound_ms: int = 100, amp: int = 3000) -> bytes:
    quiet = np.zeros(FMT.rate * silence_ms // 1000, dtype="<i2")
    quiet[::7] = 40  # ruído abaixo de -50 dBFS
    loud = np.full(FMT.rate * sound_ms // 1000, amp, dtype="<i2")
    return quiet.tobytes() + loud.tobytes()


async def chunked(data: bytes, step: int = 4096) -> AsyncIterator[bytes]:
    for i in range(0, len(data), step):
        yield data[i : i + step]


async def collect(it: AsyncIterable[bytes]) -> bytes:
    return b"".join([c async for c in it])


# -- silêncio inicial ---------------------------------------------------------------------------


async def test_silencio_inicial_cortado_em_bloco_e_em_streaming():
    data = pcm(300)
    sound = pcm(0)
    assert trim_silence(data, FMT) == sound
    assert await collect(trim_lead(chunked(data), FMT)) == sound
    assert await collect(trim_lead(chunked(data, 333), FMT)) == sound  # blocos desalinhados


async def test_corte_nunca_passa_de_600_ms():
    limit = FMT.bytes_for_ms(MAX_TRIM_MS)
    data = pcm(900)
    assert len(trim_silence(data, FMT)) == len(data) - limit
    assert len(await collect(trim_lead(chunked(data), FMT))) == len(data) - limit
    quiet = b"\x01\x00" * 200  # curto e todo baixo: é a fala inteira, fica como está
    assert trim_silence(quiet, FMT) == quiet
    assert await collect(trim_lead(chunked(quiet, 64), FMT)) == quiet


class PcmTts:
    name = "fake"
    model = "voz-1"
    free_tier = False
    output_format = FMT
    voice = "nova"

    def __init__(self, gate: asyncio.Event | None = None) -> None:
        self.calls: list[str] = []
        self.gate = gate

    def synthesize(self, text, *, personal: bool) -> AsyncIterator[bytes]:
        self.calls.append(text)
        return self._gen()

    async def _gen(self) -> AsyncIterator[bytes]:
        async for c in chunked(pcm(400)):
            yield c


class FakeLink:
    def __init__(self) -> None:
        self.hello = SatelliteHello("pc")
        self.plays: list[list[bytes]] = []
        self.sent: list[object] = []
        self.first_audio = asyncio.Event()
        self.done = asyncio.Event()

    async def send(self, msg: object) -> None:
        self.sent.append(msg)

    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
        chunks: list[bytes] = []
        self.plays.append(chunks)
        async for c in audio:
            chunks.append(c)
            self.first_audio.set()
        self.done.set()


def speaker(tmp_path: Path, tts: PcmTts, fixed: Sequence[str] = ()) -> PhraseSpeaker:
    return PhraseSpeaker(tts, phrases=Phrases.build(fixed), cache=PhraseCache(tmp_path), auto_warm=False)


async def test_cache_grava_cortado_e_regrava_entrada_antiga(tmp_path):
    tts = PcmTts()
    spk = speaker(tmp_path, tts, ["Pronto."])
    link = FakeLink()
    await spk.say("Pronto.", link, personal=False)
    key = spk.key("Pronto.")
    assert b"".join(link.plays[0]) == pcm(0) == spk.cache.get(key)
    spk.cache.put(key, pcm(350))  # entrada de antes da 1.24, com silêncio
    await spk.say("Pronto.", link, personal=False)
    assert b"".join(link.plays[1]) == pcm(0) == spk.cache.get(key)
    assert tts.calls == ["Pronto."]


async def test_say_stream_duas_frases_no_mesmo_envio(tmp_path):
    tts = PcmTts()
    spk = speaker(tmp_path, tts)
    link = FakeLink()

    async def texts() -> AsyncIterator[str]:
        yield "Primeira frase."
        yield "Segunda frase."

    await spk.say_stream(texts(), link, personal=True)
    assert len(link.plays) == 1 and b"".join(link.plays[0]) == pcm(0) * 2
    assert tts.calls == ["Primeira frase.", "Segunda frase."]


# -- rascunho de fala -------------------------------------------------------------------------


def test_rascunho_solta_frase_quando_a_seguinte_comeca():
    d = SpeechDraft()
    assert d.push("Uma aranha tem oito ") == []
    assert d.push("patas.") == []
    assert d.push(" Elas") == []  # palavra em curso fica de fora
    assert d.push(" têm") == ["Uma aranha tem oito patas."]
    assert d.push(" quatro pares. Veja https://x.org/a.") == ["Elas têm quatro pares."]
    assert d.push(" Mais uma.") == [] and d.finish() == []  # no máximo 2 frases


def test_rascunho_ignora_markdown_e_lista():
    d = SpeechDraft()
    out = d.push("**Oito** patas, veja [a wiki](https://w.org). Detalhes:\n- item um\n- item dois\n")
    assert out == ["Oito patas, veja a wiki."]
    assert d.finish() == ["Detalhes."]


# -- agente -----------------------------------------------------------------------------------


class StreamChat:
    """Chat falso com ``chat_stream``: cada roteiro é (pedaços de texto, ferramentas)."""

    name = "fake"
    model = "fake-1"
    free_tier = False

    def __init__(self, script: Sequence[tuple[Sequence[str], tuple[ToolCall, ...]]]) -> None:
        self.script = list(script)
        self.gate = asyncio.Event()
        self.gate.set()
        self.finished = False
        self.spoken_at_call: list[int] = []
        self.early: EarlySpeech | None = None

    async def chat(self, messages, *, tools=(), json_mode=False, personal):  # pragma: no cover
        raise AssertionError("deveria usar chat_stream")

    async def chat_stream(self, messages, *, tools=(), personal, on_text):
        self.spoken_at_call.append(len(self.early.spoken) if self.early else 0)
        pieces, calls = self.script.pop(0)
        for i, piece in enumerate(pieces):
            if i == len(pieces) - 1:
                await self.gate.wait()
            on_text(piece)
            await asyncio.sleep(0)
        self.finished = True
        return ChatReply(text="".join(pieces), tool_calls=calls)


class Providers:
    def __init__(self, chat: StreamChat) -> None:
        self._chat = chat

    def chat(self, task=None) -> StreamChat:
        return self._chat


async def test_frase_de_espera_antes_da_ferramenta_e_resposta_final_inteira():
    chat = StreamChat([(("Deixa eu ver", " aqui"), (ToolCall("c1", "nao_existe", {}),)),
                       (("Achei. ", "São oito."), ())])
    said: list[str] = []

    async def play(texts: AsyncIterator[str]) -> None:
        said.extend([t async for t in texts])

    early = EarlySpeech(play)
    chat.early = early
    token = EARLY_SPEECH.set(early)
    try:
        result = await GraphAgent(Providers(chat)).answer("quantas patas", CTX)
    finally:
        EARLY_SPEECH.reset(token)
    assert chat.spoken_at_call == [0, 1]  # a frase de espera saiu antes da 2ª chamada
    assert early.interim == ["Deixa eu ver aqui"]
    await early.finish(early.missing(result.speech))
    assert said == ["Deixa eu ver aqui", "Achei.", "São oito."]  # a espera não come a resposta


async def test_sem_ferramenta_continua_com_duas_frases():
    chat = StreamChat([(("Uma. ", "Duas. ", "Três."), ())])
    said: list[str] = []

    async def play(texts: AsyncIterator[str]) -> None:
        said.extend([t async for t in texts])

    early = EarlySpeech(play)
    chat.early = early
    token = EARLY_SPEECH.set(early)
    try:
        result = await GraphAgent(Providers(chat)).answer("conta", CTX)
    finally:
        EARLY_SPEECH.reset(token)
    await early.finish(early.missing(result.speech))
    assert said == ["Uma.", "Duas."] and early.interim == []


# -- turno ponta a ponta ----------------------------------------------------------------------


class FakeStt:
    async def transcribe(self, audio, fmt, *, hint="", language="pt", personal):
        return Transcript.raw("quantas patas tem uma aranha")


class FakeHud:
    def __init__(self) -> None:
        self.msgs: list[object] = []

    async def send(self, msg) -> None:
        self.msgs.append(msg)


def machine(tmp_path: Path, chat: StreamChat) -> tuple[TurnMachine, FakeLink, FakeHud, PcmTts]:
    tts = PcmTts()
    deps = TurnDeps(stt=FakeStt(), agent=GraphAgent(Providers(chat)), speaker=speaker(tmp_path, tts))
    link, hud = FakeLink(), FakeHud()
    m = TurnMachine(link, hud, TurnPipeline(deps))
    m._state = TurnState.THINKING  # como depois do audio-stop
    return m, link, hud, tts


async def test_primeira_frase_vira_audio_antes_do_fim_da_geracao(tmp_path):
    pieces = ["Uma aranha tem oito ", "patas. ", "Elas têm ", "quatro pares. ", "Uma terceira ", "frase."]
    chat = StreamChat([(pieces, ())])
    chat.gate.clear()
    m, link, hud, tts = machine(tmp_path, chat)
    m._start(m._think(b"\0\0", FMT, CTX))
    await asyncio.wait_for(link.first_audio.wait(), 1)
    assert not chat.finished and m.state is TurnState.SPEAKING
    assert tts.calls[0] == "Uma aranha tem oito patas."
    chat.gate.set()
    await asyncio.wait_for(m._task, 1)
    assert len(link.plays) == 1  # um só audio-start … audio-stop
    assert tts.calls == ["Uma aranha tem oito patas.", "Elas têm quatro pares."]
    assert b"".join(link.plays[0]) == pcm(0) * 2  # silêncio inicial cortado nas duas
    sub = [x for x in hud.msgs if isinstance(x, SubtitleMsg)][-1]
    assert sub.full is not None and "terceira" in sub.full


async def test_ativacao_durante_a_fala_corta_tudo(tmp_path):
    chat = StreamChat([(["Uma aranha tem oito ", "patas. ", "Elas têm ", "quatro pares."], ())])
    chat.gate.clear()
    m, link, _, tts = machine(tmp_path, chat)
    m._start(m._think(b"\0\0", FMT, CTX))
    await asyncio.wait_for(link.first_audio.wait(), 1)
    await m.wake()
    assert any(isinstance(x, StopPlayback) for x in link.sent)
    assert m.state is TurnState.LISTENING
    chat.gate.set()
    await asyncio.sleep(0.05)
    assert not link.done.is_set()  # envio cancelado, nada mais falado
    assert tts.calls == ["Uma aranha tem oito patas."]
