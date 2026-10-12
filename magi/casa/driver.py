"""Contrato puro dos drivers de TV (spec §10.5, assinaturas finais; dono: C1.1).

Sem I/O e sem dependência de biblioteca de TV: importado pelos drivers, pelo ``Executor`` e pelos
testes. Regras do contrato:

- o driver **não** emula: método sem a ``Cap`` → ``ResTv(False, Motivo.NAO_SUPORTADO)``; a emulação
  mora em ``magi/casa/emula.py`` (``Executor``), acima do driver;
- o driver nunca levanta para o chamador: exceção de rede → ``OFFLINE``/``TEMPO_ESGOTADO``;
  inesperada → ``ERRO_DRIVER`` + log ``exception`` sem segredo;
- ``ok=True`` só depois da resposta do protocolo (em ``power``, com o estado confirmado).

Fábrica: cada ``magi/casa/drivers/<nome>.py`` expõe ``criar(tv: TvConfig, ctx: ContextoDriver) ->
TvDriver``; o registro ``magi.casa.drivers.DRIVERS`` importa o módulo só na hora de criar.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from magi.elo.mensagens import EstadoTv

if TYPE_CHECKING:  # pragma: no cover
    from magi.casa.apps import AppCatalogo

__all__ = [
    "ENTRADAS_CANONICAS",
    "Cap",
    "Capacidades",
    "ContextoDriver",
    "EstadoTv",
    "Key",
    "Motivo",
    "ResTv",
    "TvConfig",
    "TvDriver",
    "cap_necessaria",
]


class Cap(StrEnum):
    POWER_ON = "power_on"
    POWER_OFF = "power_off"
    VOL_STEP = "vol_step"
    VOL_SET = "vol_set"
    MUTE = "mute"
    CHANNEL = "channel"
    INPUT = "input"
    APP = "app"
    KEY = "key"
    TEXT = "text"
    STATE = "state"


class Key(StrEnum):
    """Teclas canônicas; cada driver mapeia para a sua (§11.4)."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    OK = "ok"
    BACK = "back"
    HOME = "home"
    MENU = "menu"
    PLAY_PAUSE = "play_pause"
    REWIND = "rewind"
    FORWARD = "forward"
    VOL_UP = "vol_up"
    VOL_DOWN = "vol_down"
    MUTE = "mute"
    CH_UP = "ch_up"
    CH_DOWN = "ch_down"
    POWER = "power"


class Motivo(StrEnum):
    NAO_SUPORTADO = "nao_suportado"
    OFFLINE = "offline"
    TEMPO_ESGOTADO = "tempo_esgotado"
    REDE_DESLIGADA = "rede_desligada"
    STANDBY_PROFUNDO = "standby_profundo"
    SEM_MAC = "sem_mac"
    NAO_PAREADO = "nao_pareado"
    ACESSO_NEGADO = "acesso_negado"
    APP_DESCONHECIDO = "app_desconhecido"
    ENTRADA_DESCONHECIDA = "entrada_desconhecida"
    PRECISA_CONFIRMAR = "precisa_confirmar"
    OCUPADA = "ocupada"
    TV_DESCONHECIDA = "tv_desconhecida"
    TV_AMBIGUA = "tv_ambigua"
    NAO_AUTORIZADO = "nao_autorizado"
    ERRO_DRIVER = "erro_driver"


ENTRADAS_CANONICAS: tuple[str, ...] = ("hdmi1", "hdmi2", "hdmi3", "hdmi4", "tv", "av")


@dataclass(frozen=True)
class Capacidades:
    caps: frozenset[Cap]
    entradas: tuple[str, ...] = ()  # canônicas: "hdmi1".."hdmi4", "tv", "av"
    apps: tuple[str, ...] = ()  # ids do apps.yaml que esta TV abre
    vol_max: int = 100  # escala da TV (Android TV informa; demais 100)
    emula: frozenset[Cap] = frozenset()  # caps entregues por emulação no Executor (§10.7)

    def pode(self, cap: Cap) -> bool:
        return cap in self.caps or cap in self.emula

    def anunciadas(self) -> tuple[str, ...]:
        """Valores para ``TvInfo.caps`` (já com as emuladas), na ordem da ``Cap``."""
        return tuple(c.value for c in Cap if self.pode(c))


@dataclass(frozen=True)
class ResTv:
    ok: bool
    motivo: Motivo | None = None
    detalhe: str = ""  # p/ log e "causa provável"; sem segredo
    emulado: bool = False
    estado: EstadoTv | None = None


def cap_necessaria(
    metodo: str, *, on: bool | None = None, step: int | None = None, set_to: int | None = None
) -> Cap | None:
    """``Cap`` exigida por uma chamada do ``TvDriver`` (``None`` = conectar/fechar, sem cap)."""
    if metodo == "power":
        return Cap.POWER_ON if on else Cap.POWER_OFF
    if metodo == "volume":
        return Cap.VOL_SET if set_to is not None else Cap.VOL_STEP
    por_metodo = {
        "mute": Cap.MUTE,
        "channel": Cap.CHANNEL,
        "input": Cap.INPUT,
        "app": Cap.APP,
        "key": Cap.KEY,
        "text": Cap.TEXT,
        "state": Cap.STATE,
    }
    return por_metodo.get(metodo)


@dataclass(frozen=True)
class TvConfig:
    """Uma ``[[tv]]`` do ``casa.toml`` (§12.4), já validada por ``magi.casa.config``."""

    id: str
    nome: str
    driver: str  # "samsung" | "roku" | "androidtv"
    apelidos: tuple[str, ...] = ()
    chave: str = ""  # identidade estável da descoberta (§12.1); não é segredo
    ip: str = ""
    mac: str = ""
    ano: int | None = None
    zerar_passos: int = 50  # §10.7
    entradas: Mapping[str, str] = field(default_factory=dict)  # apelido → canônica
    adb: bool = False


@dataclass(frozen=True)
class ContextoDriver:
    """O que a fábrica ``criar(tv, ctx)`` de cada driver recebe além da própria TV."""

    broadcast: str = "192.168.0.255"  # WOL
    apps: AppCatalogo | None = None
    dir_pareamento: Path | None = None  # ``~/.local/share/magi/casa/`` (0700)
    relogio: Callable[[], float] | None = None  # monotônico; None = time.monotonic


@runtime_checkable
class TvDriver(Protocol):
    nome: str  # "samsung" | "roku" | "androidtv" | "adb" | "falso"
    capacidades: Capacidades

    async def conectar(self) -> ResTv: ...
    async def fechar(self) -> None: ...
    async def power(self, on: bool) -> ResTv: ...
    async def volume(self, step: int | None = None, set_to: int | None = None) -> ResTv: ...
    async def mute(self, on: bool | None) -> ResTv: ...  # None = alterna
    async def channel(self, step: int) -> ResTv: ...
    async def input(self, nome: str) -> ResTv: ...  # canônica
    async def app(self, app_id: str) -> ResTv: ...  # id do apps.yaml
    async def key(self, key: Key) -> ResTv: ...
    async def text(self, s: str) -> ResTv: ...
    async def state(self) -> EstadoTv: ...
