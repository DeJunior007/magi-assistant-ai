"""Entrevista pela vaga na tela learning (LI2.2; learning-imersivo design §7, spec §7, R6, R2.1,
R2.5): faixa no topo da coluna da conversa com o chip ``INTERVIEW // CARGO · EMPRESA ▾``, o botão
``[ END INTERVIEW ]`` e a linha ``STAGE 3/6 · TECHNICAL — PYTHON  12:40``; painel do perfil (stack
e requisitos obrigatórios) aberto pelo chip. Grupo ``interview`` da ``LearningScreen``.

Parte pura (sem Qt): o estado vem do último ``lm_interview`` do núcleo (guardado no
``LearningModel`` com o instante de chegada); ``InterviewView`` guarda só o painel aberto/fechado.
``chip_parts``, ``stage_line``, ``elapsed``/``clock_text``, ``profile_rows`` e a geometria
(``strip_rect``, ``chip_rect``, ``end_rect``, ``retry_rect``, ``panel_rect``) são funções puras.
A pintura (``paint``) importa o Qt só por dentro.

Estados: ``preparing`` (linha ``READING THE JOB POST`` + barra de segmentos animada como a do
balão), ``ready``/``running``/``paused``/``debriefing`` (etapa e tempo; o tempo corre só em
``running``), ``error`` (a linha de erro e ``[ RETRY ]``, que manda ``lm_job {"job_id"}``) e
``done`` (faixa some). ``[ END INTERVIEW ]`` manda ``lm_interview {"cmd": "end"}``.
"""
from __future__ import annotations

import math
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .learning_text import Point, Rect

VISIBLE = frozenset({"preparing", "ready", "running", "paused", "debriefing", "error"})
ANIM_FPS = 5.0           # = learning_overlay.ANIM_FPS (barra de preparo)
LOAD_SEGS = 12

STRIP_H = 60.0           # faixa no topo da coluna da conversa (base 1920)
ROW_H = 26.0             # caixa do chip e dos botões
END_W = 176.0
RETRY_W = 96.0
GAP = 12.0
PAD = 12.0
PANEL_W = 520.0
PANEL_HEAD = 36.0
PANEL_LINE = 20.0
PANEL_CHAR = 7.4         # largura média do caractere mono 12 px (quebra pura do painel)
MAX_MUST = 8


# ====================================================================== estado (puro)

def visible(msg: Mapping[str, Any] | None) -> bool:
    return bool(msg) and str(msg.get("state")) in VISIBLE


def chip_parts(msg: Mapping[str, Any] | None) -> tuple[str, str, str | None]:
    """``("INTERVIEW // ", CARGO, empresa)``; sem cargo ainda (preparando), ``PREPARING``/``JOB``."""
    m = msg or {}
    title = str(m.get("title") or "").strip()
    if not title:
        title = "preparing" if m.get("state") == "preparing" else "job"
    company = str(m.get("company") or "").strip() or None
    return ("INTERVIEW // ", title.upper(), company)


def chip_text(msg: Mapping[str, Any] | None) -> str:
    head, title, company = chip_parts(msg)
    return f"{head}{title}{f' · {company}' if company else ''} ▾"


def elapsed(msg: Mapping[str, Any] | None, at: float | None, now: float) -> float:
    """Segundos da simulação: ``elapsed_s`` do núcleo + o que passou desde a chegada (só em
    ``running``; pausada/pronta o relógio para)."""
    m = msg or {}
    base = float(m.get("elapsed_s") or 0.0)
    if m.get("state") == "running" and at is not None:
        base += max(0.0, now - at)
    return base


def clock_text(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def stage_text(msg: Mapping[str, Any] | None) -> str:
    """``STAGE 3/6 · TECHNICAL — PYTHON`` (sem etapa ainda: vazio)."""
    m = msg or {}
    stage, n = m.get("stage"), m.get("n_stages")
    if stage is None:
        return ""
    head = f"STAGE {int(stage)}/{int(n)}" if n else f"STAGE {int(stage)}"
    lbl = str(m.get("stage_label") or "").strip()
    return f"{head} · {lbl.upper()}" if lbl else head


def stage_line(msg: Mapping[str, Any] | None, at: float | None, now: float) -> str:
    """Linha de baixo da faixa conforme o estado (o tempo entra separado na pintura)."""
    m = msg or {}
    st = m.get("state")
    if st == "preparing":
        return "READING THE JOB POST"
    if st == "error":
        return f"JOB POST FAILED — {m.get('error') or 'unknown error'}"
    if st == "debriefing":
        return "WRITING THE DEBRIEF"
    line = stage_text(m) or "STAGE —"
    if st == "paused":
        line += " · PAUSED"
    return f"{line}  {clock_text(elapsed(m, at, now))}"


def can_retry(msg: Mapping[str, Any] | None) -> bool:
    m = msg or {}
    return m.get("state") == "error" and bool(m.get("job_id"))


def frame(at: float | None, now: float) -> int:
    """Quadro da barra de preparo (``ANIM_FPS`` por segundo desde a chegada)."""
    return 0 if at is None else max(0, int((now - at) * ANIM_FPS))


def deadline(msg: Mapping[str, Any] | None, at: float | None, now: float) -> float | None:
    """Próximo instante em que a faixa muda sozinha: quadro da barra (preparando) ou virada do
    segundo do relógio (rodando); ``None`` nos outros estados."""
    m = msg or {}
    if at is None or not visible(m):
        return None
    if m.get("state") == "preparing":
        return at + (frame(at, now) + 1) / ANIM_FPS
    if m.get("state") == "running":
        e = elapsed(m, at, now)
        return now + (math.floor(e) + 1 - e)
    return None


def profile_rows(msg: Mapping[str, Any] | None, max_chars: int = 64) -> list[tuple[str, str]]:
    """Linhas do painel do perfil: ``(estilo, texto)`` com estilo ``head``/``text``/``item``/
    ``dim``. Stack em linhas quebradas por ``max_chars``; até ``MAX_MUST`` requisitos."""
    m = msg or {}
    rows: list[tuple[str, str]] = []
    if m.get("seniority"):
        rows.append(("dim", f"seniority: {m['seniority']}"))
    stack = [str(s) for s in (m.get("stack") or ()) if s]
    rows.append(("head", "STACK"))
    if stack:
        rows += [("text", ln) for ln in textwrap.wrap(" · ".join(stack), max(8, max_chars))]
    else:
        rows.append(("dim", "—"))
    must = [str(s) for s in (m.get("must") or ()) if s]
    rows.append(("head", "MUST HAVE"))
    if must:
        rows += [("item", s) for s in must[:MAX_MUST]]
        if len(must) > MAX_MUST:
            rows.append(("dim", f"+{len(must) - MAX_MUST} more"))
    else:
        rows.append(("dim", "—"))
    return rows


# ====================================================================== geometria (pura)

def strip_rect(history: Rect) -> Rect:
    return Rect(history.x, history.y, history.w, min(STRIP_H, history.h))


def end_rect(strip: Rect) -> Rect:
    return Rect(strip.right - END_W, strip.y + 4, END_W, ROW_H)


def chip_rect(strip: Rect) -> Rect:
    return Rect(strip.x, strip.y + 4, max(0.0, strip.w - END_W - GAP), ROW_H)


def retry_rect(strip: Rect) -> Rect:
    return Rect(strip.right - RETRY_W, strip.y + ROW_H + 8, RETRY_W, ROW_H - 4)


def panel_chars(strip: Rect) -> int:
    return int((min(PANEL_W, strip.w) - 2 * PAD) / PANEL_CHAR)


def panel_rect(strip: Rect, msg: Mapping[str, Any] | None) -> Rect:
    n = len(profile_rows(msg, panel_chars(strip)))
    return Rect(strip.x, strip.bottom + 4, min(PANEL_W, strip.w), PANEL_HEAD + n * PANEL_LINE + PAD)


# ====================================================================== painel aberto/fechado

@dataclass
class InterviewView:
    """Painel do perfil (aberto pelo chip). ``press`` decide o clique; a tela manda as mensagens."""

    panel_open: bool = False

    def sync(self, msg: Mapping[str, Any] | None) -> None:
        if not visible(msg):
            self.panel_open = False

    def key(self, name: str) -> bool:
        if self.panel_open and name == "esc":
            self.panel_open = False
            return True
        return False

    def press(self, point: Point, strip: Rect, msg: Mapping[str, Any] | None) -> str:
        """``"end"`` (botão), ``"retry"`` (erro com ``job_id``), ``"toggle"`` (chip),
        ``"inside"`` (faixa ou painel), ``"outside"`` (fora com o painel aberto: fecha e o clique
        segue) ou ``"none"`` (sem simulação ou fora de tudo)."""
        self.sync(msg)
        if not visible(msg):
            return "none"
        if strip.contains(point):
            if end_rect(strip).contains(point):
                return "end"
            if can_retry(msg) and retry_rect(strip).contains(point):
                return "retry"
            if chip_rect(strip).contains(point):
                self.panel_open = not self.panel_open
                return "toggle"
            return "inside"
        if self.panel_open:
            if panel_rect(strip, msg).contains(point):
                return "inside"
            self.panel_open = False
            return "outside"
        return "none"


# ====================================================================== pintura (Qt)

def _box(p, r: Rect, col, fill=None) -> None:
    from PySide6.QtCore import QRectF

    q = QRectF(r.x, r.y, r.w, r.h)
    if fill is not None:
        p.fillRect(q, fill)
    p.fillRect(QRectF(q.left(), q.top(), q.width(), 1), col)
    p.fillRect(QRectF(q.left(), q.bottom() - 1, q.width(), 1), col)
    p.fillRect(QRectF(q.left(), q.top(), 1, q.height()), col)
    p.fillRect(QRectF(q.right() - 1, q.top(), 1, q.height()), col)


def paint_bar(p, x0: float, x1: float, cy: float, frm: int) -> None:
    """Barra de ``LOAD_SEGS`` segmentos com o pulso lilás (o mesmo desenho do balão)."""
    from PySide6.QtCore import QRectF

    from .theme import CPU, SEG_OFF, alpha, color

    gap, n, h = 3.0, LOAD_SEGS, 6.0
    seg_w = max(4.0, (x1 - x0 - (n - 1) * gap) / n)
    head = frm % (n + 3)
    for i in range(n):
        d = head - i
        if d == 0:
            col = color(CPU)
        elif 0 < d <= 3:
            col = alpha(CPU, (150, 90, 45)[d - 1])
        else:
            col = color(SEG_OFF)
        p.fillRect(QRectF(x0 + i * (seg_w + gap), cy - h / 2, seg_w, h), col)


def paint(p, strip: Rect, msg: Mapping[str, Any] | None, at: float | None, now: float,
          view: InterviewView, fill: str = "#0c0b11") -> None:
    """Faixa (fundo opaco, cobre o topo do histórico) e, se aberto, o painel do perfil."""
    if not visible(msg):
        return
    from PySide6.QtCore import QRectF

    from .main_screen import C, R, label, text
    from .theme import CPU, HOT, LINE, LINE_STRONG, TEXT, TEXT_DIM, alpha, color

    m = msg or {}
    p.fillRect(QRectF(strip.x, strip.y, strip.w, strip.h), color(fill))
    p.fillRect(QRectF(strip.x, strip.bottom - 1, strip.w, 1), color(LINE))
    # chip
    c = chip_rect(strip)
    _box(p, c, color(CPU) if view.panel_open else color(LINE_STRONG),
         alpha(CPU, 22) if view.panel_open else None)
    p.fillRect(QRectF(c.x, c.y, 2, c.h), color(CPU))
    head, title, company = chip_parts(m)
    y = c.y + 18
    x = c.x + PAD
    x += label(p, x, y, head, px=13, color_=TEXT_DIM, upper=False).width()
    arrow_w = 18.0
    x += label(p, x, y, title, px=13, color_=TEXT, upper=False,
               max_w=max(0.0, c.right - PAD - arrow_w - x)).width()
    if company and x < c.right - PAD - arrow_w - 20:
        label(p, x, y, f" · {company}", px=13, color_=TEXT_DIM, upper=False,
              max_w=max(0.0, c.right - PAD - arrow_w - x))
    label(p, c.right - PAD, y, "▴" if view.panel_open else "▾", px=13, color_=CPU, align=R)
    # [ END INTERVIEW ]
    e = end_rect(strip)
    _box(p, e, color("#6e5a9e"))
    text(p, e.x + e.w / 2, e.y + 18, "[ END INTERVIEW ]", key="cond", px=14, color_="#d8c7ff",
         spacing=0.1, align=C)
    # linha de baixo
    y2 = strip.y + ROW_H + 24
    st = m.get("state")
    if st == "preparing":
        w = label(p, strip.x + PAD, y2, stage_line(m, at, now), px=11, color_=TEXT_DIM).width()
        paint_bar(p, strip.x + PAD + w + 14, min(strip.right, strip.x + PAD + w + 14 + 240),
                  y2 - 4, frame(at, now))
    elif st == "error":
        right = retry_rect(strip).left - GAP if can_retry(m) else strip.right
        label(p, strip.x + PAD, y2, stage_line(m, at, now), px=11, color_=HOT, upper=False,
              max_w=max(0.0, right - strip.x - PAD))
        if can_retry(m):
            r = retry_rect(strip)
            _box(p, r, color(HOT))
            label(p, r.x + r.w / 2, r.y + 15, "[ RETRY ]", px=11, color_=TEXT, align=C)
    else:
        line = stage_text(m) or "STAGE —"
        tail = " · PAUSED" if st == "paused" else ""
        if st == "debriefing":
            line, tail = stage_line(m, at, now), ""
        else:
            label(p, strip.right, y2, clock_text(elapsed(m, at, now)), px=13, color_=CPU, align=R)
        label(p, strip.x + PAD, y2, line + tail, px=12, color_=TEXT, upper=False,
              max_w=max(0.0, strip.w - PAD - 70))
    if view.panel_open:
        paint_panel(p, panel_rect(strip, m), m, panel_chars(strip))


def paint_panel(p, r: Rect, m: Mapping[str, Any], chars: int) -> None:
    """Painel do perfil: cabeçalho ``JOB PROFILE // 求人`` + ``ESC``, senioridade, stack e
    requisitos obrigatórios (marcador lilás)."""
    from PySide6.QtCore import QRectF

    from . import kit
    from .main_screen import R, label, text
    from .theme import CPU, LINE, LINE_STRONG, PANEL, TEXT, TEXT_DIM, color

    kit.panel(p, QRectF(r.x, r.y, r.w, r.h), fill=PANEL, border=LINE_STRONG, accent=CPU)
    hb = r.y + PANEL_HEAD - 12
    w = text(p, r.x + PAD, hb, "JOB PROFILE", key="cond", px=15, weight=600, spacing=0.12,
             color_=TEXT).width()
    text(p, r.x + PAD + w + 10, hb, "求人", key="jp", px=10, color_=TEXT_DIM)
    label(p, r.right - PAD, hb, "ESC", px=10, color_=TEXT_DIM, align=R)
    p.fillRect(QRectF(r.x + PAD, r.y + PANEL_HEAD - 3, r.w - 2 * PAD, 1), color(LINE))
    y = r.y + PANEL_HEAD + 14
    for style, s in profile_rows(m, chars):
        if style == "head":
            label(p, r.x + PAD, y, s, px=10, color_=CPU)
        elif style == "item":
            text(p, r.x + PAD, y, "•", px=12, color_=CPU)
            text(p, r.x + PAD + 14, y, s, px=12, color_=TEXT, max_w=r.w - 2 * PAD - 14)
        else:
            text(p, r.x + PAD, y, s, px=12, color_=TEXT if style == "text" else TEXT_DIM,
                 max_w=r.w - 2 * PAD)
        y += PANEL_LINE
