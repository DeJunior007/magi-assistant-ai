"""Ponte entre o `gamerhud.py` e as telas "wired" (U4, R23.6/R23.8/R23.9; termômetro R13.7).

O `gamerhud` continua dono das fontes de dados (`Sensors`, `FpsSource`, `ProcStats`, controles,
OpenRGB, ponte com a Magui) e do ciclo Qt (timers, `paintEvent`, cliques). Aqui fica o que é do
tema novo, sem depender do QWidget, para dar para testar com fontes falsas:

- `build_snapshot(...)`: monta o `Snapshot` a partir das fontes existentes + `data.py` (pura);
- `WiredUI`: as duas telas (mascote compartilhado), os dados novos (rede, histórico, FPS,
  Spotify, log do rodapé), o estado da Magui (expressão, boca, legenda, humor) e do LED, os
  eventos do rodapé, o roteamento de cliques e o painel de detalhes por processo no estilo wired.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QPainter

from . import kit
from .data import EventLog, FpsSnapshot, FpsStats, LoadHistory, NetRate, NowPlaying
from .main_screen import (
    NA,
    SCENE,
    C,
    MainScreen,
    Pilot,
    R,
    Snapshot,
    Track,
    dev_rect,
    heading,
    label,
    text,
)
from .mascot import EXPRESSIONS, Mascot
from .portrait import make_mascot
from .standby_screen import StandbyScreen
from .theme import CPU, GPU, LINE, PANEL, RAM, TEXT, TEXT_DIM, alpha, color

CARD_DETAIL = {"card:cpu": "cpu", "card:gpu": "gpu", "card:ram": "mem"}  # alvo → ProcStats.poll
PLAYER = ("prev", "playpause", "next")
ALERT_LEVELS = ("bomba", "alta")  # cards da ponte que viram aviso no rodapé
DETAIL_RECT = SCENE.adjusted(1, 1, -1, -1)  # painel de detalhes cobre o "cam 01"
DETAIL_INFO = {
    "cpu": ("Melchior", "詳細解析 · cpu por aplicativo", CPU),
    "gpu": ("Balthasar", "詳細解析 · gpu por aplicativo", GPU),
    "mem": ("Casper", "詳細解析 · ram (pss) e vram", RAM),
}


def rgb_hex(rgb) -> str | None:
    """(r, g, b[, nível]) do OpenRGB → "#rrggbb"; preto (LEDs apagados) ou None → None."""
    if not rgb:
        return None
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb[:3])
    if max(r, g, b) < 10:
        return None
    return f"#{r:02x}{g:02x}{b:02x}"


def short_gpu(spec_gpu: str | None) -> str | None:
    """"AMD RADEON RX 9060 XT · 16 GB" → "AMD RADEON RX 9060 XT" (a VRAM já aparece na Casper)."""
    if not spec_gpu or spec_gpu == "--":
        return None
    return spec_gpu.split(" · ")[0]


def build_snapshot(data: dict, *, spec=(), pads=(), gaming: bool = False, fps: FpsSnapshot | None = None,
                   net: NetRate | None = None, history: LoadHistory | None = None,
                   now_playing: NowPlaying | None = None, events: EventLog | None = None,
                   led_on: bool = False, led_rgb: str | None = None, magui_state: str = "sleeping",
                   mouth_level: float = 0.0, caption: str | None = None, mood: int | None = None,
                   now: float | None = None) -> Snapshot:
    """Snapshot das telas. `data` = `Sensors.data`; `spec` = `system_info()`; `pads` = `controllers()`.
    Sem GPU (`vram_txt == "--"`) as leituras de GPU/VRAM viram None ("– –", R23.3)."""
    d = data or {}
    has_gpu = d.get("vram_txt") not in (None, "--")
    sp = dict(spec)
    track = None
    if now_playing is not None and now_playing.active:
        track = Track(now_playing.title, now_playing.artist, now_playing.album, now_playing.year,
                      now_playing.position(now), now_playing.length, now_playing.status == "Playing",
                      now_playing.cover_pixmap())
    snap = Snapshot(
        gaming=gaming,
        cpu=d.get("cpu"), cpu_temp=d.get("cpu_temp"),
        gpu=d.get("gpu") if has_gpu else None, gpu_temp=d.get("gpu_temp"), gpu_w=d.get("gpu_w"),
        ram=d.get("ram"), ram_txt=d.get("ram_txt"),
        vram=d.get("vram") if has_gpu else None, vram_txt=d.get("vram_txt") if has_gpu else None,
        cpu_label=sp.get("CPU") or None, gpu_label=short_gpu(sp.get("GPU")), ram_label=sp.get("RAM") or None,
        specs=list(spec),
        pilots=[Pilot(str(n), b, c or "", bool(ch)) for n, b, c, ch in pads],
        track=track, led_on=bool(led_on), led_rgb=led_rgb if led_on else None,
        magui_state=magui_state if magui_state in EXPRESSIONS else "sleeping",
        mouth_level=mouth_level, caption=caption or None,
        mood=None if mood is None else max(0, min(4, int(mood))),
    )
    if net is not None:
        snap.net_down, snap.net_up = net.down, net.up
        snap.net_series = list(net.down_series)
    if history is not None:
        snap.history = {k: history.series(k) for k in ("cpu", "gpu", "ram")}
        snap.history_axis = history.axis()
    if fps is not None:
        snap.fps, snap.fps_min, snap.fps_avg, snap.fps_max = fps.current, fps.min, fps.avg, fps.max
        snap.fps_series = list(fps.series)
    if events is not None:
        snap.events = events.ticker(3)
    return snap


class WiredUI:
    """Estado e telas do tema wired. O HUD chama `poll` a 1 Hz, `build` quando algo muda, repassa
    os eventos da Magui e usa `screen(view)` para pintar/invalidar e `hit` para os cliques."""

    def __init__(self, now_playing: NowPlaying | None = None, net: NetRate | None = None,
                 history: LoadHistory | None = None, fps: FpsStats | None = None,
                 events: EventLog | None = None, mascot: Mascot | None = None):
        self.mascot = mascot or make_mascot("sleeping")  # retrato da Condessa, se houver a arte
        self.main = MainScreen(self.mascot)
        self.standby = StandbyScreen(self.mascot)
        self.now_playing = now_playing if now_playing is not None else NowPlaying()
        self.net = net or NetRate()
        self.history = history or LoadHistory()
        self.fps = fps or FpsStats()
        self.events = events or EventLog()
        self.magui_state = "sleeping"
        self.mouth_level = 0.0
        self.caption: str | None = None
        self.mood: int | None = None
        self.led_on = False
        self.led_rgb: str | None = None
        self._game: str | None = None
        self._track: tuple | None = None
        self._led_warned = False
        self.snap = Snapshot()

    def screen(self, view: str) -> MainScreen | StandbyScreen:
        return self.standby if view == "idle" else self.main

    # ---------------------------------------------------------------- dados (1 Hz)

    def poll(self, data: dict, fps: float | None, game: str | None, mono: float | None = None,
             wall: float | None = None) -> None:
        mono = time.monotonic() if mono is None else mono
        wall = time.time() if wall is None else wall
        self.net.poll(mono)
        has_gpu = (data or {}).get("vram_txt") not in (None, "--")
        self.history.push(data.get("cpu"), data.get("gpu") if has_gpu else None, data.get("ram"), wall)
        self.fps.push(fps, mono)
        self.now_playing.tick(mono)
        if game != self._game:
            if game:
                self.events.add(f"jogo detectado: {game}")
            elif self._game:
                self.events.add(f"jogo fechado: {self._game}")
            self._game = game
        np = self.now_playing
        key = (np.title, np.artist) if np.active else None
        if key != self._track:
            if key is not None:
                self.events.add(f"♪ {np.title}" + (f" — {np.artist}" if np.artist else ""))
            self._track = key

    def build(self, data: dict, *, spec=(), pads=(), gaming: bool = False) -> Snapshot:
        self.snap = build_snapshot(
            data, spec=spec, pads=pads, gaming=gaming, fps=self.fps.snapshot(), net=self.net,
            history=self.history, now_playing=self.now_playing, events=self.events,
            led_on=self.led_on, led_rgb=self.led_rgb, magui_state=self.magui_state,
            mouth_level=self.mouth_level, caption=self.caption, mood=self.mood)
        return self.snap

    # ---------------------------------------------------------------- LED (RGB Sync)

    def set_led(self, on: bool, rgb: str | None) -> None:
        """`on` = RGB Sync ligado; `rgb` = cor do OpenRGB ou None se ele não respondeu (visual off)."""
        if on and rgb is None and not self._led_warned:
            self.events.add("openrgb sem resposta · led off")
            self._led_warned = True
        elif rgb is not None or not on:
            self._led_warned = False
        self.led_on, self.led_rgb = bool(on), (rgb if on else None)

    # ---------------------------------------------------------------- Magui (hud_bridge)

    def set_state(self, expr: str) -> None:
        if expr not in EXPRESSIONS:
            return
        if self.magui_state == "sleeping" and expr != "sleeping":
            self.events.add("magui ativada")
        self.magui_state = expr
        self.snap.magui_state = expr
        self.mascot.set_expression(expr)

    def set_mouth(self, level: float) -> None:
        self.mouth_level = min(1.0, max(0.0, float(level)))
        self.snap.mouth_level = self.mouth_level  # o paint repassa o snapshot ao mascote
        self.mascot.set_level(self.mouth_level)

    def set_caption(self, txt: str | None) -> None:
        self.caption = txt or None

    def set_mood(self, v: int | None) -> None:
        self.mood = None if v is None else max(0, min(4, int(v)))

    def on_card(self, card: dict) -> None:
        if card.get("level") in ALERT_LEVELS and card.get("title"):
            self.events.add(f"⚠ {card['title']}")

    def on_connected(self, up: bool) -> None:
        if not up:
            self.set_state("sleeping")
            self.set_caption(None)

    # ---------------------------------------------------------------- cliques

    def hit(self, pos: QPoint | QPointF, size: QSize, view: str, detail: str | None = None) -> str | None:
        """Alvo do clique: "led", "prev"/"playpause"/"next", "card:cpu|gpu|ram", "detail" (fecha
        o painel aberto), "face" (mascote → push-to-talk) ou None."""
        scr = self.screen(view)
        s = scr.scale(size)
        pt = QPointF(pos.x() / s, pos.y() / s)
        if view != "idle" and detail and DETAIL_RECT.contains(pt):
            return "detail"
        if scr.MASCOT_RECT.contains(pt):
            return "face"
        return scr.hit_test(pos, size)

    def player(self, target: str) -> bool:
        """Controles do Spotify (MPRIS). True se `target` era um deles."""
        np = self.now_playing
        action = {"prev": np.previous, "playpause": np.play_pause, "next": np.next}.get(target)
        if action is None:
            return False
        action()
        return True

    # ---------------------------------------------------------------- detalhes por processo

    @staticmethod
    def detail_rect(size: QSize) -> QRect:
        return dev_rect(DETAIL_RECT, size.width() / 1920.0)

    def paint_detail(self, p: QPainter, size: QSize, region: QRect, kind: str, rows) -> None:
        """Painel de detalhes (`ProcStats.poll`) sobre o "cam 01" do painel completo."""
        dev = self.detail_rect(size)
        if not region.intersects(dev):
            return
        name, sub, base = DETAIL_INFO.get(kind, DETAIL_INFO["cpu"])
        col = color(self.led_rgb) if (self.led_on and self.led_rgb) else color(base)
        s = size.width() / 1920.0
        r = DETAIL_RECT
        p.save()
        p.setClipRect(region.intersected(dev))
        p.scale(s, s)
        p.fillRect(r, color(PANEL))
        p.fillRect(r, alpha(col, 14))
        x0, x1 = r.left() + 22, r.right() - 22
        heading(p, x0, r.top() + 42, name, px=26, color_=col)
        label(p, x0, r.top() + 64, sub, upper=False)
        label(p, x1, r.top() + 42, "✕ fechar · 閉じる", color_=TEXT, align=R)
        p.fillRect(QRectF(x0, r.top() + 78, x1 - x0, 1), color(LINE))
        if not rows:
            text(p, r.center().x(), r.center().y(), "解析中 · analisando", key="jp", px=16, color_=TEXT_DIM,
                 align=C)
            p.restore()
            return
        scale = max(rows[0][1], 2.0 if kind == "mem" else 10.0)
        row_h = min(46.0, (r.bottom() - 18 - (r.top() + 90)) / max(8, len(rows)))
        for i, (app, val, extra) in enumerate(rows[:8]):
            y = r.top() + 90 + i * row_h
            cy = y + row_h / 2
            if i % 2 == 0:
                p.fillRect(QRectF(x0 - 8, y, x1 - x0 + 16, row_h - 2), alpha(col, 10))
            label(p, x0, cy + 4.5, f"{i + 1:02d}", color_=col)
            text(p, x0 + 30, cy + 5, app, px=13, max_w=160)
            kit.segments(p, QRectF(x0 + 200, cy - 5, 120, 10), 20, min(100.0, 100.0 * val / scale), col)
            label(p, x0 + 400, cy + 4.5, extra or "", px=11, upper=False, align=R)
            main = f"{val:.1f} GB" if kind == "mem" else f"{val:.1f}%"
            text(p, x1, cy + 5, main, px=14, color_=TEXT, align=R)
        p.restore()


__all__ = ["CARD_DETAIL", "DETAIL_RECT", "NA", "PLAYER", "WiredUI", "build_snapshot", "rgb_hex", "short_gpu"]
