"""Embeddings falsos determinísticos para os testes de memória (saco de palavras com hash)."""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import Sequence

DIM = 256
_STOP = frozenset("que eu o a os as de do da dos das um uma e é em no na pra para com por meu minha".split())


def _words(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", text.casefold())
    t = "".join(c if c.isalnum() else " " for c in t if not unicodedata.combining(c))
    return [w for w in t.split() if w not in _STOP and len(w) > 1]


def vector(text: str, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    for w in _words(text):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeEmbed:
    """``Embed`` falso: conta chamadas e textos."""

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim
        self.calls: list[list[str]] = []

    async def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [vector(t, self.dim) for t in texts]
