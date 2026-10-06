#!/usr/bin/env python3
"""Renderiza offscreen as peças do kit "wired" (U1) em PNGs 2560×1440 (grade 1920×1080 × 4/3).

    QT_QPA_PLATFORM=offscreen uv run python hud/tools/wired_demo.py [pasta]
    # padrão: ~/.cache/gamerhud/wired-demo/

Arquivos: kit.png (painéis, segmentos, sparklines, rótulos, selo, tingimento LED off/on),
scene-main.png (cena "cam 01" + mascote), scene-standby.png (fundo da espera com as áreas de
texto), mascot.png (prancha com as 7 expressões, bocas, piscada e olhar em dois acentos) e
fonts.png (as quatro famílias).

U3: main-<estado>-<led>.png e standby-<estado>-<led>.png — as duas telas em 2560×1440 nos estados
standby/gaming × LED off / on #ff3b6b / on #3bb6ff, mais main-empty.png e standby-empty.png (sem
nenhum dado), com o tempo de um quadro completo e de um incremental. O snapshot de demonstração
existe só aqui; o código de produção não tem valores simulados.
"""

from __future__ import annotations

import math
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPointF, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QLinearGradient, QPainter, QPixmap  # noqa: E402
from wired import fonts, kit, scene  # noqa: E402
from wired.main_screen import MainScreen, Pilot, Snapshot, Track  # noqa: E402
from wired.mascot import EXPRESSIONS, Mascot  # noqa: E402
from wired.standby_screen import StandbyScreen  # noqa: E402
from wired.theme import (  # noqa: E402
    BG,
    CPU,
    GPU,
    LINE,
    LINE_STRONG,
    RAM,
    TEXT,
    TEXT_DIM,
    TOKENS,
    WARN,
    color,
    tint,
)

W, H, SCALE = 1920, 1080, 4 / 3
RGB = "#ff3b6b"  # cor de exemplo do OpenRGB (a do canvas)
R = Qt.AlignmentFlag.AlignRight
C = Qt.AlignmentFlag.AlignHCenter


def board(name: str, out: Path, draw) -> Path:
    img = QImage(round(W * SCALE), round(H * SCALE), QImage.Format.Format_RGB32)
    img.fill(color(BG))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.scale(SCALE, SCALE)
    draw(p)
    p.end()
    path = out / f"{name}.png"
    img.save(str(path))
    return path


def series(seed: float, base: float, amp: float, n: int) -> list[float]:
    """Só para a demo (o HUD nunca mostra dado simulado, R23.3)."""
    return [max(2, min(98, base + amp * (math.sin(i * .37 + seed) * .5 + math.sin(i * 1.13 + seed * 2) * .3
                                         + math.sin(i * 2.9 + seed * 3) * .2))) for i in range(n)]


def stat_card(p, r, name, col, sub, value, right, pct, warn_from=None, right_col=TEXT):
    kit.panel(p, r)
    x0, x1 = r.left() + 20, r.right() - 20
    kit.heading(p, QPointF(x0, r.top() + 34), name, color_=col)
    kit.label(p, QPointF(x1, r.top() + 32), sub, align=R)
    kit.text(p, QPointF(x0, r.top() + 82), value, key="cond", px=40, color_=TEXT)
    kit.label(p, QPointF(x1, r.top() + 80), right, color_=right_col, align=R)
    kit.segments(p, QRectF(x0, r.bottom() - 24, x1 - x0, 10), 24, pct, col, warn_from)


def draw_kit(p: QPainter) -> None:
    x, w = 28.0, 360.0
    r = QRectF(x, 28, w, 230)
    kit.panel(p, r)
    kit.heading(p, QPointF(48, 64), "FPS", px=24)
    kit.text(p, QPointF(r.right() - 20, 62), "毎秒フレーム数", key="jp", px=12, color_=TEXT_DIM, align=R)
    kit.text(p, QPointF(48, 150), "144", key="cond", px=96, color_=TEXT)
    for i, s in enumerate(("avg 142", "min 118", "max 165")):
        kit.label(p, QPointF(48 + i * 90, 180), s)
    kit.sparkline(p, QRectF(48, 192, w - 40, 40), series(1, 70, 25, 60), TEXT, 1.2)
    stat_card(p, QRectF(x, 274, w, 120), "CPU", CPU, "i5-11400F · 6C/12T", "51%", "50°C", 51)
    stat_card(p, QRectF(x, 410, w, 120), "GPU", GPU, "RX 9060 XT · 161W", "100%", "78°C", 100,
              right_col=WARN)
    stat_card(p, QRectF(x, 546, w, 120), "RAM", RAM, "32GB DDR4 3200", "36%", "11.4 / 32 GB", 36)
    r = QRectF(x, 682, w, 120)
    kit.panel(p, r)
    kit.heading(p, QPointF(48, 716), "Network")
    kit.label(p, QPointF(48, 750), "↓ 2.4 MB/s", color_=TEXT)
    kit.label(p, QPointF(180, 750), "↑ 812 KB/s", color_=TEXT)
    vals = series(4, 40, 30, 60)
    vals[20:26] = [None] * 6  # lacuna = sem dado
    kit.sparkline(p, QRectF(48, 762, w - 40, 30), vals, TEXT_DIM, 1.0)
    # standby do FPS
    r = QRectF(x, 818, w, 230)
    kit.panel(p, r)
    kit.heading(p, QPointF(48, 854), "FPS", px=24)
    kit.text(p, QPointF(48, 940), "– –", key="cond", px=96, color_=LINE_STRONG)
    kit.heading(p, QPointF(48, 980), "No signal", px=20, color_=TEXT_DIM)
    kit.text(p, QPointF(150, 980), "ゲーム未検出", key="jp", px=14, color_=TEXT_DIM)

    # MAGI SYSTEM: LED off e LED on
    for col, led in ((420, False), (980, True)):
        top = 28.0
        kit.heading(p, QPointF(col, top + 26), f"MAGI system — LED {'on' if led else 'off'}")
        units = (("Melchior", "magi·1 // cpu", CPU, 51, 50), ("Balthasar", "magi·2 // gpu", GPU, 100, 78),
                 ("Casper", "magi·3 // memory", RAM, 29, 36))
        for i, (name, sub, base, load, temp) in enumerate(units):
            t = tint(base, RGB, led)
            r = QRectF(col, top + 50 + i * 130, 540, 116)
            p.fillRect(r, t.bg)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(t.border)
            p.drawRect(r.adjusted(.5, .5, -.5, -.5))
            kit.text(p, QPointF(r.left() + 18, r.top() + 36), name.upper(), key="cond", px=26,
                     weight=600, spacing=.04, color_=t.color)
            kit.label(p, QPointF(r.left() + 18, r.top() + 58), sub, px=11)
            for j, (k, pct, wf, v) in enumerate((("負荷 load", load, None, f"{load}%"),
                                                  ("温度 temp", temp, 15, f"{temp}°"))):
                y = r.top() + 76 + j * 22
                kit.text(p, QPointF(r.left() + 18, y + 10), k, key="jp", px=12, color_=TEXT_DIM)
                kit.segments(p, QRectF(r.left() + 92, y, 290, 12), 20, pct, t.seg, wf)
                kit.text(p, QPointF(r.left() + 458, y + 11), v, px=14, color_=TEXT, align=R)
            kit.seal(p, QRectF(r.right() - 70, r.top() + 1, 70, r.height() - 2), t.color)
        # botão LED
        b = QRectF(col + 380, top, 160, 44)
        p.fillRect(b, color("#14121b"))
        p.setPen(color(RGB) if led else color(LINE_STRONG))
        p.drawRect(b.adjusted(.5, .5, -.5, -.5))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        if led:
            glow = color(RGB)
            glow.setAlpha(70)
            p.setBrush(glow)
            p.drawEllipse(QPointF(b.left() + 20, b.center().y()), 9, 9)
        p.setBrush(color(RGB) if led else color(LINE_STRONG))
        p.drawEllipse(QPointF(b.left() + 20, b.center().y()), 5, 5)
        kit.text(p, QPointF(b.left() + 36, b.center().y() + 5), "点灯" if led else "消灯", key="jp",
                 px=13, color_=TEXT)
        kit.label(p, QPointF(b.left() + 76, b.center().y() + 4), "on" if led else "off", color_=TEXT)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    # barras de temperatura: warn a partir de 75%, 3 últimas hot
    y0 = 490.0
    kit.heading(p, QPointF(420, y0), "Segmentos — temperatura (warn 75%+, hot 3 últimos)")
    for i, pct in enumerate((40, 74, 80, 90, 100)):
        y = y0 + 20 + i * 26
        kit.label(p, QPointF(420, y + 11), f"{pct}%")
        n = kit.segments(p, QRectF(480, y, 500, 12), 20, pct, CPU, 15)
        kit.label(p, QPointF(1000, y + 11), f"{n}/20 acesos")
    # scanlines sobre painel
    r = QRectF(420, 640, 540, 400)
    path = kit.panel(p, r)
    p.drawPixmap(r.toRect(), scene.main_scene(r.width(), r.height(), CPU, SCALE))
    kit.draw_scanlines(p, r, clip=path)
    kit.panel(p, r, fill=None)
    kit.label(p, QPointF(444, 676), "cam 01 // 電線", color_=TEXT)
    kit.label(p, QPointF(444, 696), "rec ● 19:04")
    kit.text(p, QPointF(444, 1000), "信号は、まだ届いている。", key="jp", px=18, color_=TEXT, spacing=.14)
    kit.label(p, QPointF(444, 1022), "the signal is still arriving.", upper=False)
    # rótulos e selos soltos
    r = QRectF(980, 640, 540, 400)
    kit.panel(p, r)
    kit.heading(p, QPointF(1000, 676), "Rótulos")
    kit.label(p, QPointF(1000, 706), "General purpose monitoring system — MAGI-01", px=13)
    kit.text(p, QPointF(1000, 760), "汎用監視システム", key="mincho", px=46, color_=TEXT, spacing=.06)
    kit.text(p, QPointF(1000, 800), "私は、ここにいる。", key="jp", px=16, color_=TEXT, spacing=.2)
    kit.text(p, QPointF(1000, 900), "19:04", key="cond", px=84, color_=TEXT, spacing=.02)
    kit.text(p, QPointF(1200, 900), "37", key="cond", px=32, color_=TEXT_DIM)
    for i, c in enumerate((CPU, GPU, RAM, RGB)):
        kit.seal(p, QRectF(1260 + i * 64, 930, 60, 90), c, divider=i > 0)
    p.fillRect(QRectF(1540, 0, 1, H), color(LINE))
    kit.label(p, QPointF(1560, 60), "tokens")
    for i, (k, v) in enumerate(TOKENS.items()):
        y = 80 + i * 34
        p.fillRect(QRectF(1560, y, 26, 26), color(v))
        p.setPen(color(LINE))
        p.drawRect(QRectF(1560, y, 26, 26))
        kit.label(p, QPointF(1598, y + 18), f"{k} {v}", color_=TEXT)


def draw_scene_main(p: QPainter) -> None:
    # centro-topo do Painel: cena (flex 1.4) + mascote (flex 1)
    r = QRectF(408, 144, 924, 510)
    path = kit.panel(p, r)
    sw = r.width() * 1.4 / 2.4
    sr = QRectF(r.left(), r.top(), sw, r.height())
    p.save()
    p.setClipPath(path)
    p.drawPixmap(sr, scene.main_scene(sr.width(), sr.height(), CPU, SCALE), QRectF())
    p.restore()
    kit.draw_scanlines(p, sr, clip=path)
    kit.panel(p, r, fill=None)
    p.fillRect(QRectF(sr.right(), r.top(), 1, r.height()), color(LINE))
    kit.label(p, QPointF(sr.left() + 24, sr.top() + 36), "cam 01 // 電線", color_=TEXT)
    kit.label(p, QPointF(sr.left() + 24, sr.top() + 56), "rec ● 19:04")
    kit.text(p, QPointF(sr.left() + 24, sr.bottom() - 44), "信号は、まだ届いている。", key="jp", px=18,
             color_=TEXT, spacing=.14)
    kit.label(p, QPointF(sr.left() + 24, sr.bottom() - 22), "the signal is still arriving.", upper=False)
    x0 = sr.right() + 22
    kit.label(p, QPointF(x0, r.top() + 36), "magi-01 // condessa")
    m = Mascot("listening", rng=random.Random(1), now=0.0)
    m.tick(0.0)
    m.paint(p, QRectF(x0, r.top() + 52, r.right() - 22 - x0, 150), CPU)
    chip = QRectF(x0, r.top() + 216, 120, 34)
    p.setPen(color(LINE_STRONG))
    p.drawRect(chip)
    kit.heading(p, QPointF(x0 + 14, chip.bottom() - 9), "Online", px=18, color_=GPU)
    kit.text(p, QPointF(x0, r.top() + 290), "「同期完了。見ているよ。」", key="jp", px=16, color_=TEXT)
    kit.label(p, QPointF(x0, r.top() + 318), "sync complete. watching.", upper=False)
    # a mesma cena em outro tamanho (cache por tamanho)
    r2 = QRectF(408, 680, 400, 360)
    path = kit.panel(p, r2)
    p.save()
    p.setClipPath(path)
    p.drawPixmap(r2, scene.main_scene(r2.width(), r2.height(), RGB, SCALE), QRectF())
    p.restore()
    kit.draw_scanlines(p, r2, clip=path)
    kit.panel(p, r2, fill=None)
    kit.label(p, QPointF(r2.left() + 20, r2.top() + 32), "400×360 · acento rgb", color_=TEXT)


def draw_scene_standby(p: QPainter) -> None:
    p.drawPixmap(QRectF(0, 0, W, H), scene.standby_scene(W, H, RGB, SCALE), QRectF())
    kit.draw_scanlines(p, QRectF(0, 0, W, H))
    p.fillRect(QRectF(160, 170, 4, H - 340), color(RGB))  # trilho tingido pelo LED
    x = 208
    kit.heading(p, QPointF(x, 200), "MAGI system", px=24, color_=TEXT_DIM)
    kit.text(p, QPointF(x + 160, 200), "待機中", key="jp", px=22, color_=TEXT_DIM)
    kit.text(p, QPointF(x, 420), "拾九時", key="mincho", px=180, color_=TEXT)
    kit.text(p, QPointF(x, 640), "拾壱分", key="mincho", px=180, color_=TEXT)
    kit.label(p, QPointF(x, 720), "nineteen eleven", px=20, color_=TEXT)
    kit.label(p, QPointF(x, 760), "sex · 02 out 2026", px=16)
    col = QRectF(1180, 170, 440, H - 340)
    kit.label(p, QPointF(col.left(), col.top() + 20), "status // led 点灯 on", color_=TEXT)
    m = Mascot("sleeping", now=0.0)
    m.tick(0.0)
    m.paint(p, QRectF(col.left(), col.center().y() - 58, 200, 115), RGB)
    kit.text(p, QPointF(col.left() + 220, col.center().y()), "「おやすみ…」", key="jp", px=16, color_=TEXT)
    kit.label(p, QPointF(col.left(), col.bottom() - 10), "now playing – –")
    ok = all(scene.standby_text_safe(r) for r in (QRectF(160, 170, 900, H - 340), col))
    kit.label(p, QPointF(160, H - 70), f"meta+m · painel completo   [texto livre do cenário: {ok}]", px=12)


def draw_mascot(p: QPainter) -> None:
    shots = [(e, e, 0.0, None) for e in EXPRESSIONS if e != "speaking"]
    shots += [("speaking —", "speaking", 0.05, None), ("speaking o", "speaking", 0.3, None),
              ("speaking O", "speaking", 0.8, None), ("piscada", "listening", 0.0, "blink"),
              ("olhar ←", "listening", 0.0, -1), ("olhar →", "speaking", 0.6, 1)]
    cw, ch = 300.0, 230.0
    for row, accent in enumerate((CPU, RGB)):
        for i, (name, expr, lvl, mod) in enumerate(shots):
            col_i, sub = i % 6, i // 6
            r = QRectF(28 + col_i * (cw + 14), 28 + (row * 2 + sub) * (ch + 34), cw, ch)
            kit.panel(p, r)
            m = Mascot(expr, rng=random.Random(3), now=0.0)
            m.set_level(lvl)
            now = 0.0
            if mod == "blink":
                now = m._blink_at + 0.01
            elif mod in (-1, 1):
                m._glance_dir, m._glance_end = mod, 10.0
            m.tick(now)
            m.paint(p, QRectF(r.left() + 20, r.top() + 20, cw - 40, ch - 70), accent, now)
            kit.label(p, QPointF(r.left() + 20, r.bottom() - 22), name, color_=TEXT, upper=False)
            kit.label(p, QPointF(r.right() - 20, r.bottom() - 22), f"mouth {m.mouth}", align=R,
                      upper=False)


def draw_fonts(p: QPainter) -> None:
    y = 100.0
    for key, w, s in (("mincho", 700, "汎用監視システム 拾九時 Shippori Mincho 700"),
                      ("cond", 500, "144 19:04 BARLOW CONDENSED 500"),
                      ("cond", 600, "LOAD HISTORY · MAGI SYSTEM 600"),
                      ("mono", 400, "JETBRAINS MONO 400 · cpu i5-11400F 51%"),
                      ("mono", 500, "JETBRAINS MONO 500 · ↓ 2.4 MB/s ↑ 812 KB/s"),
                      ("jp", 400, "私は、ここにいる。信号は、まだ届いている。 Zen Kaku 400"),
                      ("jp", 500, "正常 負荷履歴 機体情報 Zen Kaku 500")):
        kit.text(p, QPointF(60, y), s, key=key, px=56, weight=w, color_=TEXT)
        kit.label(p, QPointF(60, y + 30), f"{key} {w} → {fonts.font(key, 56, w).families()[0]}")
        y += 130


# ------------------------------------------------------------------ U3: telas (dados de demonstração)

DEMO_NOW = datetime(2026, 10, 3, 19, 11, 42)


def demo_cover() -> QPixmap:
    pm = QPixmap(300, 300)
    p = QPainter(pm)
    g = QLinearGradient(0, 0, 300, 300)
    g.setColorAt(0, color("#2a1f3d"))
    g.setColorAt(1, color("#0d2a2a"))
    p.fillRect(0, 0, 300, 300, g)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color("#e8b04a"))
    p.drawEllipse(QPointF(190, 110), 46, 46)
    p.end()
    return pm


def demo_snapshot(mode: str, rgb: str | None) -> Snapshot:
    gaming = mode == "gaming"
    hist = {k: series(seed, base, 18 if k != "ram" else 3, 120)
            for k, seed, base in (("cpu", 2, 50 if gaming else 22), ("gpu", 5, 84 if gaming else 30),
                                  ("ram", 9, 36))}
    axis = [(i / 4, f"{18 + (i + 1) // 4:02d}:{(i * 15 + 11) % 60:02d}") for i in range(5)]
    fps_series = [max(60.0, v * 1.6 + 30) for v in series(1, 70, 25, 60)]
    return Snapshot(
        gaming=gaming,
        cpu=51 if gaming else 12, cpu_temp=50 if gaming else 41,
        gpu=100 if gaming else 6, gpu_temp=78 if gaming else 44, gpu_w=161 if gaming else 14,
        ram=36, ram_txt="11.4/32G", vram=29, vram_txt="4.7/16G",
        cpu_label="i5-11400F · 6C/12T", gpu_label="RX 9060 XT", ram_label="32GB DDR4 3200",
        specs=[("CPU", "INTEL CORE I5-11400F"), ("GPU", "AMD RADEON RX 9060 XT 16G"),
               ("M/B", "GIGABYTE Z490 AORUS PRO AX"), ("RAM", "32 GB DDR4 3200"),
               ("OS", "NOBARA LINUX 44 · 7.2.6"), ("MESA", "26.2.3")],
        pilots=[Pilot("DUALSENSE", 25, "BT", True)],
        net_down=2.4e6, net_up=812e3, net_series=[v * 3e4 for v in series(4, 45, 35, 60)],
        history=hist, history_axis=axis,
        fps=144 if gaming else None, fps_min=118 if gaming else None, fps_avg=142 if gaming else None,
        fps_max=165 if gaming else None, fps_series=fps_series if gaming else [],
        track=Track("Demo Track Title", "Demo Artist", "Demo Album", 2024, 102.0, 238.0,
                    playing=gaming, cover=demo_cover() if gaming else None),
        events=["[19:03:24] game.exe launched", "[19:03:41] network up 2.4 MB/s", "[19:04:10] user active"],
        news=[("19:08", "A Bandai Namco mostrou três minutos de gameplay de Gundam Rogue Orbit, que chega em "
                        "março de 2027."),
              ("19:06", "O criador de Hunter x Hunter vai recusar trabalhos com prazo para cuidar da saúde."),
              ("19:05", "The Record of a Fallen Vampire vai virar anime para TV em 2027.")],
        led_on=rgb is not None, led_rgb=rgb,
        magui_state="listening" if gaming else "sleeping",
    )


def render_screen(screen, snap: Snapshot, path: Path, mono: float = 0.0) -> float:
    size = QSize(round(W * SCALE), round(H * SCALE))
    img = QImage(size, QImage.Format.Format_RGB32)
    p = QPainter(img)
    t0 = time.perf_counter()
    screen.paint(p, size, snap, DEMO_NOW, mono=mono)
    dt = time.perf_counter() - t0
    p.end()
    img.save(str(path))
    return dt


def bench(screen, snap: Snapshot, n: int = 20) -> tuple[float, float]:
    """(quadro completo, quadro incremental de 1 s) em ms, 2560×1440 offscreen."""
    size = QSize(round(W * SCALE), round(H * SCALE))
    img = QImage(size, QImage.Format.Format_RGB32)
    full = []
    for _ in range(n):
        screen._static = None  # força a reconstrução do cache
        p = QPainter(img)
        t0 = time.perf_counter()
        screen.paint(p, size, snap, DEMO_NOW, mono=0.0)
        full.append(time.perf_counter() - t0)
        p.end()
    inc = []
    for i in range(1, n + 1):
        now = DEMO_NOW.replace(second=(DEMO_NOW.second + i) % 60)
        t0 = time.perf_counter()
        regs = screen.dirty_regions(snap, now, size)
        p = QPainter(img)
        for r in regs:
            screen.paint(p, size, snap, now, mono=float(i), region=r)
        p.end()
        inc.append(time.perf_counter() - t0)
    return sorted(full)[n // 2] * 1e3, sorted(inc)[n // 2] * 1e3


def render_screens(out: Path) -> None:
    for mode in ("standby", "gaming"):
        for led, rgb in (("off", None), ("on-ff3b6b", "#ff3b6b"), ("on-3bb6ff", "#3bb6ff")):
            snap = demo_snapshot(mode, rgb)
            for prefix, cls in (("main", MainScreen), ("standby", StandbyScreen)):
                path = out / f"{prefix}-{mode}-{led}.png"
                render_screen(cls(), snap, path)
                print(path)
    for prefix, cls in (("main", MainScreen), ("standby", StandbyScreen)):
        path = out / f"{prefix}-empty.png"
        render_screen(cls(), Snapshot(), path)
        print(path)
    for prefix, cls, mode in (("main", MainScreen, "gaming"), ("standby", StandbyScreen, "standby")):
        full, inc = bench(cls(), demo_snapshot(mode, "#ff3b6b"))
        print(f"{prefix}: quadro completo {full:.1f} ms · incremental (1 s) {inc:.2f} ms")


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".cache/gamerhud/wired-demo"
    out.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841
    print("fontes:", fonts.load())
    for name, fn in (("kit", draw_kit), ("scene-main", draw_scene_main),
                     ("scene-standby", draw_scene_standby), ("mascot", draw_mascot), ("fonts", draw_fonts)):
        print(board(name, out, fn))
    render_screens(out)


if __name__ == "__main__":
    main()
