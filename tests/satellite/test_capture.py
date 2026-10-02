import time
import wave

import numpy as np

from magi.common.contracts import CHUNK_BYTES, CHUNK_SAMPLES
from magi.satellite import capture
from magi.satellite.capture import ArraySource, WavSource, iter_blocks, pipewire_alsa_props, read_wav


def test_import_nao_carrega_sounddevice():
    # sounddevice precisa do PortAudio de sistema; só é importado ao abrir o microfone
    src = open(capture.__file__).read().split("def start", 1)[0]
    assert "import sounddevice" not in src


def test_iter_blocks_completa_ultimo_bloco():
    blocks = iter_blocks(np.ones(CHUNK_SAMPLES * 2 + 10, np.int16))
    assert len(blocks) == 3
    assert all(len(b) == CHUNK_BYTES for b in blocks)
    last = np.frombuffer(blocks[-1], "<i2")
    assert last[:10].tolist() == [1] * 10 and not last[10:].any()


def test_iter_blocks_converte_float():
    b = iter_blocks(np.full(CHUNK_SAMPLES, 0.5, np.float32))[0]
    assert np.frombuffer(b, "<i2")[0] == 16383


def test_read_wav_reamostra_e_mistura(tmp_path):
    p = tmp_path / "x.wav"
    st = np.zeros((44100, 2), np.int16)
    st[:, 0] = 1000
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(st.tobytes())
    pcm = read_wav(p)
    assert pcm.dtype == np.int16
    assert abs(len(pcm) - 16000) <= 1
    assert abs(int(pcm[8000]) - 500) <= 2


async def test_array_source_rapido():
    src = ArraySource(np.zeros(CHUNK_SAMPLES * 5, np.int16))
    got = [b async for b in src.blocks()]
    assert len(got) == 5


async def test_array_source_tempo_real():
    src = ArraySource(np.zeros(CHUNK_SAMPLES * 4, np.int16), realtime=True)
    t0 = time.monotonic()
    n = 0
    async for _ in src.blocks():
        n += 1
    dt = time.monotonic() - t0
    assert n == 4
    assert 0.30 <= dt < 0.45  # 4 x 80 ms


async def test_array_source_loop_e_close():
    src = ArraySource(np.zeros(CHUNK_SAMPLES, np.int16), loop=True)
    n = 0
    async for _ in src.blocks():
        n += 1
        if n == 7:
            await src.close()
    assert n == 7


async def test_wav_source(tmp_path):
    p = tmp_path / "a.wav"
    capture.write_wav(p, np.zeros(CHUNK_SAMPLES * 3, np.int16))
    assert len([b async for b in WavSource(p).blocks()]) == 3


def test_pipewire_alsa_props():
    assert pipewire_alsa_props() == '{ application.name = "magi" media.role = "Assistant" }'
    assert 'target.object = "mic1"' in pipewire_alsa_props(target="mic1")
