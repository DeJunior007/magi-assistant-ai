"""Humor da Condessa (spec §2, acordo §1). Dono: V0.2 (esqueleto: V0.1).

``Humor`` (ânimo, energia, decaimento, retorno decrescente, faixa com histerese), ``Postura`` (fone
com motivo) e ``Estado`` (persistência em ``~/.local/state/magi/condessa-estado.json``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .vida import Causa, Evento, Faixa, Fone

ESTADO_FILE = Path.home() / ".local/state/magi/condessa-estado.json"


@dataclass
class Postura:
    """Fone CABECA/PESCOCO, com o motivo da última troca (spec §4)."""

    fone: Fone = Fone.PESCOCO
    motivo: str = ""


class Humor:
    """Ânimo e energia (spec §2). Números do ``[vida.humor]``."""

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or {}

    def aplicar(self, evento: Evento, agora: float) -> float:
        """Aplica o Δ do evento (habituação, trava por fonte, piso, teto); devolve o Δ efetivo."""
        raise NotImplementedError

    def tick(self, agora: float, hora: int, ctx: dict) -> None:
        """Volta à base, Pedro sumido, energia pelo relógio."""
        raise NotImplementedError

    def faixa(self, agora: float) -> Faixa:
        """Faixa atual, com histerese."""
        raise NotImplementedError

    def medidor(self) -> tuple[float, str, str, tuple[Causa, ...]]:
        """(valor -1..+1, cor, momento, últimas 3 causas)."""
        raise NotImplementedError


class Estado:
    """Humor + postura + contadores do governador, persistidos com escrita atômica."""

    def __init__(self, humor: Humor | None = None, postura: Postura | None = None,
                 governador: dict | None = None) -> None:
        self.humor = humor or Humor()
        self.postura = postura or Postura()
        self.governador = governador or {}

    def salvar(self, agora: float, path: Path | None = None) -> None:
        raise NotImplementedError

    @classmethod
    def carregar(cls, agora: float, cfg: dict | None = None, path: Path | None = None) -> Estado:
        """Lê o estado (inválido → base) e aplica o decaimento do tempo com o HUD fechado."""
        raise NotImplementedError
