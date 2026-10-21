"""Y6.6c: cartão do código de pareamento no HUD (painel e espera), em offscreen.

O ``CardMsg`` do núcleo (``AvisosAyanami.codigo_pareamento``) passa pelo ``hud_bridge`` e chega ao
``gamerhud``: antes virava só "⚠ Código…" no rodapé de eventos (nenhum card desenhado). Agora o
``WiredUI`` guarda o cartão, as telas pintam o código grande, "vale 5 min" e o link no lugar do
``LAST SESSION``, clique fecha, some em 5 min.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GAMERHUD_NO_WALLPAPER"] = "1"
os.environ.setdefault("MAGI_PORTRAIT_DIR", "/nonexistent/magi-portrait")
os.environ.setdefault("MAGI_NO_CLAUDE_STATS", "1")
os.environ.setdefault("MAGI_NO_VOLUME", "1")
os.environ.setdefault("MAGI_NO_NOTIF", "1")
os.environ.setdefault("MAGI_NO_EXTRAS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from PySide6.QtCore import QPoint, QSize  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from wired import pairing_card as pc  # noqa: E402
from wired.integration import WiredUI  # noqa: E402

from magi.common.contracts import CardLevel, CardMsg  # noqa: E402
from magi.common.events import encode_hud_line  # noqa: E402

LINK = "https://magi.dekasis.com.br/app/#/parear?c=199152"
MSG = CardMsg(CardLevel.ALTA, "Código de pareamento 199 152", url=LINK, source="pareamento")
CARD = {k: v for k, v in MSG.to_dict().items() if k != "t"}
BASE = QSize(1920, 1080)
NOW = datetime(2026, 10, 21, 21, 0, 0)


def test_codigo_do_link_e_do_titulo():
    assert pc.code_of(CARD) == "199 152"
    assert pc.code_of({"title": "Código de pareamento 482 913"}) == "482 913"
    assert pc.is_pairing(CARD) and not pc.is_pairing({"level": "alta", "title": "x"})


def test_some_em_5_min_e_ao_fechar():
    c = pc.PairingCard()
    c.set(CARD, 100.0)
    assert c.current(399.0) == CARD and c.current(400.0) is None
    assert c.deadline() == 400.0
    c.close()
    assert c.current(101.0) is None


def render(w: WiredUI, view: str) -> QImage:
    img = QImage(BASE, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    w.screen(view).paint(p, BASE, w.snap, NOW, mono=0.0)
    p.end()
    return img


@pytest.mark.parametrize("view", ["full", "idle"])
def test_tela_pinta_o_cartao_e_clique_fecha(view):
    w = WiredUI()
    scr = w.screen(view)
    region = scr.SUMMARY_RECT.toAlignedRect().adjusted(-2, -2, 2, 2)
    before = render(w, view).copy(region)
    k0 = scr.group_key("pairing", w.snap, NOW)
    w.on_card(dict(CARD))
    assert not any("199" in e for e in w.snap.events)   # o código não vai ao rodapé de eventos
    assert w.pairing_now() is not None
    assert scr.group_key("pairing", w.snap, NOW) != k0
    img = render(w, view)
    assert img.copy(region) != before
    if out := os.environ.get("PAIRING_CAPTURE"):
        Path(out).mkdir(parents=True, exist_ok=True)
        img.save(str(Path(out) / f"pairing_{view}.png"))
    c = scr.SUMMARY_RECT.center()
    assert w.hit(QPoint(round(c.x()), round(c.y())), BASE, view) == "pairing"
    w.pairing_close()
    assert w.pairing_now() is None
    assert scr.group_key("pairing", w.snap, NOW) == k0


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
    yield w
    for name in ("face_timer", "anim_timer", "data_timer", "rgb_timer", "wired_timer", "caption_timer"):
        t = getattr(w, name, None)
        if t is not None:
            t.stop()
    bridge.stop()
    w.hide()
    w.deleteLater()


def test_gamerhud_recebe_cardmsg_pelo_bridge(hud, monkeypatch):
    """Linha do socket → ``hud_bridge`` → sinal ``card`` → ``gamerhud`` → cartão visível, prazo
    agendado em 5 min, clique fecha."""
    import gamerhud
    import hud_bridge

    shots = []
    monkeypatch.setattr(gamerhud.QTimer, "singleShot", lambda ms, fn: shots.append((ms, fn)))
    msg = hud_bridge._decode_min(encode_hud_line(MSG))
    hud.bridge._dispatch[msg["t"]](msg)
    cur = hud.wired.pairing_now()
    assert cur is not None and cur["url"] == LINK and pc.code_of(cur) == "199 152"
    assert any(299_000 <= ms <= 300_100 and fn == hud.wired_refresh for ms, fn in shots)
    hud.wired_click("pairing")
    assert hud.wired.pairing_now() is None
