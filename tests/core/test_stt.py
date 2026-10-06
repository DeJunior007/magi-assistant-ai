"""Transcrição com dica (tarefa 1.5): provedor, catálogo e repositórios falsos."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

import pytest

from magi.common.contracts import (
    CAPTURE_FORMAT,
    STT_HINT_MAX_TOKENS,
    Correction,
    Game,
    PcmFormat,
    ProviderError,
    SttProvider,
    Transcript,
    TurnContext,
    VocabTerm,
    WakeSource,
)
from magi.core.stt import BASE_TERMS, HINT_PREFIX, HintedStt, HintTerm, build_hint, estimate_tokens
from magi.core.turn import TurnDeps, TurnPipeline

AUDIO = b"\x00\x01" * CAPTURE_FORMAT.rate  # 1 s de PCM falso


@dataclass
class FakeStt:
    text: str = "abre o dead cells"
    error: Exception | None = None
    name: str = "fake"
    model: str = "fake-stt"
    free_tier: bool = False
    calls: list[dict] = field(default_factory=list)

    async def transcribe(
        self, audio: bytes, fmt: PcmFormat, *, hint: str = "", language: str = "pt", personal: bool
    ) -> Transcript:
        self.calls.append({"audio": audio, "hint": hint, "language": language, "personal": personal})
        if self.error is not None:
            raise self.error
        return Transcript.raw(self.text, language)


class FakeCatalog:
    def __init__(self, games: list[Game]) -> None:
        self.games = games

    def all(self) -> list[Game]:
        return list(self.games)


class FakeVocab:
    def __init__(self, terms: list[VocabTerm]) -> None:
        self.terms = terms

    async def all(self, kind: str | None = None) -> list[VocabTerm]:
        return [t for t in self.terms if kind is None or t.kind == kind]


class FakeCorrections:
    def __init__(self, items: list[Correction]) -> None:
        self.items = items

    async def all(self) -> list[Correction]:
        return list(self.items)


class BrokenRepo:
    async def all(self, *args: object) -> list:
        raise RuntimeError("banco fora")


GAMES = [
    Game(588650, "Dead Cells", aliases=("deducels",)),
    Game(367520, "Hollow Knight"),
]
VOCAB = [VocabTerm("mó brisa", "slang", 0.5), VocabTerm("Magui", "name", 3.0)]
CORRS = [Correction("rolou night", "Hollow Knight", uses=4), Correction("sei lá", "Celeste", uses=0)]


def make(stt: FakeStt | None = None, **kw: object) -> tuple[HintedStt, FakeStt]:
    stt = stt or FakeStt()
    kw.setdefault("catalog", FakeCatalog(GAMES))
    kw.setdefault("vocab", FakeVocab(VOCAB))
    kw.setdefault("corrections", FakeCorrections(CORRS))
    kw.setdefault("base_terms", ())
    return HintedStt(stt, **kw), stt  # type: ignore[arg-type]


# --- guarda contra escrita em disco (R3.6) -------------------------------------------------

_WRITES: list[object] | None = None
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _audit(event: str, args: tuple) -> None:
    if _WRITES is None or event != "open":
        return
    path, mode, flags = (*args, None, None)[:3]
    writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
        isinstance(flags, int) and flags & _WRITE_FLAGS
    )
    if writing:
        _WRITES.append(path)


sys.addaudithook(_audit)


@pytest.fixture
def no_disk_writes():
    global _WRITES
    _WRITES = []
    try:
        yield _WRITES
    finally:
        _WRITES = None


# --- testes ----------------------------------------------------------------------------------


def test_protocol_and_delegation() -> None:
    hinted, stt = make()
    assert isinstance(hinted, SttProvider)
    assert (hinted.name, hinted.model, hinted.free_tier) == ("fake", "fake-stt", False)


async def test_transcribes_test_phrase_with_hint(no_disk_writes: list) -> None:
    hinted, stt = make()
    t = await hinted.transcribe(AUDIO, CAPTURE_FORMAT, personal=True)
    assert t == Transcript.raw("abre o dead cells")
    call = stt.calls[0]
    assert call["audio"] is AUDIO and call["personal"] is True and call["language"] == "pt"
    hint = call["hint"]
    assert hint.startswith(HINT_PREFIX)
    for term in ("Dead Cells", "Hollow Knight", "deducels", "mó brisa", "Magui", "Celeste"):
        assert term in hint
    # Prioridade: Hollow Knight (1+4 usos) > Magui (3.0) > ... > mó brisa (0.5)
    assert hint.index("Hollow Knight") < hint.index("Magui") < hint.index("Dead Cells")
    assert hint.index("deducels") < hint.index("mó brisa")
    assert hint.count("Hollow Knight") == 1  # sem duplicata entre correção e catálogo
    assert no_disk_writes == []


async def test_audit_guard_detects_writes(no_disk_writes: list, tmp_path) -> None:
    (tmp_path / "x.wav").write_bytes(b"1")
    assert no_disk_writes


async def test_hint_capped_at_200_tokens() -> None:
    games = [Game(i, f"Jogo Muito Comprido Número {i}") for i in range(300)]
    hinted, stt = make(catalog=FakeCatalog(games))
    await hinted.transcribe(AUDIO, CAPTURE_FORMAT, personal=True)
    hint = stt.calls[0]["hint"]
    assert estimate_tokens(hint) <= STT_HINT_MAX_TOKENS
    assert len(hint) > 600  # usa o orçamento, não só poucos termos
    assert "Hollow Knight" in hint and "Magui" in hint  # os de maior peso ficam


def test_build_hint_rules() -> None:
    assert build_hint([]) == ""
    assert estimate_tokens("a" * 7) == 2
    terms = [HintTerm("x" * 50, 2.0), HintTerm("  grande   termo ", 1.0), HintTerm("GRANDE termo", 5)]
    small = estimate_tokens(f"{HINT_PREFIX}GRANDE termo.")
    assert build_hint(terms, max_tokens=small) == f"{HINT_PREFIX}GRANDE termo."
    assert build_hint(terms, max_tokens=500) == f"{HINT_PREFIX}GRANDE termo, {'x' * 50}."


async def test_caller_hint_has_top_priority() -> None:
    hinted, stt = make()
    await hinted.transcribe(AUDIO, CAPTURE_FORMAT, hint="Baldur's Gate", personal=True)
    assert stt.calls[0]["hint"].startswith(f"{HINT_PREFIX}Baldur's Gate, Hollow Knight")


@pytest.mark.parametrize("error", [ProviderError("caiu"), TimeoutError(), ValueError("json")])
async def test_provider_failure_returns_empty(error: Exception) -> None:
    hinted, _ = make(FakeStt(error=error))
    t = await hinted.transcribe(AUDIO, CAPTURE_FORMAT, personal=True)
    assert t.is_empty and t.heard == ""


@pytest.mark.parametrize("text", ["", "   \n "])
async def test_empty_text_returns_empty(text: str) -> None:
    hinted, _ = make(FakeStt(text=text))
    assert (await hinted.transcribe(AUDIO, CAPTURE_FORMAT, personal=True)).is_empty


async def test_no_audio_skips_provider() -> None:
    hinted, stt = make()
    assert (await hinted.transcribe(b"", CAPTURE_FORMAT, personal=True)).is_empty
    assert stt.calls == []


async def test_broken_sources_and_no_sources() -> None:
    hinted, stt = make(vocab=BrokenRepo(), corrections=BrokenRepo())
    t = await hinted.transcribe(AUDIO, CAPTURE_FORMAT, personal=True)
    assert t.final == "abre o dead cells"
    assert stt.calls[0]["hint"] == f"{HINT_PREFIX}Dead Cells, Hollow Knight, deducels."
    bare = HintedStt(FakeStt())
    assert (await bare.transcribe(AUDIO, CAPTURE_FORMAT, personal=True)).final
    assert bare.inner.calls[0]["hint"] == f"{HINT_PREFIX}{', '.join(BASE_TERMS)}."  # type: ignore[attr-defined]
    nothing = HintedStt(FakeStt(), base_terms=())
    assert (await nothing.transcribe(AUDIO, CAPTURE_FORMAT, personal=True)).final
    assert nothing.inner.calls[0]["hint"] == ""  # type: ignore[attr-defined]


async def test_provider_factory_follows_config_reload() -> None:
    current = {"stt": FakeStt(text="primeiro")}
    hinted = HintedStt(lambda: current["stt"])
    assert (await hinted.transcribe(AUDIO, CAPTURE_FORMAT, personal=True)).final == "primeiro"
    current["stt"] = FakeStt(text="segundo", name="outro")
    assert (await hinted.transcribe(AUDIO, CAPTURE_FORMAT, personal=True)).final == "segundo"
    assert hinted.name == "outro"


async def test_plugs_into_turn_pipeline(no_disk_writes: list) -> None:
    hinted, _ = make()
    pipeline = TurnPipeline(TurnDeps(stt=hinted))
    ctx = TurnContext("pc", WakeSource.PTT, datetime.now())
    t = await pipeline.transcribe(AUDIO, CAPTURE_FORMAT, ctx)
    assert t.final == "abre o dead cells"
    hinted.inner.error = ProviderError("x")  # type: ignore[attr-defined]
    assert (await pipeline.transcribe(AUDIO, CAPTURE_FORMAT, ctx)).is_empty
    assert no_disk_writes == []


@pytest.mark.live
async def test_live_registry_stt() -> None:  # pragma: no cover - precisa de chaves
    pytest.skip("transcrição real: rodar manualmente com áudio gravado em memória")
