"""LM4.6 (CA-21): cartão ``LAST SESSION`` no painel e na espera.

- Lógica pura (relógio falso): linhas do cartão, ★ nas salvas, ``+N``; aparece na view de retorno,
  some em 60 s, ao clicar e ao ``lm_mode on``; ``lm_summary`` atrasado > 10 s é descartado; sem
  pontuação/streak no texto.
- Telas: grupo ``lm_summary`` com chave que muda só ao aparecer/sumir, sem cobrir retrato nem
  player; alvo ``"lm_summary"`` no ``hit``.
- ``gamerhud`` (offscreen): ``lm_summary`` agenda o ``singleShot`` do prazo; clique fecha.

``LM_SUMMARY_CAPTURE=<dir> pytest tests/learning/test_summary_card.py`` salva as capturas do painel
e da espera com o cartão (CA-19).
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

from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from wired import learning_summary as ls  # noqa: E402
from wired import main_screen  # noqa: E402
from wired.integration import WiredUI  # noqa: E402
from wired.learning_model import LearningModel  # noqa: E402

ON = {"t": "lm_mode", "on": True}
OFF = {"t": "lm_mode", "on": False}
SUMMARY = {
    "t": "lm_summary", "session_id": "LS-20261007-01", "n": 1,
    "started_at": "2026-10-07T17:00:00", "ended_at": "2026-10-07T17:24:00", "duration_s": 1440,
    "end_reason": "button", "n_msgs": 38, "n_you": 19, "obs_count": 6,
    "practiced": ["Prepositions", "Past tense"], "new_words": ["repository", "deploy", "assistant"],
    "saved": ["assistant"], "more_practiced": 0, "more_words": 2, "topics": ["free"],
}
BASE = QSize(1920, 1080)
NOW = datetime(2026, 10, 7, 17, 42, 10)
FORBIDDEN = ("SCORE", "STREAK", "XP", "%", "POINT", "GRADE", "BEST", "RANK", "LEVEL")


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


# ------------------------------------------------------------------ texto (puro)


def test_linhas_do_cartao():
    lines = ls.card_lines(SUMMARY)
    assert lines == [
        ("", "LAST SESSION // 01"),
        ("", "24 MIN · 38 MSGS · 6 OBS · FREE TALK"),
        ("PRACTISED", "Prepositions · Past tense"),
        ("NEW WORDS", "repository · deploy · assistant ★  +2"),
    ]


def test_sem_pontuacao_nem_streak():
    txt = " ".join(t for _, t in ls.card_lines(SUMMARY)).upper()
    assert not any(w in txt for w in FORBIDDEN)


def test_fit_soma_o_que_nao_coube_ao_mais():
    items = ["repository", "deploy", "assistant ★"]
    assert ls.fit(items, 2, 1e9, len) == "repository · deploy · assistant ★  +2"
    assert ls.fit(items, 2, len("repository · deploy  +3"), len) == "repository · deploy  +3"
    assert ls.fit(items, 0, 5, len) == "+3"
    assert ls.fit([], 0, 100, len) == "—"


def test_temas_e_vazios():
    s = {**SUMMARY, "topics": ["free", "news", "free"], "practiced": [], "duration_s": 20}
    assert ls.stats(s) == "1 MIN · 38 MSGS · 6 OBS · FREE TALK / NEWS"
    assert ls.card_lines(s)[2] == ("PRACTISED", "—")
    assert ls.topics_label([]) == "FREE TALK"


# ------------------------------------------------------------------ validade (relógio falso)


def model_after_off(clock: Clock, delay: float = 1.0) -> tuple[LearningModel, ls.SummaryCard]:
    m, card = LearningModel(clock=clock), ls.SummaryCard()
    m.feed(ON)
    card.mode(True, clock())
    m.feed(OFF)
    card.mode(False, clock())
    clock.t += delay
    m.feed(SUMMARY)
    return m, card


def test_aparece_e_some_em_60_s():
    clock = Clock()
    m, card = model_after_off(clock)
    assert card.current(m, clock()) is not None
    assert card.current(m, clock() + 59.9) is not None
    assert card.current(m, clock() + 60.0) is None
    assert card.deadline(m.summary_at) == clock() + 60.0


def test_clique_fecha():
    clock = Clock()
    m, card = model_after_off(clock)
    card.close(m.summary_at)
    assert card.current(m, clock()) is None


def test_lm_mode_on_esconde():
    clock = Clock()
    m, card = model_after_off(clock)
    m.feed(ON)
    card.mode(True, clock())
    assert card.current(m, clock()) is None
    m.feed(OFF)   # sai de novo: o resumo antigo não volta
    card.mode(False, clock())
    assert card.current(m, clock()) is None


@pytest.mark.parametrize(("delay", "shown"), [(0.0, True), (10.0, True), (10.1, False), (30.0, False)])
def test_resumo_atrasado_descartado(delay, shown):
    clock = Clock()
    m, card = model_after_off(clock, delay)
    assert (card.current(m, clock()) is not None) is shown


def test_sem_off_visto_nao_mostra():
    """HUD reiniciado (ou resumo antes do off deste HUD): não reexibe."""
    clock = Clock()
    m, card = LearningModel(clock=clock), ls.SummaryCard()
    m.feed(SUMMARY)
    assert card.current(m, clock()) is None
    card.mode(False, clock() + 1)   # off depois do resumo
    assert card.current(m, clock() + 1) is None


# ------------------------------------------------------------------ telas


@pytest.fixture
def ui():
    clock = Clock()
    w = WiredUI()
    w.learning.info = LearningModel(clock=clock)
    w.fake = clock
    return w


def show(w: WiredUI) -> None:
    m = w.learning.info
    m.feed(ON)
    w.summary_mode(True)
    m.feed(OFF)
    w.summary_mode(False)
    w.fake.t += 0.5
    m.feed(SUMMARY)


def dev(r) -> QRect:
    return r.toAlignedRect()


@pytest.mark.parametrize("view", ["full", "idle"])
def test_hit_e_chave_do_grupo(ui, view):
    scr = ui.screen(view)
    c = scr.SUMMARY_RECT.center()
    pos = QPoint(round(c.x()), round(c.y()))
    k0 = scr.group_key("lm_summary", ui.snap, NOW)
    assert ui.hit(pos, BASE, view) != "lm_summary"
    show(ui)
    assert ui.hit(pos, BASE, view) == "lm_summary"
    k1 = scr.group_key("lm_summary", ui.snap, NOW)
    assert k1 != k0
    ui.fake.t += 30
    assert scr.group_key("lm_summary", ui.snap, NOW) == k1   # não muda enquanto visível
    assert ui.summary_deadline() == pytest.approx(ui.learning.info.summary_at + 60)
    ui.summary_close()
    assert scr.group_key("lm_summary", ui.snap, NOW) == k0
    assert ui.hit(pos, BASE, view) != "lm_summary"


@pytest.mark.parametrize("view", ["full", "idle"])
def test_nao_cobre_retrato_nem_player(ui, view):
    scr = ui.screen(view)
    r = scr.SUMMARY_RECT
    assert not r.intersects(scr.MASCOT_RECT)
    for pr in scr.groups()["player"]:
        assert not r.intersects(pr)
    if view == "full":
        assert not r.intersects(main_screen.NP) and not r.intersects(main_screen.LEARN_BTN)
    else:
        assert not r.intersects(scr.learn_btn) and r.bottom() < scr.y_rule2
    assert list(scr.groups())[-1] == "lm_summary"   # pintado por cima


def render(w: WiredUI, view: str) -> QImage:
    img = QImage(BASE, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    w.screen(view).paint(p, BASE, w.snap, NOW, mono=0.0)
    p.end()
    return img


@pytest.mark.parametrize("view", ["full", "idle"])
def test_pinta_o_cartao_so_na_area_dele(ui, view):
    scr = ui.screen(view)
    box = dev(scr.SUMMARY_RECT)
    region = box.adjusted(-2, -2, 2, 2)
    before = render(ui, view).copy(region)
    show(ui)
    img = render(ui, view)
    assert img.copy(region) != before
    out = os.environ.get("LM_SUMMARY_CAPTURE")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        img.save(str(Path(out) / f"lm_summary_{view}.png"))


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
    yield w
    for name in ("face_timer", "anim_timer", "data_timer", "rgb_timer", "wired_timer", "caption_timer"):
        t = getattr(w, name, None)
        if t is not None:
            t.stop()
    bridge.stop()
    w.hide()
    w.deleteLater()


def deliver(hud, msg):
    """Como o bridge: entrega ao learning_model e depois emite ``learning``."""
    hud.learning_model.feed(msg)
    hud.on_bridge_learning(msg)


def test_gamerhud_agenda_o_prazo_e_clique_fecha(hud, monkeypatch):
    import gamerhud

    shots = []
    monkeypatch.setattr(gamerhud.QTimer, "singleShot", lambda ms, fn: shots.append((ms, fn)))
    hud.view = "full"
    deliver(hud, ON)
    deliver(hud, OFF)
    assert hud.wired.summary_now() is None
    deliver(hud, SUMMARY)
    assert hud.wired.summary_now() is not None
    assert any(59_000 <= ms <= 60_100 and fn == hud.wired_refresh for ms, fn in shots)
    hud.wired_click("lm_summary")
    assert hud.wired.summary_now() is None


def test_gamerhud_lm_mode_on_esconde(hud, monkeypatch):
    import gamerhud

    monkeypatch.setattr(gamerhud.QTimer, "singleShot", lambda ms, fn: None)
    hud.view = "idle"
    deliver(hud, ON)
    deliver(hud, OFF)
    deliver(hud, SUMMARY)
    assert hud.wired.summary_now() is not None
    deliver(hud, ON)
    assert hud.wired.summary_now() is None
