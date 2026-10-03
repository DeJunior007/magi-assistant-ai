"""Integração rosto + ponte no gamerhud (1.16), offscreen, sem abrir o HUD de verdade."""

from __future__ import annotations

import time

import gamerhud
import hud_bridge
import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication


@pytest.fixture
def hud(tmp_path, monkeypatch):
    monkeypatch.setattr(gamerhud, "load_settings", lambda: {"view": "full", "transition": False, "ui": "eva"})
    bridge = hud_bridge.HudBridge(tmp_path / "hud.sock")  # ninguém escuta: só tenta reconectar
    w = gamerhud.HUD({"seg": "Hack"}, bridge=bridge)
    w.resize(2560, 1440)
    yield w
    for t in (w.face_timer, w.anim_timer, w.data_timer, w.rgb_timer):
        t.stop()
    bridge.stop()
    w.hide()
    w.deleteLater()


@pytest.mark.parametrize("view", ["idle", "full"])
def test_monta_com_rosto(hud, view):
    hud.view = view
    hud.render_caches()
    r = hud.r_face()
    assert hud.rect().contains(r.toAlignedRect())
    img = hud.grab(r.toAlignedRect()).toImage()
    bg = hud.frame.copy(r.toAlignedRect()).toImage()
    assert img != bg  # o rosto é desenhado por cima do cache, não dentro dele
    if view == "idle":
        assert r.left() >= 1280 and r.height() >= 200  # metade direita, com legenda
    else:
        assert r.height() < 200 and r.bottom() < hud.R(0, 212, 1, 1).top()  # no cabeçalho


def test_sinais_da_ponte_chegam_ao_rosto(hud):
    b = hud.bridge
    b.feed_line('{"t":"state","v":"speaking"}')
    b.feed_line('{"t":"mouth","v":0.8}')
    b.feed_line('{"t":"subtitle","text":"Oi!","full":"Oi! Tudo bem?"}')
    b.feed_line('{"t":"mood","v":3}')
    b.feed_line('{"t":"vote","verdict":"pending","label":"Fechar o jogo"}')
    assert hud.face.state == "speaking"
    assert hud.face.mouth_level == pytest.approx(0.8)
    assert hud.face.subtitle == "Oi!"
    assert hud.magui_mood == 3
    assert hud.magui_vote == ("pending", "Fechar o jogo")
    b.connectedChanged.emit(False)  # núcleo caiu: a Magui dorme
    assert hud.face.state == "sleeping" and hud.face.subtitle == ""


def test_detalhe_pela_ponte_abre_e_fecha(hud, monkeypatch):
    monkeypatch.setattr(hud.procs, "poll", lambda kind: [])
    hud.view = "idle"
    hud.render_caches()
    hud.bridge.feed_line('{"t":"detail","v":"memory"}')
    assert hud.detail == "mem" and hud.view == "full"
    hud.bridge.feed_line('{"t":"detail","v":"none"}')
    assert hud.detail is None and hud.view == "idle"  # volta pra view de antes


@pytest.mark.parametrize("view", ["idle", "full"])
def test_redesenho_so_na_regiao_do_rosto(hud, view, monkeypatch):
    hud.view = view
    for t in (hud.anim_timer, hud.data_timer, hud.rgb_timer):
        t.stop()
    hud.show()
    hud.render_caches()
    QApplication.processEvents()
    calls = []
    monkeypatch.setattr(hud, "update", lambda *a: calls.append(a))
    hud.bridge.feed_line('{"t":"state","v":"speaking"}')
    hud.bridge.feed_line('{"t":"mouth","v":0.9}')
    end = time.monotonic() + 0.5  # o tick limita a 30 fps: o redesenho pode vir no próximo prazo
    while not calls and time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.005)
    assert calls, "trocar de expressão pede redesenho"
    face = QRegion(hud.r_face().toAlignedRect())
    for args in calls:
        assert len(args) == 1 and isinstance(args[0], QRect)  # nunca a tela inteira
        assert face.subtracted(QRegion(args[0])) != face
        assert QRegion(args[0]).subtracted(face).isEmpty()


def test_clique_no_rosto_pede_push_to_talk(hud, monkeypatch):
    sent = []
    monkeypatch.setattr(hud.bridge, "send_cmd", lambda name, args=None: sent.append(name))
    for view in ("idle", "full"):
        hud.view = view
        assert hud.clickable(hud.r_face().center()) == "face"

    class Click:
        def button(self):
            return gamerhud.Qt.LeftButton

        def position(self):
            return hud.r_face().center()

    hud.mousePressEvent(Click())
    assert sent == ["push_to_talk"]
