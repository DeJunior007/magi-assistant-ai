"""Entrada ``ayanami <sub>`` (dono: Y0.2; depois da Y0.2 ninguém mais edita este arquivo).

Cada subcomando despacha, por import preguiçoso, para uma função do módulo dono, que recebe a lista
de argumentos **depois** do subcomando e devolve o código de saída (``int`` ou ``None`` = 0):

======================  ===========================================  ======
subcomando              função                                       dono
======================  ===========================================  ======
``migrar``              ``ayanami.migrar:cli(args)``                 Y0.3
``worker``              ``ayanami.worker:cli(args)``                 Y3.1
``batimento``           ``ayanami.worker:cli_batimento(args)``       Y3.1
``voz``                 ``ayanami.voz.servidor:cli(args)``           Y3.5
``dispositivo``         ``ayanami.dispositivos_cli:cli(args)``       Y2.1
``backup``              ``ayanami.workers.backup:cli(args)``         Y4.2
``push``                ``ayanami.push:cli(args)``                   P2.1
======================  ===========================================  ======

Módulo (ou função) ainda ausente → mensagem clara com "dono: <ID>" e código 2.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Sub:
    nome: str
    modulo: str
    funcao: str
    dono: str
    ajuda: str


SUBCOMANDOS: tuple[Sub, ...] = (
    Sub("migrar", "ayanami.migrar", "cli", "Y0.3", "aplica as migrações do banco da Ayanami"),
    Sub("worker", "ayanami.worker", "cli", "Y3.1", "roda o worker de uma fila (rapida|agendada|lenta)"),
    Sub("batimento", "ayanami.worker", "cli_batimento", "Y3.1", "healthcheck do worker de uma fila"),
    Sub("voz", "ayanami.voz.servidor", "cli", "Y3.5", "servidor de TTS Kokoro (ayanami-voz)"),
    Sub("dispositivo", "ayanami.dispositivos_cli", "cli", "Y2.1", "cria, lista e revoga tokens"),
    Sub("backup", "ayanami.workers.backup", "cli", "Y4.2", "backups restic (iniciar, rodar, testar)"),
    Sub("push", "ayanami.push", "cli", "P2.1", "Web Push (ex.: ayanami push chaves)"),
)


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ayanami", description="Ayanami: API central da Condessa.")
    subs = parser.add_subparsers(dest="sub", metavar="<sub>", required=True)
    for s in SUBCOMANDOS:
        p = subs.add_parser(s.nome, help=f"{s.ajuda} (dono: {s.dono})", add_help=False)
        p.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def despachar(sub: Sub, args: list[str]) -> int:
    try:
        modulo = importlib.import_module(sub.modulo)
    except ModuleNotFoundError as e:
        if e.name is None or not (sub.modulo == e.name or sub.modulo.startswith(e.name + ".")):
            raise  # dependência faltando dentro do módulo: erro real, não "ainda não existe"
        print(
            f"ayanami {sub.nome}: ainda não implementado ({sub.modulo} não existe; dono: {sub.dono})",
            file=sys.stderr,
        )
        return 2
    funcao = getattr(modulo, sub.funcao, None)
    if funcao is None:
        print(
            f"ayanami {sub.nome}: {sub.modulo}.{sub.funcao} não existe (dono: {sub.dono})",
            file=sys.stderr,
        )
        return 2
    codigo = funcao(args)
    return 0 if codigo is None else int(codigo)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # tudo depois do subcomando vai cru para o dono (o argparse.REMAINDER engasga com "--opcao" logo
    # depois do subcomando); o parser só cuida de --help e de subcomando inválido
    por_nome = {s.nome: s for s in SUBCOMANDOS}
    if argv and argv[0] in por_nome:
        return despachar(por_nome[argv[0]], argv[1:])
    montar_parser().parse_args(argv)  # --help sai com 0; resto sai com 2
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
