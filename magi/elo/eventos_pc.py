"""Eventos e confirmações da Ayanami no PC (ayanami-central Y6.6, design §12, R9.2).

O ``NoPc`` (Y6.2) despacha ``evento`` → ``EventosPc.evento`` e ``confirma`` →
``EventosPc.confirma``.

- ``evento``: vai para a proatividade (``magi.core.proactive.ayanami.AvisosAyanami`` sobre o
  ``ProactiveSink`` do core), com as mesmas regras de silêncio/jogo dos avisos locais. ``seq`` já
  visto (reenvio no ``retomar_desde``) é ignorado. Responde ``ack`` (devolve ``None``).
- ``confirma`` (pergunta, ``resposta is None``): responde ``ack`` na hora (o handler não segura o
  elo por 120 s) e pergunta ao Pedro pela pergunta proativa do core (``Offer``: "sim"/"não").
  Com a resposta, manda ``Confirma(pedido, resposta=…)`` com ``resp`` = id da pergunta (a Ayanami
  trata no ``hub.ao_receber(CONFIRMA)``). Sem resposta até ``expira_em`` (padrão agora + 120 s) →
  nada. ``confirma`` com ``resposta`` preenchida (respondida em outro lugar) → esquece a pergunta.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from magi.common.contracts import ActionResult
from magi.core.proactive.ayanami import AvisosAyanami
from magi.core.proactive.sink import Offer
from magi.elo.mensagens import Confirma, Envelope, Evento, Tipo

log = logging.getLogger(__name__)

PRAZO_PADRAO_S = 120.0
SEQS_LEMBRADOS = 512

Enviar = Callable[..., Awaitable[Any]]
Esperar = Callable[["asyncio.Future[bool]", float], Awaitable[bool]]


def _agora() -> datetime:
    return datetime.now(UTC)


async def _esperar(fut: asyncio.Future[bool], prazo_s: float) -> bool:
    return await asyncio.wait_for(asyncio.shield(fut), prazo_s)


class EventosPc:
    def __init__(
        self,
        core: Any = None,
        *,
        avisos: AvisosAyanami | None = None,
        enviar: Enviar | None = None,
        agora: Callable[[], datetime] = _agora,
        esperar: Esperar = _esperar,
    ) -> None:
        """``core``: ``magi.core.assemble.Core`` (``proactive``, ``ayanami``), ou ``None``.
        ``enviar(t, corpo, para, resp=…)``: padrão ``core.ayanami.cliente.enviar``."""
        self.core = core
        self._avisos = avisos
        self._enviar = enviar
        self._agora = agora
        self._esperar = esperar
        self._seqs: deque[int] = deque(maxlen=SEQS_LEMBRADOS)
        self._pendentes: dict[str, asyncio.Future[bool]] = {}
        self._tarefas: set[asyncio.Task[None]] = set()

    @property
    def avisos(self) -> AvisosAyanami:
        if self._avisos is None:
            return AvisosAyanami(getattr(self.core, "proactive", None))
        return self._avisos

    def _envio(self) -> Enviar | None:
        if self._enviar is not None:
            return self._enviar
        cliente = getattr(getattr(self.core, "ayanami", None), "cliente", None)
        return getattr(cliente, "enviar", None)

    # --- evento ---------------------------------------------------------------------------------

    async def evento(self, env: Envelope) -> None:
        ev = env.corpo
        if not isinstance(ev, Evento):
            return None
        if ev.seq in self._seqs:
            log.info("ayanami: evento %s repetido (seq %s)", ev.tipo, ev.seq)
            return None
        self._seqs.append(ev.seq)
        try:
            await self.avisos.evento(str(ev.tipo), ev.titulo, ev.resumo, proativo=ev.proativo)
        except Exception:
            log.exception("ayanami: evento %s não entregue", ev.tipo)
        return None

    # --- confirma -------------------------------------------------------------------------------

    async def confirma(self, env: Envelope) -> Confirma | None:
        c = env.corpo
        if not isinstance(c, Confirma):
            return None
        if c.resposta is not None:  # respondida no celular: a pergunta daqui perde o sentido
            fut = self._pendentes.pop(c.pedido, None)
            if fut is not None and not fut.done():
                fut.cancel()
            return None
        if c.pedido in self._pendentes:
            return None
        prazo = PRAZO_PADRAO_S
        if c.expira_em is not None:
            prazo = (c.expira_em - self._agora()).total_seconds()
        if prazo <= 0:
            log.info("ayanami: confirmação já expirada")
            return None
        fut: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pendentes[c.pedido] = fut
        t = asyncio.create_task(self._perguntar(env, c, fut, prazo), name="ayanami-confirma")
        self._tarefas.add(t)
        t.add_done_callback(self._tarefas.discard)
        return None

    async def _perguntar(self, env: Envelope, c: Confirma, fut: asyncio.Future[bool], prazo: float) -> None:
        async def aceitar() -> ActionResult:
            if not fut.done():
                fut.set_result(True)
            return ActionResult(ok=True, speech="Confirmado.")

        def recusar() -> None:
            if not fut.done():
                fut.set_result(False)

        try:
            await self.avisos.pergunta(c.descricao, Offer(accept=aceitar, decline=recusar))
            try:
                resposta = await self._esperar(fut, prazo)
            except (TimeoutError, asyncio.CancelledError):
                log.info("ayanami: confirmação sem resposta; nada enviado")
                return
            enviar = self._envio()
            if enviar is None:
                log.warning("ayanami: sem elo para responder a confirmação")
                return
            corpo = Confirma(pedido=c.pedido, descricao=c.descricao, origem=c.origem, resposta=resposta)
            await enviar(Tipo.CONFIRMA, corpo, env.de, resp=env.id)
            log.info("ayanami: confirmação respondida (%s)", "sim" if resposta else "não")
        except Exception:
            log.exception("ayanami: confirmação falhou")
        finally:
            if self._pendentes.get(c.pedido) is fut:
                del self._pendentes[c.pedido]

    async def aclose(self) -> None:
        for t in list(self._tarefas):
            t.cancel()
        for t in list(self._tarefas):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
