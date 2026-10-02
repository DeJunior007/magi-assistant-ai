"""Correções salvas em Postgres (tarefa 1.6, §7 tabela ``corrections``, R3.3-R3.4).

Implementa ``magi.common.contracts.CorrectionsRepo`` sobre uma ``psycopg.AsyncConnection``
(autocommit ou não: cada operação roda na sua própria transação). Um ``heard`` tem no máximo
um par: ``add`` com o mesmo ``heard`` troca o ``correct`` (e zera ``uses`` se ele mudou).
"""

from __future__ import annotations

import psycopg
from psycopg.rows import class_row

from magi.common.contracts import Correction

_COLS = "heard, correct, uses, created_at, id"


class CorrectionsRepo:
    """``CorrectionsRepo`` em Postgres."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def add(self, heard: str, correct: str) -> Correction:
        heard, correct = heard.strip(), correct.strip()
        if not heard or not correct:
            raise ValueError("heard e correct não podem ser vazios")
        async with self._conn.transaction():
            cur = self._conn.cursor(row_factory=class_row(Correction))
            # Duplicatas antigas do mesmo heard (inseridas por fora) somem; fica a mais antiga.
            await cur.execute(
                "DELETE FROM corrections WHERE heard = %s"
                " AND id <> (SELECT min(id) FROM corrections WHERE heard = %s)",
                [heard, heard],
            )
            await cur.execute(
                "UPDATE corrections SET uses = CASE WHEN correct = %s THEN uses ELSE 0 END,"
                f" correct = %s WHERE heard = %s RETURNING {_COLS}",
                [correct, correct, heard],
            )
            row = await cur.fetchone()
            if row is None:
                await cur.execute(
                    f"INSERT INTO corrections (heard, correct) VALUES (%s, %s) RETURNING {_COLS}",
                    [heard, correct],
                )
                row = await cur.fetchone()
        assert row is not None
        return row

    async def all(self) -> list[Correction]:
        async with self._conn.transaction():
            cur = self._conn.cursor(row_factory=class_row(Correction))
            await cur.execute(f"SELECT {_COLS} FROM corrections ORDER BY id")
            return await cur.fetchall()

    async def bump(self, correction_id: int) -> None:
        async with self._conn.transaction():
            await self._conn.execute(
                "UPDATE corrections SET uses = uses + 1 WHERE id = %s", [correction_id]
            )

    async def delete(self, correction_id: int) -> None:
        async with self._conn.transaction():
            await self._conn.execute("DELETE FROM corrections WHERE id = %s", [correction_id])
