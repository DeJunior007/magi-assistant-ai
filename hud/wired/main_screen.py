"""Painel completo "wired" (R23.1–R23.8): composição do kit (U1) com os dados (U2 + HUD).

Entrada desacoplada: um `Snapshot` com tudo o que a tela mostra; campo `None`/vazio vira "– –"
ou estado vazio (R23.3) — nada é simulado aqui. Desenho na grade lógica 1920×1080 com
`painter.scale(size.width() / 1920)` (2560×1440 → 4/3).

Desempenho (R23.8): fundo, painéis, cenário "cam 01", scanlines e rótulos fixos ficam num
QPixmap do tamanho do dispositivo (cache por tamanho). O resto é dividido em grupos com
retângulo próprio; `dirty_regions(snap, now, size)` compara a chave de cada grupo com a do último
desenho e devolve só os retângulos (pixels do dispositivo) que mudaram — o relógio todo segundo,
os dados quando mudam. O mascote anima à parte: `mascot_tick(mono, size)` diz quando e onde
redesenhar (até 30 fps acordada, 1 vez a cada 4 s dormindo). No `paintEvent`, passe
`region=event.rect()` para `paint`: o fundo sai do cache e só os grupos tocados são redesenhados.

`hit_test(pos, size)` devolve "led", "prev", "playpause", "next", "card:cpu", "card:gpu",
"card:ram" (as unidades MELCHIOR/BALTHASAR/CASPER) ou None (pos em pixels do dispositivo).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

from . import fonts, kit, scene, sky
from .mascot import Mascot
from .theme import (
    BG,
    BUTTON,
    BUTTON_LINE,
    CPU,
    FOCUS,
    GPU,
    HOT,
    LINE,
    LINE_STRONG,
    RAM,
    SEG_OFF,
    TEXT,
    TEXT_DIM,
    WARN,
    alpha,
    color,
    tint,
)

W, H = 1920.0, 1080.0
NA = "– –"
R = Qt.AlignmentFlag.AlignRight
C = Qt.AlignmentFlag.AlignHCenter
L = Qt.AlignmentFlag.AlignLeft


# ====================================================================== entrada


@dataclass
class Pilot:
    """Controle conectado (de `gamerhud.controllers()`: label, bateria, conexão, carregando)."""
    name: str
    battery: int | str | None = None  # %
    conn: str = ""  # "BT" | "USB" | ""
    charging: bool = False


@dataclass
class Track:
    """Faixa do Spotify (de `data.NowPlaying`)."""
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    year: str | int | None = None
    position: float | None = None  # s
    length: float | None = None  # s
    playing: bool = False
    cover: QPixmap | None = None


@dataclass
class Snapshot:
    """Tudo o que as telas mostram num instante. `None`/vazio = sem dado (R23.3)."""
    gaming: bool = False  # jogo detectado (chip, falas)
    # sensores (Sensors.data): carga em %, temperatura em °C, potência em W
    cpu: float | None = None
    cpu_temp: float | None = None
    gpu: float | None = None
    gpu_temp: float | None = None
    gpu_w: float | None = None
    ram: float | None = None
    ram_txt: str | None = None  # "11.4/32G"
    vram: float | None = None
    vram_txt: str | None = None  # "4.7/16G"
    # specs: rótulos curtos dos cards e linhas do Unit spec (system_info)
    cpu_label: str | None = None  # "i5-11400F · 6C/12T"
    gpu_label: str | None = None  # "RX 9060 XT"
    ram_label: str | None = None  # "32GB DDR4 3200"
    specs: list[tuple[str, str]] = field(default_factory=list)
    pilots: list[Pilot] = field(default_factory=list)
    # rede (data.NetRate), bytes/s
    net_down: float | None = None
    net_up: float | None = None
    net_series: list[float] = field(default_factory=list)
    # histórico de 60 min (data.LoadHistory): séries cpu/gpu/ram e eixo [(0..1, "HH:MM")]
    history: dict[str, list[float | None]] = field(default_factory=dict)
    history_axis: list[tuple[float, str]] = field(default_factory=list)
    # FPS (data.FpsStats.snapshot()); None = sem jogo
    fps: float | None = None
    fps_min: float | None = None
    fps_avg: float | None = None
    fps_max: float | None = None
    fps_series: list[float] = field(default_factory=list)
    track: Track | None = None
    events: list[str] = field(default_factory=list)  # EventLog.ticker()
    led_on: bool = False
    led_rgb: str | None = None  # "#rrggbb" do OpenRGB; None = sem cor (visual "off")
    magui_state: str = "sleeping"  # uma das 7 expressões do R17
    mouth_level: float = 0.0
    caption: str | None = None  # legenda da fala da Magui
    mood: int | None = None  # termômetro de humor 0 (pega leve) .. 4 (pode zoar), R13.7; None = sem dado
    news: list[tuple[str, str]] = field(default_factory=list)  # Rádio Ayanami: (HH:MM, manchete), novas 1º
    claude: Any = None  # data.ClaudeView: consumo e sessões do Claude Code; None = sem dado
    self_usage: Any = None  # data.SelfView: cpu/ram/gpu/vram dos processos da Condessa; None = sem dado


def led_lit(snap: Snapshot) -> bool:
    return bool(snap.led_on and snap.led_rgb)


# chip de estado da Condessa: ouvindo/pensando acendem na cor de foco (o Pedro vê quando ela ativou)
CHIP_STATES = {"listening": "Listening · 聴取中", "thinking": "Thinking · 思考中"}


def chip_label(snap: Snapshot) -> tuple[str, str, bool]:
    """(texto, cor, aceso) do chip: ouvindo/pensando, senão jogando (Active) ou Standby."""
    lbl = CHIP_STATES.get(snap.magui_state)
    if lbl is not None:
        return lbl, FOCUS, True
    if snap.gaming:
        return "Active · 稼働中", GPU, False
    return "Standby · 待機中", TEXT, False


def state_chip(p: QPainter, x: float, y: float, snap: Snapshot) -> QRectF:
    """Desenha o chip de estado em (x, y) (canto superior esquerdo); devolve o retângulo."""
    lbl, fg, lit = chip_label(snap)
    f_w = width(lbl.upper(), "cond", 18, 600, 0.04)
    chip = QRectF(x, y, f_w + 30, 35.6)
    if lit:  # aceso: fundo translúcido e borda na cor de foco
        bg = color(FOCUS)
        bg.setAlphaF(0.14)
        p.fillRect(chip, bg)
        p.setPen(QPen(color(FOCUS), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(chip.adjusted(1, 1, -1, -1))
    else:
        p.setPen(color(LINE_STRONG))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(chip.adjusted(0.5, 0.5, -0.5, -0.5))
    heading(p, chip.left() + 15, chip.top() + 26, lbl, px=18, color_=fg)
    return chip


def accent(snap: Snapshot) -> QColor:
    """Cor de acento: a do RGB com o LED ligado, senão a da Melchior."""
    return color(snap.led_rgb) if led_lit(snap) else color(CPU)


# ====================================================================== formatação


def num(v, fmt: str = "{:.0f}", suffix: str = "") -> str:
    if v is None:
        return NA
    try:
        return fmt.format(float(v)) + suffix
    except (TypeError, ValueError):
        return NA


def gb(txt: str | None) -> str:
    """"11.4/32G" → "11.4 / 32 GB"."""
    if not txt or txt.strip() in ("--", ""):
        return NA
    t = txt.strip()
    if t.endswith("G"):
        t = t[:-1].replace("/", " / ") + " GB"
    return t


def mmss(sec: float | None) -> str:
    if sec is None or sec < 0:
        return NA
    s = int(sec)
    return f"{s // 60}:{s % 60:02d}"


def rate(bps: float | None) -> str:
    from .data import fmt_rate
    return fmt_rate(bps)


JP_DAYS = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]  # weekday()
PT_DAYS = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]
PT_MONTHS = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


# ====================================================================== texto


@lru_cache(maxsize=128)
def _metrics(key: str, px: float, weight: int | None, spacing: float) -> QFontMetricsF:
    return QFontMetricsF(fonts.font(key, px, weight, spacing))


def baseline(key: str, px: float, top: float, lh: float | None = None, weight: int | None = None) -> float:
    """Linha de base de um texto cuja caixa de linha CSS começa em `top` (line-height `lh` px)."""
    fm = _metrics(key, px, weight, 0.0)
    a, d = fm.ascent(), fm.descent()
    lh = a + d if lh is None else lh
    return top + (lh - (a + d)) / 2 + a


def text(p: QPainter, x: float, y: float, s: str, *, key: str = "mono", px: float = 12,
         color_=TEXT, weight: int | None = None, spacing: float = 0.0, align=L,
         max_w: float | None = None, upper: bool = False) -> QRectF:
    """`kit.text` com corte por reticências em `max_w`."""
    s = s.upper() if upper else s
    if max_w is not None:
        fm = _metrics(key, px, weight, spacing)
        if fm.horizontalAdvance(s) > max_w:
            s = fm.elidedText(s, Qt.TextElideMode.ElideRight, max_w)
    return kit.text(p, QPointF(x, y), s, key=key, px=px, color_=color_, weight=weight,
                    spacing=spacing, align=align)


def label(p: QPainter, x: float, y: float, s: str, *, px: float = 12, color_=TEXT_DIM, upper=True,
          align=L, max_w: float | None = None) -> QRectF:
    return text(p, x, y, s, key="mono", px=px, color_=color_, spacing=0.08, align=align,
                max_w=max_w, upper=upper)


def heading(p: QPainter, x: float, y: float, s: str, *, px: float = 22, color_=TEXT, align=L) -> QRectF:
    return kit.heading(p, QPointF(x, y), s, px=px, color_=color_, align=align)


def width(s: str, key: str = "mono", px: float = 12, weight: int | None = None,
          spacing: float = 0.0) -> float:
    w = _metrics(key, px, weight, spacing).horizontalAdvance(s)
    return w - px * spacing if spacing else w


def wrapped(p: QPainter, rect: QRectF, s: str, *, key: str = "jp", px: float = 16, color_=TEXT,
            spacing: float = 0.0, line_h: float | None = None, max_lines: int = 4) -> None:
    """Texto com quebra de linha (o Qt quebra também entre ideogramas) e reticências na última."""
    f = fonts.font(key, px, None, spacing)
    fm = _metrics(key, px, None, spacing)
    lh = line_h or fm.height()
    words, lines = s.split(), []
    cur = ""
    for wd in words:  # quebra por palavra; palavra (ou frase CJK) longa quebra por caractere
        cand = f"{cur} {wd}" if cur else wd
        if fm.horizontalAdvance(cand) <= rect.width():
            cur = cand
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in wd:
            if fm.horizontalAdvance(cur + ch) > rect.width() and cur:
                lines.append(cur)
                cur = ""
            cur += ch
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        last = " ".join(lines[max_lines - 1:])
        lines = lines[:max_lines - 1] + [fm.elidedText(last + "…", Qt.TextElideMode.ElideRight, rect.width())]
    p.save()
    p.setFont(f)
    p.setPen(color(color_))
    a = fm.ascent()
    for i, ln in enumerate(lines):
        p.drawText(QPointF(rect.left(), rect.top() + (lh - fm.height()) / 2 + a + i * lh), ln)
    p.restore()


def human_tokens(n: int | None) -> str:
    """Tokens em forma curta: 950, 12,3 mil, 271 mi."""
    if n is None:
        return NA
    if n >= 10**8:
        return f"{n / 1e6:.0f} mi"
    if n >= 10**6:
        return f"{n / 1e6:.1f} mi".replace(".", ",")
    if n >= 1000:
        return f"{n / 1e3:.1f} mil".replace(".", ",")
    return str(n)


def dev_rect(r: QRectF, s: float) -> QRect:
    d = QRectF(r.left() * s, r.top() * s, r.width() * s, r.height() * s)
    return d.toAlignedRect().adjusted(-1, -1, 1, 1)


_COVERS: dict[tuple, QPixmap] = {}


def cover_scaled(pm: QPixmap | None, w: float, h: float, s: float) -> QPixmap | None:
    """Capa recortada para preencher w×h lógicos, em pixels do dispositivo (memorizada)."""
    if pm is None or pm.isNull():
        return None
    dw, dh = max(1, round(w * s)), max(1, round(h * s))
    key = (pm.cacheKey(), dw, dh)
    out = _COVERS.get(key)
    if out is None:
        sc = pm.scaled(dw, dh, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
        out = sc.copy((sc.width() - dw) // 2, (sc.height() - dh) // 2, dw, dh)
        out.setDevicePixelRatio(s)
        if len(_COVERS) > 8:
            _COVERS.clear()
        _COVERS[key] = out
    return out


def draw_cover(p: QPainter, r: QRectF, cover: QPixmap | None, s: float, ring: float, stroke: float,
               dot: float) -> None:
    """Moldura da capa: a capa real (com scanlines) ou o disco decorativo do canvas (sem dado)."""
    p.fillRect(r, color("#1a1823"))
    inner = r.adjusted(1, 1, -1, -1)
    pm = cover_scaled(cover, inner.width(), inner.height(), s)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if pm is not None:
        p.drawPixmap(inner, pm, QRectF())
        p.restore()
        kit.draw_scanlines(p, inner)
        p.save()
    else:
        c = r.center()
        p.setPen(QPen(color(BUTTON_LINE), stroke))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, ring, ring)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(WARN, round(0.7 * 255)))
        p.drawEllipse(c, dot, dot)
    p.restore()
    p.setPen(color(LINE_STRONG))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))


def led_dot(p: QPainter, c: QPointF, r: float, snap: Snapshot) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    if led_lit(snap):
        rgb = color(snap.led_rgb)
        g = QRadialGradient(c, r * 2.2)
        g.setColorAt(0.0, alpha(rgb, 150))
        g.setColorAt(1.0, alpha(rgb, 0))
        p.setBrush(g)
        p.drawEllipse(c, r * 2.2, r * 2.2)
        p.setBrush(rgb)
    else:
        p.setBrush(color(LINE_STRONG))
    p.drawEllipse(c, r, r)
    p.restore()


# ====================================================================== termômetro (R13.7)

MOOD_LEVELS = 5  # 0 pega leve .. 4 pode zoar pesado


def mood_color(snap: Snapshot) -> QColor | None:
    """Cor do termômetro: 0 hot, 1 warn, 2 text-dim, 3–4 verde (ou a cor do LED ligado)."""
    m = snap.mood
    if m is None:
        return None
    m = max(0, min(MOOD_LEVELS - 1, int(m)))
    if m <= 1:
        return color(HOT if m == 0 else WARN)
    if m == 2:
        return color(TEXT_DIM)
    return color(snap.led_rgb) if led_lit(snap) else color(GPU)


def mood_key(snap: Snapshot) -> tuple:
    c = mood_color(snap)
    return (snap.mood, c.rgb() if c is not None else None)


def draw_mood(p: QPainter, r: QRectF, snap: Snapshot, *, legend: bool = True, bar_w: float = 8.0) -> None:
    """Termômetro vertical fino: `mood + 1` segmentos acesos de baixo pra cima. A quantidade de
    segmentos (e o número, com `legend`) carrega a informação, não só a cor (R23.7)."""
    col = mood_color(snap)
    lit = 0 if col is None else max(0, min(MOOD_LEVELS - 1, int(snap.mood))) + 1
    top, bottom = r.top(), r.bottom()
    cx = r.center().x()
    if legend:
        text(p, cx, top + 12, "気", key="jp", px=12, color_=TEXT_DIM, align=C)
        text(p, cx, bottom - 3, "–" if snap.mood is None else str(lit - 1), px=12,
             color_=TEXT if col is not None else TEXT_DIM, align=C)
        top, bottom = top + 20, bottom - 20
    gap = 3.0
    h = (bottom - top - gap * (MOOD_LEVELS - 1)) / MOOD_LEVELS
    off = color(SEG_OFF)
    for i in range(MOOD_LEVELS):  # i = 0 é o de baixo
        y = bottom - (i + 1) * h - i * gap
        p.fillRect(QRectF(cx - bar_w / 2, y, bar_w, h), col if i < lit else off)


# ====================================================================== base


class Screen:
    """Base das duas telas: cache da camada estática, grupos com chave e retângulo, mascote."""

    MASCOT_RECT = QRectF()
    SCENE_KIND = "main"

    def __init__(self, mascot: Mascot | None = None, anim: scene.SceneAnimator | None = None):
        self.mascot = mascot or Mascot("sleeping")
        self.anim = anim or scene.SceneAnimator(self.SCENE_KIND)
        self.sky = sky.NIGHT
        self._static: tuple[tuple, QPixmap] | None = None
        self._keys: dict[str, tuple] = {}
        self._snap: Snapshot | None = None

    # -- a implementar
    def groups(self) -> dict[str, list[QRectF]]:
        raise NotImplementedError

    def group_key(self, name: str, snap: Snapshot, now: datetime) -> tuple:
        raise NotImplementedError

    def draw_group(self, name: str, p: QPainter, snap: Snapshot, now: datetime, s: float) -> None:
        raise NotImplementedError

    def draw_static(self, p: QPainter, s: float) -> None:
        raise NotImplementedError

    def paint_scene(self, p: QPainter, snap: Snapshot, mono: float, s: float) -> None:
        """Camada animada do cenário (painter na grade lógica, recortado à região)."""
        raise NotImplementedError

    def scene_rects(self) -> list[QRectF]:
        raise NotImplementedError

    def set_time(self, now: datetime) -> None:
        """Dia e noite: paleta do céu para ``now`` (o fundo em cache muda junto, a cada 5 min)."""
        self.sky = sky.sky_at(now)
        self.anim.set_sky(self.sky)

    # -- comum
    @staticmethod
    def scale(size: QSize) -> float:
        return size.width() / W

    def sync(self, snap: Snapshot) -> None:
        """Repassa o estado da Magui ao mascote (expressão e boca)."""
        try:
            self.mascot.set_expression(snap.magui_state)
        except ValueError:
            self.mascot.set_expression("sleeping")
        self.mascot.set_level(snap.mouth_level)

    def static_pixmap(self, size: QSize) -> QPixmap:
        key = (size.width(), size.height(), self.sky.key)
        if self._static is None or self._static[0] != key:
            s = self.scale(size)
            pm = QPixmap(size)
            pm.fill(color(BG))
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.scale(s, s)
            self.draw_static(p, s)
            p.end()
            self._static = (key, pm)
            self._keys.clear()
        return self._static[1]

    def paint(self, p: QPainter, size: QSize, snap: Snapshot, now: datetime | None = None,
              mono: float | None = None, region: QRect | None = None) -> None:
        """Desenha a tela (painter sem transformação, em pixels do dispositivo). `region`: só essa
        área (o fundo sai do cache e só os grupos que a tocam são redesenhados)."""
        now = now or datetime.now()
        mono = time.monotonic() if mono is None else mono
        self.set_time(now)
        s = self.scale(size)
        full = QRect(0, 0, size.width(), size.height())
        dev = full if region is None else region.intersected(full)
        static = self.static_pixmap(size)
        self.sync(snap)
        self._snap = snap
        p.save()
        p.setClipRect(dev)
        p.drawPixmap(dev, static, dev)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.scale(s, s)
        for name, rects in self.groups().items():
            drs = [dev_rect(r, s) for r in rects]
            if not any(dev.intersects(d) for d in drs):
                continue
            if name == "mascot":
                self.mascot.paint(p, self.MASCOT_RECT, accent(snap), mono)
            elif name == "scene":
                self.paint_scene(p, snap, mono, s)
            else:
                self.draw_group(name, p, snap, now, s)
            if all(dev.contains(d.intersected(full)) for d in drs):
                self._keys[name] = self.group_key(name, snap, now)
        p.restore()

    def dirty_regions(self, snap: Snapshot, now: datetime | None = None,
                      size: QSize | None = None) -> list[QRect]:
        """Retângulos (dispositivo) cujos dados mudaram desde o último `paint`. Vazio = nada a fazer."""
        now = now or datetime.now()
        size = size or QSize(round(W), round(H))
        s = self.scale(size)
        self.set_time(now)
        if self._static is None or self._static[0] != (size.width(), size.height(), self.sky.key):
            return [QRect(0, 0, size.width(), size.height())]
        out = []
        for name, rects in self.groups().items():
            if self._keys.get(name) != self.group_key(name, snap, now):
                out += [dev_rect(r, s) for r in rects]
        return out

    def mascot_tick(self, mono: float | None = None, size: QSize | None = None) -> tuple[QRect | None, float]:
        """Avança o mascote; (retângulo a redesenhar ou None, próximo prazo em monotonic)."""
        size = size or QSize(round(W), round(H))
        redraw, nxt = self.mascot.tick(mono)
        # só a área do rosto (sem a faixa do humor ao lado: ela não muda a cada quadro)
        rect = getattr(self, "MASCOT_DIRTY", None) or self.MASCOT_RECT
        return (dev_rect(rect, self.scale(size)) if redraw else None), nxt

    def scene_tick(self, mono: float | None = None, size: QSize | None = None) -> tuple[list[QRect], float]:
        """Avança o cenário animado (fios, janelas, névoa, pássaro); (retângulos a redesenhar,
        próximo prazo em monotonic)."""
        size = size or QSize(round(W), round(H))
        moved, nxt = self.anim.tick(mono)
        if not moved:
            return [], nxt
        s = self.scale(size)
        full = QRect(0, 0, size.width(), size.height())
        return [dev_rect(r, s).intersected(full) for r in self.scene_rects()], nxt

    def hit_rects(self, snap: Snapshot | None = None) -> dict[str, QRectF]:
        return {}

    def hit_test(self, pos: QPoint | QPointF, size: QSize) -> str | None:
        """Área clicável sob `pos` (pixels do dispositivo) ou None."""
        s = self.scale(size)
        pt = QPointF(pos.x() / s, pos.y() / s)
        for name, r in self.hit_rects(self._snap).items():
            if r.contains(pt):
                return name
        return None


# ====================================================================== geometria do painel

X1, X2, X3 = 28.0, 588.0, 1532.0  # colunas 540 | 924 | 360, gap 20
Y2, Y3 = 144.0, 1024.0  # linhas 96 | 860 | 28
# esquerda: MAGI system (CPU/GPU/memória, só aqui) + FPS + rede
_RR = (860 - 20) / 2.25
MAGI = QRectF(X1, Y2, 540, _RR * 1.25)
_LEFT_REST = Y3 - 20 - MAGI.bottom() - 16 * 2
CARD_FPS = QRectF(X1, MAGI.bottom() + 16, 540, _LEFT_REST * 0.55)
CARD_NET = QRectF(X1, CARD_FPS.bottom() + 16, 540, _LEFT_REST * 0.45)
_M = (860 - 20) / 2.45  # centro: flex 1.45 / 1
MID_TOP = QRectF(X2, Y2, 924, _M * 1.45)
SCENE = QRectF(X2, Y2, 1 + 922 * 1.4 / 2.4, MID_TOP.height())
SIDE_X, SIDE_R = SCENE.right() + 22, MID_TOP.right() - 23
HIST = QRectF(X2, MID_TOP.bottom() + 20, 544, _M)
SPEC = QRectF(HIST.right() + 20, HIST.top(), 360, _M)
# direita: Now playing compacto, Rádio Ayanami (cartões) e Claude Code
NP = QRectF(X3, Y2, 360, 292)
RADIO = QRectF(X3, NP.bottom() + 20, 360, 262)
CLAUDE = QRectF(X3, RADIO.bottom() + 20, 360, Y3 - 20 - RADIO.bottom() - 20)
RADIO_ITEMS = 3
RADIO_CARD_H = 56.0

# lado do mascote (flex column gap 14, a partir de top+1+22)
_SY = Y2 + 23
MASCOT_MAIN = QRectF(SIDE_X, _SY + 15.8 + 14, SIDE_R - SIDE_X, 252)  # retrato da Condessa (+20%)
CHIP_TOP = MASCOT_MAIN.bottom() + 14
MOOD_MAIN = QRectF(SIDE_R - 24, MASCOT_MAIN.top() + 4, 24, MASCOT_MAIN.height() - 8)  # à direita do mascote
TALK = QRectF(SIDE_X - 2, CHIP_TOP - 2, SIDE_R - SIDE_X + 4, MID_TOP.bottom() - CHIP_TOP - 20)

# MAGI system
LED_BTN = QRectF(MAGI.right() - 21 - 150, MAGI.top() + 19, 150, 44)
SELF_H = 26.0  # linha "Condessa" (consumo dela) sob as três unidades
_UNIT_H = (MAGI.height() - 38 - 44 - 36 - SELF_H) / 3
UNITS = [QRectF(MAGI.left() + 21, LED_BTN.bottom() + 12 + i * (_UNIT_H + 12), 498, _UNIT_H) for i in range(3)]
SELF_ROW = QRectF(MAGI.left() + 21, UNITS[-1].bottom() + 4, 498, SELF_H)  # acaba 15 px acima da borda
UNIT_NAMES = (("Melchior", "magi·1 // cpu"), ("Balthasar", "magi·2 // gpu"), ("Casper", "magi·3 // memory"))
UNIT_KEYS = ("負荷 load", "温度 temp", "映像 vram", "主記 ram")
UNIT_GAP = 12.0  # entre nome | barras | selo
ROW_GAP = 8.0  # entre rótulo | barra | valor


@lru_cache(maxsize=1)
def unit_columns() -> tuple[float, float, float]:
    """(nome, rótulo, valor) em px lógicos, medidos com as fontes reais. A barra fica com o resto
    (a coluna `1fr` do canvas): ~100 px em vez dos ~60 do layout com o nome em 150 px fixos."""
    name = max(max(width(n.upper(), "cond", 24, 600, 0.04), width(sub.upper(), "mono", 12, None, 0.08))
               for n, sub in UNIT_NAMES)
    key = max(width(k, "jp", 12, None, 0.08) for k in UNIT_KEYS)
    val = width("00.0/00G", "mono", 14)
    return math.ceil(name), math.ceil(key) + 2, math.ceil(val) + 2

# Now playing (compacto: capa e texto lado a lado, barra e botões embaixo)
COVER_S = 100.0
NP_ROW = NP.top() + 19 + 26.4 + 16
COVER = QRectF(NP.left() + 21, NP_ROW, COVER_S, COVER_S)
NP_X = COVER.right() + 14
NP_R = NP.right() - 21
NP_BAR = COVER.bottom() + 16
BTN_Y = NP.bottom() - 21 - 44
BTNS = {k: QRectF(NP.left() + 21 + i * 52, BTN_Y, 44, 44)
        for i, k in enumerate(("prev", "playpause", "next"))}
EQ = (10, 22, 34, 18, 40, 28, 14, 30, 38, 20, 12, 26, 16, 8)  # alturas decorativas do canvas

HEADER_CLOCK = QRectF(1380, 36, 1892 - 1380, 84)
REC = QRectF(SCENE.left() + 20, Y2 + 44, 150, 18)
FOOTER = QRectF(400, Y3, 1290, 28)


def _btn(p: QPainter, r: QRectF, active: bool) -> None:
    p.fillRect(r, color(BUTTON))
    p.setPen(color(BUTTON_LINE))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))


def _icon(p: QPainter, r: QRectF, kind: str, c: QColor) -> None:
    """Ícones do canvas (viewBox 24, desenhados a 18 px, traço 2)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(r.center().x() - 9, r.center().y() - 9)
    p.scale(0.75, 0.75)
    pen = QPen(c, 2)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def tri(*pts):
        path = QPainterPath(QPointF(*pts[0]))
        for pt in pts[1:]:
            path.lineTo(QPointF(*pt))
        path.closeSubpath()
        p.drawPath(path)

    if kind == "prev":
        tri((18, 5), (8, 12), (18, 19))
        p.drawLine(QPointF(6, 5), QPointF(6, 19))
    elif kind == "next":
        tri((6, 5), (16, 12), (6, 19))
        p.drawLine(QPointF(18, 5), QPointF(18, 19))
    elif kind == "pause":
        p.drawLine(QPointF(8, 5), QPointF(8, 19))
        p.drawLine(QPointF(16, 5), QPointF(16, 19))
    else:
        tri((7, 5), (19, 12), (7, 19))
    p.restore()


def _bolt(p: QPainter, c: QPointF, col: QColor) -> None:
    pts = [(1.5, -6), (-3, 0.8), (0, 0.8), (-1.5, 6), (3, -0.8), (0, -0.8)]
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col)
    path = QPainterPath(QPointF(c.x() + pts[0][0], c.y() + pts[0][1]))
    for x, y in pts[1:]:
        path.lineTo(QPointF(c.x() + x, c.y() + y))
    path.closeSubpath()
    p.drawPath(path)
    p.restore()


def mb(v: float | None) -> str:
    """MB → "610 MB" / "1.2 GB" (arredondado a 10 MB, para a linha não piscar à toa)."""
    if v is None:
        return NA
    if v >= 1000:
        return f"{v / 1024:.1f} GB"
    return f"{round(v, -1):.0f} MB"


def self_line(snap: Snapshot) -> list[tuple[str, str]] | None:
    """Linha "Condessa" do MAGI system: [(rótulo, valor)] já arredondados (é também a chave do
    grupo) ou None sem dado."""
    u = snap.self_usage
    if u is None:
        return None
    return [("cpu", num(u.cpu, suffix="%")), ("ram", mb(u.ram_mb)), ("gpu", num(u.gpu, suffix="%")),
            ("vram", mb(u.vram_mb))]


def talk_lines(snap: Snapshot) -> tuple[list[str], str]:
    """Falas do estado (canvas). A de temperatura só aparece se estiver mesmo quente."""
    if snap.gaming:
        hot = any(t is not None and t >= 75 for t in (snap.cpu_temp, snap.gpu_temp))
        if hot:
            return ["「同期完了。見ているよ。」", "「温度、少し上がってる。」"], \
                "Sync complete. I am watching. Temperature rising a little."
        return ["「同期完了。見ているよ。」", "「異常なし。」"], "Sync complete. I am watching. No anomalies."
    return ["「システムは正常です。」", "「少し眠いです…」"], "System is normal. A little sleepy…"


# ====================================================================== tela


class MainScreen(Screen):
    """Painel completo (Main.dc.html)."""

    MASCOT_RECT = MASCOT_MAIN
    MASCOT_DIRTY = QRectF(MASCOT_MAIN.left(), MASCOT_MAIN.top(), MOOD_MAIN.left() - 4 - MASCOT_MAIN.left(),
                          MASCOT_MAIN.height())

    # ---------------------------------------------------------------- estático

    def draw_static(self, p: QPainter, s: float) -> None:
        # header
        p.fillRect(QRectF(X1, 123, 1864, 1), color(LINE))
        text(p, X1, 82, "汎用監視システム", key="mincho", px=46, spacing=0.06)
        label(p, X1, 106, "General purpose monitoring system — MAGI-01", px=13)
        text(p, 960, 82, "私は、ここにいる。", key="jp", px=16, spacing=0.2, align=C)
        label(p, 960, 102, "// i am here · node 01 online", px=11, align=C)
        # coluna esquerda: MAGI system, FPS e rede
        kit.panel(p, MAGI)
        w = heading(p, MAGI.left() + 21, LED_BTN.top() + 32, "MAGI system", px=26).width()
        text(p, MAGI.left() + 21 + w + 12, LED_BTN.top() + 32, "三体合議制御", key="jp", px=12,
             color_=TEXT_DIM)
        for r in (CARD_FPS, CARD_NET):
            kit.panel(p, r)
        heading(p, X1 + 20, CARD_FPS.top() + 43, "FPS", px=24)
        text(p, CARD_FPS.right() - 20, CARD_FPS.top() + 43, "毎秒フレーム数", key="jp", px=12,
             color_=TEXT_DIM, spacing=0.08, align=R)
        heading(p, X1 + 20, CARD_NET.top() + 37, "Network", color_=TEXT)
        # centro em cima: cena + lado do mascote
        kit.panel(p, MID_TOP)
        self._scene_frame(p, s, None)
        p.fillRect(QRectF(SCENE.right() - 1, MID_TOP.top(), 1, MID_TOP.height()), color(LINE))
        label(p, SIDE_X, _SY + 12, "magi-01 // condessa")
        text(p, SIDE_R, _SY + 12, "人格", key="jp", px=12, color_=TEXT_DIM, align=R)
        # centro embaixo
        kit.panel(p, HIST)
        hx = HIST.left() + 20
        hb = HIST.top() + 39
        w = heading(p, hx, hb, "Load history").width()
        text(p, hx + w + 12, hb, "負荷履歴", key="jp", px=12, color_=TEXT_DIM)
        x = HIST.right() - 20
        for name, col in (("■ ram", RAM), ("■ gpu", GPU), ("■ cpu", CPU)):
            x -= label(p, x, hb, name, color_=col, align=R).width() + 14
        kit.panel(p, SPEC)
        sx = SPEC.left() + 20
        w = heading(p, sx, hb, "Unit spec").width()
        text(p, sx + w + 12, hb, "機体情報", key="jp", px=12, color_=TEXT_DIM)
        p.fillRect(QRectF(sx, HIST.top() + 182, 320, 1), color(LINE))
        w = heading(p, sx, HIST.top() + 208, "Pilots", px=16).width()
        text(p, sx + w + 10, HIST.top() + 208, "操縦者", key="jp", px=12, color_=TEXT_DIM)
        # direita: Now playing e Rádio Ayanami
        kit.panel(p, NP)
        w = heading(p, NP.left() + 21, NP.top() + 41, "Now playing").width()
        text(p, NP.left() + 21 + w + 12, NP.top() + 41, "再生中", key="jp", px=12, color_=TEXT_DIM)
        kit.panel(p, RADIO)
        w = heading(p, RADIO.left() + 21, RADIO.top() + 41, "Rádio Ayanami").width()
        text(p, RADIO.left() + 21 + w + 12, RADIO.top() + 41, "放送", key="jp", px=12, color_=TEXT_DIM)
        kit.panel(p, CLAUDE)
        w = heading(p, CLAUDE.left() + 21, CLAUDE.top() + 41, "Claude Code").width()
        text(p, CLAUDE.left() + 21 + w + 12, CLAUDE.top() + 41, "補佐", key="jp", px=12, color_=TEXT_DIM)
        # rodapé
        w = heading(p, X1, 1043, "MAGI", px=16).width()
        label(p, X1 + w + 12, 1042, "multi agent guidance interface")
        label(p, 1892, 1042, "meta+m · painel completo", align=R)

    def _scene_frame(self, p: QPainter, s: float, mono: float | None) -> None:
        """"cam 01": fundo do céu da hora, camada animada (``mono``; None = parado, no estático),
        scanlines, borda do painel e legendas por cima."""
        path = kit.panel_path(MID_TOP)
        p.save()
        p.setClipPath(path, Qt.ClipOperation.IntersectClip)
        p.setClipRect(SCENE, Qt.ClipOperation.IntersectClip)
        p.drawPixmap(SCENE, scene.main_scene(SCENE.width(), SCENE.height(), CPU, s, self.sky, live=False),
                     QRectF())
        self.anim.paint(p, SCENE, CPU, mono)
        p.restore()
        kit.draw_scanlines(p, SCENE, clip=path)
        p.save()
        p.setClipRect(SCENE, Qt.ClipOperation.IntersectClip)
        kit.panel(p, MID_TOP, fill=None)
        p.restore()
        label(p, SCENE.left() + 24, Y2 + 35, "cam 01 // 電線", color_=TEXT)
        text(p, SCENE.left() + 24, MID_TOP.bottom() - 50, "信号は、まだ届いている。", key="jp", px=18,
             spacing=0.14)
        label(p, SCENE.left() + 24, MID_TOP.bottom() - 26, "the signal is still arriving.", upper=False)

    def paint_scene(self, p: QPainter, snap: Snapshot, mono: float, s: float) -> None:
        self._scene_frame(p, s, mono)

    def scene_rects(self) -> list[QRectF]:
        return self.anim.regions(SCENE)

    # ---------------------------------------------------------------- grupos

    def groups(self) -> dict[str, list[QRectF]]:
        def inner(r: QRectF, top: float = 50) -> QRectF:  # abaixo do título do card
            return QRectF(r.left() + 2, r.top() + top, r.width() - 4, r.height() - top - 2)

        return {
            "scene": self.scene_rects(),  # primeiro: REC e o resto do cam 01 vão por cima
            "clock": [HEADER_CLOCK, REC],
            "fps": [inner(CARD_FPS)],
            "net": [QRectF(X1 + 2, CARD_NET.top() + 2, CARD_NET.width() - 4, CARD_NET.height() - 4)],
            "mascot": [MASCOT_MAIN],
            "mood": [MOOD_MAIN],
            "talk": [TALK],
            "history": [QRectF(HIST.left() + 2, HIST.top() + 50, HIST.width() - 4, HIST.height() - 52)],
            "spec": [QRectF(SPEC.left() + 2, SPEC.top() + 50, SPEC.width() - 4, 128),
                     QRectF(SPEC.left() + 2, SPEC.top() + 214, SPEC.width() - 4, SPEC.height() - 216)],
            "magi": [QRectF(MAGI.left() + 2, LED_BTN.top() - 2, MAGI.width() - 4,
                            UNITS[-1].bottom() + 2 - (LED_BTN.top() - 2))],
            "self": [SELF_ROW],
            "player": [QRectF(NP.left() + 2, NP.top() + 18, NP.width() - 4, NP.height() - 20)],
            "radio": [inner(RADIO, 56)],
            "claude": [inner(CLAUDE, 56)],
            "footer": [FOOTER],
        }

    def group_key(self, name: str, snap: Snapshot, now: datetime) -> tuple:
        sn = snap
        if name == "clock":
            return (now.strftime("%Y%m%d%H%M%S"),)
        if name == "fps":
            return (sn.fps, sn.fps_min, sn.fps_avg, sn.fps_max, tuple(sn.fps_series))
        if name == "net":
            return (sn.net_down, sn.net_up, tuple(sn.net_series))
        if name == "scene":
            return (self.sky.key,)
        if name == "mascot":
            return (accent(sn).rgb(), sn.magui_state)
        if name == "mood":
            return mood_key(sn)
        if name == "talk":
            return (sn.gaming, chip_label(sn), sn.caption, *talk_lines(sn)[0])
        if name == "history":
            return (tuple((k, tuple(v)) for k, v in sorted(sn.history.items())), tuple(sn.history_axis))
        if name == "spec":
            return (tuple(sn.specs), tuple((x.name, x.battery, x.conn, x.charging) for x in sn.pilots))
        if name == "magi":
            return (led_lit(sn), accent(sn).rgb(), sn.cpu, sn.cpu_temp, sn.gpu, sn.gpu_temp,
                    sn.vram, sn.vram_txt, sn.ram, sn.ram_txt)
        if name == "self":
            return tuple(self_line(sn) or ())
        if name == "player":
            t = sn.track
            if t is None:
                return (None,)
            pos = None if t.position is None else int(t.position)
            return (t.title, t.artist, t.album, t.year, pos, t.length, t.playing,
                    t.cover.cacheKey() if t.cover is not None else None)
        if name == "radio":
            return tuple(sn.news)
        if name == "claude":
            c = sn.claude
            return (None,) if c is None else (c.tokens, c.output, c.replies, tuple(c.sessions), c.running,
                                               c.autofix, c.window_end, c.window_fresh, c.window_cache)
        if name == "footer":
            return tuple(sn.events)
        return ()

    def draw_group(self, name: str, p: QPainter, snap: Snapshot, now: datetime, s: float) -> None:
        getattr(self, f"_g_{name}")(p, snap, now, s)

    # ---------------------------------------------------------------- header

    def _g_clock(self, p, snap, now, s):
        right = 1892.0
        ss_w = width("00", "cond", 32, 500)
        hm_w = width("00:00", "cond", 84, 500)
        y = baseline("cond", 84, 110 - 84 * 0.82, 84 * 0.82, 500)
        text(p, right, y, f"{now.second:02d}", key="cond", px=32, color_=TEXT_DIM, weight=500, align=R)
        text(p, right - ss_w - 6, y, now.strftime("%H:%M"), key="cond", px=84, weight=500,
             spacing=0.02, align=R)
        dx = right - ss_w - 6 - hm_w - 20
        date = f"{PT_DAYS[now.weekday()]} {now.day:02d} {PT_MONTHS[now.month - 1]} {now.year}"
        label(p, dx, 100, date, px=14, color_=TEXT, align=R)
        text(p, dx, 74, JP_DAYS[now.weekday()], key="jp", px=16, color_=TEXT_DIM, align=R)
        label(p, SCENE.left() + 24, Y2 + 57, f"rec ● {now:%H:%M}")

    # ---------------------------------------------------------------- coluna esquerda

    def _g_fps(self, p, snap, now, s):
        r = CARD_FPS
        x = r.left() + 20
        top = r.top() + 19 + 28.8 + 8
        y = baseline("cond", 96, top, 96 * 0.9, 500)
        if snap.fps is None:
            text(p, x, y, NA, key="cond", px=96, color_=LINE_STRONG, weight=500)
            yb = top + 86.4 + 8 + 20
            w = heading(p, x, yb, "No signal", px=20, color_=TEXT_DIM).width()
            text(p, x + w + 12, yb, "ゲーム未検出", key="jp", px=14, color_=TEXT_DIM)
            return
        text(p, x, y, num(snap.fps), key="cond", px=96, weight=500)
        ly = top + 86.4 + 8 + 12
        lx = x
        for k, v in (("avg", snap.fps_avg), ("min", snap.fps_min), ("max", snap.fps_max)):
            lx += label(p, lx, ly, f"{k} {num(v)}").width() + 16
        vals = list(snap.fps_series)
        if len(vals) >= 2:
            lo, hi = min(vals), max(vals)
            pad = max(1.0, (hi - lo) * 0.15)
            kit.sparkline(p, QRectF(x, ly + 10, r.width() - 40, r.bottom() - 18 - ly - 10), vals, TEXT, 1.2,
                          vmin=max(0.0, lo - pad), vmax=hi + pad, n=max(60, len(vals)))

    def _g_net(self, p, snap, now, s):
        r = CARD_NET
        x0, x1 = r.left() + 20, r.right() - 20
        up = snap.net_down is not None or snap.net_up is not None
        text(p, x1, r.top() + 37, "接続中" if up else "未接続", key="jp", px=12, color_=TEXT_DIM,
             spacing=0.08, align=R)
        gap = (r.height() - 30 - 26.4 - 15.8 - 30) / 2
        ly = baseline("mono", 12, r.top() + 15 + 26.4 + gap)
        w = label(p, x0, ly, f"↓ {rate(snap.net_down)}", color_=TEXT if up else TEXT_DIM, upper=False).width()
        label(p, x0 + w + 20, ly, f"↑ {rate(snap.net_up)}", color_=TEXT if up else TEXT_DIM, upper=False)
        vals = list(snap.net_series)
        if len(vals) >= 2:
            hi = max(max(vals), 1.0)
            kit.sparkline(p, QRectF(x0, r.bottom() - 15 - 30, r.width() - 40, 30), vals, TEXT_DIM, 1.0,
                          vmin=0.0, vmax=hi * 1.1, n=max(60, len(vals)))

    # ---------------------------------------------------------------- centro

    def _g_mood(self, p, snap, now, s):
        draw_mood(p, MOOD_MAIN, snap)

    def _g_talk(self, p, snap, now, s):
        chip = state_chip(p, SIDE_X, CHIP_TOP, snap)
        top = chip.bottom() + 14
        wdt = SIDE_R - SIDE_X
        if snap.caption:
            wrapped(p, QRectF(SIDE_X, top, wdt, TALK.bottom() - top), snap.caption, px=16,
                    line_h=27.2, max_lines=max(1, int((TALK.bottom() - top) // 27.2)))
            return
        jp, en = talk_lines(snap)
        for i, ln in enumerate(jp):
            text(p, SIDE_X, baseline("jp", 16, top + i * 27.2, 27.2), ln, key="jp", px=16, max_w=wdt)
        wrapped(p, QRectF(SIDE_X, top + 2 * 27.2 + 14, wdt, 60), en, key="mono", px=12, color_=TEXT_DIM,
                spacing=0.08, line_h=19.2, max_lines=3)

    def _g_history(self, p, snap, now, s):
        r = HIST
        chart = QRectF(r.left() + 20, r.top() + 17 + 26.4 + 10, 504, 0)
        chart.setBottom(r.bottom() - 17 - 14.5 - 10)
        for f in (0.25, 0.5, 0.75):
            gy = chart.top() + chart.height() * f
            p.fillRect(QRectF(chart.left(), gy, chart.width(), 1), color(SEG_OFF))
        p.fillRect(QRectF(chart.left(), chart.top(), 1, chart.height()), color(LINE))
        p.fillRect(QRectF(chart.left(), chart.bottom() - 1, chart.width(), 1), color(LINE))
        plot = chart.adjusted(1, 0, 0, -1)
        for k, col, wd in (("ram", RAM, 1.0), ("gpu", GPU, 1.4), ("cpu", CPU, 1.4)):
            vals = snap.history.get(k) or []
            if len(vals) >= 2:
                kit.sparkline(p, plot, vals, col, wd, n=max(120, len(vals)))
        y = r.bottom() - 17 - 3
        axis = snap.history_axis
        if not axis:
            label(p, chart.left(), y, NA, px=11)
            return
        for frac, hhmm in axis:
            al = L if frac <= 0 else R if frac >= 1 else C
            lw = width(hhmm, "mono", 11, None, 0.08)
            x = chart.left() + (frac * chart.width() if al != C else lw / 2 + frac * (chart.width() - lw))
            label(p, x, y, hhmm, px=11, align=al)

    def _g_spec(self, p, snap, now, s):
        sx = SPEC.left() + 20
        y = SPEC.top() + 17 + 26.4 + 10
        rows = snap.specs[:6] or [("cpu", NA)]
        for i, (k, v) in enumerate(rows):
            yb = baseline("mono", 12, y + i * 20.8)
            label(p, sx, yb, k, px=11)
            text(p, sx + 56, yb, v or NA, px=12, max_w=264)
        py = SPEC.top() + 217
        n = min(3, max(2, len(snap.pilots)))
        for i in range(n):
            r = QRectF(sx, py + i * 33.8, 320, 27.8)
            yb = baseline("mono", 12, r.top() + 6)
            if i < len(snap.pilots):
                pl = snap.pilots[i]
                p.setPen(color(LINE_STRONG))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
                x = sx + 11 + label(p, sx + 11, yb, f"{i + 1:02d}").width() + 14
                bat = num(pl.battery, suffix="%")
                try:
                    low = float(pl.battery) < 30
                except (TypeError, ValueError):
                    low = False
                bat_txt = bat
                bw = width(bat_txt, "mono", 12) + (14 if pl.charging else 0)
                x += text(p, x, yb, pl.name, max_w=320 - 22 - bw - 60 - (x - sx)).width() + 8
                if pl.conn:
                    label(p, x, yb, pl.conn.lower())
                bc = color(WARN) if (pl.charging or low) and pl.battery is not None else \
                    color(TEXT if pl.battery is not None else TEXT_DIM)
                tw = text(p, r.right() - 11, yb, bat_txt, align=R, color_=bc).width()
                if pl.charging:  # ⚡ desenhado (a JetBrains Mono não tem o glifo)
                    _bolt(p, QPointF(r.right() - 11 - tw - 8, yb - 4.5), bc)
            else:
                pen = QPen(color(LINE), 1, Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
                x = sx + 11 + label(p, sx + 11, yb, f"{i + 1:02d}").width() + 10
                w = text(p, x, yb, "未接続", key="jp", px=12, color_=TEXT_DIM, spacing=0.08).width()
                label(p, x + w + 6, yb, "— empty", upper=False)

    def _g_magi(self, p, snap, now, s):
        lit = led_lit(snap)
        b = LED_BTN
        p.fillRect(b, color(BUTTON))
        p.setPen(color(snap.led_rgb) if lit else color(LINE_STRONG))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(b.adjusted(0.5, 0.5, -0.5, -0.5))
        led_dot(p, QPointF(b.left() + 20, b.center().y()), 5, snap)
        yb = b.center().y() + 4.5
        w = text(p, b.left() + 35, yb, "点灯" if lit else "消灯", key="jp", px=12, spacing=0.08).width()
        label(p, b.left() + 35 + w + 10, yb, f"led {'on' if lit else 'off'}", color_=TEXT)
        units = (
            (CPU, ("負荷 load", snap.cpu, None, num(snap.cpu, suffix="%")),
             ("温度 temp", snap.cpu_temp, 15, num(snap.cpu_temp, suffix="°"))),
            (GPU, ("負荷 load", snap.gpu, None, num(snap.gpu, suffix="%")),
             ("温度 temp", snap.gpu_temp, 15, num(snap.gpu_temp, suffix="°"))),
            (RAM, ("映像 vram", snap.vram, None, (snap.vram_txt or NA).replace("--", NA)),
             ("主記 ram", snap.ram, None, snap.ram_txt or NA)),
        )
        name_w, key_w, val_w = unit_columns()
        for r, (name, sub), (base, row1, row2) in zip(UNITS, UNIT_NAMES, units, strict=True):
            t = tint(base, snap.led_rgb, lit)
            p.fillRect(r, t.bg)
            p.setPen(t.border)
            p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
            ih = r.height() - 26
            off = (ih - 46.6) / 2
            x = r.left() + 15
            heading(p, x, baseline("cond", 24, r.top() + 13 + off, None, 600), name, px=24, color_=t.color)
            label(p, x, baseline("mono", 12, r.top() + 13 + off + 28.8 + 2), sub)
            bx = x + name_w + UNIT_GAP
            seal_x = r.right() - 15 - 70
            vx = seal_x - UNIT_GAP  # borda direita do valor
            seg_x = bx + key_w + ROW_GAP
            seg_w = vx - val_w - ROW_GAP - seg_x
            for j, (k, v, wf, val) in enumerate((row1, row2)):
                cy = r.top() + 13 + (ih - 47) / 2 + 9.25 + j * 28.5
                text(p, bx, cy + 4.5, k, key="jp", px=12, color_=TEXT_DIM, spacing=0.08)
                kit.segments(p, QRectF(seg_x, cy - 6, seg_w, 12), 20, v or 0.0, t.seg, warn_from=wf)
                text(p, vx, cy + 5, val, px=14, align=R, color_=TEXT if v is not None else TEXT_DIM)
            kit.seal(p, QRectF(seal_x, r.top() + 1, 70, r.height() - 2), t.color)

    def _g_self(self, p, snap, now, s):
        """Rodapé do MAGI system: o que a própria Condessa gasta (CPU/RAM/GPU/VRAM)."""
        pairs = self_line(snap)
        if pairs is None:
            return
        r = SELF_ROW
        yb = r.center().y() + 4.5
        x = r.left() + 15 + label(p, r.left() + 15, yb, "condessa", color_=TEXT).width() + 8
        text(p, x, yb, "自己", key="jp", px=12, color_=TEXT_DIM, spacing=0.08)
        x = r.right() - 15
        for i, (k, v) in enumerate(reversed(pairs)):
            x -= text(p, x, yb + 0.5, v, px=13, color_=TEXT, align=R).width() + 6
            x -= label(p, x, yb, k, align=R).width()
            if i < len(pairs) - 1:
                x -= 10 + label(p, x - 10, yb, "·", align=R).width() + 10

    def _g_player(self, p, snap, now, s):
        t = snap.track
        active = t is not None and bool(t.title)
        label(p, NP.right() - 21, NP.top() + 41, "● spotify" if active else "○ spotify",
              color_=GPU if active else TEXT_DIM, upper=False, align=R)
        draw_cover(p, COVER, t.cover if active else None, s, 28, 12, 7)
        x, wdt = NP_X, NP_R - NP_X
        y0 = COVER.top() + 4
        if active:
            text(p, x, baseline("cond", 22, y0, 24, 500), t.title, key="cond", px=22, weight=500, max_w=wdt)
            text(p, x, baseline("mono", 12, y0 + 30), t.artist or NA, px=12, max_w=wdt,
                 color_=TEXT if t.artist else TEXT_DIM)
            alb = " · ".join(str(v) for v in (t.album, t.year) if v) or NA
            label(p, x, baseline("mono", 11, y0 + 50), alb, px=11, upper=False, max_w=wdt)
        else:
            text(p, x, baseline("cond", 22, y0, 24, 500), NA, key="cond", px=22, weight=500,
                 color_=LINE_STRONG)
            label(p, x, baseline("mono", 11, y0 + 50), "nada tocando", px=11, upper=False)
        bx, bw, by = NP.left() + 21, NP_R - NP.left() - 21, NP_BAR
        p.fillRect(QRectF(bx, by, bw, 3), color(LINE))
        if active and t.position is not None and t.length:
            frac = min(1.0, max(0.0, t.position / t.length))
            p.fillRect(QRectF(bx, by, bw * frac, 3), color(WARN))
        ty = by + 3 + 6 + 11.5
        label(p, bx, ty, mmss(t.position) if active else NA, px=11)
        label(p, NP_R, ty, mmss(t.length) if active else NA, px=11, align=R)
        playing = active and t.playing
        ic = color(TEXT) if active else color(TEXT_DIM)
        for k, r in BTNS.items():
            _btn(p, r, active)
            _icon(p, r, ("pause" if playing else "play") if k == "playpause" else k, ic)
        ex = NP_R - (len(EQ) * 4 + (len(EQ) - 1) * 3)
        for i, h in enumerate(EQ):
            hh = h if playing else 4
            p.fillRect(QRectF(ex + i * 7, BTN_Y + 44 - hh, 4, hh), color(LINE_STRONG))

    def _g_radio(self, p, snap, now, s):
        x, wdt = RADIO.left() + 21, RADIO.width() - 42
        y = RADIO.top() + 60
        if not snap.news:
            label(p, x, y + 14, "nenhuma notícia ainda", upper=False)
            label(p, x, y + 36, 'diga "novidades"', upper=False, color_=TEXT_DIM)
            return
        for i, (hhmm, title) in enumerate(snap.news[:RADIO_ITEMS]):
            card = QRectF(x, y + i * (RADIO_CARD_H + 8), wdt, RADIO_CARD_H)
            first = i == 0
            p.fillRect(card, color(BUTTON))
            bar = color(CPU if first else LINE_STRONG)
            p.fillRect(QRectF(card.left(), card.top(), 3, card.height()), bar)
            label(p, card.left() + 12, card.top() + 16, hhmm, px=10, color_=CPU if first else TEXT_DIM)
            wrapped(p, QRectF(card.left() + 12, card.top() + 21, card.width() - 20, RADIO_CARD_H - 24), title,
                    key="mono", px=12, color_=TEXT if first else TEXT_DIM, line_h=15, max_lines=2)

    def _g_claude(self, p, snap, now, s):
        x, x1 = CLAUDE.left() + 21, CLAUDE.right() - 21
        y = CLAUDE.top() + 60
        c = snap.claude
        if c is None or c.tokens is None:
            label(p, x, y + 14, "sem dados do claude code", upper=False)
            return
        if c.window_end:
            label(p, x, y + 10, f"janela 5h · até {c.window_end}", px=11)
            text(p, x, baseline("cond", 30, y + 16, 32, 500), human_tokens(c.window_fresh), key="cond", px=30,
                 weight=500)
            label(p, x1, y + 34, f"+{human_tokens(c.window_cache)} cache", px=11, align=R, upper=False)
        else:
            label(p, x, y + 10, "janela 5h · livre", px=11)
            text(p, x, baseline("cond", 30, y + 16, 32, 500), "0", key="cond", px=30, weight=500)
        label(p, x, y + 66, f"hoje {human_tokens(c.tokens)} novos · {c.replies} resp", px=11, upper=False,
              color_=TEXT_DIM)
        y += 78
        p.fillRect(QRectF(x, y, x1 - x, 1), color(LINE))
        label(p, x, y + 18, f"sessões · {c.running} rodando", px=11)
        y += 26
        if not c.sessions:
            label(p, x, y + 14, "nenhuma ativa", upper=False, color_=TEXT_DIM)
        for proj, running, ago in c.sessions[:3]:
            dot = "●" if running else "○"
            label(p, x, y + 14, f"{dot} {proj}", upper=False, color_=GPU if running else TEXT_DIM, max_w=230)
            label(p, x1, y + 14, "agora" if ago < 1 else f"{ago} min", px=11, align=R, upper=False)
            y += 22
        if c.autofix:
            yb = CLAUDE.bottom() - 26
            p.fillRect(QRectF(x, yb - 18, x1 - x, 1), color(LINE))
            label(p, x, yb, c.autofix, px=11, upper=False, color_=WARN, max_w=x1 - x)

    # ---------------------------------------------------------------- rodapé

    def _g_footer(self, p, snap, now, s):
        msg = " · ".join(snap.events) if snap.events else NA
        lw = width("MAGI", "cond", 16, 600, 0.04) + 12 + \
            width("MULTI AGENT GUIDANCE INTERFACE", "mono", 12, None, 0.08)
        rw = width("META+M · PAINEL COMPLETO", "mono", 12, None, 0.08)
        left, right = X1 + lw + 40, 1892 - rw - 40
        label(p, (left + right) / 2, 1042, msg, upper=False, align=C, max_w=right - left)

    # ---------------------------------------------------------------- cliques

    def hit_rects(self, snap: Snapshot | None = None) -> dict[str, QRectF]:
        # unidades MAGI abrem o detalhe por processo (antes eram os cards CPU/GPU/RAM da esquerda)
        return {"led": LED_BTN, **BTNS, "card:cpu": UNITS[0], "card:gpu": UNITS[1], "card:ram": UNITS[2]}


__all__ = ["MainScreen", "NA", "Pilot", "Screen", "Snapshot", "Track", "accent", "draw_mood", "led_lit",
           "mood_color"]
