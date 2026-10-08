"""LM1.5: LearningScreen offscreen — pinta em QImage sem erro; ``group_key`` muda só quando o
dado do grupo muda; END SESSION no ``hit_test``; ``WiredUI.screen("learning")``."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MAGI_PORTRAIT_DIR", "/nonexistent/magi-portrait")
os.environ.setdefault("MAGI_NO_CLAUDE_STATS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from wired.learning_screen import LearningInfo, LearningScreen  # noqa: E402
from wired.main_screen import Snapshot  # noqa: E402

SIZE = QSize(2560, 1440)
NOW = datetime(2026, 10, 7, 17, 42, 10)
GROUPS = {"header", "topic", "mascot", "condessa", "system", "history", "input", "obs", "footer",
          "overlay"}


def snap(**kw) -> Snapshot:
    base = dict(cpu=14.0, gpu=3.0, ram=41.0, net_down=1.2e5, net_up=3e3, magui_state="sleeping")
    base.update(kw)
    return Snapshot(**base)


def render(scr, sn, size=SIZE, region=None, now=NOW) -> QImage:
    img = QImage(size, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    scr.paint(p, size, sn, now, mono=0.0, region=region)
    p.end()
    return img


def test_pinta_sem_erro_e_nao_fica_vazia():
    scr = LearningScreen(info=LearningInfo(log="[19:30:44] english session active: 01"))
    img = render(scr, snap())
    assert not img.isNull()
    colors = {img.pixel(x, y) for x in range(0, 2560, 37) for y in range(0, 1440, 37)}
    assert len(colors) > 5
    # região parcial também pinta sem erro
    render(scr, snap(), region=QRect(0, 0, 400, 300))


def test_grupos_existem():
    scr = LearningScreen()
    assert set(scr.groups()) == GROUPS
    for name, rects in scr.groups().items():
        assert rects and all(r.width() > 0 and r.height() > 0 for r in rects), name


def test_magi_recolhido_pinta():
    render(LearningScreen(info=LearningInfo(magi_open=False, connected=False)), snap())


def test_group_key_so_muda_com_o_dado_do_grupo():
    scr = LearningScreen()
    base = snap()
    keys = {g: scr.group_key(g, base, NOW) for g in GROUPS}

    def changed(sn=base, now=NOW) -> set[str]:
        return {g for g in GROUPS if scr.group_key(g, sn, now) != keys[g]}

    assert changed() == set()
    assert changed(now=NOW.replace(second=55)) == set()  # mesmo minuto
    assert changed(now=NOW.replace(minute=43)) == {"header"}
    assert changed(snap(magui_state="speaking")) == {"mascot", "condessa"}
    assert changed(snap(cpu=80.0)) == {"system"}
    assert changed(snap(caption="algo")) == set()
    scr.info.log = "[19:30:44] english session active: 01"
    assert changed() == {"footer"}
    scr.info.log = None
    scr.info.action_running = True
    assert changed() == {"condessa"}
    scr.info.action_running = False
    scr.info.magi_open = False
    assert changed() == {"system"}


def test_dirty_regions_so_do_grupo():
    scr = LearningScreen()
    render(scr, snap())
    assert scr.dirty_regions(snap(), NOW, SIZE) == []
    rects = scr.dirty_regions(snap(magui_state="speaking"), NOW, SIZE)
    assert rects and all(not r.contains(QRect(0, 0, 2560, 1440)) for r in rects)


def test_end_session_no_hit_test():
    scr = LearningScreen()
    render(scr, snap())
    b = scr.L.end_btn
    s = 2560 / 1920
    c = QPoint(round((b.x + b.w / 2) * s), round((b.y + b.h / 2) * s))
    assert scr.hit_test(c, SIZE) == "learning"
    assert scr.hit_test(QPoint(5, 1400), SIZE) is None


def test_wired_ui_screen_learning(tmp_path, monkeypatch):
    from wired import reactions
    from wired.integration import WiredUI

    for name in ("GENRES_FILE", "CLEANUP_FILE", "TASTE_FILE", "SEEN_FILE", "FAVORITES_FILE", "SPEECH_FILE"):
        monkeypatch.setattr(reactions, name, tmp_path / "reacoes" / name.lower())  # nada real

    w = WiredUI()
    scr = w.screen("learning")
    assert isinstance(scr, LearningScreen)
    assert scr.mascot is w.mascot
    assert w.mascot.layout == "main"
    assert w.screen("full") is w.main and w.screen("idle") is w.standby
    assert w.hit(QPoint(10, 10), SIZE, "learning") is None  # sem mouse no LM1.5


@pytest.mark.parametrize("size", [QSize(1920, 1080), QSize(2560, 1440)])
def test_resolucoes(size):
    render(LearningScreen(), snap(), size=size)
