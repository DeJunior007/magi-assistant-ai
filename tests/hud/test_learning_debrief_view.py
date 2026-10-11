"""LI2.4: painel do retorno da entrevista (``hud/wired/learning_debrief.py``) — parte pura e
``LearningScreen`` com ``lm_debrief`` falso cheio (5 notas), com notas faltando e vazio
(offscreen 2560×1440); Esc fecha; o drawer de observações volta igual."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MAGI_PORTRAIT_DIR", "/nonexistent/magi-portrait")
os.environ.setdefault("MAGI_NO_CLAUDE_STATS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

import pytest  # noqa: E402
from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from wired import learning_debrief as dbv  # noqa: E402
from wired.learning_model import LearningModel  # noqa: E402
from wired.learning_screen import LearningScreen  # noqa: E402
from wired.main_screen import Snapshot  # noqa: E402

NOW = datetime(2026, 10, 11, 18, 5, 0)
S = 2560 / 1920


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


SCORES = [
    {"aspect": "fluency", "score": 72, "note": "Few pauses, but long fillers in the technical part."},
    {"aspect": "grammar", "score": 64, "note": "Past tense slips when telling stories."},
    {"aspect": "vocabulary", "score": 81, "note": "Good technical range."},
    {"aspect": "job_fit", "score": 58, "note": "Kubernetes was barely touched."},
    {"aspect": "clarity", "score": 90, "note": "Answers had a clear structure."},
]


def debrief(**kw):
    return {"t": "lm_debrief", "run_id": "IR-0001",
            "coverage": [
                {"requirement": "5+ years of Python", "cover": "covered",
                 "evidence": "I have been writing Python services since 2017"},
                {"requirement": "REST API design", "cover": "thin", "evidence": "we used FastAPI"},
                {"requirement": "Kubernetes in production", "cover": "missed", "evidence": None},
            ],
            "scores": SCORES,
            "strengths": ["Concrete examples with numbers", "Calm pace"],
            "improve": ["Talk about trade-offs", "Use the past tense in stories",
                        "Ask about the team"],
            "rewrites": [["Tell me about a hard bug.",
                          "Last year I tracked down a race condition in our payment worker…"]],
            "language": ["Past tense", "Prepositions", "deploy"],
            "closing": "Nice work. The details are on the screen.",
            "title": "Backend Engineer", "company": "Acme", "at": "2026-10-11T18:04:00", **kw}


CASES = {
    "full": debrief(),
    "missing": debrief(scores=[SCORES[0], SCORES[3]]),
    "empty": {"t": "lm_debrief", "run_id": "IR-0002", "coverage": [], "scores": [],
              "strengths": [], "improve": [], "rewrites": [], "language": [], "closing": "",
              "title": "Backend Engineer", "at": "2026-10-11T18:04:00"},
}


def screen_with(msg=None):
    sc = LearningScreen(info=LearningModel(clock=Clock()))
    sc.send_lm = lambda t, f: True
    sc.info.feed({"t": "lm_session", "id": "LS-0001", "n_msgs": 3, "topic": "interview"})
    if msg is not None:
        sc.info.feed(msg)
    return sc


def key(sc):
    return sc.group_key("debrief", Snapshot(), NOW)


def render(sc) -> QImage:
    size = QSize(2560, 1440)
    img = QImage(size, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    sc.paint(p, size, Snapshot(), NOW)
    p.end()
    return img


def center(r):
    return (r.x + r.w / 2, r.y + r.h / 2)


# ====================================================================== puro

def test_scores_one_line_per_aspect_absent_is_dash_no_overall():
    rs = dbv.rows(CASES["missing"])
    sc = [r for r in rs if r.kind == "score"]
    assert [r.text for r in sc] == ["FLUENCY", "GRAMMAR", "VOCABULARY", "JOB FIT", "CLARITY"]
    assert [r.value for r in sc] == [72, None, None, 58, None]
    assert [dbv.score_text(r.value) for r in sc] == ["72", "—", "—", "58", "—"]
    assert not any("OVERALL" in r.text.upper() for r in rs)
    assert rs[0] == dbv.Row("head", "SCORES")  # notas no topo


def test_score_map_drops_unknown_clamps_and_keeps_first():
    m = dbv.score_map({"scores": [{"aspect": "charisma", "score": 99, "note": ""},
                                  {"aspect": "fluency", "score": 140, "note": "x"},
                                  {"aspect": "fluency", "score": 10, "note": "y"},
                                  {"aspect": "grammar", "score": "bad"}]})
    assert m == {"fluency": (100, "x")}


def test_rows_coverage_marks_evidence_and_sections():
    rs = dbv.rows(CASES["full"], chars=60)
    cov = [r for r in rs if r.kind == "cover" and r.value]
    assert [r.value for r in cov] == ["covered", "thin", "missed"]
    assert [dbv.MARKS[r.value] for r in cov] == ["✓", "~", "✗"]
    ev = [r.text for r in rs if r.kind == "evidence"]
    assert ev[0].startswith("“I have been") and len(ev) == 2  # missed sem evidência
    heads = [r.text for r in rs if r.kind == "head"]
    assert heads == ["SCORES", "REQUIREMENTS", "STRENGTHS", "TO IMPROVE", "BETTER ANSWERS",
                     "ENGLISH"]
    notes = [r for r in rs if r.kind == "note"]
    assert notes and all(len(r.text) <= 60 for r in notes)


def test_empty_debrief_only_scores_with_dashes():
    rs = dbv.rows(CASES["empty"])
    assert [r.kind for r in rs] == ["head"] + ["score"] * 5
    assert all(r.value is None for r in rs[1:])


def test_view_opens_once_per_debrief_scrolls_and_closes():
    v = dbv.DebriefView()
    panel = dbv.Rect(0, 0, 360, 330)
    msg = CASES["full"]
    v.sync(msg)
    assert v.is_open
    assert dbv.max_scroll(panel, msg) > 0
    assert v.wheel(-3, panel, msg) and v.scroll == 3 * dbv.WHEEL_STEP
    assert not v.wheel(-1000, panel, msg) or v.scroll == dbv.max_scroll(panel, msg)
    assert v.scroll == dbv.max_scroll(panel, msg)
    assert v.key("esc") and not v.is_open
    v.sync(msg)
    assert not v.is_open                       # o mesmo retorno não reabre
    v.sync(debrief(run_id="IR-0009"))
    assert v.is_open and v.scroll == 0
    assert v.press(center(dbv.close_rect(panel)), panel, debrief(run_id="IR-0009")) == "close"
    assert not v.is_open


def test_model_keeps_debrief():
    m = LearningModel(clock=Clock())
    assert m.feed(CASES["full"]) == {"debrief"}
    assert m.debrief["run_id"] == "IR-0001" and "t" not in m.debrief
    assert m.feed({"t": "lm_debrief"}) == set() and m.debrief["run_id"] == "IR-0001"


# ====================================================================== tela

def test_group_over_obs_and_esc_closes():
    sc = screen_with(CASES["full"])
    names = list(sc.groups())
    assert names.index("obs") < names.index("debrief")
    assert sc.groups()["debrief"][0] == sc.groups()["obs"][0]
    k = key(sc)
    assert k[0] is True
    assert sc.key("esc") and not sc.debrief_view.is_open
    assert key(sc) == (False,)
    assert not sc.key("esc")


def test_click_inside_does_not_toggle_obs_and_outside_closes():
    sc = screen_with(CASES["full"])
    head = sc.obs_view.head_rect(sc.L.obs)
    sc.mouse("press", center(head))
    assert sc.debrief_view.is_open and not sc.obs_view.is_open
    sc.mouse("press", (sc.L.history.x + 50, sc.L.history.y + 200))
    assert not sc.debrief_view.is_open
    sc.mouse("press", center(head))
    assert sc.obs_view.is_open                 # fechado o retorno, o drawer volta a responder


def test_close_button_and_wheel():
    sc = screen_with(CASES["full"])
    k = key(sc)
    sc.mouse("wheel", center(sc.L.obs), -2)
    assert sc.debrief_view.scroll > 0 and key(sc) != k
    sc.mouse("press", center(dbv.close_rect(sc.L.obs)))
    assert not sc.debrief_view.is_open


def test_hidden_without_debrief():
    sc = screen_with(None)
    assert key(sc) == (False,)
    head = sc.obs_view.head_rect(sc.L.obs)
    sc.mouse("press", center(head))
    assert sc.obs_view.is_open


def _px(img, x, y):
    return QColor(img.pixel(round(x * S), round(y * S)))


@pytest.mark.parametrize("name", list(CASES))
def test_paints_offscreen(name, tmp_path):
    sc = screen_with(CASES[name])
    img = render(sc)
    body = dbv.body_rect(sc.L.obs)
    # barra da FLUENCY: lilás com nota, apagada sem nota
    rs = dbv.rows(CASES[name], dbv.chars(sc.L.obs))
    i = next(i for i, r in enumerate(rs) if r.kind == "score")
    y = body.y + sum(r.h for r in rs[:i]) + rs[i].h / 2
    c = _px(img, body.x + dbv.BAR_X + 2, y)
    if name == "empty":
        assert c.blue() < 80
    else:
        assert c.red() > 120 and c.blue() > 180
    assert img.save(str(tmp_path / f"debrief_{name}.png"))


def test_obs_drawer_comes_back_the_same():
    plain = screen_with(None)
    plain.info.feed({"t": "lm_obs", "items": [{"category": "vocabulary", "label": "deploy",
                                               "message_id": 1}], "count": 1})
    before = render(plain).copy(*[round(v * S) for v in (plain.L.obs.x, plain.L.obs.y,
                                                         plain.L.obs.w, plain.L.obs.h)])
    sc = screen_with(None)
    sc.info.feed({"t": "lm_obs", "items": [{"category": "vocabulary", "label": "deploy",
                                            "message_id": 1}], "count": 1})
    sc.info.feed(CASES["full"])
    size = QSize(2560, 1440)
    img = render(sc)
    assert sc.key("esc")
    regions = sc.dirty_regions(Snapshot(), NOW, size)
    assert regions
    p = QPainter(img)
    for r in regions:
        sc.paint(p, size, Snapshot(), NOW, region=r)
    p.end()
    after = img.copy(*[round(v * S) for v in (sc.L.obs.x, sc.L.obs.y, sc.L.obs.w, sc.L.obs.h)])
    assert after == before
