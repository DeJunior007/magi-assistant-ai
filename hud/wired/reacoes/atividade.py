"""Atividade do Pedro: "evento real", último uso e primeiro do dia (spec §5). Dono: R1.4. Stub de R0.1.

Estado em ``~/.local/state/magi/condessa-atividade.json`` (``ultimo``, ``dia``, ``primeiro_do_dia``);
o caminho é injetável.
"""

from __future__ import annotations

from pathlib import Path

ESTADO_FILE = Path.home() / ".local/state/magi/condessa-atividade.json"


class Atividade:
    """Guarda o último evento real do Pedro e se o de hoje já foi o primeiro do dia."""

    def __init__(self, caminho: Path | None = None) -> None:
        self.caminho = caminho or ESTADO_FILE  # lido na hora: os testes trocam o ESTADO_FILE
        self.ultimo: float | None = None
        self.dia: str | None = None
        self.primeiro_do_dia: bool = False

    def evento(self, agora: float, motivo: str) -> None:
        """Registra um evento real (clique no HUD, faixa nova, Claude rodando, Magui ouvindo, jogo)."""

    def parado_s(self, agora: float) -> float | None:
        """Segundos desde o último evento real (None = nenhum ainda)."""
        return None
