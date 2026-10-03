"""1.26: ganho leve antes do STT, WAV de diagnóstico e log do texto ouvido/rota/resposta."""

from datetime import UTC, datetime

import numpy as np

from magi.common.config import Config, PathsConfig
from magi.common.contracts import (
    ActionResult,
    Intent,
    IntentId,
    PcmFormat,
    RouteKind,
    RouteResult,
    Transcript,
    TurnContext,
    WakeSource,
)
from magi.core.assemble import utterance_saver
from magi.core.turn import TurnDeps, TurnPipeline
from magi.core.utterance import (
    MAX_GAIN_DB,
    PEAK_CEILING,
    UtteranceSaver,
    normalize_pcm16,
    speech_level_dbfs,
)

FMT = PcmFormat(16000, 2, 1)


def voice(dbfs, seconds=1.0, rate=16000):
    t = np.arange(int(rate * seconds)) / rate
    amp = 10 ** (dbfs / 20) * np.sqrt(2) * 32768
    return (np.sin(2 * np.pi * 220 * t) * amp).astype("<i2")


def level(pcm_bytes):
    return speech_level_dbfs(np.frombuffer(pcm_bytes, "<i2"), 16000)


def test_fala_baixa_ganha_nivel_sem_clipar():
    quiet = voice(-36)
    out, gain = normalize_pcm16(quiet.tobytes(), FMT)
    assert gain == MAX_GAIN_DB  # -36 -> -20 pediria 16 dB; limitado a 12
    assert abs(level(out) - (-36 + MAX_GAIN_DB)) < 0.5
    assert np.abs(np.frombuffer(out, "<i2")).max() < 32767


def test_ganho_limitado_pelo_pico():
    pcm = voice(-30)
    pcm[100] = 20000  # estalo: o pico limita o ganho
    out, gain = normalize_pcm16(pcm.tobytes(), FMT)
    assert 0 < gain < 10
    assert np.abs(np.frombuffer(out, "<i2")).max() <= PEAK_CEILING * 32767 + 1


def test_fala_forte_silencio_e_ruido_passam_intactos():
    for pcm in (voice(-15), np.zeros(16000, "<i2"), voice(-62)):
        out, gain = normalize_pcm16(pcm.tobytes(), FMT)
        assert gain == 0.0 and out == pcm.tobytes()
    assert normalize_pcm16(b"", FMT) == (b"", 0.0)


def test_saver_guarda_as_ultimas(tmp_path):
    saver = UtteranceSaver(tmp_path / "u", max_files=3)
    for _ in range(5):
        assert saver.save(voice(-30, 0.1).tobytes(), FMT) is not None
    files = sorted((tmp_path / "u").glob("*.wav"))
    assert len(files) == 3


def test_save_audio_do_config(tmp_path):
    def cfg(raw):
        return Config({}, {}, paths=PathsConfig(cache_dir=tmp_path), raw=raw)

    saver = utterance_saver(cfg({"debug": {"save_audio": True}}))
    assert saver is not None and saver.directory == tmp_path / "utterances"
    assert utterance_saver(cfg({})) is None
    assert utterance_saver(cfg({"debug": {"save_audio": False}})) is None


class Stt:
    name = model = "fake"
    free_tier = False

    def __init__(self):
        self.got = None

    async def transcribe(self, audio, fmt, *, hint="", language="pt", personal):
        self.got = audio
        return Transcript.raw("abre o jogo")


class Router:
    def route(self, text, ctx):
        return RouteResult(RouteKind.LOCAL, text, 95, Intent(IntentId.GAME_OPEN))


class Actions:
    def handles(self, intent_id):
        return True

    async def run(self, req):
        return ActionResult(ok=True, speech="Abrindo o jogo.")


async def test_turno_loga_texto_rota_e_resposta_e_salva_wav(tmp_path, caplog):
    caplog.set_level("INFO", logger="magi.core.turn")
    stt = Stt()
    pipe = TurnPipeline(TurnDeps(stt=stt, router=Router(), actions=Actions(),
                                 save_audio=UtteranceSaver(tmp_path)))
    ctx = TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime.now(UTC))
    audio = voice(-36).tobytes()
    transcript = await pipe.transcribe(audio, FMT, ctx)
    assert stt.got != audio and level(stt.got) > level(audio) + 10  # STT recebeu o áudio com ganho
    assert len(list(tmp_path.glob("*.wav"))) == 1
    assert 'pc: ouvi "abre o jogo" (1.0 s de áudio, ganho +12.0 dB)' in caplog.text
    await pipe.respond(transcript, ctx)
    assert f'pc: rota local:{IntentId.GAME_OPEN} (95) -> "Abrindo o jogo."' in caplog.text
