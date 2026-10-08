import re
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from wired import main_screen as ms
from wired.main_screen import MainScreen, Pilot, Snapshot, Track
from wired.standby_screen import StandbyScreen, en_words, kanji_num

SIZE = QSize(2560, 1440)
NOW = datetime(2026, 10, 3, 19, 11, 42)
HUD = Path(__file__).resolve().parents[2] / "hud" / "wired"


def full_snapshot(**kw) -> Snapshot:
    cover = QPixmap(64, 64)
    cover.fill(QColor("#335577"))
    base = dict(
        gaming=True, cpu=51.0, cpu_temp=80.0, gpu=99.0, gpu_temp=78.0, gpu_w=160.0, ram=36.0,
        ram_txt="11.4/32G", vram=29.0, vram_txt="4.7/16G", cpu_label="cpu x", gpu_label="gpu y",
        ram_label="32GB", specs=[("CPU", "A"), ("GPU", "B")], pilots=[Pilot("PAD", "40", "BT", True)],
        net_down=1e6, net_up=2e3, net_series=[1.0, 5.0, 3.0], history={"cpu": [1.0, None, 50.0]},
        history_axis=[(0.0, "18:11"), (0.5, "18:41"), (1.0, "19:11")], fps=120.0, fps_min=90.0,
        fps_avg=110.0, fps_max=130.0, fps_series=[100.0, 120.0], events=["[19:00:00] x"],
        track=Track("t", "a", "al", 2020, 30.0, 200.0, True, cover), led_on=True, led_rgb="#ff3b6b",
        magui_state="speaking", mouth_level=0.7, caption="uma legenda longa " * 8,
    )
    base.update(kw)
    return Snapshot(**base)


def render(screen, snap, size=SIZE, region=None, now=NOW) -> QImage:
    img = QImage(size, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    screen.paint(p, size, snap, now, mono=0.0, region=region)
    p.end()
    return img


@pytest.mark.parametrize("cls", [MainScreen, StandbyScreen])
@pytest.mark.parametrize("snap", [Snapshot(), full_snapshot(),
                                  full_snapshot(magui_state="nope", led_rgb=None)])
def test_paint_empty_and_full(cls, snap):
    img = render(cls(), snap)
    assert not img.isNull()
    if cls is StandbyScreen:
        assert img.pixelColor(5, 5) == QColor("#09080d")
        return
    # painel: fundo do mockup (#09080f) no vão entre colunas, longe da vinheta (scanline: +4 no máximo)
    c = img.pixelColor(round(472 * ms.F * 4 / 3), round(480 * ms.F * 4 / 3))
    bg = QColor(ms.M_BG)
    pairs = ((c.red(), bg.red()), (c.green(), bg.green()), (c.blue(), bg.blue()))
    assert all(abs(x - y) <= 5 for x, y in pairs)
    assert img.pixelColor(2, 2).lightness() <= bg.lightness()  # canto escurecido pela vinheta


def test_paint_other_size():
    render(MainScreen(), full_snapshot(), QSize(1920, 1080))
    render(StandbyScreen(), Snapshot(), QSize(3840, 2160))


def test_hit_test_scale_4_3():
    sc = MainScreen()
    s = 4 / 3

    def at(r):
        return QPoint(round(r.center().x() * s), round(r.center().y() * s))

    assert sc.hit_test(at(ms.LED_BTN), SIZE) == "led"
    assert sc.hit_test(at(ms.LEARN_BTN), SIZE) == "learning"
    assert sc.hit_test(at(ms.KONSOLE), SIZE) == "konsole"
    for k in ("prev", "playpause", "next"):
        assert sc.hit_test(at(ms.BTNS[k]), SIZE) == k
        # controles do mockup: 36×32 → 41×37 na base 1920 (≈ 55×49 px no monitor 2)
        assert ms.BTNS[k].width() >= 40 and ms.BTNS[k].height() >= 36
    for k, unit in zip(("cpu", "gpu", "ram"), ms.UNITS, strict=True):  # unidades MAGI abrem o detalhe
        assert sc.hit_test(at(unit), SIZE) == f"card:{k}"
    assert sc.hit_test(at(ms.CARD_NET), SIZE) is None
    assert sc.hit_test(at(ms.RADIO), SIZE) is None
    assert sc.hit_test(at(ms.TALK), SIZE) is None
    assert sc.hit_test(QPoint(5, 5), SIZE) is None
    assert ms.LED_BTN.height() >= 38
    assert StandbyScreen().hit_test(QPoint(1000, 700), SIZE) is None


def test_no_demo_strings_in_production():
    for f in ("main_screen.py", "standby_screen.py"):
        src = (HUD / f).read_text()
        for bad in ("[Nome da faixa]", "[Artista]", "[capa do álbum]", "Demo Track"):
            assert bad not in src, (f, bad)
        assert not re.search(r"(?<![\d.])144(?![\d.])", src), f  # FPS do canvas (1440 pode)


def test_dirty_regions_and_incremental_time():
    sc = MainScreen()
    snap = full_snapshot(caption=None)
    render(sc, snap)
    assert sc.dirty_regions(snap, NOW, SIZE) == []
    nxt = NOW.replace(second=43)
    regs = sc.dirty_regions(snap, nxt, SIZE)
    assert regs and all(isinstance(r, QRect) for r in regs)
    assert sum(r.width() * r.height() for r in regs) < SIZE.width() * SIZE.height() * 0.1
    snap2 = full_snapshot(caption=None, cpu=10.0)
    regs2 = sc.dirty_regions(snap2, NOW, SIZE)
    assert len(regs2) >= 2  # card CPU + MAGI
    # quadro incremental (relógio) bem abaixo do completo
    img = QImage(SIZE, QImage.Format.Format_RGB32)
    t0 = time.perf_counter()
    for i in range(10):
        now = NOW.replace(second=(43 + i) % 60)
        p = QPainter(img)
        for r in sc.dirty_regions(snap, now, SIZE):
            sc.paint(p, SIZE, snap, now, mono=0.0, region=r)
        p.end()
    assert (time.perf_counter() - t0) / 10 < 0.010


def test_standby_clock_only_on_minute():
    sc = StandbyScreen()
    snap = Snapshot()
    render(sc, snap)
    assert sc.dirty_regions(snap, NOW.replace(second=59), SIZE) == []
    assert sc.dirty_regions(snap, NOW.replace(minute=12), SIZE)
    assert sc.dirty_regions(Snapshot(led_on=True, led_rgb="#3bb6ff"), NOW, SIZE)


def test_mascot_tick_region():
    sc = MainScreen()
    render(sc, Snapshot(magui_state="listening"))
    rect, nxt = sc.mascot_tick(100.0, SIZE)
    assert rect is not None and nxt > 100.0
    assert rect.width() < 600


def test_partial_paint_matches_full():
    snap = full_snapshot(caption=None)
    a = render(MainScreen(), snap)
    sc = MainScreen()
    render(sc, snap)
    img = render(sc, snap)  # mesma tela, mesmo dado
    reg = QRect(0, 0, 900, 700)
    p = QPainter(img)
    sc.paint(p, SIZE, snap, NOW, mono=0.0, region=reg)
    p.end()
    assert img.copy(reg) == a.copy(reg)


def test_kanji_and_words():
    assert kanji_num(19) + "時" == "拾九時"
    assert kanji_num(11) + "分" == "拾壱分"
    assert kanji_num(0) == "零"
    assert kanji_num(37) == "参拾七"
    assert en_words(19, 11) == "NINETEEN ELEVEN"
    assert en_words(7, 5) == "SEVEN OH FIVE"
    assert en_words(0, 0) == "ZERO O'CLOCK"
    assert en_words(23, 59) == "TWENTY-THREE FIFTY-NINE"


def test_formatting_none():
    assert ms.num(None) == ms.NA
    assert ms.gb(None) == ms.NA and ms.gb("--") == ms.NA
    assert ms.gb("11.4/32G") == "11.4 / 32 GB"
    assert ms.mmss(None) == ms.NA and ms.mmss(102) == "1:42"


def _focus_px(img: QImage) -> int:
    """Pixels na cor de foco (#5fd0e0), amostrados de 2 em 2."""
    n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            n += abs(c.red() - 0x5F) < 30 and abs(c.green() - 0xD0) < 30 and abs(c.blue() - 0xE0) < 30
    return n


def test_chip_de_estado_ouvindo_e_pensando():
    from wired.main_screen import chip_label

    assert chip_label(Snapshot(magui_state="listening"))[0] == "Listening · 聴取中"
    assert chip_label(Snapshot(magui_state="thinking"))[0] == "Thinking · 思考中"
    assert chip_label(Snapshot(gaming=True, magui_state="sleeping"))[0] == "Active · 稼働中"
    assert chip_label(Snapshot(magui_state="speaking"))[0] == "Speaking · 発話中"  # falando não é Standby
    assert chip_label(Snapshot(magui_state="happy"))[0] == "Standby · 待機中"
    # a fase do turno (turn_phase) manda no chip: "happy" na resposta falada continua Speaking
    assert chip_label(Snapshot(magui_state="happy", chip="speaking"))[0] == "Speaking · 発話中"
    assert chip_label(Snapshot(magui_state="listening", chip="idle"))[0] == "Standby · 待機中"
    assert chip_label(Snapshot(magui_state="listening"))[2]  # aceso (cor de foco)
    size = QSize(1280, 720)
    for cls in (MainScreen, StandbyScreen):
        sc = cls()
        idle, heard = Snapshot(), Snapshot(magui_state="listening")
        assert sc.group_key("talk", idle, NOW) != sc.group_key("talk", heard, NOW)  # redesenha o chip
        assert sc.group_key("talk", heard, NOW) != sc.group_key("talk", Snapshot(magui_state="thinking"), NOW)
        render(sc, idle, size)
        assert any(r.intersects(QRect(0, 0, 1280, 720)) for r in sc.dirty_regions(heard, NOW, size))
        assert _focus_px(render(cls(), heard, size)) > _focus_px(render(cls(), idle, size)) + 20


def test_uso_proprio_no_system_activity():
    from wired.data import SelfView
    u = SelfView(cpu=80.0, cpu_total=9.4, ram_mb=1248.6, gpu=3.2, vram_mb=212.0)
    snap = full_snapshot(caption=None, self_usage=u)
    rows = ms.self_rows(snap)
    assert [(k, v) for k, v, _ in rows] == [("CPU", "9%"), ("GPU", "3%"), ("RAM", "1.2G"), ("VRAM", "210M")]
    assert rows[2][2] == pytest.approx(100 * 1248.6 / 1024 / 32, abs=0.1)  # barra: % da RAM da máquina
    assert ms.self_rows(full_snapshot()) is None
    # muda só depois do arredondamento: nada a redesenhar; mudou o número: só o corpo do card
    sc = MainScreen()
    render(sc, snap)
    same = replace(snap, self_usage=SelfView(cpu=80.0, cpu_total=9.1, ram_mb=1250.0, gpu=3.4, vram_mb=209.0))
    assert sc.dirty_regions(same, NOW, SIZE) == []
    other = replace(snap, self_usage=SelfView(cpu=80.0, cpu_total=14.0, ram_mb=1250.0, gpu=3.4,
                                              vram_mb=209.0))
    assert sc.dirty_regions(other, NOW, SIZE) == sc.group_rects("activity", SIZE)
