"""CA-10 (e parte de CA-09): seleção normalizada para palavras, recortada, menu com 4 ações,
Improve desabilitado em mensagem da Condessa (P7), Vocabulary só 1–4 palavras."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hud"))

from wired.learning_text import (  # noqa: E402
    Rect,
    Selector,
    can_open_menu,
    menu_items,
    menu_label,
    normalize,
    wrap,
)

from magi.learning.contracts import (  # noqa: E402
    ActionKind,
    Author,
    LearningMessage,
    Selection,
    Source,
)

AT = datetime(2026, 10, 7, 12, tzinfo=UTC)


def msg(i: int, author: Author, text: str) -> LearningMessage:
    return LearningMessage(id=i, session_id="s1", author=author, source=Source.TEXT, text=text,
                           at=AT)


YOU = msg(10, Author.YOU, "Yesterday I buyed some apples. I make a homemade apple pie!")
CON = msg(11, Author.CONDESSA, "Oh, nice. What kind of pie did you make?")


def selector():
    w = wrap([YOU, CON], 400, lambda s: 9.0 * len(s), indent=90)
    return w, Selector(w.boxes, {m.id: m.text for m in (YOU, CON)}, Rect(0, 0, 400, 600))


def word_point(w, m, word):
    b = next(b for b in w.boxes if b.message_id == m.id and m.text[b.start:b.end] == word)
    return (b.rect.left + 1, b.rect.top + 1)


def enabled(sel, author):
    return {i.kind: i.enabled for i in menu_items(sel, author)}


def test_selecao_eh_o_contrato_e_bate_com_a_mensagem():
    w, s = selector()
    sel = s.press(word_point(w, YOU, "apples."))
    assert isinstance(sel, Selection)
    assert sel.matches(YOU)
    assert sel.text == "apples"
    assert Selection.from_dict(sel.to_dict()) == sel


def test_arrasto_normalizado_e_recortado():
    w, s = selector()
    s.press(word_point(w, YOU, "homemade"))
    sel = s.move(word_point(w, CON, "kind"))
    assert sel.message_id == YOU.id
    assert sel.text == "homemade apple pie"  # "!" aparado
    assert sel.matches(YOU)


def test_so_pontuacao_nao_abre_menu():
    assert normalize(1, "-- ... !!", 0, 9) is None
    assert not can_open_menu(None)


def test_menu_tem_4_acoes_na_ordem():
    sel = Selection(message_id=10, start=0, end=9, text="Yesterday")
    items = menu_items(sel, Author.YOU)
    assert [i.kind for i in items] == [ActionKind.IMPROVE, ActionKind.EXPLAIN,
                                       ActionKind.TRANSLATE, ActionKind.VOCABULARY]
    assert [i.icon for i in items] == ["✦", "?", "⇄", "◇"]
    assert all(i.enabled for i in items)


def test_improve_desabilitado_na_condessa():
    w, s = selector()
    sel = s.press(word_point(w, CON, "kind"))
    e = enabled(sel, Author.CONDESSA)
    assert e == {ActionKind.IMPROVE: False, ActionKind.EXPLAIN: True,
                 ActionKind.TRANSLATE: True, ActionKind.VOCABULARY: True}
    assert enabled(sel, "condessa")[ActionKind.IMPROVE] is False  # autor vindo do fio
    assert enabled(sel, "you")[ActionKind.IMPROVE] is True


def test_vocabulary_ate_4_palavras():
    text = "one two three four five"
    four = Selection(message_id=1, start=0, end=18, text=text[:18])
    five = Selection(message_id=1, start=0, end=len(text), text=text)
    assert enabled(four, Author.YOU)[ActionKind.VOCABULARY] is True
    e5 = enabled(five, Author.YOU)
    assert e5[ActionKind.VOCABULARY] is False
    assert e5[ActionKind.IMPROVE] and e5[ActionKind.EXPLAIN] and e5[ActionKind.TRANSLATE]


def test_translate_ate_400_caracteres():
    ok = Selection(message_id=1, start=0, end=400, text="a" * 400)
    long = Selection(message_id=1, start=0, end=401, text="a" * 401)
    assert enabled(ok, Author.YOU)[ActionKind.TRANSLATE] is True
    assert enabled(long, Author.YOU)[ActionKind.TRANSLATE] is False


def test_frase_por_duplo_clique():
    w, s = selector()
    sel = s.double(word_point(w, YOU, "homemade"))
    assert sel.text == "I make a homemade apple pie"
    assert enabled(sel, Author.YOU)[ActionKind.VOCABULARY] is False


def test_mensagem_em_fala_nao_abre_menu():
    sel = Selection(message_id=11, start=0, end=2, text="Oh")
    assert can_open_menu(sel) and can_open_menu(sel, speaking_message_id=10)
    assert not can_open_menu(sel, speaking_message_id=11)


def test_rotulo_do_menu_truncado():
    sel = Selection(message_id=1, start=0, end=6, text="I make")
    assert menu_label(sel) == 'selected: "I make"'
    longo = Selection(message_id=1, start=0, end=60, text="x" * 60)
    lab = menu_label(longo, max_chars=20)
    assert lab.endswith('…"') and len(lab) == len('selected: ""') + 20


def test_sem_magi_usa_espelho_do_contrato():
    code = ("import sys; sys.modules['magi'] = None; "
            f"sys.path.insert(0, {str(ROOT / 'hud')!r}); "
            "from wired.learning_text import Selector, wrap, menu_items, Author; "
            "w = wrap([type('M', (), {'id': 1, 'text': 'I make pies.'})()], 300, len); "
            "s = Selector(w.boxes, {1: 'I make pies.'}).press((9.5, 1)); "
            "assert s.text == 'pies', s; "
            "assert [i.enabled for i in menu_items(s, 'condessa')] == [False, True, True, True]; "
            "assert s.to_dict() == {'message_id': 1, 'start': 7, 'end': 11, 'text': 'pies'}")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
