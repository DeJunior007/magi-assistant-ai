"""Fixtures da API (dono: Y2.1): cliente ASGI em memória, banco ``pg`` (base nova por teste no
``ayanami-pg-teste``) e banco falso (fora do ar)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import psycopg
import pytest

from ayanami.api.app import criar_app
from ayanami.api.auth import criar_dispositivo
from ayanami.config import de_dict
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso

URL_BASE = "https://ayanami.exemplo.ts.net"


class DbPorConexao:
    """``Db`` que abre uma conexão por uso (as rotas síncronas rodam em threads)."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


class DbFora:
    """``Db`` falso com o banco fora do ar."""

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        raise psycopg.OperationalError("banco falso fora do ar")
        yield  # pragma: no cover


@pytest.fixture
def cfg():
    return de_dict({"geral": {"url_base": URL_BASE}})


@pytest.fixture
def relogio() -> RelogioFalso:
    return RelogioFalso()


@pytest.fixture
def base(pg_nova_base: Callable[[str], str]) -> str:
    dsn = pg_nova_base("ayanami_api")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return dsn


@pytest.fixture
def db(base: str) -> DbPorConexao:
    return DbPorConexao(base)


class Codigos:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return f"{100000 + self.n:06d}"


@pytest.fixture
def fazer_app(cfg, relogio) -> Callable[..., Any]:
    def fazer(db: Any, **kw: Any):
        kw.setdefault("gerar_codigo", Codigos())
        return criar_app(cfg, db, relogio, **kw)

    return fazer


@pytest.fixture
def app(fazer_app, db):
    return fazer_app(db)


def _cliente(app: Any, token: str | None = None, ip: str = "100.64.0.1") -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transporte = httpx.ASGITransport(app=app, client=(ip, 40000))
    return httpx.AsyncClient(transport=transporte, base_url="http://ayanami.test", headers=headers)


@pytest.fixture
def cliente() -> Callable[..., httpx.AsyncClient]:
    """``cliente(app, token=None, ip=...)`` → ``httpx.AsyncClient`` sobre o ASGI (sem rede)."""
    return _cliente


@pytest.fixture
def novo_token(db: DbPorConexao) -> Callable[..., str]:
    def criar(nome: str, tipo: str, escopos: list[str] | None = None) -> str:
        with db.connection() as conn:
            token, _ = criar_dispositivo(conn, nome, tipo, escopos)
        return token

    return criar


@pytest.fixture
def db_fora() -> DbFora:
    return DbFora()
