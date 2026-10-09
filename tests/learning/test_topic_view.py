"""LM1.9 / CA-25: seletor de tema (lógica pura de ``learning_topic``) e o grupo ``topic`` da
``LearningScreen`` (abre em sessão nova e não em retomada; fecha em 10 s, Esc, clique fora e
mensagem; o chip mostra só o tema confirmado e o ``detail`` do fallback; clique → ``lm_topic``)."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MAGI_PORTRAIT_DIR", "/nonexistent/magi-portrait")
os.environ.setdefault("MAGI_NO_CLAUDE_STATS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from wired import learning_topic as tp  # noqa: E402
from wired.learning_screen import LearningScreen  # noqa: E402
from wired.learning_text import Rect  # noqa: E402
from wired.main_screen import Snapshot  # noqa: E402

NOW = datetime(2026, 10, 7, 17, 42, 10)
CHIP = Rect(1000, 160, 300, 44)
COL = Rect(500, 160, 900, 700)


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def session(sid="LS-0001", n_msgs=0, **kw):
    return {"t": "lm_session", "id": sid, "started_at": "2026-10-07T17:40:00", "level": "B2",
            "track": "conversation", "topic": "free", "n_msgs": n_msgs, "obs_count": 0, **kw}


def screen_with(n_msgs=0, **kw):
    clock = Clock()
    sc = LearningScreen()
    sc.topic_picker = tp.TopicPicker(clock=clock)
    sent = []
    sc.send_lm = lambda t, f: sent.append((t, f)) or True
    sc.info.feed(session(n_msgs=n_msgs, **kw))
    return sc, clock, sent


def key(sc):
    return sc.group_key("topic", Snapshot(), NOW)


def center(r: Rect):
    return (r.x + r.w / 2, r.y + r.h / 2)


# ------------------------------------------------------------------ puro

def test_opens_only_in_new_session():
    clock = Clock()
    p = tp.TopicPicker(clock=clock)
    p.sync(session(n_msgs=0), None)
    assert p.is_open and p.auto
    p.close()
    p.sync(session(n_msgs=0), None)   # mesma sessão: não reabre
    assert not p.is_open
    q = tp.TopicPicker(clock=clock)
    q.sync(session(n_msgs=12), 5)     # retomada
    assert not q.is_open


def test_closes_on_timeout_esc_and_message():
    clock = Clock()
    p = tp.TopicPicker(clock=clock)
    p.sync(session(), None)
    clock.t += 9.9
    p.sync(session(), None)
    assert p.is_open
    clock.t += 0.2
    assert p.sync(session(), None) and not p.is_open        # 10 s sem escolha
    p.open(last_you=None)
    assert p.key("esc") and not p.is_open
    assert not p.key("esc")                                  # fechada: Esc não é dela
    p.open(last_you=3)
    p.sync(session(), 3)
    assert p.is_open
    p.sync(session(), 4)                                     # o Pedro falou/digitou
    assert not p.is_open


def test_chip_shows_confirmed_topic_and_detail():
    assert tp.chip_text({}, {}) == "TOPIC // FREE TALK ▾"
    assert tp.chip_text({}, {"topic": "interview"}) == "TOPIC // TECH INTERVIEW ▾"
    fb = {"topic": "free", "requested": "game", "label": "FREE TALK", "detail": "no game detected"}
    assert tp.chip_text(fb) == "TOPIC // FREE TALK · no game detected ▾"
    ok = {"topic": "game", "requested": "game", "label": "THE GAME I'M PLAYING", "detail": None}
    assert tp.chip_parts(ok, {"topic": "free"}) == ("TOPIC // ", "THE GAME I'M PLAYING", None)


def test_press_geometry():
    p = tp.TopicPicker(clock=Clock())
    lst = tp.list_rect(CHIP, COL)
    assert lst.top > CHIP.bottom and lst.right == CHIP.right and lst.w == tp.LIST_W
    assert COL.contains_rect(lst)
    assert p.press(center(CHIP), CHIP, lst) == ("toggle", None) and p.is_open
    assert p.press(center(tp.row_rect(lst, 2)), CHIP, lst) == ("choose", "game")
    assert not p.is_open
    p.open()
    assert p.press((lst.x + 5, lst.y + 5), CHIP, lst) == ("inside", None) and p.is_open
    assert p.press((10, 10), CHIP, lst) == ("outside", None) and not p.is_open
    assert p.press((10, 10), CHIP, lst) == ("none", None)


# ------------------------------------------------------------------ tela

def test_screen_new_session_opens_and_times_out():
    sc, clock, _ = screen_with(n_msgs=0)
    k0 = key(sc)
    assert sc.topic_picker.is_open
    assert len(sc.groups()["topic"]) == 2                    # chip + lista
    clock.t += 10.0
    assert key(sc) != k0 and not sc.topic_picker.is_open


def test_screen_resumed_session_stays_closed():
    sc, _, _ = screen_with(n_msgs=8)
    key(sc)
    assert not sc.topic_picker.is_open
    assert sc.groups()["topic"] == sc._topic_now() and len(sc._topic_now()) == 1


def test_screen_click_item_sends_lm_topic_and_chip_waits_confirmation():
    sc, _, sent = screen_with()
    key(sc)
    lst = sc._topic_list()
    sc.mouse("hover", center(tp.row_rect(lst, 1)))
    assert sc.topic_picker.hover == 1
    assert sc.mouse("press", center(tp.row_rect(lst, 1))) is None
    assert sent == [("lm_topic", {"topic": "interview"})]
    assert not sc.topic_picker.is_open
    assert tp.chip_parts(sc.info.topic, sc.info.session)[1] == "FREE TALK"   # ainda não confirmado
    sc.info.feed({"t": "lm_topic", "topic": "interview", "requested": "interview",
                  "label": "TECH INTERVIEW", "detail": None})
    assert tp.chip_parts(sc.info.topic, sc.info.session)[1] == "TECH INTERVIEW"


def test_screen_chip_reopens_esc_and_message_close():
    sc, _, sent = screen_with()
    key(sc)
    sc.mouse("press", (10, 500))                             # clique fora fecha
    assert not sc.topic_picker.is_open and not sent
    sc.mouse("press", center(sc.L.topic))                    # o chip reabre
    assert sc.topic_picker.is_open
    assert sc.key("esc") and not sc.topic_picker.is_open
    sc.mouse("press", center(sc.L.topic))
    sc.info.feed({"t": "lm_msg", "id": 1, "author": "you", "source": "voice", "text": "hi there",
                  "at": "", "speaking": False})
    key(sc)
    assert not sc.topic_picker.is_open                       # o Pedro falou
    sc.mouse("press", center(sc.L.topic))
    assert sc.key("enter", typing=True) is False and not sc.topic_picker.is_open


def test_screen_send_failure_logs_and_list_paints_after_history():
    sc, _, _ = screen_with(topic_hints={"game": "Hades II · 2 h today"})
    sc.send_lm = lambda t, f: False
    assert sc.choose_topic("news") is False and "not connected" in (sc.info.log or "")
    names = list(sc.groups())
    assert names.index("topic") > names.index("history")
    key(sc)
    assert sc._topic_list().w == tp.LIST_W_HINT
    sc.info.feed({"t": "lm_topic", "topic": "free", "requested": "game", "label": "FREE TALK",
                  "detail": "no game detected"})
    img = QImage(QSize(1920, 1080), QImage.Format.Format_ARGB32)
    p = QPainter(img)
    sc.paint(p, QSize(1920, 1080), Snapshot(), NOW)
    p.end()
    assert sc._tp_shown == sc._topic_now()
    sc.topic_picker.close()
    assert len(sc.groups()["topic"]) == 2                    # a lista velha entra para ser apagada
