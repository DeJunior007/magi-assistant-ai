"""LI2.2 / CA-07 (parte da tela): faixa da entrevista pela vaga (chip, etapa, tempo,
``[ END INTERVIEW ]``), estados ``preparing`` (barra animada) e ``error`` (``retry`` →
``lm_job {"job_id"}``), painel do perfil aberto pelo chip, e o grupo ``interview`` da
``LearningScreen`` com ``lm_interview`` falsos em todos os estados (offscreen 2560×1440)."""

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

from wired import learning_interview as iv  # noqa: E402
from wired.learning_model import LearningModel  # noqa: E402
from wired.learning_screen import LearningScreen  # noqa: E402
from wired.learning_text import Point, Rect  # noqa: E402
from wired.main_screen import Snapshot  # noqa: E402

NOW = datetime(2026, 10, 11, 17, 42, 10)
HIST = Rect(436.8, 216.0, 809.2, 624.0)


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def running(**kw):
    return {"t": "lm_interview", "state": "running", "job_id": "JB-0001", "run_id": "IR-0001",
            "title": "Backend Engineer", "company": "Acme", "seniority": "senior",
            "stack": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"],
            "must": ["5+ years of Python", "REST API design", "SQL"],
            "stage": 3, "n_stages": 6, "stage_label": "technical — python", "asked": 1,
            "quota": 3, "elapsed_s": 760.0, "minutes": 30, **kw}


STATES = {
    "preparing": {"t": "lm_interview", "state": "preparing"},
    "ready": running(state="ready", stage=1, stage_label="intro", elapsed_s=0.0),
    "running": running(),
    "paused": running(state="paused"),
    "debriefing": running(state="debriefing"),
    "error": {"t": "lm_interview", "state": "error", "job_id": "JB-0001",
              "error": "extraction timed out"},
    "error_no_job": {"t": "lm_interview", "state": "error", "error": "budget exceeded"},
}


def center(r: Rect) -> Point:
    return (r.x + r.w / 2, r.y + r.h / 2)


# ====================================================================== puro

def test_chip_and_stage_line():
    m = running()
    assert iv.chip_parts(m) == ("INTERVIEW // ", "BACKEND ENGINEER", "Acme")
    assert iv.chip_text(m) == "INTERVIEW // BACKEND ENGINEER · Acme ▾"
    assert iv.chip_parts(STATES["preparing"]) == ("INTERVIEW // ", "PREPARING", None)
    assert iv.stage_text(m) == "STAGE 3/6 · TECHNICAL — PYTHON"
    assert iv.stage_line(m, 10.0, 10.0) == "STAGE 3/6 · TECHNICAL — PYTHON  12:40"
    assert iv.stage_line(m, 10.0, 75.0) == "STAGE 3/6 · TECHNICAL — PYTHON  13:45"   # relógio corre
    paused = STATES["paused"]
    assert iv.stage_line(paused, 10.0, 75.0) == "STAGE 3/6 · TECHNICAL — PYTHON · PAUSED  12:40"
    assert iv.stage_line(STATES["preparing"], 0, 0) == "READING THE JOB POST"
    assert "extraction timed out" in iv.stage_line(STATES["error"], 0, 0)


def test_visible_and_retry():
    assert not iv.visible(None)
    assert not iv.visible(running(state="done"))
    assert all(iv.visible(m) for m in STATES.values())
    assert iv.can_retry(STATES["error"])
    assert not iv.can_retry(STATES["error_no_job"])
    assert not iv.can_retry(running())


def test_deadline_bar_and_clock():
    assert iv.deadline(STATES["preparing"], 10.0, 10.05) == pytest.approx(10.2)
    assert iv.frame(10.0, 10.65) == 3
    assert iv.deadline(running(elapsed_s=760.4), 10.0, 10.0) == pytest.approx(10.6)
    assert iv.deadline(STATES["paused"], 10.0, 11.0) is None
    assert iv.deadline(None, None, 0.0) is None


def test_profile_rows():
    rows = iv.profile_rows(running(), 20)
    assert rows[0] == ("dim", "seniority: senior")
    assert ("head", "STACK") in rows and ("head", "MUST HAVE") in rows
    assert [s for st, s in rows if st == "item"] == ["5+ years of Python", "REST API design", "SQL"]
    assert all(len(s) <= 20 for st, s in rows if st == "text")
    many = iv.profile_rows(running(must=[f"req {i}" for i in range(11)], stack=[]))
    assert ("dim", "+3 more") in many and ("dim", "—") in many


def test_press_geometry():
    view = iv.InterviewView()
    strip = iv.strip_rect(HIST)
    m = running()
    assert view.press(center(iv.end_rect(strip)), strip, m) == "end"
    assert view.press(center(iv.chip_rect(strip)), strip, m) == "toggle" and view.panel_open
    assert view.press(center(iv.panel_rect(strip, m)), strip, m) == "inside" and view.panel_open
    assert view.press((HIST.x + 10, HIST.bottom - 10), strip, m) == "outside"
    assert not view.panel_open
    assert view.press(center(iv.retry_rect(strip)), strip, STATES["error"]) == "retry"
    assert view.press(center(iv.retry_rect(strip)), strip, STATES["error_no_job"]) == "inside"
    view.panel_open = True
    assert view.key("esc") and not view.panel_open and not view.key("esc")
    assert view.press(center(strip), strip, running(state="done")) == "none"


# ====================================================================== modelo

def test_model_keeps_interview_and_ignores_commands():
    clock = Clock()
    model = LearningModel(clock=clock)
    assert model.feed({"t": "lm_interview", "cmd": "end"}) == set()
    assert model.interview is None
    assert model.feed(running()) == {"interview"}
    assert model.interview["title"] == "Backend Engineer" and "t" not in model.interview
    assert model.interview_at == 100.0
    model.feed({"t": "lm_mode", "on": False})
    assert model.interview is None


def test_model_new_session_drops_interview():
    model = LearningModel(clock=Clock())
    model.feed({"t": "lm_session", "id": "LS-0001", "n_msgs": 3})
    model.feed(running())
    model.feed({"t": "lm_session", "id": "LS-0002", "n_msgs": 0})
    assert model.interview is None


# ====================================================================== tela

def screen_with(msg=None):
    clock = Clock()
    sc = LearningScreen(info=LearningModel(clock=clock))
    sent = []
    sc.send_lm = lambda t, f: sent.append((t, f)) or True
    sc.info.feed({"t": "lm_session", "id": "LS-0001", "n_msgs": 3, "topic": "interview"})
    if msg is not None:
        sc.info.feed(msg)
    return sc, clock, sent


def key(sc):
    return sc.group_key("interview", Snapshot(), NOW)


def render(sc) -> QImage:
    size = QSize(2560, 1440)
    img = QImage(size, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    sc.paint(p, size, Snapshot(), NOW)
    p.end()
    return img


def test_group_order_and_strip_over_history():
    sc, _, _ = screen_with(running())
    names = list(sc.groups())
    assert names.index("history") < names.index("interview") < names.index("topic")
    strip = sc._interview_strip()
    assert strip.top == sc.L.history.top and strip.w == sc.L.history.w


def test_end_and_retry_send_messages():
    sc, _, sent = screen_with(running())
    strip = sc._interview_strip()
    assert sc.mouse("press", center(iv.end_rect(strip))) is None
    assert sent == [("lm_interview", {"cmd": "end"})]
    sc.info.feed(STATES["error"])
    sc.mouse("press", center(iv.retry_rect(strip)))
    assert sent[-1] == ("lm_job", {"job_id": "JB-0001"})


def test_send_failure_logs():
    sc, _, _ = screen_with(running())
    sc.send_lm = lambda t, f: False
    sc.mouse("press", center(iv.end_rect(sc._interview_strip())))
    assert sc.info.log == "end not sent — not connected"


def test_chip_opens_panel_esc_and_click_outside_close():
    sc, _, _ = screen_with(running())
    strip = sc._interview_strip()
    k0 = key(sc)
    sc.mouse("press", center(iv.chip_rect(strip)))
    assert sc.interview_view.panel_open and key(sc) != k0
    panel = iv.panel_rect(strip, sc.info.interview)
    rects = sc.groups()["interview"]
    assert len(rects) == 2 and rects[1].top() == panel.top and rects[1].height() == panel.h
    assert sc.key("esc") and not sc.interview_view.panel_open
    sc.mouse("press", center(iv.chip_rect(strip)))
    sc.mouse("press", (panel.x + 5, panel.bottom + 30))
    assert not sc.interview_view.panel_open


def test_key_changes_with_clock_and_frame():
    sc, clock, _ = screen_with(running())
    k = key(sc)
    clock.t += 0.4
    assert key(sc) == k            # mesmo segundo
    clock.t += 1.0
    assert key(sc) != k            # 12:41
    assert sc.interview_deadline() is not None
    sc.info.feed(STATES["preparing"])
    k = key(sc)
    clock.t += 0.2
    assert key(sc) != k            # quadro da barra
    sc.info.feed(running(state="done"))
    assert key(sc) == (False,) and sc.interview_deadline() is None


def test_hidden_without_interview_and_click_passes_through():
    sc, _, sent = screen_with(None)
    assert key(sc) == (False,)
    strip = sc._interview_strip()
    sc.mouse("press", center(iv.end_rect(strip)))
    assert sent == []


@pytest.mark.parametrize("name", list(STATES))
def test_paints_every_state_offscreen(name, tmp_path):
    sc, clock, _ = screen_with(STATES[name])
    clock.t += 0.6
    sc.interview_view.panel_open = name in ("running", "ready")
    img = render(sc)
    s = 2560 / 1920
    strip = sc._interview_strip()
    lilac = QColor("#b392f0")
    x0 = round((strip.x + 0.5) * s)                 # traço lilás à esquerda do chip
    y = round((iv.chip_rect(strip).y + 10) * s)
    assert QColor(img.pixel(x0, y)).red() > 120 and QColor(img.pixel(x0, y)).blue() >= lilac.blue() - 60
    assert img.save(str(tmp_path / f"interview_{name}.png"))


def test_done_paints_nothing_over_history():
    sc, _, _ = screen_with(running(state="done"))
    img = render(sc)
    s = 2560 / 1920
    strip = sc._interview_strip()
    x0, y = round((strip.x + 0.5) * s), round((iv.chip_rect(strip).y + 10) * s)
    assert QColor(img.pixel(x0, y)) != QColor("#b392f0")
