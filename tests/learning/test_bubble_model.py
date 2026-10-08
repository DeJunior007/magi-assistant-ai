"""LM2.2: lógica pura do menu e do balão (``learning_overlay``) — formatação por ``kind``, itens
do menu, teclado, correlação do resultado, "more ▸", erro com retry e o provedor falso, tudo sem
importar PySide6."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hud"))

from wired.learning_overlay import (  # noqa: E402
    CLOSED,
    ERROR,
    LOADING,
    MENU,
    MOCK_EXPLAIN,
    MOCK_IMPROVE,
    MOCK_TRANSLATE,
    MOCK_VOCAB,
    OK,
    FakeProvider,
    Overlay,
    bubble_lines,
    format_result,
    item_at,
    item_rect,
    layout_bubble,
    title_line,
    wrap_text,
)
from wired.learning_text import ActionKind, Rect, Selection  # noqa: E402

TEXT = "It was pretty good. Yesterday I make a new authentication system for my project."


def sel(word: str, mid: int = 2, text: str = TEXT) -> Selection:
    s = text.index(word)
    return Selection(message_id=mid, start=s, end=s + len(word), text=word)


def texts(lines) -> list[str]:
    return [ln.text for ln in lines if ln.style != "gap"]


class Later:
    """Provedor que não responde na hora (como o real do LM3.4)."""

    def __init__(self):
        self.sent = []

    def submit(self, action, text):
        self.sent.append(action)
        return None


# ---------------------------------------------------------------- formatação por kind


def test_improve_como_no_mockup():
    lines = format_result(ActionKind.IMPROVE, MOCK_IMPROVE)
    assert texts(lines) == ["YOUR SENTENCE:", "yesterday I make a new", "MORE NATURAL:",
                            "yesterday I built a new", "WHY?", MOCK_IMPROVE["why"]]
    assert [ln.style for ln in lines if ln.text == "yesterday I built a new"] == ["strong"]
    t = title_line("improve", {"ok": True, "data": MOCK_IMPROVE})
    assert t.text == "IMPROVE // 改善" and t.tags == ("GRAMMAR", "NATURALNESS")


@pytest.mark.parametrize("kind,tags", [("grammar", ("GRAMMAR",)), ("naturalness", ("NATURALNESS",)),
                                       ("none", ("LOOKS GOOD",)), ("???", ())])
def test_etiquetas_do_improve(kind, tags):
    assert title_line("improve", {"ok": True, "data": {**MOCK_IMPROVE, "kind": kind}}).tags == tags
    assert title_line("improve").tags == ()  # carregando: sem etiqueta


def test_explain_translate():
    assert texts(format_result("explain", MOCK_EXPLAIN)) == [MOCK_EXPLAIN["question"],
                                                              MOCK_EXPLAIN["answer"]]
    lines = format_result("translate", MOCK_TRANSLATE, "I make")
    assert texts(lines) == ["SELECTED:", "I make", "TRANSLATION:", "eu faço (aqui: eu fiz)",
                            MOCK_TRANSLATE["note"]]
    no_note = format_result("translate", {"translation": "eu fiz", "note": None})
    assert texts(no_note) == ["TRANSLATION:", "eu fiz"]


def test_vocabulary_more():
    short = format_result("vocabulary", MOCK_VOCAB)
    assert texts(short) == ["authentication", "noun · B2", "the process of proving who a user is",
                            "IN CONTEXT:", "the login system you built", "more ▸"]
    assert short[-1].target == "more" and short[-1].style == "action"
    full = texts(format_result("vocabulary", MOCK_VOCAB, more=True))
    assert "· We added two-factor authentication." in full and "verification" in full
    assert full[-1] == "◂ less"
    bare = {**MOCK_VOCAB, "examples": [], "synonyms": []}
    assert "more ▸" not in texts(format_result("vocabulary", bare))


def test_bubble_lines_por_fase():
    assert bubble_lines(MENU, "improve") == [] and bubble_lines(CLOSED, "improve") == []
    load = bubble_lines(LOADING, "explain")
    assert texts(load) == ["EXPLAIN // 解説", "analyzing…"]
    err = bubble_lines(ERROR, "explain", {"ok": False, "error": "timeout"})
    assert texts(err) == ["EXPLAIN // 解説", "couldn't analyze — took too long", "[ retry ]"]
    assert err[-1].target == "retry"
    budget = bubble_lines(ERROR, "explain", {"ok": False, "error": "budget"})
    assert not any(ln.target == "retry" for ln in budget)  # repetir não adianta


# ---------------------------------------------------------------- quebra e geometria


def test_wrap_e_layout():
    m = lambda s: 10.0 * len(s)  # noqa: E731
    assert wrap_text("aa bb cc", 50, m) == ["aa bb", "cc"]
    assert wrap_text("abcdefghij x", 50, m) == ["abcdefghij", "x"]  # palavra longa não corta
    lines = bubble_lines(OK, "improve", {"ok": True, "data": MOCK_IMPROVE})
    rows, h = layout_bubble(lines, lambda st, s: 8.0 * len(s), width=300)
    assert rows[0].style == "title" and rows[0].tags
    ys = [r.rect.y for r in rows]
    assert ys == sorted(ys) and h > ys[-1]
    assert all(r.rect.right <= 300 for r in rows)
    assert sum(r.style == "text" for r in rows) > 2  # o WHY quebrou


def test_itens_do_menu_e_hit():
    menu = Rect(100, 200, 260, 30 + 4 * 28 + 6)
    assert item_rect(menu, 0).top == 230 and item_rect(menu, 3).bottom == 230 + 4 * 28
    assert item_at(menu, 4, (150, 235)) == 0 and item_at(menu, 4, (150, 320)) == 3
    assert item_at(menu, 4, (150, 210)) is None  # rótulo selected: "…"


# ---------------------------------------------------------------- Overlay


def test_menu_itens_por_autor():
    o = Overlay()
    o.open(sel("I make"), "you", TEXT)
    assert o.phase == MENU and o.label() == 'selected: "I make"'
    assert [(it.label, it.enabled) for it in o.items] == [
        ("Improve", True), ("Explain", True), ("Translate", True), ("Vocabulary", True)]
    o.open(sel("How was your day", 1, "How was your day today?"), "condessa")
    assert [it.enabled for it in o.items] == [False, True, True, True]  # P7
    long = "It was pretty good. Yesterday"
    o.open(sel(long), "you", TEXT)
    assert o.items[3].enabled is False  # Vocabulary: até 4 palavras


def test_improve_com_provedor_falso():
    fake = FakeProvider()
    o = Overlay(provider=fake)
    o.open(sel("I make"), "you", TEXT)
    act = o.choose("improve")
    assert act is not None and set(act) == {"id", "kind", "message_id", "start", "end"}
    assert act["kind"] == "improve" and (act["start"], act["end"]) == (30, 36)
    assert o.phase == OK and o.result["data"] == MOCK_IMPROVE
    assert texts(o.lines())[0] == "IMPROVE // 改善"
    assert fake.calls == [act]


def test_dados_do_mockup_por_kind():
    for kind, word, data in (("explain", "make", MOCK_EXPLAIN), ("translate", "I make", MOCK_TRANSLATE),
                             ("vocabulary", "authentication", MOCK_VOCAB)):
        o = Overlay()
        o.open(sel(word), "you", TEXT)
        o.choose(kind)
        assert o.phase == OK and o.result["data"] == data, kind


def test_erro_e_retry():
    fake = FakeProvider()
    o = Overlay(provider=fake)
    o.open(sel("pretty"), "you", TEXT)
    o.choose("explain")  # fora do mockup: erro "model"
    assert o.phase == ERROR and o.result["error"] == "model"
    first = o.action_id
    fake.fail = None
    assert o.retry() is not None and o.action_id != first and len(fake.calls) == 2
    fake.fail = "timeout"
    o.retry()
    assert o.phase == ERROR and "took too long" in texts(o.lines())[1]


def test_resultado_atrasado_correlacionado_por_id():
    p = Later()
    o = Overlay(provider=p)
    o.open(sel("make"), "you", TEXT)
    o.choose("explain")
    assert o.phase == LOADING and texts(o.lines())[-1] == "analyzing…"
    old = o.action_id
    o.choose("translate")  # trocou de ação: o resultado antigo não vale mais
    assert not o.on_result({"id": old, "ok": True, "data": MOCK_EXPLAIN})
    assert o.phase == LOADING
    assert o.on_result({"id": o.action_id, "ok": True, "data": MOCK_TRANSLATE})
    assert o.phase == OK and o.kind is ActionKind.TRANSLATE
    o.close()
    assert not o.on_result({"id": o.action_id, "ok": True, "data": {}})


def test_desabilitado_nao_envia():
    p = Later()
    o = Overlay(provider=p)
    o.open(sel("How", 1, "How was your day today?"), "condessa")
    assert o.choose("improve") is None and p.sent == [] and o.phase == MENU


def test_more_alterna_so_no_vocabulary():
    o = Overlay()
    o.open(sel("authentication"), "you", TEXT)
    o.choose("vocabulary")
    v = o.version
    assert o.target("more") and o.more and o.version > v
    assert "verification" in texts(o.lines())
    assert o.target("more") and not o.more
    o.open(sel("I make"), "you", TEXT)
    o.choose("improve")
    assert not o.toggle_more()


def test_teclado():
    o = Overlay()
    assert not o.key("down")  # fechado: não consome
    o.open(sel("How", 1, "How was your day today?"), "condessa")
    assert o.key("down") and o.hover == 1  # Improve desabilitado é pulado
    assert o.key("up") and o.hover == 3    # volta pelo fim
    assert o.key("down") and o.hover == 1
    assert o.key("enter") and o.phase == ERROR  # Explain em "How": fora do mockup
    assert o.key("enter") and o.phase == ERROR  # Enter no erro = retry
    assert o.key("esc") and o.phase == CLOSED
    assert not o.key("esc")
    o.open(sel("I make"), "you", TEXT)
    assert not o.key("enter")  # sem foco em item: não consome


def test_versao_muda_a_cada_mudanca_visivel():
    o = Overlay()
    seen = {o.state_key()}
    o.open(sel("I make"), "you", TEXT)
    seen.add(o.state_key())
    o.set_hover(2)
    seen.add(o.state_key())
    assert not o.set_hover(2)  # igual: sem repintura
    o.choose("improve")
    seen.add(o.state_key())
    o.close()
    seen.add(o.state_key())
    assert len(seen) == 5


def test_sem_pyside6():
    code = (f"import sys; sys.path.insert(0, {str(ROOT / 'hud')!r}); import wired.learning_overlay as o; "
            "x = o.Overlay(); "
            "assert not any(m.startswith('PySide6') for m in sys.modules), 'PySide6'")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
