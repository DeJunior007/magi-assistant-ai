"""Registro ``DRIVERS`` (dono: C1.1; ninguém mais edita este arquivo).

Cada nome aponta, por import **preguiçoso**, para ``magi.casa.drivers.<nome>``, que expõe
``criar(tv: TvConfig, ctx: ContextoDriver) -> TvDriver`` (``magi/casa/driver.py``). Importar este
pacote não importa nenhuma biblioteca de TV. Módulo ainda ausente → ``DriverAusente``, que responde
``NAO_SUPORTADO`` com "dono: <ID>" em todo método (a casa sobe do mesmo jeito).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from magi.casa.driver import Capacidades, ContextoDriver, Key, Motivo, ResTv, TvConfig, TvDriver
from magi.elo.mensagens import EstadoTv


@dataclass(frozen=True)
class Registro:
    modulo: str
    dono: str


DRIVERS: dict[str, Registro] = {
    "samsung": Registro("magi.casa.drivers.samsung", "C1.2"),
    "roku": Registro("magi.casa.drivers.roku", "C1.3"),
    "androidtv": Registro("magi.casa.drivers.androidtv", "C1.4"),
}


class DriverAusente:
    """Driver de um módulo que ainda não existe: tudo ``NAO_SUPORTADO``, nada de I/O."""

    def __init__(self, tv: TvConfig, nome: str, dono: str) -> None:
        self.nome = nome
        self.capacidades = Capacidades(caps=frozenset())
        self._tv = tv
        self._detalhe = f"driver {nome} ainda não implementado (dono: {dono})"

    def _nao(self) -> ResTv:
        return ResTv(False, Motivo.NAO_SUPORTADO, self._detalhe)

    async def conectar(self) -> ResTv:
        return self._nao()

    async def fechar(self) -> None:
        return None

    async def power(self, on: bool) -> ResTv:
        return self._nao()

    async def volume(self, step: int | None = None, set_to: int | None = None) -> ResTv:
        return self._nao()

    async def mute(self, on: bool | None) -> ResTv:
        return self._nao()

    async def channel(self, step: int) -> ResTv:
        return self._nao()

    async def input(self, nome: str) -> ResTv:
        return self._nao()

    async def app(self, app_id: str) -> ResTv:
        return self._nao()

    async def key(self, key: Key) -> ResTv:
        return self._nao()

    async def text(self, s: str) -> ResTv:
        return self._nao()

    async def state(self) -> EstadoTv:
        return EstadoTv(id=self._tv.id, nome=self._tv.nome, driver=self.nome, online=False)


def conhecido(nome: str) -> bool:
    return nome in DRIVERS


def criar_driver(tv: TvConfig, ctx: ContextoDriver | None = None) -> TvDriver:
    """Instancia o driver da TV. Driver fora do registro → ``KeyError`` (o ``config`` já ignora)."""
    reg = DRIVERS[tv.driver]
    try:
        modulo = importlib.import_module(reg.modulo)
    except ModuleNotFoundError as e:
        if e.name is None or not (reg.modulo == e.name or reg.modulo.startswith(e.name + ".")):
            raise  # dependência faltando dentro do módulo: erro real, não "ainda não existe"
        return DriverAusente(tv, tv.driver, reg.dono)
    criar = getattr(modulo, "criar", None)
    if criar is None:
        return DriverAusente(tv, tv.driver, reg.dono)
    return criar(tv, ctx or ContextoDriver())
