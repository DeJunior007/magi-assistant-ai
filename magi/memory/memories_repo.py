"""Memórias e histórico de turnos (tarefa 4.1, §7 ``memories``/``turns``, R11.2, R11.5, R11.6).

- ``PgMemoriesRepo`` / ``InMemoryMemoriesRepo``: ``MemoriesRepo`` com busca por cosseno. A busca
  devolve no máximo ``limit`` memórias com ``score`` (1 - distância de cosseno) ≥ ``min_score``:
  o limiar evita que memória sem relação entre no prompt.
- ``PgTurnsRepo``: ``TurnsRepo`` sobre ``turns`` (histórico local consultável e apagável).
- ``MemoryStore``: o que agente e "esquece isso" usam. ``remember`` grava em segundo plano
  (o embedding não atrasa a resposta); ``relevant`` faz um embedding da fala e busca até 5;
  ``forget_last`` apaga a última memória gravada; ``forget`` apaga a mais parecida com um texto.
  O custo dos embeddings passa pelo registro de provedores (orçamento, R16).
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from psycopg.rows import class_row

from magi.common.contracts import MEMORY_TOP_K, Memory, TurnRecord

log = logging.getLogger(__name__)

#: Similaridade mínima para uma memória entrar no prompt (text-embedding-3-small: textos sem
#: relação ficam em ~0,1-0,25; o mesmo assunto passa de ~0,4).
MIN_SCORE = 0.35
#: "forget(what)" só apaga se a mais parecida passar deste limiar.
#: Memória mais nova que isso é "desta conversa": o "esquece" apaga sem perguntar.
FRESH_MEMORY = timedelta(minutes=30)
FORGET_MIN_SCORE = 0.45
#: Fato quase igual a um já gravado não é gravado de novo.
DUPLICATE_SCORE = 0.93
#: Tempo máximo do embedding da busca antes do turno (sem memórias se estourar).
SEARCH_TIMEOUT_S = 2.0
BODY_MAX_CHARS = 500

_MEM_COLS = "kind, body, turn_id, created_at, id"


def _vec(embedding: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(x):.7g}" for x in embedding) + "]"


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class MemoriesStore(Protocol):
    """``MemoriesRepo`` + ``recent`` e ``min_score`` na busca (os dois repos daqui)."""

    async def add(self, memory: Memory, embedding: Sequence[float]) -> int: ...

    async def search(
        self, embedding: Sequence[float], limit: int = MEMORY_TOP_K, min_score: float = 0.0
    ) -> list[Memory]: ...

    async def delete(self, memory_id: int) -> None: ...

    async def delete_by_turn(self, turn_id: int) -> int: ...

    async def recent(self, limit: int = 20) -> list[Memory]: ...


# ---------------------------------------------------------------------------------------------
# Repositórios
# ---------------------------------------------------------------------------------------------


class PgMemoriesRepo:
    """``MemoriesRepo`` em Postgres + pgvector (índice HNSW de cosseno)."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def add(self, memory: Memory, embedding: Sequence[float]) -> int:
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "INSERT INTO memories (kind, body, embedding, turn_id) VALUES (%s, %s, %s::public.vector, %s)"
                " RETURNING id",
                [memory.kind, memory.body, _vec(embedding), memory.turn_id],
            )
            row = await cur.fetchone()
        assert row is not None
        return int(row[0])

    async def search(
        self, embedding: Sequence[float], limit: int = MEMORY_TOP_K, min_score: float = 0.0
    ) -> list[Memory]:
        v = _vec(embedding)
        async with self._conn.transaction():
            cur = self._conn.cursor(row_factory=class_row(Memory))
            await cur.execute(
                f"SELECT {_MEM_COLS}, (1 - (embedding <=> %s::public.vector))::float8 AS score"
                " FROM memories WHERE embedding IS NOT NULL"
                " ORDER BY embedding <=> %s::public.vector LIMIT %s",
                [v, v, limit],
            )
            rows = await cur.fetchall()
        return [m for m in rows if (m.score or 0.0) >= min_score]

    async def delete(self, memory_id: int) -> None:
        async with self._conn.transaction():
            await self._conn.execute("DELETE FROM memories WHERE id = %s", [memory_id])

    async def delete_by_turn(self, turn_id: int) -> int:
        async with self._conn.transaction():
            cur = await self._conn.execute("DELETE FROM memories WHERE turn_id = %s", [turn_id])
            return cur.rowcount

    async def recent(self, limit: int = 20) -> list[Memory]:
        async with self._conn.transaction():
            cur = self._conn.cursor(row_factory=class_row(Memory))
            await cur.execute(f"SELECT {_MEM_COLS} FROM memories ORDER BY id DESC LIMIT %s", [limit])
            return await cur.fetchall()


class InMemoryMemoriesRepo:
    """Mesma API sem banco (testes e núcleo sem Postgres: vale só enquanto o processo vive)."""

    def __init__(self) -> None:
        self._rows: dict[int, tuple[Memory, list[float]]] = {}
        self._next = 1

    async def add(self, memory: Memory, embedding: Sequence[float]) -> int:
        mid = self._next
        self._next += 1
        self._rows[mid] = (replace(memory, id=mid, created_at=datetime.now(UTC), score=None), list(embedding))
        return mid

    async def search(
        self, embedding: Sequence[float], limit: int = MEMORY_TOP_K, min_score: float = 0.0
    ) -> list[Memory]:
        scored = [replace(m, score=cosine(embedding, e)) for m, e in self._rows.values()]
        scored.sort(key=lambda m: m.score or 0.0, reverse=True)
        return [m for m in scored[:limit] if (m.score or 0.0) >= min_score]

    async def delete(self, memory_id: int) -> None:
        self._rows.pop(memory_id, None)

    async def delete_by_turn(self, turn_id: int) -> int:
        ids = [i for i, (m, _) in self._rows.items() if m.turn_id == turn_id]
        for i in ids:
            del self._rows[i]
        return len(ids)

    async def recent(self, limit: int = 20) -> list[Memory]:
        return [self._rows[i][0] for i in sorted(self._rows, reverse=True)[:limit]]


_TURN_COLS = (
    "coalesce(satellite, '') AS satellite, coalesce(text_heard, '') AS text_heard,"
    " coalesce(text_final, '') AS text_final, at, intent, routed_local, coalesce(reply, '') AS reply,"
    " CASE WHEN mood ~ '^-?[0-9]+$' THEN mood::int END AS mood, cost_usd::float8 AS cost_usd, id"
)


class PgTurnsRepo:
    """``TurnsRepo`` em Postgres (R11.6). ``turns.mood`` é texto no banco; aqui vira int."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def add(self, turn: TurnRecord) -> int:
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "INSERT INTO turns (at, satellite, text_heard, text_final, intent, routed_local, reply,"
                " mood, cost_usd) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                [
                    turn.at,
                    turn.satellite,
                    turn.text_heard,
                    turn.text_final,
                    turn.intent,
                    turn.routed_local,
                    turn.reply,
                    None if turn.mood is None else str(turn.mood),
                    turn.cost_usd,
                ],
            )
            row = await cur.fetchone()
        assert row is not None
        return int(row[0])

    async def _select(self, where: str, args: list[Any], limit: int) -> list[TurnRecord]:
        async with self._conn.transaction():
            cur = self._conn.cursor(row_factory=class_row(TurnRecord))
            await cur.execute(
                f"SELECT {_TURN_COLS} FROM turns {where} ORDER BY id DESC LIMIT %s", [*args, limit]
            )
            return await cur.fetchall()

    async def last(self, satellite: str | None = None) -> TurnRecord | None:
        where, args = ("WHERE satellite = %s", [satellite]) if satellite else ("", [])
        rows = await self._select(where, args, 1)
        return rows[0] if rows else None

    async def recent(self, limit: int = 20) -> list[TurnRecord]:
        return await self._select("", [], limit)

    async def delete(self, turn_id: int) -> None:
        async with self._conn.transaction():
            await self._conn.execute("DELETE FROM turns WHERE id = %s", [turn_id])

    async def delete_all(self) -> int:
        async with self._conn.transaction():
            cur = await self._conn.execute("DELETE FROM turns")
            return cur.rowcount


# ---------------------------------------------------------------------------------------------
# Serviço
# ---------------------------------------------------------------------------------------------

Embed = Callable[[Sequence[str]], Awaitable[list[list[float]]]]


def provider_embed(providers: Any) -> Embed:
    """``Embed`` sobre ``providers.embeddings()`` (tarefa ``embeddings``; dado pessoal)."""

    async def embed(texts: Sequence[str]) -> list[list[float]]:
        return await providers.embeddings().embed(texts, personal=True)

    return embed


class MemoryStore:
    """Memórias do agente: grava em segundo plano, busca antes do turno, apaga no "esquece isso"."""

    def __init__(
        self,
        repo: MemoriesStore,
        embed: Embed,
        *,
        min_score: float = MIN_SCORE,
        limit: int = MEMORY_TOP_K,
        search_timeout_s: float = SEARCH_TIMEOUT_S,
    ) -> None:
        self.repo = repo
        self._embed = embed
        self.min_score = min_score
        self.limit = limit
        self.search_timeout_s = search_timeout_s
        self.last_id: int | None = None
        self._pending: set[asyncio.Task[int | None]] = set()

    def remember(self, body: str, kind: str = "fact", turn_id: int | None = None) -> bool:
        """Agenda a gravação (embedding + insert) sem bloquear. ``False`` se o texto é vazio."""
        body = " ".join(body.split())[:BODY_MAX_CHARS]
        if not body:
            return False
        task = asyncio.create_task(self._store(Memory(kind=kind, body=body, turn_id=turn_id)))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return True

    async def _store(self, memory: Memory) -> int | None:
        try:
            [vec] = await self._embed([memory.body])
            near = await self.repo.search(vec, 1, DUPLICATE_SCORE)
            if near and near[0].id is not None:  # já sei disso: troca pelo texto novo
                await self.repo.delete(near[0].id)
            mid = await self.repo.add(memory, vec)
        except Exception:
            log.exception("memória: falha ao gravar %r", memory.body[:60])
            return None
        self.last_id = mid
        return mid

    async def drain(self) -> None:
        """Espera as gravações pendentes (antes de apagar e nos testes)."""
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def relevant(self, text: str) -> list[Memory]:
        """Até ``limit`` memórias acima do limiar; ``[]`` em erro ou estouro de tempo."""
        if not text.strip():
            return []
        try:
            async with asyncio.timeout(self.search_timeout_s):
                [vec] = await self._embed([text])
                return await self.repo.search(vec, self.limit, self.min_score)
        except Exception as e:
            log.warning("memória: busca indisponível (%s)", type(e).__name__)
            return []

    def is_fresh(self, memory: Memory, now: datetime | None = None) -> bool:
        """Memória desta conversa: a última gravada nesta execução ou com até ``FRESH_MEMORY``.
        Apagar uma dessas não pede confirmação; uma antiga, sim."""
        if memory.id is not None and memory.id == self.last_id:
            return True
        if memory.created_at is None:
            return False
        return (now or datetime.now(UTC)) - memory.created_at <= FRESH_MEMORY

    async def last_memory(self) -> Memory | None:
        """A última memória gravada (nesta execução ou, se nenhuma, a mais recente do banco)."""
        await self.drain()
        recent = await self.repo.recent(50)
        target = next((m for m in recent if m.id == self.last_id), None) if self.last_id else None
        if target is None and recent:
            target = recent[0]
        return target if target is not None and target.id is not None else None

    async def similar(self, what: str) -> Memory | None:
        """A memória mais parecida com ``what`` (se passar de ``FORGET_MIN_SCORE``); vazio = a última."""
        await self.drain()
        if not what.strip():
            return await self.last_memory()
        [vec] = await self._embed([what])
        hits = await self.repo.search(vec, 1, FORGET_MIN_SCORE)
        return hits[0] if hits and hits[0].id is not None else None

    async def delete(self, memory_id: int) -> None:
        await self.repo.delete(memory_id)
        if memory_id == self.last_id:
            self.last_id = None

    async def forget_last(self) -> Memory | None:
        """Apaga a última memória gravada (ver ``last_memory``)."""
        target = await self.last_memory()
        if target is not None and target.id is not None:
            await self.delete(target.id)
        return target

    async def forget(self, what: str) -> Memory | None:
        """Apaga a memória mais parecida com ``what`` (ver ``similar``)."""
        target = await self.similar(what)
        if target is not None and target.id is not None:
            await self.delete(target.id)
        return target

    async def recent(self, limit: int = 20) -> list[Memory]:
        return await self.repo.recent(limit)
