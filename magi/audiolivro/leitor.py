"""Leitura em curso (tarefa A2.2; design §3–§4, requirements A5, A6.2, A8).

``partes()`` gera ``(texto, OpcoesVoz)`` frase a frase: regras sempre, marcas do Qwen quando o
cache do capítulo já existe (nunca espera), voz pelo ``Elenco``. Cache de PCM dos 3 últimos
parágrafos; ``interrompida()`` pausa na frase em curso.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from magi.audiolivro.contratos import Livro, OpcoesVoz, Posicao

Estado = Literal["lendo", "pausada", "parada"]


class Leitura:
    estado: Estado = "parada"

    def abrir(self, livro: Livro, posicao: Posicao | None = None) -> None:
        raise NotImplementedError("A2.2")

    def partes(self) -> AsyncIterator[tuple[str, OpcoesVoz]]:
        raise NotImplementedError("A2.2")

    def interrompida(self) -> None:
        raise NotImplementedError("A2.2")

    def voltar(self, n: int = 1) -> None:
        raise NotImplementedError("A2.2")

    def pular(self, n: int = 1) -> None:
        raise NotImplementedError("A2.2")

    def capitulo(self, *, delta: int | None = None, n: int | None = None) -> None:
        raise NotImplementedError("A2.2")

    def velocidade(self, delta: float) -> float:
        raise NotImplementedError("A2.2")
