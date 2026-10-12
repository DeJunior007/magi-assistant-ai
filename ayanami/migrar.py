"""``ayanami migrar`` — aplica ``ayanami/migrations/NNN_*.sql`` (dono: Y0.3; spec §3).

- Cada migração roda numa transação, sob ``pg_advisory_xact_lock``, e fica registrada em
  ``schema_migracoes(versao, aplicada)``; rodar de novo não faz nada (idempotente).
- O marcador ``{{NEWS_DIM}}`` é trocado pelo mesmo renderizador do PC
  (:meth:`magi.memory.migrate.Migration.render`); o valor é ``--dim``, senão ``[noticias] dim`` do
  ``ayanami.toml`` (``--config``, padrão ``/etc/ayanami/ayanami.toml`` se existir), senão 768.
- DSN: ``--dsn``, senão :func:`ayanami.db.dsn_padrao`. DSN do ``magi-pg`` é recusado.
- O esquema do ``procrastinate`` não é daqui (``procrastinate schema --apply``, serviço ``migrar``).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg

from ayanami import config as cfgmod
from ayanami.db import DbError, dsn_padrao, recusar_magi
from magi.memory.migrate import DEFAULT_NEWS_DIM, Migration, available_migrations

DIRETORIO = Path(__file__).with_name("migrations")
_TRAVA = 0x6179616E  # "ayan"; serializa execuções concorrentes


def migracoes(diretorio: Path = DIRETORIO) -> list[Migration]:
    return available_migrations(diretorio)


def aplicadas(conn: psycopg.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT versao FROM schema_migracoes ORDER BY versao").fetchall()]


def migrar(
    conn: psycopg.Connection, *, dim: int = DEFAULT_NEWS_DIM, diretorio: Path = DIRETORIO
) -> list[str]:
    """Aplica as migrações pendentes; devolve as versões aplicadas nesta chamada."""
    if not 1 <= dim <= 2000:
        raise ValueError(f"dimensão inválida: {dim}; precisa estar entre 1 e 2000")
    dims = {"NEWS_DIM": dim}
    todas = migracoes(diretorio)
    with conn.transaction():
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migracoes ("
            " versao text PRIMARY KEY, aplicada timestamptz NOT NULL DEFAULT now())"
        )
    feitas: list[str] = []
    for mig in todas:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", [_TRAVA])
            if mig.version in aplicadas(conn):
                continue
            conn.execute(mig.render(dims).encode())
            conn.execute("INSERT INTO schema_migracoes (versao) VALUES (%s)", [mig.version])
        feitas.append(mig.version)
    return feitas


def _dim_da_config(caminho: str | None) -> int:
    if caminho is None:
        if not cfgmod.CAMINHO_PADRAO.exists():
            return DEFAULT_NEWS_DIM
        caminho = str(cfgmod.CAMINHO_PADRAO)
    return cfgmod.ler(caminho).noticias.dim


def cli(args: Sequence[str]) -> int:
    p = argparse.ArgumentParser(prog="ayanami migrar", description="aplica as migrações do banco da Ayanami")
    p.add_argument("--dsn", default=None, help="padrão: $AYANAMI_DB_DSN ou ayanami-pg com $POSTGRES_PASSWORD")
    p.add_argument(
        "--config", default=None, help=f"ayanami.toml (padrão: {cfgmod.CAMINHO_PADRAO} se existir)"
    )
    p.add_argument("--dim", type=int, default=None, help="dimensão das notícias (padrão: [noticias] dim)")
    a = p.parse_args(list(args))
    try:
        dim = a.dim if a.dim is not None else _dim_da_config(a.config)
        dsn = a.dsn or dsn_padrao()
        recusar_magi(dsn)
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            feitas = migrar(conn, dim=dim)
    except (cfgmod.ConfigError, DbError, ValueError, psycopg.Error) as e:
        print(f"ayanami migrar: falhou: {e}", file=sys.stderr)
        return 1
    print("aplicadas: " + ", ".join(feitas) if feitas else "banco já está atualizado")
    return 0
