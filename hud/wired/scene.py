"""Cenário de fios, postes e prédios das duas telas, em QPixmap cacheado por tamanho e acento.

- `main_scene`: "cam 01" do Painel completo (viewBox 540×500, recorte como `xMidYMid slice`).
- `standby_scene`: tela de espera inteira (1920×1080); poste em x≈1760, fios saindo para
  cima/fora e prédios só abaixo de y≈900 — nada atrás do texto.

Os pixmaps têm `devicePixelRatio = scale`: desenhados num retângulo lógico w×h com o painter
escalado por `scale`, caem 1:1 nos pixels do monitor (sem reamostrar).
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

from .theme import BG, SCENE_BG, WARN, WIRE, color

MAIN_VIEW = (540.0, 500.0)
STANDBY_VIEW = (1920.0, 1080.0)
POLE_X = 1756.0  # poste da tela de espera (x≈1760)
BUILDINGS_TOP = 900.0

# (x, y, w, h, cor)
_MAIN_BUILDINGS = [
    (0, 380, 70, 120, "#1a1823"), (70, 350, 58, 150, "#16141e"), (140, 405, 90, 95, "#1a1823"),
    (300, 330, 64, 170, "#16141e"), (364, 390, 80, 110, "#1a1823"), (455, 300, 85, 200, "#16141e"),
]
# janelinhas acesas: (x, y, opacidade, acento?)
_MAIN_WINDOWS = [(84, 370, .55, False), (104, 398, .35, False), (318, 356, .5, True),
                 (478, 330, .45, False), (500, 372, .3, False)]
_MAIN_POLES = [(166, 40, 8, 460), (112, 78, 116, 5), (124, 104, 92, 4),
               (420, 150, 5, 350), (390, 172, 66, 3), (398, 188, 50, 3)]
# fios: (x0, y0, cx, cy, x1, y1, espessura)
_MAIN_WIRES = [
    (-10, 60, 60, 110, 114, 80, 1.6), (-10, 92, 60, 140, 126, 106, 1.4),
    (114, 80, 260, 150, 392, 173, 1.5), (228, 80, 320, 140, 456, 173, 1.5),
    (126, 106, 270, 172, 400, 189, 1.3), (216, 106, 330, 170, 448, 189, 1.3),
    (456, 173, 500, 200, 560, 196, 1.3), (448, 189, 500, 220, 560, 222, 1.2),
]

_SB_BUILDINGS = [
    (1040, 960, 110, 120, "#121019"), (1150, 935, 80, 145, "#0f0e15"),
    (1250, 975, 150, 105, "#121019"), (1420, 920, 96, 160, "#0f0e15"),
    (1530, 955, 140, 125, "#121019"), (1690, 900, 230, 180, "#0f0e15"),
]
_SB_WINDOWS = [(1170, 955, .35, False), (1446, 944, .45, True), (1730, 930, .3, False)]
_SB_POLE = "#1a1823"
_SB_POLES = [(POLE_X, 40, 10, 1040), (1696, 96, 130, 6), (1710, 126, 102, 5)]
_SB_WIRES = [
    (1696, 99, 1600, 150, 1480, -10, 2), (1710, 128, 1580, 190, 1400, -10, 2),
    (1826, 99, 1880, 140, 1940, 128, 2), (1812, 128, 1870, 175, 1940, 168, 2),
]


def _new_pixmap(w: float, h: float, scale: float, fill: str) -> tuple[QPixmap, QPainter]:
    pm = QPixmap(max(1, round(w * scale)), max(1, round(h * scale)))
    pm.setDevicePixelRatio(scale)
    pm.fill(color(fill))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    return pm, p


def _draw(p: QPainter, buildings, windows, win_size, poles, pole_color, wires, wire_color,
          accent: QColor, moon: tuple | None = None) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    if moon:
        cx, cy, r, c = moon
        p.setBrush(color(c))
        p.drawEllipse(QPointF(cx, cy), r, r)
    for x, y, w, h, c in buildings:
        p.fillRect(QRectF(x, y, w, h), color(c))
    ww, wh = win_size
    for x, y, op, acc in windows:
        c = QColor(accent) if acc else color(WARN)
        c.setAlphaF(op)
        p.fillRect(QRectF(x, y, ww, wh), c)
    for x, y, w, h in poles:
        p.fillRect(QRectF(x, y, w, h), color(pole_color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    for x0, y0, cx, cy, x1, y1, sw in wires:
        path = QPainterPath(QPointF(x0, y0))
        path.quadTo(QPointF(cx, cy), QPointF(x1, y1))
        p.setPen(QPen(color(wire_color), sw))
        p.drawPath(path)


@lru_cache(maxsize=8)
def _main(w: int, h: int, accent: str, scale: float) -> QPixmap:
    pm, p = _new_pixmap(w, h, scale, SCENE_BG)
    vw, vh = MAIN_VIEW
    k = max(w / vw, h / vh)  # preserveAspectRatio="xMidYMid slice"
    p.translate((w - vw * k) / 2, (h - vh * k) / 2)
    p.scale(k, k)
    _draw(p, _MAIN_BUILDINGS, _MAIN_WINDOWS, (6, 8), _MAIN_POLES, WIRE, _MAIN_WIRES, WIRE,
          color(accent), moon=(400, 150, 58, "#1c1925"))
    p.end()
    return pm


@lru_cache(maxsize=4)
def _standby(w: int, h: int, accent: str, scale: float) -> QPixmap:
    pm, p = _new_pixmap(w, h, scale, BG)
    vw, vh = STANDBY_VIEW
    k = min(w / vw, h / vh)  # SVG padrão: "xMidYMid meet"
    p.translate((w - vw * k) / 2, (h - vh * k) / 2)
    p.scale(k, k)
    _draw(p, _SB_BUILDINGS, _SB_WINDOWS, (7, 9), _SB_POLES, _SB_POLE, _SB_WIRES, _SB_POLE,
          color(accent))
    p.end()
    return pm


def _key(accent: str | QColor) -> str:
    return color(accent).name()


def main_scene(w: float, h: float, accent: str | QColor = "#b392f0", scale: float = 1.0) -> QPixmap:
    """Cena "cam 01" (fundo #13111a, lua, prédios, postes, fios) para um retângulo lógico w×h."""
    return _main(round(w), round(h), _key(accent), float(scale))


def standby_scene(w: float = 1920, h: float = 1080, accent: str | QColor = "#b392f0",
                  scale: float = 1.0) -> QPixmap:
    """Fundo da tela de espera (bg + poste à direita + prédios na faixa de baixo)."""
    return _standby(round(w), round(h), _key(accent), float(scale))


def standby_text_safe(rect: QRectF) -> bool:
    """True se `rect` (lógico, 1920×1080) não cruza nenhum elemento do cenário da espera."""
    for x, y, w, h, _c in _SB_BUILDINGS:
        if QRectF(x, y, w, h).intersects(rect):
            return False
    for x, y, w, h in _SB_POLES:
        if QRectF(x, y, w, h).intersects(rect):
            return False
    for x0, y0, cx, cy, x1, y1, sw in _SB_WIRES:
        path = QPainterPath(QPointF(x0, y0))
        path.quadTo(QPointF(cx, cy), QPointF(x1, y1))
        if path.controlPointRect().adjusted(-sw, -sw, sw, sw).intersects(rect) and \
                _path_hits(path, rect):
            return False
    return True


def _path_hits(path: QPainterPath, rect: QRectF, steps: int = 64) -> bool:
    return any(rect.contains(path.pointAtPercent(i / steps)) for i in range(steps + 1))


def clear_cache() -> None:
    _main.cache_clear()
    _standby.cache_clear()
