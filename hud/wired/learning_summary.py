"""Cartão ``LAST SESSION`` do Learning Mode no painel e na espera (LM4.6, LM-011, design §4.6).

Puro (sem Qt) até ``paint_card``: linhas do cartão a partir do ``SessionSummary`` que chega no
``lm_summary`` (dict, como veio do núcleo), o ``+N`` do que não coube, a ★ nas palavras salvas e a
validade (``SummaryCard.visible``): o cartão aparece só fora do modo, para um ``lm_summary`` que
chegou até ``LATE_S`` depois do ``lm_mode off`` visto por este HUD, e some em ``show_s``, ao ser
clicado ou ao ``lm_mode on``. Não guarda nada em disco: reiniciar o ``gamerhud`` não reexibe.

Sem nota, pontuação, streak ou comparação com outras sessões (PDF §12, requirements LM-011).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

SHOW_S = 60.0      # [learning] summary_show_s
LATE_S = 10.0      # lm_summary chegado mais de 10 s depois do lm_mode off é descartado (spec §10.2)
SEP = " · "
STAR = " ★"
LABEL_PRACTISED = "PRACTISED"
LABEL_WORDS = "NEW WORDS"
TOPIC_LABELS = {"free": "FREE TALK", "interview": "TECH INTERVIEW", "game": "GAME", "news": "NEWS"}


# ====================================================================== texto (puro)

def header(s: Mapping[str, Any]) -> str:
    return f"LAST SESSION // {int(s.get('n') or 0):02d}"


def topics_label(topics: Sequence[str] | None) -> str:
    seen: list[str] = []
    for t in topics or ():
        lab = TOPIC_LABELS.get(str(t), str(t).upper())
        if lab not in seen:
            seen.append(lab)
    return " / ".join(seen) or TOPIC_LABELS["free"]


def stats(s: Mapping[str, Any]) -> str:
    """``24 MIN · 38 MSGS · 6 OBS · FREE TALK``."""
    minutes = max(1, round(int(s.get("duration_s") or 0) / 60))
    return SEP.join((f"{minutes} MIN", f"{int(s.get('n_msgs') or 0)} MSGS",
                     f"{int(s.get('obs_count') or 0)} OBS", topics_label(s.get("topics"))))


def practised(s: Mapping[str, Any]) -> tuple[list[str], int]:
    return [str(x) for x in s.get("practiced") or ()], int(s.get("more_practiced") or 0)


def words(s: Mapping[str, Any]) -> tuple[list[str], int]:
    """Palavras novas com ★ nas salvas nesta sessão, e quantas ficaram de fora no núcleo."""
    saved = {str(w).casefold() for w in s.get("saved") or ()}
    out = [str(w) + (STAR if str(w).casefold() in saved else "") for w in s.get("new_words") or ()]
    return out, int(s.get("more_words") or 0)


def fit(items: Sequence[str], more: int, width: float, measure: Callable[[str], float]) -> str:
    """Junta ``items`` com `` · `` até caber em ``width``; o que não coube soma ao ``more`` e vira
    ``  +N`` no fim. Sem itens: ``—``."""
    if not items:
        return f"—  +{more}" if more else "—"
    for k in range(len(items), -1, -1):
        rest = more + len(items) - k
        txt = SEP.join(items[:k]) + (f"  +{rest}" if rest else "")
        if k == 0 or measure(txt) <= width:
            return txt.strip()
    return ""  # inalcançável


def card_lines(s: Mapping[str, Any], width: float = 1e9,
               measure: Callable[[str], float] = len, label_w: float = 0.0) -> list[tuple[str, str]]:
    """As 4 linhas do cartão como ``(rótulo, texto)`` (rótulo vazio nas duas primeiras)."""
    p_items, p_more = practised(s)
    w_items, w_more = words(s)
    room = width - label_w
    return [("", header(s)), ("", stats(s)),
            (LABEL_PRACTISED, fit(p_items, p_more, room, measure)),
            (LABEL_WORDS, fit(w_items, w_more, room, measure))]


# ====================================================================== validade (relógio falso)

@dataclass
class SummaryCard:
    """Estado do cartão no HUD. ``summary``/``at`` vêm do ``learning_model`` (``summary``,
    ``summary_at``); ``off_at`` é o instante (mesmo relógio) do último ``lm_mode off``."""

    show_s: float = SHOW_S
    late_s: float = LATE_S
    off_at: float | None = None
    closed_at: float | None = None   # ``summary_at`` do cartão fechado por clique

    def mode(self, on: bool, now: float) -> None:
        self.off_at = None if on else now
        if on:
            self.closed_at = None

    def visible(self, summary: Mapping[str, Any] | None, at: float | None, now: float,
                mode_on: bool = False) -> bool:
        if summary is None or at is None or mode_on or self.off_at is None:
            return False
        if not 0.0 <= at - self.off_at <= self.late_s:
            return False  # atrasado (> 10 s do off) ou de antes do off deste HUD
        if self.closed_at == at:
            return False
        return now - at < self.show_s

    def deadline(self, at: float | None) -> float | None:
        return None if at is None else at + self.show_s

    def close(self, at: float | None) -> None:
        self.closed_at = at

    # -- atalhos sobre o learning_model (objeto com summary, summary_at, mode_on)
    def current(self, model: Any, now: float) -> dict[str, Any] | None:
        s, at = getattr(model, "summary", None), getattr(model, "summary_at", None)
        return s if self.visible(s, at, now, bool(getattr(model, "mode_on", False))) else None


def card_key(s: Mapping[str, Any] | None) -> tuple:
    """Chave do grupo: muda só ao aparecer/sumir (ou outro resumo)."""
    if s is None:
        return (None,)
    return (s.get("session_id"), s.get("n"), s.get("ended_at"))


# ====================================================================== pintura

def paint_card(p, rect, s: Mapping[str, Any], *, px: float = 11.0, line_h: float | None = None,
               pad: float = 10.0) -> None:
    """Desenha o cartão em ``rect`` (coordenadas lógicas do painter): fundo opaco, borda fina
    ``TEXT_DIM``, texto ``TEXT_DIM``/``TEXT``; sem brilho nem animação."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QFontMetricsF, QPen

    from .fonts import font
    from .theme import BG, TEXT, TEXT_DIM, color

    lh = line_h or px * 1.55
    f = font("mono", px)
    fm = QFontMetricsF(f)
    er = Qt.TextElideMode.ElideRight
    r = QRectF(rect)
    p.save()
    p.fillRect(r, color(BG))
    pen = QPen(color(TEXT_DIM))
    pen.setWidthF(1.0)
    p.setPen(pen)
    p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
    p.setFont(f)
    x, inner = r.left() + pad, r.width() - 2 * pad
    label_w = max(fm.horizontalAdvance(LABEL_PRACTISED), fm.horizontalAdvance(LABEL_WORDS)) + px
    lines = card_lines(s, inner, fm.horizontalAdvance, label_w)
    y = r.top() + pad + fm.ascent()
    for i, (lab, txt) in enumerate(lines):
        if lab:
            p.setPen(color(TEXT_DIM))
            p.drawText(QPointF(x, y), lab)
            p.setPen(color(TEXT))
            p.drawText(QPointF(x + label_w, y), fm.elidedText(txt, er, inner - label_w))
        else:
            p.setPen(color(TEXT if i == 0 else TEXT_DIM))
            p.drawText(QPointF(x, y), fm.elidedText(txt, er, inner - (2 * px if i == 0 else 0)))
            if i == 0:
                p.setPen(color(TEXT_DIM))
                p.drawText(QPointF(r.right() - pad - fm.horizontalAdvance("×"), y), "×")
        y += lh
    p.restore()


def card_height(px: float = 11.0, line_h: float | None = None, pad: float = 10.0) -> float:
    return 2 * pad + 4 * (line_h or px * 1.55)


__all__ = ["LATE_S", "SHOW_S", "SummaryCard", "card_height", "card_key", "card_lines", "fit",
           "header", "paint_card", "stats", "topics_label", "words"]
