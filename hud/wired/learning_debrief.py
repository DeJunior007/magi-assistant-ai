"""Painel do retorno da entrevista pela vaga na tela learning (LI2.4; learning-imersivo design §7,
spec §2 ``InterviewDebrief``, §7 ``lm_debrief``, R6, R4.3, D3). Grupo ``debrief`` da
``LearningScreen``.

Enquanto aberto, ocupa o lugar do drawer de observações (o painel ``obs`` da coluna direita) com
fundo opaco; fechado, o drawer volta igual (o grupo ``obs`` é repintado por baixo). No topo, as
**notas 0–100 por aspecto** (D3): uma linha por aspecto (``FLUENCY  72`` + barra fina) e a ``note``
em ``TEXT_DIM`` embaixo; aspecto ausente mostra ``—`` (barra vazia); **sem nota geral**. Depois:
cobertura por requisito (``✓`` covered / ``~`` thin / ``✗`` missed, com a evidência em
``TEXT_DIM``), fortes, a melhorar, respostas reescritas e inglês (rótulos das observações).
Rolável (roda do mouse); fecha em ``✕``, Esc ou clique fora.

Parte pura (sem Qt): ``rows`` (linhas já quebradas), ``content_h``/``max_scroll``, geometria
(``body_rect``, ``close_rect``) e ``DebriefView`` (aberto/fechado, rolagem, abre sozinho uma vez a
cada retorno novo — R5.2). A pintura (``paint``) importa o Qt só por dentro.
"""
from __future__ import annotations

import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .learning_text import Point, Rect

ASPECTS: tuple[tuple[str, str], ...] = (   # ordem do enum ``Aspect`` (contracts.py)
    ("fluency", "FLUENCY"),
    ("grammar", "GRAMMAR"),
    ("vocabulary", "VOCABULARY"),
    ("job_fit", "JOB FIT"),
    ("clarity", "CLARITY"),
)
MARKS = {"covered": "✓", "thin": "~", "missed": "✗"}
ABSENT = "—"

HEAD_H = 60.0            # título + linha da vaga
PAD = 21.0               # = learning_obs.PAD
CLOSE_W = 28.0
CHAR_W = 7.4             # largura média do caractere mono 12 px (quebra pura)
WHEEL_STEP = 40.0        # px por "clique" da roda
HEIGHTS = {"head": 26.0, "score": 20.0, "note": 16.0, "cover": 18.0, "evidence": 16.0,
           "item": 18.0, "more": 18.0, "dim": 16.0}
SCORE_X = 112.0          # coluna do número (alinhado à direita) a partir da margem
BAR_X = 124.0            # início da barra
BAR_H = 3.0


@dataclass(frozen=True)
class Row:
    """Linha do painel: ``kind`` (``head``/``score``/``note``/``cover``/``evidence``/``item``/
    ``more``/``dim``), ``text`` e ``value`` (nota ``int``/``None`` em ``score``; ``cover`` em
    ``cover``; ``True`` na primeira linha de um item com marcador)."""

    kind: str
    text: str
    value: Any = None

    @property
    def h(self) -> float:
        return HEIGHTS[self.kind]


# ====================================================================== dados (puro)

def score_map(msg: Mapping[str, Any] | None) -> dict[str, tuple[int, str]]:
    """``aspecto → (nota 0..100, note)``; aspecto desconhecido ou nota inválida caem."""
    out: dict[str, tuple[int, str]] = {}
    for s in (msg or {}).get("scores") or ():
        try:
            asp, score = str(s["aspect"]), int(s["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if asp in dict(ASPECTS) and asp not in out:
            out[asp] = (max(0, min(100, score)), str(s.get("note") or ""))
    return out


def score_text(score: int | None) -> str:
    return ABSENT if score is None else str(score)


def job_line(msg: Mapping[str, Any] | None) -> str:
    m = msg or {}
    title = str(m.get("title") or "").strip()
    company = str(m.get("company") or "").strip()
    return " · ".join(x for x in (title, company) if x)


def _wrap(s: str, chars: int) -> list[str]:
    return textwrap.wrap(str(s), max(8, chars)) or [""]


def rows(msg: Mapping[str, Any] | None, chars: int = 44) -> list[Row]:
    """Conteúdo do painel, de cima para baixo, já quebrado em ``chars`` colunas."""
    m = msg or {}
    out: list[Row] = [Row("head", "SCORES")]
    scores = score_map(m)
    for key, lbl in ASPECTS:
        score, note = scores.get(key, (None, ""))
        out.append(Row("score", lbl, score))
        if note:
            out += [Row("note", ln) for ln in _wrap(note, chars)]
    cov = [c for c in (m.get("coverage") or ()) if isinstance(c, Mapping) and c.get("requirement")]
    if cov:
        out.append(Row("head", "REQUIREMENTS"))
        for c in cov:
            cover = str(c.get("cover") or "missed")
            lines = _wrap(c["requirement"], chars - 3)
            out.append(Row("cover", lines[0], cover))
            out += [Row("cover", ln, None) for ln in lines[1:]]
            if c.get("evidence"):
                out += [Row("evidence", ln) for ln in _wrap(f"“{c['evidence']}”", chars - 3)]
    for head, key in (("STRENGTHS", "strengths"), ("TO IMPROVE", "improve")):
        items = [str(s) for s in (m.get(key) or ()) if s]
        if items:
            out.append(Row("head", head))
            for s in items:
                lines = _wrap(s, chars - 2)
                out.append(Row("item", lines[0], True))
                out += [Row("item", ln, False) for ln in lines[1:]]
    rewrites = [r for r in (m.get("rewrites") or ()) if isinstance(r, (list, tuple)) and len(r) == 2]
    if rewrites:
        out.append(Row("head", "BETTER ANSWERS"))
        for q, a in rewrites:
            out += [Row("dim", ln) for ln in _wrap(f"Q: {q}", chars)]
            out += [Row("item", ln, i == 0) for i, ln in enumerate(_wrap(str(a), chars - 2))]
    lang = [str(s) for s in (m.get("language") or ()) if s]
    if lang:
        out.append(Row("head", "ENGLISH"))
        out += [Row("more", ln) for ln in _wrap(" · ".join(lang), chars)]
    return out


def content_h(rs: list[Row]) -> float:
    return sum(r.h for r in rs)


# ====================================================================== geometria (pura)

def body_rect(panel: Rect) -> Rect:
    return Rect(panel.x + PAD, panel.y + HEAD_H, max(0.0, panel.w - 2 * PAD),
                max(0.0, panel.h - HEAD_H - 12))


def close_rect(panel: Rect) -> Rect:
    return Rect(panel.right - PAD - CLOSE_W + 6, panel.y + 12, CLOSE_W, CLOSE_W)


def chars(panel: Rect) -> int:
    return int(body_rect(panel).w / CHAR_W)


def max_scroll(panel: Rect, msg: Mapping[str, Any] | None) -> float:
    return max(0.0, content_h(rows(msg, chars(panel))) - body_rect(panel).h)


def debrief_id(msg: Mapping[str, Any] | None) -> tuple | None:
    """Identidade do retorno (abre sozinho uma vez por retorno novo)."""
    if not msg:
        return None
    return (str(msg.get("run_id") or ""), str(msg.get("at") or ""))


# ====================================================================== estado

@dataclass
class DebriefView:
    """Aberto/fechado e rolagem. ``sync`` abre o painel quando chega um retorno novo."""

    is_open: bool = False
    scroll: float = 0.0
    seen: tuple | None = None

    def sync(self, msg: Mapping[str, Any] | None) -> None:
        did = debrief_id(msg)
        if did is None:
            self.is_open = False
            return
        if did != self.seen:
            self.seen, self.is_open, self.scroll = did, True, 0.0

    def close(self) -> None:
        self.is_open = False
        self.scroll = 0.0

    def key(self, name: str) -> bool:
        if self.is_open and name == "esc":
            self.close()
            return True
        return False

    def wheel(self, delta: float, panel: Rect, msg: Mapping[str, Any] | None) -> bool:
        """Roda (positivo = para cima). ``True`` se a rolagem mudou."""
        old = self.scroll
        self.scroll = max(0.0, min(max_scroll(panel, msg), self.scroll - delta * WHEEL_STEP))
        return self.scroll != old

    def press(self, point: Point, panel: Rect, msg: Mapping[str, Any] | None) -> str:
        """``"close"`` (✕), ``"inside"`` (painel), ``"outside"`` (fecha; o clique segue) ou
        ``"none"`` (fechado)."""
        self.sync(msg)
        if not self.is_open:
            return "none"
        if panel.contains(point):
            if close_rect(panel).contains(point):
                self.close()
                return "close"
            return "inside"
        self.close()
        return "outside"


# ====================================================================== pintura (Qt)

def paint(p, panel: Rect, msg: Mapping[str, Any] | None, view: DebriefView) -> None:
    """Painel opaco no lugar do drawer: cabeçalho ``DEBRIEF // 講評`` + ``✕``, a vaga, e o
    conteúdo de ``rows`` rolado por ``view.scroll`` (cortado no corpo, com indicador)."""
    if not view.is_open or not msg:
        return
    from PySide6.QtCore import QRectF, Qt

    from . import kit
    from .main_screen import C, R, heading, label, text
    from .theme import CPU, GPU, HOT, LINE, LINE_STRONG, PANEL, SEG_OFF, TEXT, TEXT_DIM, WARN, color

    q = QRectF(panel.x, panel.y, panel.w, panel.h)
    kit.panel(p, q, fill=PANEL, border=LINE_STRONG, accent=CPU)
    x0 = panel.x + PAD
    w = heading(p, x0, panel.y + 34, "Debrief", px=20, color_=TEXT).width()
    text(p, x0 + w + 10, panel.y + 34, "講評", key="jp", px=12, color_=TEXT_DIM)
    c = close_rect(panel)
    text(p, c.x + c.w / 2, c.y + 20, "✕", px=14, color_=TEXT_DIM, align=C)
    label(p, x0, panel.y + 52, job_line(msg) or "interview", px=10, color_=TEXT_DIM, upper=False,
          max_w=panel.w - 2 * PAD)
    p.fillRect(QRectF(x0, panel.y + HEAD_H - 3, panel.w - 2 * PAD, 1), color(LINE))

    body = body_rect(panel)
    rs = rows(msg, chars(panel))
    total = content_h(rs)
    top = max(0.0, min(view.scroll, max(0.0, total - body.h)))
    p.save()
    p.setClipRect(QRectF(body.x, body.y, body.w, body.h), Qt.ClipOperation.IntersectClip)
    y = body.y - top
    marks = {"covered": GPU, "thin": WARN, "missed": HOT}
    for r in rs:
        if y + r.h < body.y:
            y += r.h
            continue
        if y > body.bottom:
            break
        base = y + r.h - 5
        if r.kind == "head":
            label(p, body.x, base, r.text, px=10, color_=CPU)
        elif r.kind == "score":
            label(p, body.x, base, r.text, px=11, color_=TEXT)
            num_col = TEXT_DIM if r.value is None else CPU
            text(p, body.x + SCORE_X, base, score_text(r.value), px=13, color_=num_col, align=R)
            bx, bw = body.x + BAR_X, body.w - BAR_X
            by = y + r.h / 2 - BAR_H / 2
            p.fillRect(QRectF(bx, by, bw, BAR_H), color(SEG_OFF))
            if r.value:
                p.fillRect(QRectF(bx, by, bw * r.value / 100.0, BAR_H), color(CPU))
        elif r.kind == "cover":
            if r.value is not None:
                text(p, body.x, base, MARKS.get(r.value, "?"), px=12,
                     color_=marks.get(r.value, TEXT_DIM))
            text(p, body.x + 18, base, r.text, px=12, color_=TEXT, max_w=body.w - 18)
        elif r.kind == "item":
            if r.value:
                text(p, body.x, base, "•", px=12, color_=CPU)
            text(p, body.x + 14, base, r.text, px=12, color_=TEXT, max_w=body.w - 14)
        elif r.kind == "evidence":
            text(p, body.x + 18, base, r.text, px=11, color_=TEXT_DIM, max_w=body.w - 18)
        elif r.kind == "more":
            text(p, body.x, base, r.text, px=12, color_=TEXT, max_w=body.w)
        else:  # note, dim
            text(p, body.x, base, r.text, px=11, color_=TEXT_DIM, max_w=body.w)
        y += r.h
    p.restore()
    if total > body.h > 0:  # indicador de rolagem
        th = max(16.0, body.h * body.h / total)
        ty = body.y + (body.h - th) * (top / (total - body.h))
        p.fillRect(QRectF(panel.right - 8, ty, 2, th), color(CPU))
