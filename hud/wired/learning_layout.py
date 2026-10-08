"""Geometria pura da tela learning (sem Qt). LM2.1: só a posição do menu e do balão.

O LM1.5 acrescenta aqui as colunas, o topo, o rodapé e a entrada.

- ``menu_size(label_w, n_items)``: largura saída da medida do rótulo ``selected: "…"``, com
  mínimo de ``MENU_MIN_W`` lógicos (nota do LM0.3: 220 fixo cortava o rótulo).
- ``menu_rect``: ancorado no fim da seleção (esquerda da última palavra, base + 4); vira para a
  esquerda/para cima quando passaria da coluna; nunca cobre a seleção nem sai da tela (SEL-002).
- ``bubble_rect``: ao lado do menu; pode sobrepor a borda entre a conversa e a coluna direita,
  mas não sai da tela nem cobre a seleção ou o menu (design §4).
"""

from __future__ import annotations

from collections.abc import Sequence

from .learning_text import Rect

MENU_MIN_W = 260.0
MENU_PAD = 12.0      # margem interna horizontal
MENU_HEAD_H = 30.0   # linha do rótulo selected: "…"
MENU_ITEM_H = 28.0
MENU_GAP = 4.0       # distância entre a seleção e o menu (LM0.3)
BUBBLE_GAP = 8.0


def menu_size(label_w: float, n_items: int = 4) -> tuple[float, float]:
    """(largura, altura) do menu a partir da largura medida do rótulo."""
    w = max(MENU_MIN_W, label_w + 2 * MENU_PAD)
    h = MENU_HEAD_H + n_items * MENU_ITEM_H + MENU_PAD / 2
    return w, h


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if hi < lo else min(max(v, lo), hi)


def _bounds(column: Rect, screen: Rect) -> Rect:
    left, top = max(column.left, screen.left), max(column.top, screen.top)
    right, bottom = min(column.right, screen.right), min(column.bottom, screen.bottom)
    return Rect(left, top, max(0.0, right - left), max(0.0, bottom - top))


def _free(r: Rect, avoid: Sequence[Rect]) -> bool:
    return not any(r.intersects(a) for a in avoid)


def menu_rect(selection: Sequence[Rect], column: Rect, screen: Rect, label_w: float,
              n_items: int = 4) -> Rect:
    """Retângulo do menu para a seleção ``selection`` (caixas das palavras, em ordem).

    Preferência: abaixo da última palavra, alinhado à esquerda dela; se passa da direita da
    coluna, alinha pela direita; se passa de baixo, vai para cima da seleção. Sempre dentro de
    ``column ∩ screen`` (largura cortada se a coluna for mais estreita).
    """
    if not selection:
        raise ValueError("menu_rect sem seleção")
    area = _bounds(column, screen)
    w, h = menu_size(label_w, n_items)
    w = min(w, area.w)
    h = min(h, area.h)
    last = selection[-1]
    top_sel = min(r.top for r in selection)
    bottom_sel = max(r.bottom for r in selection)
    xs = (last.left, last.right - w)
    ys = (last.bottom + MENU_GAP, top_sel - MENU_GAP - h)
    candidates = []
    for y in ys:
        for x in xs:
            cx = _clamp(x, area.left, area.right - w)
            candidates.append(Rect(cx, y, w, h))
    for r in candidates:
        if area.contains_rect(r) and _free(r, selection):
            return r
    # Seleção maior que a coluna: o lado com mais espaço, encostado nela.
    below = area.bottom - bottom_sel
    above = top_sel - area.top
    x = _clamp(last.left, area.left, area.right - w)
    y = bottom_sel + MENU_GAP if below >= above else top_sel - MENU_GAP - h
    return Rect(x, _clamp(y, area.top, area.bottom - h), w, h)


def bubble_rect(menu: Rect, selection: Sequence[Rect], screen: Rect, size: tuple[float, float],
                column: Rect | None = None) -> Rect:
    """Retângulo do balão de resultado (``size`` = largura, altura desejadas).

    Ordem: à direita do menu (pode passar da coluna para a coluna direita), à esquerda do
    menu, abaixo do menu, acima do menu. Sem cobrir a seleção nem o menu; dentro da tela.
    ``column`` (opcional) só desempata: o lado que fica mais dentro dela vence.
    """
    w = min(size[0], screen.w)
    h = min(size[1], screen.h)
    avoid = [*selection, menu]
    top = _clamp(menu.top, screen.top, screen.bottom - h)
    side = [Rect(menu.right + BUBBLE_GAP, top, w, h), Rect(menu.left - BUBBLE_GAP - w, top, w, h)]
    if column is not None:
        side.sort(key=lambda r: -_overlap_w(r, column))
    xc = _clamp(menu.left, screen.left, screen.right - w)
    candidates = [*side, Rect(xc, menu.bottom + BUBBLE_GAP, w, h),
                  Rect(xc, menu.top - BUBBLE_GAP - h, w, h)]
    for r in candidates:
        if screen.contains_rect(r) and _free(r, avoid):
            return r
    # Sem lugar livre: o primeiro candidato empurrado para dentro da tela.
    r = candidates[0]
    return Rect(_clamp(r.x, screen.left, screen.right - w), _clamp(r.y, screen.top,
                screen.bottom - h), w, h)


def _overlap_w(r: Rect, c: Rect) -> float:
    return max(0.0, min(r.right, c.right) - max(r.left, c.left))
