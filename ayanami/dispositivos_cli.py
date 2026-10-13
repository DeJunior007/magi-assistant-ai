"""``ayanami dispositivo criar|listar|revogar`` (dono: Y2.1; design §4.1, spec §2.1).

Roda no contêiner (``docker compose exec ayanami-api ayanami dispositivo …``). ``criar`` imprime o
token **uma vez** (só ali; no banco vai o sha256). ``revogar`` grava ``revogado``; a API deixa de
aceitar o token em ≤ 5 s (TTL do cache).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

import psycopg

from ayanami import config as cfgmod
from ayanami.api import auditoria
from ayanami.api.auth import TIPOS, NomeEmUso, criar_dispositivo, iso_z, listar_dispositivos, marcar_revogado
from ayanami.db import DbError, dsn_padrao, recusar_magi
from ayanami.relogio import RelogioReal


def _escopos_mcp(caminho: str | None) -> tuple[str, ...] | None:
    if caminho is None and not cfgmod.CAMINHO_PADRAO.exists():
        return None
    return cfgmod.ler(caminho or cfgmod.CAMINHO_PADRAO).mcp.escopos


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ayanami dispositivo", description="cria, lista e revoga tokens")
    p.add_argument("--dsn", default=None, help="padrão: $AYANAMI_DB_DSN ou ayanami-pg com $POSTGRES_PASSWORD")
    p.add_argument("--config", default=None, help="ayanami.toml (escopos do mcp)")
    sub = p.add_subparsers(dest="acao", required=True)
    c = sub.add_parser("criar", help="cria um dispositivo e imprime o token uma vez")
    c.add_argument("nome")
    c.add_argument("--tipo", choices=TIPOS, required=True)
    c.add_argument("--escopos", default=None, help="lista separada por vírgula (padrão: os do tipo)")
    sub.add_parser("listar", help="lista os dispositivos (prefixo, nunca o token)")
    r = sub.add_parser("revogar", help="revoga pelo nome")
    r.add_argument("nome")
    return p


def cli(args: Sequence[str], *, conectar=psycopg.connect, relogio=None, saida=None) -> int:  # noqa: ANN001
    a = montar_parser().parse_args(list(args))
    out = saida or sys.stdout
    relogio = relogio or RelogioReal()
    try:
        dsn = a.dsn or dsn_padrao()
        recusar_magi(dsn)
        with conectar(dsn) as conn:
            if a.acao == "criar":
                escopos = [e for e in a.escopos.split(",") if e] if a.escopos else None
                if escopos is None and a.tipo == "mcp":
                    escopos = _escopos_mcp(a.config)
                token, d = criar_dispositivo(conn, a.nome, a.tipo, escopos)
                auditoria.registrar(conn, tipo="dispositivo", dispositivo=d.id, alvo=d.nome,
                                    resumo=f"criado pelo CLI ({d.tipo})", ok=True)
                print(f"{d.nome} ({d.tipo}; {','.join(sorted(d.escopos))})", file=out)
                print(f"token (guarde agora; não aparece de novo): {token}", file=out)
            elif a.acao == "listar":
                for d in listar_dispositivos(conn):
                    estado = f"revogado {iso_z(d.revogado)}" if d.revogado else "ativo"
                    print(f"{d.id}\t{d.nome}\t{d.tipo}\t{d.prefixo}…\t{','.join(sorted(d.escopos))}\t"
                          f"{iso_z(d.ultimo_uso) or '-'}\t{estado}", file=out)
            else:
                d = marcar_revogado(conn, a.nome, relogio.agora())
                if d is None:
                    print(f"ayanami dispositivo: {a.nome!r} não existe", file=sys.stderr)
                    return 1
                auditoria.registrar(conn, tipo="dispositivo", dispositivo=d.id, alvo=d.nome,
                                    resumo="revogado pelo CLI", ok=True)
                print(f"{d.nome} revogado (a API recusa em ≤ 5 s)", file=out)
    except NomeEmUso as e:
        print(f"ayanami dispositivo: nome em uso: {e}", file=sys.stderr)
        return 1
    except (cfgmod.ConfigError, DbError, ValueError, psycopg.Error) as e:
        print(f"ayanami dispositivo: falhou: {e}", file=sys.stderr)
        return 1
    return 0
