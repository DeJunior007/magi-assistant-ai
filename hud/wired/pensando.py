"""Pose de pensar da Condessa (espera viva, spec §2). Puro, sem Qt.

``pose(desde_s, tool, lote, tem)`` diz o olhar, a inclinação, os efeitos e o corpo do rosto
enquanto ela pensa: etapa ``hm`` → ``pensando`` → ``concentrada`` pelo tempo, olhar de painel pela
ferramenta em curso e etapa mínima ``pensando`` depois de um lote. O retrato (E1.2) só troca o
``_think_look`` e o ``tilt`` por essa ``Pose``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# cópias de ``portrait.THINK_*`` (sem importar Qt); o teste confere que batem
THINK_CYCLE: tuple[tuple[str, float, float], ...] = (
    ("B13", 4.0, -3.0), ("F4", 5.0, -3.0), ("B13", 4.0, -3.0), ("F6", 6.0, 0.0),
    ("F1", -6.0, 0.0), ("F7", 0.0, 3.0))
THINK_STEP = 1.3
THINK_TILT = 2.2

HM_ATE_S = 1.2  # até aqui: "hm" (olhar para cima, fixo)
PENSANDO_ATE_S = 3.5  # até aqui: "pensando"; depois "concentrada"
OLHAR_PAINEL_S = 1.5  # quanto dura o olhar de painel depois que a ferramenta muda (o retrato cronometra)

_HM_CICLO = (("F4", 5.0, -3.0),)
_CONC_CICLO = (("B18", 4.0, -3.0), ("B13", 4.0, -3.0))
_CONC_SEM_B18 = (("B13", 4.0, -3.0), ("F7", 0.0, 3.0))

# ferramenta → painel (chave de ``LOOK_DIRS[tela]``); fora daqui não há olhar (spec §2.3)
TOOL_PAINEL = {
    "news_query": "radio",
    "spotify_play": "player", "spotify_pick": "player", "spotify_control": "player",
    "open_game": "fps", "close_game": "fps", "game_help": "fps", "steam_game": "fps",
    "rgb": "led",
}


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
    if desde_s < HM_ATE_S and lote < 1:
        etapa, ciclo, passo, tilt, efeitos, corpo = "hm", _HM_CICLO, HM_ATE_S, 3.0, (), ()
    elif desde_s < PENSANDO_ATE_S:
        etapa, ciclo, passo, tilt = "pensando", THINK_CYCLE, THINK_STEP, THINK_TILT
        efeitos, corpo = ("dots",), ("sway",)
    else:
        etapa, passo, tilt = "concentrada", 2.0, 1.5
        ciclo = _CONC_CICLO if tem("eyes/B18.png") else _CONC_SEM_B18
        efeitos, corpo = ("dots",), ("bob_lento", "braco:P14")
    ciclo = tuple(c for c in ciclo if tem(f"eyes/{c[0]}.png")) or THINK_CYCLE
    look = TOOL_PAINEL.get(tool) if tool else None
    return Pose(etapa, ciclo, passo, tilt, efeitos, corpo, look)
