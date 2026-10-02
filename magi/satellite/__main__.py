"""Satélite da Magui (``magi-satellite``): captura, wake word e envio de ``magi-wake`` (§5, R1).

Conecta no núcleo por Wyoming (``WYOMING_HOST:WYOMING_PORT``), manda ``magi-hello`` primeiro e
um ``magi-wake`` a cada ativação. Se a conexão cair, reconecta sozinho; ativações sem conexão
são descartadas (com log). O limiar do wake word é recarregado quando o ``config.toml`` é salvo.

Uso::

    uv run magi-satellite                      # microfone padrão
    uv run magi-satellite --wav frase.wav      # áudio de arquivo, em tempo real (sem microfone)
    uv run magi-satellite --download-models    # baixa os modelos do openWakeWord e sai
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

from wyoming.event import Event, async_read_event, async_write_event

from magi import __version__ as _magi_version
from magi.common.config import Config, ConfigError, ConfigWatcher
from magi.common.contracts import (
    WYOMING_HOST,
    WYOMING_PORT,
    SatelliteHello,
    SatelliteToCore,
    WakeEvent,
    WakeSource,
)
from magi.common.events import to_event
from magi.satellite.capture import AudioSource, MicSource, WavSource
from magi.satellite.wake import (
    OpenWakeWordDetector,
    WakeDetector,
    WakeSettings,
    WakeSpotter,
    download_models,
)

log = logging.getLogger("magi.satellite")

EventCallback = Callable[[Event], Awaitable[None] | None]


class CoreClient:
    """Cliente Wyoming do núcleo, com reconexão. ``magi-hello`` é sempre o primeiro evento."""

    def __init__(
        self,
        hello: SatelliteHello,
        host: str = WYOMING_HOST,
        port: int = WYOMING_PORT,
        *,
        retry_s: float = 1.0,
        max_retry_s: float = 10.0,
        on_event: EventCallback | None = None,
    ) -> None:
        self.hello = hello
        self.host = host
        self.port = port
        self.retry_s = retry_s
        self.max_retry_s = max_retry_s
        self.on_event = on_event
        self._writer: asyncio.StreamWriter | None = None
        self._connected = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def wait_connected(self, timeout: float | None = None) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="core-client")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._close_writer()

    async def _close_writer(self) -> None:
        self._connected.clear()
        w, self._writer = self._writer, None
        if w is not None:
            w.close()
            with contextlib.suppress(Exception):
                await w.wait_closed()

    async def _run(self) -> None:
        delay = self.retry_s
        while True:
            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
                await async_write_event(to_event(self.hello), writer)
                self._writer = writer
                self._connected.set()
                log.info("conectado ao núcleo em %s:%s", self.host, self.port)
                delay = self.retry_s
                while (event := await async_read_event(reader)) is not None:
                    if self.on_event is not None:
                        res = self.on_event(event)
                        if asyncio.iscoroutine(res):
                            await res
                log.warning("núcleo fechou a conexão")
            except (OSError, asyncio.IncompleteReadError) as e:
                log.debug("núcleo indisponível em %s:%s (%s)", self.host, self.port, e)
            await self._close_writer()
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.max_retry_s)

    async def send(self, msg: SatelliteToCore) -> bool:
        """Envia um evento; ``False`` se não houver conexão (o evento é descartado)."""
        w = self._writer
        if w is None:
            return False
        try:
            await async_write_event(to_event(msg), w)
        except (OSError, ConnectionError) as e:
            log.warning("falha ao enviar %s: %s", type(msg).__name__, e)
            await self._close_writer()
            return False
        return True


async def wake_loop(source: AudioSource, spotter: WakeSpotter, client: CoreClient, satellite: str) -> None:
    """Loop ocioso do satélite: wake word em cada bloco de 80 ms (único custo ocioso, §5)."""
    async for block in source.blocks():
        det = spotter.feed(block)
        if det is None:
            continue
        log.info("wake word (%.2f)", det.score)
        ev = WakeEvent(source=WakeSource.WAKE, satellite=satellite, score=round(det.score, 4),
                       timestamp=det.timestamp_ms)
        if not await client.send(ev):
            log.warning("ativação descartada: sem conexão com o núcleo")


def load_settings(config: str | None) -> tuple[WakeSettings, ConfigWatcher | None]:
    """Lê ``[satellite]`` do config. Sem config válido, usa os padrões e não recarrega."""
    try:
        watcher = ConfigWatcher(config)
        return WakeSettings.from_raw(watcher.current.raw), watcher
    except (ConfigError, TypeError, ValueError) as e:
        log.warning("%s; usando padrões do satélite sem recarga", e)
        return WakeSettings(), None


def reload_handler(
    spotter: WakeSpotter, current: WakeSettings, fixed_threshold: float | None = None
) -> Callable[[Config], None]:
    """Callback de ``ConfigWatcher``: aplica o novo ``[satellite]`` ao ``spotter`` (R1.6).

    Limiar, paciência e recarga valem na hora; ``wake_model`` só ao reiniciar. Valor inválido é
    ignorado (fica o anterior). ``fixed_threshold`` (``--threshold``) tem prioridade.
    """

    def on_reload(cfg: Config) -> None:
        try:
            new = WakeSettings.from_raw(cfg.raw)
        except (TypeError, ValueError) as e:
            log.error("recarga de [satellite] ignorada: %s", e)
            return
        if fixed_threshold is not None:
            new = replace(new, threshold=fixed_threshold)
        spotter.apply(new)
        if new.model != current.model:
            log.warning("troca de wake_model só vale ao reiniciar o satélite")

    return on_reload


async def run(args: argparse.Namespace, detector: WakeDetector | None = None) -> None:
    """Roda o satélite. ``detector`` substitui o openWakeWord (testes)."""
    settings, watcher = load_settings(args.config)
    if args.id:
        settings = replace(settings, satellite=args.id)
    if args.model:
        settings = replace(settings, model=args.model)
    if args.threshold is not None:
        settings = replace(settings, threshold=args.threshold)

    if detector is None:
        detector = OpenWakeWordDetector(settings.model, settings.models_dir)
    spotter = WakeSpotter(detector, threshold=settings.threshold, patience=settings.patience,
                          cooldown_ms=settings.cooldown_ms, gate_dbfs=settings.gate_dbfs)

    stop = asyncio.Event()
    watch_task: asyncio.Task[None] | None = None
    if watcher is not None:
        watcher.on_reload(reload_handler(spotter, settings, args.threshold))
        watch_task = asyncio.create_task(watcher.run(stop), name="config-watch")

    hello = SatelliteHello(satellite=settings.satellite, name="Magui satélite", version=_magi_version)
    client = CoreClient(hello, args.host, args.port)
    client.start()

    source: AudioSource
    if args.wav:
        source = WavSource(args.wav, realtime=True)
    else:
        source = MicSource(target=settings.mic_target)
    try:
        await wake_loop(source, spotter, client, settings.satellite)
        if args.wav:
            await asyncio.sleep(0.5)  # deixa o último evento sair
    finally:
        stop.set()
        if watch_task is not None:
            watch_task.cancel()
        await source.close()
        await client.stop()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="magi-satellite", description=__doc__.splitlines()[0])
    p.add_argument("--host", default=WYOMING_HOST)
    p.add_argument("--port", type=int, default=WYOMING_PORT)
    p.add_argument("--config", help="caminho do config.toml (padrão: $MAGI_CONFIG ou ~/.config/magi)")
    p.add_argument("--id", help="id do satélite (padrão: [satellite] id ou 'pc')")
    p.add_argument("--model", help="nome ou caminho .onnx do wake word (padrão: hey_jarvis provisório)")
    p.add_argument("--threshold", type=float, help="limiar do wake word, 0..1 (fixa; ignora recarga)")
    p.add_argument("--wav", type=Path, help="usa um WAV em tempo real no lugar do microfone")
    p.add_argument("--download-models", action="store_true", help="baixa os modelos e sai")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.download_models:
        settings, _ = load_settings(args.config)
        names = (args.model or settings.model,)
        download_models(settings.models_dir, names)
        print(f"modelos em {settings.models_dir}")
        return
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
