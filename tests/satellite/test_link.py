"""Satélite <-> núcleo falso (servidor Wyoming em porta efêmera)."""

import asyncio
import time
from pathlib import Path

import numpy as np
import pytest
from wyoming.event import async_read_event

from magi.common.config import load_config
from magi.common.contracts import CHUNK_SAMPLES, SatelliteHello, WakeEvent, WakeSource
from magi.common.events import from_event
from magi.satellite.__main__ import CoreClient, parse_args, reload_handler, run, wake_loop
from magi.satellite.capture import ArraySource
from magi.satellite.wake import WakeSettings, WakeSpotter

DATA = Path(__file__).parent / "data"


class FakeCore:
    def __init__(self):
        self.received: asyncio.Queue = asyncio.Queue()
        self.connections = 0
        self.writers = []

    async def _handle(self, reader, writer):
        self.connections += 1
        self.writers.append(writer)
        while (ev := await async_read_event(reader)) is not None:
            await self.received.put((time.monotonic(), from_event(ev)))
        writer.close()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        for w in self.writers:
            w.close()
        self.server.close()

    async def get(self, timeout=3.0):
        return await asyncio.wait_for(self.received.get(), timeout)

    def drop_all(self):
        for w in self.writers:
            w.close()
        self.writers.clear()


class Scripted:
    """Detector falso: nota alta nos blocos listados."""

    name = "fake"

    def __init__(self, hits):
        self.hits = set(hits)
        self.i = 0

    def process(self, block):
        self.i += 1
        return 0.9 if self.i - 1 in self.hits else 0.0

    def reset(self):
        pass


async def test_hello_primeiro_e_wake():
    async with FakeCore() as core:
        client = CoreClient(SatelliteHello(satellite="pc"), "127.0.0.1", core.port)
        client.start()
        await client.wait_connected(3)
        src = ArraySource(np.zeros(CHUNK_SAMPLES * 10, np.int16))
        await wake_loop(src, WakeSpotter(Scripted({4}), gate_dbfs=None), client, "pc")
        _, first = await core.get()
        _, second = await core.get()
        await client.stop()
    assert first == SatelliteHello(satellite="pc")
    assert isinstance(second, WakeEvent)
    assert second.source == WakeSource.WAKE and second.satellite == "pc" and second.score == 0.9
    assert second.timestamp is not None


async def test_reconecta_e_manda_hello_de_novo():
    async with FakeCore() as core:
        client = CoreClient(SatelliteHello(satellite="pc"), "127.0.0.1", core.port, retry_s=0.05)
        client.start()
        await client.wait_connected(3)
        assert isinstance((await core.get())[1], SatelliteHello)
        core.drop_all()
        for _ in range(100):
            if core.connections == 2 and client.connected:
                break
            await asyncio.sleep(0.02)
        assert isinstance((await core.get())[1], SatelliteHello)
        assert await client.send(WakeEvent(source=WakeSource.WAKE, satellite="pc", score=0.8))
        assert isinstance((await core.get())[1], WakeEvent)
        await client.stop()


async def test_sem_nucleo_descarta_sem_quebrar():
    client = CoreClient(SatelliteHello(satellite="pc"), "127.0.0.1", 1, retry_s=0.05)
    client.start()
    await asyncio.sleep(0.1)
    assert not client.connected
    assert not await client.send(WakeEvent(source=WakeSource.WAKE, satellite="pc"))
    await client.stop()


def test_recarga_do_config_muda_limiar(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[satellite]\nwake_threshold = 0.7\n")
    sp = WakeSpotter(Scripted([]), threshold=0.5)
    handler = reload_handler(sp, WakeSettings())
    handler(load_config(cfg))
    assert sp.threshold == 0.7
    cfg.write_text("[satellite]\nwake_threshold = 7\n")
    handler(load_config(cfg))  # inválido: mantém o anterior
    assert sp.threshold == 0.7
    cfg.write_text("[satellite]\nwake_threshold = 0.9\n")
    reload_handler(sp, WakeSettings(), fixed_threshold=0.4)(load_config(cfg))  # --threshold vence
    assert sp.threshold == 0.4


async def test_run_ponta_a_ponta_com_wav_real(tmp_path):
    """Satélite completo com o WAV gravado em tempo real: hello, depois wake em < 300 ms."""
    from magi.satellite.wake import DEFAULT_WAKE_MODEL, default_models_dir, resolve_model

    try:
        resolve_model(DEFAULT_WAKE_MODEL, default_models_dir())
    except FileNotFoundError:
        pytest.skip("modelos do openWakeWord não baixados")
    cfg = tmp_path / "config.toml"
    cfg.write_text('[satellite]\nid = "teste"\nwake_threshold = 0.5\n')
    async with FakeCore() as core:
        args = parse_args(["--port", str(core.port), "--config", str(cfg),
                           "--wav", str(DATA / "hey_jarvis.wav")])
        task = asyncio.create_task(run(args))
        t0, hello = await core.get(timeout=10)  # chega junto com o início da captura
        t_wake, wake = await core.get(timeout=6)
        await task
    assert hello.satellite == "teste"
    assert isinstance(wake, WakeEvent) and wake.satellite == "teste"
    # fim da fala no arquivo: 1,0 s de silêncio + 0,879 s de frase
    latency = (t_wake - t0) - 1.879
    assert latency < 0.3, latency
