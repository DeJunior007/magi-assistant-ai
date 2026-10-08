"""CA-10b: hit-test puro de ``learning_text`` com medidor falso (10 lógicos por caractere)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hud"))

from wired.learning_text import Rect, Selector, hit, normalize, sentence_span, wrap  # noqa: E402


@dataclass
class Msg:
    id: int
    text: str


def measure(s: str) -> float:
    return 10.0 * len(s)


M1 = Msg(1, "Yesterday I went to the market. I buyed some apples. Then I was cooking a pie.")
M2 = Msg(2, "Oh, nice. What kind of pie?")
COL = Rect(0, 0, 300, 400)


def layout():
    w = wrap([M1, M2], COL.w, measure, x=COL.x, y=COL.y, line_h=30, gap=12)
    sel = Selector(w.boxes, {1: M1.text, 2: M2.text}, bounds=COL)
    return w, sel


def center(w, mid: int, word: str, nth: int = 0):
    boxes = [b for b in w.boxes if b.message_id == mid
             and {1: M1, 2: M2}[mid].text[b.start:b.end].strip(".,?!") == word]
    r = boxes[nth].rect
    return (r.left + r.w / 2, r.top + r.h / 2)


def test_wrap_quebra_na_largura_e_caixas_batem_com_texto():
    w, _ = layout()
    for b in w.boxes:
        assert b.rect.right <= COL.right
        assert " " not in {1: M1, 2: M2}[b.message_id].text[b.start:b.end]
        assert b.rect.w == measure({1: M1, 2: M2}[b.message_id].text[b.start:b.end])
    assert len([ln for ln in w.lines if ln.message_id == 1]) > 1  # quebrou
    assert sum(ln.first for ln in w.lines) == 2
    # mensagem 2 começa depois do bloco 1 + gap
    assert w.blocks[2].top == w.blocks[1].bottom + 12
    assert w.height == w.blocks[2].bottom


def test_palavra_maior_que_a_linha_fica_sozinha():
    w = wrap([Msg(9, "a supercalifragilistic b")], 100, measure)
    assert [b.line for b in w.boxes] == [0, 1, 2]


def test_mensagem_vazia_ocupa_uma_linha():
    w = wrap([Msg(1, ""), Msg(2, "hi")], 200, measure, line_h=20, gap=0)
    assert w.boxes[0].rect.top == 20


def test_clique_na_palavra():
    w, sel = layout()
    s = sel.press(center(w, 1, "market"))
    assert s is not None and s.text == "market" and s.message_id == 1
    assert M1.text[s.start:s.end] == "market"


def test_clique_entre_palavras_e_fim_da_linha_pega_a_mais_proxima():
    w, sel = layout()
    b = next(b for b in w.boxes if M1.text[b.start:b.end] == "market.")
    assert sel.press((b.rect.right + 3, b.rect.top + 5)).text == "market"
    # fim da linha (à direita da última palavra)
    last = [x for x in w.lines[0].boxes][-1]
    s = sel.press((COL.right - 1, last.rect.top + 1))
    assert s.start == last.start


def test_clique_sem_texto_limpa():
    w, sel = layout()
    sel.press(center(w, 1, "market"))
    gap_y = w.blocks[1].bottom + 5
    assert sel.press((10, gap_y)) is None
    assert sel.selection is None
    assert hit(w.boxes, (10, 1000)) is None


def test_pontuacao_colada_aparada():
    w, sel = layout()
    assert sel.press(center(w, 1, "apples")).text == "apples"
    assert normalize(1, '  "hello," ', 0, 11).text == "hello"
    assert normalize(1, " .,! ", 0, 5) is None


def test_arrasto_estende_palavras_inteiras():
    w, sel = layout()
    sel.press(center(w, 1, "buyed"))
    r = next(b for b in w.boxes if M1.text[b.start:b.end] == "apples.").rect
    s = sel.move((r.left + 4, r.top + 5))  # meio da palavra
    assert s.text == "buyed some apples"


def test_arrasto_para_tras():
    w, sel = layout()
    sel.press(center(w, 1, "apples"))
    s = sel.move(center(w, 1, "buyed"))
    assert s.text == "buyed some apples"


def test_arrasto_atravessa_quebra_de_linha():
    w, sel = layout()
    a = next(b for b in w.boxes if M1.text[b.start:b.end] == "the")
    z = next(b for b in w.boxes if M1.text[b.start:b.end] == "some")
    assert a.line != z.line
    sel.press((a.rect.left + 1, a.rect.top + 1))
    s = sel.move((z.rect.left + 1, z.rect.top + 1))
    assert s.text == M1.text[a.start:z.end]
    assert len(sel.selected_boxes()) > 2


def test_arrasto_para_outra_mensagem_recorta_na_de_inicio():
    w, sel = layout()
    sel.press(center(w, 1, "Then"))
    s = sel.move(center(w, 2, "kind"))
    assert s.message_id == 1 and s.text == "Then I was cooking a pie"
    # para trás, em mensagem anterior: recorta no começo
    sel.press(center(w, 2, "kind"))
    s = sel.move(center(w, 1, "market"))
    assert s.message_id == 2 and s.text == "Oh, nice. What kind"


def test_arrasto_para_fora_da_coluna_para_na_ultima_palavra():
    w, sel = layout()
    sel.press(center(w, 1, "buyed"))
    sel.move(center(w, 1, "some"))
    s = sel.move((COL.right + 50, center(w, 1, "Then")[1]))
    assert s.text == "buyed some"


def test_move_sem_press_nao_seleciona():
    w, sel = layout()
    assert sel.move(center(w, 1, "market")) is None


def test_duplo_clique_seleciona_a_frase():
    w, sel = layout()
    s = sel.double(center(w, 1, "pie"))
    assert s.text == "Then I was cooking a pie"
    s = sel.double(center(w, 2, "Oh"))
    assert s.text == "Oh, nice"
    # press -> release -> double (ordem do Qt): o double troca a palavra pela frase
    sel.press(center(w, 1, "apples"))
    assert sel.double(center(w, 1, "apples")).text == "I buyed some apples"


def test_sentence_span_sem_ponto_final_e_numero():
    assert sentence_span("it costs 3.5 dollars", 13) == (0, 20)
    assert sentence_span("Hi! How are you", 5) == (3, 15)


def test_rolagem_entra_por_y_e_set_boxes_limpa():
    w, sel = layout()
    sel.press(center(w, 1, "market"))
    w2 = wrap([M1, M2], COL.w, measure, y=-30)
    sel.set_boxes(w2.boxes, COL)
    assert sel.selection is None
    assert w2.boxes[0].rect.top == -30


@pytest.mark.parametrize("mod", ["wired.learning_text", "wired.learning_layout"])
def test_sem_pyside6(mod):
    code = (f"import sys; sys.path.insert(0, {str(ROOT / 'hud')!r}); import {mod}; "
            "assert not any(m.startswith('PySide6') for m in sys.modules), 'PySide6'")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
