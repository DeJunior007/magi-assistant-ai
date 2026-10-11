"""Pose de pensar da Condessa (espera viva, spec §2). Puro, sem Qt.

``pose(desde_s, tool, lote, tem)`` diz o olhar, a inclinação, os efeitos e o corpo do rosto
enquanto ela pensa: etapa ``hm`` → ``pensando`` → ``concentrada`` pelo tempo, olhar de painel pela
ferramenta em curso e etapa mínima ``pensando`` depois de um lote. O retrato (E1.2) só troca o
``_think_look`` e o ``tilt`` por essa ``Pose``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Pose:
    etapa: str  # "hm" | "pensando" | "concentrada"
    ciclo: tuple[tuple[str, float, float], ...]  # (olhos, dx, dy) como THINK_CYCLE
    passo_s: float  # tempo em cada olhar do ciclo
    tilt: float  # graus a mais (hoje THINK_TILT 2.2)
    efeitos: tuple[str, ...] = ()  # "dots", "question"
    corpo: tuple[str, ...] = ()  # "sway", "bob_lento", "braco:P14"
    look: str | None = None  # painel (chave de LOOK_DIRS) quando há ferramenta


def pose(desde_s: float, tool: str | None, lote: int, tem: Callable[[str], bool]) -> Pose:
    """Pose de pensar ``desde_s`` segundos depois do 1º ``thinking`` (ou do aviso do lote).
    ``tool``: ferramenta em curso (``THINK_TOOLS``) ou ``None``; ``lote``: último lote falado
    (0 = nenhum); ``tem("eyes/X.png")``: o asset existe? Tarefa E1.1 (spec §2.1–§2.3)."""
    raise NotImplementedError("E1.1")
