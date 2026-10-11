"""Refino da marcação pelo Qwen local (tarefa A1.3; D2; spec §2, requirements A3.1).

Por capítulo, manda os parágrafos numerados e os trechos das regras; o Qwen devolve só JSON de
``Marca`` (nunca texto); valida e mescla. Roda em segundo plano à frente da leitura e nunca a
bloqueia; liga o ``magi-qwen`` pelo ``ContainerRuntime`` (``magi/learning/runtime.py``) quando
preciso. Cache por livro/capítulo em ``cache_dir/<id>/marcas-<cap>.json``. Qwen fora do ar,
timeout ou JSON inválido → ``None`` (vale a regra). Sem custo; nunca LLM pago.
"""

from __future__ import annotations

from typing import Any

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Capitulo, Livro, Marca, Trecho


def validar(dados: Any, trechos: list[list[Trecho]]) -> list[Marca]:
    """Marcas válidas do JSON (índices existentes, enums válidos); o resto é descartado."""
    raise NotImplementedError("A1.3")


def mesclar(trechos: list[list[Trecho]], marcas: list[Marca]) -> list[list[Trecho]]:
    """Aplica as marcas nos trechos das regras sem mudar nenhum ``texto`` (A9)."""
    raise NotImplementedError("A1.3")


class RefinoQwen:
    """``modelo``: ``LearningModel`` (``complete(system, user, schema)``); ``runtime``: o
    ``ContainerRuntime``/``NullRuntime`` do ``magi-qwen``. Os dois injetados (testes: falsos)."""

    def __init__(self, cfg: ConfigAudiolivro, modelo: Any, runtime: Any) -> None:
        self.cfg = cfg
        self.modelo = modelo
        self.runtime = runtime

    def pronto(self, livro: Livro, cap: int) -> list[list[Trecho]] | None:
        """Trechos refinados do capítulo se o cache já existe; ``None`` = use as regras."""
        raise NotImplementedError("A1.3")

    async def refinar(
        self, livro: Livro, capitulo: Capitulo, trechos: list[list[Trecho]]
    ) -> list[list[Trecho]] | None:
        """Refina e grava no cache; ``None`` quando o Qwen não respondeu direito."""
        raise NotImplementedError("A1.3")

    async def parar(self) -> None:
        """Para o container se foi o refino que o ligou."""
        raise NotImplementedError("A1.3")
