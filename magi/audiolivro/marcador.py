"""Marcador por livro e registro de sessões (tarefa A1.4; spec §1, requirements A5, A10).

Posição em ``estado_dir/audiolivro.json`` (atômico, com ``.bak``; ≤ 1 escrita a cada 2 s em
leitura contínua + no fim); sessões em ``audiolivro.jsonl`` com giro de 5 MB. Relógio injetado.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Posicao

#: Intervalo mínimo entre gravações em leitura contínua (CA-A5).
INTERVALO_S = 2.0
#: Tamanho em que o ``audiolivro.jsonl`` gira.
GIRO_BYTES = 5 * 1024 * 1024


class Marcador:
    def __init__(self, cfg: ConfigAudiolivro, *, relogio: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self.relogio = relogio

    def posicao(self, livro_id: str) -> Posicao | None:
        """Última posição gravada do livro (do ``.bak`` se o principal estiver truncado)."""
        raise NotImplementedError("A1.4")

    def avancar(self, livro_id: str, posicao: Posicao, *, forcar: bool = False) -> None:
        """Nova posição; grava no máximo 1×/``INTERVALO_S`` (``forcar`` = agora)."""
        raise NotImplementedError("A1.4")

    def registrar_sessao(self, registro: dict[str, Any]) -> None:
        """Uma linha no ``audiolivro.jsonl`` (A10)."""
        raise NotImplementedError("A1.4")
