"""Kit do wake word (tools/wakeword): corte, aumento, roteiro de gravação, TTS com teto, MLP."""

from __future__ import annotations

import json

import numpy as np
import pytest

from tools.wakeword import common, evaluate, record, train

RATE = common.AUDIO_RATE


def tone(seconds: float, amp: float = 8000.0, freq: float = 300.0) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.int16)


def with_silence(sig: np.ndarray, before: float = 1.0, after: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(0)
    pre = (rng.standard_normal(int(before * RATE)) * 10).astype(np.int16)
    post = (rng.standard_normal(int(after * RATE)) * 10).astype(np.int16)
    return np.concatenate([pre, sig, post])


# --- common ----------------------------------------------------------------------------------


def test_trim_silence_cuts_edges_and_keeps_padding():
    out = common.trim_silence(with_silence(tone(0.5)), pad_ms=150)
    assert 0.5 * RATE <= len(out) <= (0.5 + 0.32) * RATE


def test_trim_silence_empty_when_only_noise():
    rng = np.random.default_rng(1)
    assert len(common.trim_silence((rng.standard_normal(RATE) * 5).astype(np.int16))) == 0
    assert len(common.trim_silence(np.zeros(RATE, np.int16))) == 0


def test_place_in_window_ends_near_window_end():
    rng = np.random.default_rng(2)
    clip = np.full(8000, 1000, np.int16)
    w = common.place_in_window(clip, rng)
    assert len(w) == common.WINDOW_SAMPLES
    nz = np.flatnonzero(w)
    tail = common.WINDOW_SAMPLES - (nz[-1] + 1)
    assert 0.05 * RATE <= tail <= 0.5 * RATE and len(nz) == len(clip)
    long = common.place_in_window(np.full(3 * RATE, 7, np.int16), rng)  # corta o começo
    assert len(long) == common.WINDOW_SAMPLES


def test_mix_at_snr_hits_target():
    rng = np.random.default_rng(3)
    sig = tone(1.0, amp=5000)
    noise = (rng.standard_normal(RATE // 2) * 1000).astype(np.int16)  # curto: repete
    mixed = common.mix_at_snr(sig, noise, 10.0, rng)
    n = mixed.astype(float) - sig
    snr = 10 * np.log10(np.mean(sig.astype(float) ** 2) / np.mean(n**2))
    assert abs(snr - 10.0) < 0.5


def test_augment_shapes_and_no_digital_silence():
    rng = np.random.default_rng(4)
    clip = tone(0.7)
    noises = [(rng.standard_normal(RATE) * 300).astype(np.int16)]
    for _ in range(5):
        w = common.augment(clip, rng, noises)
        assert w.dtype == np.int16 and len(w) == common.WINDOW_SAMPLES
        assert np.count_nonzero(w[:1000]) > 500  # dither: nada de zeros puros em volta
    same = common.augment(tone(3.0), rng, noises, window=None, speed=(1, 1))
    assert len(same) == 3 * RATE


def test_speed_and_reverb_keep_level():
    rng = np.random.default_rng(5)
    clip = tone(1.0)
    assert abs(len(common.change_speed(clip, 1.1)) - RATE / 1.1) < 5
    rev = common.add_reverb(clip, common.synthetic_rir(rng, 0.4))
    assert len(rev) == len(clip) and abs(int(np.abs(rev).max()) - 8000) <= 2


def test_next_index(tmp_path):
    for n in ("pos_normal_001.wav", "pos_normal_007.wav", "pos_alto_009.wav"):
        (tmp_path / n).touch()
    assert common.next_index(tmp_path, "pos_normal") == 8
    assert common.next_index(tmp_path, "neg_frase") == 1


# --- record ----------------------------------------------------------------------------------


def test_build_takes_counts():
    takes = record.build_takes()
    pos = [t for t in takes if t.section == "positive"]
    neg = [t for t in takes if t.section == "negative"]
    assert 50 <= len(pos) <= 60 and all(t.say.endswith("Condessa") for t in pos)
    forms = {t.say for t in pos}
    assert forms == {"Condessa", "Hey Condessa", "Oi Condessa", "Oh Condessa"}
    counts = [sum(t.say == f for t in pos) for f in forms]
    assert max(counts) - min(counts) <= 1  # distribuídas por igual
    for label, _how, n in record.POSITIVE_STYLES:  # cada jeito de falar pega formas variadas
        assert len({t.say for t in pos if t.label == label}) == min(n, 4), label
    assert not any("condessa" in t.say.lower() for t in neg)  # ensinaria a ignorá-la
    assert 150 <= sum(t.seconds for t in neg) <= 240  # ~3 min de fala negativa
    assert [t.seconds for t in takes if t.section == "noise"] == [60.0]


class FakeMic:
    def __init__(self, silent_first: bool = False):
        self.calls = 0
        self.silent_first = silent_first

    def __call__(self, seconds: float) -> np.ndarray:
        self.calls += 1
        if self.silent_first and self.calls == 1:
            return np.zeros(int(seconds * RATE), np.int16)
        return with_silence(tone(0.6), 0.5, max(0.1, seconds - 1.1))


def scripted(answers):
    it = iter(answers)
    return lambda _prompt: next(it)


def test_run_records_trims_and_rerecords(tmp_path):
    takes = [record.Take("positive", "normal", "Condessa", "x", 2.5)] * 3
    mic = FakeMic(silent_first=True)
    # 1ª: silêncio (repete), grava, regrava a última, grava as duas que faltam, fim
    saved = record.run(takes, tmp_path, mic, ask=scripted(["", "", "r", "", "", ""]), out=lambda s: None)
    files = sorted((tmp_path / "positive").glob("*.wav"))
    assert saved == 3 and len(files) == 3 and mic.calls == 5
    pcm = common.read_wav(files[0])
    assert len(pcm) < 1.2 * RATE  # bordas cortadas
    # retoma: nada a fazer
    assert record.run(takes, tmp_path, mic, ask=scripted([]), out=lambda s: None) == 0


def test_run_noise_not_trimmed_and_quit(tmp_path):
    takes = [record.Take("noise", "quarto", "-", "-", 2.0), record.Take("noise", "quarto", "-", "-", 2.0)]

    def mic(seconds):
        return (np.random.default_rng(0).standard_normal(int(seconds * RATE)) * 200).astype(np.int16)

    record.run(takes, tmp_path, mic, ask=scripted(["", "q"]), out=lambda s: None)
    (f,) = (tmp_path / "noise").glob("*.wav")
    assert len(common.read_wav(f)) == 2 * RATE


# --- train -----------------------------------------------------------------------------------


def test_synthesize_respects_budget(tmp_path):
    calls = []

    def speak(text, voice, instructions):
        calls.append((text, voice))
        assert "português do Brasil" in instructions
        pcm = np.concatenate([np.zeros(4800), np.sin(np.arange(24000) / 10) * 8000, np.zeros(4800)])
        return pcm.astype("<i2").tobytes()  # 1,4 s a 24 kHz

    made, spent = train.synthesize(tmp_path, 1000, 0.01, speak, log=lambda s: None)
    assert 0 < made == len(calls) < 1000 and spent <= 0.01
    assert len(list(tmp_path.glob("tts_*.wav"))) == made
    assert json.loads((tmp_path / "spend.json").read_text())["usd"] == pytest.approx(spent, abs=1e-5)
    # acumulado: uma segunda execução com o mesmo teto não gasta mais
    made2, _ = train.synthesize(tmp_path, 10, 0.01, speak, log=lambda s: None)
    assert made2 == 0


def test_split_positives_is_stable(tmp_path):
    files = [tmp_path / f"pos_normal_{i:03d}.wav" for i in range(1, 21)]
    split = tmp_path / "split.json"
    tr = train.split_positives(files, split)
    held = json.loads(split.read_text())["heldout"]
    assert len(held) == 4 and len(tr) == 16
    new = tmp_path / "pos_normal_021.wav"
    assert new in train.split_positives(files + [new], split)  # novos vão para o treino


def test_windows_and_activations():
    stream = np.arange(20 * 96, dtype=np.float32).reshape(20, 96)
    w = train.windows(stream)
    assert w.shape == (5, 16, 96) and w[1, 0, 0] == 96
    assert train.windows(stream[:10]).shape == (0, 16, 96)
    scores = np.zeros(100)
    scores[[10, 11, 20, 50]] = 0.9
    assert train.activations(scores, 0.5) == 2  # 11 e 20 caem na recarga de 2 s
    assert evaluate.count_activations(scores, 0.5) == 2


def test_mlp_learns_separable_data():
    rng = np.random.default_rng(0)
    pos = rng.normal(1.0, 1.0, (200, 16, 96)).astype(np.float32)
    neg = rng.normal(-1.0, 1.0, (600, 16, 96)).astype(np.float32)
    x = np.concatenate([pos, neg])
    y = np.r_[np.ones(200), np.zeros(600)]
    mlp = train.MLP(seed=0).fit(x, y, epochs=5, log=lambda s: None)
    p = mlp.predict(x)
    assert (p[:200] > 0.5).mean() > 0.95 and (p[200:] < 0.5).mean() > 0.95


def test_export_onnx_matches_numpy(tmp_path):
    pytest.importorskip("onnx")
    import onnxruntime as ort

    rng = np.random.default_rng(1)
    mlp = train.MLP(seed=1)
    mlp.mu = rng.normal(0, 1, 16 * 96).astype(np.float32)
    mlp.sd = rng.uniform(0.5, 2, 16 * 96).astype(np.float32)
    path = tmp_path / "m.onnx"
    train.export_onnx(mlp, path)
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    assert sess.get_inputs()[0].shape[1] == 16 and sess.get_outputs()[0].shape[1] == 1
    x = rng.normal(0, 1, (4, 16, 96)).astype(np.float32)
    assert np.allclose(sess.run(None, {"x": x})[0][:, 0], mlp.predict(x), atol=1e-4)


# --- evaluate --------------------------------------------------------------------------------


def test_suggest_threshold():
    rows = [evaluate.Row(0.3, 1.0, 3.0), evaluate.Row(0.5, 0.97, 0.4), evaluate.Row(0.6, 0.97, 0.0),
            evaluate.Row(0.8, 0.80, 0.0)]
    assert evaluate.suggest(rows).threshold == 0.6
    assert evaluate.suggest([evaluate.Row(0.5, 1.0, 2.0)]) is None


class FakeDetector:
    name = "fake"

    def __init__(self):
        self.resets = 0

    def process(self, block):
        return 0.9 if np.abs(block.astype(np.int32)).max() > 4000 else 0.0

    def reset(self):
        self.resets += 1


def test_evaluate_with_fake_detector(tmp_path):
    common.write_wav(tmp_path / "p1.wav", tone(0.5))
    common.write_wav(tmp_path / "n1.wav", with_silence(tone(0.3), 5, 4.7))  # 10 s, 1 disparo falso
    common.write_wav(tmp_path / "n2.wav", (np.random.default_rng(0).standard_normal(RATE * 10) * 50)
                     .astype(np.int16))
    lines = []
    negs = [tmp_path / "n1.wav", tmp_path / "n2.wav"]
    best = evaluate.evaluate(FakeDetector(), [tmp_path / "p1.wav"], negs, out=lines.append)
    assert best is None  # 1 falso em 20 s = 180/h
    assert any("180.00" in s for s in lines) and any("100.0%" in s for s in lines)


def test_pastas_por_palavra(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    root = tmp_path / "magi" / "wakeword-data"
    assert common.data_dir() == root / "condessa"
    assert common.data_dir("outra") == root / "outra"
    assert common.train_dir() == tmp_path / "magi" / "wakeword-train"
    assert train.TEXTS == ["Condessa", "Hey Condessa", "Oi Condessa", "Oh Condessa"]
