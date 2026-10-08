"""Bus do Learning Mode (tarefa LM4.1; design §6, ENG-001, CA-02).

``TurnPipeline``/``wiring`` ──``publish(msg)``──► ``LearningBus`` ──► observações do engine.

- ``publish`` é **síncrono** e nunca bloqueia (``put_nowait``): o turno da conversa não espera o
  Learning Engine. Fila cheia descarta o **mais antigo** (a mensagem nova é a que interessa) e
  conta em ``dropped``.
- ``get`` é o lado do consumidor (o worker de observações do ``LearningEngine``).
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

#: Tamanho da fila (design §6: ``Queue maxsize=50``).
BUS_MAXSIZE = 50


class LearningBus[T]:
    """Fila limitada, ``publish`` sem bloqueio, descarta o mais antigo quando cheia."""

    def __init__(self, maxsize: int = BUS_MAXSIZE) -> None:
        if maxsize < 1:
            raise ValueError("LearningBus precisa de maxsize >= 1")
        self.maxsize = maxsize
        self._queue: asyncio.Queue[T] = asyncio.Queue(maxsize)
        #: Itens descartados por fila cheia desde a criação.
        self.dropped = 0

    def __len__(self) -> int:
        return self._queue.qsize()

    def publish(self, item: T) -> bool:
        """Enfileira sem bloquear. ``False`` = a fila estava cheia e o mais antigo saiu."""
        try:
            self._queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            pass
        try:
            old = self._queue.get_nowait()
            self._queue.task_done()
        except asyncio.QueueEmpty:  # pragma: no cover - só com outro consumidor no meio
            old = None
        self.dropped += 1
        log.info("learning: bus cheio (%d); descartado o mais antigo: %r", self.maxsize, old)
        self._queue.put_nowait(item)
        return False

    async def get(self) -> T:
        """Próximo item (espera se vazia)."""
        item = await self._queue.get()
        self._queue.task_done()
        return item

    def get_nowait(self) -> T:
        """Próximo item ou ``asyncio.QueueEmpty``."""
        item = self._queue.get_nowait()
        self._queue.task_done()
        return item

    def clear(self) -> int:
        """Esvazia a fila; devolve quantos saíram."""
        n = 0
        while True:
            try:
                self.get_nowait()
            except asyncio.QueueEmpty:
                return n
            n += 1


__all__ = ["BUS_MAXSIZE", "LearningBus"]
