"""Pintura do Konsole: offscreen sem erro, mapa de cores e tamanho em células."""

import select
import time

import konsole_term as kt
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from wired import konsole_view as kv

S = 2560 / 1920


def image():
    img = QImage(2560, 1440, QImage.Format.Format_RGB32)
    img.fill(QColor("#09080d"))
    return img


def colors_in(img, rect):
    r = QRectF(rect.x() * S, rect.y() * S, rect.width() * S, rect.height() * S).toAlignedRect()
    seen = set()
    for y in range(r.top() + 2, r.bottom() - 2, 3):
        for x in range(r.left() + 2, r.right() - 2, 3):
            seen.add(img.pixel(x, y) & 0xFFFFFF)
    return seen


def test_mapa_de_cores():
    assert kv.fg_hex("default") == kv.TEXT
    assert kv.fg_hex("red") == kv.RED
    assert kv.fg_hex("green") == kv.GREEN
    assert kv.fg_hex("magenta") == kv.LILAC
    assert kv.fg_hex("brightwhite") == kv.TEXT_HI
    assert kv.fg_hex("d77757") in kv.HUES          # laranja do Claude → paleta
    assert kv.fg_hex("00cd00") == kv.GREEN
    assert kv.fg_hex("808080") in kv.GREYS
    assert kv.fg_hex("zz") == kv.TEXT
    assert kv.bg_hex("default") is None
    bg = kv.bg_hex("red")
    assert bg and bg != kv.RED                       # fundo esmaecido
    assert kv.bg_hex("3d0100") is not None


def test_reverse_troca_texto_e_fundo():
    c = kt.Cell("x", "red", "default", reverse=True)
    assert kv.cell_colors(c) == (kv.BG, kv.RED)
    assert kv.cell_colors(kt.Cell("x")) == (kv.TEXT, None)


def test_cells_for():
    cols, rows = kv.cells_for(kv.EXPANDED_RECT, S)
    assert 55 <= cols <= 90 and 15 <= rows <= 30   # caixa do cam 01 (troca de lugar com ela)
    small = kv.cells_for(kv.CARD_RECT, S, expanded=False)
    assert small[0] < cols   # o card é mais estreito (e mais alto) que a caixa do cam 01
    wide = kv.cells_for(QRectF(0, 0, 1800, 900), S)
    assert wide[0] > cols
    assert kv.cells_for(QRectF(0, 0, 10, 10), S) == (2, 2)


def test_placeholders():
    v = kv.KonsoleView()
    assert v.placeholder() == "clique para abrir o Claude Code"
    v.error = "x"
    assert v.placeholder() == "x"


def test_hit_expandido():
    v = kv.KonsoleView()
    r = kv.EXPANDED_RECT
    assert v.hit_expanded(QPointF(r.left() - 5, r.top() + 50)) is None
    assert v.hit_expanded(r.center()) == "term"
    for b in v.button_rects().values():
        assert v.hit_expanded(b.center()) == "collapse"


def test_pinta_sem_sessao():
    v = kv.KonsoleView()
    img = image()
    p = QPainter(img)
    p.scale(S, S)
    v.paint_expanded(p, kv.EXPANDED_RECT, S)
    v.paint_compact(p, kv.CARD_RECT, S)
    p.end()
    assert len(colors_in(img, kv.EXPANDED_RECT)) > 3


@pytest.mark.skipif(not kt.HAVE_PYTE, reason="sem pyte")
def test_pinta_sessao_com_cores():
    cols, rows = kv.cells_for(kv.EXPANDED_RECT, S)
    s = kt.KonsoleSession(["bash", "-c", "printf '\\e[32mverde\\e[0m \\e[41m fundo \\e[0m\\n"
                                         "╭──╮\\n│ok│\\n╰──╯\\n日本 > '; sleep 5"], cols=cols, rows=rows)
    try:
        end = time.monotonic() + 5
        while "日本" not in "".join(s.lines()) and time.monotonic() < end:
            select.select([s.fd], [], [], 0.05)
            s.pump()
        v = kv.KonsoleView()
        v.session = s
        v.status = {"project": "~/magi", "branch": "main", "added": 3, "removed": 1}
        img = image()
        p = QPainter(img)
        p.scale(S, S)
        v.paint_expanded(p, kv.EXPANDED_RECT, S)
        v.paint_compact(p, kv.CARD_RECT, S)
        p.end()
        seen = colors_in(img, kv.term_rect())
        assert QColor(kv.CURSOR).rgb() & 0xFFFFFF in seen   # cursor em bloco fixo
        assert len(seen) > 5
        assert v.row_rects({0, 2}, kv.EXPANDED_RECT, S)[0].top() < kv.term_rect().top() + 5
        s.close(grace=0.3)
        assert v.placeholder() == "[sessão encerrada · clique para abrir outra]"
        img2 = image()
        p = QPainter(img2)
        p.scale(S, S)
        v.paint_compact(p, kv.CARD_RECT, S)
        v.paint_expanded(p, kv.EXPANDED_RECT, S)
        p.end()
    finally:
        s.close(grace=0.3)


def test_funcoes_do_modulo_usam_view():
    img = image()
    p = QPainter(img)
    p.scale(S, S)
    kv.paint_compact(p, kv.CARD_RECT, S)
    kv.paint_expanded(p, kv.EXPANDED_RECT, S)
    p.end()


# ------------------------------------------------------------------ HUD real (gamerhud)


class _NP:
    title = artist = album = year = None
    length, status, active = 0.0, None, False

    def position(self, now=None):
        return 0.0

    def __getattr__(self, name):   # tick, play_pause…: nada
        return lambda *a, **k: None


class _Net:
    down = up = 0.0
    down_series = ()

    def poll(self, now=None):
        pass


@pytest.fixture
def hud(tmp_path, monkeypatch):
    import gamerhud
    import hud_bridge
    from wired.integration import WiredUI

    cfg = {"view": "full", "transition": False, "ui": "wired",
           "konsole_cmd": ["bash", "-c", "printf 'pronto\\n'; exec cat"], "konsole_cwd": str(tmp_path),
           "konsole_tmux": False}
    monkeypatch.setattr(gamerhud, "load_settings", lambda: dict(cfg))
    monkeypatch.setattr(gamerhud, "save_settings", lambda d: None)
    monkeypatch.setattr(gamerhud.orgb, "board_color", lambda: None)
    monkeypatch.setattr(gamerhud, "WiredUI", lambda: WiredUI(now_playing=_NP(), net=_Net()))
    bridge = hud_bridge.HudBridge(tmp_path / "hud.sock")
    w = gamerhud.HUD({"seg": "Hack"}, bridge=bridge)
    w.resize(2560, 1440)
    yield w
    w.konsole_stop()
    for t in (w.face_timer, w.anim_timer, w.data_timer, w.rgb_timer, w.wired_timer, w.kon_timer):
        t.stop()
    bridge.stop()
    w.hide()
    w.deleteLater()
    kv.VIEW.session = None
    kv.VIEW.error = None


def _pump(w, pred, timeout=5.0):
    from PySide6.QtWidgets import QApplication

    end = time.monotonic() + timeout
    while time.monotonic() < end and not pred():
        if w.kon is not None and w.kon.fd is not None:
            select.select([w.kon.fd], [], [], 0.05)
        w.konsole_read()
        QApplication.processEvents()
    return pred()


@pytest.mark.skipif(not kt.HAVE_PYTE, reason="sem pyte")
def test_hud_expande_digita_e_recolhe(hud):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent, QMouseEvent

    assert hud.kon is None and not hud.kon_open   # sob demanda: nada sobe com o HUD
    hud.wired_click("konsole")
    assert hud.kon_open and hud.kon is not None and hud.kon.alive
    assert (hud.kon.cols, hud.kon.rows) == kv.cells_for(kv.EXPANDED_RECT, hud.width() / 1920)
    assert _pump(hud, lambda: "pronto" in "".join(hud.kon.lines()))
    none = Qt.KeyboardModifier.NoModifier
    for ch in "oi":
        hud.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, ord(ch.upper()), none, ch))
    hud.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, none, "\r"))
    assert _pump(hud, lambda: "\n".join(hud.kon.lines()).count("oi") >= 2)
    hud.konsole_flush()
    assert not hud.grab().isNull()   # pinta o painel com o Konsole por cima
    assert not hud.focusNextPrevChild(True)   # Tab fica no terminal
    # clique fora: recolhe, a sessão segue viva
    pos = QPointF(10, 10)
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    hud.mousePressEvent(ev)
    assert not hud.kon_open and hud.kon.alive
    hud.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, ord("X"), Qt.KeyboardModifier.NoModifier, "x"))
    hud.wired_click("konsole")   # reabre a mesma sessão
    assert hud.kon_open
    pid = hud.kon.pid
    hud.view = "idle"            # sair do painel recolhe
    assert not hud.kon_open
    hud.close()
    assert not hud.kon.alive
    import os
    assert not os.path.exists(f"/proc/{pid}")


@pytest.mark.skipif(not kt.HAVE_PYTE, reason="sem pyte")
def test_hud_expandido_troca_com_cam01(hud):
    """Expandido = caixa do cam 01; a câmera vai para o slot do card; clicar nela recolhe."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    from wired import main_screen as ms

    def click(pt):
        s = hud.width() / 1920
        pos = QPointF(pt.x() * s, pt.y() * s)
        hud.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, Qt.MouseButton.LeftButton,
                                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))

    main = hud.wired.main
    hud.wired_click("konsole")
    assert hud.kon_open and main.kon_swap
    assert not hud.grab().isNull()
    click(kv.EXPANDED_RECT.center())          # terminal: mantém
    assert hud.kon_open and main.kon_swap
    click(ms.CAM_SWAPPED.center())            # câmera pequena: recolhe e destroca
    assert not hud.kon_open and not main.kon_swap and hud.kon.alive
    hud.wired_click("konsole")
    b = kv.VIEW.button_rects()["min"]
    click(b.center())                         # "–": recolhe
    assert not hud.kon_open and not main.kon_swap
