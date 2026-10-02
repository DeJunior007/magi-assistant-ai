"""Conexão assíncrona compartilhada entre os repositórios do núcleo.

Os repositórios abrem ``async with conn.transaction()`` na mesma ``AsyncConnection``. Duas tarefas
fazendo isso ao mesmo tempo (ex.: importação do gosto e checagem de custo ao subir) aninham as
transações fora de ordem e o psycopg levanta ``OutOfOrderTransactionNesting``. ``SerialConn`` põe
as transações em fila com um ``asyncio.Lock``. Um ``execute`` solto (autocommit, ex.: repositório
de notícias) também entra na fila, para não cair dentro da transação de outra tarefa; dentro da
própria transação ele passa direto. O resto é repassado à conexão real.
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
        self._owner: asyncio.Task[Any] | None = None

    @asynccontextmanager
    async def transaction(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        if self._owner is asyncio.current_task():  # aninhada na mesma tarefa: savepoint normal
            async with self._conn.transaction(*args, **kwargs) as tx:
                yield tx
            return
        async with self._lock:
            self._owner = asyncio.current_task()
            try:
                async with self._conn.transaction(*args, **kwargs) as tx:
                    yield tx
            finally:
                self._owner = None

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        if self._owner is asyncio.current_task():
            return await self._conn.execute(*args, **kwargs)
        async with self._lock:
            return await self._conn.execute(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)
