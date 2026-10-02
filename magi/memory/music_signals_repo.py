"""Sinais de música em Postgres (tarefa 2.4, §7 tabela ``music_signals``, R8.3-R8.5).

Implementa ``magi.common.contracts.MusicSignalsRepo`` sobre uma ``psycopg.AsyncConnection``. Os
sinais só são acrescentados (histórico); o peso de gosto os soma na view ``taste_effective``.
"""

from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from magi.common.contracts import MusicSignal, MusicSignalValue


class MusicSignalsRepo:
    """``MusicSignalsRepo`` em Postgres."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def add(self, signal: MusicSignal) -> None:
        async with self._conn.transaction():
            await self._conn.execute(
                "INSERT INTO music_signals (at, track_uri, artist, context, signal)"
                " VALUES (%s, %s, %s, %s, %s)",
                [signal.at, signal.track_uri, signal.artist, Jsonb(dict(signal.context)), int(signal.signal)],
            )

    async def banned_tracks(self) -> set[str]:
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "SELECT DISTINCT track_uri FROM music_signals WHERE signal = %s AND track_uri IS NOT NULL",
                [int(MusicSignalValue.NEVER)],
            )
            rows = await cur.fetchall()
        return {r[0] for r in rows}

    async def recent(self, limit: int = 100) -> list[MusicSignal]:
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "SELECT track_uri, artist, signal, at, context FROM music_signals"
                " ORDER BY at DESC, id DESC LIMIT %s",
                [limit],
            )
            rows = await cur.fetchall()
        return [
            MusicSignal(u or "", a or "", MusicSignalValue(s), at, ctx or {}) for u, a, s, at, ctx in rows
        ]
