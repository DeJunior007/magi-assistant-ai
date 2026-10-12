"""LI4.2 / CA-09 (HUD): linha "Roleplay ▸" com os cenários de ``lm_session.scenarios`` como
sublinhas; clique manda ``lm_topic {"topic":"roleplay","scenario"}`` (pelo ``on_scenario``); chip
``ROLEPLAY // <TITLE>``; captura offscreen da lista."""
from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from wired import learning_topic as tp
from wired.learning_text import Rect

CHIP = Rect(1200.0, 100.0, 400.0, 40.0)
COL = Rect(600.0, 80.0, 1000.0, 1200.0)
SCEN = [{"id": "doctor_visit", "title": "Doctor visit"},
        {"id": "hotel_checkin", "title": "Hotel check-in"},
        {"id": "ordering_food", "title": "Ordering food"},
        {"id": "support_call", "title": "Support call"}]
JOBS = [{"job_id": "JOB-aaaa0001", "title": "Backend", "company": "ACME"}]


def center(r: Rect) -> tuple[float, float]:
    return (r.x + r.w / 2, r.y + r.h / 2)


def picker(**session) -> tp.TopicPicker:
    p = tp.TopicPicker(clock=lambda: 0.0)
    p.sync({"id": "LS-1", "n_msgs": 0, **session}, None, now=0.0)
    return p


def test_cenarios_do_lm_session() -> None:
    p = picker(scenarios=[*SCEN, {"title": "sem id"}, "lixo"])
    assert [s.id for s in p.scenarios] == [s["id"] for s in SCEN]
    assert tp.scenarios_of({}) == () and tp.ITEMS[tp.ROLEPLAY].topic == "roleplay"


def test_clique_no_cenario_manda_lm_topic_com_scenario() -> None:
    for jobs in ([], JOBS):
        p = picker(scenarios=SCEN, jobs=jobs)
        sent: list[dict] = []
        p.on_scenario = lambda sid, sent=sent: sent.append(tp.scenario_payload(sid))
        lst = tp.list_rect(CHIP, COL, n_jobs=len(p.jobs))
        assert COL.contains_rect(lst)
        assert tp.scenario_rect(lst, 3).bottom <= lst.bottom
        assert tp.item_at(lst, center(tp.scenario_rect(lst, 1))) == tp.SCENARIO_ROW + 1
        assert p.press(center(tp.scenario_rect(lst, 1)), CHIP, lst) == ("inside", None)
        assert sent == [{"topic": "roleplay", "scenario": "hotel_checkin"}] and not p.is_open
        p.open()   # a linha Roleplay só agrupa: não manda nada nem fecha
        assert p.press(center(tp.row_rect(lst, tp.ROLEPLAY)), CHIP, lst) == ("inside", None)
        assert p.is_open and len(sent) == 1
        # as linhas antigas e as sublinhas da vaga continuam onde estavam
        assert p.press(center(tp.row_rect(lst, 3)), CHIP, lst) == ("choose", "news")
        assert tp.item_at(lst, center(tp.sub_rect(lst, 0))) == tp.PASTE_ROW


def test_sem_cenarios_clique_nao_manda() -> None:
    p = picker()
    sent: list[str] = []
    p.on_scenario = sent.append
    lst = tp.list_rect(CHIP, COL)
    assert p.press(center(tp.scenario_rect(lst, 0)), CHIP, lst) == ("inside", None)
    assert sent == [] and p.is_open


def test_chip_do_roleplay() -> None:
    msg = {"topic": "roleplay", "requested": "roleplay", "label": "ROLEPLAY // HOTEL CHECK-IN"}
    assert tp.chip_parts(msg) == ("ROLEPLAY // ", "HOTEL CHECK-IN", None)
    assert tp.chip_text(msg) == "ROLEPLAY // HOTEL CHECK-IN ▾"
    fb = {"topic": "free", "requested": "roleplay", "label": "FREE TALK", "detail": "unknown scenario"}
    assert tp.chip_text(fb) == "TOPIC // FREE TALK · unknown scenario ▾"
    assert tp.chip_text({}, {"topic": "roleplay"}) == "TOPIC // ROLEPLAY ▾"


def test_captura_offscreen_com_as_sublinhas(tmp_path) -> None:
    p = picker(scenarios=SCEN, jobs=JOBS)
    p.set_hover(tp.SCENARIO_ROW + 2)
    lst = tp.list_rect(Rect(1100, 10, 400, 40), Rect(0, 0, 1600, 900), n_jobs=1)
    img = QImage(1600, 900, QImage.Format.Format_ARGB32)
    img.fill(QColor("#000000"))
    qp = QPainter(img)
    tp.paint_list(qp, lst, p, "roleplay", {})
    tp.paint_chip(qp, Rect(1100, 10, 400, 40),
                  {"topic": "roleplay", "label": "ROLEPLAY // ORDERING FOOD"}, {}, True)
    qp.end()
    img.save(str(tmp_path / "roleplay_picker.png"))
    for k in range(4):
        r = tp.scenario_rect(lst, k)
        assert not img.copy(QRectF(r.x, r.y, r.w, r.h).toRect()).allGray(), k
    # sem cenários (núcleo antigo) também pinta
    qp = QPainter(img)
    tp.paint_list(qp, lst, picker(), "free", {})
    qp.end()
