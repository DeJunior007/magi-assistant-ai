"""Contratos das reações da Condessa (spec §2). Dono: R0.1.

Só tipos, sem lógica: os detectores emitem ``Disparo``, o catálogo guarda ``Def`` (sequência de
``Passo``), o governador escolhe uma ``Def`` e o ``Reactor`` entrega ao retrato um passo por vez.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

# ID do asset de efeito (checklist D*) -> nome do efeito desenhado pelo retrato
EFEITO: dict[str, str] = {
    "D1": "blush", "D2": "sweat", "D3": "zz", "D4": "question", "D5": "bang",
    "D6": "notes", "D7": "tear", "D8": "vein", "D9": "sparkle",
}

# extras de corpo aceitos em ``Passo.corpo`` (os com ":" levam argumento: "braco:P9", "iris:up")
CORPO = ("bob", "sway", "tails", "fone_on", "fone_off", "braco:", "iris:")


@dataclass(frozen=True)
class Passo:
    ms: int  # duração
    eyes: str | None = None  # B*/F* (None = do estado)
    mouth: str | None = None  # C*/V*
    look: str | None = None  # painel (LOOK_DIRS) ou None
    efeitos: tuple[str, ...] = ()  # nomes de EFEITO (até 3)
    corpo: tuple[str, ...] = ()  # "bob", "sway", "tails", "fone_on", "fone_off", "braco:P9", "iris:<olhar>"


class Classe(StrEnum):
    """Classes de uma reação (uma reação pode ter várias)."""

    PASSIVA = "passiva"
    RARA = "rara"
    DIARIA = "diaria"
    SONO = "sono"
    ZOEIRA = "zoeira"
    COBRANCA = "cobranca"
    SISTEMA = "sistema"
    VITORIA = "vitoria"
    VOLTA = "volta"
    MUSICA = "musica"
    TEMPO = "tempo"
    PEDRO = "pedro"
    NOTURNA = "noturna"


@dataclass(frozen=True)
class Def:
    """Definição de uma reação do catálogo."""

    chave: str
    n: int | str  # Nº da planilha (1–90) ou "I7"
    nome: str
    passos: tuple[Passo, ...]  # 1..4
    classes: frozenset[Classe]
    mood: str = "calm"  # fundo
    prio: int = 1  # dentro da mesma classe
    cooldown_s: float = 600.0
    sinal: str | None = None  # "A".."F", "fan", "restart", "capturas", "datas", "P13"; None = já roda
    fala: str | None = None  # chave em [falas.*] do gosto; None = só rosto
    variante: str | None = None  # variante de uma chave atual (spec §1); None = reação própria
    substituida: bool = False  # 49 e 68: fora de ATIVAS

    @property
    def ms(self) -> int:
        """Duração total da sequência."""
        return sum(p.ms for p in self.passos)


@dataclass(frozen=True)
class Disparo:
    """Evento de um detector: pede a reação ``chave`` (e ``variante``) por ``motivo``."""

    chave: str
    motivo: str
    variante: str | None = None
    fmt: dict = field(default_factory=dict)
