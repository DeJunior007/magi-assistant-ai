"""Subcomandos de manutenção do ``magi-casa`` (spec §10.1, §12.1–§12.3).

**Stubs** da C1.1; dono dos corpos: C1.5 (descoberta, pareamento e CLI). Cada função recebe a
lista crua de argumentos depois do subcomando e devolve o código de saída (``int`` ou ``None`` = 0).
"""

from __future__ import annotations

import sys

DONO = "C1.5"


def _ainda_nao(sub: str) -> int:
    print(f"magi-casa {sub}: ainda não implementado (dono: {DONO})", file=sys.stderr)
    return 2


def descobrir(args: list[str]) -> int | None:
    """SSDP + mDNS, confirma por HTTP e lista as TVs achadas com a ``chave`` estável (dono: C1.5)."""
    return _ainda_nao("descobrir")


def nomear(args: list[str]) -> int | None:
    """``nomear <chave> <id> [--padrao] [--driver]``: grava a TV no ``casa.toml`` (dono: C1.5)."""
    return _ainda_nao("nomear")


def parear(args: list[str]) -> int | None:
    """``parear <tv>``: Samsung 60 s, Android TV 120 s com código, Roku ``device-info`` (dono: C1.5)."""
    return _ainda_nao("parear")


def esquecer(args: list[str]) -> int | None:
    """``esquecer <tv>``: apaga o pareamento guardado da TV (dono: C1.5)."""
    return _ainda_nao("esquecer")


def estado(args: list[str]) -> int | None:
    """Mostra o ``EstadoTv`` de cada TV configurada (dono: C1.5)."""
    return _ainda_nao("estado")


def testar(args: list[str]) -> int | None:
    """``testar <tv> <acao>``: roda uma ação pelo ``Executor`` e mostra ``ok``/``motivo``/``ms``
    (dono: C1.5)."""
    return _ainda_nao("testar")
