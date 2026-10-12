"""Entrada ``magi-casa`` (spec §10.1; dono: C1.1, o corpo de ``servir`` é da C1.1c).

======================  ===========================  ======
subcomando              função                       dono
======================  ===========================  ======
``servir`` (padrão)     ``servir(args)`` (aqui)      C1.1c
``descobrir``           ``magi.casa.cli:descobrir``  C1.5
``nomear``              ``magi.casa.cli:nomear``     C1.5
``parear``              ``magi.casa.cli:parear``     C1.5
``esquecer``            ``magi.casa.cli:esquecer``   C1.5
``estado``              ``magi.casa.cli:estado``     C1.5
``testar <tv> <acao>``  ``magi.casa.cli:testar``     C1.5
======================  ===========================  ======

Cada função recebe a lista crua de argumentos depois do subcomando e devolve ``int | None``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence


def servir(args: list[str]) -> int | None:
    """Sobe a casa: config + drivers + ``Executor`` + API local (dono: C1.1c)."""
    print("magi-casa servir: ainda não implementado (dono: C1.1c)", file=sys.stderr)
    return 2


SUBCOMANDOS: tuple[tuple[str, str], ...] = (
    ("servir", "sobe a casa: API local e TVs (padrão)"),
    ("descobrir", "procura TVs na rede (SSDP + mDNS)"),
    ("nomear", "grava uma TV achada no casa.toml"),
    ("parear", "pareia uma TV (código/aceite na tela)"),
    ("esquecer", "apaga o pareamento de uma TV"),
    ("estado", "mostra o estado de cada TV"),
    ("testar", "testar <tv> <acao>: roda uma ação e mostra o resultado"),
)


def _funcao(nome: str) -> Callable[[list[str]], int | None]:
    if nome == "servir":
        return servir
    from magi.casa import cli

    return getattr(cli, nome)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="magi-casa", description="Casa da Condessa: controle das TVs (sem nuvem obrigatória)."
    )
    subs = parser.add_subparsers(dest="sub", metavar="<sub>")
    for nome, ajuda in SUBCOMANDOS:
        p = subs.add_parser(nome, help=ajuda, add_help=False)
        p.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    nomes = {n for n, _ in SUBCOMANDOS}
    if not argv:
        argv = ["servir"]
    if argv[0] in nomes:
        codigo = _funcao(argv[0])(argv[1:])
        return 0 if codigo is None else int(codigo)
    montar_parser().parse_args(argv)  # --help sai com 0; resto sai com 2
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
