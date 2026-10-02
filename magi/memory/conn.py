"""Conexão assíncrona compartilhada entre os repositórios do núcleo.

Os repositórios abrem ``async with conn.transaction()`` na mesma ``AsyncConnection``. Duas tarefas
fazendo isso ao mesmo tempo (ex.: importação do gosto e checagem de custo ao subir) aninham as
transações fora de ordem e o psycopg levanta ``OutOfOrderTransactionNesting``. ``SerialConn`` põe
as transações em fila com um ``asyncio.Lock``; o resto é repassado à conexão real.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class SerialConn:
    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        async with self._lock, self._conn.transaction(*args, **kwargs) as tx:
            yield tx

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)
