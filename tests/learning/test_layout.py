"""LM1.5: layout da tela learning (puro) — CA-26 (retrato = MASCOT_MAIN), RNF-06 (≤ ~110
caracteres na coluna central) e a parte de layout do CA-11 (colunas dentro da tela, sem
sobreposição, em 1920×1080, 2560×1440 e 3440×1440)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MAGI_PORTRAIT_DIR", "/nonexistent/magi-portrait")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from wired.learning_layout import (  # noqa: E402
    CHAR_W,
    MAX_CHARS,
    PANEL_PAD,
    PORTRAIT_SIZE,
    column_widths,
    menu_rect,
    screen_layout,
)
from wired.learning_text import Rect  # noqa: E402

# (largura, altura) em pixels; o quadro lógico tem largura 1920 (escala do HUD)
RESOLUTIONS = [(1920, 1080), (2560, 1440), (3440, 1440)]


def logical(w_px: int, h_px: int) -> tuple[float, float]:
    return 1920.0, h_px / (w_px / 1920)


def test_ca26_retrato_do_tamanho_do_painel_gamer():
    from PySide6.QtWidgets import QApplication  # noqa: F401 - MASCOT_MAIN é QRectF puro
    from wired.main_screen import MASCOT_MAIN

    size = MASCOT_MAIN.size()
    assert size.height() == 302
    assert PORTRAIT_SIZE == pytest.approx((size.width(), size.height()))
    lay = screen_layout(1920, 1080, (size.width(), size.height()))
    assert (lay.portrait.w, lay.portrait.h) == (size.width(), size.height())
    assert lay.right.w >= size.width() + 2 * PANEL_PAD
    assert lay.right.contains_rect(lay.portrait)
    assert lay.condessa.contains_rect(lay.portrait)


def test_ca26_retrato_na_learning_screen():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from wired.learning_screen import LearningScreen
    from wired.main_screen import MASCOT_MAIN

    scr = LearningScreen()
    assert scr.MASCOT_RECT.size() == MASCOT_MAIN.size()


def test_retrato_nunca_encolhe_centro_cede():
    pw = 600.0  # retrato largo: a direita cresce, o centro cede
    left, center, right = column_widths(1920, pw)
    assert right == pytest.approx(pw + 2 * PANEL_PAD)
    lay = screen_layout(1920, 1080, (pw, 302))
    assert lay.portrait.w == pw
    assert lay.center.w == pytest.approx(center)


@pytest.mark.parametrize("res", RESOLUTIONS)
def test_colunas_dentro_da_tela_sem_sobrepor(res):
    w, h = logical(*res)
    lay = screen_layout(w, h, PORTRAIT_SIZE)
    for name in ("left", "center", "right", "header", "footer", "history", "input", "entry",
                 "session", "topic", "end_btn", "clock", "condessa", "state", "level"):
        r = getattr(lay, name)
        assert lay.screen.contains_rect(r), name
    assert lay.left.right <= lay.center.left
    assert lay.center.right <= lay.right.left
    assert not lay.left.intersects(lay.center)
    assert not lay.center.intersects(lay.right)
    assert lay.header.bottom <= lay.center.top
    assert lay.center.bottom <= lay.footer.top
    # dentro da conversa: sessão, histórico e entrada empilhados
    for name in ("session", "history", "input"):
        assert lay.center.contains_rect(getattr(lay, name)), name
    assert lay.session.bottom <= lay.history.top
    assert lay.history.bottom <= lay.input.top
    assert lay.input.contains_rect(lay.entry)
    assert lay.session.contains_rect(lay.topic)
    # coluna direita: retrato, estado, nível e observações sem sobrepor
    assert lay.portrait.bottom <= lay.state.top <= lay.state.bottom <= lay.level.top
    assert lay.condessa.bottom <= lay.obs.top
    # o botão END SESSION não encosta no relógio nem no canto
    assert lay.end_btn.right <= lay.clock.left
    assert lay.history.h > 200


@pytest.mark.parametrize("res", RESOLUTIONS)
def test_rnf06_coluna_central_ate_110_caracteres(res):
    lay = screen_layout(*logical(*res), PORTRAIT_SIZE)
    assert lay.text_chars <= MAX_CHARS + 1e-6
    assert lay.history.w / CHAR_W > 80  # e não fica estreita demais


def test_rnf06_largura_sobrando_vai_para_as_laterais():
    lay = screen_layout(3440, 1440, PORTRAIT_SIZE)  # quadro lógico largo (escala 1)
    assert lay.text_chars == pytest.approx(MAX_CHARS)
    mid = lay.center.left + lay.center.w / 2
    assert abs(mid - 3440 / 2) < 60  # centralizada (o retrato só desloca um pouco)


@pytest.mark.parametrize("res", RESOLUTIONS)
def test_ca11_menu_fica_na_coluna_central(res):
    lay = screen_layout(*logical(*res), PORTRAIT_SIZE)
    col = lay.history
    for sel in ([Rect(col.left + 10, col.top + 10, 60, 20)],
                [Rect(col.right - 50, col.bottom - 22, 50, 20)]):
        m = menu_rect(sel, col, lay.screen, 140)
        assert col.contains_rect(m)
        assert not any(m.intersects(s) for s in sel)
