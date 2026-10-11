"""LI2.1 / CA-07 (envio): ``[ PASTE JOB ]`` e vagas recentes no seletor de tema, ``lm_job`` pelo
clipboard (falso), resposta ao ``lm_job_req`` e a pergunta da colagem longa no campo (R1.1–R1.4)."""

from __future__ import annotations

import gamerhud
import hud_bridge
import pytest
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter
from wired import learning_topic as tp
from wired.integration import WiredUI
from wired.learning_text import Rect

from magi.learning.interview import contracts as ic

from .test_wired_integration import FakeNet, FakeNP

CHIP = Rect(1200.0, 100.0, 400.0, 40.0)
COL = Rect(600.0, 80.0, 1000.0, 1200.0)
JOB = "Senior Python backend engineer.\n" + "- build APIs with FastAPI and Postgres\n" * 12
JOBS = [{"job_id": "JOB-aaaa0001", "title": "Backend Engineer", "company": "Acme"},
        {"job_id": "JOB-aaaa0002", "title": "Data Engineer"},
        {"job_id": "JOB-aaaa0003", "title": "Full-stack", "company": "Foo"},
        {"job_id": "JOB-aaaa0004", "title": "Extra"}]


def center(r: Rect) -> tuple[float, float]:
    return (r.x + r.w / 2, r.y + r.h / 2)


# ------------------------------------------------------------------ parte pura

def test_constants_mirror_core():
    assert (tp.JOB_MIN, tp.JOB_MAX, tp.PASTE_ASK) == (ic.JOB_MIN, ic.JOB_MAX, ic.PASTE_ASK)
    assert tp.JOB_MAX == hud_bridge.JOB_MAX


def test_job_check_and_long_paste():
    assert tp.job_check("") == (None, tp.EMPTY)
    assert tp.job_check("   \n ") == (None, tp.EMPTY)
    assert tp.job_check("x" * 199) == (None, tp.TOO_SHORT)
    assert tp.job_check(JOB) == (JOB.strip(), None)
    big = ("line of a long job post\n" * 600)
    text, warn = tp.job_check(big)
    assert warn == tp.TRIMMED and len(text) <= tp.JOB_MAX and text.endswith("post")
    assert tp.job_check("a\r\nb" + "c" * 300)[0].startswith("a\nb")
    assert not tp.is_long_paste("short") and not tp.is_long_paste(None)
    assert tp.is_long_paste("a\nb") and tp.is_long_paste("x" * 601)
    assert not tp.is_long_paste("x" * 600)


def test_jobs_of_keeps_three_with_id():
    jobs = tp.jobs_of({"jobs": JOBS + [{"title": "no id"}]})
    assert [j.job_id for j in jobs] == ["JOB-aaaa0001", "JOB-aaaa0002", "JOB-aaaa0003"]
    assert jobs[0].text() == "Backend Engineer · Acme" and jobs[1].text() == "Data Engineer"
    assert tp.jobs_of({}) == () and tp.jobs_of({"jobs": "x"}) == ()


def test_geometry_with_subrows_keeps_rows_consistent():
    plain = tp.list_rect(CHIP, COL)
    assert tp.n_subs(plain) == 1                              # sempre o [ PASTE JOB ]
    full = tp.list_rect(CHIP, COL, n_jobs=5)
    assert tp.n_subs(full) == 4 and full.h == plain.h + 3 * tp.SUB_H
    for lst in (plain, full):
        assert tp.item_at(lst, center(tp.row_rect(lst, 1))) == 1
        assert tp.item_at(lst, center(tp.row_rect(lst, 2))) == 2
        assert tp.item_at(lst, center(tp.sub_rect(lst, 0))) == tp.PASTE_ROW
        assert tp.sub_rect(lst, 0).top == tp.row_rect(lst, 1).bottom
        assert tp.row_rect(lst, 2).top == tp.sub_rect(lst, tp.n_subs(lst) - 1).bottom
        assert COL.contains_rect(lst)
    assert tp.item_at(full, center(tp.sub_rect(full, 3))) == tp.PASTE_ROW + 3


def test_press_subrows_call_on_job_and_close():
    picked = []
    p = tp.TopicPicker(clock=lambda: 0.0, on_job=picked.append)
    p.sync({"id": "LS-1", "n_msgs": 0, "jobs": JOBS}, None, now=0.0)
    assert p.is_open and len(p.jobs) == 3
    lst = tp.list_rect(CHIP, COL, n_jobs=len(p.jobs))
    assert p.press(center(tp.sub_rect(lst, 0)), CHIP, lst) == ("inside", None)
    assert picked == [None] and not p.is_open
    p.open()
    assert p.press(center(tp.sub_rect(lst, 2)), CHIP, lst) == ("inside", None)
    assert picked == [None, "JOB-aaaa0002"] and not p.is_open
    p.open()
    assert p.press(center(tp.row_rect(lst, 1)), CHIP, lst) == ("choose", "interview")


def test_paint_list_with_subrows_offscreen():
    p0 = tp.TopicPicker(clock=lambda: 0.0)
    p0.sync({"id": "LS-1", "n_msgs": 0, "jobs": JOBS}, None, now=0.0)
    lst = tp.list_rect(Rect(1100, 10, 400, 40), Rect(0, 0, 1600, 900), n_jobs=3)
    img = QImage(1600, 900, QImage.Format.Format_ARGB32)
    img.fill(QColor("#000000"))
    p0.set_hover(tp.PASTE_ROW + 1)
    p = QPainter(img)
    tp.paint_list(p, lst, p0, "interview", {})
    p.end()
    r = tp.sub_rect(lst, 1)
    assert not img.copy(QRectF(r.x, r.y, r.w, r.h).toRect()).allGray()   # sublinha pintada


# ------------------------------------------------------------------ gamerhud (clipboard falso)

@pytest.fixture
def hud(tmp_path, monkeypatch):
    cfg = {"view": "full", "transition": False, "ui": "wired"}
    monkeypatch.setattr(gamerhud, "load_settings", lambda: cfg)
    monkeypatch.setattr(gamerhud, "save_settings", lambda d: None)
    monkeypatch.setattr(gamerhud.orgb, "board_color", lambda: None)
    monkeypatch.setattr(gamerhud, "steam_game", lambda: None)
    monkeypatch.setattr(gamerhud, "FPS_DIR", tmp_path / "fps")
    monkeypatch.setattr(gamerhud, "WiredUI", lambda: WiredUI(now_playing=FakeNP(), net=FakeNet()))
    bridge = hud_bridge.HudBridge(tmp_path / "hud.sock")
    w = gamerhud.HUD({"seg": "Hack"}, bridge=bridge)
    w.clip = [JOB]
    w.lm_clipboard = lambda: w.clip[0]          # nada do QClipboard real
    w.sent = []
    w.connected = True
    monkeypatch.setattr(w.bridge, "send_lm",
                        lambda t, f=None: w.connected and (w.sent.append((t, f)) or True))
    w.view = "learning"
    yield w
    for t in (w.face_timer, w.anim_timer, w.data_timer, w.rgb_timer, w.wired_timer):
        t.stop()
    bridge.stop()
    w.hide()
    w.deleteLater()


def key(w, k, mod=Qt.KeyboardModifier.NoModifier, text=""):
    ev = QKeyEvent(QEvent.Type.KeyPress, k, mod, text)
    return w.eventFilter(w.lm_entry, ev)


def test_paste_job_sends_lm_job(hud):
    assert hud.learning_paste_job()
    assert hud.sent == [("lm_job", {"text": JOB.strip(), "source": "clipboard"})]
    assert "preparing" in hud.learning_model.log


def test_paste_job_refuses_empty_and_short_locally(hud):
    for raw, line in (("", tp.EMPTY), ("vaga curta", tp.TOO_SHORT)):
        hud.clip[0] = raw
        assert not hud.learning_paste_job()
        assert hud.learning_model.log == line
    assert hud.sent == []


def test_paste_job_disconnected(hud):
    hud.connected = False
    assert not hud.learning_paste_job()
    assert hud.learning_model.log == "job not sent — not connected"


def test_lm_job_req_answers_with_clipboard(hud):
    hud.on_bridge_learning({"t": "lm_job_req"})
    assert hud.sent == [("lm_job", {"text": JOB.strip(), "source": "voice"})]


def test_picker_subrow_routes_to_hud(hud):
    hud.learning_entry_sync()
    picker = hud.wired.learning.topic_picker
    picker.pick_job(None)
    picker.pick_job("JOB-aaaa0001")
    assert hud.sent == [("lm_job", {"text": JOB.strip(), "source": "clipboard"}),
                        ("lm_job", {"job_id": "JOB-aaaa0001"})]


def test_long_paste_in_field_asks_then_yes(hud):
    assert key(hud, Qt.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert hud.lm_paste_ask and hud.learning_model.log == tp.PASTE_QUESTION
    assert hud.lm_entry.text() == "" and hud.sent == []
    assert key(hud, Qt.Key_Return)
    assert not hud.lm_paste_ask
    assert hud.sent == [("lm_job", {"text": JOB.strip(), "source": "clipboard"})]


def test_long_paste_no_and_other_key(hud):
    assert key(hud, Qt.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert key(hud, Qt.Key_Escape)
    assert not hud.lm_paste_ask and hud.learning_model.log is None and hud.sent == []
    assert key(hud, Qt.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert not key(hud, Qt.Key_A, text="a")                    # outra tecla desiste e segue
    assert not hud.lm_paste_ask and hud.sent == []


def test_short_paste_goes_to_field(hud):
    hud.clip[0] = "hello there"
    assert not key(hud, Qt.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert not hud.lm_paste_ask
