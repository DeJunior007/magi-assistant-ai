"""``NewsRepo`` em Postgres (design §7). Tarefa 6.1 cobre fontes e notícias cruas; a 6.6, criar
itens e juntar cruas a eles (agrupamento). Os demais métodos de itens, preferências, progresso e
retorno são das tarefas 6.7+ e ainda levantam ``NotImplementedError``.

Usa uma ``psycopg.AsyncConnection`` em modo ``autocommit`` (cada chamada é uma transação). Os
nomes das tabelas não têm schema: o ``search_path`` da conexão decide (testes usam um schema
temporário).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg

from magi.common.contracts import FranchisePref, NewsItem, NewsLevel, NewsRaw, NewsSource, Progress


def _todo(name: str) -> NotImplementedError:
    return NotImplementedError(f"PgNewsRepo.{name}: implementado nas tarefas 6.7+")


_ITEM_COLS = (
    "id, title, summary, first_seen, sources, max_trust, franchise, kind, spoiler, priority, level, "
    "delivered_at"
)


def _vec(embedding: Sequence[float]) -> str:
    """Literal de ``vector`` do pgvector (sem depender do adaptador registrado na conexão)."""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def _item(row: Sequence[Any]) -> NewsItem:
    i, title, summary, first_seen, sources, max_trust, franchise, kind, spoiler, prio, level, deliv = row
    return NewsItem(
        title=title,
        summary=summary or "",
        first_seen=first_seen,
        sources=sources,
        max_trust=max_trust or 1,
        franchise=franchise,
        kind=kind,
        spoiler=spoiler,
        priority=prio,
        level=NewsLevel(level) if level else None,
        delivered_at=deliv,
        id=i,
    )


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

    async def add_item(self, item: NewsItem, embedding: Sequence[float], raw_ids: Sequence[int]) -> int:
        """Cria o item e liga as cruas. Com ``raw_ids``, ``sources`` e ``max_trust`` são recontados
        das fontes ligadas (os valores de ``item`` valem só sem cruas)."""
        async with self.conn.transaction():
            cur = await self.conn.execute(
                """
                INSERT INTO news_items (title, summary, embedding, first_seen, sources, max_trust)
                VALUES (%s, %s, %s::public.vector, COALESCE(%s, now()), %s, %s)
                RETURNING id
                """,
                [item.title, item.summary, _vec(embedding), item.first_seen, item.sources, item.max_trust],
            )
            row = await cur.fetchone()
            assert row is not None
            item_id = int(row[0])
            for raw_id in raw_ids:
                await self._link(item_id, raw_id)
            if raw_ids:
                await self._recount(item_id)
        return item_id

    async def attach_raw(self, item_id: int, raw_id: int) -> None:
        """Liga a crua ao item e reconta ``sources`` (fontes distintas) e ``max_trust``."""
        async with self.conn.transaction():
            await self._link(item_id, raw_id)
            await self._recount(item_id)

    async def similar_items(
        self, embedding: Sequence[float], since: datetime, min_cosine: float, limit: int = 5
    ) -> list[tuple[NewsItem, float]]:
        """Itens com ``first_seen >= since`` e cosseno >= ``min_cosine``, do mais parecido."""
        cur = await self.conn.execute(
            f"""
            SELECT {_ITEM_COLS}, 1 - (embedding OPERATOR(public.<=>) q.v) AS cos
            FROM news_items, (SELECT %s::public.vector AS v) q
            WHERE embedding IS NOT NULL AND first_seen >= %s
              AND 1 - (embedding OPERATOR(public.<=>) q.v) >= %s
            ORDER BY embedding OPERATOR(public.<=>) q.v
            LIMIT %s
            """,
            [_vec(embedding), since, min_cosine, limit],
        )
        return [(_item(r[:-1]), float(r[-1])) for r in await cur.fetchall()]

    async def _link(self, item_id: int, raw_id: int) -> None:
        await self.conn.execute(
            "INSERT INTO news_item_sources (item_id, raw_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            [item_id, raw_id],
        )

    async def _recount(self, item_id: int) -> None:
        # Crua sem fonte (fonte apagada) conta como fonte própria; confiança desconhecida = 1.
        await self.conn.execute(
            """
            UPDATE news_items i
            SET sources = GREATEST(c.n, 1), max_trust = c.t
            FROM (
                SELECT count(DISTINCT COALESCE(r.source_id::bigint, -r.id)) AS n,
                       max(COALESCE(s.trust, 1)) AS t
                FROM news_item_sources l
                JOIN news_raw r ON r.id = l.raw_id
                LEFT JOIN news_sources s ON s.id = r.source_id
                WHERE l.item_id = %s
            ) c
            WHERE i.id = %s
            """,
            [item_id, item_id],
        )

    # --- tarefas 6.7+ ------------------------------------------------------------------------

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
