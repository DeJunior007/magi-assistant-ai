"""Diretor de cenas (spec §8, acordo §4–§5). Dono: V0.10 (esqueleto: V0.1).

Recebe todos os ``Disparo``, agrupa por causa, escolhe roteiro e ramo, aplica fila e interrupção e
entrega **uma** ``Cena`` ao Reactor. O que não vira cena vira atenção dirigida ou só mexe no humor.
"""

from __future__ import annotations

import random

from .contratos import Disparo
from .estado import Estado
from .vida import Cena


class Diretor:
    def __init__(self, estado: Estado, cfg: dict | None = None, rng: random.Random | None = None) -> None:
        self.estado = estado
        self.cfg = cfg or {}
        self.rng = rng or random.Random()

    def receber(self, disparos: list[Disparo], agora: float) -> None:
        """Coalesce os disparos pela causa (``coalescencia_s``) e absorve a mesma família."""
        raise NotImplementedError

    def proxima(self, agora: float) -> Cena | None:
        """A cena a tocar agora (interrompe, fila de 1 vaga) ou ``None``."""
        raise NotImplementedError

    def atencao(self, agora: float) -> str | None:
        """Card para onde olhar (``atencao_ms``) quando o acontecimento não virou cena."""
        raise NotImplementedError
