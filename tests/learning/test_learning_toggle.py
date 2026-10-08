"""LM1.7 (CA-18b): botão LEARNING e troca de tela.

- ``learning_toggle`` (puro, sem Qt): ``lm_mode`` confirmado leva ``full``/``idle`` → ``learning`` e
  volta para a view guardada; Meta+M durante o modo só muda o retorno; reenvio não duplica.
- Telas: ``[ LEARNING // 学習 ]`` no painel e na espera com alvo ``"learning"``; sem o botão o
  painel e a espera pintam igual (a diferença fica só no retângulo do botão) e os cliques antigos
  (LED, player, cards, rosto) seguem iguais.
- ``gamerhud`` (offscreen): clique → ``send_lm("lm_mode")``; a tela só troca na confirmação (botão
  ou voz); com o núcleo fora nada muda.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GAMERHUD_NO_WALLPAPER"] = "1"  # nunca toca no papel de parede real
os.environ.setdefault("MAGI_PORTRAIT_DIR", "/nonexistent/magi-portrait")
os.environ.setdefault("MAGI_NO_CLAUDE_STATS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from wired.integration import learning_toggle  # noqa: E402

ON = {"t": "lm_mode", "on": True}
OFF = {"t": "lm_mode", "on": False}


def meta_m(view: str) -> dict:
    return {"t": "view", "view": view}


# ------------------------------------------------------------------ learning_toggle (puro)


@pytest.mark.parametrize("origem", ["full", "idle"])
def test_entra_e_volta_para_a_view_guardada(origem):
    view, ret = learning_toggle(origem, None, ON)
    assert (view, ret) == ("learning", origem)
    assert learning_toggle(view, ret, OFF) == (origem, None)


def test_lm_mode_on_repetido_nao_perde_o_retorno():
    # reenvio do núcleo na reconexão / learning.start com o modo ligado: só confirma
    assert learning_toggle("learning", "idle", ON) == ("learning", "idle")


def test_lm_mode_off_fora_do_modo_nao_muda_a_view():
    assert learning_toggle("full", None, OFF) == ("full", None)
    assert learning_toggle("idle", "full", OFF) == ("idle", None)


def test_meta_m_durante_o_modo_so_muda_o_retorno():
    view, ret = learning_toggle("full", None, ON)
    view, ret = learning_toggle(view, ret, meta_m("idle"))
    assert (view, ret) == ("learning", "idle")
    view, ret = learning_toggle(view, ret, meta_m("full"))
    assert (view, ret) == ("learning", "full")
    assert learning_toggle(view, ret, OFF) == ("full", None)


def test_meta_m_fora_do_modo_troca_como_antes():
    assert learning_toggle("full", None, meta_m("idle")) == ("idle", None)
    assert learning_toggle("idle", None, meta_m("full")) == ("full", None)
    assert learning_toggle("full", None, meta_m("full")) == ("full", None)


def test_retorno_invalido_ou_ausente_volta_ao_painel():
    assert learning_toggle("learning", None, OFF) == ("full", None)
    assert learning_toggle("learning", "learning", OFF) == ("full", None)
    # settings.json com valor estranho durante o modo não estraga o retorno guardado
    assert learning_toggle("learning", "idle", meta_m("learning")) == ("learning", "idle")


def test_mensagem_estranha_nao_muda_nada():
    assert learning_toggle("idle", None, {"t": "lm_msg", "text": "hi"}) == ("idle", None)
    assert learning_toggle("learning", "idle", {}) == ("learning", "idle")


# ------------------------------------------------------------------ telas (offscreen)

from PySide6.QtCore import QPoint, QPointF, QSize  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from wired import main_screen, standby_screen  # noqa: E402
from wired.integration import WiredUI  # noqa: E402

BASE = QSize(1920, 1080)
NOW = datetime(2026, 10, 7, 17, 42, 10)


def center(r) -> QPoint:
    c = r.center()
    return QPoint(round(c.x()), round(c.y()))


def render(scr, size=BASE) -> QImage:
    """Camada estática (onde o botão vive): determinística, sem relógio nem animação."""
    img = QImage(size, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    scr.draw_static(p, 1.0)
    p.end()
    return img


def diff_box(a: QImage, b: QImage, ignore=None) -> tuple[int, int, int, int] | None:
    """Caixa dos pixels diferentes; ``ignore``: retângulo com ruído próprio (cenário "cam 01")."""
    xs, ys = [], []
    for y in range(a.height()):
        for x in range(a.width()):
            if ignore is not None and ignore.contains(QPointF(x, y)):
                continue
            if a.pixel(x, y) != b.pixel(x, y):
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


@pytest.mark.parametrize("view", ["full", "idle"])
def test_botao_learning_no_hit_test(view):
    w = WiredUI()
    scr = w.screen(view)
    r = main_screen.LEARN_BTN if view == "full" else scr.learn_btn
    assert w.hit(center(r), BASE, view) == "learning"
    # escala do monitor (2560×1440): o alvo acompanha
    big = QSize(2560, 1440)
    s = scr.scale(big)
    c = r.center()
    assert w.hit(QPoint(round(c.x() * s), round(c.y() * s)), big, view) == "learning"


def test_botao_learning_nao_cruza_fala_nem_player():
    w = WiredUI()
    ms = main_screen
    # painel: no vão logo abaixo do card da Condessa, sem encostar em nenhum card
    assert ms.LEARN_BTN.top() >= ms.TALK.bottom() and ms.LEARN_BTN.left() >= ms.TALK.left()
    for card in (ms.MID_TOP, ms.HIST, ms.SPEC):
        assert not ms.LEARN_BTN.intersects(card)
    sb = w.screen("idle")
    assert not sb.learn_btn.intersects(sb.talk)
    assert sb.learn_btn.bottom() <= sb.y_rule2


def test_cliques_antigos_seguem_iguais():
    w = WiredUI()
    ms = main_screen
    assert w.hit(center(ms.LED_BTN), BASE, "full") == "led"
    for k, r in ms.BTNS.items():
        assert w.hit(center(r), BASE, "full") == k
    for k, r in zip(("card:cpu", "card:gpu", "card:ram"), ms.UNITS, strict=True):
        assert w.hit(center(r), BASE, "full") == k
    assert w.hit(center(ms.MASCOT_MAIN), BASE, "full") == "face"
    sb = w.screen("idle")
    assert w.hit(center(sb.MASCOT_RECT), BASE, "idle") == "face"
    assert w.hit(center(sb.talk), BASE, "idle") is None


@pytest.mark.parametrize("view", ["full", "idle"])
def test_sem_o_botao_a_tela_pinta_igual(view, monkeypatch):
    """O botão é a única diferença: sem ele (desenho trocado por nada) o resto é igual pixel a
    pixel; as diferenças ficam todas dentro do retângulo do botão."""
    mod = main_screen if view == "full" else standby_screen
    com = render(WiredUI().screen(view))
    monkeypatch.setattr(mod, "draw_learning_btn", lambda *a, **k: 0.0)
    sem = render(WiredUI().screen(view))
    # o cenário do "cam 01" varia entre duas pinturas mesmo sem mudança nenhuma: fica de fora
    box = diff_box(com, sem, main_screen.SCENE.adjusted(-1, -1, 1, 1) if view == "full" else None)
    assert box is not None, "o botão não foi desenhado"
    scr = WiredUI().screen(view)
    r = main_screen.LEARN_BTN if view == "full" else scr.learn_btn
    x0, y0, x1, y1 = box
    folga = r.adjusted(-1, -1, 1, 1)
    assert folga.contains(QPointF(x0, y0)) and folga.contains(QPointF(x1, y1)), (box, r)


# ------------------------------------------------------------------ gamerhud (offscreen)


@pytest.fixture
def hud(tmp_path, monkeypatch):
    import gamerhud
    import hud_bridge
    from wired import reactions

    for name in ("GENRES_FILE", "CLEANUP_FILE", "TASTE_FILE", "SEEN_FILE", "FAVORITES_FILE", "SPEECH_FILE"):
        monkeypatch.setattr(reactions, name, tmp_path / "reacoes" / name.lower())
    cfg = {"view": "full", "transition": False, "ui": "wired", "rgb_sync": False}
    monkeypatch.setattr(gamerhud, "load_settings", lambda: dict(cfg))
    monkeypatch.setattr(gamerhud, "save_settings", lambda d: None)
    monkeypatch.setattr(gamerhud.orgb, "board_color", lambda: None)
    bridge = hud_bridge.HudBridge(tmp_path / "hud.sock")
    w = gamerhud.HUD({"seg": "Hack"}, bridge=bridge)
    w.resize(1920, 1080)
    w.test_cfg = cfg
    yield w
    for name in ("face_timer", "anim_timer", "data_timer", "rgb_timer", "wired_timer", "caption_timer"):
        t = getattr(w, name, None)
        if t is not None:
            t.stop()
    bridge.stop()
    w.hide()
    w.deleteLater()


def meta_m_hud(hud, monkeypatch, view):
    """Meta+M grava ``view`` no settings.json; o HUD lê no próximo ``poll_rgb``."""
    import gamerhud

    hud.test_cfg["view"] = view
    monkeypatch.setattr(gamerhud, "settings_mtime", lambda: hud.settings_mtime + 1.0)
    hud.poll_rgb()


@pytest.mark.parametrize("origem", ["full", "idle"])
def test_clique_pede_e_a_confirmacao_troca(hud, monkeypatch, origem):
    sent = []
    monkeypatch.setattr(hud.bridge, "send_lm", lambda t, f=None: sent.append((t, f)) or True)
    hud.view = origem
    hud.wired_click("learning")
    assert sent == [("lm_mode", {"on": True})]
    assert hud.view == origem   # só troca na confirmação do núcleo
    hud.on_bridge_learning(ON)
    assert hud.view == "learning" and hud.lm_return == origem
    hud.wired_click("learning")   # END SESSION
    assert sent[-1] == ("lm_mode", {"on": False})
    assert hud.view == "learning"
    hud.on_bridge_learning(OFF)
    assert hud.view == origem and hud.lm_return is None


def test_clique_real_no_botao_do_painel(hud, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QMouseEvent

    sent = []
    monkeypatch.setattr(hud.bridge, "send_lm", lambda t, f=None: sent.append((t, f)) or True)
    c = main_screen.LEARN_BTN.center()
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, c, c, Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    hud.mousePressEvent(ev)
    assert sent == [("lm_mode", {"on": True})]


def test_voz_troca_igual_ao_botao(hud):
    # learning.start/stop por voz: o núcleo só manda lm_mode, sem clique nenhum
    hud.view = "idle"
    hud.on_bridge_learning(ON)
    assert hud.view == "learning"
    hud.on_bridge_learning(ON)   # reenvio na reconexão
    assert hud.view == "learning" and hud.lm_return == "idle"
    hud.on_bridge_learning(OFF)
    assert hud.view == "idle"


def test_nucleo_fora_nada_muda(hud):
    assert not hud.bridge.is_connected
    hud.view = "full"
    hud.wired_click("learning")   # send_lm real: falso, nada sai
    assert hud.view == "full" and hud.lm_return is None


def test_meta_m_no_hud_durante_o_modo_so_muda_o_retorno(hud, monkeypatch):
    hud.on_bridge_learning(ON)
    assert hud.view == "learning" and hud.lm_return == "full"
    meta_m_hud(hud, monkeypatch, "idle")
    assert hud.view == "learning" and hud.lm_return == "idle"
    hud.on_bridge_learning(OFF)
    assert hud.view == "idle"
    meta_m_hud(hud, monkeypatch, "full")   # fora do modo: Meta+M como antes
    assert hud.view == "full"


def test_detalhe_pedido_pela_voz_nao_tira_da_tela_learning(hud):
    hud.view = "idle"
    hud.on_bridge_detail("cpu")   # abre o painel a partir da espera (detail_return = idle)
    assert hud.view == "full" and hud.detail_return == "idle"
    hud.on_bridge_learning(ON)
    assert hud.view == "learning" and hud.lm_return == "idle" and hud.detail_return is None
    hud.detail_closed()
    assert hud.view == "learning"
