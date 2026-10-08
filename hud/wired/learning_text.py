"""Lógica pura do texto da tela learning (LM2.1; design §4.2, spec §5): sem Qt.

- ``wrap(messages, width, measure)`` quebra cada mensagem em linhas com um medidor injetado
  (``measure(str) -> float``; em produção ``QFontMetricsF.horizontalAdvance``, nos testes um
  medidor de largura fixa) e devolve as linhas e uma ``WordBox`` por palavra (``\\S+``), em
  coordenadas lógicas. A mesma lista de caixas pinta e faz o hit-test.
- ``hit(boxes, point)``: palavra sob o ponto; ponto entre palavras → a mais próxima na linha.
- ``Selector``: clique = palavra, arrasto = intervalo de palavras inteiras (recortado à mensagem
  de início; fora da coluna para na última palavra alcançada), duplo clique = frase.
- ``normalize`` apara espaços/pontuação nas pontas (``apples.`` → ``apples``) e gera a
  ``Selection`` (contrato LM0.1).
- ``Selection``/``ActionKind``/``Author`` vêm de ``magi.learning.contracts`` (LM0.1); como o HUD
  roda sem o venv do MAGI (ver ``hud_bridge``), há um espelho mínimo quando o import falha.
- ``menu_items(selection, author)``: as 4 ações com disponibilidade (spec §5; Improve
  desabilitado em mensagem da Condessa, P7; Vocabulary só 1–4 palavras).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

try:  # pragma: no branch - depende do ambiente
    from magi.learning.contracts import ActionKind, Author, Selection
except Exception:  # noqa: BLE001 - HUD sem o venv do MAGI (hud_bridge): espelho mínimo do LM0.1
    from enum import StrEnum

    class ActionKind(StrEnum):  # type: ignore[no-redef]
        IMPROVE = "improve"
        EXPLAIN = "explain"
        TRANSLATE = "translate"
        VOCABULARY = "vocabulary"

    class Author(StrEnum):  # type: ignore[no-redef]
        YOU = "you"
        CONDESSA = "condessa"

    @dataclass(frozen=True, slots=True)
    class Selection:  # type: ignore[no-redef]
        message_id: int
        start: int
        end: int
        text: str

        def to_dict(self) -> dict:
            return {"message_id": self.message_id, "start": self.start, "end": self.end,
                    "text": self.text}

Point = tuple[float, float]
Measure = Callable[[str], float]

_WORD = re.compile(r"\S+")
# Pontas aparadas da seleção: espaço e pontuação (inclui aspas/parênteses/travessões).
_EDGE = set(".,!?;:\"'()[]{}<>…—–-“”‘’«»*/\\") | {" ", "\t", "\n", "\r", " "}
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")

TRANSLATE_MAX_CHARS = 400
VOCAB_MAX_WORDS = 4


@dataclass(frozen=True, slots=True)
class Rect:
    """Retângulo lógico (x, y, largura, altura); ``right``/``bottom`` exclusivos."""

    x: float
    y: float
    w: float
    h: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    def contains(self, point: Point) -> bool:
        px, py = point
        return self.left <= px < self.right and self.top <= py < self.bottom

    def contains_rect(self, other: Rect) -> bool:
        return (self.left <= other.left and other.right <= self.right
                and self.top <= other.top and other.bottom <= self.bottom)

    def intersects(self, other: Rect) -> bool:
        return (self.left < other.right and other.left < self.right
                and self.top < other.bottom and other.top < self.bottom)

    def moved(self, x: float, y: float) -> Rect:
        return Rect(x, y, self.w, self.h)


class MessageLike(Protocol):
    """O que ``wrap`` precisa de uma mensagem (``LearningMessage`` serve)."""

    @property
    def id(self) -> int: ...

    @property
    def text(self) -> str: ...


@dataclass(frozen=True, slots=True)
class WordBox:
    """Uma palavra (``\\S+``) da mensagem: ``text[start:end]`` desenhada em ``rect``."""

    message_id: int
    start: int
    end: int
    rect: Rect
    line: int  # índice global da linha em ``Wrapped.lines``


@dataclass(frozen=True, slots=True)
class Line:
    """Uma linha visual de uma mensagem; ``first`` marca a linha do rótulo (CONDESSA/YOU)."""

    message_id: int
    rect: Rect
    boxes: tuple[WordBox, ...]
    first: bool


@dataclass(frozen=True, slots=True)
class Wrapped:
    """Saída de ``wrap``: linhas, caixas de palavra, bloco de cada mensagem e altura total."""

    lines: tuple[Line, ...]
    boxes: tuple[WordBox, ...]
    blocks: dict[int, Rect]
    height: float


def wrap(messages: Iterable[MessageLike], width: float, measure: Measure, *,
         x: float = 0.0, y: float = 0.0, indent: float = 0.0, line_h: float = 30.0,
         gap: float = 12.0) -> Wrapped:
    """Quebra as mensagens na coluna ``[x, x + width)`` a partir de ``y``.

    O texto começa em ``x + indent`` (o rótulo fica à esquerda, na primeira linha). Palavra
    maior que a linha fica sozinha na linha (não é cortada). Mensagem vazia ocupa uma linha.
    ``gap`` separa mensagens. Coordenadas lógicas; a rolagem entra por ``y``.
    """
    space = measure(" ")
    left = x + indent
    right = x + width
    lines: list[Line] = []
    boxes: list[WordBox] = []
    blocks: dict[int, Rect] = {}
    cur_y = y
    for n, msg in enumerate(messages):
        if n:
            cur_y += gap
        top = cur_y
        line_boxes: list[WordBox] = []
        first = True
        cx = left

        for m in _WORD.finditer(msg.text):
            w = measure(m.group())
            if line_boxes and cx + w > right:
                lines.append(Line(msg.id, Rect(x, cur_y, width, line_h), tuple(line_boxes),
                                  first))
                first = False
                line_boxes = []
                cur_y += line_h
                cx = left
            box = WordBox(msg.id, m.start(), m.end(), Rect(cx, cur_y, w, line_h), len(lines))
            line_boxes.append(box)
            boxes.append(box)
            cx += w + space
        lines.append(Line(msg.id, Rect(x, cur_y, width, line_h), tuple(line_boxes), first))
        cur_y += line_h
        blocks[msg.id] = Rect(x, top, width, cur_y - top)
    return Wrapped(tuple(lines), tuple(boxes), blocks, cur_y - y)


def _distance_x(box: WordBox, px: float) -> float:
    r = box.rect
    if r.left <= px < r.right:
        return 0.0
    return min(abs(px - r.left), abs(px - r.right))


def hit(boxes: Sequence[WordBox], point: Point, bounds: Rect | None = None) -> WordBox | None:
    """Palavra sob ``point``; entre palavras ou no fim da linha → a mais próxima na mesma linha.

    ``None`` se o ponto não está na altura de nenhuma linha com palavras ou está fora de
    ``bounds`` (a coluna da conversa), quando dado.
    """
    if bounds is not None and not bounds.contains(point):
        return None
    px, py = point
    line = [b for b in boxes if b.rect.top <= py < b.rect.bottom]
    if not line:
        return None
    return min(line, key=lambda b: _distance_x(b, px))


def normalize(message_id: int, text: str, start: int, end: int) -> Selection | None:
    """Apara espaços/pontuação nas pontas de ``text[start:end]``; ``None`` se não sobra nada."""
    start = max(0, start)
    end = min(len(text), end)
    while start < end and text[start] in _EDGE:
        start += 1
    while end > start and text[end - 1] in _EDGE:
        end -= 1
    if start >= end:
        return None
    return Selection(message_id=message_id, start=start, end=end, text=text[start:end])


def sentence_span(text: str, pos: int) -> tuple[int, int]:
    """Limites ``[start, end)`` da frase que contém ``pos`` (fim em ``. ! ?`` seguido de espaço
    ou fim da mensagem)."""
    start = 0
    for m in _SENTENCE_END.finditer(text):
        if m.end() > pos:
            return start, m.end()
        start = m.end()
    return start, len(text)


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


class Selector:
    """Estado da seleção de um gesto do mouse (pontos em coordenadas lógicas).

    ``press`` → palavra (ou limpa, em área sem texto); ``move`` (só com botão apertado) →
    intervalo da palavra inicial até a sob o ponteiro, recortado à mensagem de início;
    ``double`` → frase; ``selection`` → ``Selection`` normalizada ou ``None``.
    """

    def __init__(self, boxes: Sequence[WordBox], texts: dict[int, str],
                 bounds: Rect | None = None) -> None:
        self.boxes = tuple(boxes)
        self.texts = texts
        self.bounds = bounds
        self._anchor: WordBox | None = None
        self._current: WordBox | None = None
        self._span: tuple[int, int, int] | None = None  # (message_id, start, end)

    def set_boxes(self, boxes: Sequence[WordBox], bounds: Rect | None = None) -> None:
        """Troca as caixas (nova quebra/rolagem) e limpa a seleção."""
        self.boxes = tuple(boxes)
        self.bounds = bounds
        self.clear()

    def clear(self) -> None:
        self._anchor = self._current = None
        self._span = None

    def press(self, point: Point) -> Selection | None:
        box = hit(self.boxes, point, self.bounds)
        if box is None:
            self.clear()
            return None
        self._anchor = self._current = box
        self._span = (box.message_id, box.start, box.end)
        return self.selection

    def move(self, point: Point) -> Selection | None:
        if self._anchor is None:
            return None
        anchor = self._anchor
        box = hit(self.boxes, point, self.bounds)
        if box is None:
            pass  # fora da coluna / sem texto: para na última palavra alcançada
        elif box.message_id == anchor.message_id:
            self._current = box
        else:
            own = [b for b in self.boxes if b.message_id == anchor.message_id]
            after = self.boxes.index(box) > self.boxes.index(anchor)
            self._current = own[-1] if after else own[0]
        cur = self._current
        assert cur is not None
        self._span = (anchor.message_id, min(anchor.start, cur.start), max(anchor.end, cur.end))
        return self.selection

    def double(self, point: Point) -> Selection | None:
        box = hit(self.boxes, point, self.bounds)
        if box is None:
            self.clear()
            return None
        s, e = sentence_span(self.texts[box.message_id], box.start)
        self._anchor = self._current = box
        self._span = (box.message_id, s, e)
        return self.selection

    @property
    def selection(self) -> Selection | None:
        if self._span is None:
            return None
        mid, s, e = self._span
        return normalize(mid, self.texts[mid], s, e)

    def selected_boxes(self) -> tuple[WordBox, ...]:
        """Caixas cobertas pela seleção (para o destaque e a âncora do menu)."""
        sel = self.selection
        if sel is None:
            return ()
        return tuple(b for b in self.boxes if b.message_id == sel.message_id
                     and b.start < sel.end and b.end > sel.start)


@dataclass(frozen=True, slots=True)
class MenuItem:
    kind: ActionKind
    icon: str
    label: str
    enabled: bool


MENU_ORDER: tuple[tuple[ActionKind, str, str], ...] = (
    (ActionKind.IMPROVE, "✦", "Improve"),
    (ActionKind.EXPLAIN, "?", "Explain"),
    (ActionKind.TRANSLATE, "⇄", "Translate"),
    (ActionKind.VOCABULARY, "◇", "Vocabulary"),
)


def available(kind: ActionKind, selection: Selection, author: Author | str) -> bool:
    """Disponibilidade de uma ação (spec §5, tabela)."""
    words = word_count(selection.text)
    if words < 1:
        return False
    if kind is ActionKind.IMPROVE:
        return author == Author.YOU  # P7: desabilitado em mensagem da Condessa
    if kind is ActionKind.TRANSLATE:
        return len(selection.text) <= TRANSLATE_MAX_CHARS
    if kind is ActionKind.VOCABULARY:
        return words <= VOCAB_MAX_WORDS
    return True  # Explain: qualquer trecho


def menu_items(selection: Selection, author: Author | str) -> tuple[MenuItem, ...]:
    """As 4 ações do menu, sempre nesta ordem, com ``enabled`` pela tabela de spec §5."""
    return tuple(MenuItem(k, icon, label, available(k, selection, author))
                 for k, icon, label in MENU_ORDER)


def menu_label(selection: Selection, max_chars: int = 28) -> str:
    """Rótulo do menu: ``selected: "…"`` (truncado com reticências)."""
    text = " ".join(selection.text.split())
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return f'selected: "{text}"'


def can_open_menu(selection: Selection | None, speaking_message_id: int | None = None) -> bool:
    """Menu abre com seleção não vazia fora da mensagem em fala (spec §11)."""
    return selection is not None and selection.message_id != speaking_message_id
