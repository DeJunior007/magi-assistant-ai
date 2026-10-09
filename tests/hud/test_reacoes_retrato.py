"""R2.A: retrato clicável e hover (spec §6 A, D1 = a), com eventos Qt sintéticos."""

from __future__ import annotations

import gamerhud
import hud_bridge
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from wired.integration import WiredUI
from wired.reacoes import catalogo, det_entrada

SIZE = QSize(2560, 1440)


class FakeNP:  # player parado: nada do MPRIS real
    title = artist = album = year = status = None
    length, active = 0.0, False

    def position(self, now=None):
        return 0.0

    def cover_pixmap(self):
        return None

    def tick(self, now=None):
        pass


class FakeNet:
    down = up = 0.0
    down_series = ()

    def poll(self, now=None):
        pass


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def hud(tmp_path, monkeypatch):
    cfg = {"view": "full", "transition": False, "ui": "wired"}
    monkeypatch.setattr(gamerhud, "load_settings", lambda: cfg)
    monkeypatch.setattr(gamerhud, "save_settings", lambda d: None)
    monkeypatch.setattr(gamerhud.orgb, "board_color", lambda: None)
    monkeypatch.setattr(gamerhud, "WiredUI", lambda: WiredUI(now_playing=FakeNP(), net=FakeNet()))
    bridge = hud_bridge.HudBridge(tmp_path / "hud.sock")
    w = gamerhud.HUD({"seg": "Hack"}, bridge=bridge)
    w.resize(SIZE)
    w.sent = []
    monkeypatch.setattr(w.bridge, "send_cmd", lambda name, args=None: w.sent.append(name) or True)
    w.mono = Relogio()
    yield w
    for t in (w.face_timer, w.anim_timer, w.data_timer, w.rgb_timer, w.wired_timer, w.face_ptt_timer):
        t.stop()
    bridge.stop()
    w.hide()
    w.deleteLater()


def _rosto(w, fy=0.5):
    r, _ = w.face_rect()
    return QPoint(round(r.center().x()), round(r.top() + r.height() * fy))


def _gestos(w):
    return [g for _, g in w.wired.reactor.ctx.get("gestos") or ()]


def _mover(w, pos, botao=Qt.MouseButton.NoButton):
    p = QPointF(pos)
    w.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, p, p, Qt.MouseButton.NoButton, botao,
                                 Qt.KeyboardModifier.NoModifier))


def test_tracking_e_alvo(hud):
    assert hud.hasMouseTracking()
    assert hud.clickable(_rosto(hud)) == "face"


def test_clique_simples_ainda_e_push_to_talk(hud):
    QTest.mouseClick(hud, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _rosto(hud))
    assert hud.sent == [] and hud.face_ptt_timer.isActive()  # espera o 2º clique (D1 = a)
    assert hud.face_ptt_timer.interval() == 250
    hud.face_ptt_timer.timeout.emit()  # passaram 250 ms sem 2º clique
    assert hud.sent == ["push_to_talk"]
    assert [a for _, a in hud.wired.reactor.ctx["cliques"]] == ["face"]
    assert _gestos(hud) == []


def test_clique_duplo_e_69_sem_ptt(hud):
    pos = _rosto(hud)
    QTest.mouseClick(hud, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    hud.mono.t += 0.15
    QTest.mouseClick(hud, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert not hud.face_ptt_timer.isActive() and hud.sent == []
    assert _gestos(hud) == ["dbl"]
    ctx = hud.wired.reactor.ctx
    assert [d.chave for d in det_entrada._retrato(ctx)] == ["clique_duplo"]


def test_segurar_e_70_sem_ptt(hud):
    pos = _rosto(hud)
    QTest.mousePress(hud, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    hud.mono.t += 0.9
    QTest.mouseRelease(hud, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert not hud.face_ptt_timer.isActive() and hud.sent == []
    assert _gestos(hud) == ["long"]


def test_arrasto_na_metade_de_cima_e_67_sem_ptt(hud):
    pos = _rosto(hud, 0.25)
    _, s = hud.face_rect()
    QTest.mousePress(hud, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    _mover(hud, pos + QPoint(round(20 * s), 0), Qt.MouseButton.LeftButton)
    assert "arrasto" not in _gestos(hud)
    _mover(hud, pos + QPoint(round(50 * s), 0), Qt.MouseButton.LeftButton)
    _mover(hud, pos + QPoint(round(80 * s), 0), Qt.MouseButton.LeftButton)
    QTest.mouseRelease(hud, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert _gestos(hud).count("arrasto") == 1
    assert not hud.face_ptt_timer.isActive() and hud.sent == []


def test_arrasto_na_metade_de_baixo_vira_clique(hud):
    pos = _rosto(hud, 0.8)
    _, s = hud.face_rect()
    QTest.mousePress(hud, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    _mover(hud, pos + QPoint(round(60 * s), 0), Qt.MouseButton.LeftButton)
    QTest.mouseRelease(hud, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    assert "arrasto" not in _gestos(hud) and hud.face_ptt_timer.isActive()


def test_hover_entra_parado_e_sai(hud):
    fora = QPoint(5, 5)
    _mover(hud, fora)
    assert _gestos(hud) == []
    _mover(hud, _rosto(hud))
    ctx = hud.wired.reactor.ctx
    assert _gestos(hud) == ["in"] and ctx["rosto_parado"] == 1000.0
    hud.mono.t += 1.0
    _mover(hud, _rosto(hud) + QPoint(3, 0))  # mexeu: o "parado" recomeça
    assert ctx["rosto_parado"] == 1001.0 and _gestos(hud) == ["in"]
    ctx["agora"] = 1002.0
    assert [d.chave for d in det_entrada._retrato(ctx)] == ["hover"]
    ctx["agora"] = 1004.5
    assert [d.chave for d in det_entrada._retrato(ctx)] == ["flagrada"]
    ctx["agora"] = 1008.0
    assert det_entrada._retrato(ctx) == []
    ctx["agora"] = 1011.5
    assert [d.chave for d in det_entrada._retrato(ctx)] == ["encarando"]
    ctx["agora"] = 1030.0
    assert det_entrada._retrato(ctx) == []
    hud.leaveEvent(QEvent(QEvent.Type.Leave))
    assert ctx["rosto_parado"] is None


def test_hover_fora_do_wired_e_learning_nao_conta(hud):
    hud.view = "learning"
    _mover(hud, _rosto(hud))
    assert _gestos(hud) == []


# ------------------------------------------------------------------ detector puro


def test_parado_direto_10s_so_encarando():
    ctx = {"rosto_parado": 0.0, "agora": 12.0}
    assert [d.chave for d in det_entrada._retrato(ctx)] == ["encarando"]
    assert det_entrada._retrato(ctx) == []
    ctx.update(rosto_parado=20.0, agora=23.5)  # nova parada
    assert [d.chave for d in det_entrada._retrato(ctx)] == ["flagrada"]


def test_gestos_viram_disparos_uma_vez():
    ctx = {"gestos": ((1.0, "in"), (2.0, "dbl"), (3.0, "long"), (4.0, "arrasto"), (5.0, "in"))}
    esperado = ["hover", "clique_duplo", "segurar_clique", "carinho"]
    assert [d.chave for d in det_entrada._retrato(ctx)] == esperado
    assert det_entrada._retrato(ctx) == []


def test_64_vale_no_retrato():
    ctx = {"cliques": ((1.0, "face"), (2.0, "led"), (3.0, "face"))}
    assert [d.chave for d in det_entrada.detectar(None, None, ctx)] == ["led"]
    ctx = {"cliques": ((1.0, "face"), (2.0, "face"))}
    assert det_entrada.detectar(None, None, ctx) == []  # sem fone: o 66 é só do LED


def test_condicionadas_do_sinal_a_ativas():
    for chave in ("encarando", "hover", "carinho", "clique_duplo", "segurar_clique", "flagrada"):
        assert chave in catalogo.ATIVAS and catalogo.DEFS[chave].sinal is None
