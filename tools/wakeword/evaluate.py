"""Avaliação do wake word (spike S4): taxa de acerto e falsos disparos por hora.

Uso::

    uv run python -m tools.wakeword.evaluate
    uv run python -m tools.wakeword.evaluate --model ~/.local/share/magi/models/wakeword/condessa.onnx \\
        --negatives ~/.local/share/magi/wakeword-data/condessa/eval

Passa o áudio em blocos de 80 ms pelo mesmo detector do satélite (``OpenWakeWordDetector``),
sem o portão de energia (mais rigoroso que em produção), e decide como o ``WakeSpotter``:
``patience`` notas seguidas >= limiar ativam e cada ativação tem 2 s de recarga.

- Positivas: as reservadas pelo treino (``split.json``) ou ``--positives DIR``; cada uma com 1 s
  de ruído fraco antes e depois. Acerto = a positiva ativaria (``patience`` notas seguidas).
- Negativas: os WAV de ``eval/`` (gravações longas de jogo, vídeo etc., que o treino não vê) ou
  ``--negatives DIR``; se ``eval/`` estiver vazio, ``negative/`` e ``noise/``. Mais os 15% finais
  de ``validation_set_features.npy`` (~1,6 h que o treino nunca vê), passados direto pelo ``.onnx``
  (``--no-features`` desliga).

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
from tools.wakeword.common import (
    AUDIO_RATE,
    DEFAULT_WORD,
    EXTRA_FILE,
    FRAME_S,
    N_FRAMES,
    activations,
    data_dir,
    detected,
    extra_split,
    list_wavs,
    read_wav,
    train_dir,
)

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


def count_activations(scores: np.ndarray, threshold: float, cooldown: int = COOLDOWN_BLOCKS,
                      patience: int = 1) -> int:
    return activations(scores, threshold, patience, cooldown)


@dataclass(frozen=True, slots=True)
class Row:
    threshold: float
    recall: float
    fp_per_hour: float
    patience: int = 1


def table(pos_scores: list[np.ndarray], neg_scores: list[np.ndarray], hours: float,
          patience: int = 1) -> list[Row]:
    rows = []
    for t in THRESHOLDS:
        recall = (float(np.mean([detected(s, t, patience) for s in pos_scores]))
                  if pos_scores else float("nan"))
        fps = sum(count_activations(s, t, patience=patience) for s in neg_scores)
        rows.append(Row(t, recall, fps / hours if hours > 0 else float("nan"), patience))
    return rows


def suggest(rows: list[Row]) -> Row | None:
    """Maior acerto entre as linhas com <= 0,5 falso/h; no empate, menos falsos/h, depois o menor
    ``patience`` (ativa mais rápido) e o limiar mais alto."""
    ok = [r for r in rows if r.fp_per_hour <= TARGET_FP_PER_HOUR]
    if not ok:
        return None
    best = max(r.recall for r in ok)
    if not best > 0:
        return None
    return max((r for r in ok if r.recall == best),
               key=lambda r: (-r.fp_per_hour, -r.patience, r.threshold))


def feature_scores(model: Path, stream: np.ndarray, chunk: int = 20_000) -> np.ndarray:
    """Notas do ``.onnx`` (``[N, 16, 96] -> [N, 1]``) em cada passo de 80 ms de um fluxo de embeddings."""
    import onnxruntime as ort

    sess = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    out = []
    for s in range(0, max(0, len(stream) - N_FRAMES + 1), chunk):
        part = stream[s : s + chunk + N_FRAMES - 1]
        w = np.lib.stride_tricks.sliding_window_view(part, N_FRAMES, axis=0).transpose(0, 2, 1)
        out.append(sess.run(None, {name: np.ascontiguousarray(w, np.float32)})[0][:, 0])
    return np.concatenate(out) if out else np.zeros(0)


def heldout_features(path: Path) -> np.ndarray:
    """Os 15% finais de ``validation_set_features.npy`` (o treino usa só o começo)."""
    x = np.load(path, mmap_mode="r")
    return np.asarray(x[extra_split(len(x)) :], np.float32)


def heldout_files(base: Path) -> list[Path]:
    split = base / "split.json"
    if not split.exists():
        return []
    return [base / "positive" / n for n in json.loads(split.read_text())["heldout"]
            if (base / "positive" / n).exists()]


def evaluate(detector: WakeDetector, positives: list[Path], negatives: list[Path], out=print, *,
             patiences: tuple[int, ...] = (1,), extra_scores: np.ndarray | None = None) -> Row | None:
    """``extra_scores``: notas já calculadas de um fluxo de negativos (80 ms cada), somadas às WAV."""
    pad = room_tone(AUDIO_RATE)
    pos_scores = [scores_for(detector, np.concatenate([pad, read_wav(p), pad])) for p in positives]
    neg_scores, seconds = [], 0.0
    for p in negatives:
        pcm = read_wav(p)
        seconds += len(pcm) / AUDIO_RATE
        neg_scores.append(scores_for(detector, pcm))
    wav_min = seconds / 60
    if extra_scores is not None and len(extra_scores):
        neg_scores.append(extra_scores)
        seconds += len(extra_scores) * FRAME_S
    hours = seconds / 3600
    out(f"modelo: {detector.name} · positivas: {len(positives)} · negativas: {hours * 60:.1f} min "
        f"({wav_min:.1f} min de WAV + {hours * 60 - wav_min:.1f} min de atributos reservados)")
    rows: list[Row] = []
    for pat in patiences:
        part = table(pos_scores, neg_scores, hours, pat)
        rows += part
        out(f"patience {pat} · limiar  acerto  falsos/h")
        for r in part:
            out(f"             {r.threshold:.2f}  {r.recall * 100:5.1f}%  {r.fp_per_hour:7.2f}")
    if pos_scores:
        misses = [f"{p.name} ({s.max():.2f})" for p, s in zip(positives, pos_scores, strict=True)
                  if s.max() < 0.5]
        if misses:
            out(f"perdidas a 0,5 (nota máxima): {', '.join(misses[:10])}")
    best = suggest(rows)
    if best is None:
        out("nenhum limiar fica em <= 0,5 falso/h: treine com mais negativos (ver docs/spikes/S4.md)")
    else:
        verdict = "PASSA" if best.recall >= TARGET_RECALL else "NÃO PASSA"
        out(f"sugestão: wake_threshold = {best.threshold:.2f}, wake_patience = {best.patience} "
            f"({best.recall * 100:.1f}% de acerto, {best.fp_per_hour:.2f} falsos/h) -> {verdict} "
            "no critério do S4")
    if hours < 1:
        out(f"aviso: só {hours * 60:.0f} min de negativos; para medir falsos/h grave >= 1 h de jogo em eval/")
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--word", default=DEFAULT_WORD, help="palavra: pasta dos dados e <word>.onnx")
    ap.add_argument("--model", default=None, help="nome ou .onnx; padrão: <word>.onnx em models_dir")
    ap.add_argument("--models-dir", type=Path, default=None)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--positives", type=Path, action="append", help="pasta(s) de positivas")
    ap.add_argument("--negatives", type=Path, action="append", help="pasta(s) de negativas")
    ap.add_argument("--patience", type=int, nargs="+", default=[1, 2, 3],
                    help="valores de wake_patience a testar (padrão: 1 2 3)")
    ap.add_argument("--features", type=Path, default=None,
                    help=f"atributos .npy (fluxo N×96); padrão: {EXTRA_FILE} do fetch, se existir")
    ap.add_argument("--no-features", action="store_true", help="só os WAV de negativas")
    args = ap.parse_args(argv)
    from magi.satellite.wake import OpenWakeWordDetector

    base = args.data_dir or data_dir(args.word)
    models_dir = args.models_dir or default_models_dir()
    detector = OpenWakeWordDetector(args.model or str(models_dir / f"{args.word}.onnx"), models_dir)
    positives = list_wavs(*args.positives) if args.positives else heldout_files(base)
    if args.negatives:
        negatives = list_wavs(*args.negatives)
    else:
        negatives = list_wavs(base / "eval")
        if not negatives:
            print("eval/ vazio: usando negative/ e noise/ (usados no treino: falsos/h otimista)")
            negatives = list_wavs(base / "negative", base / "noise")
    extra = None
    feats = args.features or train_dir() / EXTRA_FILE
    if not args.no_features and feats.exists():
        extra = feature_scores(detector.path, heldout_features(feats))
    evaluate(detector, positives, negatives, patiences=tuple(args.patience), extra_scores=extra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
