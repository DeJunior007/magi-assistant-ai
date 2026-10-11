"""Espera viva: frase de espera local por tópico (specs/espera-viva, design §3).

Módulo puro, sem I/O fora do ``Catalogo.load``. O turno (``TurnMachine._think``) usa:

- ``EsperaCfg.from_raw`` — seção ``[espera]`` do ``config.toml`` (spec §5);
- ``Catalogo.load`` — ``magi/core/espera.yaml`` (tópicos → frases e moldes, spec §3.1);
- ``topico`` / ``demorado`` — tópico do pedido e se ele parece demorado (D2: só em pedido
  demorado há frase de espera, spec §3.3);
- ``Cota`` + ``escolher`` — a frase do turno ou ``None`` (R3.6);
- ``mesma_espera`` — a frase interina do modelo é só "espera vazia"? (R3.4);
- ``honesta`` — linter de honestidade (R4, spec §4).

E0.1 deixa ``EsperaCfg`` pronto e o resto como stub com a assinatura final; cada stub diz a tarefa
dona.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from magi.common.config import ConfigError

SECTION = "espera"


def _bool(raw: Mapping[str, Any], key: str, default: bool) -> bool:
    v = raw.get(key, default)
    if not isinstance(v, bool):
        raise ConfigError(f"[{SECTION}] {key}: esperado true/false, veio {v!r}")
    return v


def _int(raw: Mapping[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    v = raw.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ConfigError(f"[{SECTION}] {key}: esperado inteiro em {lo}..{hi}, veio {v!r}")
    return v


@dataclass(frozen=True, slots=True)
class EsperaCfg:
    """Seção ``[espera]`` (spec §5). Seção ausente → padrões."""

    frase: bool = True  # R3: frase de espera local
    so_demorado: bool = True  # D2: frase só em pedido demorado (tópico/sinal, spec §3.3)
    frase_apos_ms: int = 700  # espera após a transcrição antes da frase
    lotes: bool = True  # R5.1–R5.4
    lotes_max: int = 3  # lotes por turno (D3)
    lotes_frases_max: int = 6  # frases faladas no turno: lotes + resposta final (D3)
    ferramentas_paralelo: bool = True  # R5.5

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any] | None) -> EsperaCfg:
        """Lê a seção ``[espera]`` (o mapeamento da seção, não o config inteiro).

        Chave desconhecida ou valor inválido → ``ConfigError`` com o nome da chave.
        """
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise ConfigError(f"[{SECTION}] deve ser uma tabela, veio {type(raw).__name__}")
        known = set(cls.__dataclass_fields__)
        for key in raw:
            if key not in known:
                raise ConfigError(f"[{SECTION}] chave desconhecida: {key!r}")
        d = cls()
        cfg = cls(
            frase=_bool(raw, "frase", d.frase),
            so_demorado=_bool(raw, "so_demorado", d.so_demorado),
            frase_apos_ms=_int(raw, "frase_apos_ms", d.frase_apos_ms, 0, 10_000),
            lotes=_bool(raw, "lotes", d.lotes),
            lotes_max=_int(raw, "lotes_max", d.lotes_max, 1, 10),
            lotes_frases_max=_int(raw, "lotes_frases_max", d.lotes_frases_max, 2, 20),
            ferramentas_paralelo=_bool(raw, "ferramentas_paralelo", d.ferramentas_paralelo),
        )
        return cfg


@dataclass(frozen=True, slots=True)
class Topico:
    """Um tópico do catálogo (spec §3.1)."""

    nome: str
    palavras: tuple[str, ...] = ()
    frases: tuple[str, ...] = ()
    moldes: tuple[str, ...] = ()  # com ``{jogo}``


@dataclass(frozen=True, slots=True)
class Catalogo:
    """``magi/core/espera.yaml`` (spec §3.1): tópicos em ordem, ``geral`` por último."""

    topicos: tuple[Topico, ...] = ()
    demorados: frozenset[str] = frozenset()  # D2: tópicos que contam como pedido demorado
    sinais_demora: tuple[str, ...] = ()  # D2: prefixos de palavra que indicam ferramenta/demora
    vetadas: frozenset[str] = frozenset()  # do yaml ∪ ``condessa-gosto.toml [espera] vetadas``

    @classmethod
    def load(cls, path: Path, gosto: Path | None = None) -> Catalogo:
        """Lê o catálogo e junta as vetadas do gosto (caminho injetável). Tarefa E2.2."""
        raise NotImplementedError("E2.2")


def topico(cat: Catalogo, texto: str) -> str:
    """Tópico do pedido por prefixo de palavra, sem acento; sem acerto → ``geral`` (spec §3.2).
    Tarefa E2.2."""
    raise NotImplementedError("E2.2")


def demorado(cat: Catalogo, texto: str) -> bool:
    """D2: o pedido parece demorado? Tópico em ``cat.demorados`` ou sinal de ``cat.sinais_demora``
    no texto (spec §3.3). Tarefa E2.2."""
    raise NotImplementedError("E2.2")


@dataclass(slots=True)
class Cota:
    """Cota da frase de espera por satélite (R3.6, spec §3.3): sem repetir as 2 últimas; depois
    de 2 turnos de agente seguidos com frase, o 3º não tem. Tarefa E2.2."""

    ultimas: list[str] = field(default_factory=list)
    seguidas: int = 0

    def livre(self) -> bool:
        """Este turno pode ter frase (folga)? Tarefa E2.2."""
        raise NotImplementedError("E2.2")

    def registrar(self, frase: str | None) -> None:
        """Fim de um turno de agente: ``frase`` dita ou ``None``. Tarefa E2.2."""
        raise NotImplementedError("E2.2")


def escolher(
    cat: Catalogo,
    texto: str,
    cota: Cota,
    rng: random.Random,
    *,
    jogo: str | None = None,
    continuacao: bool = False,
    so_demorado: bool = True,
) -> str | None:
    """A frase de espera do turno, já preenchida (molde com ``{jogo}`` só no tópico ``jogo``), ou
    ``None`` (pedido não demorado com ``so_demorado``, continuação curta, folga, tudo repetido ou
    vetado). Não registra na cota. Tarefa E2.2."""
    raise NotImplementedError("E2.2")


def mesma_espera(frase: str) -> bool:
    """R3.4: frase só de "espera vazia" (≤ 8 palavras, prefixo da spec §3.4). Tarefa E2.2."""
    raise NotImplementedError("E2.2")


def honesta(frase: str) -> list[str]:
    """R4: violações do linter (spec §4); lista vazia = aprovada. Tarefa E2.2."""
    raise NotImplementedError("E2.2")


__all__: Sequence[str] = (
    "Catalogo",
    "Cota",
    "EsperaCfg",
    "Topico",
    "demorado",
    "escolher",
    "honesta",
    "mesma_espera",
    "topico",
)
