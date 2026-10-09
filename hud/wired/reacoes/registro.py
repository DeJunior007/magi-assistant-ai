"""Registro das reações (R10) em ``~/.local/state/magi/reacoes.jsonl``, giro de 5 MB.
Dono: R0.2. Stub de R0.1."""

from __future__ import annotations

from pathlib import Path

from .contratos import Def, Disparo

REGISTRO_FILE = Path.home() / ".local/state/magi/reacoes.jsonl"
GIRO_BYTES = 5 * 1024 * 1024


def gravar(d: Def, disparo: Disparo, agora: float, caminho: Path = REGISTRO_FILE) -> None:
    """Acrescenta uma linha JSON com a reação tocada (gira o arquivo acima de ``GIRO_BYTES``)."""
