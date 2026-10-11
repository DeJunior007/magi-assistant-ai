"""Contratos do audiolivro (tarefa A0.1; spec §1, design §2).

Tudo imutável. ``Trecho.texto`` é **exatamente** o texto do livro (A9): a marcação só escolhe voz.
``Livro.capitulo(n)`` extrai sob demanda pelo leitor do formato (``epub``/``pdf``, A1.1) e guarda
os 3 últimos capítulos extraídos (LRU).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

Formato = Literal["epub", "pdf"]
Genero = Literal["f", "m"]
Idade = Literal["crianca", "jovem", "adulto", "idoso"]
GENEROS: tuple[str, ...] = ("f", "m")
IDADES: tuple[str, ...] = ("crianca", "jovem", "adulto", "idoso")


class Tipo(StrEnum):
    NARRACAO = "narracao"
    FALA = "fala"
    PENSAMENTO = "pensamento"
    TITULO = "titulo"


class Emocao(StrEnum):
    NEUTRA = "neutra"
    ALEGRE = "alegre"
    TRISTE = "triste"
    TENSA = "tensa"
    RAIVA = "raiva"
    MEDO = "medo"
    SUSSURRO = "sussurro"
    GRITO = "grito"
    IRONIA = "ironia"
    CARINHO = "carinho"


@dataclass(frozen=True)
class Paragrafo:
    n: int
    frases: tuple[str, ...]

    @property
    def texto(self) -> str:
        return " ".join(self.frases)


@dataclass(frozen=True)
class Capitulo:
    n: int
    titulo: str
    paragrafos: tuple[Paragrafo, ...]
    paginas: float  # PDF: páginas reais; EPUB: caracteres / chars_por_pagina

    @property
    def caracteres(self) -> int:
        return sum(len(p.texto) for p in self.paragrafos)


def livro_id(caminho: Path, tamanho: int) -> str:
    """``sha1`` do caminho + tamanho, 12 caracteres (spec §1)."""
    return hashlib.sha1(f"{caminho}\0{tamanho}".encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Livro:
    id: str
    caminho: Path
    titulo: str
    autor: str | None
    idioma: str  # idioma do texto ("pt-br", "en", ...); a voz é sempre a dela (D5)
    formato: Formato
    capitulos: int
    caracteres: int

    def capitulo(self, n: int) -> Capitulo:
        """Capítulo ``n`` (0 = primeiro), extraído sob demanda; LRU dos 3 últimos."""
        return _extrair(self.formato, self.caminho, self.id, n)


@lru_cache(maxsize=3)
def _extrair(formato: Formato, caminho: Path, _id: str, n: int) -> Capitulo:
    if formato == "epub":
        from magi.audiolivro import epub as leitor
    else:
        from magi.audiolivro import pdf as leitor  # type: ignore[no-redef]
    return leitor.capitulo(caminho, n)


@dataclass(frozen=True)
class Trecho:
    texto: str  # exatamente o texto do livro (A9)
    tipo: Tipo = Tipo.NARRACAO
    emocao: Emocao = Emocao.NEUTRA
    falante: str | None = None
    genero: Genero | None = None
    idade: Idade | None = None
    par: int = 0  # posição (o capítulo vem da Leitura)
    frase: int = 0


@dataclass(frozen=True)
class Marca:
    """Uma linha do JSON do Qwen (A1.3): ``i`` é o índice do trecho no parágrafo ``par``. Nunca
    traz texto."""

    par: int
    i: int
    tipo: Tipo
    emocao: Emocao
    falante: str | None = None
    genero: Genero | None = None
    idade: Idade | None = None


@dataclass(frozen=True)
class OpcoesVoz:
    """Opções do Kokoro para uma parte. ``voice``/``speed``/``lang`` vão para
    ``GuardedTts.com_opcoes`` (sem os ``None``); ``pausa_ms`` vira silêncio depois da parte no
    ``say_parts`` (A2.1) e não vai ao ``CallCtx``."""

    voice: str | None = None
    speed: float | None = None
    lang: str | None = None
    pausa_ms: int = 0

    def tts(self) -> dict[str, object]:
        """O que vai para ``com_opcoes(**...)``."""
        d = {"voice": self.voice, "speed": self.speed, "lang": self.lang}
        return {k: v for k, v in d.items() if v is not None}


@dataclass(frozen=True)
class Posicao:
    cap: int
    par: int
    frase: int
    velocidade: float = 1.0


@dataclass(frozen=True)
class Estimativa:
    """Tempo de leitura (spec §4). Custo de API é sempre 0 (D1/D2)."""

    paginas_capitulo: float
    minutos_capitulo: float
    minutos_livro_restante: float
