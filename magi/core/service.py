"""Serviço ``magi-core``: servidor Wyoming dos satélites e socket do HUD (§3, §4.1, tarefa 1.4).

Cada conexão TCP é um satélite. O primeiro evento deve ser ``magi-hello``; depois os eventos são
decodificados (``from_event``) e entregues ao ``TurnMachine`` daquele satélite. A resposta volta
pela mesma conexão (``WyomingLink``, que implementa ``SatelliteLink``).

Uso em código (e nos testes)::

    hud = HudServer(path)
    await hud.start()
    service = CoreService(TurnDeps(stt=..., router=..., speaker=...), hud, port=0)
    await service.start()          # service.port tem a porta real
    ...
    await service.stop()
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
from collections.abc import AsyncIterable, Mapping
from pathlib import Path

from wyoming.event import Event, async_read_event, async_write_event

from magi.common.config import Config, ConfigError, load_config, parse_config
from magi.common.contracts import (
    CONFIRM_TIMEOUT_MS,
    WYOMING_HOST,
    WYOMING_PORT,
    AudioEnd,
    CmdMsg,
    CoreToSatellite,
    HudSink,
    PcmFormat,
    SatelliteHello,
)
from magi.common.events import EventDecodeError, audio_chunk, audio_start, from_event, to_event
from magi.core.assemble import Core, assemble
from magi.core.hud_client import HudServer, NullHud
from magi.core.turn import CONFIRM_GRACE_MS, TurnDeps, TurnMachine, TurnPipeline

log = logging.getLogger(__name__)

#: Prazo para o satélite mandar ``magi-hello`` depois de conectar (s).
HELLO_TIMEOUT_S = 5.0


class WyomingLink:
    """Conexão com um satélite; implementa ``SatelliteLink`` (R22.1, R22.3)."""

    def __init__(self, hello: SatelliteHello, writer: asyncio.StreamWriter) -> None:
        self.hello = hello
        self._writer = writer
        self._lock = asyncio.Lock()

    async def write_event(self, event: Event) -> None:
        # Cada evento sai inteiro (escrita síncrona); o lock só ordena escritores concorrentes.
        async with self._lock:
            await async_write_event(event, self._writer)

    async def send(self, msg: CoreToSatellite) -> None:
        await self.write_event(to_event(msg))

    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
        """``audio-start``, ``audio-chunk``..., ``audio-stop``. Volta ao fim do envio."""
        await self.write_event(audio_start(fmt))
        async for pcm in audio:
            if pcm:
                await self.write_event(audio_chunk(pcm, fmt))
        await self.send(AudioEnd())


class CoreService:
    """Servidor Wyoming do núcleo, um ``TurnMachine`` por satélite conectado (§3.1)."""

    def __init__(
        self,
        deps: TurnDeps | None = None,
        hud: HudSink | None = None,
        *,
        host: str = WYOMING_HOST,
        port: int = WYOMING_PORT,
        confirm_timeout_ms: int = CONFIRM_TIMEOUT_MS,
        confirm_grace_ms: int = CONFIRM_GRACE_MS,
    ) -> None:
        self.pipeline = TurnPipeline(deps)
        self.hud: HudSink = hud if hud is not None else NullHud()
        self.host = host
        self._port = port
        self.confirm_timeout_ms = confirm_timeout_ms
        self.confirm_grace_ms = confirm_grace_ms
        self._server: asyncio.Server | None = None
        self._machines: dict[str, TurnMachine] = {}
        self._conns: set[asyncio.Task[None]] = set()

    @property
    def deps(self) -> TurnDeps:
        return self.pipeline.deps

    @property
    def port(self) -> int:
        """Porta real (útil com ``port=0``)."""
        if self._server is not None and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    @property
    def satellites(self) -> Mapping[str, TurnMachine]:
        """Satélites conectados, por id do ``magi-hello``."""
        return self._machines

    def machine(self, satellite: str) -> TurnMachine | None:
        return self._machines.get(satellite)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, self.host, self._port)
        log.info("núcleo: Wyoming em %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
        for task in list(self._conns):
            task.cancel()
        if self._conns:
            await asyncio.gather(*self._conns, return_exceptions=True)
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None

    async def on_hud_command(self, cmd: CmdMsg) -> None:
        """Comandos vindos do HUD (§6). Ainda nenhum é tratado no núcleo."""
        log.info("HUD pediu %s (sem tratamento ainda)", cmd.name)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._conns.add(task)
        machine: TurnMachine | None = None
        try:
            hello = await self._read_hello(reader)
            if hello is None:
                return
            link = WyomingLink(hello, writer)
            machine = TurnMachine(
                link,
                self.hud,
                self.pipeline,
                confirm_timeout_ms=self.confirm_timeout_ms,
                confirm_grace_ms=self.confirm_grace_ms,
            )
            old = self._machines.get(hello.satellite)
            if old is not None:
                log.warning("satélite %s reconectou; a conexão antiga perde o turno", hello.satellite)
                await old.close()
            self._machines[hello.satellite] = machine
            log.info("satélite conectado: %s", hello.satellite)
            await self._loop(reader, machine)
        except (OSError, asyncio.IncompleteReadError) as e:
            log.info("conexão encerrada: %s", e)
        finally:
            if machine is not None:
                with contextlib.suppress(Exception):
                    await machine.close()
                if self._machines.get(machine.satellite) is machine:
                    del self._machines[machine.satellite]
                log.info("satélite desconectado: %s", machine.satellite)
            writer.close()
            if task is not None:
                self._conns.discard(task)

    async def _read_hello(self, reader: asyncio.StreamReader) -> SatelliteHello | None:
        try:
            event = await asyncio.wait_for(async_read_event(reader), HELLO_TIMEOUT_S)
        except TimeoutError:
            log.warning("satélite não mandou magi-hello a tempo")
            return None
        if event is None:
            return None
        try:
            msg = from_event(event)
        except EventDecodeError as e:
            log.warning("primeiro evento inválido: %s", e)
            return None
        if not isinstance(msg, SatelliteHello):
            log.warning("primeiro evento não é magi-hello: %s", event.type)
            return None
        return msg

    async def _loop(self, reader: asyncio.StreamReader, machine: TurnMachine) -> None:
        while (event := await async_read_event(reader)) is not None:
            try:
                msg = from_event(event)
            except EventDecodeError as e:
                log.warning("%s: evento ignorado: %s", machine.satellite, e)
                continue
            try:
                await machine.handle(msg)
            except Exception:
                log.exception("%s: erro tratando %s", machine.satellite, event.type)


async def run(
    *,
    host: str = WYOMING_HOST,
    port: int = WYOMING_PORT,
    hud_path: Path | None = None,
    deps: TurnDeps | None = None,
    config: Config | None = None,
) -> None:
    """Sobe HUD e Wyoming e roda até SIGINT/SIGTERM. Sem ``deps``, monta o núcleo a partir de
    ``config`` (``magi.core.assemble``; sem config, tudo degradado)."""
    hud = HudServer(hud_path)
    core: Core | None = None
    if deps is None:
        core = await assemble(config if config is not None else parse_config({}), hud)
        deps = core.deps
    service = CoreService(deps, hud, host=host, port=port)
    hud.on_command = service.on_hud_command
    try:
        await hud.start()
    except OSError as e:
        log.warning("HUD indisponível (%s): seguindo sem HUD", e)
    await service.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await service.stop()
        await hud.stop()
        if core is not None:
            await core.aclose()


def main(argv: list[str] | None = None) -> None:
    """Entry point ``magi-core``."""
    parser = argparse.ArgumentParser(prog="magi-core", description="Núcleo da Magui")
    parser.add_argument("--host", default=WYOMING_HOST)
    parser.add_argument("--port", type=int, default=WYOMING_PORT)
    parser.add_argument("--hud-socket", type=Path, default=None, help="padrão: hud_socket_path()")
    parser.add_argument("--config", type=Path, default=None, help="padrão: ~/.config/magi/config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config(args.config)
        log.info("config: %s", config.source)
    except ConfigError as e:
        log.warning("%s; seguindo com os padrões (sem provedores)", e)
        config = parse_config({})
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(host=args.host, port=args.port, hud_path=args.hud_socket, config=config))


if __name__ == "__main__":
    main()
