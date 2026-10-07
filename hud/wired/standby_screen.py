"""Tela de espera "wired" (Standby.dc.html): relógio em kanji, status do LED, mascote e mini player.

Mesma entrada (`Snapshot`) e mesma mecânica de cache/invalidação do `MainScreen`: o cenário, as
scanlines e os rótulos fixos ficam no cache; o relógio só redesenha na troca de minuto, o LED,
a fala e o player quando mudam, e o mascote pelo `mascot_tick` (dormindo, 1 vez a cada 4 s).
Nada do cenário passa atrás do texto (o cenário da U1 garante, ver `scene.standby_text_safe`).
A tela não tem botões: `hit_test` devolve sempre None.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter

from . import kit, scene
from .main_screen import (
    CHIP_STATES,
    JP_DAYS,
    NA,
    Screen,
    Snapshot,
    _metrics,
    accent,
    baseline,
    chip_label,
    draw_cover,
    draw_mood,
    label,
    led_dot,
    led_lit,
    mood_key,
    state_chip,
    text,
    width,
    wrapped,
)
from .theme import CPU, GPU, LINE, LINE_STRONG, TEXT, TEXT_DIM, WARN, color

TOP, BOTTOM = 170.0, 910.0
RAIL = QRectF(160, TOP, 4, BOTTOM - TOP)
TX = 208.0  # trilho 4 + gap 44
COL = QRectF(1180, TOP, 440, BOTTOM - TOP)
KANJI = "#efeae0"

_K = "零壱弐参四伍六七八九"  # os mesmos do gamerhud.KANJI_DIGITS (19 → 拾九, como no handoff)
_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
         "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty"]
EN_DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]  # weekday()
EN_MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER",
             "OCTOBER", "NOVEMBER", "DECEMBER"]


def kanji_num(n: int) -> str:
    """19 → 拾九, 11 → 拾壱, 37 → 参拾七, 0 → 零 (igual ao `gamerhud.kanji_num`)."""
    if n == 0:
        return "零"
    tens, ones = divmod(n, 10)
    return (_K[tens] if tens > 1 else "") + ("拾" if tens else "") + (_K[ones] if ones else "")


def _en(n: int) -> str:
    return _ONES[n] if n < 20 else _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")


def en_words(h: int, m: int) -> str:
    """Hora por extenso do canvas: 19:11 → "NINETEEN ELEVEN", 7:05 → "SEVEN OH FIVE"."""
    hh = "zero" if h == 0 else _en(h)
    mm = "o'clock" if m == 0 else f"oh {_en(m)}" if m < 10 else _en(m)
    return f"{hh} {mm}".upper()


def _lh(key: str, px: float, weight: int | None = None) -> float:
    fm = _metrics(key, px, weight, 0.0)
    return fm.ascent() + fm.descent()


PORTRAIT_H = 408.0  # altura do retrato da Condessa na tela de espera (+20%)


class StandbyScreen(Screen):
    """Tela de espera."""

    SCENE_KIND = "standby"

    def __init__(self, mascot=None):
        super().__init__(mascot)
        # coluna do relógio: topo / kanji (2 × 162) / base, distribuídos (space-between)
        h_top = _lh("cond", 40, 600)
        h_bot = _lh("cond", 56, 500) + 10 + _lh("mono", 16)
        gap = (BOTTOM - TOP - h_top - 324 - h_bot) / 2
        self.y_title = baseline("cond", 40, TOP, None, 600)
        self.y_kanji = TOP + h_top + gap
        self.y_words = baseline("cond", 56, BOTTOM - h_bot, None, 500)
        self.y_date = baseline("mono", 16, BOTTOM - _lh("mono", 16))
        # coluna direita: status / mascote / player
        h1 = _lh("mono", 13) + 14
        self.y_status = baseline("mono", 13, TOP)
        self.y_rule1 = TOP + h1
        h3 = 1 + 18 + 72
        self.y_rule2 = BOTTOM - h3
        if getattr(self.mascot, "TALL", False):  # retrato da Condessa: grande, com a fala embaixo
            ph, th = PORTRAIT_H, 115
            gap = (BOTTOM - TOP - (h1 + 1) - ph - 16 - th - h3) / 2
            self.mid = TOP + h1 + 1 + gap
            self.MASCOT_RECT = QRectF(COL.left(), self.mid, COL.width() - 30, ph)
            self.mood = QRectF(COL.right() - 12, self.mid + 20, 12, ph - 40)
            self.talk = QRectF(COL.left(), self.mid + ph + 16, COL.width(), th)
        else:
            gap = (BOTTOM - TOP - (h1 + 1) - 115 - h3) / 2
            self.mid = TOP + h1 + 1 + gap
            self.MASCOT_RECT = QRectF(COL.left(), self.mid, 200, 115)
            self.mood = QRectF(COL.left() + 205, self.mid + 10, 12, 95)  # discreto, entre mascote e fala
            self.talk = QRectF(COL.left() + 222, self.mid, COL.right() - COL.left() - 222, 115)
        self.cover = QRectF(COL.left(), BOTTOM - 72, 72, 72)

    # ---------------------------------------------------------------- estático

    def draw_static(self, p: QPainter, s: float) -> None:
        p.drawPixmap(QRectF(0, 0, 1920, 1080),
                     scene.standby_scene(1920, 1080, CPU, s, self.sky, live=False), QRectF())
        kit.draw_scanlines(p, QRectF(0, 0, 1920, 1080))
        w = text(p, TX, self.y_title, "MAGI SYSTEM", key="cond", px=40, weight=600, spacing=0.04).width()
        text(p, TX + w + 20, self.y_title, "待機中", key="jp", px=22, color_=TEXT_DIM)
        label(p, COL.left(), self.y_status, "magi-01 // condessa", px=13)
        p.fillRect(QRectF(COL.left(), self.y_rule1, COL.width(), 1), color(LINE))
        p.fillRect(QRectF(COL.left(), self.y_rule2, COL.width(), 1), color(LINE))
        label(p, 160, 1080 - 70 - 3.5, "meta+m · painel completo")

    # ---------------------------------------------------------------- grupos

    def paint_scene(self, p: QPainter, snap: Snapshot, mono: float, s: float) -> None:
        self.anim.paint(p, QRectF(0, 0, 1920, 1080), CPU, mono)  # o fundo já veio do estático

    def scene_rects(self) -> list[QRectF]:
        return self.anim.regions(QRectF(0, 0, 1920, 1080))

    def groups(self) -> dict[str, list[QRectF]]:
        return {
            "scene": self.scene_rects(),  # primeiro: o resto vai por cima
            "clock": [QRectF(TX - 4, self.y_kanji - 4, 1160 - TX, BOTTOM + 6 - self.y_kanji)],
            "led": [RAIL, QRectF(COL.right() - 130, TOP - 4, 132, self.y_rule1 - TOP)],
            "mascot": [self.MASCOT_RECT],
            "mood": [self.mood],
            "talk": [self.talk],
            "player": [QRectF(COL.left() - 2, self.y_rule2 + 2, COL.width() + 4, BOTTOM - self.y_rule2 + 2)],
        }

    def group_key(self, name: str, snap: Snapshot, now: datetime) -> tuple:
        if name == "scene":
            return (self.sky.key,)
        if name == "clock":
            return (now.strftime("%Y%m%d%H%M"),)
        if name == "led":
            return (led_lit(snap), accent(snap).rgb())
        if name == "mascot":
            return (accent(snap).rgb(), snap.magui_state)
        if name == "mood":
            return mood_key(snap)
        if name == "talk":
            return (snap.caption, snap.magui_state == "sleeping", chip_label(snap))
        if name == "player":
            t = snap.track
            if t is None:
                return (None,)
            frac = None
            if t.position is not None and t.length:
                frac = round(min(1.0, t.position / t.length) * 440)  # 1 px lógico
            return (t.title, t.artist, t.playing, frac, t.cover.cacheKey() if t.cover is not None else None)
        return ()

    def draw_group(self, name: str, p: QPainter, snap: Snapshot, now: datetime, s: float) -> None:
        getattr(self, f"_g_{name}")(p, snap, now, s)

    def _g_clock(self, p, snap, now, s):
        for i, ln in enumerate((kanji_num(now.hour) + "時", kanji_num(now.minute) + "分")):
            y = baseline("mincho", 150, self.y_kanji + i * 162, 162)
            text(p, TX, y, ln, key="mincho", px=150, color_=KANJI)
        text(p, TX, self.y_words, en_words(now.hour, now.minute), key="cond", px=56, weight=500, spacing=0.02)
        date = f"{EN_DAYS[now.weekday()]}, {EN_MONTHS[now.month - 1]} {now.day} · "
        w = label(p, TX, self.y_date, date, px=16).width()
        text(p, TX + w + 16 * 0.08, self.y_date, JP_DAYS[now.weekday()], key="jp", px=16, color_=TEXT_DIM)

    def _g_led(self, p, snap, now, s):
        lit = led_lit(snap)
        p.fillRect(RAIL, color(snap.led_rgb) if lit else color(LINE_STRONG))
        txt = f"led {'on' if lit else 'off'}"
        tw = width(txt.upper(), "mono", 13, None, 0.08)
        label(p, COL.right(), self.y_status, txt, px=13, color_=TEXT, align=Qt.AlignmentFlag.AlignRight)
        led_dot(p, QPointF(COL.right() - tw - 8 - 4, self.y_status - 4.5), 4, snap)

    def _g_mood(self, p, snap, now, s):
        draw_mood(p, self.mood, snap, legend=False, bar_w=4.0)

    def _g_talk(self, p, snap, now, s):
        r = self.talk
        if snap.magui_state in CHIP_STATES:  # ouvindo/pensando: chip aceso no alto, a fala embaixo
            chip = state_chip(p, r.left(), r.top() + 2, snap)
            r = r.adjusted(0, chip.height() + 8, 0, 0)
            if snap.caption:
                wrapped(p, r, snap.caption, px=16, line_h=24, max_lines=max(1, int(r.height() // 24)))
                return
        if snap.caption:
            wrapped(p, r.adjusted(0, 8, 0, 0), snap.caption, px=16, line_h=24, max_lines=4)
            return
        line = {"sleeping": "「少し眠いです…」", "listening": "「はい、聞いています。」",
                "thinking": "「考えています…」"}.get(snap.magui_state, "「システムは正常です。」")
        top = r.top() + (r.height() - _lh("jp", 16) - 8 - _lh("jp", 14)) / 2
        text(p, r.left(), baseline("jp", 16, top), line, key="jp", px=16, max_w=r.width())
        text(p, r.left(), baseline("jp", 14, top + _lh("jp", 16) + 8), "信号は、まだ届いている。", key="jp",
             px=14, color_=TEXT_DIM, spacing=0.14, max_w=r.width())

    def _g_player(self, p, snap, now, s):
        t = snap.track
        active = t is not None and bool(t.title)
        draw_cover(p, self.cover, t.cover if active else None, s, 22, 9, 5)
        x = self.cover.right() + 18
        wdt = COL.right() - x
        top = BOTTOM - 72 + (72 - (_lh("mono", 11) + 6 + 28.8 + 6 + 2)) / 2
        y1 = baseline("mono", 11, top)
        y2 = baseline("cond", 24, top + _lh("mono", 11) + 6, 28.8)
        bar = top + _lh("mono", 11) + 6 + 28.8 + 6
        if active:
            st = "再生中" if t.playing else "一時停止"
            label(p, x, y1, f"● spotify · {st}", px=11, color_=GPU if t.playing else TEXT_DIM, upper=False)
            artist = f" — {t.artist}" if t.artist else ""
            tw = width(t.title, "cond", 24)
            title_w = min(tw, wdt - min(width(artist, "cond", 24), wdt * 0.4)) if artist else wdt
            w = text(p, x, y2, t.title, key="cond", px=24, max_w=title_w).width()
            if artist:
                text(p, x + w, y2, artist, key="cond", px=24, color_=TEXT_DIM, max_w=wdt - w)
        else:
            label(p, x, y1, "○ spotify", px=11, upper=False)
            text(p, x, y2, NA, key="cond", px=24, color_=LINE_STRONG)
        p.fillRect(QRectF(x, bar, wdt, 2), color(LINE))
        if active and t.position is not None and t.length:
            p.fillRect(QRectF(x, bar, wdt * min(1.0, max(0.0, t.position / t.length)), 2), color(WARN))


__all__ = ["StandbyScreen", "en_words", "kanji_num"]
