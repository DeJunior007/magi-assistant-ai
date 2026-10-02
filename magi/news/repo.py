"""``NewsRepo`` em Postgres (design §7). Tarefa 6.1 cobre fontes e notícias cruas; os métodos de
itens, preferências, progresso e retorno são das tarefas 6.6+ e ainda levantam
``NotImplementedError``.

Usa uma ``psycopg.AsyncConnection`` em modo ``autocommit`` (cada chamada é uma transação). Os
nomes das tabelas não têm schema: o ``search_path`` da conexão decide (testes usam um schema
temporário).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import psycopg

from magi.common.contracts import FranchisePref, NewsItem, NewsLevel, NewsRaw, NewsSource, Progress


def _todo(name: str) -> NotImplementedError:
    return NotImplementedError(f"PgNewsRepo.{name}: implementado nas tarefas 6.6+")


class PgNewsRepo:
    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self.conn = conn

    @classmethod
    async def connect(cls, dsn: str, *, schema: str | None = None, timeout: int = 5) -> PgNewsRepo:
        options = f"-c search_path={schema},public" if schema else None
        conn = await psycopg.AsyncConnection.connect(
            dsn, autocommit=True, connect_timeout=timeout, options=options
        )
        return cls(conn)

    async def close(self) -> None:
        await self.conn.close()

    # --- fontes e notícias cruas (6.1) -------------------------------------------------------

    async def sources(self) -> list[NewsSource]:
        cur = await self.conn.execute("SELECT id, name, kind, url, trust FROM news_sources ORDER BY id")
        return [NewsSource(name=n, kind=k, url=u, trust=t, id=i) for i, n, k, u, t in await cur.fetchall()]

    async def upsert_source(self, source: NewsSource) -> int:
        """Chave natural: ``url``. Atualiza nome, tipo e confiança se a fonte já existe."""
        cur = await self.conn.execute(
            """
            INSERT INTO news_sources (name, kind, url, trust) VALUES (%s, %s, %s, %s)
            ON CONFLICT (url) DO UPDATE
                SET name = EXCLUDED.name, kind = EXCLUDED.kind, trust = EXCLUDED.trust
            RETURNING id
            """,
            [source.name, source.kind, source.url, source.trust],
        )
        row = await cur.fetchone()
        assert row is not None
        return int(row[0])

    async def add_raw(self, raw: NewsRaw) -> int | None:
        cur = await self.conn.execute(
            """
            INSERT INTO news_raw (source_id, url, title, body, published_at, fetched_at)
            VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()))
            ON CONFLICT (url) DO NOTHING
            RETURNING id
            """,
            [raw.source_id, raw.url, raw.title, raw.body, raw.published_at, raw.fetched_at],
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None

    async def ungrouped_raw(self, limit: int = 200) -> list[NewsRaw]:
        """Cruas ainda sem item (fora de ``news_item_sources``), mais antigas primeiro."""
        cur = await self.conn.execute(
            """
            SELECT r.id, r.source_id, r.url, r.title, r.body, r.published_at, r.fetched_at
            FROM news_raw r
            WHERE NOT EXISTS (SELECT 1 FROM news_item_sources s WHERE s.raw_id = r.id)
            ORDER BY r.fetched_at, r.id
            LIMIT %s
            """,
            [limit],
        )
        return [
            NewsRaw(source_id=s, url=u, title=t or "", body=b or "", published_at=p, fetched_at=f, id=i)
            for i, s, u, t, b, p, f in await cur.fetchall()
        ]

    # --- tarefas 6.6+ ------------------------------------------------------------------------

    async def add_item(self, item: NewsItem, embedding: Sequence[float], raw_ids: Sequence[int]) -> int:
        raise _todo("add_item")

    async def attach_raw(self, item_id: int, raw_id: int) -> None:
        raise _todo("attach_raw")

    async def similar_items(
        self, embedding: Sequence[float], since: datetime, min_cosine: float, limit: int = 5
    ) -> list[tuple[NewsItem, float]]:
        raise _todo("similar_items")

    async def update_item(self, item: NewsItem) -> None:
        raise _todo("update_item")

    async def unclassified(self, limit: int = 50) -> list[NewsItem]:
        raise _todo("unclassified")

    async def undelivered(self, levels: Sequence[NewsLevel], limit: int = 5) -> list[NewsItem]:
        raise _todo("undelivered")

    async def mark_delivered(self, item_id: int, at: datetime) -> None:
        raise _todo("mark_delivered")

    async def search_items(
        self, *, franchise: str | None = None, embedding: Sequence[float] | None = None, limit: int = 5
    ) -> list[NewsItem]:
        raise _todo("search_items")

    async def franchise_prefs(self) -> list[FranchisePref]:
        raise _todo("franchise_prefs")

    async def set_franchise_pref(self, pref: FranchisePref) -> None:
        raise _todo("set_franchise_pref")

    async def progress(self, franchise: str) -> list[Progress]:
        raise _todo("progress")

    async def set_progress(self, progress: Progress) -> None:
        raise _todo("set_progress")

    async def add_feedback(self, item_id: int, signal: int, at: datetime) -> None:
        raise _todo("add_feedback")
