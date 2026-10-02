"""Lado do núcleo no socket do HUD (§6, R17, tarefa 1.4).

O núcleo é o **servidor** do socket Unix (``hud_socket_path()``); cada HUD conecta como cliente.
``HudServer`` implementa ``HudSink``: ``send`` manda uma linha JSON a todos os HUDs conectados e
nunca levanta (HUD fechado = mensagem descartada). Um HUD que conecta depois recebe o último
``state`` para mostrar a expressão certa. Linhas vindas do HUD (``cmd``) vão para
``on_command``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import stat
from pathlib import Path

from magi.common.contracts import CmdMsg, HudCommandHandler, HudMessage, StateMsg, hud_socket_path
from magi.common.events import HudDecodeError, decode_hud, encode_hud_line

log = logging.getLogger(__name__)

#: Tempo máximo esperando um HUD lento esvaziar o buffer antes de desconectá-lo (s).
WRITE_TIMEOUT_S = 0.5


class NullHud:
    """``HudSink`` que descarta tudo (sem HUD)."""

    async def send(self, msg: HudMessage) -> None:
        return None


class HudServer:
    """Servidor do socket do HUD; implementa ``HudSink`` (§6)."""

    def __init__(
        self,
        path: Path | None = None,
        on_command: HudCommandHandler | None = None,
        *,
        write_timeout: float = WRITE_TIMEOUT_S,
    ) -> None:
        self.path = path if path is not None else hud_socket_path()
        self.on_command = on_command
        self.write_timeout = write_timeout
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._handlers: set[asyncio.Task[None]] = set()
        self._last_state: bytes | None = None

    @property
    def clients(self) -> int:
        """Número de HUDs conectados."""
        return len(self._clients)

    async def start(self) -> None:
        """Cria o diretório (0700), remove socket velho e começa a aceitar HUDs."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(FileNotFoundError):
            if stat.S_ISSOCK(self.path.lstat().st_mode):
                self.path.unlink()
        self._server = await asyncio.start_unix_server(self._serve, path=str(self.path))
        os.chmod(self.path, 0o600)
        log.info("HUD: escutando em %s", self.path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
        for writer in list(self._clients):
            writer.close()
        self._clients.clear()
        for task in list(self._handlers):
            task.cancel()
        if self._handlers:
            await asyncio.gather(*self._handlers, return_exceptions=True)
        if self._server is not None:
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()

    async def send(self, msg: HudMessage) -> None:
        """Manda ``msg`` a todos os HUDs. Nunca levanta; HUD com erro ou lento é desconectado."""
        line = encode_hud_line(msg)
        if isinstance(msg, StateMsg):
            self._last_state = line
        for writer in list(self._clients):
            if not await self._write(writer, line):
                self._drop(writer)

    async def _write(self, writer: asyncio.StreamWriter, line: bytes) -> bool:
        try:
            writer.write(line)
            await asyncio.wait_for(writer.drain(), self.write_timeout)
        except (OSError, TimeoutError, RuntimeError) as e:
            log.debug("HUD: cliente descartado (%s)", e)
            return False
        return True

    def _drop(self, writer: asyncio.StreamWriter) -> None:
        self._clients.discard(writer)
        writer.close()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        log.info("HUD conectado")
        try:
            if self._last_state is not None and not await self._write(writer, self._last_state):
                return
            self._clients.add(writer)
            while line := await reader.readline():
                await self._received(line)
        except (OSError, asyncio.IncompleteReadError, ValueError) as e:
            log.debug("HUD: leitura encerrada (%s)", e)
        finally:
            self._drop(writer)
            if task is not None:
                self._handlers.discard(task)
            log.info("HUD desconectado")

    async def _received(self, line: bytes) -> None:
        if not line.strip():
            return
        try:
            msg = decode_hud(line)
        except HudDecodeError as e:
            log.warning("HUD: linha inválida: %s", e)
            return
        if not isinstance(msg, CmdMsg):
            log.debug("HUD: mensagem ignorada: %r", msg)
            return
        if self.on_command is None:
            log.info("HUD: comando sem destino: %s", msg.name)
            return
        try:
            await self.on_command(msg)
        except Exception:
            log.exception("HUD: erro no comando %s", msg.name)
