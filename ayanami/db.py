"""Acesso ao banco da Ayanami (dono: Y0.3; spec §3).

- DSN: env ``AYANAMI_DB_DSN``; senão montado de ``POSTGRES_PASSWORD`` (do ``.env``) com as variáveis
  libpq ``PGHOST``/``PGPORT``/``PGUSER``/``PGDATABASE`` do Compose (padrão ``ayanami-pg:5432``,
  usuário e base ``ayanami``). :func:`dsn_padrao` nunca registra o DSN em log.
- :class:`Db`: o protocolo mínimo que o resto da Ayanami usa — ``connection()`` como gerenciador de
  contexto que devolve uma ``psycopg.Connection``. ``psycopg_pool.ConnectionPool`` já cumpre;
  :class:`ConexaoUnica` cumpre com uma conexão só (testes, CLI).
- :func:`transacao`: ``with transacao(db) as conn:`` — conexão do pool dentro de uma transação
  (commit no fim, rollback em exceção).
- :func:`recusar_magi`: a Ayanami nunca escreve no ``magi-pg`` do PC (porta ``54329`` ou base
  ``magi``); ``ayanami migrar`` e o fixture ``pg`` dos testes chamam antes de conectar.

O ``psycopg_pool`` (extra ``ayanami``) é importado só dentro de :func:`abrir_pool`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import quote

import psycopg
from psycopg.conninfo import conninfo_to_dict

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

HOST_PADRAO = "ayanami-pg"
PORTA_MAGI_PG = 54329
BASE_MAGI = "magi"


class DbError(RuntimeError):
    """DSN ausente ou proibido (nunca carrega a senha na mensagem)."""


@runtime_checkable
class Db(Protocol):
    def connection(self) -> AbstractContextManager[psycopg.Connection]: ...


def dsn_padrao(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    dsn = env.get("AYANAMI_DB_DSN")
    if dsn:
        return dsn
    senha = env.get("POSTGRES_PASSWORD")
    if not senha:
        raise DbError("sem AYANAMI_DB_DSN nem POSTGRES_PASSWORD no ambiente")
    host = env.get("PGHOST") or HOST_PADRAO
    porta = env.get("PGPORT") or "5432"
    usuario = quote(env.get("PGUSER") or "ayanami", safe="")
    base = quote(env.get("PGDATABASE") or "ayanami", safe="")
    return f"postgresql://{usuario}:{quote(senha, safe='')}@{host}:{porta}/{base}"


def recusar_magi(dsn: str) -> None:
    """Erro se o DSN aponta para o banco do PC (porta 54329 ou base ``magi``)."""
    try:
        partes = conninfo_to_dict(dsn)
    except psycopg.ProgrammingError as e:
        raise DbError("DSN inválido") from e
    porta = str(partes.get("port") or "")
    base = str(partes.get("dbname") or "")
    if str(PORTA_MAGI_PG) in porta.split(","):
        raise DbError(f"DSN na porta {PORTA_MAGI_PG} (magi-pg do PC): recusado")
    if base == BASE_MAGI:
        raise DbError(f"DSN na base {BASE_MAGI!r} (banco do PC): recusado")


def abrir_pool(dsn: str, *, minimo: int = 1, maximo: int = 8, nome: str = "ayanami") -> ConnectionPool:
    """Pool ``psycopg`` aberto (o chamador fecha com ``pool.close()`` ou ``with``)."""
    from psycopg_pool import ConnectionPool

    recusar_magi(dsn)
    return ConnectionPool(dsn, min_size=minimo, max_size=maximo, name=nome, open=True)


class ConexaoUnica:
    """:class:`Db` sobre uma conexão já aberta (não fecha a conexão ao sair)."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        yield self.conn


@contextmanager
def transacao(db: Db) -> Iterator[psycopg.Connection]:
    with db.connection() as conn, conn.transaction():
        yield conn
