"""Cenário de fios, postes e prédios das duas telas, em QPixmap cacheado por tamanho e acento.

- `main_scene`: "cam 01" do Painel completo (viewBox 540×500, recorte como `xMidYMid slice`).
- `standby_scene`: tela de espera inteira (1920×1080); poste em x≈1760, fios saindo para
  cima/fora e prédios só abaixo de y≈900 — nada atrás do texto.
- `SceneAnimator`: o que se mexe (fios, janelas, névoa, pássaro) por cima do fundo `live=False`.

Dia e noite (`sky.sky_at`): o fundo é cacheado por paleta, que muda no máximo a cada 5 min.

Os pixmaps têm `devicePixelRatio = scale`: desenhados num retângulo lógico w×h com o painter
escalado por `scale`, caem 1:1 nos pixels do monitor (sem reamostrar).
"""

from __future__ import annotations

import math
import random
import time
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

from . import sky
from .sky import Sky
from .theme import SCENE_BG, WARN, WIRE, color

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


def _wire_path(wire: tuple, sway: float = 0.0) -> QPainterPath:
    x0, y0, cx, cy, x1, y1, _sw = wire
    path = QPainterPath(QPointF(x0, y0))
    path.quadTo(QPointF(cx, cy + sway), QPointF(x1, y1))
    return path


def _draw_windows(p: QPainter, windows, win_size, accent: QColor, lit=None) -> None:
    ww, wh = win_size
    for i, (x, y, op, acc) in enumerate(windows):
        if lit is not None and not lit[i]:
            continue
        c = QColor(accent) if acc else color(WARN)
        c.setAlphaF(op)
        p.fillRect(QRectF(x, y, ww, wh), c)


def _draw_wires(p: QPainter, wires, wire_color: str, sways=None) -> None:
    p.setBrush(Qt.BrushStyle.NoBrush)
    for i, wire in enumerate(wires):
        p.setPen(QPen(color(wire_color), wire[6]))
        p.drawPath(_wire_path(wire, sways[i] if sways else 0.0))


def _draw_back(p: QPainter, vw: float, vh: float, sky_: Sky, buildings, poles, pole_color,
               moon: tuple | None, sun: tuple | None, gradient: bool) -> None:
    """Céu (gradiente), sol/lua e prédios e postes: a parte que só muda com a hora."""
    if gradient:
        g = QLinearGradient(0, 0, 0, vh)
        g.setColorAt(0, color(sky_.top))
        g.setColorAt(1, color(sky_.horizon))
        p.fillRect(QRectF(0, 0, vw, vh), g)
    p.setPen(Qt.PenStyle.NoPen)
    if sun and sky_.sun > 0:
        cx, cy, r, c = sun
        q = color(c)
        q.setAlphaF(sky_.sun)
        p.setBrush(q)
        p.drawEllipse(QPointF(cx, cy), r, r)
    if moon and sky_.moon > 0:
        cx, cy, r, c = moon
        q = color(c)
        q.setAlphaF(sky_.moon)
        p.setBrush(q)
        p.drawEllipse(QPointF(cx, cy), r, r)
    for x, y, w, h, c in buildings:
        p.fillRect(QRectF(x, y, w, h), color(sky.building(c, sky_)))
    for x, y, w, h in poles:
        p.fillRect(QRectF(x, y, w, h), color(pole_color))


def _main_transform(p: QPainter, w: float, h: float) -> None:
    vw, vh = MAIN_VIEW
    k = max(w / vw, h / vh)  # preserveAspectRatio="xMidYMid slice"
    p.translate((w - vw * k) / 2, (h - vh * k) / 2)
    p.scale(k, k)


def _standby_transform(p: QPainter, w: float, h: float) -> None:
    vw, vh = STANDBY_VIEW
    k = min(w / vw, h / vh)  # SVG padrão: "xMidYMid meet"
    p.translate((w - vw * k) / 2, (h - vh * k) / 2)
    p.scale(k, k)


_MAIN_MOON = (400, 150, 58, "#1c1925")
_MAIN_SUN = (285, 118, 36, "#3a3550")


@lru_cache(maxsize=8)
def _main(w: int, h: int, accent: str, scale: float, sky_key: tuple, live: bool) -> QPixmap:
    sky_ = _SKIES[sky_key]
    pm, p = _new_pixmap(w, h, scale, SCENE_BG)
    _main_transform(p, w, h)
    vw, vh = MAIN_VIEW
    _draw_back(p, vw, vh, sky_, _MAIN_BUILDINGS, _MAIN_POLES, WIRE, _MAIN_MOON, _MAIN_SUN,
               gradient=sky_ != sky.NIGHT or not live)
    if live:
        _draw_windows(p, _MAIN_WINDOWS, (6, 8), color(accent))
        _draw_wires(p, _MAIN_WIRES, WIRE)
    p.end()
    return pm


@lru_cache(maxsize=4)
def _standby(w: int, h: int, accent: str, scale: float, sky_key: tuple, live: bool) -> QPixmap:
    sky_ = _SKIES[sky_key]
    pm, p = _new_pixmap(w, h, scale, sky_.bg)
    _standby_transform(p, w, h)
    _draw_back(p, *STANDBY_VIEW, sky_, _SB_BUILDINGS, _SB_POLES, _SB_POLE, None, None, gradient=False)
    if live:
        _draw_windows(p, _SB_WINDOWS, (7, 9), color(accent))
        _draw_wires(p, _SB_WIRES, _SB_POLE)
    p.end()
    return pm


_SKIES: dict[tuple, Sky] = {}


def _sky_key(sky_: Sky | None) -> tuple:
    sky_ = sky_ or sky.NIGHT
    _SKIES[sky_.key] = sky_
    return sky_.key


def _key(accent: str | QColor) -> str:
    return color(accent).name()


def main_scene(w: float, h: float, accent: str | QColor = "#b392f0", scale: float = 1.0,
               sky_: Sky | None = None, live: bool = True) -> QPixmap:
    """Cena "cam 01" (céu, lua/sol, prédios, postes, fios) para um retângulo lógico w×h.
    ``live=False``: sem janelas e fios (o ``SceneAnimator`` desenha por cima)."""
    return _main(round(w), round(h), _key(accent), float(scale), _sky_key(sky_), live)


def standby_scene(w: float = 1920, h: float = 1080, accent: str | QColor = "#b392f0",
                  scale: float = 1.0, sky_: Sky | None = None, live: bool = True) -> QPixmap:
    """Fundo da tela de espera (bg + poste à direita + prédios na faixa de baixo)."""
    return _standby(round(w), round(h), _key(accent), float(scale), _sky_key(sky_), live)


# ---------------------------------------------------------------------------- animação

FPS = 6.0
SWAY = {"main": 1.8, "standby": 2.6}  # amplitude do balanço dos fios (unidades do viewBox)
SWAY_PERIOD = (7.0, 11.0)
TOGGLE_EVERY = (20.0, 50.0)  # uma janela acende/apaga
BIRD_EVERY = (180.0, 480.0)
BIRD_STAY = (40.0, 90.0)
FOG_SPEED = 5.0  # unidades/s
FOG_W, FOG_H, FOG_Y = 300.0, 110.0, 330.0


class SceneAnimator:
    """O que se mexe no cenário: fios balançando, janelas acendendo/apagando aos poucos (mais à
    noite), névoa passando (só no "cam 01") e, de vez em quando, um pássaro pousado num fio.

    Desenha por cima do fundo de ``main_scene``/``standby_scene(live=False)``, no mesmo sistema de
    coordenadas (``paint(p, rect)`` aplica o recorte/escala do viewBox). Redesenha a ``FPS``.
    """

    def __init__(self, kind: str = "main", rng: random.Random | None = None, mono: float | None = None):
        if kind not in ("main", "standby"):
            raise ValueError(kind)
        self.kind = kind
        self.rng = rng or random.Random(f"magi-{kind}")  # semente fixa: o mesmo desenho a cada início
        mono = time.monotonic() if mono is None else mono
        main = kind == "main"
        self.windows = _MAIN_WINDOWS if main else _SB_WINDOWS
        self.win_size = (6, 8) if main else (7, 9)
        self.wires = _MAIN_WIRES if main else _SB_WIRES
        self.wire_color = WIRE if main else _SB_POLE
        self.sky = sky.NIGHT
        self.lit = [False] * len(self.windows)
        self._fill_to_target()
        self.phases = [self.rng.uniform(0, 2 * math.pi) for _ in self.wires]
        self.periods = [self.rng.uniform(*SWAY_PERIOD) for _ in self.wires]
        self.next_toggle = mono + self.rng.uniform(*TOGGLE_EVERY)
        self.bird: tuple[int, float, float] | None = None  # (fio, t na curva, até quando)
        self.next_bird = mono + self.rng.uniform(60.0, 180.0)
        self.fog_x0 = self.rng.uniform(0, 600)
        self._last = -1.0

    # -- estado
    def set_sky(self, sky_: Sky) -> None:
        if sky_ != self.sky:
            self.sky = sky_

    def _target(self) -> int:
        return round(self.sky.lights * len(self.windows))

    def _fill_to_target(self) -> None:
        order = list(range(len(self.windows)))
        self.rng.shuffle(order)
        on = set(order[: self._target()])
        self.lit = [i in on for i in range(len(self.windows))]

    def _toggle(self) -> None:
        on = [i for i, v in enumerate(self.lit) if v]
        off = [i for i, v in enumerate(self.lit) if not v]
        target = self._target()
        if len(on) < target and off:
            self.lit[self.rng.choice(off)] = True
        elif len(on) > target and on:
            self.lit[self.rng.choice(on)] = False
        elif on and off and self.rng.random() < 0.5:  # troca uma por outra
            self.lit[self.rng.choice(on)] = False
            self.lit[self.rng.choice(off)] = True

    def tick(self, mono: float | None = None) -> tuple[bool, float]:
        """Avança janelas e pássaro; (redesenhar?, próximo prazo em monotonic)."""
        mono = time.monotonic() if mono is None else mono
        if mono >= self.next_toggle:
            self._toggle()
            self.next_toggle = mono + self.rng.uniform(*TOGGLE_EVERY)
        if self.bird is not None and mono >= self.bird[2]:
            self.bird = None
            self.next_bird = mono + self.rng.uniform(*BIRD_EVERY)
        elif self.bird is None and mono >= self.next_bird:
            self.bird = (self.rng.randrange(len(self.wires)), self.rng.uniform(0.35, 0.65),
                         mono + self.rng.uniform(*BIRD_STAY))
        frame = 1.0 / FPS
        redraw = mono - self._last >= frame * 0.9
        if redraw:
            self._last = mono
        return redraw, (self._last if redraw else mono) + frame

    def sways(self, mono: float) -> list[float]:
        a = SWAY[self.kind]
        return [a * math.sin(2 * math.pi * mono / per + ph) for per, ph in zip(self.periods, self.phases,
                                                                            strict=True)]

    # -- desenho
    def regions(self, rect: QRectF) -> list[QRectF]:
        """Retângulos lógicos (da tela) que mudam: o "cam 01" inteiro, ou na espera só os fios e as
        janelas (nada do texto)."""
        if self.kind == "main":
            return [QRectF(rect)]
        vw, vh = STANDBY_VIEW
        k = min(rect.width() / vw, rect.height() / vh)
        ox, oy = rect.left() + (rect.width() - vw * k) / 2, rect.top() + (rect.height() - vh * k) / 2
        m = SWAY["standby"] + 6
        box = QRectF()
        for wire in self.wires:
            box = box.united(_wire_path(wire).controlPointRect().adjusted(-m, -m, m, m))
        ww, wh = self.win_size
        out = [box.intersected(QRectF(0, 0, vw, vh))]
        out += [QRectF(x - 1, y - 1, ww + 2, wh + 2) for x, y, *_ in self.windows]
        return [QRectF(ox + r.left() * k, oy + r.top() * k, r.width() * k, r.height() * k) for r in out]

    def paint(self, p: QPainter, rect: QRectF, accent: str | QColor, mono: float | None = None) -> None:
        mono = time.monotonic() if mono is None else mono
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.translate(rect.topLeft())
        (_main_transform if self.kind == "main" else _standby_transform)(p, rect.width(), rect.height())
        if self.kind == "main" and self.sky.fog > 0:
            self._fog(p, mono)
        _draw_windows(p, self.windows, self.win_size, color(accent), self.lit)
        sways = self.sways(mono)
        _draw_wires(p, self.wires, self.wire_color, sways)
        if self.bird is not None:
            i, t, _ = self.bird
            self._bird(p, _wire_path(self.wires[i], sways[i]).pointAtPercent(t))
        p.restore()

    def _fog(self, p: QPainter, mono: float) -> None:
        vw, _ = MAIN_VIEW
        span = vw + FOG_W
        x = (self.fog_x0 + mono * FOG_SPEED) % span - FOG_W / 2
        c = QColor(sky.FOG_TINT)
        g = QRadialGradient(QPointF(x, FOG_Y), FOG_W / 2)
        c.setAlphaF(self.sky.fog)
        g.setColorAt(0, c)
        c2 = QColor(c)
        c2.setAlphaF(0)
        g.setColorAt(1, c2)
        p.save()
        p.translate(x, FOG_Y)
        p.scale(1.0, FOG_H / FOG_W)
        p.translate(-x, -FOG_Y)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(x, FOG_Y), FOG_W / 2, FOG_W / 2)
        p.restore()

    def _bird(self, p: QPainter, at: QPointF) -> None:
        """Silhueta pequena pousada (corpo, cabeça e rabo), na cor dos postes."""
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color(self.wire_color if self.kind == "standby" else "#0b0a10"))
        x, y = at.x(), at.y()
        p.drawEllipse(QRectF(x - 4.5, y - 7, 9, 6.5))  # corpo
        p.drawEllipse(QPointF(x + 4, y - 7.5), 2.4, 2.4)  # cabeça
        tail = QPainterPath(QPointF(x - 4, y - 4))
        tail.lineTo(QPointF(x - 9, y - 1.5))
        tail.lineTo(QPointF(x - 3.5, y - 2.2))
        p.drawPath(tail)
        p.restore()


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
