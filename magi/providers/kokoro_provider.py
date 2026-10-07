"""Voz local com o Kokoro (ONNX, CPU): sem rede, sem custo e sem chave.

Config::

    [providers.kokoro]
    local = true                    # sem chave no keyring
    model_dir = "~/.cache/magi/kokoro"   # kokoro-v1.0.onnx + voices-v1.0.bin

    [tasks]
    tts = { provider = "kokoro", model = "kokoro-v1.0", voice = "bf_isabella", lang = "en-gb" }

``voice`` aceita uma voz do arquivo (``bf_isabella``, ``pf_dora``…) ou uma mistura
``"bf_isabella:0.7,pf_dora:0.3"``. ``speed`` (padrão 1.0). A síntese roda numa thread (cerca de 3×
mais rápida que o tempo real numa CPU de mesa) e sai em PCM 24 kHz 16 bits mono, o mesmo formato
do TTS da OpenAI. O modelo carrega uma vez (``warm``) e fica na memória.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from magi.common.config import ProviderConfig
from magi.common.contracts import ApiKey, PcmFormat, ProviderError
from magi.providers.base import CallCtx

log = logging.getLogger(__name__)

FORMAT = PcmFormat(rate=24_000, width=2, channels=1)
CHUNK = 4_800  # 0,1 s de áudio por pedaço
DEFAULT_DIR = "~/.cache/magi/kokoro"


class KokoroBackend:
    #: Sintetiza a frase inteira antes do primeiro pedaço: a duração sai antes de tocar (legenda).
    whole_sentence = True

    def __init__(self, pcfg: ProviderConfig) -> None:
        self.dir = Path(str(pcfg.options.get("model_dir", DEFAULT_DIR))).expanduser()
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from kokoro_onnx import Kokoro

                onnx, voices = self.dir / "kokoro-v1.0.onnx", self.dir / "voices-v1.0.bin"
                if not onnx.exists() or not voices.exists():
                    raise ProviderError(f"kokoro: modelo não encontrado em {self.dir}")
                self._model = Kokoro(str(onnx), str(voices))
                log.info("kokoro: modelo carregado de %s", self.dir)
            return self._model

    def _voice(self, model: Any, spec: str) -> Any:
        if ":" not in spec:
            return spec
        mix = None
        for part in spec.split(","):
            name, weight = part.split(":")
            style = float(weight) * model.get_voice_style(name.strip())
            mix = style if mix is None else mix + style
        return mix

    def _synth(self, ctx: CallCtx, text: str) -> bytes:
        import numpy as np

        model = self._load()
        voice = self._voice(model, str(ctx.options.get("voice", "bf_isabella")))
        audio, rate = model.create(text, voice=voice, speed=float(ctx.options.get("speed", 1.0)),
                                   lang=str(ctx.options.get("lang", "en-gb")))
        if rate != FORMAT.rate:
            raise ProviderError(f"kokoro: taxa {rate} inesperada (esperava {FORMAT.rate})")
        return (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()

    # -- contrato Backend ---------------------------------------------------------------------

    def tts_format(self, ctx: CallCtx) -> PcmFormat:
        return FORMAT

    async def synthesize(self, key: ApiKey, ctx: CallCtx, text: str) -> AsyncIterator[bytes]:
        pcm = await asyncio.to_thread(self._synth, ctx, text)
        for i in range(0, len(pcm), CHUNK):
            yield pcm[i: i + CHUNK]

    async def warm(self, key: ApiKey, ctx: CallCtx) -> None:
        await asyncio.to_thread(self._load)

    async def transcribe(self, *a: Any, **k: Any) -> Any:
        raise ProviderError("kokoro só faz voz (tts)")

    async def chat(self, *a: Any, **k: Any) -> Any:
        raise ProviderError("kokoro só faz voz (tts)")

    async def ask(self, *a: Any, **k: Any) -> Any:
        raise ProviderError("kokoro só faz voz (tts)")

    def embed_dimensions(self, ctx: CallCtx) -> int:
        raise ProviderError("kokoro só faz voz (tts)")

    async def embed(self, *a: Any, **k: Any) -> Any:
        raise ProviderError("kokoro só faz voz (tts)")
