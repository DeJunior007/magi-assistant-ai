"""Leitor de EPUB (tarefa A1.1; spec §1, requirements A1–A2).

OPF → spine → XHTML, só ``zipfile`` + ``xml.etree`` + ``html.parser``. Pula ``nav``/``toc`` e notas
(``epub:type="footnote|endnote"``); ``<h*>`` vira parágrafo título; itálico marcado para A1.2.
Metadados: título, autor, idioma (``dc:language``).
"""

from __future__ import annotations

from pathlib import Path

from magi.audiolivro.contratos import Capitulo, Livro


class EpubInvalido(ValueError):
    """Arquivo que não é EPUB legível (zip/OPF quebrado)."""


def metadados(caminho: Path) -> Livro:
    """``Livro`` sem extrair o texto todo (título, autor, idioma, nº de capítulos, caracteres)."""
    raise NotImplementedError("A1.1")


def capitulo(caminho: Path, n: int) -> Capitulo:
    """Capítulo ``n`` (0 = primeiro item de leitura do spine) com parágrafos e frases."""
    raise NotImplementedError("A1.1")
