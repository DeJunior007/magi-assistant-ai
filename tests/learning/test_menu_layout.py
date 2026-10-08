"""CA-11 (parte do menu): menu dentro da coluna central em 3440×1440 e 1920×1080, nunca cobre a
seleção nem sai da tela; vira para a esquerda/para cima na borda; balão ao lado sem cobrir."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from wired.learning_layout import (  # noqa: E402
    MENU_GAP,
    MENU_MIN_W,
    bubble_rect,
    menu_rect,
    menu_size,
)
from wired.learning_text import Rect, wrap  # noqa: E402


def frame(w_px: int, h_px: int) -> tuple[Rect, Rect]:
    """Tela e coluna central em coordenadas lógicas (escala = largura / 1920, como o HUD)."""
    scale = w_px / 1920
    screen = Rect(0, 0, 1920, h_px / scale)
    col_w = min(0.53 * 1920, 110 * 9.5)  # ≤ ~110 caracteres
    column = Rect((1920 - col_w) / 2, 90, col_w, screen.h - 90 - 140)
    return screen, column


SCREENS = {"3440x1440": frame(3440, 1440), "1920x1080": frame(1920, 1080)}


def word(column: Rect, fx: float, fy: float, w: float = 60, h: float = 30) -> Rect:
    x = column.left + fx * (column.w - w)
    y = column.top + fy * (column.h - h)
    return Rect(x, y, w, h)


POSITIONS = [(fx, fy) for fx in (0.0, 0.3, 0.7, 1.0) for fy in (0.0, 0.2, 0.5, 0.8, 1.0)]


@pytest.mark.parametrize("res", SCREENS)
@pytest.mark.parametrize("pos", POSITIONS)
@pytest.mark.parametrize("label_w", [80.0, 300.0, 520.0])
def test_menu_dentro_da_coluna_sem_cobrir(res, pos, label_w):
    screen, column = SCREENS[res]
    sel = [word(column, *pos)]
    m = menu_rect(sel, column, screen, label_w)
    assert column.contains_rect(m) and screen.contains_rect(m)
    assert not m.intersects(sel[0])
    assert m.w == max(MENU_MIN_W, label_w + 24)


@pytest.mark.parametrize("res", SCREENS)
def test_ancora_padrao_abaixo_da_ultima_palavra(res):
    screen, column = SCREENS[res]
    sel = [word(column, 0.1, 0.1), word(column, 0.2, 0.1)]
    m = menu_rect(sel, column, screen, 100)
    assert (m.left, m.top) == (sel[-1].left, sel[-1].bottom + MENU_GAP)


@pytest.mark.parametrize("res", SCREENS)
def test_vira_para_esquerda_e_para_cima(res):
    screen, column = SCREENS[res]
    last = word(column, 1.0, 1.0)
    m = menu_rect([last], column, screen, 100)
    assert m.right <= column.right and m.right == last.right  # alinhado pela direita
    assert m.bottom == last.top - MENU_GAP  # acima da seleção


@pytest.mark.parametrize("res", SCREENS)
def test_selecao_de_varias_linhas_perto_do_fim_sobe_acima_de_todas(res):
    screen, column = SCREENS[res]
    w = wrap([type("M", (), {"id": 1, "text": "word " * 60})()], column.w, lambda s: 9.5 * len(s),
             x=column.left, y=column.bottom - 4 * 30)
    sel = [b.rect for b in w.boxes if b.rect.bottom <= column.bottom][-30:]
    m = menu_rect(sel, column, screen, 200)
    assert column.contains_rect(m)
    assert not any(m.intersects(r) for r in sel)


def test_selecao_maior_que_a_coluna_fica_dentro():
    screen, column = SCREENS["1920x1080"]
    sel = [Rect(column.left, column.top + 10, column.w, column.h - 20)]
    m = menu_rect(sel, column, screen, 100)
    assert column.contains_rect(m)


def test_largura_cortada_em_coluna_estreita():
    screen = Rect(0, 0, 1920, 1080)
    column = Rect(100, 100, 200, 800)
    m = menu_rect([Rect(150, 300, 40, 30)], column, screen, 400)
    assert m.w == 200 and column.contains_rect(m)


def test_menu_size():
    assert menu_size(10)[0] == MENU_MIN_W
    assert menu_size(400)[0] == 424
    assert menu_size(10, 4)[1] > menu_size(10, 3)[1]


def test_menu_sem_selecao_falha():
    with pytest.raises(ValueError):
        menu_rect([], *reversed(SCREENS["1920x1080"]), 10)


@pytest.mark.parametrize("res", SCREENS)
@pytest.mark.parametrize("pos", POSITIONS)
def test_balao_na_tela_sem_cobrir_selecao_nem_menu(res, pos):
    screen, column = SCREENS[res]
    sel = [word(column, *pos)]
    m = menu_rect(sel, column, screen, 200)
    b = bubble_rect(m, sel, screen, (420, 220), column)
    assert screen.contains_rect(b)
    assert not b.intersects(sel[0]) and not b.intersects(m)


def test_balao_pode_passar_da_coluna_para_a_direita():
    screen, column = SCREENS["3440x1440"]
    sel = [word(column, 1.0, 0.3)]
    m = menu_rect(sel, column, screen, 100)
    b = bubble_rect(m, sel, screen, (400, 200))  # sem `column`: o lado direito vem primeiro
    assert screen.contains_rect(b)
    assert b.left >= m.right  # ao lado do menu, sobre a borda da coluna direita
    assert b.right > column.right
