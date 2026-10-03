"""Sessões onnxruntime enxutas para o satélite (tarefa 1.23; RNF-02).

Wake word e VAD rodam modelos minúsculos a cada bloco de 80 ms. O padrão do onnxruntime é feito
para vazão: arena de memória que só cresce e "memory pattern" pré-alocado por forma de entrada.
Aqui não há ganho nisso, só RAM ociosa. ``session_options`` liga o modo enxuto (1 thread, sem arena,
sem memory pattern) e ``lean_sessions`` o impõe às sessões que o openWakeWord cria por dentro.

``import_openwakeword_model`` evita que ``import openwakeword`` puxe scipy + scikit-learn (o
``__init__`` do pacote importa o treinador de verificadores, que não usamos): ~40 MB a menos.
"""

from __future__ import annotations

import contextlib
import sys
import types
from collections.abc import Iterator
from typing import Any

_VERIFIER = "openwakeword.custom_verifier_model"


def session_options(ort: Any) -> Any:
    """``SessionOptions`` com 1 thread, sem arena de CPU e sem memory pattern."""
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.enable_cpu_mem_arena = False
    opts.enable_mem_pattern = False
    return opts


@contextlib.contextmanager
def lean_sessions(ort: Any) -> Iterator[None]:
    """Durante o bloco, toda ``ort.InferenceSession(...)`` nasce com ``session_options`` (só CPU)."""
    original = ort.InferenceSession

    def factory(path: Any, sess_options: Any = None, providers: Any = None, **kwargs: Any) -> Any:
        return original(path, sess_options=session_options(ort), providers=["CPUExecutionProvider"], **kwargs)

    ort.InferenceSession = factory
    try:
        yield
    finally:
        ort.InferenceSession = original


def _stub_verifier() -> None:
    if _VERIFIER in sys.modules:
        return
    stub = types.ModuleType(_VERIFIER)

    def train_custom_verifier(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("treino de verificador do openWakeWord desligado no Magui")

    stub.train_custom_verifier = train_custom_verifier  # type: ignore[attr-defined]
    sys.modules[_VERIFIER] = stub


def import_openwakeword_model() -> type:
    """``openwakeword.model.Model`` sem carregar scipy/scikit-learn."""
    _stub_verifier()
    from openwakeword.model import Model

    return Model
