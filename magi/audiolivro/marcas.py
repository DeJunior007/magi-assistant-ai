"""Marcação por regras locais (tarefa A1.2; spec §2, requirements A3).

Parágrafo → ``Trecho``s (narração/fala/pensamento/título, emoção, falante, gênero, idade) por
travessão, aspas, verbos de elocução (``verbos.toml``) e pontuação. Roda sempre (D2); o Qwen
(A1.3) só refina. A concatenação dos ``texto`` com espaços é o parágrafo (A9).
"""

from __future__ import annotations

from magi.audiolivro.contratos import Paragrafo, Trecho


def marcar(paragrafo: Paragrafo, idioma: str) -> list[Trecho]:
    """Trechos do parágrafo no idioma do **texto** (``Livro.idioma``), na ordem."""
    raise NotImplementedError("A1.2")
