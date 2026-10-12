"""``DriverFalso`` e ``RelogioFalso``: base dos testes da casa (spec §10.5; dono: C1.1).

``DriverFalso(capacidades, script)`` grava cada chamada (``Chamada``) e responde do ``script``, um
mapa *método → resposta*. A resposta pode ser:

- ``ResTv`` (ou ``EstadoTv`` em ``state``): devolvida sempre;
- uma exceção (instância ou classe): levantada (para testar quem chama o driver);
- uma lista/tupla: consumida em ordem, a última se repete;
- um chamável ``f(chamada)`` (sync ou async) que devolve qualquer um dos acima.

Método fora do script → ``ResTv(True)`` (``state`` → ``EstadoTv`` online). Como todo driver, o falso
**não emula**: método sem a ``Cap`` em ``capacidades.caps`` devolve ``NAO_SUPORTADO`` sem consultar o
script (mas a chamada fica gravada).
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from magi.casa.driver import Capacidades, Key, Motivo, ResTv, cap_necessaria
from magi.elo.mensagens import EstadoTv


class RelogioFalso:
    """Relógio monotônico injetável: ``relogio()`` lê, ``avancar(s)`` anda, ``dormir(s)`` anda sem
    esperar de verdade (para passar como ``sleep``)."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)
        self.dormidas: list[float] = []

    def __call__(self) -> float:
        return self.t

    def avancar(self, s: float) -> None:
        self.t += float(s)

    async def dormir(self, s: float) -> None:
        self.dormidas.append(float(s))
        self.t += max(0.0, float(s))


@dataclass(frozen=True)
class Chamada:
    metodo: str
    args: Mapping[str, Any] = field(default_factory=dict)
    t: float = 0.0


class DriverFalso:
    def __init__(
        self,
        capacidades: Capacidades,
        script: Mapping[str, Any] | None = None,
        *,
        relogio: Callable[[], float] | None = None,
        nome: str = "falso",
        tv_id: str = "falsa",
        tv_nome: str = "TV falsa",
    ) -> None:
        self.nome = nome
        self.capacidades = capacidades
        self.script: dict[str, Any] = dict(script or {})
        self.relogio = relogio or time.monotonic
        self.tv_id = tv_id
        self.tv_nome = tv_nome
        self.chamadas: list[Chamada] = []
        self._pos: dict[str, int] = {}

    # --- utilidades de teste -------------------------------------------------------------
    def metodos(self) -> list[str]:
        return [c.metodo for c in self.chamadas]

    def de(self, metodo: str) -> list[Chamada]:
        return [c for c in self.chamadas if c.metodo == metodo]

    # --- núcleo ---------------------------------------------------------------------------
    async def _responder(self, metodo: str, args: Mapping[str, Any], padrao: Any) -> Any:
        chamada = Chamada(metodo, dict(args), self.relogio())
        self.chamadas.append(chamada)
        cap = cap_necessaria(metodo, on=args.get("on"), step=args.get("step"), set_to=args.get("set_to"))
        if cap is not None and metodo != "state" and cap not in self.capacidades.caps:
            return ResTv(False, Motivo.NAO_SUPORTADO, f"{self.nome}: sem {cap.value}")
        if metodo not in self.script:
            return padrao
        resp = self.script[metodo]
        if isinstance(resp, list | tuple):
            if not resp:
                return padrao
            i = self._pos.get(metodo, 0)
            self._pos[metodo] = i + 1
            resp = resp[min(i, len(resp) - 1)]
        if callable(resp) and not (isinstance(resp, type) and issubclass(resp, BaseException)):
            resp = resp(chamada)
            if inspect.isawaitable(resp):
                resp = await resp
        if isinstance(resp, BaseException) or (isinstance(resp, type) and issubclass(resp, BaseException)):
            raise resp
        return resp

    def _estado_padrao(self) -> EstadoTv:
        return EstadoTv(id=self.tv_id, nome=self.tv_nome, driver=self.nome, online=True)

    # --- TvDriver -------------------------------------------------------------------------
    async def conectar(self) -> ResTv:
        return await self._responder("conectar", {}, ResTv(True))

    async def fechar(self) -> None:
        await self._responder("fechar", {}, None)

    async def power(self, on: bool) -> ResTv:
        return await self._responder("power", {"on": on}, ResTv(True))

    async def volume(self, step: int | None = None, set_to: int | None = None) -> ResTv:
        return await self._responder("volume", {"step": step, "set_to": set_to}, ResTv(True))

    async def mute(self, on: bool | None) -> ResTv:
        return await self._responder("mute", {"on": on}, ResTv(True))

    async def channel(self, step: int) -> ResTv:
        return await self._responder("channel", {"step": step}, ResTv(True))

    async def input(self, nome: str) -> ResTv:
        return await self._responder("input", {"nome": nome}, ResTv(True))

    async def app(self, app_id: str) -> ResTv:
        return await self._responder("app", {"app_id": app_id}, ResTv(True))

    async def key(self, key: Key) -> ResTv:
        return await self._responder("key", {"key": key}, ResTv(True))

    async def text(self, s: str) -> ResTv:
        return await self._responder("text", {"s": s}, ResTv(True))

    async def state(self) -> EstadoTv:
        return await self._responder("state", {}, self._estado_padrao())
