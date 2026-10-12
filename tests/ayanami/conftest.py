"""Fixtures dos testes da Ayanami (dono: Y0.3).

Testes marcados ``pg`` usam **só** o Postgres descartável ``ayanami-pg-teste``
(``deploy/ayanami/pg-teste.sh subir`` → ``AYANAMI_TEST_DSN``); sem a variável eles pulam. O DSN
na porta 54329 ou na base ``magi`` (o ``magi-pg`` do PC) é recusado: o teste falha, nunca conecta.

- ``pg_dsn``: o DSN administrativo validado (sessão).
- ``pg_nova_base``: fábrica ``() -> dsn`` de bases vazias novas dentro do contêiner de teste,
  removidas no fim da sessão.
- ``pg_base``: DSN de uma base com as migrações da Ayanami (001–002) aplicadas (sessão).
- ``pg_base_pc``: DSN de outra base com as migrações do PC (``magi/memory/migrations``,
  inclusive a 005) aplicadas (sessão; para a Y3.3).
- ``pg``: conexão aberta em ``pg_base`` (por teste).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ayanami.db import DbError, recusar_magi
from ayanami.migrar import migrar
from magi.memory import migrate as pc_migrate

ENV_DSN = "AYANAMI_TEST_DSN"


def validar_dsn_teste(dsn: str) -> str:
    """Devolve o DSN se ele pode ser usado pelos testes; senão ``pytest.fail`` (nunca conecta)."""
    try:
        recusar_magi(dsn)
    except DbError as e:
        pytest.fail(f"{ENV_DSN} recusado: {e}; use deploy/ayanami/pg-teste.sh (porta 54340)")
    return dsn


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(ENV_DSN):
        return
    pula = pytest.mark.skip(reason=f"sem {ENV_DSN} (suba com deploy/ayanami/pg-teste.sh subir)")
    for item in items:
        if "pg" in item.keywords:
            item.add_marker(pula)


@pytest.fixture(scope="session")
def pg_dsn() -> str:
    dsn = os.environ.get(ENV_DSN)
    if not dsn:
        pytest.skip(f"sem {ENV_DSN}")
    return validar_dsn_teste(dsn)


def _com_base(dsn: str, base: str) -> str:
    partes = conninfo_to_dict(dsn)
    partes["dbname"] = base
    return make_conninfo(**partes)


@pytest.fixture(scope="session")
def pg_nova_base(pg_dsn: str) -> Iterator[Callable[[str], str]]:
    try:
        admin = psycopg.connect(pg_dsn, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.skip(f"ayanami-pg-teste indisponível: {e}")
    criadas: list[str] = []

    def criar(prefixo: str = "ayanami_t") -> str:
        nome = f"{prefixo}_{uuid.uuid4().hex[:10]}"
        assert nome != "magi"
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
        criadas.append(nome)
        return validar_dsn_teste(_com_base(pg_dsn, nome))

    try:
        yield criar
    finally:
        validar_dsn_teste(pg_dsn)  # de novo, antes de remover qualquer coisa
        for nome in criadas:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome)))
        admin.close()


@pytest.fixture(scope="session")
def pg_base(pg_nova_base: Callable[[str], str]) -> str:
    dsn = pg_nova_base("ayanami_t")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return dsn


@pytest.fixture(scope="session")
def pg_base_pc(pg_nova_base: Callable[[str], str]) -> str:
    dsn = pg_nova_base("magi_pc_t")
    with psycopg.connect(dsn) as conn:
        pc_migrate.migrate(conn)
    return dsn


@pytest.fixture
def pg(pg_base: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(pg_base) as conn:
        yield conn
