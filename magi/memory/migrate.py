"""Executor de migrações do banco da Magui (design §7).

Uso: ``uv run python -m magi.memory.migrate [--dsn ...] [--schema ...]``

- DSN: argumento ``--dsn``, senão ``MAGI_DB_DSN``, senão :data:`DEFAULT_DSN`.
- Migrações: arquivos ``magi/memory/migrations/NNN_nome.sql``, aplicados em ordem, cada um numa
  transação; os aplicados ficam em ``schema_migrations`` (rodar de novo não faz nada).
- Dimensão dos vetores: os arquivos SQL têm os marcadores ``{{MEMORIES_DIM}}`` e ``{{NEWS_DIM}}``.
  Valor usado, em ordem de prioridade: parâmetro (``memories_dim``/``news_dim`` ou
  ``--memories-dim``/``--news-dim``), env ``MAGI_EMBED_DIM_MEMORIES``/``MAGI_EMBED_DIM_NEWS``,
  padrão 1536/768. O núcleo deve passar a dimensão do modelo de embeddings da config. Os valores
  usados ficam gravados em ``schema_migrations.params``.
- ``schema``: cria e usa um schema próprio (search_path = schema, public). Serve aos testes,
  para não sujar o schema ``public`` do banco de desenvolvimento.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

DEFAULT_DSN = "postgresql://magi:magi@127.0.0.1:54329/magi"
DEFAULT_MEMORIES_DIM = 1536
DEFAULT_NEWS_DIM = 768
MAX_HNSW_DIM = 2000  # limite do índice HNSW para o tipo vector

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_FILE_RE = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")
_LOCK_KEY = 0x6D616769  # "magi"; serializa execuções concorrentes do executor


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path

    def render(self, dims: dict[str, int]) -> str:
        text = self.path.read_text(encoding="utf-8")
        for key, value in dims.items():
            text = text.replace("{{" + key + "}}", str(value))
        leftover = re.search(r"\{\{[A-Z_]+\}\}", text)
        if leftover:
            raise ValueError(f"marcador sem valor em {self.path.name}: {leftover.group(0)}")
        return text


def dsn_from_env() -> str:
    return os.environ.get("MAGI_DB_DSN") or DEFAULT_DSN


def _dim(value: int | None, env: str, default: int) -> int:
    if value is None:
        raw = os.environ.get(env)
        value = int(raw) if raw else default
    value = int(value)
    if not 1 <= value <= MAX_HNSW_DIM:
        raise ValueError(f"dimensão inválida ({env}): {value}; precisa estar entre 1 e {MAX_HNSW_DIM}")
    return value


def embedding_dims(memories_dim: int | None = None, news_dim: int | None = None) -> dict[str, int]:
    return {
        "MEMORIES_DIM": _dim(memories_dim, "MAGI_EMBED_DIM_MEMORIES", DEFAULT_MEMORIES_DIM),
        "NEWS_DIM": _dim(news_dim, "MAGI_EMBED_DIM_NEWS", DEFAULT_NEWS_DIM),
    }


def available_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found = []
    for path in sorted(directory.glob("*.sql")):
        m = _FILE_RE.match(path.name)
        if not m:
            raise ValueError(f"nome de migração fora do padrão NNN_nome.sql: {path.name}")
        found.append(Migration(m.group(1), m.group(2), path))
    versions = [m.version for m in found]
    if len(set(versions)) != len(versions):
        raise ValueError(f"versões de migração repetidas em {directory}")
    return found


def applied_versions(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r[0] for r in rows}


def _use_schema(conn: psycopg.Connection, schema: str) -> None:
    with conn.transaction():
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        conn.execute("SELECT set_config('search_path', %s, false)", [f'"{schema}", public'])


def migrate(
    conn: psycopg.Connection,
    *,
    schema: str | None = None,
    memories_dim: int | None = None,
    news_dim: int | None = None,
    directory: Path = MIGRATIONS_DIR,
) -> list[str]:
    """Aplica as migrações pendentes; devolve as versões aplicadas nesta chamada."""
    dims = embedding_dims(memories_dim, news_dim)
    migrations = available_migrations(directory)
    if schema:
        _use_schema(conn, schema)
    with conn.transaction():
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     text PRIMARY KEY,
                name        text NOT NULL,
                params      jsonb NOT NULL DEFAULT '{}'::jsonb,
                applied_at  timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    applied: list[str] = []
    for mig in migrations:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_KEY])
            if mig.version in applied_versions(conn):
                continue
            conn.execute(mig.render(dims).encode())
            conn.execute(
                "INSERT INTO schema_migrations (version, name, params) VALUES (%s, %s, %s)",
                [mig.version, mig.name, json.dumps(dims)],
            )
        applied.append(mig.version)
    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="magi.memory.migrate", description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", default=None, help="padrão: $MAGI_DB_DSN ou " + DEFAULT_DSN)
    parser.add_argument("--schema", default=None, help="schema alvo (padrão: o do search_path)")
    parser.add_argument("--memories-dim", type=int, default=None)
    parser.add_argument("--news-dim", type=int, default=None)
    args = parser.parse_args(argv)

    dsn = args.dsn or dsn_from_env()
    try:
        with psycopg.connect(dsn) as conn:
            done = migrate(
                conn, schema=args.schema, memories_dim=args.memories_dim, news_dim=args.news_dim
            )
    except (psycopg.Error, ValueError) as exc:
        print(f"migração falhou: {exc}", file=sys.stderr)
        return 1
    print("aplicadas: " + ", ".join(done) if done else "banco já está atualizado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
