"""Tokens de cor do handoff "wired" e tingimento das unidades MAGI pelo LED (R23.6)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor

BG = "#09080d"
PANEL = "#0f0e15"
LINE = "#26232f"
LINE_STRONG = "#3a3646"
SEG_OFF = "#1d1b25"
TEXT = "#d8d3e6"
TEXT_DIM = "#8f89a6"
DECO = "#5c576b"
CPU = "#b392f0"  # Melchior
GPU = "#5fd38d"  # Balthasar
RAM = "#c9c4d6"  # Casper
WARN = "#e8b04a"
HOT = "#e5695b"
# cores auxiliares do canvas (cenário, botões)
SCENE_BG = "#13111a"
WIRE = "#050408"
BUTTON = "#14121b"
BUTTON_LINE = "#2f2b3a"

TOKENS = {
    "bg": BG, "panel": PANEL, "line": LINE, "line-strong": LINE_STRONG, "seg-off": SEG_OFF,
    "text": TEXT, "text-dim": TEXT_DIM, "deco": DECO, "cpu": CPU, "gpu": GPU, "ram": RAM,
    "warn": WARN, "hot": HOT,
}

# borda e fundo de cada unidade com o LED desligado (valores do canvas)
UNIT_OFF = {
    CPU: ("#3b2f55", "#141120"),
    GPU: ("#244a33", "#0f1712"),
    RAM: ("#2f2b3a", "#121118"),
}

_cache: dict[str, QColor] = {}


def color(c: str | QColor) -> QColor:
    """QColor a partir de um token ("text-dim"), hex ("#rrggbb"/"#rrggbbaa") ou QColor."""
    if isinstance(c, QColor):
        return QColor(c)
    q = _cache.get(c)
    if q is None:
        s = TOKENS.get(c, c)
        if len(s) == 9 and s.startswith("#"):  # #rrggbbaa (CSS), o QColor lê #aarrggbb
            q = QColor(s[:7])
            q.setAlpha(int(s[7:], 16))
        else:
            q = QColor(s)
        if not q.isValid():
            raise ValueError(f"cor inválida: {c!r}")
        _cache[c] = q
    return QColor(q)


def alpha(c: str | QColor, a: int) -> QColor:
    q = color(c)
    q.setAlpha(a)
    return q


@dataclass(frozen=True)
class Tint:
    color: QColor  # texto/nome da unidade
    border: QColor
    bg: QColor
    seg: QColor  # segmentos acesos


def tint(base: str | QColor, rgb: str | QColor | None, led_on: bool) -> Tint:
    """Cores de uma unidade MAGI. LED ligado: rgb no texto e segmentos, borda rgb+0x88, fundo rgb+0x14.

    Desligado: a cor própria da unidade, com borda/fundo do canvas (ou derivados da base).
    Sem cor do OpenRGB (`rgb=None`), comporta-se como desligado.
    """
    if led_on and rgb is not None:
        c = color(rgb)
        c.setAlpha(255)
        return Tint(QColor(c), alpha(c, 0x88), alpha(c, 0x14), QColor(c))
    b = color(base)
    key = b.name()
    if key in UNIT_OFF:
        border, bg = (color(x) for x in UNIT_OFF[key])
    else:
        border, bg = mix(b, PANEL, 0.3), mix(b, PANEL, 0.06)
    return Tint(QColor(b), border, bg, QColor(b))


def mix(a: str | QColor, b: str | QColor, t: float) -> QColor:
    """Mistura opaca: `t` de `a` sobre `b` (0 = b, 1 = a)."""
    ca, cb = color(a), color(b)
    return QColor(round(ca.red() * t + cb.red() * (1 - t)), round(ca.green() * t + cb.green() * (1 - t)),
                  round(ca.blue() * t + cb.blue() * (1 - t)))
