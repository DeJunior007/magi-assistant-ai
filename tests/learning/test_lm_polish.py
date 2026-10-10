"""Polimento do Learning Mode: balão em carregamento.

- Repintar só um pedaço do histórico (região parcial, como o ``paintEvent`` faz com cada
  retângulo da região suja) não pode desenhar o histórico por cima do menu/balão fora dessa
  região (bug: o ``setClipRect`` do histórico trocava o clip da região → balão "translúcido").
- A barra de carregamento avança com o tempo (~5 quadros/s), agenda o próximo quadro por
  ``frame_deadline`` e só pede a repintura da linha animada.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GAMERHUD_NO_WALLPAPER"] = "1"
os.environ.setdefault("MAGI_PORTRAIT_DIR", "/nonexistent/magi-portrait")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from PySide6.QtCore import QRect, QSize  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from wired import learning_overlay as ov  # noqa: E402
from wired.learning_screen import LearningScreen, ModelProvider  # noqa: E402
from wired.learning_text import ActionKind, Selection  # noqa: E402
from wired.main_screen import Snapshot  # noqa: E402

SZ = QSize(2560, 1440)
S = 2560 / 1920
NOW = datetime(2026, 10, 9, 17, 0)
SNAP = Snapshot(magui_state="sleeping")
LONG = ("we talked about the repository, the deploy pipeline and the authentication flow that "
        "keeps breaking every time I push a new build to the server")


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class Silent:  # o lm_result não chega: o balão fica em LOADING
    def submit(self, action, text):
        return None


def _loading_screen() -> tuple[LearningScreen, Clock]:
    scr = LearningScreen()
    clk = Clock()
    scr.overlay.clock = clk
    scr.overlay.provider = ModelProvider(scr, Silent())
    scr.info.feed({"t": "lm_mode", "on": True, "session_id": "LS-0001"})
    for i in range(1, 9):
        txt = "yesterday I make a new authentication system" if i == 7 else f"message {i}: {LONG}"
        scr.info.feed({"t": "lm_msg", "id": i, "author": "you" if i % 2 else "condessa", "text": txt})
    box = next(b for b in scr.history_boxes() if b.message_id == 7)
    pt = (box.rect.x + 4, box.rect.y + box.rect.h / 2)
    scr.mouse("double", pt)
    scr.mouse("release", pt)
    menu = scr._overlay_geometry()[0]
    r0 = ov.item_rect(menu, 0)
    scr.mouse("press", (r0.x + 20, r0.y + r0.h / 2))
    assert scr.overlay.phase == ov.LOADING
    return scr, clk


def _paint(scr, img, region=None):
    p = QPainter(img)
    scr.paint(p, SZ, SNAP, NOW, mono=0.0, region=region)
    p.end()


def _dev(r):
    return QRect(round(r.x * S) + 2, round(r.y * S) + 2, round(r.w * S) - 4, round(r.h * S) - 4)


def test_repintura_parcial_do_historico_nao_cobre_menu_nem_balao():
    scr, _ = _loading_screen()
    img = QImage(SZ, QImage.Format.Format_RGB32)
    img.fill(0)
    _paint(scr, img)
    menu, bubble, _ = scr._overlay_geometry()
    before = [img.copy(_dev(r)) for r in (menu, bubble)]
    h = scr.L.history  # faixa no pé do histórico, longe do menu e do balão
    band = QRect(round(h.x * S), round((h.bottom - 30) * S), round(h.w * S), round(20 * S))
    assert not band.intersects(_dev(menu)) and not band.intersects(_dev(bubble))
    _paint(scr, img, band)
    after = [img.copy(_dev(r)) for r in (menu, bubble)]
    assert after[0] == before[0] and after[1] == before[1]


def test_quadro_da_barra_avanca_com_o_tempo():
    clk = Clock()
    o = ov.Overlay(provider=ov.BridgeProvider(lambda t, f: True), clock=clk)
    assert o.frame() == 0 and o.frame_deadline() is None
    o.open(Selection(message_id=1, start=0, end=6, text="I make"), "you", "I make a thing")
    o.choose(ActionKind.IMPROVE)
    step = 1 / ov.ANIM_FPS
    assert 4 <= ov.ANIM_FPS <= 6
    assert o.frame() == 0 and o.frame_deadline() == clk.t + step
    clk.t += step * 1.5
    assert o.frame() == 1 and abs(o.frame_deadline() - (100.0 + 2 * step)) < 1e-9
    assert o.deadline() == 100.0 + ov.UI_TIMEOUT_S  # o timeout de 12 s continua o mesmo
    assert [ln.style for ln in o.lines()][-1] == "loading"
    o.on_result({"id": o.action_id, "kind": "improve", "ok": True, "data": dict(ov.MOCK_IMPROVE)})
    assert o.frame() == 0 and o.frame_deadline() is None


def test_tela_repinta_so_a_linha_animada_quando_o_quadro_muda():
    scr, clk = _loading_screen()
    img = QImage(SZ, QImage.Format.Format_RGB32)
    img.fill(0)
    _paint(scr, img)
    assert scr.overlay_anim_rects(SZ) == []  # quadro já pintado
    first = img.copy()
    clk.t += 1 / ov.ANIM_FPS
    rects = scr.overlay_anim_rects(SZ)
    _, bubble, _ = scr._overlay_geometry()
    bdev = QRect(round(bubble.x * S) - 2, round(bubble.y * S) - 2, round(bubble.w * S) + 4,
                 round(bubble.h * S) + 4)
    assert len(rects) == 1 and bdev.contains(rects[0]) and rects[0].height() < bdev.height() / 2
    assert scr.dirty_regions(SNAP, NOW, SZ) == []  # o resto da tela não fica sujo
    _paint(scr, img, rects[0])
    assert img.copy(rects[0]) != first.copy(rects[0])  # o pulso andou
    assert scr.overlay_anim_rects(SZ) == []
    scr.overlay.close()
    assert scr.overlay_anim_rects(SZ) == []
