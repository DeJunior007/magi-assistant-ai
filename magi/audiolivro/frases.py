"""Parágrafo → frases (tarefa A1.1): abreviações PT/EN (Sr., Dra., etc., Mr., Dr.), reticências,
travessão; não quebra dentro de aspas abertas. Nunca muda o texto (A9): ``" ".join`` das frases
reconstrói o parágrafo normalizado.
"""

from __future__ import annotations


def dividir(texto: str) -> tuple[str, ...]:
    """Frases do parágrafo, na ordem."""
    raise NotImplementedError("A1.1")
