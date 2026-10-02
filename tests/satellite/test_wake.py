"""Wake word: lógica do ``WakeSpotter`` com detector falso e openWakeWord real com áudio gravado.

Os testes com o modelo real são pulados se os modelos não estiverem baixados
(``uv run magi-satellite --download-models``). O áudio "hey jarvis" foi sintetizado (espeak-ng)
para o modelo provisório; trocar pela gravação "Ei Magui" junto com o modelo do spike S4.
"""

import time
from pathlib import Path

import numpy as np
import pytest

from magi.common.contracts import CHUNK_MS, CHUNK_SAMPLES
from magi.satellite.capture import iter_blocks, read_wav
from magi.satellite.wake import (
    DEFAULT_WAKE_MODEL,
    OpenWakeWordDetector,
    WakeDetector,
    WakeSettings,
    WakeSpotter,
    block_dbfs,
    default_models_dir,
    resolve_model,
)

DATA = Path(__file__).parent / "data"


class FakeDetector:
    name = "fake"

    def __init__(self, scores):
        self.scores = list(scores)
        self.resets = 0
        self.calls = 0

    def process(self, block):
        assert len(block) == CHUNK_SAMPLES
        self.calls += 1
        return self.scores.pop(0) if self.scores else 0.0

    def reset(self):
        self.resets += 1


BLOCK = bytes(CHUNK_SAMPLES * 2)


def run(spotter, n, step=CHUNK_MS / 1000):
    return [spotter.feed(BLOCK, now=i * step) for i in range(n)]


def test_fake_cumpre_protocolo():
    assert isinstance(FakeDetector([]), WakeDetector)


def test_ativa_no_limiar_e_respeita_recarga():
    det = FakeDetector([0.1, 0.6, 0.9, 0.9, 0.9, 0.0])
    sp = WakeSpotter(det, threshold=0.5, cooldown_ms=1000, gate_dbfs=None)
    out = run(sp, 6)
    hits = [i for i, d in enumerate(out) if d]
    assert hits == [1]
    assert out[1].score == pytest.approx(0.6)
    assert det.resets == 1
    # depois da recarga (1 s) ativa de novo
    det.scores = [0.9]
    assert sp.feed(BLOCK, now=1.2) is not None


def test_paciencia_exige_blocos_seguidos():
    det = FakeDetector([0.7, 0.2, 0.7, 0.8, 0.0])
    sp = WakeSpotter(det, threshold=0.5, patience=2, gate_dbfs=None)
    out = run(sp, 5)
    assert [i for i, d in enumerate(out) if d] == [3]
    assert out[3].score == pytest.approx(0.8)


def test_limiar_recarregavel():
    det = FakeDetector([0.6, 0.6])
    sp = WakeSpotter(det, threshold=0.7, gate_dbfs=None)
    assert sp.feed(BLOCK, now=0) is None
    sp.apply(WakeSettings(threshold=0.55, gate_dbfs=None))
    assert sp.threshold == 0.55
    assert sp.feed(BLOCK, now=0.08) is not None
    with pytest.raises(ValueError):
        sp.threshold = 1.5


def test_desligado_nao_processa():
    det = FakeDetector([0.9])
    sp = WakeSpotter(det, enabled=False)
    assert sp.feed(BLOCK) is None
    assert det.calls == 0


class Recorder:
    name = "rec"

    def __init__(self):
        self.sizes = []

    def process(self, block):
        self.sizes.append(len(block))
        return 0.0

    def reset(self):
        pass


def test_block_dbfs():
    assert block_dbfs(np.zeros(CHUNK_SAMPLES, np.int16)) == -120.0
    assert block_dbfs(np.full(CHUNK_SAMPLES, 32767, np.int16)) == pytest.approx(0.0, abs=0.01)
    assert block_dbfs(np.full(CHUNK_SAMPLES, 328, np.int16)) == pytest.approx(-40.0, abs=0.1)


def test_portao_pula_silencio_e_entrega_contexto():
    rec = Recorder()
    sp = WakeSpotter(rec, gate_dbfs=-50)
    loud = np.full(CHUNK_SAMPLES, 1000, np.int16).tobytes()
    for i in range(20):  # 1,6 s de silêncio: nada roda
        sp.feed(BLOCK, now=i * 0.08)
    assert rec.sizes == [] and sp.skipped == 20
    sp.feed(loud, now=1.6)  # abre: 16 blocos de contexto de uma vez + o bloco atual
    assert rec.sizes == [16 * CHUNK_SAMPLES, CHUNK_SAMPLES]
    sp.feed(BLOCK, now=1.68)  # silêncio dentro da janela de 2 s continua passando
    assert rec.sizes[-1] == CHUNK_SAMPLES and len(rec.sizes) == 3
    sp.feed(BLOCK, now=3.7)  # depois de 2 s, fecha
    assert len(rec.sizes) == 3


def test_settings_from_raw(tmp_path):
    s = WakeSettings.from_raw({})
    assert s.model == DEFAULT_WAKE_MODEL and s.threshold == 0.5 and s.satellite == "pc"
    s = WakeSettings.from_raw({"satellite": {"id": "sala", "wake_model": "/m/ei_magui.onnx",
                                              "wake_threshold": 0.6, "models_dir": str(tmp_path),
                                              "mic_target": "alsa_input.x"}})
    assert (s.satellite, s.model, s.threshold, s.models_dir, s.mic_target) == (
        "sala", "/m/ei_magui.onnx", 0.6, tmp_path, "alsa_input.x")
    assert s.gate_dbfs == -50.0
    assert WakeSettings.from_raw({"satellite": {"wake_gate_dbfs": "off"}}).gate_dbfs is None
    with pytest.raises(ValueError):
        WakeSettings.from_raw({"satellite": {"wake_threshold": 0}})


def test_resolve_model(tmp_path):
    (tmp_path / "hey_jarvis_v0.1.onnx").write_bytes(b"")
    (tmp_path / "ei_magui.onnx").write_bytes(b"")
    assert resolve_model("hey_jarvis", tmp_path).name == "hey_jarvis_v0.1.onnx"
    assert resolve_model("ei_magui", tmp_path).name == "ei_magui.onnx"
    assert resolve_model(str(tmp_path / "ei_magui.onnx"), Path("/nada")) == tmp_path / "ei_magui.onnx"
    with pytest.raises(FileNotFoundError, match="download-models"):
        resolve_model("alexa", tmp_path)


# ---------------------------------------------------------------------------------------------
# openWakeWord real
# ---------------------------------------------------------------------------------------------


def _models_ok() -> bool:
    try:
        resolve_model(DEFAULT_WAKE_MODEL, default_models_dir())
    except FileNotFoundError:
        return False
    return (default_models_dir() / "embedding_model.onnx").exists()


needs_models = pytest.mark.skipif(not _models_ok(), reason="rode `uv run magi-satellite --download-models`")


@pytest.fixture(scope="module")
def oww():
    return OpenWakeWordDetector()


def speech_end_block(pcm: np.ndarray, level: int = 300) -> int:
    """Índice do bloco onde termina a fala (última amostra acima de ``level``)."""
    return int(np.nonzero(np.abs(pcm) > level)[0][-1]) // CHUNK_SAMPLES


@needs_models
@pytest.mark.parametrize("gate", [None, -50.0])
def test_openwakeword_detecta_frase_gravada(oww, gate):
    pcm = read_wav(DATA / "hey_jarvis.wav")
    oww.reset()
    sp = WakeSpotter(oww, threshold=0.5, gate_dbfs=gate)
    hits = [(i, d) for i, b in enumerate(iter_blocks(pcm)) if (d := sp.feed(b, now=i * 0.08))]
    assert len(hits) == 1, hits
    i, d = hits[0]
    assert d.score >= 0.5
    # ativação em < 300 ms de áudio depois do fim da fala (R1.2 / pronto da 1.1)
    assert (i - speech_end_block(pcm)) * CHUNK_MS < 300


@needs_models
@pytest.mark.parametrize("gate", [None, -50.0])
def test_openwakeword_ignora_outra_fala(oww, gate):
    oww.reset()
    sp = WakeSpotter(oww, threshold=0.5, gate_dbfs=gate)
    blocks = iter_blocks(read_wav(DATA / "fala_ptbr.wav"))
    assert not [d for i, b in enumerate(blocks) if (d := sp.feed(b, now=i * 0.08))]
    assert sp.last_score < 0.5


@needs_models
def test_openwakeword_custo_por_bloco(oww):
    # proxy rápido do RNF-01: CPU por bloco de 80 ms bem abaixo do bloco (medição real no relatório)
    rng = np.random.default_rng(1)
    blocks = [(rng.standard_normal(CHUNK_SAMPLES) * 300).astype(np.int16) for _ in range(60)]
    oww.reset()
    for b in blocks[:10]:
        oww.process(b)
    t = time.process_time()
    for b in blocks[10:]:
        oww.process(b)
    per_block_ms = (time.process_time() - t) / 50 * 1000
    assert per_block_ms < 8, per_block_ms  # folga para máquina carregada; típico ~1,5 ms
