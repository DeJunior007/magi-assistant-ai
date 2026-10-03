"""Voz no núcleo (1.12): cache de frases, streaming, invalidação por voz, erro do provedor."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path

import pytest

from magi.common.contracts import (
    PcmFormat,
    ProviderError,
    SatelliteHello,
    SatelliteLink,
    Speaker,
    TtsProvider,
)
from magi.core.tts import PhraseCache, Phrases, PhraseSpeaker

FMT = PcmFormat(rate=24_000)


class FakeTts:
    name = "fake"
    model = "voz-1"
    free_tier = False
    output_format = FMT

    def __init__(self, chunks: int = 3, fail_after: int | None = None) -> None:
        self.calls: list[tuple[str, bool]] = []
        self.chunks = chunks
        self.fail_after = fail_after
        self.voice = "nova"
        self.gate: asyncio.Event | None = None

    def synthesize(self, text: str | AsyncIterable[str], *, personal: bool) -> AsyncIterator[bytes]:
        assert isinstance(text, str)
        self.calls.append((text, personal))
        return self._gen(text)

    async def _gen(self, text: str) -> AsyncIterator[bytes]:
        for i in range(self.chunks):
            if self.fail_after is not None and i >= self.fail_after:
                raise ProviderError("caiu")
            if self.gate is not None and i == 1:
                await self.gate.wait()
            yield f"{text}#{i};".encode()


class FakeLink:
    def __init__(self) -> None:
        self.hello = SatelliteHello("pc")
        self.plays: list[tuple[list[bytes], PcmFormat]] = []
        self.events: list[str] = []

    async def send(self, msg: object) -> None:  # pragma: no cover - não usado
        pass

    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
        got: list[bytes] = []
        self.events.append("start")
        async for pcm in audio:
            self.events.append("chunk")
            got.append(pcm)
        self.events.append("stop")
        self.plays.append((got, fmt))


def make(tmp_path: Path, tts: FakeTts, **kw: object) -> PhraseSpeaker:
    phrases = Phrases.build(["Cancelado.", "Não peguei, repete?"], ["Abrindo {game}."])
    return PhraseSpeaker(
        tts,
        phrases=phrases,
        cache=PhraseCache(tmp_path / "tts", max_bytes=10_000),
        auto_warm=False,
        **kw,  # type: ignore[arg-type]
    )


def test_protocols(tmp_path: Path) -> None:
    assert isinstance(FakeTts(), TtsProvider)
    assert isinstance(FakeLink(), SatelliteLink)
    assert isinstance(make(tmp_path, FakeTts()), Speaker)


def test_phrases_yaml_loads() -> None:
    p = Phrases.load()
    assert "Cancelado." in p.fixed
    assert p.cacheable("cancelado.")
    assert p.cacheable("Abrindo Elden Ring.")
    assert not p.cacheable("Abrindo")
    assert not p.cacheable("Hoje o dia tá bonito.")


async def test_cached_phrase_plays_without_provider(tmp_path: Path) -> None:
    tts = FakeTts()
    sp = make(tmp_path, tts)
    assert await sp.warm() == 2
    tts.calls.clear()
    link = FakeLink()
    await sp.say("  cancelado. ", link, personal=True)
    assert tts.calls == []
    chunks, fmt = link.plays[0]
    assert fmt == FMT
    assert b"".join(chunks) == b"Cancelado.#0;Cancelado.#1;Cancelado.#2;"


async def test_template_cached_by_value_after_first_use(tmp_path: Path) -> None:
    tts = FakeTts()
    sp = make(tmp_path, tts)
    link = FakeLink()
    await sp.say("Abrindo Hades.", link, personal=True)
    await sp.say("Abrindo Hades.", link, personal=True)
    await sp.say("Abrindo Celeste.", link, personal=True)
    assert [c[0] for c in tts.calls] == ["Abrindo Hades.", "Abrindo Celeste."]
    assert b"".join(link.plays[0][0]) == b"".join(link.plays[1][0])


async def test_free_text_streams_in_order_without_waiting(tmp_path: Path) -> None:
    tts = FakeTts(chunks=3)
    tts.gate = asyncio.Event()
    sp = make(tmp_path, tts)
    link = FakeLink()
    task = asyncio.create_task(sp.say("Resposta livre.", link, personal=True))
    for _ in range(20):
        await asyncio.sleep(0)
    # o primeiro bloco já foi ao satélite antes de o provedor terminar
    assert link.events == ["start", "chunk"]
    tts.gate.set()
    await task
    assert link.plays[0][0] == [b"Resposta livre.#0;", b"Resposta livre.#1;", b"Resposta livre.#2;"]
    assert tts.calls == [("Resposta livre.", True)]
    assert list((tmp_path / "tts").glob("*.pcm")) == []  # texto livre não vai para o cache


async def test_voice_change_invalidates(tmp_path: Path) -> None:
    tts = FakeTts()
    voice = {"v": "nova"}
    sp = make(tmp_path, tts, voice=lambda: voice["v"])
    link = FakeLink()
    await sp.say("Cancelado.", link, personal=False)
    await sp.say("Cancelado.", link, personal=False)
    assert len(tts.calls) == 1
    voice["v"] = "shimmer"
    await sp.say("Cancelado.", link, personal=False)
    assert len(tts.calls) == 2


async def test_provider_error_does_not_raise_nor_cache(tmp_path: Path) -> None:
    tts = FakeTts(chunks=3, fail_after=1)
    sp = make(tmp_path, tts)
    link = FakeLink()
    await sp.say("Cancelado.", link, personal=True)
    assert link.events == ["start", "chunk", "stop"]  # audio-stop sai: satélite fecha o turno
    tts.fail_after = None
    await sp.say("Cancelado.", link, personal=True)
    assert len(tts.calls) == 2  # parcial não foi para o cache


async def test_provider_refuses_on_call(tmp_path: Path) -> None:
    class Refusing(FakeTts):
        def synthesize(self, text, *, personal):  # type: ignore[no-untyped-def]
            raise ProviderError("recusado")

    link = FakeLink()
    await make(tmp_path, Refusing()).say("Oi.", link, personal=True)
    assert link.events == ["start", "stop"]


async def test_warm_stops_on_error_and_auto_warm(tmp_path: Path) -> None:
    tts = FakeTts(fail_after=0)
    sp = make(tmp_path, tts)
    assert await sp.warm() == 0
    assert len(tts.calls) == 1
    tts2 = FakeTts()
    sp2 = PhraseSpeaker(
        tts2,
        phrases=Phrases.build(["Ok."]),
        cache=PhraseCache(tmp_path / "c2"),
    )
    await sp2.say("Texto qualquer.", FakeLink(), personal=True)
    await sp2._warm_task  # type: ignore[misc]
    assert ("Ok.", False) in tts2.calls
    await sp2.aclose()


def test_cache_lru_limit(tmp_path: Path) -> None:
    import os

    cache = PhraseCache(tmp_path, max_bytes=250)
    for i, k in enumerate("abc"):
        cache.put(k, bytes(100))
        os.utime(tmp_path / f"{k}.pcm", ns=(i * 10**9, i * 10**9))
    # "a" (o mais antigo) saiu ao entrar "c"
    assert "a" not in cache and "b" in cache and "c" in cache
    assert cache.size() <= 250
    assert cache.get("zz") is None


def test_callable_provider(tmp_path: Path) -> None:
    tts = FakeTts()
    sp = PhraseSpeaker(lambda: tts, phrases=Phrases.build(), cache=PhraseCache(tmp_path))
    assert sp.provider() is tts
    assert sp.key("Ok.") == sp.key("  ok. ")


@pytest.mark.live
async def test_live_tts_registry() -> None:  # pragma: no cover - precisa de chaves
    from magi.providers.registry import Registry  # noqa: F401

    pytest.skip("rodar manualmente com config real: PhraseSpeaker(registry.tts)")


# -- 1.23: frases fixas do núcleo no cache -----------------------------------------------------


def _say_constants() -> list[tuple[str, str]]:
    """Toda string de constante ``SAY_*`` (e valores de dicionários ``SAY_*``) em ``magi/``."""
    import ast

    root = Path(__file__).resolve().parents[2] / "magi"
    out: list[tuple[str, str]] = []
    for f in sorted(root.rglob("*.py")):
        for node in ast.parse(f.read_text(encoding="utf-8")).body:
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            target = node.targets[0]
            if not (isinstance(target, ast.Name) and target.id.lstrip("_").startswith("SAY_")):
                continue
            v = node.value
            values = [v] if isinstance(v, ast.Constant) else list(v.values) if isinstance(v, ast.Dict) else []
            out += [
                (f"{f.name}:{target.id}", c.value)
                for c in values
                if isinstance(c, ast.Constant) and isinstance(c.value, str)
            ]
    return out


def test_every_fixed_core_phrase_is_cacheable() -> None:
    import re

    phrases = Phrases.load()
    consts = _say_constants()
    assert len(consts) > 50
    missing = [
        (where, text) for where, text in consts if not phrases.cacheable(re.sub(r"\{\w+\}", "X", text))
    ]
    assert missing == [], "ponha estas frases em magi/core/phrases.yaml (fixed/lazy/templates)"


async def test_lazy_and_core_phrases_hit_cache_second_time(tmp_path: Path) -> None:
    from magi.core.turn import SAY_UNAVAILABLE

    tts = FakeTts()
    sp = PhraseSpeaker(
        tts,
        phrases=Phrases.load(),
        cache=PhraseCache(tmp_path / "tts", max_bytes=10_000_000),
        auto_warm=False,
    )
    link = FakeLink()
    for text in (SAY_UNAVAILABLE, "HUD fechado.", "Não tenho nada guardado sobre Zelda."):
        await sp.say(text, link, personal=False)
    first = len(tts.calls)
    assert first == 3
    for text in (SAY_UNAVAILABLE, "HUD fechado.", "Não tenho nada guardado sobre Zelda."):
        await sp.say(text, link, personal=False)
    assert len(tts.calls) == first  # zero chamadas ao TTS na segunda vez
    assert b"".join(link.plays[0][0]) == b"".join(link.plays[3][0])


async def test_lazy_phrases_are_not_pre_generated(tmp_path: Path) -> None:
    tts = FakeTts()
    phrases = Phrases.build(["Cancelado."], lazy=["HUD fechado."])
    sp = PhraseSpeaker(tts, phrases=phrases, cache=PhraseCache(tmp_path / "tts"), auto_warm=False)
    assert await sp.warm() == 1
    assert [c[0] for c in tts.calls] == ["Cancelado."]
    assert phrases.cacheable("hud fechado.")
