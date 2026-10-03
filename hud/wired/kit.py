"""Peças do kit "wired": painel chanfrado, scanlines, segmentos, sparkline, rótulos e selo 正常.

Tudo em px lógicos (grade 1920×1080); o painter pode estar escalado (4/3 no monitor 1440p).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import lru_cache

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from . import fonts
from .theme import HOT, LINE, LINE_STRONG, PANEL, SEG_OFF, TEXT_DIM, WARN, alpha, color

CHAMFER = 14.0
ACCENT_W, ACCENT_H = 56.0, 3.0
SCAN_PERIOD = 3
SCAN_ALPHA = round(0.025 * 255)  # 2,5% de branco


# ------------------------------------------------------------------ painel

def panel_path(rect: QRectF, chamfer: float = CHAMFER) -> QPainterPath:
    """Contorno do painel: cantos cima-direita e baixo-esquerda chanfrados."""
    r = QRectF(rect)
    c = min(chamfer, r.width() / 2, r.height() / 2)
    path = QPainterPath()
    path.addPolygon(QPolygonF([
        r.topLeft(), QPointF(r.right() - c, r.top()), QPointF(r.right(), r.top() + c),
        r.bottomRight(), QPointF(r.left() + c, r.bottom()), QPointF(r.left(), r.bottom() - c),
    ]))
    path.closeSubpath()
    return path


def panel(p: QPainter, rect: QRectF, *, fill: str | QColor | None = PANEL,
          border: str | QColor = LINE, accent: str | QColor | None = LINE_STRONG,
          chamfer: float = CHAMFER) -> QPainterPath:
    """Painel do canvas: fundo, borda de 1 px nas arestas retas (o clip-path corta a borda na
    diagonal, como no CSS) e traço 56×3 no topo-esquerdo. Devolve o contorno (para clip)."""
    r = QRectF(rect)
    c = min(chamfer, r.width() / 2, r.height() / 2)
    path = panel_path(r, c)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if fill is not None:
        p.fillPath(path, color(fill))
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    b = color(border)
    x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
    p.fillRect(QRectF(x0, y0, r.width() - c, 1), b)  # topo
    p.fillRect(QRectF(x1 - 1, y0 + c, 1, r.height() - c), b)  # direita
    p.fillRect(QRectF(x0 + c, y1 - 1, r.width() - c, 1), b)  # base
    p.fillRect(QRectF(x0, y0, 1, r.height() - c), b)  # esquerda
    if accent is not None:
        p.fillRect(QRectF(x0, y0, min(ACCENT_W, r.width() - c), ACCENT_H), color(accent))
    p.restore()
    return path


# ------------------------------------------------------------------ scanlines

@lru_cache(maxsize=16)
def scanlines_pixmap(w: int, h: int, period: int = SCAN_PERIOD) -> QPixmap:
    """Pixmap transparente com linhas de 1 px a 2,5% de branco a cada `period` px (cacheado)."""
    pm = QPixmap(max(1, int(w)), max(1, int(h)))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    line = QColor(255, 255, 255, SCAN_ALPHA)
    for y in range(0, pm.height(), max(1, period)):
        p.fillRect(0, y, pm.width(), 1, line)
    p.end()
    return pm


def draw_scanlines(p: QPainter, rect: QRectF, clip: QPainterPath | None = None) -> None:
    """Desenha as scanlines sobre `rect` em pixels do dispositivo (nítidas mesmo com escala)."""
    t = p.transform()
    dev = t.mapRect(QRectF(rect)).toAlignedRect()
    period = max(SCAN_PERIOD, round(SCAN_PERIOD * math.hypot(t.m21(), t.m22())))
    p.save()
    if clip is not None:
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
    p.resetTransform()
    p.drawPixmap(dev.topLeft(), scanlines_pixmap(dev.width(), dev.height(), period))
    p.restore()


# ------------------------------------------------------------------ segmentos

def lit_count(n: int, pct: float) -> int:
    """Segmentos acesos: arredonda como o Math.round do canvas (0,5 sobe)."""
    pct = 0.0 if pct is None or math.isnan(pct) else min(100.0, max(0.0, float(pct)))
    return int(math.floor(pct / 100.0 * n + 0.5))


def segment_colors(n: int, pct: float, base: str | QColor, warn_from: int | None = None,
                   off: str | QColor = SEG_OFF) -> list[QColor]:
    """Cor de cada segmento. `warn_from` é o índice do 1º segmento de alerta (15 de 20 = 75%):
    dali em diante `warn`, e os 3 últimos `hot` — só nos acesos."""
    on = lit_count(n, pct)
    c_base, c_off, c_warn, c_hot = color(base), color(off), color(WARN), color(HOT)
    out = []
    for i in range(n):
        c = c_base
        if warn_from is not None and i >= warn_from:
            c = c_hot if i >= n - 3 else c_warn
        out.append(QColor(c) if i < on else QColor(c_off))
    return out


def segments(p: QPainter, rect: QRectF, n: int, pct: float, color_: str | QColor,
             warn_from: int | None = None, gap: float = 2.0, off: str | QColor = SEG_OFF) -> int:
    """Barra de `n` segmentos (flex:1, gap 2 px). Devolve quantos acenderam."""
    r = QRectF(rect)
    w = (r.width() - gap * (n - 1)) / n
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    for i, c in enumerate(segment_colors(n, pct, color_, warn_from, off)):
        p.fillRect(QRectF(r.left() + i * (w + gap), r.top(), w, r.height()), c)
    p.restore()
    return lit_count(n, pct)


# ------------------------------------------------------------------ sparkline

def sparkline(p: QPainter, rect: QRectF, values: Sequence[float | None], color_: str | QColor,
              width: float = 1.2, vmin: float = 0.0, vmax: float = 100.0,
              n: int | None = None) -> None:
    """Polilinha de `values` em `rect` (0 em baixo). `None` abre uma lacuna (sem dado).
    `n` fixa o número de posições no eixo x (padrão: len(values))."""
    vals = list(values)
    slots = max(n or len(vals), 2)
    if len(vals) < 2 or vmax <= vmin:
        return
    r = QRectF(rect)
    dx = r.width() / (slots - 1)
    x0 = r.right() - dx * (len(vals) - 1)  # alinha à direita (mais recente na borda)
    path, pen_down = QPainterPath(), False
    for i, v in enumerate(vals):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            pen_down = False
            continue
        y = r.bottom() - (min(vmax, max(vmin, v)) - vmin) / (vmax - vmin) * r.height()
        pt = QPointF(x0 + i * dx, y)
        if pen_down:
            path.lineTo(pt)
        else:
            path.moveTo(pt)
            pen_down = True
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color(color_), width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()


# ------------------------------------------------------------------ texto

def text(p: QPainter, pos: QPointF, s: str, *, key: str = "mono", px: float = 12,
         color_: str | QColor = TEXT_DIM, weight: int | None = None, spacing: float = 0.0,
         align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft) -> QRectF:
    """Texto com a linha de base em `pos.y()`; `align` esquerda/centro/direita em `pos.x()`.
    Devolve o retângulo ocupado."""
    f = fonts.font(key, px, weight, spacing)
    fm = QFontMetricsF(f)
    w = fm.horizontalAdvance(s)
    if spacing:  # o Qt soma o espaçamento também depois do último glifo; o CSS também, mas
        w -= px * spacing  # para alinhar à direita/centro o visual é sem a sobra
    x = pos.x()
    if align & Qt.AlignmentFlag.AlignRight:
        x -= w
    elif align & Qt.AlignmentFlag.AlignHCenter:
        x -= w / 2
    p.save()
    p.setFont(f)
    p.setPen(color(color_))
    p.drawText(QPointF(x, pos.y()), s)
    p.restore()
    return QRectF(x, pos.y() - fm.ascent(), w, fm.height())


def label(p: QPainter, pos: QPointF, s: str, *, px: float = 12, color_: str | QColor = TEXT_DIM,
          upper: bool = True, weight: int | None = None,
          align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft) -> QRectF:
    """Rótulo `.lb` do canvas: JetBrains Mono, CAIXA ALTA, letter-spacing .08em, text-dim."""
    return text(p, pos, s.upper() if upper else s, key="mono", px=px, color_=color_,
                weight=weight, spacing=0.08, align=align)


def heading(p: QPainter, pos: QPointF, s: str, *, px: float = 22, color_: str | QColor = "text",
            align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft) -> QRectF:
    """Título `.hd`: Barlow Condensed 600, CAIXA ALTA, letter-spacing .04em."""
    return text(p, pos, s.upper(), key="cond", px=px, color_=color_, weight=600, spacing=0.04,
                align=align)


def seal(p: QPainter, rect: QRectF, color_: str | QColor, *, divider: bool = True) -> None:
    """Selo 正常 / NORMAL (a cor nunca vai sozinha, R23.7), centrado; divisória à esquerda."""
    r = QRectF(rect)
    if divider:
        p.fillRect(QRectF(r.left(), r.top(), 1, r.height()), color(LINE))
    cx, cy = r.center().x(), r.center().y()
    text(p, QPointF(cx, cy + 3), "正常", key="jp", px=20, color_=color_,
         align=Qt.AlignmentFlag.AlignHCenter)
    label(p, QPointF(cx, cy + 20), "normal", px=10, align=Qt.AlignmentFlag.AlignHCenter)


def device_rect(p: QPainter, rect: QRectF) -> QRect:
    """Retângulo em pixels do dispositivo (para update() por região)."""
    return p.transform().mapRect(QRectF(rect)).toAlignedRect().adjusted(-1, -1, 1, 1)


__all__ = [
    "CHAMFER", "alpha", "device_rect", "draw_scanlines", "heading", "label", "lit_count", "panel",
    "panel_path", "scanlines_pixmap", "seal", "segment_colors", "segments", "sparkline", "text",
]
