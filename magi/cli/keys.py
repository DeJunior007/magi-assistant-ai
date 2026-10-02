"""``magi-keys``: guarda e confere chaves de API no keyring.

    magi-keys add <nome>      # pede o valor sem eco (ou lê de stdin se não for terminal)
    magi-keys remove <nome>
    magi-keys list            # nomes citados no config e se estão no keyring (nunca o valor)
"""

from __future__ import annotations

import argparse
import getpass
import sys

from magi.common import secrets
from magi.common.config import ConfigError, load_config


def _read_value(name: str) -> str:
    if sys.stdin.isatty():
        return getpass.getpass(f"Valor da chave '{name}': ")
    return sys.stdin.readline()


def cmd_add(args: argparse.Namespace) -> int:
    if secrets.has_secret(args.name) and not args.force:
        print(f"'{args.name}' já existe no keyring; use --force para trocar.", file=sys.stderr)
        return 1
    value = _read_value(args.name)
    try:
        secrets.set_secret(args.name, value)
    except secrets.SecretError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    print(f"'{args.name}' guardada no keyring (serviço {secrets.SERVICE}).")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    if secrets.delete_secret(args.name):
        print(f"'{args.name}' removida.")
        return 0
    print(f"'{args.name}' não estava no keyring.", file=sys.stderr)
    return 1


def cmd_list(args: argparse.Namespace) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    missing = 0
    for prov in cfg.providers.values():
        for name in prov.keys:
            ok = secrets.has_secret(name)
            missing += not ok
            print(f"{prov.name:10} {name:24} {'ok' if ok else 'FALTA'}")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="magi-keys", description="Chaves de API do Magui no keyring.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="guarda uma chave")
    p.add_argument("name")
    p.add_argument("--force", action="store_true", help="substitui se já existir")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", help="apaga uma chave")
    p.add_argument("name")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("list", help="confere as chaves citadas no config")
    p.add_argument("--config", default=None, help="caminho do config.toml")
    p.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except secrets.SecretError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
