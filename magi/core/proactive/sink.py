"""Entrega proativa (R15.1, R15.2, R15.6): o único caminho para o Magui falar sem ser chamado.

``ProactiveSink.deliver(kind, speech, card, priority)``:

- o ``card`` (se houver) vai para o HUD na hora: a tela nunca interrompe nada;
- ``Priority.SCREEN``, call no Discord (qualquer satélite com ``in_call``) ou nenhum satélite
  conectado → a frase vira legenda (``SubtitleMsg``), sem voz (R15.2);
- ``Priority.VOICE`` fora de call → a frase entra numa fila e é falada pelo satélite
  (``ProactiveTarget.announce``) só quando ele estiver dormindo e livre: nunca corta uma fala ou
  um turno em curso. Se a call começar enquanto espera, ou se o satélite seguir ocupado por
  ``max_wait_s``, a frase cai para legenda.

Usos: alertas (5.3, ``magi.core.proactive.alerts``), notícias (6.10: "bomba" com
``Priority.VOICE``, "alta" com ``Priority.SCREEN``) e sugestão de música (5.4).

``offer`` (5.4): pergunta com resposta. Falada, o satélite abre a escuta curta de confirmação;
"sim/bora/pode" chama ``Offer.accept`` (o resultado é falado), "não" chama ``Offer.decline``,
silêncio volta a dormir calado. Na tela (call/sem satélite) a pergunta fica só na legenda.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from magi.common.contracts import ActionResult, CardMsg, Expression, HudSink, SubtitleMsg
from magi.core.i18n import tr

log = logging.getLogger(__name__)

RETRY_S = 0.5
MAX_WAIT_S = 120.0


class Priority(StrEnum):
    """Como entregar: ``voice`` fala fora de call (e mostra); ``screen`` só mostra."""

    VOICE = "voice"
    SCREEN = "screen"


class Outcome(StrEnum):
    """Resultado de ``deliver``: ``queued`` = vai ser falada; ``screen`` = só na tela."""

    QUEUED = "queued"
    SCREEN = "screen"


@dataclass(frozen=True, slots=True)
class Offer:
    """Pergunta proativa com resposta (5.4): ``accept`` no "sim", ``decline`` no "não"."""

    accept: Callable[[], Awaitable[ActionResult]]
    decline: Callable[[], Any] | None = None


@runtime_checkable
class ProactiveTarget(Protocol):
    """Satélite que pode falar um aviso (``magi.core.turn.TurnMachine``)."""

    @property
    def in_call(self) -> bool: ...

    async def announce(
        self, text: str, expression: Expression | None = None, *, offer: Offer | None = None
    ) -> bool:
        """Fala se estiver dormindo e livre; ``False`` = ocupado, tente depois. ``offer``: escuta
        a resposta depois da fala (5.4)."""
        ...


Targets = Callable[[], Iterable[ProactiveTarget]]


@dataclass(frozen=True, slots=True)
class _Item:
    kind: str
    speech: str
    expression: Expression | None
    offer: Offer | None = None


class ProactiveSink:
    """Fila de avisos proativos. ``targets`` pode ser ligado depois (o serviço Wyoming nasce
    depois do ``assemble``); sem ele, tudo vai só para a tela."""

    def __init__(
        self,
        hud: HudSink,
        targets: Targets | None = None,
        *,
        retry_s: float = RETRY_S,
        max_wait_s: float = MAX_WAIT_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hud = hud
        self.targets = targets
        self.retry_s = retry_s
        self.max_wait_s = max_wait_s
        self._sleep = sleep
        self._clock = clock
        self._queue: asyncio.Queue[_Item] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    def _targets(self) -> list[ProactiveTarget]:
        if self.targets is None:
            return []
        try:
            return list(self.targets())
        except Exception:
            log.exception("não consegui listar os satélites")
            return []

    def in_call(self) -> bool:
        return any(t.in_call for t in self._targets())

    async def deliver(
        self,
        kind: str,
        speech: str,
        card: CardMsg | None = None,
        priority: Priority = Priority.VOICE,
        *,
        expression: Expression | None = None,
        offer: Offer | None = None,
    ) -> Outcome:
        """Entrega um aviso (ver docstring do módulo). Não espera a fala terminar. Fala e título
        do card saem no idioma de ``[speech] language`` (``magi.core.i18n``)."""
        speech = tr(speech)
        if card is not None:
            if (title := tr(card.title)) != card.title:
                card = dataclasses.replace(card, title=title)
            await self.hud.send(card)
        targets = self._targets()
        if priority is Priority.SCREEN or not targets or any(t.in_call for t in targets):
            if speech:
                await self.hud.send(SubtitleMsg(speech))
            log.info("aviso %s só na tela: %s", kind, speech)
            return Outcome.SCREEN
        if speech:
            self._queue.put_nowait(_Item(kind, speech, expression, offer))
            if self._worker is None or self._worker.done():
                self._worker = asyncio.create_task(self._run())
        return Outcome.QUEUED

    async def drain(self) -> None:
        """Espera a fila esvaziar (testes e desligamento ordenado)."""
        await self._queue.join()

    async def aclose(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None and not worker.done():
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                await self._speak(item)
            except Exception:
                log.exception("aviso %s falhou", item.kind)
            finally:
                self._queue.task_done()

    async def _speak(self, item: _Item) -> None:
        deadline = self._clock() + self.max_wait_s
        while True:
            targets = self._targets()
            if not targets or any(t.in_call for t in targets):
                break
            extra = {"offer": item.offer} if item.offer is not None else {}
            if await targets[0].announce(item.speech, item.expression, **extra):
                log.info("aviso %s falado: %s", item.kind, item.speech)
                return
            if self._clock() >= deadline:
                log.info("aviso %s esperou demais; vai para a tela", item.kind)
                break
            await self._sleep(self.retry_s)
        await self.hud.send(SubtitleMsg(item.speech))
