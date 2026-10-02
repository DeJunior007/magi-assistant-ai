"""Perfil de gosto musical em Postgres (tarefa 2.3, §7 tabela ``taste``, R8.1, R8.2).

Implementa ``magi.common.contracts.TasteRepo`` sobre uma ``psycopg.AsyncConnection``. A chave é
``(artist, genre)``; ``genre`` vazio quando o Spotify não informa (apps novos não recebem gêneros).
``upsert`` é idempotente: grava o peso dado, substituindo o anterior (rodar a importação de novo
não duplica nem acumula). ``adjust`` soma um delta a todas as linhas do artista (cria com gênero
vazio se ele ainda não existir).
"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg

from magi.common.contracts import TasteEntry


class TasteRepo:
    """``TasteRepo`` em Postgres."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def upsert(self, entries: Sequence[TasteEntry]) -> None:
        # Última ocorrência vence se a mesma chave vier repetida no lote.
        rows = {(e.artist, e.genre or ""): float(e.weight) for e in entries if e.artist}
        if not rows:
            return
        async with self._conn.transaction():
            async with self._conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO taste (artist, genre, weight) VALUES (%s, %s, %s)"
                    " ON CONFLICT (artist, genre) DO UPDATE SET weight = EXCLUDED.weight",
                    [(a, g, w) for (a, g), w in rows.items()],
                )

    async def top(self, limit: int = 50, genre: str | None = None) -> list[TasteEntry]:
        q = "SELECT artist, genre, weight FROM taste"
        params: list[object] = []
        if genre is not None:
            q += " WHERE genre = %s"
            params.append(genre)
        q += " ORDER BY weight DESC, artist LIMIT %s"
        params.append(limit)
        async with self._conn.transaction():
            cur = await self._conn.execute(q, params)
            rows = await cur.fetchall()
        return [TasteEntry(a, g, float(w)) for a, g, w in rows]

    async def adjust(self, artist: str, delta: float) -> None:
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "UPDATE taste SET weight = weight + %s WHERE artist = %s", [delta, artist]
            )
            if cur.rowcount == 0:
                await self._conn.execute(
                    "INSERT INTO taste (artist, genre, weight) VALUES (%s, '', %s)"
                    " ON CONFLICT (artist, genre) DO UPDATE SET weight = taste.weight + EXCLUDED.weight",
                    [artist, delta],
                )

    async def count(self) -> int:
        """Quantidade de linhas (a importação automática só roda com a tabela vazia)."""
        async with self._conn.transaction():
            cur = await self._conn.execute("SELECT count(*) FROM taste")
            row = await cur.fetchone()
        return int(row[0]) if row else 0
