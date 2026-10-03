"""Detecção do wake word "Ei Magui" (§5, R1.1, R1.2, R1.6).

- ``WakeDetector``: interface de um modelo que dá uma nota 0..1 por bloco de 80 ms.
- ``OpenWakeWordDetector``: backend openWakeWord (só ONNX; ``tflite-runtime`` não tem wheel para
  Python 3.12). Enquanto o modelo próprio do spike S4 não existe, usa um modelo pré-treinado
  provisório (padrão ``hey_jarvis``); para trocar, aponte ``wake_model`` para ``ei_magui.onnx``.
- ``WakeSpotter``: aplica limiar (recarregável), paciência (blocos seguidos acima do limiar) e
  um intervalo de recarga depois de cada ativação.
- ``WakeSettings``: lido da seção ``[satellite]`` do ``config.toml``.
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np

from magi.common.contracts import CHUNK_SAMPLES

log = logging.getLogger(__name__)

#: Modelo provisório até o spike S4 entregar ``ei_magui.onnx``.
DEFAULT_WAKE_MODEL = "hey_jarvis"
DEFAULT_THRESHOLD = 0.5
DEFAULT_COOLDOWN_MS = 2000
DEFAULT_PATIENCE = 1
#: Portão de energia (RNF-01): abaixo disso o bloco é silêncio e o modelo não roda. Fala normal
#: no headset fica em -35..-20 dBFS; o ruído de fundo medido na 1.1 foi ~-63 dBFS.
DEFAULT_GATE_DBFS = -50.0
#: Blocos guardados durante o silêncio e passados ao modelo quando o portão abre (contexto de
#: 1,28 s que o openWakeWord precisa) e quanto tempo o portão fica aberto depois do último som.
GATE_PREROLL_BLOCKS = 16
GATE_HANGOVER_MS = 2000
#: Áudio bruto que o pré-processador do openWakeWord precisa guardar: até 4 blocos por chamada
#: mais 3 quadros de 10 ms de contexto do espectrograma.
RAW_BUFFER_SAMPLES = 4 * CHUNK_SAMPLES + 480
#: Modelos de atributos do openWakeWord (comuns a todos os wake words).
FEATURE_MODELS = ("melspectrogram.onnx", "embedding_model.onnx")


def default_models_dir() -> Path:
    """``$XDG_DATA_HOME/magi/models/wakeword`` (padrão ``~/.local/share``)."""
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(base).expanduser() / "magi" / "models" / "wakeword"


@runtime_checkable
class WakeDetector(Protocol):
    """Modelo de wake word. ``process`` recebe um bloco de 80 ms (``int16``, 1280 amostras) e
    devolve a nota 0..1 do bloco. ``reset`` limpa o estado interno (janela de áudio)."""

    name: str

    def process(self, block: np.ndarray) -> float: ...

    def reset(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Detection:
    score: float
    timestamp_ms: int


def block_dbfs(pcm: np.ndarray) -> float:
    """Nível RMS do bloco PCM16 em dBFS (silêncio digital = -120)."""
    x = pcm.astype(np.float32)
    ms = float(np.dot(x, x)) / max(1, len(x)) / (32768.0 * 32768.0)
    return 10.0 * np.log10(ms) if ms > 1e-12 else -120.0


class WakeSpotter:
    """Decide quando houve ativação a partir das notas do detector (R1.2, R1.6).

    Ativa quando ``patience`` blocos seguidos têm nota >= ``threshold``. Depois de uma ativação,
    ignora o áudio por ``cooldown_ms`` (a mesma fala não ativa duas vezes) e zera o detector.
    Portão de energia (RNF-01): blocos abaixo de ``gate_dbfs`` não passam pelo modelo; quando o
    som volta, os últimos 1,28 s de silêncio são entregues antes, para o modelo ter contexto.
    ``gate_dbfs=None`` desliga o portão.
    ``threshold`` pode ser trocado a qualquer momento (recarga do config).
    """

    def __init__(
        self,
        detector: WakeDetector,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        patience: int = DEFAULT_PATIENCE,
        cooldown_ms: int = DEFAULT_COOLDOWN_MS,
        enabled: bool = True,
        gate_dbfs: float | None = DEFAULT_GATE_DBFS,
    ) -> None:
        self.detector = detector
        self.threshold = threshold
        self.patience = max(1, patience)
        self.cooldown_ms = cooldown_ms
        self.enabled = enabled
        self.gate_dbfs = gate_dbfs
        self.skipped = 0  # blocos não processados pelo portão (diagnóstico)
        self._preroll: deque[np.ndarray] = deque(maxlen=GATE_PREROLL_BLOCKS)
        self._open_until = -1.0
        self.last_score = 0.0
        self._streak = 0
        self._streak_max = 0.0
        self._mute_until = 0.0

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        v = float(value)
        if not 0.0 < v <= 1.0:
            raise ValueError(f"limiar do wake word fora de (0, 1]: {v}")
        self._threshold = v

    def apply(self, settings: WakeSettings) -> None:
        """Aplica limiar, paciência e recarga de um ``WakeSettings`` recarregado."""
        if settings.threshold != self.threshold:
            log.info("limiar do wake word: %.2f -> %.2f", self.threshold, settings.threshold)
        self.threshold = settings.threshold
        self.patience = max(1, settings.patience)
        self.cooldown_ms = settings.cooldown_ms
        self.gate_dbfs = settings.gate_dbfs

    def feed(self, block: bytes | np.ndarray, now: float | None = None) -> Detection | None:
        """Processa um bloco de 80 ms. ``now`` em segundos (monotônico) para testes."""
        if not self.enabled:
            return None
        now = time.monotonic() if now is None else now
        pcm = np.frombuffer(block, dtype="<i2") if isinstance(block, bytes | bytearray) else block
        if self.gate_dbfs is not None:
            if block_dbfs(pcm) >= self.gate_dbfs:
                if now >= self._open_until and self._preroll:
                    # portão abrindo: o modelo recebe o silêncio recente de uma vez (sem decidir nele)
                    self.detector.process(np.concatenate(self._preroll))
                    self._preroll.clear()
                self._open_until = now + GATE_HANGOVER_MS / 1000
            elif now >= self._open_until:
                self._preroll.append(pcm)
                self.skipped += 1
                self.last_score = 0.0
                self._streak = 0
                return None
        score = float(self.detector.process(pcm))
        self.last_score = score
        if now < self._mute_until:
            return None
        if score >= self.threshold:
            self._streak += 1
            self._streak_max = max(self._streak_max, score)
        else:
            self._streak = 0
            self._streak_max = 0.0
        if self._streak < self.patience:
            return None
        best = self._streak_max
        self._streak = 0
        self._streak_max = 0.0
        self._mute_until = now + self.cooldown_ms / 1000
        self.detector.reset()
        return Detection(score=best, timestamp_ms=int(time.time() * 1000))


# ---------------------------------------------------------------------------------------------
# Backend openWakeWord
# ---------------------------------------------------------------------------------------------


def resolve_model(model: str | os.PathLike[str], models_dir: Path) -> Path:
    """Acha o ``.onnx`` do wake word: caminho direto, ou nome (``hey_jarvis`` ->
    ``hey_jarvis_v0.1.onnx``) dentro de ``models_dir``."""
    p = Path(model).expanduser()
    if p.suffix == ".onnx" or p.is_absolute() or os.sep in str(model):
        if not p.exists():
            raise FileNotFoundError(f"modelo de wake word não encontrado: {p}")
        return p
    exact = models_dir / f"{model}.onnx"
    if exact.exists():
        return exact
    found = sorted(models_dir.glob(f"{model}_v*.onnx"))
    if found:
        return found[-1]
    raise FileNotFoundError(
        f"modelo de wake word '{model}' não está em {models_dir}; "
        "rode `uv run magi-satellite --download-models`"
    )


def download_models(models_dir: Path, names: tuple[str, ...] = (DEFAULT_WAKE_MODEL,)) -> None:
    """Baixa os modelos de atributos e os pré-treinados ``names`` do openWakeWord (GitHub)."""
    from openwakeword.utils import download_models as _download

    models_dir.mkdir(parents=True, exist_ok=True)
    _download(model_names=[f"{n}_v" for n in names], target_directory=str(models_dir))


class OpenWakeWordDetector:
    """``WakeDetector`` com openWakeWord + onnxruntime (1 thread, sessões enxutas)."""

    def __init__(
        self, model: str | os.PathLike[str] = DEFAULT_WAKE_MODEL, models_dir: Path | None = None
    ) -> None:
        models_dir = models_dir or default_models_dir()
        path = resolve_model(model, models_dir)
        feats = [models_dir / f for f in FEATURE_MODELS]
        missing = [str(f) for f in feats if not f.exists()]
        if missing:
            raise FileNotFoundError(
                f"modelos de atributos do openWakeWord ausentes: {missing}; "
                "rode `uv run magi-satellite --download-models`"
            )
        import onnxruntime as ort

        from magi.satellite.onnx import import_openwakeword_model, lean_sessions

        model_cls = import_openwakeword_model()  # sem scipy/scikit-learn (1.23)
        self.path = path
        self.name = path.stem
        with lean_sessions(ort):  # 1 thread, sem arena nem memory pattern (1.23; RNF-02)
            self._model = model_cls(
                wakeword_models=[str(path)],
                inference_framework="onnx",
                melspec_model_path=str(feats[0]),
                embedding_model_path=str(feats[1]),
            )
        # Otimização (medida na 1.1): o openWakeWord 0.6 guarda 10 s de áudio num deque de ints
        # Python e o copia inteiro para lista a cada bloco (~1,3 ms de CPU por bloco, mais que o
        # próprio modelo). Ele só lê as últimas ``n + 480`` amostras, então um deque curto dá o
        # mesmo resultado com uma fração do custo.
        pre = self._model.preprocessor
        if isinstance(getattr(pre, "raw_data_buffer", None), deque):
            pre.raw_data_buffer = deque(pre.raw_data_buffer, maxlen=RAW_BUFFER_SAMPLES)
        log.info("wake word: openWakeWord com %s", path)

    def process(self, block: np.ndarray) -> float:
        scores = self._model.predict(block)
        return max(scores.values()) if scores else 0.0

    def reset(self) -> None:
        self._model.reset()


# ---------------------------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WakeSettings:
    """Seção ``[satellite]`` do ``config.toml`` (tudo opcional)::

        [satellite]
        id = "pc"
        wake_model = "hey_jarvis"        # nome em models_dir ou caminho de um .onnx
        wake_threshold = 0.5             # recarregável sem reiniciar
        wake_patience = 1
        wake_cooldown_ms = 2000
        wake_gate_dbfs = -50             # portão de energia; "off" desliga
        models_dir = "~/.local/share/magi/models/wakeword"
        mic_target = ""                  # nome do source do PipeWire; vazio = padrão
    """

    satellite: str = "pc"
    model: str = DEFAULT_WAKE_MODEL
    threshold: float = DEFAULT_THRESHOLD
    patience: int = DEFAULT_PATIENCE
    cooldown_ms: int = DEFAULT_COOLDOWN_MS
    gate_dbfs: float | None = DEFAULT_GATE_DBFS
    models_dir: Path = field(default_factory=default_models_dir)
    mic_target: str | None = None

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> WakeSettings:
        sec = raw.get("satellite") or {}
        if not isinstance(sec, Mapping):
            raise ValueError("[satellite] deve ser uma tabela")
        d = cls()
        threshold = float(sec.get("wake_threshold", d.threshold))
        if not 0.0 < threshold <= 1.0:
            raise ValueError(f"[satellite] wake_threshold fora de (0, 1]: {threshold}")
        models_dir = sec.get("models_dir")
        gate = sec.get("wake_gate_dbfs", d.gate_dbfs)
        return cls(
            satellite=str(sec.get("id", d.satellite)),
            model=str(sec.get("wake_model", d.model)),
            threshold=threshold,
            patience=int(sec.get("wake_patience", d.patience)),
            cooldown_ms=int(sec.get("wake_cooldown_ms", d.cooldown_ms)),
            gate_dbfs=None if gate in (None, "off", False) else float(gate),
            models_dir=Path(models_dir).expanduser() if models_dir else d.models_dir,
            mic_target=str(sec["mic_target"]) if sec.get("mic_target") else None,
        )
