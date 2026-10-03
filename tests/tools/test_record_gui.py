"""Gravador com interface do wake word: microfone falso, Qt offscreen."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.wakeword import record, record_gui  # noqa: E402
from tools.wakeword.common import AUDIO_RATE, read_wav  # noqa: E402

_app = QApplication.instance() or QApplication([])


class FakeMic:
    def __init__(self):
        self.pending: list[np.ndarray] = []
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def drain(self):
        out, self.pending = self.pending, []
        return out

    def push(self, pcm: np.ndarray):
        for i in range(0, len(pcm), record_gui.CHUNK):
            self.pending.append(pcm[i : i + record_gui.CHUNK])


def tone(seconds: float, amp: float = 8000.0, freq: float = 300.0) -> np.ndarray:
    t = np.arange(int(seconds * AUDIO_RATE)) / AUDIO_RATE
    return (np.sin(2 * np.pi * freq * t) * amp).astype(np.int16)


def quiet(seconds: float) -> np.ndarray:
    return (np.random.default_rng(1).standard_normal(int(seconds * AUDIO_RATE)) * 10).astype(np.int16)


TAKES = [record.Take("positive", "normal", f"Condessa {i}", "voz normal", 2.5) for i in range(3)] + [
    record.Take("negative", "frase", "Com certeza.", "voz normal", 3.5),
    record.Take("noise", "quarto", "(silêncio)", "fique quieto", 1.0),
]


@pytest.fixture
def make(tmp_path):
    made = []

    def _make():
        mic, beeps = FakeMic(), []
        win = record_gui.RecorderWindow(record_gui.Session(TAKES, tmp_path), mic,
                                        beep=lambda: beeps.append(1), play=lambda pcm: None)
        made.append(win)
        return win, mic, beeps

    yield _make
    for w in made:
        w.close()


def hold(win, mic, pcm):
    win.press()
    mic.push(pcm)
    win.poll()
    win.release()


def test_hold_saves_and_advances_progress(make, tmp_path):
    win, mic, beeps = make()
    assert mic.started
    assert "Positivas 0/3" in win.progress_lbl.text()
    assert "Condessa 0" in win.say_lbl.text()
    hold(win, mic, np.concatenate([quiet(0.3), tone(0.6), quiet(0.3)]))
    assert len(list((tmp_path / "positive").glob("*.wav"))) == 1
    assert "Positivas 1/3" in win.progress_lbl.text()
    assert "Condessa 1" in win.say_lbl.text()
    assert beeps == [1] and "salvo" in win.status_lbl.text()


def test_silent_take_is_not_saved(make, tmp_path):
    win, mic, beeps = make()
    hold(win, mic, quiet(1.0))
    assert not (tmp_path / "positive").exists() or not list((tmp_path / "positive").glob("*.wav"))
    assert beeps == [] and "não salvei" in win.status_lbl.text()
    assert "Condessa 0" in win.say_lbl.text()
    hold(win, mic, tone(0.05))  # toque rápido demais: curto, não salva
    assert win.session.pos == 0


def test_redo_replaces_last(make, tmp_path):
    win, mic, _ = make()
    hold(win, mic, tone(0.6))
    hold(win, mic, tone(0.6))
    files = sorted((tmp_path / "positive").glob("*.wav"))
    assert len(files) == 2
    win.redo()
    assert "Condessa 1" in win.say_lbl.text()
    hold(win, mic, tone(0.6, freq=600.0, amp=4000.0))
    files2 = sorted((tmp_path / "positive").glob("*.wav"))
    assert [f.name for f in files2] == [f.name for f in files]
    assert np.abs(read_wav(files2[1]).astype(np.int32)).max() < 4500  # é a gravação nova
    assert "Positivas 2/3" in win.progress_lbl.text()


def test_resume_and_finish(make, tmp_path):
    win, mic, _ = make()
    hold(win, mic, tone(0.6))
    hold(win, mic, tone(0.6))
    win.close()
    win, mic, beeps = make()  # reabre: retoma no 3º positivo
    assert "Condessa 2" in win.say_lbl.text() and "Positivas 2/3" in win.progress_lbl.text()
    hold(win, mic, tone(0.6))
    win.skip()  # pula a negativa
    assert "Silêncio" in win.say_lbl.text()
    win.press()  # ruído: grava 1 s com contagem
    mic.push(quiet(1.2))
    win.poll()
    assert len(list((tmp_path / "noise").glob("*.wav"))) == 1
    assert win.session.current() is None and "pulados" in win.say_lbl.text()
    win.close()
    win, mic, _ = make()  # volta só para a negativa pulada
    assert "Com certeza" in win.say_lbl.text()
    hold(win, mic, tone(0.6))
    assert "Pronto! Pode avisar o Claude" in win.say_lbl.text()
    assert str(tmp_path) in win.how_lbl.text()


def test_auto_mode_records_on_voice_and_closes_on_silence(make, tmp_path):
    win, mic, beeps = make()
    win.auto_chk.setChecked(True)
    mic.push(np.concatenate([quiet(1.0), tone(0.7), quiet(0.8)]))
    win.poll()
    files = list((tmp_path / "positive").glob("*.wav"))
    assert len(files) == 1 and beeps == [1]
    assert 0.5 < len(read_wav(files[0])) / AUDIO_RATE < 1.3
    assert "Condessa 1" in win.say_lbl.text()
