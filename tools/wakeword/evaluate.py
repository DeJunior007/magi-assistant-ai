"""Avaliação do wake word (spike S4): taxa de acerto e falsos disparos por hora.

Uso::

    uv run python -m tools.wakeword.evaluate
    uv run python -m tools.wakeword.evaluate --model ~/.local/share/magi/models/wakeword/ei_magui.onnx \\
        --negatives ~/.local/share/magi/wakeword-data/eval

Passa o áudio em blocos de 80 ms pelo mesmo detector do satélite (``OpenWakeWordDetector``),
sem o portão de energia (mais rigoroso que em produção).

- Positivas: as reservadas pelo treino (``split.json``) ou ``--positives DIR``; cada uma com 1 s
  de ruído fraco antes e depois. Acerto = nota máxima >= limiar.
- Negativas: os WAV de ``eval/`` (gravações longas de jogo, vídeo etc., que o treino não vê) ou
  ``--negatives DIR``; se ``eval/`` estiver vazio, ``negative/`` e ``noise/``.
  Conta ativações com 2 s de recarga, como o ``WakeSpotter``.

Critério do S4: >= 95% de acerto e <= 0,5 falso disparo por hora (1 a cada 2 h).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from magi.satellite.capture import iter_blocks
from magi.satellite.wake import DEFAULT_COOLDOWN_MS, WakeDetector, default_models_dir
from tools.wakeword.common import AUDIO_RATE, data_dir, list_wavs, read_wav

TARGET_RECALL = 0.95
TARGET_FP_PER_HOUR = 0.5
THRESHOLDS = [round(float(t), 2) for t in np.arange(0.1, 0.96, 0.05)]
COOLDOWN_BLOCKS = DEFAULT_COOLDOWN_MS // 80


#: Depois de ``reset`` o openWakeWord enche o buffer de atributos com ruído aleatório; 2 s de
#: silêncio antes de cada arquivo (notas descartadas) deixam a janela só com áudio real.
WARMUP_SAMPLES = 2 * AUDIO_RATE


def room_tone(n: int) -> np.ndarray:
    """Ruído branco fraco (~-60 dBFS) no lugar de zeros, como um microfone real em silêncio."""
    return (np.random.default_rng(n).standard_normal(n) * 33.0).astype(np.int16)


def scores_for(detector: WakeDetector, pcm: np.ndarray) -> np.ndarray:
    """Nota de cada bloco de 80 ms de ``pcm`` (após o aquecimento)."""
    detector.reset()
    blocks = iter_blocks(np.concatenate([room_tone(WARMUP_SAMPLES), pcm]))
    scores = [detector.process(np.frombuffer(b, dtype="<i2")) for b in blocks]
    return np.array(scores[WARMUP_SAMPLES // 1280 :])


def count_activations(scores: np.ndarray, threshold: float, cooldown: int = COOLDOWN_BLOCKS) -> int:
    n, mute = 0, -1
    for i, s in enumerate(scores):
        if i > mute and s >= threshold:
            n += 1
            mute = i + cooldown
    return n


@dataclass(frozen=True, slots=True)
class Row:
    threshold: float
    recall: float
    fp_per_hour: float


def table(pos_max: np.ndarray, neg_scores: list[np.ndarray], hours: float) -> list[Row]:
    rows = []
    for t in THRESHOLDS:
        recall = float((pos_max >= t).mean()) if len(pos_max) else float("nan")
        fps = sum(count_activations(s, t) for s in neg_scores)
        rows.append(Row(t, recall, fps / hours if hours > 0 else float("nan")))
    return rows


def suggest(rows: list[Row]) -> Row | None:
    """Maior acerto entre os limiares com <= 0,5 falso/h; no empate, o limiar mais alto."""
    ok = [r for r in rows if r.fp_per_hour <= TARGET_FP_PER_HOUR]
    if not ok:
        return None
    best = max(r.recall for r in ok)
    if not best > 0:
        return None
    return max((r for r in ok if r.recall == best), key=lambda r: r.threshold)


def heldout_files(base: Path) -> list[Path]:
    split = base / "split.json"
    if not split.exists():
        return []
    return [base / "positive" / n for n in json.loads(split.read_text())["heldout"]
            if (base / "positive" / n).exists()]


def evaluate(detector: WakeDetector, positives: list[Path], negatives: list[Path], out=print) -> Row | None:
    pad = room_tone(AUDIO_RATE)
    pos_max = np.array([scores_for(detector, np.concatenate([pad, read_wav(p), pad])).max()
                        for p in positives])
    neg_scores, seconds = [], 0.0
    for p in negatives:
        pcm = read_wav(p)
        seconds += len(pcm) / AUDIO_RATE
        neg_scores.append(scores_for(detector, pcm))
    hours = seconds / 3600
    out(f"modelo: {detector.name} · positivas: {len(positives)} · negativas: {hours * 60:.1f} min")
    rows = table(pos_max, neg_scores, hours)
    out("limiar  acerto  falsos/h")
    for r in rows:
        out(f"  {r.threshold:.2f}  {r.recall * 100:5.1f}%  {r.fp_per_hour:7.2f}")
    if len(pos_max):
        misses = [p.name for p, s in zip(positives, pos_max, strict=True) if s < 0.5]
        if misses:
            out(f"perdidas a 0,5: {', '.join(misses[:10])}")
    best = suggest(rows)
    if best is None:
        out("nenhum limiar fica em <= 0,5 falso/h: treine com mais negativos (ver docs/spikes/S4.md)")
    else:
        verdict = "PASSA" if best.recall >= TARGET_RECALL else "NÃO PASSA"
        out(f"sugestão: wake_threshold = {best.threshold:.2f} ({best.recall * 100:.1f}% de acerto, "
            f"{best.fp_per_hour:.2f} falsos/h) -> {verdict} no critério do S4")
    if hours < 1:
        out(f"aviso: só {hours * 60:.0f} min de negativos; para medir falsos/h grave >= 1 h de jogo em eval/")
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None, help="nome ou .onnx; padrão: ei_magui em models_dir")
    ap.add_argument("--models-dir", type=Path, default=None)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--positives", type=Path, action="append", help="pasta(s) de positivas")
    ap.add_argument("--negatives", type=Path, action="append", help="pasta(s) de negativas")
    args = ap.parse_args(argv)
    from magi.satellite.wake import OpenWakeWordDetector

    base = args.data_dir or data_dir()
    models_dir = args.models_dir or default_models_dir()
    detector = OpenWakeWordDetector(args.model or str(models_dir / "ei_magui.onnx"), models_dir)
    positives = list_wavs(*args.positives) if args.positives else heldout_files(base)
    if args.negatives:
        negatives = list_wavs(*args.negatives)
    else:
        negatives = list_wavs(base / "eval")
        if not negatives:
            print("eval/ vazio: usando negative/ e noise/ (usados no treino: falsos/h otimista)")
            negatives = list_wavs(base / "negative", base / "noise")
    evaluate(detector, positives, negatives)
    return 0


if __name__ == "__main__":
    sys.exit(main())
