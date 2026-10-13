"""Fila por TV da casa (spec §10.4 *Fila por TV*, §10.7; dono: C1.1b).

- um ``asyncio.Lock`` por TV: comandos da mesma TV em série, TVs diferentes em paralelo;
- no máximo ``limite`` (8) comandos por TV entre o que roda e o que espera; o seguinte →
  ``ResTv(False, OCUPADA)`` sem chamar nada;
- repetição de tecla (segurar vol+ no PWA chega como várias ``acao``): o mesmo comando repetível na
  mesma TV dentro de ``janela`` (80 ms) do último aceito é coalescido (``ok`` sem tecla), ou seja,
  sai no máximo 1 tecla a cada 80 ms;
- cada comando aceito abre uma nova *geração* da TV; a sequência emulada em curso (``Vez``) vê
  ``abortada=True`` e para na próxima tecla (a nova ganha).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass

from magi.casa.driver import Motivo, ResTv

LIMITE = 8
JANELA_S = 0.08


@dataclass(frozen=True)
class Vez:
    """A vez de um comando na fila da TV; ``abortada`` vira ``True`` quando chega outro."""

    fila: FilaTv
    tv_id: str
    geracao: int

    @property
    def abortada(self) -> bool:
        return self.fila.geracao(self.tv_id) != self.geracao


class FilaTv:
    def __init__(
        self,
        *,
        limite: int = LIMITE,
        janela: float = JANELA_S,
        relogio: Callable[[], float] | None = None,
    ) -> None:
        self.limite = limite
        self.janela = janela
        self.relogio = relogio or time.monotonic
        self._locks: dict[str, asyncio.Lock] = {}
        self._pendentes: dict[str, int] = {}
        self._geracao: dict[str, int] = {}
        self._ultima: dict[str, tuple[Hashable, float]] = {}

    def geracao(self, tv_id: str) -> int:
        return self._geracao.get(tv_id, 0)

    def pendentes(self, tv_id: str) -> int:
        return self._pendentes.get(tv_id, 0)

    async def rodar(
        self,
        tv_id: str,
        fn: Callable[[Vez], Awaitable[ResTv]],
        *,
        repeticao: Hashable | None = None,
    ) -> ResTv:
        """Roda ``fn`` na vez da TV. ``repeticao``: assinatura de comando repetível (tecla, passo de
        volume, canal) para a coalescência; ``None`` = nunca coalesce."""
        if repeticao is not None:
            agora = self.relogio()
            ultima = self._ultima.get(tv_id)
            if ultima is not None and ultima[0] == repeticao and agora - ultima[1] < self.janela - 1e-9:
                return ResTv(True, detalhe="coalescida")
        if self.pendentes(tv_id) >= self.limite:
            return ResTv(False, Motivo.OCUPADA, f"fila cheia ({self.limite})")
        if repeticao is not None:
            self._ultima[tv_id] = (repeticao, self.relogio())
        else:
            self._ultima.pop(tv_id, None)
        self._pendentes[tv_id] = self.pendentes(tv_id) + 1
        self._geracao[tv_id] = self.geracao(tv_id) + 1
        vez = Vez(self, tv_id, self._geracao[tv_id])
        lock = self._locks.setdefault(tv_id, asyncio.Lock())
        try:
            async with lock:
                return await fn(vez)
        finally:
            self._pendentes[tv_id] -= 1
