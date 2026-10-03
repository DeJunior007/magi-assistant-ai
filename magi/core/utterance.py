"""Preparo da fala antes do STT (1.26): ganho automático leve e cópia em WAV para diagnóstico.

- ``normalize_pcm16``: leva o nível da fala para perto de ``TARGET_DBFS`` com ganho limitado a
  ``MAX_GAIN_DB`` e nunca acima do que deixa o pico em ``PEAK_CEILING`` (sem clipar). Só aumenta;
  áudio já forte, silêncio ou ruído baixo demais passam como vieram.
- ``UtteranceSaver``: com ``[debug] save_audio = true``, grava cada fala enviada ao STT em
  ``~/.cache/magi/utterances/`` (mantém as ``max_files`` mais novas) para ouvir depois.
"""

from __future__ import annotations

import logging
import time
import wave
from pathlib import Path

import numpy as np

from magi.common.contracts import PcmFormat

log = logging.getLogger(__name__)

#: Nível de fala desejado (rms dos trechos altos) e limites do ganho.
TARGET_DBFS = -20.0
MAX_GAIN_DB = 12.0
PEAK_CEILING = 0.89  # -1 dBFS
#: Abaixo disto não há fala que valha amplificar (só ruído de fundo).
MIN_SPEECH_DBFS = -55.0
_FRAME_MS = 20


def speech_level_dbfs(pcm: np.ndarray, rate: int) -> float:
    """Nível da fala: rms do percentil 90 dos quadros de 20 ms (ignora pausas). -120 se vazio."""
    n = max(1, rate * _FRAME_MS // 1000)
    if len(pcm) < n:
        return -120.0
    x = pcm[: len(pcm) // n * n].astype(np.float32).reshape(-1, n) / 32768.0
    rms = np.sqrt(np.mean(x * x, axis=1))
    level = float(np.percentile(rms, 90))
    return 20 * np.log10(level) if level > 1e-6 else -120.0


def normalize_pcm16(audio: bytes, fmt: PcmFormat) -> tuple[bytes, float]:
    """Devolve (áudio, ganho em dB aplicado). Só PCM16; outros formatos passam intactos."""
    if fmt.width != 2 or not audio:
        return audio, 0.0
    pcm = np.frombuffer(audio[: len(audio) // 2 * 2], dtype="<i2")
    level = speech_level_dbfs(pcm, fmt.rate * fmt.channels)
    if level <= MIN_SPEECH_DBFS or level >= TARGET_DBFS:
        return audio, 0.0
    peak = int(np.abs(pcm.astype(np.int32)).max())
    gain_db = min(TARGET_DBFS - level, MAX_GAIN_DB)
    if peak:
        gain_db = min(gain_db, 20 * np.log10(PEAK_CEILING * 32767 / peak))
    if gain_db < 0.5:
        return audio, 0.0
    out = np.clip(np.rint(pcm.astype(np.float32) * 10 ** (gain_db / 20)), -32768, 32767).astype("<i2")
    return out.tobytes(), round(float(gain_db), 1)


class UtteranceSaver:
    """Grava as falas em WAV numerado pela hora; apaga as mais antigas além de ``max_files``."""

    def __init__(self, directory: Path, max_files: int = 50) -> None:
        self.directory = Path(directory).expanduser()
        self.max_files = max_files

    def save(self, audio: bytes, fmt: PcmFormat, label: str = "") -> Path | None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.monotonic_ns() % 1_000_000:06d}"
            path = self.directory / f"{stamp}{'-' + label if label else ''}.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(fmt.channels)
                w.setsampwidth(fmt.width)
                w.setframerate(fmt.rate)
                w.writeframes(audio)
            for old in sorted(self.directory.glob("*.wav"))[: -self.max_files]:
                old.unlink(missing_ok=True)
            return path
        except OSError as e:
            log.warning("não deu para salvar a fala em %s: %s", self.directory, e)
            return None
