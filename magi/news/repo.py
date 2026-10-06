"""``NewsRepo`` em Postgres (design §7). Tarefa 6.1 cobre fontes e notícias cruas; a 6.6, criar
itens e juntar cruas a eles (agrupamento); a 6.7, classificação e retorno; a 6.8, preferências
por obra e progresso; a 6.10, pontuação (``unscored``) e entrega; a 6.11, retorno
(``delivered_recent``, ``feedback_signals``); a 6.12, a busca por obra (``search_items``).

Usa uma ``psycopg.AsyncConnection`` em modo ``autocommit`` (cada chamada é uma transação). Os
nomes das tabelas não têm schema: o ``search_path`` da conexão decide (testes usam um schema
temporário).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from magi.common.contracts import FranchisePref, NewsItem, NewsLevel, NewsRaw, NewsSource, Progress
from magi.news.spoiler import norm

#: Obra + manchete normalizadas como ``spoiler.norm`` (minúsculas, sem acento, só letras/dígitos),
#: com espaço nas pontas para casar palavras inteiras.
_NORM_TEXT = (
    "(' ' || regexp_replace(translate(lower(coalesce(franchise, '') || ' ' || title),"
    " 'áàâãäåéèêëíìîïóòôõöúùûüçñ', 'aaaaaaeeeeiiiiooooouuuucn'), '[^a-z0-9]+', ' ', 'g') || ' ')"
)


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
        if item.id is None:
            raise ValueError("update_item exige item.id")
        await self.conn.execute(
            "UPDATE news_items SET franchise = %s, kind = %s, spoiler = %s, priority = %s, level = %s"
            " WHERE id = %s",
            [
                item.franchise,
                item.kind,
                Jsonb(dict(item.spoiler)) if item.spoiler is not None else None,
                item.priority,
                item.level.value if item.level else None,
                item.id,
            ],
        )

    async def unclassified(self, limit: int = 50) -> list[NewsItem]:
        """Itens sem ``kind`` (a classificação da 6.7 sempre grava ``kind``), mais antigos antes."""
        cur = await self.conn.execute(
            f"SELECT {_ITEM_COLS} FROM news_items WHERE kind IS NULL ORDER BY first_seen, id LIMIT %s",
            [limit],
        )
        return [_item(r) for r in await cur.fetchall()]

    async def recent_feedback(self, limit: int = 6) -> list[tuple[NewsItem, int]]:
        """Itens já classificados com retorno do usuário, o retorno mais recente de cada um
        primeiro (exemplos da classificação, design §8 passo 3)."""
        cols = ", ".join(f"i.{c.strip()}" for c in _ITEM_COLS.split(","))
        cur = await self.conn.execute(
            f"SELECT * FROM (SELECT DISTINCT ON (i.id) {cols}, f.signal, f.at FROM news_feedback f"
            " JOIN news_items i ON i.id = f.item_id WHERE i.kind IS NOT NULL"
            " ORDER BY i.id, f.at DESC, f.id DESC) t ORDER BY t.at DESC LIMIT %s",
            [limit],
        )
        return [(_item(r[:12]), r[12]) for r in await cur.fetchall()]

    async def unscored(self, limit: int = 100) -> list[NewsItem]:
        """Itens classificados ainda sem nível (passo 4 do §8; fora do contrato)."""
        cur = await self.conn.execute(
            f"SELECT {_ITEM_COLS} FROM news_items WHERE kind IS NOT NULL AND level IS NULL"
            " ORDER BY first_seen, id LIMIT %s",
            [limit],
        )
        return [_item(r) for r in await cur.fetchall()]

    async def undelivered(self, levels: Sequence[NewsLevel], limit: int = 5) -> list[NewsItem]:
        """Bombas antes, depois maior prioridade e mais recentes."""
        cur = await self.conn.execute(
            f"SELECT {_ITEM_COLS} FROM news_items WHERE delivered_at IS NULL AND level = ANY(%s)"
            " ORDER BY (level = 'bomba') DESC, priority DESC NULLS LAST, first_seen DESC, id LIMIT %s",
            [[lv.value for lv in levels], limit],
        )
        return [_item(r) for r in await cur.fetchall()]

    async def mark_delivered(self, item_id: int, at: datetime) -> None:
        """Idempotente: só grava a primeira entrega."""
        await self.conn.execute(
            "UPDATE news_items SET delivered_at = %s WHERE id = %s AND delivered_at IS NULL", [at, item_id]
        )

    async def item_links(self, item_ids: Sequence[int]) -> dict[int, list[str]]:
        """URLs das notícias cruas de cada item (fora do contrato; cards da entrega)."""
        cur = await self.conn.execute(
            "SELECT l.item_id, r.url FROM news_item_sources l JOIN news_raw r ON r.id = l.raw_id"
            " LEFT JOIN news_sources s ON s.id = r.source_id"
            " WHERE l.item_id = ANY(%s) ORDER BY l.item_id, s.trust DESC NULLS LAST, r.id",
            [list(item_ids)],
        )
        out: dict[int, list[str]] = {}
        for item_id, url in await cur.fetchall():
            out.setdefault(item_id, []).append(url)
        return out

    async def item_sources(self, item_id: int, limit: int = 5) -> list[tuple[str, str]]:
        """``(url, texto do feed)`` das notícias cruas de um item, mais confiável primeiro (fora do
        contrato; "conta mais dessa")."""
        cur = await self.conn.execute(
            "SELECT r.url, coalesce(r.body, '') FROM news_item_sources l JOIN news_raw r ON r.id = l.raw_id"
            " LEFT JOIN news_sources s ON s.id = r.source_id"
            " WHERE l.item_id = %s ORDER BY s.trust DESC NULLS LAST, length(r.body) DESC NULLS LAST LIMIT %s",
            [item_id, limit],
        )
        return [(url, body) for url, body in await cur.fetchall()]

    async def search_items(
        self, *, franchise: str | None = None, embedding: Sequence[float] | None = None, limit: int = 5
    ) -> list[NewsItem]:
        """Itens classificados sobre ``franchise`` (6.12, R20.1), maior prioridade e mais recentes
        primeiro. Casamento tolerante: cada palavra de ``norm(franchise)`` aparece inteira na obra
        ou na manchete normalizadas (sem acento/pontuação). Sem ``franchise``: todos. ``embedding``
        ainda é ignorado."""
        conds = ["kind IS NOT NULL"]
        params: list[Any] = []
        for word in norm(franchise or "").split():
            conds.append(f"{_NORM_TEXT} LIKE %s")
            params.append(f"% {word} %")
        cur = await self.conn.execute(
            f"SELECT {_ITEM_COLS} FROM news_items WHERE {' AND '.join(conds)}"
            " ORDER BY priority DESC NULLS LAST, first_seen DESC NULLS LAST, id DESC LIMIT %s",
            [*params, limit],
        )
        return [_item(r) for r in await cur.fetchall()]

    # --- preferências por obra e progresso (6.8) ----------------------------------------------

    async def franchise_prefs(self) -> list[FranchisePref]:
        cur = await self.conn.execute(
            "SELECT franchise, weight, dropped, spoilers_ok FROM franchise_prefs ORDER BY franchise"
        )
        return [FranchisePref(f, float(w), bool(d), bool(s)) for f, w, d, s in await cur.fetchall()]

    async def set_franchise_pref(self, pref: FranchisePref) -> None:
        """Grava a linha inteira (chave: ``franchise``)."""
        await self.conn.execute(
            """
            INSERT INTO franchise_prefs (franchise, weight, dropped, spoilers_ok)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (franchise) DO UPDATE
                SET weight = EXCLUDED.weight, dropped = EXCLUDED.dropped,
                    spoilers_ok = EXCLUDED.spoilers_ok
            """,
            [pref.franchise, pref.weight, pref.dropped, pref.spoilers_ok],
        )

    async def progress(self, franchise: str) -> list[Progress]:
        """Valores não numéricos na coluna ``text`` são ignorados."""
        cur = await self.conn.execute(
            "SELECT franchise, kind, value, updated_at FROM progress WHERE franchise = %s ORDER BY kind",
            [franchise],
        )
        return self._progress_rows(await cur.fetchall())

    async def all_progress(self) -> list[Progress]:
        """Todo o progresso (fora do contrato): casamento tolerante de nomes no anti-spoiler."""
        cur = await self.conn.execute(
            "SELECT franchise, kind, value, updated_at FROM progress ORDER BY franchise, kind"
        )
        return self._progress_rows(await cur.fetchall())

    @staticmethod
    def _progress_rows(rows: Sequence[Sequence[Any]]) -> list[Progress]:
        out: list[Progress] = []
        for f, k, v, at in rows:
            try:
                out.append(Progress(franchise=f, kind=k, value=float(v), updated_at=at))
            except (TypeError, ValueError):
                continue
        return out

    async def set_progress(self, progress: Progress) -> None:
        """Upsert por (``franchise``, ``kind``); ``value`` vai como texto (``12``, ``6.25``)."""
        await self.conn.execute(
            """
            INSERT INTO progress (franchise, kind, value, updated_at) VALUES (%s, %s, %s, %s)
            ON CONFLICT (franchise, kind) DO UPDATE
                SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
            """,
            [progress.franchise, progress.kind, f"{progress.value:g}", progress.updated_at],
        )

    async def progress_updated_at(self) -> datetime | None:
        """Última sincronização de progresso (fora do contrato; usado pelo intervalo de 6.8)."""
        cur = await self.conn.execute("SELECT max(updated_at) FROM progress")
        row = await cur.fetchone()
        return row[0] if row else None

    async def add_feedback(self, item_id: int, signal: int, at: datetime) -> None:
        await self.conn.execute(
            "INSERT INTO news_feedback (item_id, signal, at) VALUES (%s, %s, %s)", [item_id, signal, at]
        )

    # --- retorno (6.11; fora do contrato) ----------------------------------------------------

    async def delivered_recent(self, limit: int = 50) -> list[NewsItem]:
        """Itens já entregues, a entrega mais recente primeiro."""
        cur = await self.conn.execute(
            f"SELECT {_ITEM_COLS} FROM news_items WHERE delivered_at IS NOT NULL"
            " ORDER BY delivered_at DESC, id DESC LIMIT %s",
            [limit],
        )
        return [_item(r) for r in await cur.fetchall()]

    async def feedback_signals(self, item_ids: Sequence[int]) -> dict[int, list[int]]:
        """Sinais de retorno de cada item, do mais antigo ao mais recente."""
        cur = await self.conn.execute(
            "SELECT item_id, signal FROM news_feedback WHERE item_id = ANY(%s) ORDER BY item_id, at, id",
            [list(item_ids)],
        )
        out: dict[int, list[int]] = {}
        for item_id, signal in await cur.fetchall():
            out.setdefault(item_id, []).append(int(signal))
        return out
