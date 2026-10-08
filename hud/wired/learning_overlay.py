"""Menu e balão da tela learning (LM2.2; design §4, §4.2, spec §5): grupo ``overlay``.

Duas metades no mesmo módulo:

- **Lógica pura (sem Qt na importação):** ``Overlay`` (estado: fechado → menu → carregando →
  resultado/erro), itens do menu com foco por ↑↓ (pula os desabilitados), ``bubble_lines`` (o
  texto do balão por ``kind``, como no mockup), ``layout_bubble`` (quebra e linhas com retângulo,
  medidor injetado) e o provedor falso ``FakeProvider`` com os dados do mockup. Testado em
  ``tests/learning/test_bubble_model.py`` sem PySide6.
- **Pintura (``paint_menu``/``paint_bubble``):** QPainter, ícones em traço (sem emoji), paleta do
  wired; PySide6 e os ajudantes de ``main_screen`` só são importados na primeira pintura.

Provedor: ``submit(action, text) -> dict | None``. ``action`` tem os campos do ``lm_action``
(spec §6: ``id``, ``kind``, ``message_id``, ``start``, ``end``); ``text`` é o texto da mensagem
(o provedor falso precisa dele; o real ignora). O retorno é um ``lm_result`` (``ActionResult`` em
JSON) quando já há resposta, ou ``None`` quando ela vem depois — aí a tela chama
``Overlay.on_result`` ao receber o ``lm_result`` (LM3.4 troca o ``FakeProvider`` por um que manda
``lm_action`` pelo ``hud_bridge``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .learning_layout import MENU_HEAD_H, MENU_ITEM_H, MENU_PAD
from .learning_text import ActionKind, MenuItem, Rect, Selection, menu_items, menu_label

# ====================================================================== estado

CLOSED, MENU, LOADING, OK, ERROR = "closed", "menu", "loading", "ok", "error"

BUBBLE_W = 440.0      # largura lógica do balão
BUBBLE_PAD = 16.0     # margem interna
ROW_H = {             # altura de cada estilo de linha (lógico)
    "title": 30.0,    # IMPROVE // 改善 + etiquetas
    "label": 24.0,    # YOUR SENTENCE: / WHY? …
    "text": 22.0,     # corpo
    "strong": 24.0,   # frase melhorada, tradução, termo (lilás)
    "dim": 22.0,      # notas, "noun · B2", carregando
    "error": 22.0,
    "action": 28.0,   # "more ▸" / "[ retry ]" (clicáveis)
    "gap": 8.0,
}

TITLES = {
    ActionKind.IMPROVE: ("Improve", "改善"),
    ActionKind.EXPLAIN: ("Explain", "解説"),
    ActionKind.TRANSLATE: ("Translate", "翻訳"),
    ActionKind.VOCABULARY: ("Vocabulary", "語彙"),
}
IMPROVE_TAGS = {
    "grammar": ("GRAMMAR",),
    "naturalness": ("NATURALNESS",),
    "both": ("GRAMMAR", "NATURALNESS"),
    "none": ("LOOKS GOOD",),
}
ERRORS = {
    "timeout": "took too long",
    "budget": "budget limit reached",
    "model": "model error",
    "invalid": "invalid answer",
}
NO_RETRY = {"budget"}  # repetir não adianta: o teto só volta no outro dia


@dataclass(frozen=True, slots=True)
class BubbleLine:
    """Uma linha lógica do balão (antes da quebra). ``target`` = alvo clicável (more/retry)."""

    style: str
    text: str = ""
    tags: tuple[str, ...] = ()
    target: str | None = None


@dataclass(frozen=True, slots=True)
class Row:
    """Linha visual do balão (depois da quebra), em coordenadas relativas ao topo do balão."""

    style: str
    text: str
    rect: Rect
    tags: tuple[str, ...] = ()
    target: str | None = None


class Provider(Protocol):
    def submit(self, action: dict[str, Any], text: str) -> dict[str, Any] | None: ...


def _kind(k: ActionKind | str) -> ActionKind:
    return k if isinstance(k, ActionKind) else ActionKind(str(k))


# ====================================================================== texto do balão


def format_result(kind: ActionKind | str, data: dict[str, Any], selection_text: str = "",
                  more: bool = False) -> list[BubbleLine]:
    """Corpo do balão de um resultado ``ok`` (schemas de spec §5), sem a linha de título."""
    kind = _kind(kind)
    out: list[BubbleLine] = []
    if kind is ActionKind.IMPROVE:
        out += [BubbleLine("label", "YOUR SENTENCE:"), BubbleLine("text", str(data.get("original", ""))),
                BubbleLine("gap"),
                BubbleLine("label", "MORE NATURAL:"), BubbleLine("strong", str(data.get("improved", ""))),
                BubbleLine("gap"),
                BubbleLine("label", "WHY?"), BubbleLine("text", str(data.get("why", "")))]
    elif kind is ActionKind.EXPLAIN:
        out += [BubbleLine("strong", str(data.get("question", ""))), BubbleLine("gap"),
                BubbleLine("text", str(data.get("answer", "")))]
    elif kind is ActionKind.TRANSLATE:
        if selection_text:
            out += [BubbleLine("label", "SELECTED:"), BubbleLine("text", selection_text),
                    BubbleLine("gap")]
        out += [BubbleLine("label", "TRANSLATION:"), BubbleLine("strong", str(data.get("translation", "")))]
        if data.get("note"):
            out += [BubbleLine("gap"), BubbleLine("dim", str(data["note"]))]
    elif kind is ActionKind.VOCABULARY:
        meta = " · ".join(str(x) for x in (data.get("pos"), data.get("cefr")) if x)
        out += [BubbleLine("strong", str(data.get("term", "")))]
        if meta:
            out += [BubbleLine("dim", meta)]
        out += [BubbleLine("gap"), BubbleLine("text", str(data.get("meaning", "")))]
        if data.get("in_context"):
            out += [BubbleLine("gap"), BubbleLine("label", "IN CONTEXT:"),
                    BubbleLine("text", str(data["in_context"]))]
        examples = [str(x) for x in data.get("examples") or []]
        synonyms = [str(x) for x in data.get("synonyms") or []]
        if more:
            if examples:
                head = "EXAMPLE:" if len(examples) == 1 else "EXAMPLES:"
                out += [BubbleLine("gap"), BubbleLine("label", head)]
                out += [BubbleLine("text", f"· {e}") for e in examples]
            if synonyms:
                out += [BubbleLine("gap"), BubbleLine("label", "SYNONYMS:"),
                        BubbleLine("text", ", ".join(synonyms))]
            out.append(BubbleLine("action", "◂ less", target="more"))
        elif examples or synonyms:
            out.append(BubbleLine("action", "more ▸", target="more"))
    return out


def title_line(kind: ActionKind | str, result: dict[str, Any] | None = None) -> BubbleLine:
    """``IMPROVE // 改善`` + etiquetas (só no Improve com resultado: GRAMMAR/NATURALNESS)."""
    kind = _kind(kind)
    latin, jp = TITLES[kind]
    tags: tuple[str, ...] = ()
    if kind is ActionKind.IMPROVE and result and result.get("ok") and result.get("data"):
        tags = IMPROVE_TAGS.get(str(result["data"].get("kind", "")), ())
    return BubbleLine("title", f"{latin.upper()} // {jp}", tags=tags)


def error_text(error: str | None) -> str:
    return f"couldn't analyze — {ERRORS.get(error or '', error or 'unknown error')}"


def bubble_lines(phase: str, kind: ActionKind | str, result: dict[str, Any] | None = None,
                 selection_text: str = "", more: bool = False) -> list[BubbleLine]:
    """Todas as linhas do balão na fase ``phase`` (loading/ok/error). Fechado/menu: vazio."""
    if phase not in (LOADING, OK, ERROR):
        return []
    lines = [title_line(kind, result if phase == OK else None)]
    if phase == LOADING:
        lines.append(BubbleLine("dim", "analyzing…"))  # estático: nada pisca
    elif phase == ERROR:
        err = (result or {}).get("error")
        lines.append(BubbleLine("error", error_text(err)))
        if err not in NO_RETRY:
            lines.append(BubbleLine("action", "[ retry ]", target="retry"))
    else:
        lines += format_result(kind, (result or {}).get("data") or {}, selection_text, more)
    return lines


def wrap_text(s: str, width: float, measure: Callable[[str], float]) -> list[str]:
    """Quebra por palavra em ``width``; palavra maior que a linha fica sozinha (não corta)."""
    words = s.split()
    if not words:
        return [""]
    out, cur = [], ""
    for w in words:
        cand = f"{cur} {w}" if cur else w
        if cur and measure(cand) > width:
            out.append(cur)
            cur = w
        else:
            cur = cand
    out.append(cur)
    return out


def layout_bubble(lines: Sequence[BubbleLine], measure: Callable[[str, str], float],
                  width: float = BUBBLE_W) -> tuple[list[Row], float]:
    """Linhas visuais (retângulos relativos ao balão) e a altura total.

    ``measure(style, texto)`` mede no estilo da linha (em produção, a fonte da pintura)."""
    inner = width - 2 * BUBBLE_PAD
    rows: list[Row] = []
    y = BUBBLE_PAD
    for ln in lines:
        h = ROW_H.get(ln.style, ROW_H["text"])
        if ln.style == "gap":
            y += h
            continue
        if ln.style in ("title", "action"):
            parts = [ln.text]
        else:
            parts = wrap_text(ln.text, inner, lambda s, st=ln.style: measure(st, s))
        for part in parts:
            rows.append(Row(ln.style, part, Rect(BUBBLE_PAD, y, inner, h), ln.tags, ln.target))
            y += h
        if ln.style == "title":
            y += 6  # respiro sob a linha do título
    return rows, y + BUBBLE_PAD


# ====================================================================== provedor falso (dados do mockup)

MOCK_IMPROVE = {"original": "yesterday I make a new", "improved": "yesterday I built a new",
                "kind": "both",
                "why": "\"Built\" sounds more natural when talking about something you created."}
MOCK_EXPLAIN = {"question": "Why \"built\" instead of \"made\"?",
                "answer": "Both are possible. For software, \"built\" is generally more natural because "
                          "it emphasizes creating or developing a system."}
MOCK_TRANSLATE = {"translation": "eu faço (aqui: eu fiz)",
                  "note": "Here 'make' should be past: 'made/built'."}
MOCK_VOCAB = {"term": "authentication", "meaning": "the process of proving who a user is",
              "in_context": "the login system you built", "pos": "noun", "cefr": "B2",
              "examples": ["We added two-factor authentication."], "synonyms": ["verification"]}


def _norm(s: str) -> str:
    return " ".join(s.lower().strip(" .,!?;:\"'").split())


@dataclass
class FakeProvider:
    """Provedor local com os dados do mockup (LM2.2). Responde na hora (``submit`` devolve o
    ``lm_result``). Fora dos casos do mockup devolve erro ``model`` — é o caminho do "retry".
    ``fail`` força erro (teste/manual). LM3.4 troca por ``lm_action``/``lm_result`` reais."""

    fail: str | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def submit(self, action: dict[str, Any], text: str) -> dict[str, Any] | None:
        self.calls.append(dict(action))
        kind = _kind(action["kind"])
        sel = _norm(text[int(action["start"]):int(action["end"])])
        data = None if self.fail else self._data(kind, sel, text.lower())
        base = {"id": action["id"], "kind": kind.value, "cached": False, "ms": 0, "cost_usd": 0.0}
        if data is None:
            return {**base, "ok": False, "data": None, "error": self.fail or "model"}
        return {**base, "ok": True, "data": data, "error": None}

    @staticmethod
    def _data(kind: ActionKind, sel: str, msg: str) -> dict[str, Any] | None:
        if kind is ActionKind.IMPROVE:
            return dict(MOCK_IMPROVE) if "i make" in msg and sel else None
        if kind is ActionKind.EXPLAIN:
            return dict(MOCK_EXPLAIN) if sel in ("built", "made", "make", "i make", "i built") else None
        if kind is ActionKind.TRANSLATE:
            return dict(MOCK_TRANSLATE) if sel in ("i make", "make") else None
        if kind is ActionKind.VOCABULARY:
            return {**MOCK_VOCAB} if sel == "authentication" else None
        return None


# ====================================================================== Overlay


@dataclass
class Overlay:
    """Estado do grupo ``overlay``: menu da seleção e balão do resultado (um por vez).

    ``open`` → menu; ``choose(kind)`` → carregando (ou resultado direto, se o provedor responder
    na hora); ``on_result`` → ok/erro; ``retry``; ``toggle_more`` (Vocabulary); ``key`` para
    ↑↓/Enter/Esc; ``close``. ``version`` muda a cada mudança visível (chave do grupo)."""

    provider: Provider = field(default_factory=FakeProvider)
    phase: str = CLOSED
    selection: Selection | None = None
    author: str = "you"
    items: tuple[MenuItem, ...] = ()
    hover: int | None = None
    kind: ActionKind | None = None
    action_id: str | None = None
    result: dict[str, Any] | None = None
    more: bool = False
    version: int = 0
    seq: int = 0
    message_text: str = ""

    @property
    def is_open(self) -> bool:
        return self.phase != CLOSED

    @property
    def has_bubble(self) -> bool:
        return self.phase in (LOADING, OK, ERROR)

    def _bump(self) -> None:
        self.version += 1

    def open(self, selection: Selection, author: str, message_text: str = "") -> None:
        """Menu da seleção (fecha o balão anterior)."""
        self.selection = selection
        self.author = str(author)
        self.message_text = message_text
        self.items = menu_items(selection, author)
        self.hover = None
        self.kind = self.action_id = self.result = None
        self.more = False
        self.phase = MENU
        self._bump()

    def close(self) -> bool:
        if self.phase == CLOSED:
            return False
        self.phase = CLOSED
        self.selection = None
        self.items = ()
        self.hover = None
        self.kind = self.action_id = self.result = None
        self.more = False
        self._bump()
        return True

    def label(self) -> str:
        return menu_label(self.selection) if self.selection else ""

    # ------------------------------------------------------------ ações

    def action(self) -> dict[str, Any] | None:
        """Campos do ``lm_action`` da ação corrente (spec §6)."""
        if self.selection is None or self.kind is None or self.action_id is None:
            return None
        s = self.selection
        return {"id": self.action_id, "kind": self.kind.value, "message_id": s.message_id,
                "start": s.start, "end": s.end}

    def choose(self, kind: ActionKind | str) -> dict[str, Any] | None:
        """Pede a ação ``kind`` (se habilitada). Devolve o ``lm_action`` enviado ou ``None``."""
        if self.phase == CLOSED or self.selection is None:
            return None
        kind = _kind(kind)
        item = next((it for it in self.items if it.kind is kind), None)
        if item is None or not item.enabled:
            return None
        self.kind = kind
        self.hover = self.items.index(item)
        return self._send()

    def retry(self) -> dict[str, Any] | None:
        if self.phase != ERROR or self.kind is None:
            return None
        return self._send()

    def _send(self) -> dict[str, Any] | None:
        self.seq += 1
        self.action_id = f"ui-{self.seq}"
        self.result = None
        self.more = False
        self.phase = LOADING
        self._bump()
        act = self.action()
        assert act is not None
        res = self.provider.submit(act, self.message_text)
        if res is not None:
            self.on_result(res)
        return act

    def on_result(self, result: dict[str, Any]) -> bool:
        """``lm_result`` chegou; só vale o da ação corrente (correlação por ``id``)."""
        if self.phase != LOADING or str(result.get("id")) != self.action_id:
            return False
        self.result = dict(result)
        self.phase = OK if result.get("ok") and result.get("data") is not None else ERROR
        self._bump()
        return True

    def toggle_more(self) -> bool:
        if self.phase != OK or self.kind is not ActionKind.VOCABULARY:
            return False
        self.more = not self.more
        self._bump()
        return True

    def target(self, name: str | None) -> bool:
        """Clique num alvo do balão (``more``/``retry``)."""
        if name == "more":
            return self.toggle_more()
        if name == "retry":
            return self.retry() is not None
        return False

    # ------------------------------------------------------------ teclado / hover

    def set_hover(self, idx: int | None) -> bool:
        if idx is not None and not (0 <= idx < len(self.items) and self.items[idx].enabled):
            idx = None
        if idx == self.hover:
            return False
        self.hover = idx
        self._bump()
        return True

    def step(self, d: int) -> bool:
        """↑ (−1) / ↓ (+1): próximo item habilitado, com volta."""
        enabled = [i for i, it in enumerate(self.items) if it.enabled]
        if not enabled or self.phase == CLOSED:
            return False
        if self.hover not in enabled:
            nxt = enabled[0] if d > 0 else enabled[-1]
        else:
            nxt = enabled[(enabled.index(self.hover) + d) % len(enabled)]
        return self.set_hover(nxt) or True

    def key(self, name: str) -> bool:
        """Tecla vinda do HUD (``up``/``down``/``enter``/``esc``). ``True`` = consumida."""
        if self.phase == CLOSED:
            return False
        if name == "esc":
            return self.close()
        if name in ("up", "down"):
            return self.step(-1 if name == "up" else 1)
        if name == "enter":
            if self.phase == ERROR:
                return self.retry() is not None
            if self.hover is not None and self.items[self.hover].enabled:
                if self.phase == MENU or self.items[self.hover].kind is not self.kind:
                    return self.choose(self.items[self.hover].kind) is not None
                return True
            return False
        return False

    def state_key(self) -> tuple:
        return (self.phase, self.version)

    def lines(self) -> list[BubbleLine]:
        sel = self.selection.text if self.selection else ""
        if self.kind is None:
            return []
        return bubble_lines(self.phase, self.kind, self.result, sel, self.more)


def item_rect(menu: Rect, i: int) -> Rect:
    """Retângulo do item ``i`` dentro do menu (``learning_layout.menu_size``)."""
    return Rect(menu.x, menu.y + MENU_HEAD_H + i * MENU_ITEM_H, menu.w, MENU_ITEM_H)


def item_at(menu: Rect, n: int, point: tuple[float, float]) -> int | None:
    for i in range(n):
        if item_rect(menu, i).contains(point):
            return i
    return None


# ====================================================================== pintura (QPainter)

SEL_FILL = "#b392f040"   # destaque da seleção: lilás translúcido
HOVER_FILL = "#b392f01c"
BUBBLE_FILL = "#100e17"
MENU_FILL = "#0f0e15"
_Q: Any = None


def _qt() -> Any:
    """PySide6 e os ajudantes de texto, importados só na primeira pintura (o resto do módulo
    fica sem Qt para os testes de lógica pura)."""
    global _Q
    if _Q is None:
        from types import SimpleNamespace

        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QPainter, QPainterPath, QPen, QPolygonF

        from . import kit
        from .main_screen import label, text, width
        from .theme import CPU, HOT, LINE, LINE_STRONG, TEXT, TEXT_DIM, alpha, color

        _Q = SimpleNamespace(QPointF=QPointF, QRectF=QRectF, Qt=Qt, QPainter=QPainter,
                             QPainterPath=QPainterPath, QPen=QPen, QPolygonF=QPolygonF, kit=kit,
                             label=label, text=text, width=width, CPU=CPU, HOT=HOT, LINE=LINE,
                             LINE_STRONG=LINE_STRONG, TEXT=TEXT, TEXT_DIM=TEXT_DIM, alpha=alpha,
                             color=color)
    return _Q


# fonte de cada estilo: (chave, px, peso, espaçamento, cor)
def _style(style: str) -> tuple[str, float, int | None, float, str]:
    q = _qt()
    return {
        "title": ("cond", 17, 600, 0.12, q.CPU),
        "label": ("mono", 11, None, 0.08, q.TEXT_DIM),
        "text": ("mono", 14, None, 0.0, q.TEXT),
        "strong": ("mono", 15, None, 0.0, q.CPU),
        "dim": ("mono", 13, None, 0.0, q.TEXT_DIM),
        "error": ("mono", 13, None, 0.0, q.HOT),
        "action": ("mono", 12, None, 0.08, q.CPU),
    }.get(style, ("mono", 14, None, 0.0, q.TEXT))


def measure(style: str, s: str) -> float:
    """Medidor da pintura para ``layout_bubble`` (mesma fonte de ``_style``)."""
    key, px, weight, spacing, _ = _style(style)
    return _qt().width(s, key, px, weight, spacing)


def label_width(s: str) -> float:
    """Largura do rótulo ``selected: "…"`` (para ``learning_layout.menu_size``)."""
    return _qt().width(s, "mono", 12, None, 0.04)


def _frame(p, r: Rect, fill: str) -> None:
    q = _qt()
    rr = q.QRectF(r.x, r.y, r.w, r.h)
    # moldura do canvas (chanfro); o traço curto do topo em lilás é o único "brilho"
    q.kit.panel(p, rr, fill=fill, border=q.LINE_STRONG, accent=q.CPU)


def icon(p, kind: ActionKind, cx: float, cy: float, col, size: float = 6.0) -> None:
    """Ícones do menu em traço: ✦ (Improve), ? (Explain), ⇄ (Translate), ◇ (Vocabulary)."""
    q = _qt()
    p.save()
    p.setRenderHint(q.QPainter.RenderHint.Antialiasing, True)
    pen = q.QPen(col, 1.4)
    pen.setCapStyle(q.Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(q.Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(q.Qt.BrushStyle.NoBrush)
    s = size
    P = q.QPointF
    if kind is ActionKind.IMPROVE:  # estrela de 4 pontas (lados côncavos)
        path = q.QPainterPath(P(cx, cy - s))
        path.quadTo(P(cx, cy), P(cx + s, cy))
        path.quadTo(P(cx, cy), P(cx, cy + s))
        path.quadTo(P(cx, cy), P(cx - s, cy))
        path.quadTo(P(cx, cy), P(cx, cy - s))
        p.drawPath(path)
    elif kind is ActionKind.EXPLAIN:  # círculo com "?" em traço
        p.drawEllipse(P(cx, cy), s, s)
        path = q.QPainterPath(P(cx - s * 0.38, cy - s * 0.3))
        path.cubicTo(P(cx - s * 0.38, cy - s * 0.75), P(cx + s * 0.42, cy - s * 0.75),
                     P(cx + s * 0.38, cy - s * 0.25))
        path.cubicTo(P(cx + s * 0.32, cy + s * 0.05), P(cx, cy), P(cx, cy + s * 0.25))
        p.drawPath(path)
        p.drawPoint(P(cx, cy + s * 0.55))
    elif kind is ActionKind.TRANSLATE:  # ⇄: seta para a direita em cima, para a esquerda embaixo
        y1, y2 = cy - s * 0.4, cy + s * 0.4
        p.drawLine(P(cx - s, y1), P(cx + s, y1))
        p.drawLine(P(cx + s, y1), P(cx + s * 0.5, y1 - s * 0.45))
        p.drawLine(P(cx + s, y2), P(cx - s, y2))
        p.drawLine(P(cx - s, y2), P(cx - s * 0.5, y2 + s * 0.45))
    else:  # ◇
        p.drawPolygon(q.QPolygonF([P(cx, cy - s), P(cx + s, cy), P(cx, cy + s), P(cx - s, cy)]))
    p.restore()


def paint_menu(p, ov: Overlay, menu: Rect) -> None:
    """Menu: ``selected: "…"`` + quatro itens (desabilitado em ``TEXT_DIM`` apagado; foco/hover
    com fundo lilás fraco e traço à esquerda; a ação do balão aberto fica marcada)."""
    q = _qt()
    _frame(p, menu, MENU_FILL)
    q.text(p, menu.x + MENU_PAD, menu.y + 20, ov.label(), key="mono", px=12, color_=q.TEXT_DIM,
           spacing=0.04, max_w=menu.w - 2 * MENU_PAD)
    p.fillRect(q.QRectF(menu.x + MENU_PAD, menu.y + MENU_HEAD_H - 4, menu.w - 2 * MENU_PAD, 1),
               q.color(q.LINE))
    for i, it in enumerate(ov.items):
        r = item_rect(menu, i)
        active = it.enabled and (i == ov.hover or (ov.has_bubble and it.kind is ov.kind))
        if active:
            p.fillRect(q.QRectF(r.x + 1, r.y, r.w - 2, r.h), q.color(HOVER_FILL))
            p.fillRect(q.QRectF(r.x + 1, r.y + 4, 2, r.h - 8), q.color(q.CPU))
        col = q.color(q.CPU) if it.enabled else q.alpha(q.TEXT_DIM, 90)
        icon(p, it.kind, r.x + MENU_PAD + 8, r.y + r.h / 2, col)
        q.text(p, r.x + MENU_PAD + 26, r.y + r.h / 2 + 5, it.label, key="mono", px=14,
               color_=q.color(q.TEXT) if it.enabled else q.alpha(q.TEXT_DIM, 110))


def paint_bubble(p, rows: Sequence[Row], bubble: Rect) -> None:
    """Balão: linhas já quebradas (``layout_bubble``), deslocadas para ``bubble``."""
    q = _qt()
    _frame(p, bubble, BUBBLE_FILL)
    for row in rows:
        r = row.rect.moved(bubble.x + row.rect.x, bubble.y + row.rect.y)
        key, px, weight, spacing, col = _style(row.style)
        base = r.y + r.h - 7
        if row.style == "title":
            w = q.text(p, r.x, base, row.text, key=key, px=px, weight=weight, spacing=spacing,
                       color_=col).width()
            x = r.right
            for tag in reversed(row.tags):  # etiquetas à direita, em caixas de traço fino
                tw = q.width(tag, "mono", 10, None, 0.08) + 12
                x -= tw
                if x < r.x + w + 8:
                    break
                box = q.QRectF(x, r.y + 4, tw, r.h - 10)
                p.save()
                p.setPen(q.QPen(q.color(q.CPU), 1))
                p.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5))
                p.restore()
                q.label(p, x + 6, box.bottom() - 6, tag, px=10, color_=q.CPU)
                x -= 6
            p.fillRect(q.QRectF(r.x, r.bottom + 2, r.w, 1), q.color(q.LINE))
        elif row.style == "action":
            q.text(p, r.x, base, row.text, key=key, px=px, spacing=spacing, color_=col)
        else:
            q.text(p, r.x, base, row.text, key=key, px=px, weight=weight, spacing=spacing,
                   color_=col, max_w=r.w + 1)


__all__ = [
    "BUBBLE_W", "CLOSED", "ERROR", "LOADING", "MENU", "OK", "BubbleLine", "FakeProvider",
    "Overlay", "Row", "bubble_lines", "error_text", "format_result", "item_at", "item_rect",
    "label_width", "layout_bubble", "measure", "paint_bubble", "paint_menu", "title_line",
    "wrap_text",
]
