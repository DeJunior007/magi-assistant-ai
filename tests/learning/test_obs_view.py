"""LM4.3: agrupamento/contagem das observações (puro) e o grupo ``obs`` da ``LearningScreen``
(abre/fecha, clique no item rola até a mensagem e destaca uma vez, botão desabilitado)."""

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

from wired import learning_obs as obsv  # noqa: E402
from wired.learning_screen import LearningScreen  # noqa: E402
from wired.main_screen import Snapshot  # noqa: E402

NOW = datetime(2026, 10, 7, 17, 42, 10)


def ob(cat, label, mid, rule="x"):
    return {"id": None, "session_id": "LS-0001", "message_id": mid, "category": cat,
            "rule_key": rule, "label": label, "span": None, "suggestion": None}


ITEMS = [
    ob("vocabulary", "repository", 2),
    ob("vocabulary", "deploy", 2),
    ob("grammar", "Past tense", 4, "grammar.past_simple.irregular"),
    ob("grammar", "Prepositions", 4, "grammar.prepositions.in_on"),
    ob("vocabulary", "assistant", 6),
    ob("grammar", "Prepositions", 6, "grammar.prepositions.at"),
    ob("recurring", "Prepositions", 6, "grammar.prepositions"),
]


# ---------------------------------------------------------------- puro

def test_agrupa_por_categoria_distinto_por_rotulo():
    g = obsv.group(ITEMS)
    assert [e.text for e in g["vocabulary"]] == ["+ repository", "+ deploy", "+ assistant"]
    assert [e.text for e in g["grammar"]] == ["Past tense", "Prepositions"]
    assert [e.text for e in g["recurring"]] == ["Prepositions"]
    prep = g["grammar"][1]
    assert prep.n == 2 and prep.message_id == 6  # ocorrência mais recente
    assert obsv.distinct_count(g) == 6


def test_ignora_lixo_e_aceita_objetos():
    class Obj:
        category, label, message_id = "grammar", "Articles", 9

    g = obsv.group([ob("style", "x", 1), ob("grammar", "  ", 1), Obj()])
    assert [e.label for e in g["grammar"]] == ["Articles"]
    assert set(g) == {"vocabulary", "grammar", "recurring"}
    assert obsv.distinct_count(obsv.group([])) == 0


def test_contador_e_linhas():
    assert obsv.counter_text(3, False) == "[03] ▾"
    assert obsv.counter_text(12, True) == "[12] ▴"
    rows = obsv.drawer_rows(obsv.group(ITEMS))
    assert [r.text for r in rows if r.kind == "section"] == ["VOCABULARY", "GRAMMAR", "RECURRING"]
    assert obsv.drawer_rows(obsv.group([]))[0].kind == "empty"
    only_gram = obsv.drawer_rows(obsv.group([ob("grammar", "Past tense", 1)]))
    assert [r.text for r in only_gram] == ["GRAMMAR", "Past tense"]


def test_scroll_to_centraliza_e_limita():
    # conteúdo 1000, janela 400: scroll 0 mostra [600, 1000)
    assert obsv.scroll_to(900, 930, 1000, 400) == 0.0          # já no fim
    assert obsv.scroll_to(0, 30, 1000, 400) == 600.0           # limitado ao topo
    s = obsv.scroll_to(500, 530, 1000, 400)
    top_on_screen = 500 - (1000 - 400 - s)                     # y da mensagem na janela
    assert abs(top_on_screen - (400 - 30) / 2) < 1e-6
    assert obsv.scroll_to(0, 30, 300, 400) == 0.0              # tudo cabe


def test_flash_uma_vez():
    f = obsv.Flash()
    assert f.active(0.0) is None
    f.start(7, now=10.0)
    assert f.active(10.5) == 7
    assert f.active(10.0 + obsv.FLASH_S) is None
    assert f.active(10.2) is None  # não volta


def test_obsview_recolhido_e_clique():
    panel = obsv.Rect(0, 0, 400, 500)
    v = obsv.ObsView()
    g = obsv.group(ITEMS)
    assert v.layout(panel, g) == []
    assert v.press((10, 10), panel, g) == ("toggle", None) and v.is_open
    rows = v.layout(panel, g)
    item = next((r, row) for r, row in rows if row.kind == "item" and row.text == "Past tense")
    c = (item[0].left + 5, item[0].top + 5)
    assert v.press(c, panel, g) == ("item", g["grammar"][0])
    btn = v.button_rect(panel)
    assert v.press((btn.left + 5, btn.top + 5), panel, g) == ("profile", None)
    assert v.press((-5, -5), panel, g) is None


def test_obsview_corta_o_que_nao_cabe():
    panel = obsv.Rect(0, 0, 400, 200)
    v = obsv.ObsView(is_open=True)
    rows = v.layout(panel, obsv.group(ITEMS))
    assert rows and rows[-1][1].kind == "more"
    assert all(r.bottom <= v.button_rect(panel).top for r, _ in rows)


# ---------------------------------------------------------------- tela

def _screen_with_msgs(n=40) -> LearningScreen:
    scr = LearningScreen()
    scr.info.feed({"t": "lm_mode", "on": True, "session_id": "LS-0001"})
    for i in range(1, n + 1):
        scr.info.feed({"t": "lm_msg", "id": i, "author": "you" if i % 2 else "condessa",
                       "text": f"message number {i} about the repository and the deploy"})
    return scr


def _center(r):
    return (r.left + r.w / 2, r.top + r.h / 2)


def test_tela_contador_e_drawer_mudam_a_chave_do_obs():
    scr = _screen_with_msgs(3)
    sn = Snapshot()
    k0 = {g: scr.group_key(g, sn, NOW) for g in ("obs", "history", "footer")}
    scr.info.feed({"t": "lm_obs", "items": ITEMS, "count": 3})
    assert scr.obs_count() == 3
    assert scr.group_key("obs", sn, NOW) != k0["obs"]
    assert scr.group_key("history", sn, NOW) == k0["history"]
    k1 = scr.group_key("obs", sn, NOW)
    scr.info.feed({"t": "lm_obs", "items": ITEMS, "count": 3})  # idempotente
    assert scr.group_key("obs", sn, NOW) == k1
    head = obsv.ObsView.head_rect(scr.L.obs)
    assert scr.mouse("press", _center(head)) is None and scr.obs_view.is_open
    assert scr.group_key("obs", sn, NOW) != k1
    scr.mouse("press", _center(head))
    assert not scr.obs_view.is_open
    btn = obsv.ObsView.button_rect(scr.L.obs)
    scr.mouse("press", _center(btn))
    assert "coming later" in (scr.info.log or "")


def test_sem_count_conta_distintos():
    scr = _screen_with_msgs(1)
    scr.info.obs_items = ITEMS
    scr.info.obs_count = 0
    assert scr.obs_count() == 6


def test_clique_no_item_rola_e_destaca_uma_vez():
    scr = _screen_with_msgs(40)
    assert scr.max_scroll() > 0
    scr.info.feed({"t": "lm_obs", "items": [ob("grammar", "Past tense", 3)], "count": 1})
    scr.obs_view.is_open = True
    rows = scr.obs_view.layout(scr.L.obs, scr.obs_groups())
    r = next(r for r, row in rows if row.kind == "item")
    hk = scr.group_key("history", Snapshot(), NOW)
    scr.mouse("press", _center(r))
    assert scr.info.scroll > 0
    assert scr.obs_view.flash.active() == 3
    assert scr.group_key("history", Snapshot(), NOW) != hk
    boxes = [b for b in scr.history_boxes() if b.message_id == 3]
    assert boxes and all(scr.L.history.contains((b.rect.x, b.rect.y + 1)) for b in boxes)
    assert scr._message_rects(3)
    scr.obs_view.flash.until = 0.0  # passou o FLASH_S
    assert scr.obs_view.flash.active() is None
    assert not scr.scroll_to_message(999)


def test_pinta_dados_fixos_offscreen(tmp_path):
    scr = _screen_with_msgs(8)
    scr.info.feed({"t": "lm_obs", "items": ITEMS, "count": 3})
    scr.obs_view.is_open = True
    img = QImage(QSize(2560, 1440), QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    scr.paint(p, QSize(2560, 1440), Snapshot(magui_state="sleeping"), NOW, mono=0.0)
    p.end()
    out = os.environ.get("LM_OBS_CAPTURE")
    if out:
        img.save(out)
    assert not img.isNull()
