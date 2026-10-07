from __future__ import annotations

import numpy as np

from magi.common.config import ProviderConfig
from magi.common.contracts import ApiKey, ProviderTask
from magi.providers.base import CallCtx
from magi.providers.kokoro_provider import FORMAT, KokoroBackend


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_voice_style(self, name: str):
        return np.full(4, {"bf_isabella": 1.0, "pf_dora": 3.0}[name])

    def create(self, text, voice, speed, lang):
        self.calls.append((text, voice if isinstance(voice, str) else voice.tolist(), speed, lang))
        return np.array([0.0, 0.5, -0.5, 2.0], dtype=np.float32), 24_000


def make(options: dict) -> tuple[KokoroBackend, FakeModel, CallCtx]:
    b = KokoroBackend(ProviderConfig("kokoro", (), options={"local": True}))
    fake = FakeModel()
    b._model = fake
    ctx = CallCtx(provider="kokoro", task=ProviderTask.TTS, model="kokoro-v1.0", options=options)
    return b, fake, ctx


async def test_isabella_em_ingles_vira_pcm_16_bits():
    b, fake, ctx = make({"voice": "bf_isabella", "lang": "en-gb"})
    key = ApiKey(provider="kokoro", name="local", secret="")
    pcm = b"".join([c async for c in b.synthesize(key, ctx, "Eight, Pedro.")])
    assert b.tts_format(ctx) == FORMAT
    assert np.frombuffer(pcm, "<i2").tolist() == [0, 16383, -16383, 32767]  # clip em 1.0
    assert fake.calls == [("Eight, Pedro.", "bf_isabella", 1.0, "en-gb")]


async def test_mistura_de_vozes():
    b, fake, ctx = make({"voice": "bf_isabella:0.7,pf_dora:0.3", "lang": "pt-br"})
    key = ApiKey(provider="kokoro", name="local", secret="")
    _ = [c async for c in b.synthesize(key, ctx, "Oi")]
    assert np.allclose(fake.calls[0][1], [1.6] * 4)  # 0.7*1 + 0.3*3
