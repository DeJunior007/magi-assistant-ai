"""Integração do tema wired no gamerhud (U4) + termômetro de humor (4.4), offscreen."""

from __future__ import annotations

from collections import deque
from datetime import datetime

import gamerhud
import hud_bridge
import pytest
from PySide6.QtCore import QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from wired import main_screen as ms
from wired.data import EventLog, FpsStats, LoadHistory
from wired.integration import DETAIL_RECT, WiredUI, build_snapshot, rgb_hex, short_gpu
from wired.main_screen import MainScreen, Snapshot, draw_mood, mood_color
from wired.standby_screen import StandbyScreen
from wired.theme import GPU, HOT, SEG_OFF, TEXT_DIM, WARN

SIZE = QSize(2560, 1440)
S = 2560 / 1920
DATA = {"cpu": 51.0, "cpu_temp": 80.0, "gpu": 99.0, "gpu_temp": 78.0, "gpu_w": 160.0, "ram": 36.0,
        "ram_txt": "11.4/32G", "vram": 29.0, "vram_txt": "4.7/16G"}
SPEC = [("CPU", "INTEL CORE I5-11400F · 6C/12T"), ("GPU", "AMD RADEON RX 9060 XT · 16 GB"), ("RAM", "32 GB")]


class FakeNP:
    def __init__(self, title="Duvet", artist="bôa", status="Playing"):
        self.title, self.artist, self.album, self.year = title, artist, "Twilight", "2001"
        self.length, self.status = 203.0, status
        self.calls = []

    @property
    def active(self):
        return self.status is not None and bool(self.title)

    def position(self, now=None):
        return 74.0

    def cover_pixmap(self):
        return None

    def tick(self, now=None):
        pass

    def previous(self):
        self.calls.append("Previous")

    def next(self):
        self.calls.append("Next")

    def play_pause(self):
        self.calls.append("PlayPause")


class FakeNet:
    down, up = 1000.0, 20.0
    down_series = deque([1.0, 5.0, 3.0])

    def poll(self, now=None):
        pass


def make_ui(np=None):
    return WiredUI(now_playing=np or FakeNP(), net=FakeNet())


# ------------------------------------------------------------------ Snapshot


def test_snapshot_das_fontes():
    hist = LoadHistory()
    hist.push(50.0, 90.0, 30.0, 1000.0)
    fps = FpsStats()
    for i, v in enumerate((100.0, 120.0, 110.0)):
        fps.push(v, float(i))
    ev = EventLog()
    ev.add("jogo detectado: X", 0.0)
    snap = build_snapshot(DATA, spec=SPEC, pads=[("DUALSENSE", 95, "USB", True)], gaming=True,
                          fps=fps.snapshot(), net=FakeNet(), history=hist, now_playing=FakeNP(), events=ev,
                          led_on=True, led_rgb="#ff3b6b", magui_state="speaking", mouth_level=0.4,
                          caption="oi", mood=7)
    assert (snap.cpu, snap.gpu, snap.vram_txt, snap.ram_txt) == (51.0, 99.0, "4.7/16G", "11.4/32G")
    assert snap.cpu_label.startswith("INTEL") and snap.gpu_label == "AMD RADEON RX 9060 XT"
    assert snap.pilots[0].name == "DUALSENSE" and snap.pilots[0].charging
    assert (snap.fps, snap.fps_min, snap.fps_max) == (110.0, 100.0, 120.0)
    assert snap.net_down == 1000.0 and snap.net_series == [1.0, 5.0, 3.0]
    assert snap.history["gpu"] == [90.0] and snap.history_axis
    assert snap.track.title == "Duvet" and snap.track.playing and snap.track.position == 74.0
    assert snap.events[0].endswith("jogo detectado: X")
    assert (snap.led_rgb, snap.magui_state, snap.caption, snap.mood) == ("#ff3b6b", "speaking", "oi", 4)


def test_snapshot_vazio_sem_dado_simulado():
    snap = build_snapshot({**DATA, "gpu": 0.0, "vram": 0.0, "vram_txt": "--"},
                          now_playing=FakeNP(status=None),
                          led_on=False, led_rgb="#ff0000", magui_state="xyz", caption="", mood=None)
    assert snap.gpu is None and snap.vram is None and snap.vram_txt is None
    assert snap.track is None and snap.fps is None and snap.led_rgb is None
    assert snap.magui_state == "sleeping" and snap.caption is None and snap.mood is None


def test_rgb_hex_e_gpu_curta():
    assert rgb_hex((255, 59, 107, 1.0)) == "#ff3b6b"
    assert rgb_hex((0, 0, 0, 0.0)) is None and rgb_hex(None) is None
    assert short_gpu("--") is None and short_gpu("X · 8 GB") == "X"


def test_eventos_do_rodape():
    np = FakeNP()
    ui = make_ui(np)
    ui.poll(DATA, None, "ELDEN RING", 1.0, 1000.0)
    np.title = "Outra"
    ui.poll(DATA, 120.0, "ELDEN RING", 2.0, 1001.0)
    ui.poll(DATA, None, None, 3.0, 1002.0)
    ui.set_state("listening")
    ui.set_state("thinking")  # só a 1ª saída do sono conta
    ui.on_card({"level": "bomba", "title": "Patch novo"})
    ui.on_card({"level": "link", "title": "ignorado"})
    ui.set_led(True, None)
    ui.set_led(True, None)  # avisa uma vez só
    texts = [t for _, t in ui.events.entries]
    assert texts == ["jogo detectado: ELDEN RING", "♪ Duvet — bôa", "♪ Outra — bôa",
                     "jogo fechado: ELDEN RING", "magui ativada", "⚠ Patch novo",
                     "openrgb sem resposta · led off"]
    assert ui.build(DATA).led_rgb is None  # OpenRGB fora → visual off


def test_estado_da_magui_vai_ao_snapshot_e_ao_mascote():
    ui = make_ui()
    ui.set_state("speaking")
    ui.set_mouth(0.8)
    ui.set_caption("legenda")
    ui.set_mood(2)
    snap = ui.build(DATA)
    assert (snap.magui_state, snap.mouth_level, snap.caption, snap.mood) == ("speaking", 0.8, "legenda", 2)
    assert ui.mascot.state == "speaking" and ui.main.mascot is ui.standby.mascot
    ui.on_connected(False)
    assert ui.build(DATA).magui_state == "sleeping" and ui.snap.caption is None


# ------------------------------------------------------------------ termômetro


@pytest.mark.parametrize("mood,col", [(0, HOT), (1, WARN), (2, TEXT_DIM), (3, GPU), (4, GPU)])
def test_cor_do_termometro(mood, col):
    assert mood_color(Snapshot(mood=mood)).name() == col
    assert mood_color(Snapshot(mood=mood, led_on=True, led_rgb="#ff3b6b")).name() == \
        ("#ff3b6b" if mood >= 3 else col)
    assert mood_color(Snapshot(mood=None)) is None


def lit_segments(mood):
    img = QImage(60, 200, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    draw_mood(p, ms.QRectF(10, 10, 24, 180), Snapshot(mood=mood), legend=False)
    p.end()
    off = QColor(SEG_OFF).rgb()
    h = (180 - 3 * 4) / 5
    ys = [int(190 - (i + 0.5) * h - i * 3) for i in range(5)]  # centro de cada segmento, de baixo pra cima
    return [img.pixel(22, y) != off for y in ys]


@pytest.mark.parametrize("mood", [None, 0, 2, 4])
def test_termometro_acende_por_nivel(mood):
    n = 0 if mood is None else mood + 1
    assert lit_segments(mood) == [True] * n + [False] * (5 - n)


@pytest.mark.parametrize("cls", [MainScreen, StandbyScreen])
def test_termometro_nas_duas_telas_invalida_so_ele(cls):
    scr = cls()
    img = QImage(SIZE, QImage.Format.Format_RGB32)
    p = QPainter(img)
    scr.paint(p, SIZE, Snapshot(mood=1), datetime(2026, 10, 3, 19, 11, 42), mono=0.0)
    p.end()
    assert scr.dirty_regions(Snapshot(mood=1), datetime(2026, 10, 3, 19, 11, 42), SIZE) == []
    dirty = scr.dirty_regions(Snapshot(mood=4), datetime(2026, 10, 3, 19, 11, 42), SIZE)
    assert len(dirty) == 1 and dirty[0].width() < 40


def test_barras_das_unidades_preenchem_a_coluna():
    name_w, key_w, val_w = ms.unit_columns()
    r = ms.UNITS[0]
    seg_w = (r.right() - 15 - 70 - ms.UNIT_GAP - val_w - ms.ROW_GAP) - \
        (r.left() + 15 + name_w + ms.UNIT_GAP + key_w + ms.ROW_GAP)
    assert seg_w >= 90


# ------------------------------------------------------------------ HUD real (gamerhud)


@pytest.fixture
def make_hud(tmp_path, monkeypatch):
    made = []

    def make(ui=None, view="full"):
        cfg = {"view": view, "transition": False, "rgb_sync": True}
        if ui:
            cfg["ui"] = ui
        saved = {}
        monkeypatch.setattr(gamerhud, "load_settings", lambda: {**cfg, **saved})
        monkeypatch.setattr(gamerhud, "save_settings", lambda d: saved.update(d))
        monkeypatch.setattr(gamerhud.orgb, "board_color", lambda: None)
        np = FakeNP()
        monkeypatch.setattr(gamerhud, "WiredUI", lambda: WiredUI(now_playing=np, net=FakeNet()))
        bridge = hud_bridge.HudBridge(tmp_path / f"hud{len(made)}.sock")
        w = gamerhud.HUD({"seg": "Hack"}, bridge=bridge)
        w.resize(SIZE)
        w.np, w.saved = np, saved
        made.append((w, bridge))
        return w

    yield make
    for w, bridge in made:
        for t in (w.face_timer, w.anim_timer, w.data_timer, w.rgb_timer, w.wired_timer):
            t.stop()
        bridge.stop()
        w.hide()
        w.deleteLater()


def test_setting_ui(make_hud):
    assert make_hud().wired is not None  # padrão: wired
    eva = make_hud("eva")
    assert eva.wired is None and eva.anim_timer.isActive() and not eva.wired_timer.isActive()
    wired = make_hud("wired")
    assert wired.frame is None and not wired.anim_timer.isActive() and wired.wired_timer.isActive()
    wired.apply_ui("eva")
    assert wired.wired is None and wired.frame is not None
    wired.apply_ui("wired")
    assert wired.wired is not None and wired.frame is None


def dev(r):
    return QPoint(round(r.center().x() * S), round(r.center().y() * S))


def test_cliques_wired(make_hud, monkeypatch):
    w = make_hud()
    calls = []
    monkeypatch.setattr(w, "toggle_rgb_sync", lambda: calls.append("led"))
    monkeypatch.setattr(w.bridge, "send_cmd", lambda name, args=None: calls.append(name) or True)
    assert w.clickable(dev(ms.LED_BTN)) == "led"
    for target in ("led", "prev", "playpause", "next", "face"):
        w.wired_click(target)
    assert calls == ["led", "push_to_talk"] and w.np.calls == ["Previous", "PlayPause", "Next"]
    assert w.clickable(dev(ms.BTNS["next"])) == "next"
    monkeypatch.setattr(w.procs, "poll", lambda kind: [("game", 42.0, "x")])
    assert w.clickable(dev(ms.CARD["ram"])) == "card:ram"
    w.wired_click("card:ram")
    assert w.detail == "mem"
    w.wired_click("card:cpu")
    assert w.detail == "cpu"
    assert w.clickable(dev(DETAIL_RECT)) == "detail"
    img = w.grab()  # painel de detalhes pintado por cima do "cam 01"
    assert not img.isNull()
    w.wired_click("detail")
    assert w.detail is None and w.clickable(dev(DETAIL_RECT)) is None


def test_led_liga_rgb_sync_persistente(make_hud):
    w = make_hud()
    w.wired_click("led")
    assert w.saved["rgb_sync"] is False and w.wired.led_on is False
    w.wired_click("led")
    assert w.saved["rgb_sync"] is True and w.wired.snap.led_rgb is None  # OpenRGB fora → visual off


def test_ponte_chega_ao_tema_wired(make_hud):
    w = make_hud()
    w.on_face_state("speaking")
    w.on_face_mouth(0.7)
    w.on_face_subtitle("fala", "fala completa")
    w.on_bridge_mood(3)
    w.on_bridge_card({"level": "alta", "title": "Alerta"})
    snap = w.wired.snap
    assert (snap.magui_state, snap.mouth_level, snap.caption, snap.mood) == ("speaking", 0.7, "fala", 3)
    assert snap.events[-1].endswith("⚠ Alerta") and w.wired.mascot.state == "speaking"


def test_paint_por_regioes(make_hud):
    w = make_hud()
    w.show()
    w.wired_refresh()
    region = QRegion(QRect(0, 0, 200, 200)).united(QRegion(QRect(2000, 1300, 100, 100)))
    assert len(list(region)) == 2  # o paintEvent pinta cada retângulo, não o retângulo envolvente
    assert not w.grab().isNull()
    assert w.wired.hit(QPointF(-5, -5), SIZE, "full") is None
