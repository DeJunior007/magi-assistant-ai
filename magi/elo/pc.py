"""``NoPc``: o elo do PC com a Ayanami dentro do ``magi-core`` (design §7.2, §12; spec §6.2–§6.3).

Montado por ``assemble`` só com ``[ayanami]`` no ``config.toml`` (regra 10: sem a seção nada
muda) e ligado por ``run`` depois do ``CoreService`` existir (``iniciar``):

- ``EloCliente`` com ``[ayanami] url`` e o token do PC (``magi.elo.credenciais``), nome ``pc``;
- ``Bate.custos_mes_usd`` = total do ``custos_pc`` (Y6.6) ou, sem ele, o gasto do mês do
  ``Budget`` local (relido a cada ``custos_s``);
- despacho: ``turno`` e quadros → ``PonteTurnos``; ``evento``/``confirma`` →
  ``magi.elo.eventos_pc``; ``resumo_nuvem`` → ``magi.elo.reconciliar`` (``Ack(ids=…)``); custos →
  ``magi.elo.custos_pc``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Final

from magi.elo.cliente import EloCliente
from magi.elo.credenciais import token_pc, url_ayanami
from magi.elo.custos_pc import CustosPc
from magi.elo.eventos_pc import EventosPc
from magi.elo.mensagens import Ack, Envelope, Ola, ResumoNuvem, Tipo, TipoDispositivo
from magi.elo.ponte import PonteTurnos
from magi.elo.reconciliar import Reconciliador

log = logging.getLogger(__name__)

NOME: Final = "pc"
CAPS: Final = ("turno", "acao", "evento", "resumo")
CUSTOS_S: Final = 60.0


def _versao() -> str:
    try:
        return version("magi-assistant")
    except PackageNotFoundError:
        return "0.0.0"


class NoPc:
    def __init__(
        self,
        cliente: Callable[[Callable[[], Ola], Callable[[], float | None]], Any],
        core: Any = None,
        *,
        custos_s: float = CUSTOS_S,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """``cliente(ola, custos)`` cria o ``EloCliente`` (fábrica: testes passam um falso).
        ``core``: ``magi.core.assemble.Core`` (``budget``, repos) ou ``None``."""
        self.core = core
        self.cliente = cliente(self.ola, self.custos)
        self.eventos = EventosPc(core)
        self.reconciliador = Reconciliador(core)
        self.custos_pc = CustosPc(core, self.cliente)
        self.ponte: PonteTurnos | None = None
        self._custos_s = custos_s
        self._dormir = dormir
        self._gasto_local: float | None = None
        self._tarefas: list[asyncio.Task[Any]] = []

    @classmethod
    def de_config(
        cls,
        config: Any,
        core: Any = None,
        *,
        token: Callable[[], str | None] | None = None,
        **kw: Any,
    ) -> NoPc:
        """Levanta ``ValueError`` sem ``[ayanami] url`` ou sem token (o ``assemble`` avisa e
        segue sem o elo). O token nunca vai a log."""
        url = url_ayanami(config)
        if url is None:
            raise ValueError("[ayanami] url ausente")
        tok = (token or token_pc)()
        if not tok:
            raise ValueError("sem token do PC (keyring magi/ayanami_pc ou ayanami.token)")

        def fabrica(ola: Callable[[], Ola], custos: Callable[[], float | None]) -> EloCliente:
            return EloCliente(url, tok, NOME, ola, custos=custos)

        return cls(fabrica, core, **kw)

    # --- o que vai no elo -----------------------------------------------------------------------

    def ola(self) -> Ola:
        return Ola(tipo=TipoDispositivo.PC, versao=_versao(), caps=CAPS)

    def custos(self) -> float | None:
        total = self.custos_pc.total_mes()
        return total if total is not None else self._gasto_local

    # --- ciclo ----------------------------------------------------------------------------------

    def iniciar(self, service: Any) -> None:
        """Liga a ponte ao ``CoreService`` e sobe o cliente. Chamado uma vez por ``run``."""
        self.ponte = PonteTurnos(service, self.cliente)
        self.registrar(self.ponte)
        for coro, nome in ((self.cliente.rodar(), "ayanami-elo"),
                           (self.custos_pc.rodar(), "ayanami-custos"),
                           (self._le_budget(), "ayanami-budget")):
            self._tarefas.append(asyncio.create_task(coro, name=nome))

    def registrar(self, ponte: PonteTurnos) -> None:
        c = self.cliente
        c.on(Tipo.TURNO, ponte.receber)
        c.on_quadro(ponte.receber_quadro)
        c.on(Tipo.EVENTO, self.eventos.evento)
        c.on(Tipo.CONFIRMA, self.eventos.confirma)
        c.on(Tipo.RESUMO_NUVEM, self.resumo)

    async def resumo(self, env: Envelope) -> Ack | None:
        if not isinstance(env.corpo, ResumoNuvem):
            return None
        return Ack(ids=tuple(await self.reconciliador.gravar_resumo(env.corpo)))

    async def _le_budget(self) -> None:
        budget = getattr(self.core, "budget", None)
        if budget is None:
            return
        while True:
            try:
                self._gasto_local = float((await budget.status()).spent_usd)
            except Exception as e:
                log.debug("ayanami: gasto local ilegível (%s)", type(e).__name__)
            await self._dormir(self._custos_s)

    async def aclose(self) -> None:
        parar = getattr(self.cliente, "parar", None)
        if parar is not None:
            parar()
        if self.ponte is not None:
            await self.ponte.aclose()
        for t in self._tarefas:
            t.cancel()
        for t in self._tarefas:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tarefas.clear()
