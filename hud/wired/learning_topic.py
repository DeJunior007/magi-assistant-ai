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
LIST_W = 360.0           # largura na base 1920 (design §4.5)
LIST_W_HINT = 480.0      # com dica à direita das linhas Game/News
LIST_GAP = 4.0           # entre o chip e a lista
HEAD_H = 36.0            # cabeçalho "TOPIC // 話題"
ROW_H = 48.0             # título + linha de descrição
PAD = 12.0


@dataclass(frozen=True, slots=True)
class TopicItem:
    topic: str
    text: str


ITEMS: tuple[TopicItem, ...] = (
    TopicItem("free", "Free talk"),
    TopicItem("interview", "Tech interview"),
    TopicItem("game", "The game I'm playing"),
    TopicItem("news", "Today's news"),
)

DESC = {  # linha curta sob cada tema (a dica do núcleo, se houver, entra no lugar em Game/News)
    "free": "open conversation, any subject",
    "interview": "mock interview: questions and follow-ups",
    "game": "whatever is running right now",
    "news": "headlines of the day, in English",
}

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

CHIP_H = 26.0            # caixa do chip no cabeçalho da sessão
CHIP_PAD = 10.0


def description(topic: str, hint: Mapping[str, str] | None = None) -> str:
    """Linha de descrição do tema: a dica do núcleo (ex. nome do jogo) quando houver."""
    tip = (hint or {}).get(topic)
    if tip and topic == "game":
        return f"playing: {tip}"
    return tip or DESC.get(topic, "")


def paint_glyph(p, topic: str, cx: float, cy: float, col, s: float = 8.0) -> None:
    """Glifo em traço de cada tema (mesmo traço dos ícones do menu da seleção): balão de fala
    (Free talk), ``</>`` (Tech interview), controle (Game) e folha com linhas (News)."""
    from PySide6.QtCore import QPointF as P
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QPainter, QPen

    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(col, 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if topic == "free":
        p.drawRoundedRect(QRectF(cx - s, cy - s * 0.8, 2 * s, s * 1.3), 2.5, 2.5)
        p.drawLine(P(cx - s * 0.45, cy + s * 0.5), P(cx - s * 0.7, cy + s))
        p.drawLine(P(cx - s * 0.7, cy + s), P(cx - s * 0.05, cy + s * 0.5))
    elif topic == "interview":
        p.drawLine(P(cx - s * 0.45, cy - s * 0.55), P(cx - s, cy))
        p.drawLine(P(cx - s, cy), P(cx - s * 0.45, cy + s * 0.55))
        p.drawLine(P(cx + s * 0.45, cy - s * 0.55), P(cx + s, cy))
        p.drawLine(P(cx + s, cy), P(cx + s * 0.45, cy + s * 0.55))
        p.drawLine(P(cx + s * 0.2, cy - s * 0.75), P(cx - s * 0.2, cy + s * 0.75))
    elif topic == "game":
        p.drawRoundedRect(QRectF(cx - s, cy - s * 0.6, 2 * s, s * 1.2), s * 0.5, s * 0.5)
        p.drawLine(P(cx - s * 0.65, cy), P(cx - s * 0.15, cy))
        p.drawLine(P(cx - s * 0.4, cy - s * 0.25), P(cx - s * 0.4, cy + s * 0.25))
        p.drawPoint(P(cx + s * 0.35, cy - s * 0.12))
        p.drawPoint(P(cx + s * 0.6, cy + s * 0.15))
    else:
        p.drawRect(QRectF(cx - s * 0.75, cy - s, s * 1.5, 2 * s))
        for k in (-0.45, 0.0, 0.45):
            p.drawLine(P(cx - s * 0.4, cy + s * k), P(cx + s * (0.15 if k > 0 else 0.4), cy + s * k))
    p.restore()


def paint_chip(p, chip: Rect, topic_msg: Mapping[str, Any] | None,
               session: Mapping[str, Any] | None, is_open: bool) -> None:
    """Chip ``TOPIC // FREE TALK · no game detected ▾`` alinhado à direita, numa caixa de traço
    fino (lilás e com fundo fraco quando a lista está aberta); o ``detail`` em ``TEXT_DIM``."""
    from PySide6.QtCore import QRectF

    from .main_screen import R, label, width
    from .theme import CPU, LINE_STRONG, TEXT, TEXT_DIM, alpha, color

    head, lbl, detail = chip_parts(topic_msg, session)
    y = chip.top + 30
    parts = [("▴" if is_open else "▾", CPU)]
    if detail:
        parts.append((f" · {detail}", TEXT_DIM))
    parts += [(lbl, TEXT), (head, TEXT_DIM)]
    total = sum(width((s if i else " " + s), "mono", 13, None, 0.08) + 2  # + espaçamento final
                for i, (s, _) in enumerate(parts))
    right = chip.right - 1
    left = max(chip.left, right - total - 2 * CHIP_PAD)
    box = QRectF(left, y - CHIP_H / 2 - 5, right - left, CHIP_H)
    p.save()
    if is_open:
        p.fillRect(box, alpha(CPU, 22))
    border = color(CPU) if is_open else color(LINE_STRONG)
    p.fillRect(QRectF(box.left(), box.top(), box.width(), 1), border)
    p.fillRect(QRectF(box.left(), box.bottom() - 1, box.width(), 1), border)
    p.fillRect(QRectF(box.left(), box.top(), 1, box.height()), border)
    p.fillRect(QRectF(box.right() - 1, box.top(), 1, box.height()), border)
    p.fillRect(QRectF(box.left(), box.top(), 2, box.height()), color(CPU))  # traço lilás à esquerda
    p.restore()
    x = right - CHIP_PAD
    for i, (s, col) in enumerate(parts):
        r = label(p, x, y, s if i else " " + s, px=13, color_=col, align=R, upper=False,
                  max_w=max(0.0, x - chip.left))
        x -= r.width()
        if x <= chip.left:
            break


def paint_list(p, lst: Rect, picker: TopicPicker, current: str,
               hint: Mapping[str, str] | None = None) -> None:
    """Lista no estilo dos cards do HUD: painel chanfrado com traço lilás, cabeçalho
    ``TOPIC // 話題`` + ``ESC``, e cada tema com glifo, título e uma linha de descrição (a dica do
    núcleo em Game/News). Tema atual: traço lilás à esquerda, título lilás e etiqueta ``CURRENT``;
    item sob o mouse: fundo lilás fraco."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPen

    from . import kit
    from .main_screen import R, label, text, width
    from .theme import CPU, LINE, LINE_STRONG, PANEL, TEXT, TEXT_DIM, alpha, color

    kit.panel(p, QRectF(lst.x, lst.y, lst.w, lst.h), fill=PANEL, border=LINE_STRONG, accent=CPU)
    hb = lst.top + HEAD_H - 12
    w = text(p, lst.left + PAD, hb, "TOPIC", key="cond", px=15, weight=600, spacing=0.12,
             color_=TEXT).width()
    w += text(p, lst.left + PAD + w + 8, hb, "//", px=12, color_=TEXT_DIM).width()
    text(p, lst.left + PAD + w + 16, hb, "話題", key="jp", px=10, color_=TEXT_DIM)
    label(p, lst.right - PAD, hb, "ESC", px=10, color_=TEXT_DIM, align=R)
    p.fillRect(QRectF(lst.left + PAD, lst.top + HEAD_H - 3, lst.w - 2 * PAD, 1), color(LINE))
    for i, item in enumerate(ITEMS):
        r = row_rect(lst, i)
        on = item.topic == current
        hov = picker.hover == i
        if hov:
            p.fillRect(QRectF(r.x + 1, r.y + 1, r.w - 2, r.h - 2), alpha(CPU, 30))
        if on or hov:
            p.fillRect(QRectF(r.x + 1, r.y + 8, 2, r.h - 16), color(CPU) if on else alpha(CPU, 150))
        lit = on or hov
        paint_glyph(p, item.topic, r.left + PAD + 10, r.top + r.h / 2, color(CPU) if lit
                    else alpha(TEXT_DIM, 200))
        tag_w = 0.0
        if on:
            tw = width("CURRENT", "mono", 9, None, 0.08)
            box = QRectF(r.right - PAD - tw - 10, r.top + 9, tw + 10, 15)
            p.save()
            p.setPen(QPen(color(CPU), 1))
            p.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5))
            p.restore()
            label(p, box.left() + 5, box.bottom() - 4, "CURRENT", px=9, color_=CPU)
            tag_w = tw + 18
        x = r.left + PAD + 30
        text(p, x, r.top + 21, item.text, px=14, color_=CPU if on else TEXT,
             max_w=max(0.0, r.right - PAD - tag_w - x))
        text(p, x, r.top + 39, description(item.topic, hint), px=11, color_=TEXT_DIM,
             max_w=max(0.0, r.right - PAD - x))
        if i < len(ITEMS) - 1 and not (hov or picker.hover == i + 1):
            p.fillRect(QRectF(x, r.bottom, r.right - PAD - x, 1), alpha(LINE, 160))
