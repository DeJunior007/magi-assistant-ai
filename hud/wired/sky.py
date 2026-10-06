"""Dia e noite do cenário "wired": paleta do céu pela hora local, sem brilho.

Tudo fica nos tons apagados do tema (roxo/cinza): de dia o céu só clareia um pouco e ganha um
disco de sol fraco; ao amanhecer e ao entardecer o horizonte puxa para um rosado escuro; à noite
volta o céu atual, com a lua e mais janelas acesas. Entre as chaves a paleta é interpolada e
arredondada a ``STEP_MIN`` minutos, para os caches de fundo mudarem poucas vezes por hora.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtGui import QColor

STEP_MIN = 5


@dataclass(frozen=True)
class Sky:
    top: str  # céu em cima
    horizon: str  # céu na linha dos prédios
    bg: str  # fundo da tela de espera
    buildings: float  # 0 = prédios como à noite, 1 = misturados ao horizonte (de dia)
    lights: float  # fração das janelas acesas
    moon: float  # opacidade da lua
    sun: float  # opacidade do disco de sol (fraco)
    fog: float  # opacidade da névoa que passa

    @property
    def key(self) -> tuple:
        return (self.top, self.horizon, self.bg, round(self.buildings, 2), round(self.lights, 2),
                round(self.moon, 2), round(self.sun, 2), round(self.fog, 3))


NIGHT = Sky("#0f0d16", "#17141f", "#09080d", 0.0, 0.8, 1.0, 0.0, 0.035)
DAWN = Sky("#16131f", "#2a2132", "#0c0a10", 0.15, 0.45, 0.35, 0.35, 0.06)
DAY = Sky("#1c1928", "#29253a", "#0f0d15", 0.3, 0.12, 0.0, 0.55, 0.045)
DUSK = Sky("#171320", "#2e2032", "#0c0a10", 0.15, 0.5, 0.2, 0.3, 0.055)

# (minuto do dia, paleta)
KEYS: tuple[tuple[int, Sky], ...] = (
    (0, NIGHT), (5 * 60, NIGHT), (6 * 60, DAWN), (7 * 60 + 30, DAY), (17 * 60, DAY),
    (18 * 60 + 15, DUSK), (19 * 60 + 15, NIGHT), (24 * 60, NIGHT),
)


def _mix_hex(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    r = round(ca.red() + (cb.red() - ca.red()) * t)
    g = round(ca.green() + (cb.green() - ca.green()) * t)
    bl = round(ca.blue() + (cb.blue() - ca.blue()) * t)
    return QColor(r, g, bl).name()


def mix(a: Sky, b: Sky, t: float) -> Sky:
    def f(x: float, y: float) -> float:
        return x + (y - x) * t

    return Sky(_mix_hex(a.top, b.top, t), _mix_hex(a.horizon, b.horizon, t), _mix_hex(a.bg, b.bg, t),
               f(a.buildings, b.buildings), f(a.lights, b.lights), f(a.moon, b.moon), f(a.sun, b.sun),
               f(a.fog, b.fog))


def sky_at(when: datetime) -> Sky:
    """Paleta para a hora local de ``when`` (arredondada a ``STEP_MIN`` minutos)."""
    minute = (when.hour * 60 + when.minute) // STEP_MIN * STEP_MIN
    for (m0, s0), (m1, s1) in zip(KEYS, KEYS[1:], strict=False):
        if m0 <= minute <= m1:
            return s0 if m1 == m0 else mix(s0, s1, (minute - m0) / (m1 - m0))
    return NIGHT


def building(base: str, sky: Sky) -> str:
    """Cor de um prédio: a de noite, misturada ao horizonte conforme ``sky.buildings``."""
    return _mix_hex(base, sky.horizon, sky.buildings * 0.5)

#: Cor da névoa que passa no "cam 01" (com a opacidade de ``Sky.fog``).
FOG_TINT = "#b8b0d0"
