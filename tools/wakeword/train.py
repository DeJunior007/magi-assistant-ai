"""Treino do wake word "Condessa" (spike S4) — CPU, sem GPU.

Mesmo princípio do treino oficial do openWakeWord (``openwakeword/train.py`` e o notebook
``automatic_model_training.ipynb``): os modelos de atributos (melspectrograma + embedding do
Google) ficam congelados e só um classificador pequeno é treinado sobre janelas de 16 embeddings
(2 s de áudio). A diferença é a escala: em vez de ~100 mil clipes sintéticos do Piper e 2000 h de
negativos, usamos as gravações do usuário + ~150 clipes de TTS + aumento de dados, e treinamos uma
MLP em numpy (minutos na CPU). O ONNX exportado tem a mesma interface ``[N, 16, 96] -> [N, 1]``
que o ``openwakeword.Model`` carrega.

Passos::

    uv run python -m tools.wakeword.train synth             # TTS OpenAI, teto US$ 0,20
    uv run python -m tools.wakeword.train fetch             # 185 MB de negativos (~11 h) do openWakeWord
    uv run --with onnx python -m tools.wakeword.train train # treina e grava condessa.onnx

Todos aceitam ``--word`` (padrão ``condessa``): pasta dos dados e nome do modelo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from magi.satellite.wake import FEATURE_MODELS, default_models_dir
from tools.wakeword.common import (
    AUDIO_RATE,
    DEFAULT_WORD,
    EMB_DIM,
    N_FRAMES,
    WINDOW_SAMPLES,
    augment,
    data_dir,
    dither,
    list_wavs,
    place_in_window,
    read_wav,
    resample,
    train_dir,
    trim_silence,
    write_wav,
)

MODEL_NAME = DEFAULT_WORD  # padrão; o nome real vem de --word
EXTRA_URL = (
    "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/"
    "validation_set_features.npy"
)

# ---------------------------------------------------------------------------------------------
# Amostras sintéticas (TTS)
# ---------------------------------------------------------------------------------------------

TTS_MODEL = "gpt-4o-mini-tts"
TTS_RATE = 24_000  # response_format="pcm": PCM16 mono 24 kHz
#: Preço estimado do gpt-4o-mini-tts: US$ 0,015 por minuto de áudio + US$ 0,60/M tokens de texto.
TTS_USD_PER_MIN = 0.015
TTS_USD_PER_TOKEN = 0.60e-6
TTS_WORST_CALL_USD = 0.0015  # reserva por chamada antes de saber a duração (~6 s)
VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"]
TEXTS = ["Condessa", "Hey Condessa", "Oi Condessa", "Oh Condessa"]
STYLES = [
    "voz normal, chamando alguém que está perto",
    "falando baixo, quase sussurrando",
    "chamando alto, de longe",
    "falando rápido",
    "falando devagar",
    "voz cansada, com sono",
    "voz animada, sorrindo",
    "tom casual de quem está jogando videogame",
]
PRONUNCIATION = (
    "Fale em português do Brasil, sotaque brasileiro natural. 'Hey', 'Oi' e 'Oh' como quem chama "
    "alguém. 'Condessa' pronuncia-se 'con-DÊ-ssa', tônica no DE, E fechado. "
    "Diga só a frase, sem nada antes ou depois. Estilo: "
)

Speaker = Callable[[str, str, str], bytes]  # (texto, voz, instruções) -> PCM16 24 kHz


def openai_speaker() -> Speaker:
    from openai import OpenAI

    from magi.common.secrets import require_secret

    client = OpenAI(api_key=require_secret("openai-1"))

    def speak(text: str, voice: str, instructions: str) -> bytes:
        r = client.audio.speech.create(
            model=TTS_MODEL, voice=voice, input=text, instructions=instructions, response_format="pcm"
        )
        return r.read() if hasattr(r, "read") else r.content

    return speak


def synthesize(
    out_dir: Path,
    n: int,
    budget_usd: float,
    speak: Speaker,
    *,
    seed: int = 0,
    texts: list[str] | None = None,
    log: Callable[[str], None] = print,
) -> tuple[int, float]:
    """Gera até ``n`` clipes em ``out_dir`` sem passar de ``budget_usd`` (acumulado em
    ``spend.json``, entre execuções). Devolve (clipes gerados, gasto total estimado)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    spend_file = out_dir / "spend.json"
    spent = json.loads(spend_file.read_text())["usd"] if spend_file.exists() else 0.0
    rng = np.random.default_rng(seed + len(list(out_dir.glob("*.wav"))))
    combos = [(t, v, s) for t in (texts or TEXTS) for v in VOICES for s in STYLES]
    order = rng.permutation(len(combos))
    made = 0
    for k in order[:n]:
        if spent + TTS_WORST_CALL_USD > budget_usd:
            log(f"teto de US$ {budget_usd:.2f} atingido (gasto ~US$ {spent:.4f}); parando")
            break
        text, voice, style = combos[k]
        instr = PRONUNCIATION + style
        pcm24 = np.frombuffer(speak(text, voice, instr), dtype="<i2")
        spent += len(pcm24) / TTS_RATE / 60 * TTS_USD_PER_MIN
        spent += (len(instr) + len(text)) / 4 * TTS_USD_PER_TOKEN
        spend_file.write_text(json.dumps({"usd": round(spent, 6)}))
        pcm = trim_silence(resample(pcm24.copy(), TTS_RATE, AUDIO_RATE))
        if len(pcm) < AUDIO_RATE // 5:
            continue
        idx = len(list(out_dir.glob("*.wav"))) + 1
        write_wav(out_dir / f"tts_{voice}_{idx:03d}.wav", pcm)
        made += 1
    log(f"{made} clipes sintéticos em {out_dir}; gasto acumulado ~US$ {spent:.4f}")
    return made, spent


# ---------------------------------------------------------------------------------------------
# Dados e atributos
# ---------------------------------------------------------------------------------------------


def split_positives(real: list[Path], split_file: Path, frac: float = 0.2, seed: int = 0) -> list[Path]:
    """Reserva ``frac`` das positivas reais para avaliação (lista fixa em ``split.json``).
    Devolve as positivas de treino. Arquivos novos entram no treino."""
    if split_file.exists():
        held = set(json.loads(split_file.read_text())["heldout"])
    else:
        rng = np.random.default_rng(seed)
        k = int(round(len(real) * frac))
        held = {real[i].name for i in rng.choice(len(real), size=k, replace=False)} if k else set()
        split_file.parent.mkdir(parents=True, exist_ok=True)
        split_file.write_text(json.dumps({"heldout": sorted(held)}, indent=1))
    return [p for p in real if p.name not in held]


class Featurizer:
    """Embeddings do openWakeWord (os mesmos ONNX que o satélite usa)."""

    def __init__(self, models_dir: Path) -> None:
        from openwakeword.utils import AudioFeatures

        mel, emb = (str(models_dir / f) for f in FEATURE_MODELS)
        self._af = AudioFeatures(melspec_model_path=mel, embedding_model_path=emb,
                                 inference_framework="onnx", ncpu=os.cpu_count() or 1)

    def clips(self, x: np.ndarray, batch: int = 64) -> np.ndarray:
        """``(N, 32000)`` int16 -> ``(N, 16, 96)``."""
        if len(x) == 0:
            return np.zeros((0, N_FRAMES, EMB_DIM), np.float32)
        return self._af.embed_clips(x, batch_size=batch).astype(np.float32)

    def stream(self, pcm: np.ndarray) -> np.ndarray:
        """Áudio longo -> ``(frames, 96)``, um embedding a cada 80 ms."""
        if len(pcm) < WINDOW_SAMPLES:
            return np.zeros((0, EMB_DIM), np.float32)
        return self._af._get_embeddings(pcm).astype(np.float32)


def windows(stream: np.ndarray, stride: int = 1) -> np.ndarray:
    """``(frames, 96)`` -> ``(M, 16, 96)`` janelas deslizantes."""
    if len(stream) < N_FRAMES:
        return np.zeros((0, N_FRAMES, EMB_DIM), np.float32)
    idx = np.arange(0, len(stream) - N_FRAMES + 1, stride)
    return np.stack([stream[i : i + N_FRAMES] for i in idx]).astype(np.float32)


def load_extra(path: Path, stride: int, holdout: float = 0.15) -> tuple[np.ndarray, np.ndarray | None]:
    """Atributos pré-computados do openWakeWord. Fluxo ``(N, 96)``: devolve janelas de treino
    (com ``stride``) dos primeiros 85% e o fluxo reservado do fim, para estimar falsos disparos.
    Janelas ``(N, 16, 96)`` (ex.: ACAV100M): só treino."""
    x = np.load(path, mmap_mode="r")
    if x.ndim == 2:
        cut = int(len(x) * (1 - holdout))
        return windows(np.asarray(x[:cut], np.float32), stride), np.asarray(x[cut:], np.float32)
    return np.asarray(x[::stride], np.float32), None


def stream_scores(mlp: MLP, stream: np.ndarray, chunk: int = 20_000) -> np.ndarray:
    """Nota de cada passo de 80 ms de um fluxo de embeddings (em pedaços, sem estourar memória)."""
    out = []
    for s in range(0, max(0, len(stream) - N_FRAMES + 1), chunk):
        out.append(mlp.predict(windows(stream[s : s + chunk + N_FRAMES - 1])))
    return np.concatenate(out) if out else np.zeros(0)


# ---------------------------------------------------------------------------------------------
# Classificador (MLP em numpy) e exportação ONNX
# ---------------------------------------------------------------------------------------------


class MLP:
    """Flatten(16x96) -> padroniza -> 64 ReLU -> 64 ReLU -> 1 sigmoide."""

    def __init__(self, n_in: int = N_FRAMES * EMB_DIM, hidden: int = 64, seed: int = 0) -> None:
        rng = np.random.default_rng(seed)
        dims = [n_in, hidden, hidden, 1]
        self.W = [rng.standard_normal((o, i)).astype(np.float32) * np.sqrt(2.0 / i)
                  for i, o in zip(dims[:-1], dims[1:], strict=True)]
        self.b = [np.zeros(o, np.float32) for o in dims[1:]]
        self.mu = np.zeros(n_in, np.float32)
        self.sd = np.ones(n_in, np.float32)

    def _forward(self, x: np.ndarray):
        z = (x.reshape(len(x), -1) - self.mu) / self.sd
        acts = [z]
        for i, (w, b) in enumerate(zip(self.W, self.b, strict=True)):
            h = acts[-1] @ w.T + b
            acts.append(np.maximum(h, 0) if i < len(self.W) - 1 else h)
        return acts

    def predict(self, x: np.ndarray) -> np.ndarray:
        logit = self._forward(x)[-1][:, 0]
        return 1.0 / (1.0 + np.exp(-np.clip(logit, -30, 30)))

    def fit(self, x, y, *, neg_weight=2.0, epochs=40, batch=512, lr=1e-3, l2=1e-4, seed=0, log=print):
        x = x.reshape(len(x), -1).astype(np.float32)
        y = y.astype(np.float32)
        self.mu = x.mean(axis=0)
        self.sd = x.std(axis=0) + 1e-3
        npos, nneg = float(y.sum()), float(len(y) - y.sum())
        wts = np.where(y > 0.5, 1.0, neg_weight * npos / max(nneg, 1.0)).astype(np.float32)
        params = self.W + self.b
        m = [np.zeros_like(p) for p in params]
        v = [np.zeros_like(p) for p in params]
        rng = np.random.default_rng(seed)
        step = 0
        for ep in range(epochs):
            order = rng.permutation(len(x))
            loss_sum = 0.0
            for s in range(0, len(x), batch):
                ib = order[s : s + batch]
                acts = self._forward(x[ib])
                logit = acts[-1][:, 0]
                p = 1.0 / (1.0 + np.exp(-np.clip(logit, -30, 30)))
                wb = wts[ib]
                loss_sum += float(np.sum(wb * (np.logaddexp(0, logit) - y[ib] * logit)))
                g = (wb * (p - y[ib]) / wb.sum())[:, None].astype(np.float32)
                gW, gb = [None] * 3, [None] * 3
                for i in range(len(self.W) - 1, -1, -1):
                    gW[i] = g.T @ acts[i] + l2 * self.W[i]
                    gb[i] = g.sum(axis=0)
                    if i:
                        g = (g @ self.W[i]) * (acts[i] > 0)
                step += 1
                for j, (p_, g_) in enumerate(zip(params, gW + gb, strict=True)):
                    m[j] = 0.9 * m[j] + 0.1 * g_
                    v[j] = 0.999 * v[j] + 0.001 * g_ * g_
                    mh, vh = m[j] / (1 - 0.9**step), v[j] / (1 - 0.999**step)
                    p_ -= (lr * mh / (np.sqrt(vh) + 1e-8)).astype(np.float32)
            if ep % 10 == 9 or ep == epochs - 1:
                log(f"  época {ep + 1}/{epochs}: perda {loss_sum / wts.sum():.4f}")
        return self


def export_onnx(mlp: MLP, path: Path, name: str = MODEL_NAME) -> None:
    """Grava o MLP como ONNX ``[N, 16, 96] -> [N, 1]`` (padronização embutida na 1ª camada)."""
    try:
        import onnx
        from onnx import TensorProto, helper, numpy_helper
    except ImportError as e:
        raise SystemExit("falta o pacote onnx: rode com `uv run --with onnx python -m ...`") from e
    w1 = mlp.W[0] / mlp.sd[None, :]
    b1 = mlp.b[0] - w1 @ mlp.mu
    inits = [
        numpy_helper.from_array(np.array([-1, N_FRAMES * EMB_DIM], np.int64), "shape"),
        numpy_helper.from_array(w1.astype(np.float32), "W0"),
        numpy_helper.from_array(b1.astype(np.float32), "B0"),
    ]
    for i in (1, 2):
        inits += [numpy_helper.from_array(mlp.W[i].astype(np.float32), f"W{i}"),
                  numpy_helper.from_array(mlp.b[i].astype(np.float32), f"B{i}")]
    nodes = [
        helper.make_node("Reshape", ["x", "shape"], ["f"]),
        helper.make_node("Gemm", ["f", "W0", "B0"], ["h0"], transB=1),
        helper.make_node("Relu", ["h0"], ["a0"]),
        helper.make_node("Gemm", ["a0", "W1", "B1"], ["h1"], transB=1),
        helper.make_node("Relu", ["h1"], ["a1"]),
        helper.make_node("Gemm", ["a1", "W2", "B2"], ["logit"], transB=1),
        helper.make_node("Sigmoid", ["logit"], ["score"]),
    ]
    graph = helper.make_graph(
        nodes, name,
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, ["N", N_FRAMES, EMB_DIM])],
        [helper.make_tensor_value_info("score", TensorProto.FLOAT, ["N", 1])],
        inits,
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], producer_name="magi")
    model.ir_version = 8
    onnx.checker.check_model(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(path))


def activations(scores: np.ndarray, threshold: float, cooldown: int = 25) -> int:
    """Ativações num fluxo de notas (uma por 80 ms), com recarga de ``cooldown`` passos (2 s)."""
    n, mute = 0, -1
    for i, s in enumerate(scores):
        if i > mute and s >= threshold:
            n += 1
            mute = i + cooldown
    return n


# ---------------------------------------------------------------------------------------------
# Treino
# ---------------------------------------------------------------------------------------------


def build_dataset(base: Path, feat: Featurizer, *, n_aug: int, extra: Path | None, extra_stride: int,
                  seed: int, log=print):
    rng = np.random.default_rng(seed)
    real = list_wavs(base / "positive")
    train_real = split_positives(real, base / "split.json", seed=seed)
    synth = list_wavs(base / "synthetic")
    noises = [read_wav(p) for p in list_wavs(base / "noise")]
    neg_files = list_wavs(base / "negative")
    neg_audio = [read_wav(p) for p in neg_files]
    bg = noises + [a for a in neg_audio if len(a) > 4 * AUDIO_RATE]  # fundo para misturar
    log(f"positivas: {len(train_real)} reais de treino (+{len(real) - len(train_real)} reservadas), "
        f"{len(synth)} sintéticas; negativas: {len(neg_files)} arquivos; ruído: {len(noises)}")
    if not train_real and not synth:
        raise SystemExit("sem positivas: grave com tools.wakeword.record ou gere com `synth`")

    pos_clips = []
    for p in train_real + synth:
        clip = read_wav(p)
        pos_clips.append(dither(place_in_window(clip, rng), rng))  # uma cópia limpa
        pos_clips += [augment(clip, rng, bg) for _ in range(n_aug)]
    xp = feat.clips(np.stack(pos_clips))

    short_neg, xn_parts = [], []
    for a in neg_audio + noises:
        if len(a) <= 3 * AUDIO_RATE:  # frase curta: posições como as positivas
            short_neg.append(dither(place_in_window(a, rng), rng))
            short_neg += [augment(a, rng, noises) for _ in range(max(1, n_aug // 2))]
        else:  # fala livre / ruído: janelas deslizantes, limpas e com aumento
            xn_parts.append(windows(feat.stream(a), stride=2))
            xn_parts.append(windows(feat.stream(augment(a, rng, noises, window=None, speed=(1, 1))), 3))
    # silêncio digital e ruído bem fraco: nunca são o wake word
    short_neg += [np.zeros(WINDOW_SAMPLES, np.int16)] * 4
    short_neg += [dither(np.zeros(WINDOW_SAMPLES, np.int16), rng, (-90.0, -40.0)) for _ in range(60)]
    if short_neg:
        xn_parts.append(feat.clips(np.stack(short_neg)))
    xn = np.concatenate(xn_parts) if xn_parts else np.zeros((0, N_FRAMES, EMB_DIM), np.float32)

    val_fp = None
    if extra is not None:
        xe, val_fp = load_extra(extra, extra_stride)
        xn = np.concatenate([xn, xe])
        log(f"negativos extras: {len(xe)} janelas de treino"
            + (f", {len(val_fp) * 0.08 / 3600:.1f} h reservadas" if val_fp is not None else ""))
    if len(xn) == 0:
        raise SystemExit("sem negativos: grave negative/ e noise/ ou rode `fetch`")
    x = np.concatenate([xp, xn])
    y = np.concatenate([np.ones(len(xp)), np.zeros(len(xn))])
    return x, y, val_fp


def heldout_recall(mlp: MLP, base: Path, feat: Featurizer, threshold: float = 0.5) -> tuple[int, int]:
    held = json.loads((base / "split.json").read_text())["heldout"] if (base / "split.json").exists() else []
    clips = [read_wav(base / "positive" / n) for n in held if (base / "positive" / n).exists()]
    if not clips:
        return 0, 0
    rng = np.random.default_rng(123)
    # várias posições por clipe; vale a melhor (o detector vê a palavra passar pela janela)
    xs = feat.clips(np.stack([place_in_window(c, rng, end_jitter_s=(j, j)) for c in clips
                              for j in (0.1, 0.25, 0.4)]))
    best = mlp.predict(xs).reshape(len(clips), 3).max(axis=1)
    return int((best >= threshold).sum()), len(clips)


def train(args) -> Path:
    t0 = time.monotonic()
    base: Path = args.data_dir or data_dir(args.word)
    models_dir: Path = args.models_dir or default_models_dir()
    extra = args.extra
    if extra is None and (train_dir() / "validation_set_features.npy").exists():
        extra = train_dir() / "validation_set_features.npy"
    feat = Featurizer(models_dir)
    x, y, val_fp = build_dataset(base, feat, n_aug=args.aug, extra=extra, extra_stride=args.extra_stride,
                                 seed=args.seed)
    print(f"dataset: {int(y.sum())} positivas, {int(len(y) - y.sum())} negativas "
          f"({time.monotonic() - t0:.0f} s de atributos)")
    mlp = MLP(seed=args.seed).fit(x, y, epochs=args.epochs, neg_weight=args.neg_weight, seed=args.seed)
    hit, tot = heldout_recall(mlp, base, feat)
    if tot:
        print(f"positivas reservadas: {hit}/{tot} acima de 0,5 (avaliação completa: tools.wakeword.evaluate)")
    if val_fp is not None and len(val_fp):
        hours = len(val_fp) * 0.08 / 3600
        s = stream_scores(mlp, val_fp)
        for thr in (0.3, 0.5, 0.7, 0.9):
            print(f"  limiar {thr:.1f}: {activations(s, thr) / hours:.2f} falsos disparos/h "
                  f"em {hours:.1f} h de negativos reservados")
    out = args.output or models_dir / f"{args.word}.onnx"
    if out.exists():
        shutil.copy2(out, out.with_suffix(".onnx.bak"))
    export_onnx(mlp, out, out.stem)
    import onnxruntime as ort

    sess = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
    probe = x[:8].astype(np.float32)
    got = sess.run(None, {"x": probe})[0][:, 0]
    assert np.allclose(got, mlp.predict(probe), atol=1e-4), "ONNX diverge do modelo treinado"
    print(f"modelo gravado em {out} ({time.monotonic() - t0:.0f} s no total)")
    return out


def fetch(dest: Path) -> Path:
    import urllib.request

    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "validation_set_features.npy"
    if out.exists():
        print(f"já existe: {out}")
        return out
    print(f"baixando ~185 MB de {EXTRA_URL}")
    tmp = out.with_suffix(".part")
    urllib.request.urlretrieve(EXTRA_URL, tmp)
    tmp.rename(out)
    print(f"ok: {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--word", default=DEFAULT_WORD, help="palavra: pasta dos dados e nome do .onnx")
    ap.add_argument("--data-dir", type=Path, default=None, help="padrão: .../wakeword-data/<word>")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synth", help="gera positivas sintéticas com TTS da OpenAI")
    s.add_argument("-n", type=int, default=150)
    s.add_argument("--budget", type=float, default=0.20, help="teto acumulado em US$")
    s.add_argument("--text", action="append", help="frase (repetível); padrão: Condessa com e sem hey/oi/oh")
    sub.add_parser("fetch", help="baixa negativos pré-computados do openWakeWord (~11 h, 185 MB)")
    t = sub.add_parser("train", help="treina e exporta o ONNX")
    t.add_argument("--aug", type=int, default=10, help="variações aumentadas por positiva")
    t.add_argument("--epochs", type=int, default=40)
    t.add_argument("--neg-weight", type=float, default=2.0)
    t.add_argument("--extra", type=Path, default=None, help="atributos .npy extras de negativos")
    t.add_argument("--extra-stride", type=int, default=4)
    t.add_argument("--models-dir", type=Path, default=None)
    t.add_argument("--output", type=Path, default=None)
    t.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    base = args.data_dir or data_dir(args.word)
    if args.cmd == "synth":
        synthesize(base / "synthetic", args.n, args.budget, openai_speaker(), texts=args.text)
    elif args.cmd == "fetch":
        fetch(train_dir())
    else:
        train(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
