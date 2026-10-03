"""VAD do satélite: fim de fala (1 s, fala mínima), máximo de 15 s, escuta sem fala e Silero real."""

from pathlib import Path

import numpy as np
import pytest

from magi.common.contracts import (
    CHUNK_SAMPLES,
    MAX_RECORDING_MS,
    VAD_SILENCE_MS,
    AudioEndReason,
    ListenRequest,
)
from magi.satellite.capture import iter_blocks, read_wav
from magi.satellite.vad import (
    VAD_MODEL_NAME,
    Endpointer,
    VadSettings,
    default_vad_dir,
    download_vad_model,
    load_vad,
)

DATA = Path(__file__).parent / "data"
SILENT = np.zeros(CHUNK_SAMPLES, np.int16)


class ScriptedVad:
    """Probabilidade de fala dada por uma lista (último valor se repete)."""

    def __init__(self, probs):
        self.probs = list(probs)
        self.i = 0
        self.resets = 0

    def process(self, block):
        p = self.probs[min(self.i, len(self.probs) - 1)]
        self.i += 1
        return p

    def reset(self):
        self.resets += 1


def run_until_end(ep, limit=1000):
    for n in range(1, limit + 1):
        if (r := ep.feed(SILENT)) is not None:
            return r, n
    raise AssertionError("não terminou")


def silero():
    try:
        return load_vad()
    except FileNotFoundError:
        pytest.skip("Silero VAD não baixado (uv run magi-satellite --download-models)")


def test_corta_apos_o_silencio_de_fim():
    ep = Endpointer(ScriptedVad([0.9] * 10 + [0.0]))
    reason, n = run_until_end(ep)
    assert reason is AudioEndReason.VAD
    assert n == 10 + -(-VAD_SILENCE_MS // 80)  # 13 blocos de silêncio = 1040 ms


def test_pausa_curta_nao_corta_e_histerese():
    # 0.4 ainda é fala depois que a fala começou (limiar de saída 0.35); pausa de 560 ms não corta
    probs = [0.9] * 5 + [0.4] * 5 + [0.0] * 7 + [0.9] * 5 + [0.0]
    ep = Endpointer(ScriptedVad(probs))
    reason, n = run_until_end(ep)
    assert reason is AudioEndReason.VAD and n == 22 + -(-VAD_SILENCE_MS // 80)


def test_fim_padrao_tolera_pausa_de_900ms():
    # 1.26: 700 ms cortava frases com pausa natural; agora o padrão é 1 s
    assert VAD_SILENCE_MS >= 900
    probs = [0.9] * 5 + [0.0] * 11 + [0.9] * 5 + [0.0]
    reason, n = run_until_end(Endpointer(ScriptedVad(probs)))
    assert reason is AudioEndReason.VAD and n == 21 + -(-VAD_SILENCE_MS // 80)


def test_rabo_do_wake_word_nao_arma_o_fim():
    # 2 blocos de voz (fim do "Condessa"), pausa de 1,6 s, depois o comando: nada é cortado na pausa
    probs = [0.9] * 2 + [0.0] * 20 + [0.9] * 8 + [0.0]
    ep = Endpointer(ScriptedVad(probs), min_speech_ms=240)
    reason, n = run_until_end(ep)
    assert reason is AudioEndReason.VAD and n == 30 + -(-VAD_SILENCE_MS // 80)


def test_estalo_isolado_nao_conta_como_fala():
    ep = Endpointer(ScriptedVad([0.0] * 3 + [0.9] + [0.0]), no_speech_ms=1000)
    reason, n = run_until_end(ep)
    assert reason is AudioEndReason.NO_SPEECH and not ep.heard_speech and n * 80 >= 1000


def test_voz_comecando_no_limite_do_no_speech_espera_confirmar():
    # prazo de 800 ms (10 blocos); a voz começa no 10º bloco: não desiste, grava a fala
    probs = [0.0] * 9 + [0.9] * 6 + [0.0]
    ep = Endpointer(ScriptedVad(probs), no_speech_ms=800)
    reason, n = run_until_end(ep)
    assert reason is AudioEndReason.VAD and ep.heard_speech


def test_vad_settings_do_config():
    s = VadSettings.from_raw({"satellite": {"end_silence_ms": 1200, "min_speech_ms": 160,
                                            "vad_threshold": 0.4, "preroll_ms": 480}})
    assert (s.end_silence_ms, s.min_speech_ms, s.threshold, s.preroll_ms) == (1200, 160, 0.4, 480)
    assert VadSettings.from_raw({}) == VadSettings()
    ep = s.endpointer(ScriptedVad([0.0]))
    assert (ep.silence_ms, ep.min_speech_ms, ep.threshold, ep.neg_threshold) == (1200, 160, 0.4, 0.35)
    assert s.listen_endpointer(ScriptedVad([0.0]), ListenRequest(timeout_ms=3000)).no_speech_ms == 3000
    for bad in ({"end_silence_ms": 50}, {"vad_threshold": 1.5}, {"min_speech_ms": -1}):
        with pytest.raises(ValueError):
            VadSettings.from_raw({"satellite": bad})


def test_0_4_nao_inicia_fala():
    ep = Endpointer(ScriptedVad([0.4]), no_speech_ms=1000)
    reason, n = run_until_end(ep)
    assert reason is AudioEndReason.NO_SPEECH and not ep.heard_speech


def test_corta_em_15s_falando_sem_parar():
    ep = Endpointer(ScriptedVad([0.99]))
    reason, n = run_until_end(ep)
    assert reason is AudioEndReason.MAX_LENGTH
    assert n * 80 >= MAX_RECORDING_MS and (n - 1) * 80 < MAX_RECORDING_MS


def test_listen_sem_fala_devolve_no_speech_no_prazo():
    ep = Endpointer.for_listen(ScriptedVad([0.0]), ListenRequest(timeout_ms=2000))
    reason, n = run_until_end(ep)
    assert reason is AudioEndReason.NO_SPEECH and n * 80 == 2000


def test_listen_com_fala_depois_do_prazo_inicial_nao_conta_como_no_speech():
    # fala começa aos 800 ms (antes do prazo de 2 s) e passa do prazo: termina por silêncio
    ep = Endpointer.for_listen(ScriptedVad([0.0] * 10 + [0.9] * 30 + [0.0]), ListenRequest(timeout_ms=2000))
    reason, n = run_until_end(ep)
    assert reason is AudioEndReason.VAD and n == 40 + -(-VAD_SILENCE_MS // 80)


def test_endpointer_reinicia_o_vad():
    vad = ScriptedVad([0.0])
    Endpointer(vad)
    Endpointer(vad)
    assert vad.resets == 2


def test_download_nao_rebaixa_e_usa_url(tmp_path):
    src = tmp_path / "origem.onnx"
    src.write_bytes(b"modelo")
    dest = download_vad_model(tmp_path / "vad", url=src.as_uri())
    assert dest.name == VAD_MODEL_NAME and dest.read_bytes() == b"modelo"
    src.write_bytes(b"outro")
    assert download_vad_model(tmp_path / "vad", url=src.as_uri()).read_bytes() == b"modelo"


def test_diretorio_padrao_segue_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_vad_dir() == tmp_path / "magi" / "models" / "vad"


def test_silero_real_separa_fala_de_silencio():
    vad = silero()
    fala = [vad.process(np.frombuffer(b, "<i2")) for b in iter_blocks(read_wav(DATA / "fala_ptbr.wav"))]
    assert np.mean(np.array(fala) > 0.5) > 0.8
    vad.reset()
    quieto = [vad.process(SILENT) for _ in range(20)]
    assert max(quieto) < 0.1


def test_silero_real_fala_inteira_termina_por_silencio():
    vad = silero()
    audio = np.concatenate([read_wav(DATA / "fala_ptbr.wav"), np.zeros(16000 * 2, np.int16)])
    ep = Endpointer(vad)
    reason = None
    for b in iter_blocks(audio):
        if (reason := ep.feed(b)) is not None:
            break
    assert reason is AudioEndReason.VAD
    # a frase (~4,9 s, com pausas internas de ~200 ms) não é cortada no meio
    assert ep.elapsed_ms >= 4900
