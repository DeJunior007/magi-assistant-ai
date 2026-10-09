"""Indicador e drawer de observações da tela learning (LM4.3, design §11, spec §9 itens 4–6).

``OBSERVATIONS [nn] ▾`` no topo do painel ``obs`` (coluna direita, abaixo do retrato), recolhido
por padrão; aberto, o próprio painel vira o drawer com três grupos — **VOCABULARY** (``+ deploy``),
**GRAMMAR** (``Past tense``) e **RECURRING** (``Prepositions``). Clicar num item rola o histórico
até a mensagem de origem e destaca a mensagem **uma vez** (``Flash``: some no próximo batimento
depois de ``FLASH_S``, sem animação contínua). O contador só troca o número (sem piscar). O botão
``[ VIEW LEARNING PROFILE ]`` é desabilitado ("coming later", PRN-003).

A parte de dados é pura (sem Qt): ``group``/``distinct_count``/``drawer_rows``/``scroll_to``/
``ObsView``. A pintura (``paint``) usa os mesmos retângulos de ``ObsView.layout`` do hit-test.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .learning_text import Point, Rect

SECTIONS: tuple[tuple[str, str], ...] = (
    ("vocabulary", "VOCABULARY"),
    ("grammar", "GRAMMAR"),
    ("recurring", "RECURRING"),
)
FLASH_S = 1.0          # duração do destaque do clique (uma vez; some no batimento seguinte)
HEAD_Y = 37            # linha de base do título "Observations" (igual ao ``draw_static``)
HEAD_H = 50            # faixa clicável do título (abre/fecha)
ROW_H = 20             # altura de cada linha do drawer
SECTION_GAP = 4        # respiro antes de cada título de grupo
PAD = 21               # margem interna do painel (igual ao ``draw_static``)
BTN_H = 44             # botão Learning Profile (embaixo do painel)
BTN_BOTTOM = 21


@dataclass(frozen=True)
class ObsEntry:
    """Um item do drawer: distinto por (``category``, ``label``); ``message_id`` é a ocorrência
    mais recente (para onde o clique rola) e ``n`` quantas vezes apareceu na lista."""

    category: str
    label: str
    message_id: int | None
    n: int = 1

    @property
    def text(self) -> str:
        return f"+ {self.label}" if self.category == "vocabulary" else self.label


def _get(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def group(items: Iterable[Any]) -> dict[str, list[ObsEntry]]:
    """Agrupa a lista inteira do ``lm_obs`` (dicts ou ``Observation``) por categoria, distinta por
    (``category``, ``label``) na ordem da primeira aparição. Categorias desconhecidas e itens sem
    ``label`` são ignorados. Sempre devolve as três chaves de ``SECTIONS``."""
    out: dict[str, dict[str, ObsEntry]] = {cat: {} for cat, _ in SECTIONS}
    for it in items:
        cat = str(_get(it, "category") or "").lower()
        lab = str(_get(it, "label") or "").strip()
        if cat not in out or not lab:
            continue
        mid = _get(it, "message_id")
        mid = int(mid) if mid is not None else None
        cur = out[cat].get(lab.casefold())
        if cur is None:
            out[cat][lab.casefold()] = ObsEntry(cat, lab, mid, 1)
        else:
            out[cat][lab.casefold()] = ObsEntry(cat, cur.label, mid if mid is not None else
                                                cur.message_id, cur.n + 1)
    return {cat: list(d.values()) for cat, d in out.items()}


def distinct_count(groups: dict[str, list[ObsEntry]]) -> int:
    return sum(len(v) for v in groups.values())


def counter_text(n: int, is_open: bool) -> str:
    """``[03] ▾`` recolhido, ``[03] ▴`` aberto (dois dígitos no mínimo)."""
    return f"[{max(0, int(n)):02d}] {'▴' if is_open else '▾'}"


@dataclass(frozen=True)
class DrawerRow:
    kind: str                  # "section" | "item" | "empty"
    text: str
    entry: ObsEntry | None = None


def drawer_rows(groups: dict[str, list[ObsEntry]]) -> list[DrawerRow]:
    """Linhas do drawer: título de cada grupo não vazio seguido dos seus itens."""
    rows: list[DrawerRow] = []
    for cat, title in SECTIONS:
        entries = groups.get(cat) or []
        if not entries:
            continue
        rows.append(DrawerRow("section", title))
        rows.extend(DrawerRow("item", e.text, e) for e in entries)
    if not rows:
        rows.append(DrawerRow("empty", "no observations yet"))
    return rows


def scroll_to(msg_top: float, msg_bottom: float, content_h: float, view_h: float) -> float:
    """``scroll`` (px a partir do fim, como o ``LearningModel``) que centraliza a mensagem
    [``msg_top``, ``msg_bottom``) (coordenadas do conteúdo, y = 0 no topo) numa janela de
    ``view_h``; limitado a [0, ``content_h − view_h``]."""
    max_scroll = max(0.0, content_h - view_h)
    want = content_h - msg_top - (view_h + (msg_bottom - msg_top)) / 2
    if msg_bottom - msg_top > view_h:  # maior que a janela: mostra o começo
        want = content_h - msg_top - view_h
    return max(0.0, min(max_scroll, want))


@dataclass
class Flash:
    """Destaque de uma mensagem por ``FLASH_S`` segundos (uma vez, sem repetição)."""

    message_id: int | None = None
    until: float = 0.0

    def start(self, message_id: int, now: float | None = None) -> None:
        self.message_id = message_id
        self.until = (time.monotonic() if now is None else now) + FLASH_S

    def active(self, now: float | None = None) -> int | None:
        if self.message_id is None:
            return None
        if (time.monotonic() if now is None else now) >= self.until:
            self.message_id = None
            return None
        return self.message_id


@dataclass
class ObsView:
    """Estado do grupo ``obs``: aberto/fechado, destaque, e a geometria do painel."""

    is_open: bool = False
    flash: Flash = field(default_factory=Flash)

    @staticmethod
    def head_rect(panel: Rect) -> Rect:
        return Rect(panel.left, panel.top, panel.w, min(panel.h, HEAD_H))

    @staticmethod
    def button_rect(panel: Rect) -> Rect:
        return Rect(panel.left + PAD, panel.bottom - BTN_BOTTOM - BTN_H, panel.w - 2 * PAD, BTN_H)

    def layout(self, panel: Rect, groups: dict[str, list[ObsEntry]]) -> list[tuple[Rect, DrawerRow]]:
        """Linhas visíveis do drawer com seus retângulos (vazio se recolhido). O que não cabe
        acima do botão é cortado, com ``…`` na última linha."""
        if not self.is_open:
            return []
        btn = self.button_rect(panel)
        limit = btn.top - 22 if btn.top > panel.top + 50 else panel.bottom - 8
        y = panel.top + HEAD_H
        x, w = panel.left + PAD, panel.w - 2 * PAD
        out: list[tuple[Rect, DrawerRow]] = []
        rows = drawer_rows(groups)
        for i, row in enumerate(rows):
            if row.kind == "section" and i > 0:
                y += SECTION_GAP
            if y + ROW_H > limit:
                if out:
                    out[-1] = (out[-1][0], DrawerRow("more", "…"))
                break
            out.append((Rect(x, y, w, ROW_H), row))
            y += ROW_H
        return out

    def press(self, point: Point, panel: Rect,
              groups: dict[str, list[ObsEntry]]) -> tuple[str, ObsEntry | None] | None:
        """Clique no painel: ``("toggle", None)`` no título, ``("item", entry)`` num item,
        ``("profile", None)`` no botão desabilitado; ``None`` fora de tudo."""
        if not panel.contains(point):
            return None
        if self.head_rect(panel).contains(point):
            self.is_open = not self.is_open
            return ("toggle", None)
        btn = self.button_rect(panel)
        if btn.top > panel.top + 50 and btn.contains(point):
            return ("profile", None)
        for r, row in self.layout(panel, groups):
            if row.kind == "item" and r.contains(point):
                return ("item", row.entry)
        return None

    def key(self, n: int, groups: dict[str, list[ObsEntry]]) -> tuple:
        rows = tuple((r.kind, r.text) for r in drawer_rows(groups)) if self.is_open else ()
        return (n, self.is_open, rows)


# ---------------------------------------------------------------- pintura (Qt)

def paint(p, panel: Rect, view: ObsView, n: int, groups: dict[str, list[ObsEntry]]) -> None:
    """Pinta o contador e, aberto, o drawer e o aviso do botão (o painel, o título e a moldura
    do botão ficam no ``draw_static`` da tela)."""
    from .main_screen import R, label, text
    from .theme import CPU, TEXT, TEXT_DIM

    x1 = panel.right - PAD
    text(p, x1, panel.top + HEAD_Y, counter_text(n, view.is_open), key="mono", px=14,
         color_=CPU if n else TEXT_DIM, align=R)
    for r, row in view.layout(panel, groups):
        base = r.top + ROW_H - 5
        if row.kind == "section":
            label(p, r.left, base, row.text, px=11)
        elif row.kind == "item":
            text(p, r.left + 8, base, row.text, key="mono", px=13, color_=TEXT, max_w=r.w - 8)
        else:
            label(p, r.left, base, row.text, px=11, upper=False)
    btn = view.button_rect(panel)
    if btn.top > panel.top + 50:
        label(p, btn.right - 8, btn.top - 6, "coming later", px=10, upper=False, align=R)
