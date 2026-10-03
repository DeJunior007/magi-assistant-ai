"""VAD do satélite: Silero VAD (ONNX) e fim de fala (§5, R1.5, R5.4).

O VAD só roda depois da ativação (wake word, atalho ou ``magi-listen``); no ocioso o custo é
zero. ``Endpointer`` decide quando a gravação acaba:

- fala seguida de ``VAD_SILENCE_MS`` (700 ms) de silêncio -> ``vad``;
- ``MAX_RECORDING_MS`` (15 s) de gravação -> ``max_length``;
- ninguém falou em ``no_speech_ms`` -> ``no_speech`` (``magi-listen`` usa o ``timeout_ms`` do
  pedido; após o wake word, ``WAKE_NO_SPEECH_MS``).

O tempo é contado em áudio (blocos recebidos), não no relógio: o resultado é o mesmo em tempo
real e nos testes com arquivo.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from magi.common.contracts import (
    AUDIO_RATE,
    CHUNK_MS,
    MAX_RECORDING_MS,
    VAD_SILENCE_MS,
    AudioEndReason,
    ListenRequest,
)

#: Modelo oficial do Silero VAD (v5, 16 kHz, janelas de 512 amostras).
VAD_MODEL_NAME = "silero_vad.onnx"
VAD_MODEL_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"

#: Janela do Silero a 16 kHz e contexto que o v5 espera antes de cada janela.
WINDOW_SAMPLES = 512
CONTEXT_SAMPLES = 64

DEFAULT_THRESHOLD = 0.5
#: Histerese: durante a fala, o bloco só vira silêncio abaixo deste valor (como no Silero).
DEFAULT_NEG_THRESHOLD = 0.35
#: Após o "Condessa", se ninguém falar neste prazo a gravação termina com ``no_speech``.
WAKE_NO_SPEECH_MS = 5_000


def default_vad_dir() -> Path:
    """``$XDG_DATA_HOME/magi/models/vad`` (padrão ``~/.local/share``)."""
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(base).expanduser() / "magi" / "models" / "vad"


def download_vad_model(models_dir: Path | None = None, url: str = VAD_MODEL_URL) -> Path:
    """Baixa o ``silero_vad.onnx`` oficial (GitHub) para ``models_dir``; não baixa de novo."""
    models_dir = models_dir or default_vad_dir()
    models_dir.mkdir(parents=True, exist_ok=True)
    dest = models_dir / VAD_MODEL_NAME
    if dest.exists():
        return dest
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 (URL fixa https)
    tmp.replace(dest)
    return dest


@runtime_checkable
class SpeechDetector(Protocol):
    """Probabilidade de fala por bloco de PCM16 mono 16 kHz."""

    def process(self, block: np.ndarray) -> float: ...

    def reset(self) -> None: ...


class SileroVad:
    """Silero VAD v5 em onnxruntime, 1 thread. Bloco de 80 ms = 2,5 janelas de 512 amostras:
    o resto fica para o próximo bloco; a nota do bloco é a maior das janelas fechadas nele."""

    name = "silero"

    def __init__(self, model_path: str | os.PathLike[str] | None = None) -> None:
        import onnxruntime as ort

        path = Path(model_path) if model_path else default_vad_dir() / VAD_MODEL_NAME
        if not path.exists():
            raise FileNotFoundError(
                f"modelo do Silero VAD não está em {path}; rode `uv run magi-satellite --download-models`"
            )
        from magi.satellite.onnx import session_options

        self._session = ort.InferenceSession(
            str(path), sess_options=session_options(ort), providers=["CPUExecutionProvider"]
        )
        self._sr = np.array(AUDIO_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT_SAMPLES, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)
        self._last = 0.0

    def _window(self, x: np.ndarray) -> float:
        inp = np.concatenate([self._context, x])[np.newaxis, :]
        out, self._state = self._session.run(None, {"input": inp, "state": self._state, "sr": self._sr})
        self._context = x[-CONTEXT_SAMPLES:]
        return float(out[0, 0])

    def process(self, block: np.ndarray) -> float:
        x = np.concatenate([self._pending, block.astype(np.float32) / 32768.0])
        best: float | None = None
        n = len(x) // WINDOW_SAMPLES
        for i in range(n):
            p = self._window(x[i * WINDOW_SAMPLES : (i + 1) * WINDOW_SAMPLES])
            best = p if best is None else max(best, p)
        self._pending = x[n * WINDOW_SAMPLES :]
        if best is not None:
            self._last = best
        return self._last


def load_vad(models_dir: Path | None = None) -> SileroVad:
    """Carrega o Silero VAD de ``models_dir`` (padrão ``default_vad_dir()``)."""
    return SileroVad((models_dir or default_vad_dir()) / VAD_MODEL_NAME)


class Endpointer:
    """Decide o fim da gravação bloco a bloco (R1.5, R5.4). Um por gravação.

    Depois de ``feed``, ``voiced`` diz se o bloco tinha voz (usado na medida de tom).
    """

    def __init__(
        self,
        vad: SpeechDetector,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        neg_threshold: float = DEFAULT_NEG_THRESHOLD,
        silence_ms: int = VAD_SILENCE_MS,
        max_ms: int = MAX_RECORDING_MS,
        no_speech_ms: int | None = WAKE_NO_SPEECH_MS,
        block_ms: int = CHUNK_MS,
    ) -> None:
        self.vad = vad
        self.threshold = threshold
        self.neg_threshold = min(neg_threshold, threshold)
        self.silence_ms = silence_ms
        self.max_ms = max_ms
        self.no_speech_ms = no_speech_ms
        self.block_ms = block_ms
        self.elapsed_ms = 0
        self.silence_run_ms = 0
        self.heard_speech = False
        self.voiced = False
        self.last_prob = 0.0
        self.reason: AudioEndReason | None = None
        vad.reset()

    @classmethod
    def for_listen(cls, vad: SpeechDetector, req: ListenRequest, **kw: object) -> Endpointer:
        """Escuta curta do ``magi-listen``: ``no_speech`` se ninguém falar em ``timeout_ms``."""
        return cls(vad, no_speech_ms=req.timeout_ms, **kw)  # type: ignore[arg-type]

    def feed(self, block: bytes | np.ndarray) -> AudioEndReason | None:
        """Processa um bloco; devolve o motivo do fim quando a gravação deve acabar."""
        if self.reason is not None:
            return self.reason
        pcm = np.frombuffer(block, dtype="<i2") if isinstance(block, bytes | bytearray) else block
        prob = float(self.vad.process(pcm))
        self.last_prob = prob
        self.elapsed_ms += self.block_ms
        self.voiced = prob >= (self.neg_threshold if self.heard_speech else self.threshold)
        if self.voiced:
            self.heard_speech = True
            self.silence_run_ms = 0
        elif self.heard_speech:
            self.silence_run_ms += self.block_ms
        if self.heard_speech and self.silence_run_ms >= self.silence_ms:
            self.reason = AudioEndReason.VAD
        elif self.elapsed_ms >= self.max_ms:
            self.reason = AudioEndReason.MAX_LENGTH
        elif not self.heard_speech and self.no_speech_ms is not None and self.elapsed_ms >= self.no_speech_ms:
            self.reason = AudioEndReason.NO_SPEECH
        return self.reason
