"""Biblioteca de livros (tarefa A1.4; requirements A1, A1.1, D3).

Varre ``[audiolivro] pasta`` (``~/Livros``, criada se faltar), cache do índice em
``cache_dir/indice.json`` por mtime; ``achar`` casa o título falado sem acento, sem artigos e por
tokens. Ambíguo = duas notas a < 0,1 (ela pergunta qual, A1.1).
"""

from __future__ import annotations

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Livro

#: Diferença de nota abaixo da qual dois livros contam como ambíguos (A1.1).
AMBIGUO_DELTA = 0.1


class Biblioteca:
    def __init__(self, cfg: ConfigAudiolivro) -> None:
        self.cfg = cfg

    def livros(self) -> list[Livro]:
        """Todos os livros da pasta (EPUB e PDF), do cache quando o mtime não mudou."""
        raise NotImplementedError("A1.4")

    def achar(self, fala: str) -> list[tuple[Livro, float]]:
        """Livros que casam com o título falado, nota decrescente (0–1)."""
        raise NotImplementedError("A1.4")

    @staticmethod
    def ambiguo(achados: list[tuple[Livro, float]]) -> bool:
        """``True`` quando os dois primeiros estão a menos de ``AMBIGUO_DELTA``."""
        raise NotImplementedError("A1.4")
