"""Validação real da transcrição enquanto fala (1.25). Só roda com ``MAGI_LIVE=1`` e a chave
``openai-1`` no keyring; custo ≈ US$ 0,005 por execução (teto do teste: US$ 0,03).

    MAGI_LIVE=1 uv run pytest -q -s -m live tests/providers/test_stt_stream_live.py

Manda ``tests/satellite/data/fala_ptbr.wav`` em pedaços de 80 ms no ritmo real e mede o tempo
entre o último pedaço (fim da fala) e o texto final; compara com o caminho antigo (WAV inteiro
enviado depois do fim)."""

from __future__ import annotations

import asyncio
import os
import statistics
import time
import wave
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from magi.common.config import parse_config
from magi.common.contracts import BudgetStatus, PcmFormat, ProviderTask, Usage
from magi.providers.registry import Registry

WAV = Path(__file__).parents[1] / "satellite" / "data" / "fala_ptbr.wav"
CHUNK_MS = 80
REPS = 3
CAP_USD = 0.03
PRICE_PER_MIN = {"gpt-transcribe": 0.0045, "gpt-live-transcribe": 0.017}
HINT = "Vocabulário: Condessa."


class _Budget:
    def __init__(self) -> None:
        self.usages: list[Usage] = []

    async def ensure_allowed(self, task: ProviderTask) -> None:
        return None

    async def record(self, usage: Usage) -> None:
        self.usages.append(usage)

    async def status(self) -> BudgetStatus:
        return BudgetStatus(0.0, 5.0)


def _registry(budget: _Budget, **opts: object) -> Registry:
    data = {
        "providers": {"openai": {"keys": ["openai-1"], "timeout_s": 30.0}},
        "tasks": {"stt": {"provider": "openai", "model": "gpt-transcribe", **opts}},
    }
    return Registry(parse_config(data), budget)


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("MAGI_LIVE"), reason="MAGI_LIVE=1 e chave openai-1 no keyring")
async def test_live_stream_vs_arquivo() -> None:  # pragma: no cover - chama a OpenAI
    with wave.open(str(WAV)) as w:
        fmt = PcmFormat(rate=w.getframerate(), width=w.getsampwidth(), channels=w.getnchannels())
        audio = w.readframes(w.getnframes())
    step = fmt.rate * fmt.width * fmt.channels * CHUNK_MS // 1000
    secs = len(audio) / (fmt.rate * fmt.width * fmt.channels)
    budget = _Budget()
    spent = 0.0
    results: dict[str, list[float]] = {}
    texts: dict[str, str] = {}

    async def realtime_chunks(marks: dict[str, float]) -> AsyncIterator[bytes]:
        t0 = time.perf_counter()
        for i in range(0, len(audio), step):
            target = t0 + (i // step) * CHUNK_MS / 1000
            await asyncio.sleep(max(0.0, target - time.perf_counter()))
            yield audio[i : i + step]
        marks["end"] = time.perf_counter()

    for model in ("gpt-transcribe", "gpt-live-transcribe"):
        stt = _registry(budget, streaming=True, streaming_model=model).stt()
        assert stt.streaming
        await stt.warm()
        for _ in range(REPS):
            spent += secs / 60 * PRICE_PER_MIN[model]
            assert spent <= CAP_USD
            marks: dict[str, float] = {}
            tr = await stt.stream_transcribe(realtime_chunks(marks), fmt, hint=HINT, personal=True)
            results.setdefault(f"stream {model}", []).append(time.perf_counter() - marks["end"])
            texts[f"stream {model}"] = tr.heard

    stt = _registry(budget).stt()
    await stt.warm()
    for _ in range(REPS):
        spent += secs / 60 * PRICE_PER_MIN["gpt-transcribe"]
        assert spent <= CAP_USD
        await asyncio.sleep(secs)  # mesma "fala" em tempo real; o relógio começa no fim
        t = time.perf_counter()
        tr = await stt.transcribe(audio, fmt, hint=HINT, personal=True)
        results.setdefault("arquivo gpt-transcribe", []).append(time.perf_counter() - t)
        texts["arquivo gpt-transcribe"] = tr.heard

    for name, xs in results.items():
        print(f"\n{name}: fim da fala -> texto {statistics.median(xs) * 1000:.0f} ms (mediana), "
              f"{[round(x * 1000) for x in xs]} ms · {texts[name]!r}")
    print(f"custo estimado US$ {spent:.4f}; uso registrado: "
          f"{sorted({(u.model, round(u.input_units, 2)) for u in budget.usages})}")
    assert all(texts.values())
    assert {u.model for u in budget.usages} == {"gpt-transcribe", "gpt-live-transcribe"}
