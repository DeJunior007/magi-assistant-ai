"""Painel completo "wired" (nova UI, 2026-10-08): composição dos cards do mockup aprovado
(``docs/design/nova-ui/painel.dc.html``, desenhado em 1672×941) com os dados (U2 + HUD).

Entrada desacoplada: um `Snapshot` com tudo o que a tela mostra; campo `None`/vazio vira "– –"
ou estado vazio (R23.3) — nada é simulado aqui. Desenho na grade lógica 1920×1080 com
`painter.scale(size.width() / 1920)` (2560×1440 → 4/3); os cards são desenhados nas medidas do
mockup com mais um `scale(F)` (F = 1920/1672).

Desempenho (R23.8): fundo, cards, rótulos fixos e a moldura do KONSOLE ficam num QPixmap do
tamanho do dispositivo (cache por tamanho). O resto é dividido em grupos com retângulo próprio;
`dirty_regions(snap, now, size)` compara a chave de cada grupo com a do último desenho e devolve só
os retângulos (pixels do dispositivo) que mudaram — o relógio todo segundo, os dados quando mudam.
O mascote anima à parte: `mascot_tick(mono, size)` diz quando e onde redesenhar. No `paintEvent`,
passe `region=event.rect()` para `paint`: o fundo sai do cache e só os grupos tocados são
redesenhados; por cima vão as scanlines e a vinheta (também em cache).

`hit_test(pos, size)` devolve "learning" (botão do topo), "led", "prev", "playpause", "next",
"card:cpu", "card:gpu", "card:ram" (as unidades MELCHIOR/BALTHASAR/CASPER), "konsole" (o card do
terminal) ou None (pos em pixels do dispositivo).
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)

from . import fonts, kit, scene, sky
from . import learning_summary as lsum
from .caption_scroll import CaptionScroll
from .mascot import Mascot
from .theme import (
    BG,
    BUTTON_LINE,
    CPU,
    FOCUS,
    GPU,
    HOT,
    LINE_STRONG,
    SEG_OFF,
    TEXT,
    TEXT_DIM,
    WARN,
    alpha,
    color,
    mix,
)
from .typewriter import Typewriter

log = logging.getLogger(__name__)

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
    chip: str | None = None  # fase do turno (turn_phase) p/ o chip; None = pela expressão
    mood: int | None = None  # termômetro de humor 0 (pega leve) .. 4 (pode zoar), R13.7; None = sem dado
    # medidor dela (acordo §6, spec §10): ânimo −1..+1 na cor do fundo, o momento e as 3 últimas causas
    mood_dela: float | None = None  # None = sem dado (cai no termômetro antigo)
    mood_dela_cor: str | None = None  # estado.COR_FAIXA; None = acento
    momento: str | None = None  # vida.Momento (valor)
    causas: tuple = ()  # até 3, a mais nova por último: (texto, Δ ânimo, há quantos s)
    news: list[tuple[str, str]] = field(default_factory=list)  # Rádio Ayanami: (HH:MM, manchete), novas 1º
    claude: Any = None  # data.ClaudeView: consumo e sessões do Claude Code; None = sem dado
    lm_on: bool = False  # Learning Mode ligado (``LearningModel.mode_on``; momento Estudando/No flow)
    self_usage: Any = None  # data.SelfView: cpu/ram/gpu/vram dos processos da Condessa; None = sem dado
    # extras da nova UI (data.SysExtra, data.net_info, data.GitStatus); None = sem dado
    cpu_mhz: float | None = None
    swap_used_gb: float | None = None
    swap_total_gb: float | None = None
    disk_pct: float | None = None
    net_ip: str | None = None
    net_gateway: str | None = None
    net_dns: str | None = None
    project: str | None = None  # pasta da sessão do KONSOLE
    git_branch: str | None = None
    git_added: int | None = None
    git_removed: int | None = None
    git_head: str | None = None  # hash curto do HEAD (data.GitStatus.head); reação 75
    turn_tag: tuple[str, float] | None = None  # (tag do turno, time.monotonic() da chegada); R2.B
    volume: tuple[float, bool] | None = None  # (pct 0–150, mudo) do wpctl; None sem wpctl; R2.D
    notif: tuple[int, int, float] | None = None  # (contador, urgência 0–2, monotônico); R2.E
    fan: tuple[float, float] | None = None  # (rpm, média 5 min) do hwmon; R2.G
    reinicio: bool | None = None  # dnf needs-restarting -r: True = precisa; None = sem dado; R2.G
    captura: float | None = None  # mtime (epoch) da captura de tela mais nova; None sem pasta; R2.G
    konsole_online: bool | None = None  # sessão do Claude Code viva no KONSOLE
    konsole_rev: int = 0  # muda quando o terminal tem tela nova (repinta o miolo)


def led_lit(snap: Snapshot) -> bool:
    return bool(snap.led_on and snap.led_rgb)


# chip de estado da Condessa: ouvindo/pensando acendem na cor de foco (o Pedro vê quando ela ativou)
CHIP_STATES = {"listening": "Listening · 聴取中", "thinking": "Thinking · 思考中",
               "speaking": "Speaking · 発話中"}


def chip_label(snap: Snapshot) -> tuple[str, str, bool]:
    """(texto, cor, aceso) do chip: ouvindo/pensando/falando, senão jogando (Active) ou Standby.
    A fase vem de ``snap.chip`` (``turn_phase``, estável nas transições); sem ela, da expressão."""
    lbl = CHIP_STATES.get(snap.chip if snap.chip is not None else snap.magui_state)
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


def wrap_lines(s: str, w: float, *, key: str = "jp", px: float = 16, spacing: float = 0.0) -> list[str]:
    """Quebra ``s`` em linhas de até ``w`` (por palavra; palavra longa por caractere)."""
    fm = _metrics(key, px, None, spacing)
    words, lines = s.split(), []
    cur = ""
    for wd in words:  # quebra por palavra; palavra (ou frase CJK) longa quebra por caractere
        cand = f"{cur} {wd}" if cur else wd
        if fm.horizontalAdvance(cand) <= w:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in wd:
            if fm.horizontalAdvance(cur + ch) > w and cur:
                lines.append(cur)
                cur = ""
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def wrapped(p: QPainter, rect: QRectF, s: str, *, key: str = "jp", px: float = 16, color_=TEXT,
            spacing: float = 0.0, line_h: float | None = None, max_lines: int = 4) -> None:
    """Texto com quebra de linha (o Qt quebra também entre ideogramas) e reticências na última."""
    f = fonts.font(key, px, None, spacing)
    fm = _metrics(key, px, None, spacing)
    lh = line_h or fm.height()
    lines = wrap_lines(s, rect.width(), key=key, px=px, spacing=spacing)
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


# ====================================================================== medidor dela (acordo §6)

MOMENTO_NOME = {"conversa": "conversa", "alerta": "alerta", "jogando": "pilotando", "esperando": "esperando",
                "no_flow": "no flow", "trabalhando_junto": "trabalhando junto", "estudando": "estudando",
                "curtindo": "curtindo", "aturando": "aturando", "ouvindo": "ouvindo",
                "pedro_sumiu": "Pedro sumiu", "tedio": "tédio", "a_toa": "à toa"}
TIP_W, TIP_LINE, TIP_PAD = 250.0, 17.0, 8.0  # caixa das causas no hover


def momento_nome(m: str | None) -> str:
    return "" if not m else MOMENTO_NOME.get(str(m), str(m).replace("_", " "))


def mood_dela_color(snap: Snapshot) -> QColor:
    return color(snap.mood_dela_cor) if snap.mood_dela_cor else accent(snap)


def mood_dela_key(snap: Snapshot) -> tuple:
    v = None if snap.mood_dela is None else round(max(-1.0, min(1.0, snap.mood_dela)), 2)
    return (v, mood_dela_color(snap).rgb(), snap.momento)


def draw_mood_dela(p: QPainter, r: QRectF, snap: Snapshot, *, px: float = 9, bar_w: float = 3.0) -> None:
    """Barra vertical do ânimo dela (−1 embaixo, 0 no meio, +1 no topo) na cor do fundo e, embaixo, o
    nome do momento escrito de lado. O comprimento da barra carrega o valor, não só a cor."""
    nome = momento_nome(snap.momento)
    name_h = tw(nome, "mono", px) + 8 if nome else 0.0
    top, bottom = r.top() + 2, r.bottom() - name_h - 2
    cx = r.center().x()
    p.fillRect(QRectF(cx - bar_w / 2, top, bar_w, bottom - top), color("#1d1b28"))
    mid = (top + bottom) / 2
    p.fillRect(QRectF(cx - bar_w, mid, 2 * bar_w, 1), color(TEXT_DIM))  # o zero
    if snap.mood_dela is not None:
        v = max(-1.0, min(1.0, snap.mood_dela))
        y = mid - v * (bottom - top) / 2
        col = mood_dela_color(snap)
        p.fillRect(QRectF(cx - bar_w / 2, min(y, mid), bar_w, abs(mid - y)), alpha(col, 170))
        p.fillRect(QRectF(cx - bar_w - 1, y - 0.5, 2 * bar_w + 2, 1.5), col)
    if nome:
        p.save()
        p.translate(cx, r.bottom() - 2)
        p.rotate(-90)
        text(p, 0, px * 0.35, nome, px=px, color_=TEXT_DIM, align=L)
        p.restore()


def _ha(seg: float) -> str:
    seg = max(0.0, float(seg))
    if seg < 60:
        return "agora"
    if seg < 3600:
        return f"há {int(seg // 60)} min"
    return f"há {int(seg // 3600)} h"


def causas_linhas(causas) -> list[str]:
    """As 3 últimas causas, a mais nova em cima: ``+0,30 Ado · há 2 min``."""
    out = []
    for texto, delta, ha in list(causas)[-3:][::-1]:
        out.append(f"{delta:+.2f}".replace(".", ",") + f" {texto} · {_ha(ha)}")
    return out


def tip_rect(anchor: QRectF, n: int = 3) -> QRectF:
    """Caixa das causas à esquerda do medidor (à direita, se não couber), rente ao pé dele."""
    h = 2 * TIP_PAD + max(1, n) * TIP_LINE
    x = anchor.left() - 8 - TIP_W
    if x < 0:
        x = anchor.right() + 8
    return QRectF(x, anchor.bottom() - h, TIP_W, h)


def draw_causas(p: QPainter, box: QRectF, causas) -> None:
    linhas = causas_linhas(causas) or ["sem causa ainda"]
    p.fillRect(box, alpha(color(M_PANEL), 235))
    p.setPen(color(LINE_STRONG))
    p.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5))
    for i, ln in enumerate(linhas):
        text(p, box.left() + TIP_PAD, box.top() + TIP_PAD + (i + 0.75) * TIP_LINE, ln, px=11, color_=TEXT,
             max_w=box.width() - 2 * TIP_PAD)


# ====================================================================== base


class Screen:
    """Base das duas telas: cache da camada estática, grupos com chave e retângulo, mascote."""

    MASCOT_RECT = QRectF()
    SCENE_KIND = "main"

    def __init__(self, mascot: Mascot | None = None, anim: scene.SceneAnimator | None = None):
        self.mascot = mascot or Mascot("sleeping")
        self.anim = anim or scene.SceneAnimator(self.SCENE_KIND)
        self.sky = sky.NIGHT
        # camada estática: (tamanho + céu, {variante: pixmap}); a variante é da tela (ex.: o painel
        # com o Konsole expandido no lugar do cam 01) e trocar de variante não invalida as outras
        self._static: tuple[tuple, dict[tuple, QPixmap]] | None = None
        self._keys: dict[str, tuple] = {}
        self._snap: Snapshot | None = None
        self.hover: str | None = None  # área sob o ponteiro (``hover_rects``), ex.: "mood"

    def hover_rects(self) -> dict[str, QRectF]:
        """Áreas com hover: o medidor mostra as 3 últimas causas (acordo §6)."""
        mood = self.groups().get("mood")
        return {"mood": mood[0]} if mood else {}

    def hover_test(self, pos: QPoint | QPointF, size: QSize) -> str | None:
        s = self.scale(size)
        pt = QPointF(pos.x() / s, pos.y() / s)
        return next((n for n, r in self.hover_rects().items() if r.contains(pt)), None)

    def set_hover(self, name: str | None) -> bool:
        """Muda a área em hover; True se mudou (quem chama pede repintura pelo ``dirty_regions``)."""
        changed = name != self.hover
        self.hover = name
        return changed

    def tip_key(self, snap: Snapshot) -> tuple:
        on = self.hover == "mood" and snap.mood_dela is not None
        return (on, tuple(causas_linhas(snap.causas)) if on else ())

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

    def static_variant(self) -> tuple:
        """Variante da camada estática (as duas ficam em cache: alternar não refaz o fundo)."""
        return ()

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
            self._static = (key, {})
            self._keys.clear()
        var = self.static_variant()
        pm = self._static[1].get(var)
        if pm is None:
            s = self.scale(size)
            pm = QPixmap(size)
            pm.fill(color(BG))
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            p.scale(s, s)
            self.draw_static(p, s)
            p.end()
            self._static[1][var] = pm
        return pm

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

    def group_rects(self, name: str, size: QSize | None = None) -> list[QRect]:
        """Retângulos (dispositivo) do grupo ``name``: para invalidar só ele (ex.: a legenda)."""
        s = self.scale(size or QSize(round(W), round(H)))
        return [dev_rect(r, s) for r in self.groups().get(name, ())]

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


# ====================================================================== geometria do painel (nova UI)
#
# Fonte da verdade: docs/design/nova-ui/painel.dc.html, desenhado em 1672×941. Tudo aqui é medido
# em coordenadas do mockup e convertido para a base 1920 pelo fator F (o painter desenha os cards
# com ``p.scale(F, F)``, então fontes, traços e espaçamentos saem na proporção exata do mockup).
# Caixas de clique e de repintura (base 1920) vêm de ``mq`` (arredondadas a 0,5 px).

MOCK_W, MOCK_H = 1672.0, 941.0
F = W / MOCK_W  # 1,14833


def _h(v: float) -> float:
    return round(v * F * 2) / 2


def mq(x: float, y: float, w: float, h: float) -> QRectF:
    """Caixa do mockup (x, y, w, h) → base 1920, arredondada a 0,5 px."""
    return QRectF(_h(x), _h(y), _h(x + w) - _h(x), _h(y + h) - _h(y))


# paleta do mockup
M_BG = "#09080f"
M_PANEL = "#0e0d15"
M_LINE = "#262333"
M_RULE = "#221f2e"
M_TEXT = "#e2deee"
M_TEXT2 = "#ddd8ea"
M_BRIGHT = "#f1eef8"
M_DIM = "#a39eb8"
M_LILAC = "#b49af0"
M_GREEN = "#5fd38d"
M_SPARK = "#8f89a6"
M_OFF = "#222030"  # barra apagada
M_DARK = "#4a4560"  # LED/LEARNING apagados, borda do chip parado
M_TERM_BG = "#08070d"
M_TERM_IDLE = "#3d3752"
M_OK_LINE = "#2a2738"
LH = {"mono": 1.32, "cond": 1.2, "jp": 1.448, "mincho": 1.448}  # line-height "normal" (em)

# caixas do mockup (x, y, w, h)
B_MAGI = (23, 125, 440, 353)
B_ACT = (23, 493, 440, 218)
B_NET = (23, 727, 440, 132)
B_CAM = (482, 125, 509, 428)
B_HIST = (482, 572, 509, 287)
B_COND = (1012, 125, 310, 428)
B_SPEC = (1012, 572, 310, 287)
B_NP = (1340, 125, 310, 240)
B_RADIO = (1340, 381, 310, 128)
B_KON = (1340, 526, 310, 333)
MAGI = mq(*B_MAGI)
CARD_ACT = mq(*B_ACT)
CARD_NET = mq(*B_NET)
CAM = mq(*B_CAM)
SCENE = CAM  # o "cam 01" ocupa o card inteiro (o detalhe por processo cobre esta área)
HIST = mq(*B_HIST)
CONDESSA = mq(*B_COND)
SPEC = mq(*B_SPEC)
NP = mq(*B_NP)
RADIO = mq(*B_RADIO)
KONSOLE = mq(*B_KON)
CARDS = {"magi": MAGI, "activity": CARD_ACT, "network": CARD_NET, "cam": CAM, "history": HIST,
         "condessa": CONDESSA, "spec": SPEC, "player": NP, "radio": RADIO, "konsole": KONSOLE}
TOP_RULE_Y, FOOT_RULE_Y = 100.0, 876.0  # linhas do topo e do rodapé (mockup)

# topo: botão LEARNING no lugar dos indicadores (LM1.7)
B_LEARN = (1068, 30, 196, 52)
LEARN_BTN = mq(*B_LEARN)
LEARN_W = LEARN_BTN.width()
B_CLOCK = (1296, 18, 356, 74)  # data + relógio (alinhados à direita em 1650)
HEADER_CLOCK = mq(*B_CLOCK)

# MAGI SYSTEM: botão LED + três unidades de 84 (space-between no conteúdo de 323)
_MX, _MY, _MW = 38.0, 140.0, 410.0
LED_ROW_H = 2 + 16 + 11 * LH["jp"]  # borda + padding + linha do 消灯 (11 px)
_UGAP = (323 - LED_ROW_H - 3 * 84) / 3
U_BOXES = [(_MX, _MY + LED_ROW_H + _UGAP + i * (84 + _UGAP), _MW, 84.0) for i in range(3)]
UNITS = [mq(*b) for b in U_BOXES]
LED_W = 2 + 28 + 8 + 8 + 22 + 8 + 7 * 7.0  # "LED OFF" (o mais largo), mono 10 com .1em
B_LED = (_MX + _MW - LED_W, _MY, LED_W, LED_ROW_H)
LED_BTN = mq(*B_LED)
UNIT_NAMES = (("MELCHIOR", "CPU"), ("BALTHASAR", "GPU"), ("CASPER", "MEMORY"))
UNIT_STYLE = (  # (cor, fundo, borda, borda esquerda, cor do 正常)
    (M_LILAC, "#b49af012", "#3d3560", M_LILAC, M_LILAC),
    (M_GREEN, "#5fd38d12", "#2f5c43", M_GREEN, M_GREEN),
    (M_TEXT2, None, M_OK_LINE, M_DARK, M_GREEN),
)
UNIT_BAR_COLOR = (M_LILAC, M_GREEN, M_DIM)
BAR_AREA = 82.0  # 210 do miolo − rótulo 58 − valor 54 − 2 gaps de 8
BARS = int((BAR_AREA + 2) // 6)  # barras de 4 px com gap 2 que cabem (14; o resto o overflow corta)
CLOCK_MAX_MHZ = 5000.0  # escala da barra do clock (5 GHz = cheia)

# SYSTEM ACTIVITY (conteúdo x 40..446, corpo 544..696)
ACT_BODY = (40.0, 544.0, 406.0, 152.0)
ACT_SELF_X = 291.0  # coluna "MAGI 自己 · USO PRÓPRIO"
# NETWORK (corpo 775..846)
NET_BODY = (40.0, 775.0, 406.0, 71.0)

# CONDESSA: retrato 272×272, chip, caixa de terminal com a fala
_CX, _CY = 1013.0, 126.0  # origem da caixa de padding do card (dentro da borda)
B_PORTRAIT = (_CX + 19, _CY + 30, 272, 272)
MASCOT_MAIN = mq(*B_PORTRAIT)
B_GAUGE = (1303.0, _CY + 34, 11.0, 262.0)  # régua "在 … 01" à direita do retrato (humor, R13.7)
MOOD_MAIN = mq(*B_GAUGE)
_TIP = tip_rect(QRectF(*B_GAUGE))
TIP_MAIN = mq(_TIP.x(), _TIP.y(), _TIP.width(), _TIP.height())
B_CHIP = (_CX + 14, _CY + 310, 210.0, 28.25)
CHIP_RECT = mq(*B_CHIP)
CHIP_TOP = CHIP_RECT.top()
B_TALK = (_CX + 12, _CY + 342, 284.0, 74.0)
TALK = mq(*B_TALK)
TALK_PX, TALK_LH = 11, 11 * 1.55  # mono 11, line-height 1.55
TALK_TEXT = (B_TALK[0] + 2 + 12, B_TALK[1] + 1 + 8, 284 - 2 - 1 - 12 - 10, 74 - 2 - 16)  # x, y, w, h
CAPTION_VISIBLE = int(TALK_TEXT[3] // TALK_LH)  # 3 linhas à vista
CAPTION_LH = TALK_LH * F
CAPTION_RECT = mq(TALK_TEXT[0], TALK_TEXT[1], TALK_TEXT[2], CAPTION_VISIBLE * TALK_LH)
# cartão LAST SESSION (LM4.6, P13): coluna da Condessa, abaixo do botão LEARNING e do retrato,
# sobrepondo o topo do card SPEC enquanto visível (nunca o retrato nem o player)
SUMMARY_PX = 11
B_SUMMARY = (B_SPEC[0], B_SPEC[1], B_SPEC[2], lsum.card_height(SUMMARY_PX))
SUMMARY_RECT = mq(*B_SUMMARY)
TALK_PROMPT = "› "

# NOW PLAYING (conteúdo 1357..1633 × 140..350, space-between)
_NPG = (210 - (24 + 80 + 21.2 + 32)) / 3
NP_ROW = 140 + 24 + _NPG
NP_PROG = NP_ROW + 80 + _NPG
NP_CTRL = 350 - 32
B_COVER = (1357.0, NP_ROW, 80.0, 80.0)
COVER = mq(*B_COVER)
B_BTNS = {k: (1357.0 + i * 44, NP_CTRL, 36.0, 32.0) for i, k in enumerate(("prev", "playpause", "next"))}
BTNS = {k: mq(*b) for k, b in B_BTNS.items()}
EQ = (8, 16, 12, 22, 28, 18, 24, 32, 20, 14, 26, 18, 10, 16, 8, 12)  # alturas decorativas do mockup

# RÁDIO AYANAMI
B_REI = (1499.0, 384.0, 146.0, 124.0)
REI_PATH = Path(__file__).resolve().parent.parent / "images" / "rei.png"
RADIO_LINES = 2

# KONSOLE // CLAUDE CODE: moldura aqui, miolo do konsole_view
KON_TITLE_H, KON_TAB_H = 34.0, 24.0
KON_STATUS_H = 1 + 5 + 9.5 * LH["mono"] * 2 + 2 + 5
KON_BODY_TOP = B_KON[1] + 1 + KON_TITLE_H + KON_TAB_H
KON_STATUS_TOP = B_KON[1] + B_KON[3] - 1 - KON_STATUS_H
B_KON_VIEW = (1351.0, KON_BODY_TOP + 8, 280.0, KON_STATUS_TOP - KON_BODY_TOP - 8 - 6)
KONSOLE_VIEW = mq(*B_KON_VIEW)  # área do terminal (konsole_view.paint_compact)
KONSOLE_STATUS = mq(1341, KON_STATUS_TOP, 308, KON_STATUS_H)
KONSOLE_CWD = str(Path(__file__).resolve().parents[2])  # a sessão roda no repositório da MAGI

REC = mq(498, 160, 140, 22)

# Konsole expandido: ele ocupa a caixa do cam 01 e a câmera vai para o lugar do card KONSOLE
# (a Condessa, o LOAD HISTORY e o UNIT SPEC nunca são cobertos)
CAM_SLOT = KONSOLE


def cam_swap_transform() -> QTransform:
    """Base 1920: ``SCENE`` → dentro de ``CAM_SLOT``, escala uniforme que cabe inteira (o cenário
    não é cortado) e centrada; sobra uma faixa em cima e embaixo (o slot é mais alto que largo)."""
    k = min(CAM_SLOT.width() / SCENE.width(), CAM_SLOT.height() / SCENE.height())
    ox = CAM_SLOT.left() + (CAM_SLOT.width() - SCENE.width() * k) / 2
    oy = CAM_SLOT.top() + (CAM_SLOT.height() - SCENE.height() * k) / 2
    return QTransform(k, 0, 0, k, ox - SCENE.left() * k, oy - SCENE.top() * k)


CAM_SWAP_K = cam_swap_transform().m11()
CAM_SWAPPED = cam_swap_transform().mapRect(SCENE)  # onde a câmera fica com o Konsole expandido
LIVE = mq(1540, 400, 94, 22)
FOOTER = mq(23, 884, 1627, 34)
FOOT_Y = 905.0  # linha de base do rodapé


try:  # miolo do KONSOLE (outro módulo; sem ele o miolo fica vazio)
    from . import konsole_view  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001 - módulo ausente ou quebrado não derruba o painel
    konsole_view = None


# ====================================================================== texto (coordenadas do mockup)


def _fs(key: str, px: float, weight: int | None, ls: float) -> tuple[QFont, int]:
    """Fonte e fator: tamanho fracionário (10,5 px) vira fonte 2× desenhada com o painter a ½."""
    k = 1 if float(px).is_integer() else 2
    return fonts.font(key, px * k, weight, ls), k


@lru_cache(maxsize=512)
def _fm(key: str, px: float, weight: int | None, ls: float) -> tuple[QFontMetricsF, int]:
    f, k = _fs(key, px, weight, ls)
    return QFontMetricsF(f), k


def tw(s: str, key: str = "mono", px: float = 11, weight: int | None = None, ls: float = 0.0) -> float:
    """Largura do texto (com o letter-spacing do último glifo, como no CSS)."""
    fm, k = _fm(key, px, weight, ls)
    return fm.horizontalAdvance(s) / k


def asc(key: str, px: float, weight: int | None = None) -> float:
    fm, k = _fm(key, px, weight, 0.0)
    return fm.ascent() / k


def dsc(key: str, px: float, weight: int | None = None) -> float:
    fm, k = _fm(key, px, weight, 0.0)
    return fm.descent() / k


def mid(cy: float, key: str, px: float, weight: int | None = None) -> float:
    """Linha de base de um texto (line-height normal) centrado verticalmente em ``cy``."""
    a, d = asc(key, px, weight), dsc(key, px, weight)
    return cy - (a + d) / 2 + a


def top_base(top: float, key: str, px: float, lh: float | None = None, weight: int | None = None) -> float:
    """Linha de base de uma caixa de linha que começa em ``top`` (``lh`` px; None = normal)."""
    a, d = asc(key, px, weight), dsc(key, px, weight)
    lh = a + d if lh is None else lh
    return top + (lh - (a + d)) / 2 + a


def elide(s: str, max_w: float, key: str = "mono", px: float = 11, weight: int | None = None,
          ls: float = 0.0) -> str:
    if tw(s, key, px, weight, ls) <= max_w:
        return s
    fm, k = _fm(key, px, weight, ls)
    return fm.elidedText(s, Qt.TextElideMode.ElideRight, max_w * k)


def tx(p: QPainter, x: float, y: float, s: str, *, key: str = "mono", px: float = 11, c=M_TEXT,
       weight: int | None = None, ls: float = 0.0, align=L, max_w: float | None = None) -> float:
    """Texto com a linha de base em ``y`` (coordenadas do mockup); devolve a largura."""
    if max_w is not None:
        s = elide(s, max_w, key, px, weight, ls)
    w = tw(s, key, px, weight, ls)
    if align & R:
        x -= w
    elif align & C:
        x -= w / 2
    f, k = _fs(key, px, weight, ls)
    p.save()
    p.setFont(f)
    p.setPen(color(c))
    if k == 1:
        p.drawText(QPointF(x, y), s)
    else:
        p.translate(x, y)
        p.scale(1 / k, 1 / k)
        p.drawText(QPointF(0, 0), s)
    p.restore()
    return w


def title(p: QPainter, x: float, y: float, s: str, jp: str | None = None, *, px: float = 20,
          jp_px: float = 10, ls: float = 0.0, gap: float = 10) -> float:
    """Título de card: Barlow Condensed 600 + o japonês pequeno em text-dim, mesma linha de base."""
    w = tx(p, x, y, s, key="cond", px=px, weight=600, ls=ls, c=M_TEXT)
    if jp:
        w += gap + tx(p, x + w + gap, y, jp, key="jp", px=jp_px, c=M_DIM)
    return w


def box(p: QPainter, r: QRectF, bg=None, border=None, lw: float = 1.0) -> None:
    """Retângulo do mockup: fundo e borda de ``lw`` por dentro (box-sizing: border-box)."""
    if bg is not None:
        p.fillRect(r, color(bg))
    if border is not None:
        b = color(border)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), lw), b)
        p.fillRect(QRectF(r.left(), r.bottom() - lw, r.width(), lw), b)
        p.fillRect(QRectF(r.left(), r.top(), lw, r.height()), b)
        p.fillRect(QRectF(r.right() - lw, r.top(), lw, r.height()), b)


def card(p: QPainter, b: tuple, bg=M_PANEL, border=M_LINE) -> None:
    box(p, QRectF(*b), bg, border)


def dot(p: QPainter, cx: float, cy: float, d: float, c, *, ring: bool = False) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if ring:
        p.setPen(QPen(color(c), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), d / 2 - 0.5, d / 2 - 0.5)
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color(c))
        p.drawEllipse(QPointF(cx, cy), d / 2, d / 2)
    p.restore()


def polyline(p: QPainter, pts, c, w: float) -> None:
    path = QPainterPath(QPointF(*pts[0]))
    for pt in pts[1:]:
        path.lineTo(QPointF(*pt))
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color(c), w)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()


def spark(p: QPainter, r: QRectF, vals, c, w: float, *, vmin: float | None = None,
          vmax: float | None = None, n: int = 60) -> None:
    vals = [v for v in vals]
    nums = [v for v in vals if v is not None]
    if len(nums) < 2:
        return
    lo = min(nums) if vmin is None else vmin
    hi = max(nums) if vmax is None else vmax
    if hi <= lo:
        hi = lo + 1.0
    kit.sparkline(p, r, vals, c, w, vmin=lo, vmax=hi, n=max(n, len(vals)))


@lru_cache(maxsize=1)
def rei_pixmap() -> QPixmap | None:
    pm = QPixmap(str(REI_PATH))
    return None if pm.isNull() else pm


# ====================================================================== formatação dos cards


def short_num(n: int | float | None) -> str:
    """Tokens no estilo do mockup: 950, 12.3K, 2.4M."""
    if n is None:
        return NA
    n = float(n)
    if n >= 1e9:
        return f"{n / 1e9:.1f}B"
    if n >= 1e6:
        return f"{n / 1e6:.1f}M"
    if n >= 1e3:
        return f"{n / 1e3:.1f}K"
    return f"{n:.0f}"


def mb(v: float | None) -> str:
    """MB → "610M" / "1.2G" (arredondado a 10 MB, para o número não piscar à toa)."""
    if v is None:
        return NA
    if v >= 1000:
        return f"{v / 1024:.1f}G"
    return f"{round(v, -1):.0f}M"


def total_gb(txt: str | None) -> float | None:
    """"11.4/32G" → 32.0 (o total do sensor, para as barras do uso próprio)."""
    try:
        return float((txt or "").rstrip("G").split("/")[1])
    except (IndexError, ValueError):
        return None


def self_rows(snap: Snapshot) -> list[tuple[str, str, float]] | None:
    """Linhas "MAGI 自己 · USO PRÓPRIO": [(rótulo, valor, % da máquina)] já arredondados (é também
    a chave do grupo) ou None sem dado. CPU em % do total de núcleos (a barra é relativa à máquina)."""
    u = snap.self_usage
    if u is None:
        return None
    cpu = getattr(u, "cpu_total", None)
    ram_t, vram_t = total_gb(snap.ram_txt), total_gb(snap.vram_txt)
    ram_pct = 100 * u.ram_mb / 1024 / ram_t if ram_t else 0.0
    vram_pct = 100 * u.vram_mb / 1024 / vram_t if vram_t else 0.0
    return [("CPU", num(cpu, suffix="%"), round(cpu or 0.0)),
            ("GPU", num(u.gpu, suffix="%"), round(u.gpu or 0.0)),
            ("RAM", mb(u.ram_mb), round(ram_pct, 1)), ("VRAM", mb(u.vram_mb), round(vram_pct, 1))]


def self_line(snap: Snapshot) -> list[tuple[str, str]] | None:
    """[(rótulo, valor)] do uso próprio (compatível com a linha antiga do MAGI SYSTEM)."""
    rows = self_rows(snap)
    return None if rows is None else [(k.lower(), v) for k, v, _ in rows]


def unit_rows(snap: Snapshot) -> list[list[tuple[str, float | None, int | None, str]]]:
    """As três unidades 3×3: [(rótulo, % da barra, índice do alerta, valor)]."""
    def pct(a, b):
        return None if a is None or not b else 100.0 * a / b

    mhz = snap.cpu_mhz
    swap = NA if snap.swap_total_gb is None else \
        f"{snap.swap_used_gb or 0:.1f}/{snap.swap_total_gb:.0f}G"
    warn = round(BARS * 0.75)
    return [
        [("負荷 load", snap.cpu, None, num(snap.cpu, suffix="%")),
         ("温度 temp", snap.cpu_temp, warn, num(snap.cpu_temp, suffix="°C")),
         ("周波 clock", pct(mhz, CLOCK_MAX_MHZ), None,
          num(None if mhz is None else mhz / 1000, "{:.1f}", "GHz"))],
        [("負荷 load", snap.gpu, None, num(snap.gpu, suffix="%")),
         ("温度 temp", snap.gpu_temp, warn, num(snap.gpu_temp, suffix="°C")),
         ("映像 vram", snap.vram, None, (snap.vram_txt or NA).replace("--", NA))],
        [("主記 ram", snap.ram, None, snap.ram_txt or NA),
         ("交換 swap", pct(snap.swap_used_gb, snap.swap_total_gb), None, swap),
         ("記憶 disk", snap.disk_pct, None, num(snap.disk_pct, suffix="%"))],
    ]


def is_speaking(snap: Snapshot) -> bool:
    return (snap.chip if snap.chip is not None else snap.magui_state) == "speaking"


def main_chip(snap: Snapshot) -> tuple[str, str, str, bool]:
    """(rótulo, japonês, cor, aceso) do chip do card: falando em lilás, ouvindo/pensando na cor de
    foco, parada em branco com borda apagada."""
    lbl, fg, lit = chip_label(snap)
    en, _, jp = lbl.partition(" · ")
    if is_speaking(snap):
        fg = M_LILAC
    elif not lit:
        fg = GPU if snap.gaming else M_BRIGHT
    return f"{en.upper()} ·", jp, fg, lit


def project_label(path: str | None) -> str:
    if not path:
        return NA
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home) else path


# ====================================================================== desenhos pequenos


def draw_learning_btn(p: QPainter, x: float, y: float, *, px: float = 12, color_=TEXT) -> float:
    """``[ LEARNING // 学習 ]`` com a linha de base em ``y`` (tela de espera, LM1.7); devolve a
    largura. Só texto: os colchetes fazem o papel da borda, como o rodapé."""
    x0 = x
    for t, jp in (("[ learning // ", False), ("学習", True), (" ]", False)):
        if jp:
            x += text(p, x, y, t, key="jp", px=px, color_=color_).width()
        else:
            x += label(p, x, y, t, px=px, color_=color_).width()
    return x - x0


def draw_learning_box(p: QPainter, r: QRectF, active: bool = False, sub: str = "ENGLISH · B2") -> None:
    """Botão LEARNING do topo do painel (LM1.7), no lugar dos indicadores: ponto, LEARNING 学習 e a
    linha de baixo. ``r`` na base 1920; desenhado nas medidas do mockup (196×52)."""
    p.save()
    p.translate(r.left(), r.top())
    p.scale(r.width() / B_LEARN[2], r.height() / B_LEARN[3])
    box(p, QRectF(0, 0, B_LEARN[2], B_LEARN[3]), "#b49af01f" if active else M_PANEL,
        M_LILAC if active else "#34304a")
    # coluna centrada: linha 1 (Barlow 19, 22,8) + gap 4 + linha 2 (mono 10, 13,2)
    top = (52 - (22.8 + 4 + 13.2)) / 2
    y1 = top_base(top, "cond", 19, weight=600)
    dot(p, 14 + 3.5, top + 11.4, 7, M_LILAC if active else M_DARK)
    x = 14 + 7 + 10
    x += tx(p, x, y1, "LEARNING", key="cond", px=19, weight=600, ls=0.1, c="#ece8f5") + 10
    tx(p, x, y1, "学習", key="jp", px=13, c=M_DIM)
    tx(p, 14, top_base(top + 22.8 + 4, "mono", 10), sub, px=10, ls=0.12, c=M_DIM)
    p.restore()


def _icon(p: QPainter, r: QRectF, kind: str, c) -> None:
    """Ícones do player do mockup (viewBox 12, traço 1,3), centrados em ``r``."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(r.center().x() - 6, r.center().y() - 6)
    pen = QPen(color(c), 1.3)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def path(*pts, close=True):
        pa = QPainterPath(QPointF(*pts[0]))
        for pt in pts[1:]:
            pa.lineTo(QPointF(*pt))
        if close:
            pa.closeSubpath()
        p.drawPath(pa)

    if kind == "prev":
        p.drawLine(QPointF(3, 2), QPointF(3, 10))
        path((10, 2), (4.5, 6), (10, 10))
    elif kind == "next":
        p.drawLine(QPointF(9, 2), QPointF(9, 10))
        path((2, 2), (7.5, 6), (2, 10))
    elif kind == "pause":
        p.drawLine(QPointF(4, 2), QPointF(4, 10))
        p.drawLine(QPointF(8, 2), QPointF(8, 10))
    else:
        path((3.5, 2), (9.5, 6), (3.5, 10))
    p.restore()


def _term_icon(p: QPainter, x: float, y: float) -> None:
    """Ícone do terminal da barra de título do KONSOLE (viewBox 24 a 15 px)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(x, y)
    p.scale(15 / 24, 15 / 24)
    pen = QPen(color("#c9c3dc"), 1.6)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(3, 4, 18, 16), 1, 1)
    pa = QPainterPath(QPointF(7, 9))
    pa.lineTo(10, 12)
    pa.lineTo(7, 15)
    p.drawPath(pa)
    p.drawLine(QPointF(12, 15), QPointF(17, 15))
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
    """Painel completo (nova UI, docs/design/nova-ui/painel.dc.html)."""

    MASCOT_RECT = MASCOT_MAIN
    MASCOT_DIRTY = MASCOT_MAIN
    CAPTION_RECT = CAPTION_RECT
    SUMMARY_RECT = SUMMARY_RECT
    summary = None  # () -> dict | None: resumo visível agora (o WiredUI liga, LM4.6)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.cap = CaptionScroll(CAPTION_VISIBLE)  # rolagem do terminal da fala (acompanha / lê para trás)
        self.tw = Typewriter()  # a fala digitada 1 caractere por vez
        self._cap_lines: tuple[str, list[str]] = ("", [])
        self._overlay: tuple[tuple, QPixmap] | None = None
        self.clock = time.monotonic  # relógio da animação (os testes trocam)
        self.kon_swap = False  # Konsole expandido na caixa do cam 01; a câmera no slot do card

    # ---------------------------------------------------------------- fala (digitação + rolagem)

    def caption_lines(self, txt: str | None) -> list[str]:
        """Linhas do terminal para o texto já digitado (com o prompt ``›``)."""
        txt = txt or ""
        if self._cap_lines[0] != txt:
            self._cap_lines = (txt, wrap_lines(TALK_PROMPT + txt, TALK_TEXT[2], key="mono", px=TALK_PX)
                               if txt else [])
        return self._cap_lines[1]

    def caption_feed(self, txt: str | None, now: float | None = None) -> bool:
        """Texto novo da fala (o já dito, da ``SpeechCaption``); ``True`` = o terminal precisa
        redesenhar (caractere novo ou rolagem)."""
        now = self.clock() if now is None else now
        changed = self.tw.feed(txt, now)
        shown = self.tw.shown
        changed = self.cap.feed(shown, len(self.caption_lines(shown)), now) or changed
        return changed or self.cap.animating(now)

    def caption_deadline(self, now: float | None = None) -> float | None:
        now = self.clock() if now is None else now
        ds = [d for d in (self.tw.deadline(now), self.cap.deadline(now)) if d is not None]
        return min(ds) if ds else None

    def caption_wheel(self, lines: float, now: float | None = None) -> bool:
        """Roda do mouse no terminal da fala: ``lines`` > 0 volta para ler. ``True`` = rolou."""
        return self.cap.wheel(lines, self.clock() if now is None else now)

    def caption_hit(self, pos: QPoint | QPointF, size: QSize) -> bool:
        s = self.scale(size)
        return TALK.contains(QPointF(pos.x() / s, pos.y() / s))

    # ---------------------------------------------------------------- pintura (+ clima por cima)

    def paint(self, p: QPainter, size: QSize, snap: Snapshot, now: datetime | None = None,
              mono: float | None = None, region: QRect | None = None) -> None:
        """Como ``Screen.paint`` e, por cima da região, a máscara do retrato, as scanlines e a
        vinheta (fora do cache estático: valem também sobre os grupos redesenhados)."""
        super().paint(p, size, snap, now, mono, region)
        full = QRect(0, 0, size.width(), size.height())
        dev = full if region is None else region.intersected(full)
        s = self.scale(size)
        p.save()
        p.setClipRect(dev)
        if dev.intersects(dev_rect(MASCOT_MAIN, s)):
            p.save()
            p.scale(s * F, s * F)
            x, y, w, h = B_PORTRAIT
            g = QLinearGradient(0, y + h * 0.9, 0, y + h)
            g.setColorAt(0.0, alpha(M_PANEL, 0))
            g.setColorAt(1.0, color(M_PANEL))
            p.fillRect(QRectF(x, y + h * 0.9, w, h * 0.1 + 0.5), g)
            p.restore()
        p.drawPixmap(dev, self.overlay(size), dev)
        p.restore()

    def overlay(self, size: QSize) -> QPixmap:
        """Scanlines discretas (1 px a 1,4% de branco a cada 3 px do mockup) + vinheta."""
        key = (size.width(), size.height())
        if self._overlay is None or self._overlay[0] != key:
            pm = QPixmap(size)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            k = size.width() / MOCK_W
            line = QColor(255, 255, 255, round(0.014 * 255))
            y = 0.0
            while y < size.height():
                q.fillRect(QRectF(0, round(y), size.width(), max(1, round(k))), line)
                y += 3 * k
            w, h = size.width(), size.height()
            q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            q.translate(w / 2, h / 2)
            q.scale(1.0, h / w)  # elipse "farthest-corner" do CSS: círculo esticado
            rad = math.hypot(w / 2, w / 2)
            g = QRadialGradient(QPointF(0, 0), rad)
            g.setColorAt(0.0, QColor(0, 0, 0, 0))
            g.setColorAt(0.6, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 0, 0, round(0.4 * 255)))
            q.fillRect(QRectF(-w, -w, 2 * w, 2 * w), g)
            q.end()
            self._overlay = (key, pm)
        return self._overlay[1]

    # ---------------------------------------------------------------- estático

    def draw_static(self, p: QPainter, s: float) -> None:
        p.fillRect(QRectF(0, 0, W, H), color(M_BG))
        p.save()
        p.scale(F, F)
        # ---- topo
        tx(p, 23, top_base(26, "mincho", 40, 40), "汎用監視システム", key="mincho", px=40, ls=0.05,
           c=M_BRIGHT)
        tx(p, 23, top_base(74, "mono", 12), "GENERAL PURPOSE MONITORING SYSTEM -- MAGI-01", px=12, ls=0.14,
           c=M_DIM)
        p.fillRect(QRectF(650, 30, 1, 52), color(M_RULE))
        p.fillRect(QRectF(1039, 30, 1, 52), color(M_RULE))
        h1, h2 = 15 * LH["jp"], 12 * LH["mono"]
        t0 = 30 + (52 - (h1 + 10 + h2)) / 2
        tx(p, 845, top_base(t0, "jp", 15), "私は、ここにいる。", key="jp", px=15, ls=0.18, c=M_TEXT2, align=C)
        tx(p, 845, top_base(t0 + h1 + 10, "mono", 12), "// I AM HERE · NODE 01 ONLINE", px=12, ls=0.12,
           c=M_DIM, align=C)
        p.fillRect(QRectF(23, TOP_RULE_Y, 1650 - 23, 1), color(M_RULE))
        # ---- cards
        for b in (B_MAGI, B_ACT, B_NET, B_HIST, B_COND, B_SPEC, B_NP):
            card(p, b)
        title(p, _MX, mid(_MY + LED_ROW_H / 2, "cond", 21, 600), "MAGI SYSTEM", "三体合議制", px=21, ls=0.03)
        title(p, 40, 508 + 20, "SYSTEM ACTIVITY", "システム動作状況")
        p.fillRect(QRectF(274, 544, 1, 152), color(M_LINE))
        tx(p, 40, 557, "FPS", key="cond", px=13, c=M_TEXT2)
        tx(p, 40, 614.35, "ネットワーク", key="jp", px=11, c=M_TEXT2)
        x = ACT_SELF_X
        x += tx(p, x, 557, "MAGI", key="cond", px=13, c=M_TEXT2) + tw(" ", "cond", 13)
        x += tx(p, x, 557, "自己", key="jp", px=10, c=M_DIM) + tw(" ", "cond", 13)
        tx(p, x, 557, "· USO PRÓPRIO", px=11, c=M_DIM)
        title(p, 40, 741 + 20, "NETWORK", "ネットワーク接続", jp_px=9)
        for i, k in enumerate(("IP", "GATEWAY", "DNS")):
            tx(p, 40, 794.9 + i * 19.2, k, px=10, c=M_TEXT2)
        # load history
        title(p, 499, 587 + 21, "LOAD HISTORY", "負荷履歴", px=21)
        x = 974
        for name, col in (("RAM", M_DIM), ("GPU", M_GREEN), ("CPU", M_LILAC)):
            x -= tx(p, x, 608, name, px=11, c=M_TEXT2, align=R)
            x -= 6 + 8
            p.fillRect(QRectF(x, 608 - 4 - 4, 8, 8), color(col))
            x -= 16
        sx, sy = 499.0, 620.2
        rule = color(M_RULE)
        for gy in (10, 98, 186):
            p.fillRect(QRectF(sx + 38, sy + gy, 438, 1), rule)
        for gx in (38, 142, 246, 350, 454):
            p.fillRect(QRectF(sx + gx, sy + 10, 1, 176), rule)
        for lbl, lx, ly in (("100%", 0, 14), ("50%", 7, 102), ("0%", 14, 190)):
            tx(p, sx + lx, sy + ly, lbl, px=11, c=M_DIM)
        # condessa
        tx(p, 1025, 138 + 10.19, "MAGI-01 // CONDESSA", px=10, ls=0.06, c=M_DIM)
        tx(p, 1310, 138 + 11.59, "人格", key="jp", px=10, c=M_DIM, align=R)
        for i in range(3):
            dot(p, 1024.5, 279.5 + i * 16, 7, "#6d6884", ring=True)
        # unit spec
        title(p, 1029, 587 + 20, "UNIT SPEC", "機体情報")
        p.fillRect(QRectF(1029, 750.28, 276, 1), color(M_LINE))
        title(p, 1029, 775.28, "PILOTS", "操縦者", px=15, jp_px=9)
        # now playing
        title(p, 1357, 160, "NOW PLAYING", "再生中", jp_px=9)
        # rádio ayanami
        card(p, B_RADIO, "#0d0c15", "#2d2a3c")
        rei = rei_pixmap()
        if rei is not None:
            p.save()
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Lighten)
            p.setOpacity(0.85)
            p.drawPixmap(QRectF(*B_REI), rei, QRectF(rei.rect()))
            p.restore()
        x = 1357 + title(p, 1357, 416, "RÁDIO AYANAMI", None, ls=0.02) + 8
        x += tx(p, x, 416, "//", px=12, c=M_DIM) + 8
        tx(p, x, 416, "放送", key="jp", px=11, c=M_DIM)
        # konsole (moldura); trocado com o cam 01, o slot é da câmera
        if not self.kon_swap:
            self._konsole_frame(p)
        # ---- rodapé
        p.fillRect(QRectF(23, FOOT_RULE_Y, 1650 - 23, 1), color(M_RULE))
        x = 23 + tx(p, 23, FOOT_Y, "MAGI", px=13, weight=700, ls=0.1, c=M_BRIGHT)
        tx(p, x, FOOT_Y, "  MULTI AGENT GUIDANCE INTERFACE", px=11, ls=0.1, c=M_DIM)
        tx(p, 1650, FOOT_Y, "META+M · PAINEL COMPLETO", px=11, ls=0.1, c=M_DIM, align=R)
        p.restore()
        self._cam(p, s, None)
        draw_learning_box(p, LEARN_BTN)  # Learning Mode (LM1.7)

    def _konsole_frame(self, p: QPainter) -> None:
        x0, y0, w, h = B_KON
        box(p, QRectF(*B_KON), "#07060c", "#3a3550")
        ix, iw = x0 + 1, w - 2
        # barra de título
        ty = y0 + 1
        p.fillRect(QRectF(ix, ty, iw, KON_TITLE_H), color("#0f0d16"))
        p.fillRect(QRectF(ix, ty + KON_TITLE_H - 1, iw, 1), color("#2b2738"))
        cy = ty + (KON_TITLE_H - 1) / 2
        _term_icon(p, ix + 10, cy - 7.5)
        bx = ix + iw - 8 - 48
        for i, (g, px) in enumerate((("–", 11), ("□", 10), ("×", 12))):
            tx(p, bx + i * 16 + 8, mid(cy, "mono", px), g, px=px, c=M_DIM, align=C)
        dot(p, bx - 8 - 3, cy, 6, M_GREEN)
        nx = bx - 8 - 6 - 5
        nx -= tx(p, nx, mid(cy, "mono", 9), "NODE 01", px=9, ls=0.08, c=M_DIM, align=R)
        # o título cabe antes do NODE 01: a Barlow local é um pouco mais larga que a do navegador
        tx0 = ix + 10 + 15 + 8
        room = nx - 8 - tx0
        px, ls = next(((px, ls) for px, ls in ((16, 0.05), (16, 0.02), (16, 0.0), (15, 0.0))
                       if tw("KONSOLE // CLAUDE CODE", "cond", px, 600, ls) <= room), (15, 0.0))
        tx(p, tx0, mid(cy, "cond", px, 600), "KONSOLE // CLAUDE CODE", key="cond", px=px, weight=600, ls=ls,
           c=M_TEXT, max_w=room)
        # aba
        ay = ty + KON_TITLE_H
        p.fillRect(QRectF(ix, ay, iw, KON_TAB_H), color("#0d0b13"))
        p.fillRect(QRectF(ix, ay + KON_TAB_H - 1, iw, 1), color("#2b2738"))
        tab_w = 9 + tw("SESSION 01", "mono", 9, None, 0.1) + 10 + tw("×", "mono", 9, None, 0.1) + 9
        p.fillRect(QRectF(ix, ay - 1, tab_w, KON_TAB_H), color("#07060c"))
        p.fillRect(QRectF(ix, ay - 1, tab_w, 1), color(M_LILAC))
        p.fillRect(QRectF(ix + tab_w, ay, 1, KON_TAB_H - 1), color("#2b2738"))
        acy = ay + (KON_TAB_H - 1) / 2
        x = ix + 9 + tx(p, ix + 9, mid(acy, "mono", 9), "SESSION 01", px=9, ls=0.1, c=M_TEXT) + 10
        tx(p, x, mid(acy, "mono", 9), "×", px=9, ls=0.1, c="#6d6884")
        plus_w = 9 + tw("+", "mono", 12) + 9
        tx(p, ix + tab_w + 1 + plus_w / 2, mid(acy, "mono", 12), "+", px=12, c=M_DIM, align=C)
        p.fillRect(QRectF(ix + tab_w + 1 + plus_w, ay, 1, KON_TAB_H - 1), color("#2b2738"))
        # barra de rolagem (acompanhando o fim do terminal)
        sb = QRectF(ix + iw - 4 - 4, KON_BODY_TOP + 8, 4, KON_STATUS_TOP - KON_BODY_TOP - 16)
        p.fillRect(sb, color("#14121b"))
        p.fillRect(QRectF(sb.left(), sb.top() + sb.height() * 0.3, 4, sb.height() * 0.7), color(M_TERM_IDLE))
        # barra de status (fundo; o texto é do grupo "konsole_status")
        p.fillRect(QRectF(ix, KON_STATUS_TOP, iw, KON_STATUS_H), color("#0f0d16"))
        p.fillRect(QRectF(ix, KON_STATUS_TOP, iw, 1), color("#2b2738"))

    def _scene_frame(self, p: QPainter, s: float, mono: float | None) -> None:
        """"cam 01": céu da hora, camada animada (``mono``; None = parado, no estático),
        scanlines, borda e legendas por cima (coordenadas base 1920 para a cena)."""
        r = SCENE
        p.save()
        p.setClipRect(r, Qt.ClipOperation.IntersectClip)
        p.drawPixmap(r, scene.main_scene(r.width(), r.height(), CPU, s, self.sky, live=False), QRectF())
        self.anim.paint(p, r, CPU, mono)
        p.restore()
        kit.draw_scanlines(p, r)
        p.save()
        p.setClipRect(r, Qt.ClipOperation.IntersectClip)
        p.scale(F, F)
        box(p, QRectF(*B_CAM), None, M_LINE)
        x = 499 + tx(p, 499, 153.9, "CAM 01 // ", px=12, ls=0.08, c=M_TEXT)
        tx(p, x, 153.9, "電線", key="jp", px=12, ls=0.08, c=M_TEXT)
        c1 = 974 - tw("LATENCY: 12ms", "mono", 11, None, 0.06)
        c0 = c1 - 12 - tw("SIGNAL: 98%", "mono", 11, None, 0.06)
        tx(p, c0, 151.2, "SIGNAL: 98%", px=11, ls=0.06, c=M_TEXT)
        tx(p, c1, 151.2, "LATENCY: 12ms", px=11, ls=0.06, c=M_TEXT)
        tx(p, 974, 170.7, "SOURCE: LOCAL", px=11, ls=0.06, c=M_TEXT, align=R)
        gx = 964.0
        tx(p, gx, 196 + 11.59, "電線", key="jp", px=10, c=M_DIM, align=C)
        tx(p, gx, 196 + 14.47 + 6 + 10.19, "98%", px=10, c=M_DIM, align=C)
        p.fillRect(QRectF(gx - 1, 235.67, 2, 515.53 - 235.67), color("#4a4566"))
        p.fillRect(QRectF(gx - 6, 235.67, 12, 1), color(M_DIM))
        tx(p, gx, 536 - 14.47 + 11.59, "電線", key="jp", px=10, c=M_DIM, align=C)
        tx(p, 501, 504.96, "信号は、まだ届いている。", key="jp", px=18, ls=0.12, c="#ece8f5")
        tx(p, 501, 528.4, "the signal is still arriving.", px=12, ls=0.06, c="#b5b0c8")
        p.restore()

    def _cam(self, p: QPainter, s: float, mono: float | None) -> None:
        """O cam 01 no lugar dele ou, com o Konsole expandido, inteiro e escalado no slot do card
        KONSOLE (mesmo cenário, textos e scanlines, só menor)."""
        if not self.kon_swap:
            self._scene_frame(p, s, mono)
            return
        p.save()
        p.setClipRect(CAM_SLOT, Qt.ClipOperation.IntersectClip)
        box(p, CAM_SLOT, M_PANEL, M_LINE)
        p.setTransform(cam_swap_transform(), True)
        self._scene_frame(p, s * CAM_SWAP_K, mono)
        p.restore()

    def static_variant(self) -> tuple:
        return (self.kon_swap,)

    def paint_scene(self, p: QPainter, snap: Snapshot, mono: float, s: float) -> None:
        self._cam(p, s, mono)

    def scene_rects(self) -> list[QRectF]:
        rects = self.anim.regions(SCENE)
        if self.kon_swap:
            xf = cam_swap_transform()
            return [xf.mapRect(r) for r in rects]
        return rects

    # ---------------------------------------------------------------- grupos

    def groups(self) -> dict[str, list[QRectF]]:
        g = {
            "scene": self.scene_rects(),  # primeiro: REC e o resto do cam 01 vão por cima
            "clock": [HEADER_CLOCK, REC, LIVE],
            "magi": [mq(_MX, _MY - 1, _MW, 323 + 2)],
            "activity": [mq(*ACT_BODY)],
            "network": [mq(*NET_BODY), mq(1300, 744, 147, 20)],
            "mascot": [MASCOT_MAIN],
            "mood": [MOOD_MAIN],
            "talk": [CHIP_RECT, TALK],
            "history": [mq(499 + 1, 620.2, 476, 226)],
            "spec": [mq(1029, 615, 277, 120), mq(1029, 783, 277, 64)],
            "player": [mq(1356, 141, 278, 210)],
            "radio": [mq(1356, 432, 278, 40)],
            "konsole": [KONSOLE_VIEW],
            "konsole_status": [KONSOLE_STATUS],
            "footer": [FOOTER],
            "lm_summary": [SUMMARY_RECT],  # por último: sobrepõe o SPEC (LM4.6)
            "mood_tip": [TIP_MAIN],  # hover do medidor: por cima de tudo
        }
        if self.kon_swap:  # câmera no slot do card; o Konsole (gamerhud) pinta a caixa do cam 01
            g["clock"] = [HEADER_CLOCK, cam_swap_transform().mapRect(REC), LIVE]
            del g["konsole"], g["konsole_status"]
        return g

    def group_key(self, name: str, snap: Snapshot, now: datetime) -> tuple:
        sn = snap
        if name == "clock":
            return (now.strftime("%Y%m%d%H%M%S"),)
        if name == "magi":
            return (led_lit(sn), accent(sn).rgb(), sn.cpu, sn.cpu_temp, sn.cpu_mhz, sn.gpu, sn.gpu_temp,
                    sn.vram, sn.vram_txt, sn.ram, sn.ram_txt, sn.swap_used_gb, sn.swap_total_gb, sn.disk_pct)
        if name == "activity":
            return (sn.fps, tuple(sn.fps_series), sn.gaming, rate(sn.net_down), rate(sn.net_up),
                    tuple(self_rows(sn) or ()))
        if name == "network":
            return (sn.net_ip, sn.net_gateway, sn.net_dns, rate(sn.net_down), rate(sn.net_up),
                    tuple(sn.net_series))
        if name == "scene":
            return (self.sky.key,)
        if name == "mascot":
            return (accent(sn).rgb(), sn.magui_state)
        if name == "mood":
            return mood_dela_key(sn) if sn.mood_dela is not None else mood_key(sn)
        if name == "mood_tip":
            return self.tip_key(sn)
        if name == "talk":
            mono = self.clock()
            self.caption_feed(sn.caption, mono)
            return (main_chip(sn), is_speaking(sn), self.tw.shown, sn.caption is None,
                    round(self.cap.offset(mono) * CAPTION_LH * 2), talk_lines(sn)[1])
        if name == "history":
            return (tuple((k, tuple(v)) for k, v in sorted(sn.history.items())), tuple(sn.history_axis))
        if name == "spec":
            return (tuple(sn.specs), tuple((x.name, x.battery, x.conn, x.charging) for x in sn.pilots))
        if name == "player":
            t = sn.track
            if t is None:
                return (None,)
            pos = None if t.position is None else int(t.position)
            return (t.title, t.artist, t.album, t.year, pos, t.length, t.playing,
                    t.cover.cacheKey() if t.cover is not None else None)
        if name == "radio":
            return tuple(sn.news[:RADIO_LINES])
        if name == "konsole":
            return (sn.konsole_rev,)
        if name == "konsole_status":
            c = sn.claude
            return (sn.project, sn.git_branch, sn.git_added, sn.git_removed, sn.konsole_online,
                    short_num(None if c is None else c.tokens))
        if name == "footer":
            return tuple(sn.events)
        if name == "lm_summary":
            return lsum.card_key(self.summary() if self.summary else None)
        return ()

    def draw_group(self, name: str, p: QPainter, snap: Snapshot, now: datetime, s: float) -> None:
        if name == "scene":
            return
        p.save()
        p.scale(F, F)
        getattr(self, f"_g_{name}")(p, snap, now, s)
        p.restore()

    # ---------------------------------------------------------------- topo

    def _g_clock(self, p, snap, now, s):
        right, bottom = 1650.0, 88.0
        ss = f"{now.second:02d}"
        tx(p, right, top_base(bottom - 26, "cond", 26, 26, 600), ss, key="cond", px=26, weight=600, c=M_LILAC,
           align=R)
        x = right - tw("00", "cond", 26, 600) - 6
        hm_lh = 76 * 0.82
        tx(p, x, top_base(bottom - hm_lh, "cond", 76, hm_lh, 600), now.strftime("%H:%M"), key="cond", px=76,
           weight=600, c="#f3f0fa", align=R)
        x -= tw("00:00", "cond", 76, 600) + 22
        date = f"{PT_DAYS[now.weekday()]} {now.day:02d} {PT_MONTHS[now.month - 1]} {now.year}"
        d_bottom = bottom - 4
        tx(p, x, d_bottom - 13 * LH["mono"] + asc("mono", 13), date, px=13, ls=0.1, c=M_TEXT2, align=R)
        jp_top = d_bottom - 13 * LH["mono"] - 8 - 17 * LH["jp"]
        tx(p, x, jp_top + asc("jp", 17), JP_DAYS[now.weekday()], key="jp", px=17, c=M_DIM, align=R)
        # REC do cam 01 (junto com a câmera, também no slot trocado) e LIVE do rádio
        p.save()
        if self.kon_swap:
            p.scale(1 / F, 1 / F)
            p.setTransform(cam_swap_transform(), True)
            p.scale(F, F)
        x = 499 + tx(p, 499, 176.6, "REC", px=11, ls=0.08, c=M_TEXT) + 7
        dot(p, x + 3.5, 176.6 - 4, 7, M_LILAC)
        tx(p, x + 7 + 7, 176.6, now.strftime("%H:%M:%S"), px=11, ls=0.08, c=M_TEXT)
        p.restore()
        tx(p, 1633, 416, f"LIVE {now:%H:%M}", px=10, ls=0.1, c=M_DIM, align=R)

    # ---------------------------------------------------------------- MAGI SYSTEM

    def _g_magi(self, p, snap, now, s):
        lit = led_lit(snap)
        rgb = color(snap.led_rgb) if lit else None
        # botão LED (消灯 LED OFF / 点灯 LED ON), à direita do título
        jp, lbl = ("点灯", "LED ON") if lit else ("消灯", "LED OFF")
        bw = 2 + 28 + 8 + 8 + tw(jp, "jp", 11) + 8 + tw(lbl, "mono", 10, None, 0.1)
        b = QRectF(_MX + _MW - bw, _MY, bw, LED_ROW_H)
        box(p, b, alpha(rgb, 20) if lit else "#100f18", mix(rgb, M_PANEL, 0.45) if lit else "#34304a")
        cy = b.center().y()
        x = b.left() + 15
        p.save()
        if lit:  # brilho do LED aceso
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            g = QRadialGradient(QPointF(x + 4, cy), 9)
            g.setColorAt(0.0, alpha(rgb, 170))
            g.setColorAt(1.0, alpha(rgb, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(x + 4, cy), 9, 9)
        p.restore()
        dot(p, x + 4, cy, 8, rgb if lit else M_DARK)
        fg = rgb if lit else color(M_DIM)
        x += 8 + 8
        x += tx(p, x, mid(cy, "jp", 11), jp, key="jp", px=11, c=fg) + 8
        tx(p, x, mid(cy, "mono", 10), lbl, px=10, ls=0.1, c=fg)
        # unidades
        for bx, (name, sub), style, bar_c, rows in zip(U_BOXES, UNIT_NAMES, UNIT_STYLE, UNIT_BAR_COLOR,
                                                      unit_rows(snap), strict=True):
            fg_c, bg, border, left, ok_c = style
            if lit:
                fg_c = bar_c = left = ok_c = rgb
                bg, border = alpha(rgb, 18), mix(rgb, M_PANEL, 0.3)
            x0, y0, w, h = bx
            r = QRectF(*bx)
            box(p, r, bg, border)
            p.fillRect(QRectF(x0, y0, 3, h), color(left))
            nt = y0 + (84 - (20 + 4 + 10 * LH["mono"])) / 2
            tx(p, x0 + 17, top_base(nt, "cond", 20, 20, 600), name, key="cond", px=20, weight=600, ls=0.02,
               c=fg_c)
            tx(p, x0 + 17, nt + 24 + asc("mono", 10), sub, px=10, ls=0.08, c=M_DIM)
            for j, (k, pct, warn, val) in enumerate(rows):
                cy = y0 + 24 + j * 18
                tx(p, x0 + 123, mid(cy, "jp", 10), k, key="jp", px=10, c=M_DIM, max_w=58)
                kit.segments(p, QRectF(x0 + 189, cy - 5, BARS * 6 - 2, 10), BARS, pct or 0.0, bar_c,
                             warn_from=warn, gap=2.0, off=M_OFF)
                tx(p, x0 + 333, mid(cy, "mono", 11), val, px=11, c=M_TEXT2 if pct is not None else M_DIM,
                   align=R, max_w=54)
            st = y0 + (84 - (14 * LH["jp"] + 2 + 8 * LH["mono"])) / 2
            p.fillRect(QRectF(x0 + 343, st, 1, 84 - 2 * (st - y0)), color(M_OK_LINE))
            tx(p, x0 + 377, st + asc("jp", 14), "正常", key="jp", px=14, c=ok_c, align=C)
            tx(p, x0 + 377, st + 14 * LH["jp"] + 2 + asc("mono", 8), "NORMAL", px=8, ls=0.1, c=M_DIM,
               align=C)

    # ---------------------------------------------------------------- SYSTEM ACTIVITY e NETWORK

    def _g_activity(self, p, snap, now, s):
        x = 40.0
        val = num(snap.fps) if snap.fps is not None else NA
        tx(p, x, 589.2, val, key="cond", px=24, weight=600, c=M_BRIGHT if snap.fps is not None else M_DIM)
        sx = x + tw("0000", "cond", 24, 600) + 12
        spark(p, QRectF(sx, 565.6 + 2, 130, 24), snap.fps_series, M_SPARK, 1.2,
              vmin=0.0, n=60)
        up = snap.net_down is not None or snap.net_up is not None
        c = M_TEXT2 if up else M_DIM
        w = tx(p, x, 634.74, f"↓  {rate(snap.net_down)}", px=11, c=c)
        tx(p, x + max(w, 66) + 20, 634.74, f"↑  {rate(snap.net_up)}", px=11, c=c)
        if snap.gaming or snap.fps is not None:
            w = tx(p, x, 693, "SIGNAL OK", key="cond", px=15, ls=0.04, c=M_GREEN)
            tx(p, x + w + 12, 693, "ゲーム検出", key="jp", px=11, c=M_DIM)
        else:
            w = tx(p, x, 693, "NO SIGNAL", key="cond", px=15, ls=0.04, c=M_LILAC)
            tx(p, x + w + 12, 693, "ゲーム未検出", key="jp", px=11, c=M_DIM)
        # uso próprio
        rows = self_rows(snap)
        gap = (152 - 16.3 - 56) / 4
        for i in range(4):
            top = 544 + 16.3 + gap + i * (14 + gap)
            cy = top + 7
            k, v, pct = rows[i] if rows else (("CPU", "GPU", "RAM", "VRAM")[i], NA, 0.0)
            tx(p, ACT_SELF_X, mid(cy, "mono", 10), k, px=10, c=M_TEXT2)
            bar = QRectF(ACT_SELF_X + 34 + 10, cy - 4, 446 - 38 - 10 - (ACT_SELF_X + 44), 8)
            p.fillRect(bar, color("#1b1926"))
            if rows:
                p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * max(pct, 1.5) / 100 if pct < 100
                                  else bar.width(), 8), color(M_LILAC))
            tx(p, 446, mid(cy, "mono", 10), v, px=10, c=M_TEXT2 if rows else M_DIM, align=R)

    def _g_network(self, p, snap, now, s):
        up = snap.net_down is not None or snap.net_up is not None or bool(snap.net_ip)
        # 接続中 ● no cabeçalho
        dot(p, 446 - 3.5, 761 - 4, 7, M_GREEN if up else M_DARK)
        tx(p, 446 - 7 - 8, 761, "接続中" if up else "未接続", key="jp", px=10, c=M_DIM, align=R)
        vals = [snap.net_ip or NA, snap.net_gateway or NA, snap.net_dns or NA]
        vw = min(96.0, max(72.0, *(tw(v, "mono", 10) for v in vals)))
        for i, v in enumerate(vals):
            tx(p, 112, 794.9 + i * 19.2, v, px=10, c=M_TEXT2 if v != NA else M_DIM, max_w=vw)
        bx = 112 + vw + 14
        p.fillRect(QRectF(bx, 775, 1, 71), color(M_LINE))
        rx = bx + 1 + 14
        rw = 446 - rx
        a = f"↓  {rate(snap.net_down)}"
        b = f"↑  {rate(snap.net_up)}"
        tot = tw(a, "mono", 11) + 26 + tw(b, "mono", 11)
        x = rx + (rw - tot) / 2
        c = M_TEXT2 if up else M_DIM
        x += tx(p, x, 786.2, a, px=11, c=c) + 26
        tx(p, x, 786.2, b, px=11, c=c)
        vals = list(snap.net_series)
        if len(vals) >= 2:
            hi = max(max(v for v in vals if v is not None), 1.0)
            spark(p, QRectF(rx, 812 + 2, rw, 30), vals, M_SPARK, 1.1, vmin=0.0, vmax=hi * 1.1, n=60)

    # ---------------------------------------------------------------- CONDESSA

    def _g_mood(self, p, snap, now, s):
        """Régua "在 … 01" à direita do retrato: o traço marca o humor (0 em baixo, 4 no topo, R13.7)
        e o número embaixo diz o nível (a informação nunca vai só na cor). Com o medidor dela (acordo
        §6), a barra do ânimo dela e o nome do momento."""
        if snap.mood_dela is not None:
            draw_mood_dela(p, QRectF(*B_GAUGE), snap)
            return
        x, y, w, h = B_GAUGE
        cx = x + w / 2
        tx(p, cx, y + asc("jp", 9), "在", key="jp", px=9, c=M_DIM, align=C)
        t0, t1 = y + 9 * LH["jp"] + 6, y + h - 9 * LH["mono"] - 6
        p.fillRect(QRectF(cx - 1.5, t0, 3, t1 - t0), color("#1d1b28"))
        col = mood_color(snap)
        if snap.mood is None:
            ty = t0 + 6
        else:
            m = max(0, min(MOOD_LEVELS - 1, int(snap.mood)))
            ty = t1 - 6 - (t1 - t0 - 12) * m / (MOOD_LEVELS - 1)
            p.fillRect(QRectF(cx - 1.5, ty, 3, t1 - ty), alpha(col, 110))
        p.fillRect(QRectF(cx - 5.5, ty, 11, 1), col if col is not None else color(M_DIM))
        tx(p, cx, y + h - 9 * LH["mono"] + asc("mono", 9), "–" if snap.mood is None else f"{snap.mood:02d}",
           px=9, c=M_DIM, align=C)

    def _g_mood_tip(self, p, snap, now, s):
        if self.tip_key(snap)[0]:
            draw_causas(p, tip_rect(QRectF(*B_GAUGE)), snap.causas)

    def _g_talk(self, p, snap, now, s):
        # chip de estado
        en, jp, fg, lit = main_chip(snap)
        speaking = is_speaking(snap)
        x0, y0 = B_CHIP[0], B_CHIP[1]
        w = 2 + 18 + tw(en, "cond", 14, None, 0.04) + tw(" ", "cond", 14) + tw(jp, "jp", 14)
        chip = QRectF(x0, y0, w, B_CHIP[3])
        if lit:
            p.fillRect(chip, alpha(fg, 30))
        box(p, chip, None, fg if lit else M_DARK)
        yb = y0 + 1 + 3 + asc("jp", 14)
        x = x0 + 10 + tx(p, x0 + 10, yb, en, key="cond", px=14, ls=0.04, c=fg)
        tx(p, x + tw(" ", "cond", 14), yb, jp, key="jp", px=14, c=fg)
        # caixa de terminal
        tb = QRectF(*B_TALK)
        box(p, tb, M_TERM_BG, M_LINE)
        p.fillRect(QRectF(tb.left(), tb.top(), 2, tb.height()), color(M_LILAC if speaking else M_TERM_IDLE))
        if snap.caption is None:  # sem fala: a linha de estado, inteira (nada é digitado nem pisca)
            self._term_lines(p, wrap_lines(TALK_PROMPT + talk_lines(snap)[1], TALK_TEXT[2], key="mono",
                                           px=TALK_PX), 0.0, None)
            return
        mono = self.clock()
        self.caption_feed(snap.caption, mono)
        lines = self.caption_lines(self.tw.shown)
        self._term_lines(p, lines, self.cap.offset(mono), mono, cursor=speaking)

    def _term_lines(self, p: QPainter, lines: list[str], off: float, mono: float | None,
                    cursor: bool = False) -> None:
        """Linhas do terminal da fala com o prompt ``›`` em lilás; cursor em bloco fixo no fim."""
        x, y, w, h = TALK_TEXT
        if not lines:
            lines = [TALK_PROMPT.rstrip()] if cursor else []
        p.save()
        p.setClipRect(QRectF(x - 2, y, w + 4, CAPTION_VISIBLE * TALK_LH), Qt.ClipOperation.IntersectClip)
        first = max(0, int(math.floor(off)) - 1)
        end_x = end_y = None
        for i in range(first, min(len(lines), first + CAPTION_VISIBLE + 3)):
            top = y + (i - off) * TALK_LH
            yb = top_base(top, "mono", TALK_PX, TALK_LH)
            ln = lines[i]
            a = 1.0 if mono is None else self.cap.alpha(i, mono)
            c = color(M_TEXT2)
            c.setAlphaF(a)
            lx = x
            if i == 0 and ln.startswith("›"):
                pc = color(M_LILAC)
                pc.setAlphaF(a)
                lx += tx(p, lx, yb, "›", px=TALK_PX, c=pc)
                ln = ln[1:]
            lw = tx(p, lx, yb, ln, px=TALK_PX, c=c)
            end_x, end_y = lx + lw, yb
        p.restore()
        if cursor and end_x is not None and end_y < y + CAPTION_VISIBLE * TALK_LH:
            cx = min(end_x + 2, x + w - 7 + 10)
            p.fillRect(QRectF(cx, end_y + 2 - 13, 7, 13), color(M_LILAC))
        if mono is not None and len(lines) > CAPTION_VISIBLE:  # trilho de rolagem na borda direita
            track = QRectF(x + w + 5, y + 2, 2, CAPTION_VISIBLE * TALK_LH - 4)
            p.fillRect(track, color(M_LINE))
            th = max(8.0, track.height() * CAPTION_VISIBLE / len(lines))
            pos = self.cap.offset(mono) / max(1, self.cap.max_off)
            p.fillRect(QRectF(track.left(), track.top() + (track.height() - th) * pos, 2, th),
                       color(M_DIM if self.cap.follow else M_LILAC))

    # ---------------------------------------------------------------- LOAD HISTORY e UNIT SPEC

    def _g_history(self, p, snap, now, s):
        sx, sy = 499.0, 620.2
        plot = QRectF(sx + 38, sy + 10, 416, 176)
        for k, col, wd in (("ram", M_DIM, 1.4), ("gpu", M_GREEN, 1.3), ("cpu", M_LILAC, 1.3)):
            vals = snap.history.get(k) or []
            if len(vals) >= 2:
                kit.sparkline(p, plot, vals, col, wd, n=max(120, len(vals)))
        axis = snap.history_axis
        if not axis:
            tx(p, sx + 22, sy + 214, NA, px=11, c=M_DIM)
            return
        for frac, hhmm in axis:
            tx(p, sx + 38 + frac * 416, sy + 214, hhmm, px=11, c=M_DIM, align=C)

    def _g_spec(self, p, snap, now, s):
        rows = snap.specs[:6] or [("CPU", NA)]
        for i, (k, v) in enumerate(rows):
            yb = 621 + i * 18.86 + asc("mono", 10.5)
            tx(p, 1029, yb, str(k).upper(), px=10.5, c=M_DIM, max_w=42)
            tx(p, 1073, yb, str(v or NA).upper(), px=10.5, c=M_TEXT2, max_w=232)
        for i in range(2):
            top = 784.28 + i * (27.86 + 6)
            r = QRectF(1029, top, 276, 27.86)
            box(p, r, None, M_OK_LINE)
            yb = top + 1 + 6 + asc("mono", 10.5)
            if i < len(snap.pilots):
                pl = snap.pilots[i]
                bat = num(pl.battery, suffix="%")
                try:
                    low = float(pl.battery) < 30
                except (TypeError, ValueError):
                    low = False
                bc = WARN if (pl.charging or low) and pl.battery is not None else \
                    (M_TEXT if pl.battery is not None else M_DIM)
                bw = tx(p, 1294, yb, bat, px=10.5, c=bc, align=R)
                if pl.charging:  # ⚡ desenhado (a JetBrains Mono não tem o glifo)
                    _bolt(p, QPointF(1294 - bw - 7, yb - 4), color(bc))
                name = f"{i + 1:02d}   {pl.name}" + (f" {pl.conn}" if pl.conn else "")
                tx(p, 1040, yb, name.upper(), px=10.5, c=M_TEXT, max_w=254 - bw - 20)
            else:
                x = 1040 + tx(p, 1040, yb, f"{i + 1:02d}   ", px=10.5, c=M_DIM)
                x += tx(p, x, yb, "未接続", key="jp", px=10.5, c=M_DIM)
                tx(p, x, yb, " — empty", px=10.5, c=M_DIM)

    # ---------------------------------------------------------------- NOW PLAYING e RÁDIO

    def _g_player(self, p, snap, now, s):
        t = snap.track
        active = t is not None and bool(t.title)
        g = M_GREEN if active else M_DIM
        w = tx(p, 1633, 160 - 20 + 11.21 + (24 - 14.52) / 2, "spotify", px=11, c=g, align=R)
        dot(p, 1633 - w - 6 - 3, 160 - 20 + 12, 6, g if active else M_DARK)
        cover = QRectF(*B_COVER)
        pm = cover_scaled(t.cover if active else None, cover.width() * F, cover.height() * F, s)
        if pm is not None:
            p.drawPixmap(cover, pm, QRectF())
        else:
            p.fillRect(cover, color("#1a1823"))
            dot(p, cover.center().x(), cover.center().y(), 40, M_OK_LINE, ring=True)
        x, wd = 1451.0, 1633 - 1451.0
        y0 = NP_ROW + 2
        if active:
            tx(p, x, top_base(y0, "cond", 22, 24.2), t.title, key="cond", px=22, c=M_BRIGHT, max_w=wd)
            tx(p, x, y0 + 24.2 + 4 + asc("mono", 12), t.artist or NA, px=12, c=M_TEXT2, max_w=wd)
            alb = " · ".join(str(v) for v in (t.album, t.year) if v) or NA
            tx(p, x, y0 + 24.2 + 8 + 15.84 + asc("mono", 12), alb, px=12, c=M_TEXT2, max_w=wd)
        else:
            tx(p, x, top_base(y0, "cond", 22, 24.2), NA, key="cond", px=22, c=M_DARK)
            tx(p, x, y0 + 24.2 + 4 + asc("mono", 12), "nada tocando", px=12, c=M_DIM)
        p.fillRect(QRectF(1357, NP_PROG, 276, 2), color(M_OK_LINE))
        if active and t.position is not None and t.length:
            frac = min(1.0, max(0.0, t.position / t.length))
            p.fillRect(QRectF(1357, NP_PROG, 276 * frac, 2), color("#e3b977"))
        ty = NP_PROG + 8 + asc("mono", 10)
        tx(p, 1357, ty, mmss(t.position) if active else NA, px=10, c=M_DIM)
        tx(p, 1633, ty, mmss(t.length) if active else NA, px=10, c=M_DIM, align=R)
        playing = active and t.playing
        ic = M_TEXT2 if active else M_DIM
        for k, b in B_BTNS.items():
            r = QRectF(*b)
            box(p, r, "#12111a", "#2f2c40")
            _icon(p, r, ("pause" if playing else "play") if k == "playpause" else k, ic)
        ex = 1633 - (len(EQ) * 5 - 2)
        for i, hh in enumerate(EQ):
            hh = hh if playing else 3
            p.fillRect(QRectF(ex + i * 5, 350 - hh, 3, hh), color(M_SPARK))

    def _g_radio(self, p, snap, now, s):
        tops = (434.0, 434 + 15.84 + 4)
        if not snap.news:
            tx(p, 1357, tops[0] + asc("mono", 12), "nenhuma notícia ainda", px=12, c="#c9c2e6")
            tx(p, 1357, tops[1] + asc("mono", 12), 'diga "novidades"', px=12, c="#c9c2e6")
            return
        for i, (hhmm, ttl) in enumerate(snap.news[:RADIO_LINES]):
            yb = tops[i] + asc("mono", 12)
            x = 1357 + tx(p, 1357, yb, hhmm, px=10, c=M_LILAC if i == 0 else M_DIM) + 8
            tx(p, x, yb, ttl, px=12, c="#c9c2e6" if i == 0 else M_DIM, max_w=1633 - x)

    # ---------------------------------------------------------------- KONSOLE

    def _g_konsole(self, p, snap, now, s):
        """Miolo do terminal: ``konsole_view.paint_compact`` (outro módulo) no retângulo base 1920."""
        if konsole_view is None or not hasattr(konsole_view, "paint_compact"):
            return
        p.save()
        p.scale(1 / F, 1 / F)  # o konsole_view recebe o retângulo na base 1920
        try:
            konsole_view.paint_compact(p, KONSOLE_VIEW, s)
        except Exception:  # noqa: BLE001 - terminal quebrado não derruba o painel
            log.exception("konsole_view.paint_compact falhou")
        p.restore()

    def _g_konsole_status(self, p, snap, now, s):
        x0, x1 = 1351.0, 1639.0
        y1 = KON_STATUS_TOP + 1 + 5 + asc("mono", 9.5)
        y2 = y1 + 9.5 * LH["mono"] + 2
        sep = "#3d3752"

        def seg(x, txt, c=M_DIM, max_w=None):
            return x + tx(p, x, y1 if seg.line == 1 else y2, txt, px=9.5, c=c, max_w=max_w)

        seg.line = 1
        branch = snap.git_branch or NA
        add = "" if snap.git_added is None else f"+{snap.git_added}"
        rem = "" if snap.git_removed is None else f"-{snap.git_removed}"
        tail = tw(" | ", "mono", 9.5) * 2 + tw(branch, "mono", 9.5) + tw(f"{add} {rem}", "mono", 9.5) + 14
        x = seg(x0, project_label(snap.project), max_w=max(40.0, x1 - x0 - tail))
        x = seg(x + 7, "|", sep)
        x = seg(x + 7, branch, max_w=80)
        if add or rem:
            x = seg(x + 7, "|", sep)
            x = seg(x + 7, add, "#6fd49a")
            seg(x + tw(" ", "mono", 9.5), rem, "#e88f8f")
        seg.line = 2
        c = snap.claude
        x = seg(x0, "CLAUDE CODE")
        x = seg(x + 7, "|", sep)
        seg(x + 7, f"TOKENS {short_num(None if c is None else c.tokens)}")
        on = bool(snap.konsole_online)
        w = tx(p, x1, y2, "ONLINE" if on else "OFFLINE", px=9.5, c="#6fd49a" if on else M_DIM, align=R)
        dot(p, x1 - w - 5 - 3, y2 - 3.5, 6, M_GREEN if on else M_DARK)

    # ---------------------------------------------------------------- rodapé

    def _g_lm_summary(self, p, snap, now, s):
        cur = self.summary() if self.summary else None
        if cur is not None:
            lsum.paint_card(p, QRectF(*B_SUMMARY), cur, px=SUMMARY_PX)

    def _g_footer(self, p, snap, now, s):
        lw = tw("MAGI", "mono", 13, 700, 0.1) + tw("  MULTI AGENT GUIDANCE INTERFACE", "mono", 11, None, 0.1)
        rw = tw("META+M · PAINEL COMPLETO", "mono", 11, None, 0.1)
        left, right = 23 + lw + 24, 1650 - rw - 24
        msg = " · ".join(snap.events) if snap.events else NA
        tx(p, (left + right) / 2, FOOT_Y, msg, px=11, ls=0.04, c=M_DIM, align=C, max_w=right - left)

    # ---------------------------------------------------------------- cliques

    def hit_rects(self, snap: Snapshot | None = None) -> dict[str, QRectF]:
        # unidades MAGI abrem o detalhe por processo; LEARNING no topo (LM1.7); KONSOLE expande;
        # trocado, o slot do card é a câmera pequena ("cam": recolhe o Konsole)
        return {"learning": LEARN_BTN, "led": LED_BTN, **BTNS, "card:cpu": UNITS[0], "card:gpu": UNITS[1],
                "card:ram": UNITS[2], ("cam" if self.kon_swap else "konsole"): KONSOLE}


__all__ = ["CAM", "CAM_SLOT", "CAM_SWAPPED", "CARDS", "F",
           "KONSOLE", "KONSOLE_CWD", "KONSOLE_VIEW", "LEARN_BTN", "LEARN_W", "MainScreen", "NA",
           "Pilot", "Screen", "Snapshot", "Track", "accent", "draw_learning_box", "draw_learning_btn",
           "draw_causas", "draw_mood", "draw_mood_dela", "led_lit", "mood_color", "mood_dela_key", "mq",
           "tip_rect"]
