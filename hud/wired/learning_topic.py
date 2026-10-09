"""Seletor de tema da sessão (LM1.9, LM-013, design §4.5): chip ``TOPIC // FREE TALK ▾`` no
cabeçalho da sessão e lista curta de 4 itens ancorada nele (grupo ``topic`` da ``LearningScreen``).

Parte pura (sem Qt): ``TopicPicker`` (aberto/fechado, item sob o mouse, timeout, abre sozinho só
em sessão nova), ``chip_parts`` (o chip mostra só o tema **confirmado** pelo núcleo, com o
``detail`` do fallback) e ``list_rect``/``item_at`` (geometria). A pintura (``paint_chip``,
``paint_list``) importa o Qt só por dentro.

Regras (spec §10.1, §11): em sessão nova (``lm_session`` com ``n_msgs == 0``) a lista abre
sozinha; em retomada, não. Fecha ao escolher, ao clicar fora, em ``topic_picker_s`` (10 s), em Esc
ou quando chega mensagem do Pedro (fala ou texto). Escolher manda ``lm_topic {"topic"}``; o chip só
muda com a confirmação (``lm_topic`` do núcleo no ``LearningModel``). Sem escolha = Free talk
(nada é enviado). O chip reabre a lista a qualquer momento.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .learning_text import Point, Rect

PICKER_S = 10.0          # [learning] topic_picker_s (o núcleo pode mandar no lm_session)
LIST_W = 320.0           # largura na base 1920 (design §4.5)
LIST_W_HINT = 480.0      # com dica à direita das linhas Game/News
LIST_GAP = 4.0           # entre o chip e a lista
HEAD_H = 28.0            # linha "TOPIC ▾"
ROW_H = 28.0
PAD = 12.0


@dataclass(frozen=True, slots=True)
class TopicItem:
    topic: str
    text: str


ITEMS: tuple[TopicItem, ...] = (
    TopicItem("free", "Free talk"),
    TopicItem("interview", "Tech interview"),
    TopicItem("game", "Talk about the game I'm playing"),
    TopicItem("news", "Today's news"),
)

LABELS = {  # = contracts.TOPIC_LABELS do núcleo (o HUD não importa magi.learning)
    "free": "FREE TALK",
    "interview": "TECH INTERVIEW",
    "game": "THE GAME I'M PLAYING",
    "news": "TODAY'S NEWS",
}


# ====================================================================== tema confirmado

def confirmed(topic_msg: Mapping[str, Any] | None, session: Mapping[str, Any] | None = None) -> str:
    """Tema confirmado pelo núcleo: o último ``lm_topic``; sem ele, o do ``lm_session``; senão
    ``free``."""
    for src in (topic_msg or {}, session or {}):
        t = src.get("topic")
        if t in LABELS:
            return str(t)
    return "free"


def chip_parts(topic_msg: Mapping[str, Any] | None,
               session: Mapping[str, Any] | None = None) -> tuple[str, str, str | None]:
    """``("TOPIC // ", rótulo, detail)`` do chip. ``detail`` (fallback do núcleo, ex.
    ``"no game detected"``) só vem do ``lm_topic``."""
    msg = topic_msg or {}
    topic = confirmed(msg, session)
    lbl = str(msg.get("label") or "") if msg.get("topic") == topic else ""
    detail = msg.get("detail") or None
    return ("TOPIC // ", (lbl or LABELS[topic]).upper(), str(detail) if detail else None)


def chip_text(topic_msg: Mapping[str, Any] | None, session: Mapping[str, Any] | None = None) -> str:
    head, lbl, detail = chip_parts(topic_msg, session)
    return f"{head}{lbl}{f' · {detail}' if detail else ''} ▾"


def hints(session: Mapping[str, Any] | None) -> dict[str, str]:
    """Dicas opcionais das linhas Game/News (``lm_session.topic_hints``; sem elas, sem dica)."""
    raw = (session or {}).get("topic_hints") or {}
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): str(v) for k, v in raw.items() if v}


# ====================================================================== geometria

def list_rect(chip: Rect, bounds: Rect, with_hints: bool = False) -> Rect:
    """Lista ancorada embaixo do chip, alinhada à direita dele e dentro de ``bounds`` (a coluna
    da conversa)."""
    w = min(LIST_W_HINT if with_hints else LIST_W, bounds.w)
    h = HEAD_H + ROW_H * len(ITEMS) + PAD / 2
    x = max(bounds.left, min(chip.right - w, bounds.right - w))
    return Rect(x, chip.bottom + LIST_GAP, w, h)


def row_rect(lst: Rect, idx: int) -> Rect:
    return Rect(lst.x, lst.y + HEAD_H + ROW_H * idx, lst.w, ROW_H)


def item_at(lst: Rect, point: Point) -> int | None:
    for i in range(len(ITEMS)):
        if row_rect(lst, i).contains(point):
            return i
    return None


# ====================================================================== estado

@dataclass
class TopicPicker:
    """Aberto/fechado, item sob o mouse e prazo. ``sync`` é chamado a cada consulta da tela
    (chave do grupo, mouse): abre em sessão nova, fecha no timeout e em mensagem do Pedro."""

    timeout_s: float = PICKER_S
    clock: Callable[[], float] = field(default=time.monotonic, repr=False, compare=False)
    is_open: bool = False
    hover: int | None = None
    opened_at: float | None = None
    auto: bool = False                 # aberta sozinha (sessão nova)
    _session_id: str | None = None
    _you_mark: int | None = None       # última mensagem do Pedro quando abriu

    def open(self, last_you: int | None = None, auto: bool = False, now: float | None = None) -> None:
        self.is_open = True
        self.auto = auto
        self.hover = None
        self.opened_at = self.clock() if now is None else now
        self._you_mark = last_you

    def close(self) -> None:
        self.is_open = False
        self.auto = False
        self.hover = None
        self.opened_at = None

    def toggle(self, last_you: int | None = None) -> None:
        if self.is_open:
            self.close()
        else:
            self.open(last_you)

    def deadline(self) -> float | None:
        """Instante (no ``clock``) em que a lista fecha sozinha, ou ``None``."""
        if not self.is_open or self.opened_at is None:
            return None
        return self.opened_at + self.timeout_s

    def sync(self, session: Mapping[str, Any] | None, last_you: int | None,
             now: float | None = None) -> bool:
        """Aplica sessão nova/retomada, timeout e mensagem do Pedro. ``True`` = mudou."""
        now = self.clock() if now is None else now
        before = (self.is_open, self.hover)
        session = session or {}
        sid = session.get("id")
        if sid is not None and str(sid) != self._session_id:
            self._session_id = str(sid)
            if session.get("picker_s"):
                self.timeout_s = float(session["picker_s"])
            if int(session.get("n_msgs") or 0) == 0:
                self.open(last_you, auto=True, now=now)   # sessão nova
            else:
                self.close()                              # retomada: só mostra o tema
        if self.is_open:
            dl = self.deadline()
            if dl is not None and now >= dl:
                self.close()
            elif last_you is not None and last_you != self._you_mark:
                self.close()                              # o Pedro falou ou digitou
        return before != (self.is_open, self.hover)

    def set_hover(self, idx: int | None) -> bool:
        idx = idx if self.is_open else None
        changed = idx != self.hover
        self.hover = idx
        return changed

    def key(self, name: str) -> bool:
        """Esc fecha (consumida). As outras teclas não são do seletor."""
        if self.is_open and name == "esc":
            self.close()
            return True
        return False

    def press(self, point: Point, chip: Rect, lst: Rect | None,
              last_you: int | None = None) -> tuple[str, str | None]:
        """Clique: ``("choose", tema)`` num item, ``("toggle", None)`` no chip, ``("inside",
        None)`` no resto da lista, ``("outside", None)`` fora (fecha), ``("none", None)`` com a
        lista fechada fora do chip."""
        if chip.contains(point):
            self.toggle(last_you)
            return ("toggle", None)
        if not self.is_open:
            return ("none", None)
        if lst is not None and lst.contains(point):
            idx = item_at(lst, point)
            if idx is None:
                return ("inside", None)
            self.close()
            return ("choose", ITEMS[idx].topic)
        self.close()
        return ("outside", None)

    def state_key(self) -> tuple:
        return (self.is_open, self.hover)


def last_you(messages: Sequence[Any]) -> int | None:
    """Id da última mensagem do Pedro (``author == "you"``) no histórico, ou ``None``."""
    for m in reversed(messages):
        if getattr(m, "author", None) == "you":
            return int(m.id)
    return None


# ====================================================================== pintura (Qt)

def paint_chip(p, chip: Rect, topic_msg: Mapping[str, Any] | None,
               session: Mapping[str, Any] | None, is_open: bool) -> None:
    """``TOPIC // FREE TALK · no game detected ▾`` alinhado à direita do chip, na linha de base
    do cabeçalho da sessão; o ``detail`` em ``TEXT_DIM``."""
    from .main_screen import R, label
    from .theme import CPU, TEXT, TEXT_DIM

    head, lbl, detail = chip_parts(topic_msg, session)
    y = chip.top + 30
    x = chip.right
    parts = [("▴" if is_open else "▾", CPU)]
    if detail:
        parts.append((f" · {detail}", TEXT_DIM))
    parts += [(lbl, TEXT), (head, TEXT_DIM)]
    for i, (s, col) in enumerate(parts):
        r = label(p, x, y, s if i else " " + s, px=13, color_=col, align=R, upper=False,
                  max_w=max(0.0, x - chip.left))
        x -= r.width()
        if x <= chip.left:
            break


def paint_list(p, lst: Rect, picker: TopicPicker, current: str,
               hint: Mapping[str, str] | None = None) -> None:
    """Lista ``TOPIC ▾`` com ● no tema confirmado, ○ nos outros, fundo lilás translúcido no
    item sob o mouse e a dica (opcional) à direita das linhas Game/News."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPen

    from .main_screen import R, label, text
    from .theme import CPU, LINE_STRONG, PANEL, TEXT, TEXT_DIM, color

    box = QRectF(lst.x, lst.y, lst.w, lst.h)
    p.save()
    p.fillRect(box, color(PANEL))
    p.setPen(QPen(color(LINE_STRONG), 1))
    p.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5))
    p.restore()
    label(p, lst.left + PAD, lst.top + HEAD_H - 9, "TOPIC ▾", px=11)
    hint = hint or {}
    for i, item in enumerate(ITEMS):
        r = row_rect(lst, i)
        if picker.hover == i:
            hl = color(CPU)
            hl.setAlpha(46)
            p.fillRect(QRectF(r.x + 1, r.y, r.w - 2, r.h), hl)
        base = r.top + ROW_H - 9
        on = item.topic == current
        text(p, r.left + PAD, base, "●" if on else "○", px=12, color_=CPU if on else TEXT_DIM)
        tip = hint.get(item.topic)
        tip_w = 0.0
        if tip:
            tip_w = label(p, r.right - PAD, base, tip, px=11, upper=False, align=R,
                          max_w=r.w / 2 - PAD).width() + 12
        text(p, r.left + PAD + 20, base, item.text, px=13, color_=TEXT,
             max_w=max(0.0, r.w - 2 * PAD - 20 - tip_w))
