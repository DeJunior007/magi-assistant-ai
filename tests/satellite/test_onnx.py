"""Sessões onnxruntime enxutas do satélite (tarefa 1.23; RNF-02)."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import onnxruntime as ort
import pytest

from magi.satellite.onnx import lean_sessions, session_options


def _assert_lean(opts: ort.SessionOptions) -> None:
    assert opts.intra_op_num_threads == 1
    assert opts.inter_op_num_threads == 1
    assert opts.enable_cpu_mem_arena is False
    assert opts.enable_mem_pattern is False


def test_session_options_are_lean() -> None:
    _assert_lean(session_options(ort))


def test_lean_sessions_forces_options_and_restores() -> None:
    made: list[tuple[str, object, object]] = []

    def fake_session(path, sess_options=None, providers=None, **kw):
        made.append((path, sess_options, providers))
        return object()

    fake = types.SimpleNamespace(SessionOptions=ort.SessionOptions, InferenceSession=fake_session)
    with lean_sessions(fake):
        cuda = ["CUDAExecutionProvider"]
        fake.InferenceSession("m.onnx", sess_options=ort.SessionOptions(), providers=cuda)
    assert fake.InferenceSession is fake_session
    [(path, opts, providers)] = made
    assert path == "m.onnx" and providers == ["CPUExecutionProvider"]
    _assert_lean(opts)  # type: ignore[arg-type]


def test_silero_vad_session_is_lean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.satellite.vad import SileroVad

    seen: list[ort.SessionOptions] = []

    def fake_session(path, sess_options=None, providers=None, **kw):
        seen.append(sess_options)
        return object()

    monkeypatch.setattr(ort, "InferenceSession", fake_session)
    model = tmp_path / "silero_vad.onnx"
    model.write_bytes(b"x")
    SileroVad(model)
    _assert_lean(seen[0])


def test_wake_detector_sessions_are_lean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from magi.satellite import wake

    seen: list[ort.SessionOptions] = []

    def fake_session(path, sess_options=None, providers=None, **kw):
        seen.append(sess_options)
        return object()

    class FakeModel:
        def __init__(self, **kw: object) -> None:
            for _ in range(3):  # melspectrogram + embedding + modelo, como o openWakeWord
                ort.InferenceSession("x.onnx", sess_options=ort.SessionOptions())
            self.preprocessor = None

    monkeypatch.setattr(ort, "InferenceSession", fake_session)
    monkeypatch.setattr("magi.satellite.onnx.import_openwakeword_model", lambda: FakeModel)
    for name in (*wake.FEATURE_MODELS, "hey_jarvis_v0.1.onnx"):
        (tmp_path / name).write_bytes(b"x")
    wake.OpenWakeWordDetector("hey_jarvis", models_dir=tmp_path)
    assert len(seen) == 3
    for opts in seen:
        _assert_lean(opts)


def test_openwakeword_import_skips_scipy_and_sklearn() -> None:
    code = (
        "import sys; from magi.satellite.onnx import import_openwakeword_model as f; f(); "
        "print(sorted(m for m in ('scipy', 'sklearn') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
