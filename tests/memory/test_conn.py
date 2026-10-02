import asyncio
from contextlib import asynccontextmanager

from magi.memory.conn import SerialConn


class _Conn:
    """Imita o psycopg: transações sobrepostas na mesma conexão são erro."""

    def __init__(self):
        self.open = 0
        self.max_open = 0

    @asynccontextmanager
    async def transaction(self):
        self.open += 1
        self.max_open = max(self.max_open, self.open)
        try:
            yield self
        finally:
            self.open -= 1

    async def execute(self, q):
        await asyncio.sleep(0.01)
        return q


async def test_transactions_are_serialized():
    raw = _Conn()
    conn = SerialConn(raw)

    async def work(i):
        async with conn.transaction():
            return await conn.execute(f"q{i}")  # repassado à conexão real

    assert await asyncio.gather(*(work(i) for i in range(5))) == [f"q{i}" for i in range(5)]
    assert raw.max_open == 1
