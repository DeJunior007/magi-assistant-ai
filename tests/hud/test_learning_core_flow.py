"""LI2.5: integração tela ↔ núcleo com núcleo falso — as linhas do socket passam pelo decodificador
real do ``HudBridge`` (``feed_line``) até o ``LearningModel`` e a tela: vaga → ``ready`` →
``[ END INTERVIEW ]`` → painel do retorno; prazo da faixa no ``caption_tick``; vagas recentes no
seletor; ``[ YES ] [ NO ]`` clicáveis da colagem longa."""

from __future__ import annotations

import json

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from wired import learning_interview as iv
from wired import learning_topic as tp

from . import test_learning_job_paste as jp
from .test_learning_debrief_view import debrief
from .test_learning_job_paste import JOB, JOBS

hud = jp.hud   # fixture do HUD offscreen com clipboard e send_lm falsos (LI2.1)

SESSION = {"t": "lm_session", "id": "LS-0001", "started_at": "2026-10-12T10:00:00",
           "topic": "interview", "jobs": JOBS[:2]}
PROFILE = {"job_id": "JOB-aaaa0001", "run_id": "IV-20261012-36001", "title": "Backend Engineer",
           "company": "Acme", "seniority": "senior", "stack": ["Python", "FastAPI"],
           "must": ["5+ years of Python"], "minutes": 30}


def feed(w, msg: dict) -> None:
    w.bridge.feed_line(json.dumps(msg))


def center(r) -> tuple[float, float]:
    return (r.x + r.w / 2, r.y + r.h / 2)


def start(w) -> None:
    w.learning_model.set_connected(True)
    w.wired.learning.send_lm = w.bridge.send_lm   # o send_lm falso da fixture (o HUD liga no __init__)
    feed(w, {"t": "lm_mode", "on": True})
    feed(w, SESSION)
    w.learning_entry_sync()


def test_vaga_ready_end_painel_do_retorno(hud):
    start(hud)
    scr = hud.wired.learning
    assert hud.learning_paste_job()
    assert hud.sent == [("lm_job", {"text": JOB.strip(), "source": "clipboard"})]
    # o núcleo prepara: a faixa aparece e o caption_tick agenda a barra (~5 q/s)
    feed(hud, {"t": "lm_interview", "state": "preparing", "job_id": "JOB-aaaa0001"})
    assert hud.learning_model.interview["state"] == "preparing"
    assert scr.interview_deadline() is not None
    assert hud.caption_timer.isActive()
    feed(hud, {"t": "lm_interview", "state": "ready", **PROFILE})
    feed(hud, {"t": "lm_interview", "state": "running", "stage": 1, "n_stages": 6,
               "stage_label": "WARM-UP", "asked": 0, "quota": 2, "elapsed_s": 0, **PROFILE})
    assert hud.learning_model.interview["state"] == "running"
    # [ END INTERVIEW ] na faixa manda o comando ao núcleo
    scr.mouse("press", center(iv.end_rect(scr._interview_strip())))
    assert hud.sent[-1] == ("lm_interview", {"cmd": "end"})
    feed(hud, {"t": "lm_interview", "state": "debriefing", **PROFILE})
    assert not scr.debrief_view.is_open
    feed(hud, debrief(run_id=PROFILE["run_id"]))
    assert hud.learning_model.debrief["run_id"] == PROFILE["run_id"]
    assert len(hud.learning_model.debrief["scores"]) == 5
    feed(hud, {"t": "lm_interview", "state": "done", **PROFILE})
    hud.resize(1920, 1080)
    hud.grab()   # pinta: o painel abre sozinho no retorno novo
    assert scr.debrief_view.is_open
    for _ in range(3):   # Esc fecha primeiro o que estiver por cima (a lista de temas da sessão nova)
        if not scr.debrief_view.is_open:
            break
        assert scr.key("esc")
    assert not scr.debrief_view.is_open


def test_eco_do_comando_nao_muda_a_faixa(hud):
    start(hud)
    feed(hud, {"t": "lm_interview", "state": "running", "stage": 1, "n_stages": 6, **PROFILE})
    feed(hud, {"t": "lm_interview", "cmd": "end"})
    assert hud.learning_model.interview["state"] == "running"


def test_vagas_recentes_aparecem_no_seletor(hud):
    start(hud)
    scr = hud.wired.learning
    hud.resize(1920, 1080)
    hud.grab()   # a pintura sincroniza o seletor com o lm_session (abre sozinho em sessão nova)
    if not scr.topic_picker.is_open:
        scr.topic_picker.open()
    assert len(scr.topic_picker.jobs) == 2
    assert tp.n_subs(scr._topic_list()) == 3   # [ PASTE JOB ] + 2 vagas


def key(w, k, mod=Qt.KeyboardModifier.NoModifier):
    return w.eventFilter(w.lm_entry, QKeyEvent(QEvent.Type.KeyPress, k, mod, ""))


def test_colagem_longa_yes_e_no_clicaveis(hud):
    start(hud)
    scr = hud.wired.learning
    assert scr.paste_buttons() == {}
    assert key(hud, Qt.Key_V, Qt.KeyboardModifier.ControlModifier)
    btn = scr.paste_buttons()
    assert set(btn) == {"yes", "no"} and btn["yes"].right() < btn["no"].left()
    c = btn["no"].center()
    scr.mouse("press", (c.x(), c.y()))
    assert not hud.lm_paste_ask and hud.sent == [] and hud.learning_model.log is None
    assert key(hud, Qt.Key_V, Qt.KeyboardModifier.ControlModifier)
    c = scr.paste_buttons()["yes"].center()
    scr.mouse("press", (c.x(), c.y()))
    assert not hud.lm_paste_ask
    assert hud.sent == [("lm_job", {"text": JOB.strip(), "source": "clipboard"})]
