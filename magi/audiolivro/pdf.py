"""Leitor de PDF de texto com ``pymupdf`` (tarefa A1.1; D6; spec §1, requirements A1.2, A2).

Texto por blocos na ordem de leitura; junta hifenização; tira linhas que repetem em ≥ 60% das
páginas no topo/rodapé e números de página; capítulo por linha-título ou, sem achar, blocos de 10
páginas. Menos de 200 caracteres em 5 páginas → ``SemTexto`` (escaneado; A1.2). Idioma por
contagem de palavras-função PT/EN.
"""

from __future__ import annotations

from pathlib import Path

from magi.audiolivro.contratos import Capitulo, Livro


class SemTexto(ValueError):
    """PDF sem camada de texto (escaneado): não lê e não gasta nada (A1.2)."""


def metadados(caminho: Path) -> Livro:
    """``Livro`` do PDF (título/autor do metadado ou do nome do arquivo, idioma, capítulos)."""
    raise NotImplementedError("A1.1")


def capitulo(caminho: Path, n: int) -> Capitulo:
    """Capítulo ``n`` (0 = primeiro); ``Capitulo.paginas`` = páginas reais do trecho."""
    raise NotImplementedError("A1.1")
