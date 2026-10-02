"""Custos por chamada em Postgres (tarefa 3.2, §4.6, §7 tabela ``costs``, R16.1, R16.5).

Implementa ``magi.common.contracts.CostsRepo`` sobre uma ``psycopg.AsyncConnection``. O mês de
``month_total`` é o mês civil em America/Sao_Paulo (a virada acontece à meia-noite do dia 1 no
horário de Brasília, não em UTC). ``input_units``/``output_units`` são ``bigint`` na tabela:
unidades fracionárias (segundos de áudio) são arredondadas; o USD já vem calculado em ``usage``.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import psycopg

from magi.common.contracts import Usage

TZ = ZoneInfo("America/Sao_Paulo")


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Início (inclusivo) e fim (exclusivo) do mês civil em America/Sao_Paulo."""
    start = datetime(year, month, 1, tzinfo=TZ)
    end = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=TZ)
    return start, end


class CostsRepo:
    """``CostsRepo`` em Postgres."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def add(self, usage: Usage, at: datetime) -> int:
        if at.tzinfo is None:
            raise ValueError("at precisa de fuso horário")
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "INSERT INTO costs (at, provider, task, model, input_units, output_units, usd)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                [
                    at,
                    usage.provider,
                    str(usage.task),
                    usage.model or None,
                    round(usage.input_units),
                    round(usage.output_units),
                    usage.usd,
                ],
            )
            row = await cur.fetchone()
        assert row is not None
        return int(row[0])

    async def month_total(self, year: int, month: int) -> float:
        start, end = month_bounds(year, month)
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "SELECT coalesce(sum(usd), 0) FROM costs WHERE at >= %s AND at < %s", [start, end]
            )
            row = await cur.fetchone()
        return float(row[0]) if row else 0.0
