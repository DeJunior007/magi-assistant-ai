"""``BookHandler`` dos intents ``book.*`` (tarefa A2.3; spec §5, requirements A1, A6–A8).

Tempo restante (``book.time``), ambiguidade (A1.1), não começa em call (A8.4), música pausada e
retomada pelo MPRIS (D4), ``magi-qwen`` ligado no ``book.read`` e parado no fim se foi ele (D2).
"""

from __future__ import annotations

from typing import Any


class BookHandler:
    intents: frozenset[str] = frozenset()

    def __init__(self, **deps: Any) -> None:
        self.deps = deps

    async def run(self, req: Any) -> Any:
        raise NotImplementedError("A2.3")
