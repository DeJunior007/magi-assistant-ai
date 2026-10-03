"""Funções comuns do kit do wake word: caminhos, corte de silêncio e aumento de dados.

Todo áudio aqui é PCM16 mono 16 kHz (``np.int16``), o mesmo formato da captura do satélite.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from magi.common.contracts import AUDIO_RATE
from magi.satellite.capture import read_wav, resample, write_wav

__all__ = ["AUDIO_RATE", "read_wav", "write_wav", "resample"]

#: Janela que o classificador vê: 16 embeddings do openWakeWord = 2,0 s de áudio.
WINDOW_SAMPLES = 2 * AUDIO_RATE
N_FRAMES = 16
EMB_DIM = 96


#: Palavra de ativação padrão do kit: nome do modelo (``condessa.onnx``) e da pasta de dados.
DEFAULT_WORD = "condessa"


def data_root() -> Path:
    """``$XDG_DATA_HOME/magi/wakeword-data`` (padrão ``~/.local/share``)."""
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(base).expanduser() / "magi" / "wakeword-data"


def data_dir(word: str = DEFAULT_WORD) -> Path:
    """Dados de uma palavra: ``.../magi/wakeword-data/<word>/{positive,negative,noise,...}``."""
    return data_root() / word


def train_dir() -> Path:
    """Área de trabalho do treino (atributos baixados, cache): ``.../magi/wakeword-train``."""
    return data_root().parent / "wakeword-train"


def list_wavs(*dirs: Path) -> list[Path]:
    out: list[Path] = []
    for d in dirs:
        if d.is_dir():
            out.extend(sorted(d.rglob("*.wav")))
    return out


def next_index(d: Path, prefix: str) -> int:
    """Próximo número livre em ``d`` para arquivos ``{prefix}_NNN.wav``."""
    nums = []
    for p in d.glob(f"{prefix}_*.wav"):
        tail = p.stem.rsplit("_", 1)[-1]
        if tail.isdigit():
            nums.append(int(tail))
    return max(nums, default=0) + 1


def dbfs(pcm: np.ndarray) -> float:
    x = pcm.astype(np.float64)
    ms = float(np.mean(x * x)) / (32768.0**2) if len(x) else 0.0
    return 10.0 * np.log10(ms) if ms > 1e-12 else -120.0


def trim_silence(
    pcm: np.ndarray,
    *,
    rate: int = AUDIO_RATE,
    floor_dbfs: float = -50.0,
    rel_db: float = 35.0,
    pad_ms: int = 150,
    frame_ms: int = 10,
) -> np.ndarray:
    """Corta o silêncio das bordas. Um quadro de 10 ms é "som" se estiver acima de
    ``max(floor_dbfs, pico - rel_db)``. Mantém ``pad_ms`` de folga de cada lado.
    Devolve um array vazio se não houver som nenhum."""
    pcm = np.asarray(pcm, dtype=np.int16)
    n = rate * frame_ms // 1000
    nfr = len(pcm) // n
    if nfr == 0:
        return pcm[:0]
    frames = pcm[: nfr * n].astype(np.float64).reshape(nfr, n)
    ms = np.mean(frames * frames, axis=1) / (32768.0**2)
    db = 10.0 * np.log10(np.maximum(ms, 1e-12))
    thr = max(floor_dbfs, float(db.max()) - rel_db)
    loud = np.flatnonzero(db >= thr)
    if len(loud) == 0 or db.max() < floor_dbfs:
        return pcm[:0]
    pad = rate * pad_ms // 1000
    start = max(0, loud[0] * n - pad)
    end = min(len(pcm), (loud[-1] + 1) * n + pad)
    return pcm[start:end]


# ---------------------------------------------------------------------------------------------
# Aumento de dados
# ---------------------------------------------------------------------------------------------


def to_i16(x: np.ndarray) -> np.ndarray:
    return np.clip(np.round(x), -32768, 32767).astype(np.int16)


def apply_gain_db(pcm: np.ndarray, gain_db: float) -> np.ndarray:
    return to_i16(pcm.astype(np.float32) * (10.0 ** (gain_db / 20.0)))


def change_speed(pcm: np.ndarray, factor: float) -> np.ndarray:
    """Acelera (``factor`` > 1) ou desacelera o áudio por reamostragem (muda o tom junto)."""
    if abs(factor - 1.0) < 1e-3:
        return pcm
    src = int(round(AUDIO_RATE * factor))
    return resample(pcm, src, AUDIO_RATE)


def synthetic_rir(rng: np.random.Generator, rt60: float, rate: int = AUDIO_RATE) -> np.ndarray:
    """Resposta ao impulso de sala sintética: ruído com decaimento exponencial (RT60 em s)."""
    n = max(1, int(rt60 * rate))
    t = np.arange(n) / rate
    rir = rng.standard_normal(n) * np.exp(-6.9 * t / rt60)
    rir[0] = 1.0 / 0.3  # som direto dominante
    return rir / np.sqrt(np.sum(rir**2))


def add_reverb(pcm: np.ndarray, rir: np.ndarray) -> np.ndarray:
    from scipy.signal import fftconvolve

    x = pcm.astype(np.float32)
    y = fftconvolve(x, rir.astype(np.float32))[: len(x)]
    peak_in, peak_out = np.abs(x).max() or 1.0, np.abs(y).max() or 1.0
    return to_i16(y * (peak_in / peak_out))


def mix_at_snr(
    signal: np.ndarray, noise: np.ndarray, snr_db: float, rng: np.random.Generator
) -> np.ndarray:
    """Soma ``noise`` (trecho aleatório, repetido se curto) a ``signal`` na SNR pedida."""
    if len(noise) == 0:
        return signal
    if len(noise) < len(signal):
        noise = np.tile(noise, int(np.ceil(len(signal) / len(noise))))
    off = int(rng.integers(0, len(noise) - len(signal) + 1))
    nz = noise[off : off + len(signal)].astype(np.float32)
    s = signal.astype(np.float32)
    active = s[s != 0]  # SNR medida só onde há fala (a janela tem silêncio em volta)
    ps = float(np.mean(active * active)) if len(active) else 0.0
    pn = float(np.mean(nz * nz))
    if pn < 1e-9 or ps < 1e-9:
        return signal
    k = np.sqrt(ps / (pn * 10.0 ** (snr_db / 10.0)))
    return to_i16(s + k * nz)


def dither(pcm: np.ndarray, rng: np.random.Generator, level_dbfs=(-75.0, -55.0)) -> np.ndarray:
    """Soma ruído branco fraco. Silêncio digital (zeros) nunca aparece no microfone e, se só
    existisse em volta das positivas, o modelo aprenderia que "silêncio perfeito" = wake word."""
    std = 32768.0 * 10.0 ** (float(rng.uniform(*level_dbfs)) / 20.0)
    return to_i16(pcm.astype(np.float32) + rng.standard_normal(len(pcm)).astype(np.float32) * std)


def place_in_window(
    clip: np.ndarray, rng: np.random.Generator, window: int = WINDOW_SAMPLES, end_jitter_s=(0.05, 0.5)
) -> np.ndarray:
    """Põe ``clip`` numa janela de ``window`` amostras terminando entre 0,05 e 0,5 s antes do fim
    (o detector vê a palavra recém-terminada). Corta o começo se o clipe for maior que a janela."""
    out = np.zeros(window, np.int16)
    lo, hi = (int(s * AUDIO_RATE) for s in end_jitter_s)
    end = window - int(rng.integers(lo, hi + 1))
    clip = clip[-end:] if len(clip) > end else clip
    out[end - len(clip) : end] = clip
    return out


def augment(
    clip: np.ndarray,
    rng: np.random.Generator,
    noises: list[np.ndarray],
    *,
    p_reverb: float = 0.5,
    p_noise: float = 0.8,
    snr_db=(3.0, 20.0),
    gain_db=(-12.0, 6.0),
    speed=(0.9, 1.1),
    window: int | None = WINDOW_SAMPLES,
) -> np.ndarray:
    """Uma variação aleatória do clipe: velocidade, reverb, ganho, posição na janela de 2 s
    (``window=None`` mantém o tamanho, para negativos) e ruído de fundo em toda a janela."""
    x = change_speed(clip, float(rng.uniform(*speed)))
    if rng.random() < p_reverb:
        x = add_reverb(x, synthetic_rir(rng, float(rng.uniform(0.15, 0.7))))
    x = apply_gain_db(x, float(rng.uniform(*gain_db)))
    if window is not None:
        x = place_in_window(x, rng, window)
    x = dither(x, rng)
    if noises and rng.random() < p_noise:
        x = mix_at_snr(x, noises[int(rng.integers(len(noises)))], float(rng.uniform(*snr_db)), rng)
    return x
