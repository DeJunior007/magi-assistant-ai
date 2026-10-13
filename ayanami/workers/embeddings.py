"""Embeddings locais em lote (dono: Y3.6; spec §5.6, R3.7) — corpo de ``embeddings.lote``.

Só existe na fila com ``[embeddings] ligado = true`` (A8): :func:`ayanami.fila.montar` não
registra ``embeddings.lote`` sem isso (CA-Y13: 17 tarefas; 18 com a chave ligada).

- :class:`Embedder` é o protocolo; o real (:class:`FastEmbedLocal`) é ``fastembed`` 0.9.0 com
  ``intfloat/multilingual-e5-small`` (384 dimensões), carregado uma vez por processo no 1º uso (o
  import de ``fastembed`` só acontece aí). Testes passam um falso em ``deps.extras["embedder"]``.
- e5 pede prefixo: ``passage: `` para o que é guardado, ``query: `` para a pergunta
  (:func:`com_prefixo`). :func:`embutir` processa em lotes de :data:`LOTE` (64) e confere 384.
- O job recebe ``textos`` (lista) e ``tipo`` (``"passage"``/``"query"``) e devolve
  ``{"texto": "<n> vetores", "dados": {"vetores": [[...], ...], "dim": 384}}``; quem guardar em
  ``vector(384)`` (A8) lê dali.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from procrastinate import JobContext

from ayanami.deps import Deps

MODELO = "intfloat/multilingual-e5-small"
DIM = 384
LOTE = 64
Tipo = Literal["passage", "query"]


class Embedder(Protocol):
    def embutir(self, textos: Sequence[str]) -> list[list[float]]: ...


class FastEmbedLocal:
    """fastembed e5-small em CPU; modelo carregado no 1º uso."""

    def __init__(self, modelo: str = MODELO, *, pasta: Path | None = None) -> None:
        self.modelo, self.pasta = modelo, pasta
        self._m: Any = None
        self._trava = threading.Lock()

    def embutir(self, textos: Sequence[str]) -> list[list[float]]:
        with self._trava:
            if self._m is None:
                from fastembed import TextEmbedding  # só aqui: pesado

                self._m = TextEmbedding(self.modelo,
                                        cache_dir=str(self.pasta) if self.pasta else None)
        return [list(map(float, v)) for v in self._m.embed(list(textos), batch_size=LOTE)]


_padrao: FastEmbedLocal | None = None


def embedder_de(deps: Deps) -> Embedder:
    global _padrao
    e = deps.extras.get("embedder")
    if e is not None:
        return e
    if _padrao is None:
        _padrao = FastEmbedLocal(pasta=deps.dados / "modelos" / "fastembed")
    return _padrao


def com_prefixo(textos: Iterable[str], tipo: Tipo) -> list[str]:
    if tipo not in ("passage", "query"):
        raise ValueError(f"tipo de embedding desconhecido: {tipo!r}")
    return [f"{tipo}: {t}" for t in textos]


def lotes(itens: Sequence[str], n: int = LOTE) -> list[Sequence[str]]:
    return [itens[i:i + n] for i in range(0, len(itens), n)]


def embutir(embedder: Embedder, textos: Sequence[str], tipo: Tipo = "passage") -> list[list[float]]:
    """Vetores de ``textos`` (com prefixo e5), em lotes de 64; dimensão diferente de 384 → erro."""
    saida: list[list[float]] = []
    for parte in lotes(com_prefixo(textos, tipo)):
        vs = embedder.embutir(parte)
        if len(vs) != len(parte) or any(len(v) != DIM for v in vs):
            raise ValueError(f"embedder devolveu formato errado (esperado {len(parte)}×{DIM})")
        saida.extend(vs)
    return saida


async def lote(deps: Deps, contexto: JobContext, *, tarefa_id: str | None = None,
               textos: Sequence[str] = (), tipo: Tipo = "passage") -> dict[str, Any] | None:
    """``embeddings.lote``: ``textos`` → vetores 384 (só com ``[embeddings] ligado``; dono: Y3.6)."""
    if not deps.cfg.embeddings.ligado:
        raise RuntimeError("embeddings desligado ([embeddings] ligado = false)")
    textos = [str(t) for t in textos]
    vetores = await asyncio.to_thread(embutir, embedder_de(deps), textos, tipo)
    return {"texto": f"{len(vetores)} vetores", "dados": {"vetores": vetores, "dim": DIM}}
