"""Mascote vetorial do canvas "wired" (R23.4) com as 7 expressões do R17.

Desenho no viewBox 260×150 do canvas: parênteses `deco`, sobrancelhas, olhos, rubor em 4 traços
na cor de acento (R17.6) e boca. Falando, a boca segue o nível da voz: < 0,15 "—", < 0,5 "o",
senão "O" (R17.2). Acordada pisca e olha para os lados a até 30 fps (R17.3); dormindo redesenha
no máximo 1 vez a cada 4 s (R17.4). A API espelha `hud/face.py` (`set_state`/`set_mouth_level`
continuam como apelidos); a legenda fica com a tela (U3).
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from . import fonts
from .theme import DECO, TEXT, TEXT_DIM, WARN, color

EXPRESSIONS = ("sleeping", "listening", "thinking", "speaking", "happy", "confused", "alert")
VIEW_W, VIEW_H = 260.0, 150.0

FPS_AWAKE = 30.0
SLEEP_PERIOD = 4.0  # R17.4
BLINK_EVERY = (3.0, 6.0)
BLINK_LEN = 0.12
GLANCE_EVERY = (5.0, 12.0)
GLANCE_LEN = (0.7, 1.5)
GLANCE_DX = 4.0  # deslocamento das pupilas (unidades do viewBox)
THINK_STEP = 0.4  # "· · ·" enchendo

EYE_L, EYE_R, EYE_Y = 92.0, 168.0, 66.0


def mouth_for_level(level: float) -> str:
    """< 0,15 "—" fechada, < 0,5 "o" pequena, senão "O" grande (R17.2, igual ao face.py)."""
    if level < 0.15:
        return "—"
    if level < 0.5:
        return "o"
    return "O"


@dataclass(frozen=True)
class Look:
    eyes: str  # line | ring | happy | confused | wide
    mouth: str  # smile | — | o | O | wave | grin | zigzag | square
    extra: str = ""  # zz | dots | ? | !
    blinks: bool = True
    # sobrancelhas: (deslocamento y, inclinação em graus) da esquerda e da direita
    brows: tuple[tuple[float, float], tuple[float, float]] = ((0.0, 0.0), (0.0, 0.0))
    gaze: tuple[float, float] = (0.0, 0.0)  # olhar fixo da expressão
    glances: bool = True


LOOKS = {
    "sleeping": Look("line", "smile", "zz", blinks=False, brows=((2.0, 0.0), (2.0, 0.0)),
                     glances=False),
    "listening": Look("ring", "—"),
    "thinking": Look("ring", "wave", "dots", brows=((-5.0, -8.0), (2.0, 6.0)), gaze=(2.5, -3.0)),
    "speaking": Look("ring", "—"),
    "happy": Look("happy", "grin", blinks=False, brows=((-4.0, -6.0), (-4.0, 6.0))),
    "confused": Look("confused", "zigzag", "?", brows=((3.0, 12.0), (-6.0, -6.0)), gaze=(-1.5, 0.0)),
    "alert": Look("wide", "square", "!", brows=((-8.0, 8.0), (-8.0, -8.0)), glances=False),
}


class Mascot:
    """Estado e desenho do mascote. Tempo em segundos de `time.monotonic()`."""

    def __init__(self, state: str = "sleeping", rng: random.Random | None = None,
                 now: float | None = None):
        if state not in LOOKS:
            raise ValueError(f"expressão desconhecida: {state}")
        self._rng = rng or random.Random()
        self._now = time.monotonic() if now is None else now
        self.state = state
        self.level = 0.0
        self._blink_at = self._now + self._rng.uniform(*BLINK_EVERY)
        self._glance_at = self._now + self._rng.uniform(*GLANCE_EVERY)
        self._glance_end = -1.0
        self._glance_dir = 0
        self._dirty = True
        self._force = False
        self._last_key: tuple | None = None
        self._last_draw = -math.inf
        self.reaction = None  # reactions.Reaction em curso (só o retrato em partes usa)
        self.reaction_until = 0.0
        self.layout = "main"  # "main" (painel) ou "idle" (espera): para onde fica cada painel

    # ------------------------------------------------------------ entrada

    def set_expression(self, expr: str) -> None:
        if expr not in LOOKS:
            raise ValueError(f"expressão desconhecida: {expr}")
        if expr == self.state:
            return
        self.state = expr
        if expr != "sleeping":
            self._blink_at = max(self._blink_at, self._now + 0.8)
        self._dirty = True
        self._force = True  # troca de expressão redesenha já, mesmo entrando no sono

    def set_level(self, level: float) -> None:
        self.level = min(1.0, max(0.0, float(level)))

    def react(self, reaction, until: float) -> None:
        """Reação ao HUD/música (``wired.reactions``) até ``until`` (monotonic); None limpa."""
        if reaction is not self.reaction:
            self._dirty = True
        self.reaction, self.reaction_until = reaction, until

    set_state = set_expression  # mesma API do face.py
    set_mouth_level = set_level

    @property
    def sleeping(self) -> bool:
        return self.state == "sleeping"

    @property
    def mouth(self) -> str:
        """Boca atual: falando, "—"/"o"/"O" pelo nível; senão a da expressão."""
        if self.state == "speaking":
            return mouth_for_level(self.level)
        return LOOKS[self.state].mouth

    # ------------------------------------------------------------ animação

    def _advance(self, now: float) -> None:
        if self.sleeping:
            return
        while now >= self._blink_at + BLINK_LEN:
            self._blink_at += self._rng.uniform(*BLINK_EVERY)
            if self._blink_at + BLINK_LEN <= now:
                self._blink_at = now + self._rng.uniform(*BLINK_EVERY)
        while now >= self._glance_at:
            self._glance_end = self._glance_at + self._rng.uniform(*GLANCE_LEN)
            self._glance_dir = self._rng.choice((-1, 1))
            self._glance_at = self._glance_end + self._rng.uniform(*GLANCE_EVERY)
            if self._glance_at <= now:
                self._glance_at = now + self._rng.uniform(*GLANCE_EVERY)

    def blinking(self, now: float | None = None) -> bool:
        now = self._now if now is None else now
        return (not self.sleeping and LOOKS[self.state].blinks
                and self._blink_at <= now < self._blink_at + BLINK_LEN)

    def glance(self, now: float | None = None) -> int:
        now = self._now if now is None else now
        if not LOOKS[self.state].glances or now >= self._glance_end:
            return 0
        return self._glance_dir

    def phase(self, now: float | None = None) -> int:
        """Fase dos símbolos animados ("zz" sobe a cada 4 s, "· · ·" enche)."""
        now = self._now if now is None else now
        if self.sleeping:
            return int(now // SLEEP_PERIOD) % 2
        if self.state == "thinking":
            return int(now / THINK_STEP) % 3
        return 0

    def _key(self, now: float) -> tuple:
        return (self.state, self.blinking(now), self.glance(now), self.mouth, self.phase(now))

    def tick(self, now: float | None = None) -> tuple[bool, float]:
        """Avança a animação. Retorna (precisa_redesenhar, próximo_prazo), como `Face.tick`.

        Acordada: no máximo 30 quadros/s. Dormindo: no máximo 1 redesenho a cada 4 s.
        """
        now = time.monotonic() if now is None else now
        self._now = now
        frame = 1.0 / FPS_AWAKE
        if self.sleeping:
            if self._force:
                self._commit(now, self._key(now))
                return True, now + SLEEP_PERIOD
            nxt = self._last_draw + SLEEP_PERIOD
            if now < nxt:
                return False, nxt
            key = self._key(now)
            if self._dirty or key != self._last_key:
                self._commit(now, key)
                return True, now + SLEEP_PERIOD
            return False, (now // SLEEP_PERIOD + 1) * SLEEP_PERIOD
        if now - self._last_draw < frame - 1e-6:
            return False, self._last_draw + frame
        self._advance(now)
        key = self._key(now)
        redraw = self._dirty or key != self._last_key
        if redraw:
            self._commit(now, key)
        return redraw, self._next_event(now, frame)

    def _commit(self, now: float, key: tuple) -> None:
        self._dirty = False
        self._force = False
        self._last_key = key
        self._last_draw = now

    def _next_event(self, now: float, frame: float) -> float:
        if self.state == "speaking":
            return now + frame  # boca seguindo o áudio (R17.2: >= 15/s)
        events = [self._blink_at, self._blink_at + BLINK_LEN, self._glance_at]
        if self._glance_end > now:
            events.append(self._glance_end)
        if self.state == "thinking":
            events.append((now // THINK_STEP + 1) * THINK_STEP)
        future = [e for e in events if e > now]
        return max(min(future) if future else now + 1.0, now + frame)

    # ------------------------------------------------------------ desenho

    @staticmethod
    def view_rect(rect: QRectF) -> QRectF:
        """Área ocupada pelo viewBox 260×150 dentro de `rect` (encaixe centrado, sem distorcer)."""
        r = QRectF(rect)
        k = min(r.width() / VIEW_W, r.height() / VIEW_H)
        w, h = VIEW_W * k, VIEW_H * k
        return QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h)

    def paint(self, p: QPainter, rect: QRectF, accent: str | QColor, now: float | None = None) -> None:
        now = self._now if now is None else now
        look = LOOKS[self.state]
        v = self.view_rect(rect)
        k = v.width() / VIEW_W
        p.save()
        p.translate(v.topLeft())
        p.scale(k, k)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.NoBrush)
        text_c, acc = color(TEXT), color(accent)

        # parênteses
        pen = QPen(color(DECO), 7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for x0, cx in ((44, 14), (216, 246)):
            path = QPainterPath(QPointF(x0, 18))
            path.quadTo(QPointF(cx, 75), QPointF(x0, 132))
            p.drawPath(path)

        # sobrancelhas (arco do canvas, deslocado/inclinado por expressão)
        pen = QPen(text_c, 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for cx, (dy, tilt) in zip((EYE_L, EYE_R), look.brows, strict=True):
            p.save()
            p.translate(cx, 42 + dy)
            p.rotate(tilt)
            path = QPainterPath(QPointF(-14, 2))
            path.quadTo(QPointF(0, -8), QPointF(14, 2))
            p.drawPath(path)
            p.restore()

        # olhos
        gx = look.gaze[0] + GLANCE_DX * self.glance(now)
        gy = look.gaze[1]
        eyes = "line" if self.blinking(now) else look.eyes
        self._eyes(p, eyes, gx, gy, text_c)

        # rubor: 4 traços na cor de acento
        p.setPen(QPen(acc, 2.4))
        for x in (80, 90, 162, 172):
            p.drawLine(QPointF(x, 94), QPointF(x + 8, 84))

        self._mouth(p, self.mouth, text_c)
        self._extra(p, look.extra, self.phase(now))
        p.restore()

    @staticmethod
    def _eyes(p: QPainter, kind: str, gx: float, gy: float, c: QColor) -> None:
        if kind == "line":
            p.setPen(QPen(c, 4))
            for cx in (EYE_L, EYE_R):
                p.drawLine(QPointF(cx - 16, EYE_Y), QPointF(cx + 16, EYE_Y))
            return
        if kind == "happy":  # ^ ^
            pen = QPen(c, 3.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            for cx in (EYE_L, EYE_R):
                path = QPainterPath(QPointF(cx - 12, EYE_Y + 5))
                path.quadTo(QPointF(cx, EYE_Y - 13), QPointF(cx + 12, EYE_Y + 5))
                p.drawPath(path)
            return
        radii = {"ring": (8, 8), "confused": (6, 9), "wide": (10, 10)}[kind]
        pupil = 2.5 if kind == "wide" else 3.0
        for cx, r in zip((EYE_L, EYE_R), radii, strict=True):
            p.setPen(QPen(c, 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, EYE_Y), r, r)
            lim = max(0.0, r - pupil - 1.0)
            dx, dy = max(-lim, min(lim, gx)), max(-lim, min(lim, gy))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(cx + dx, EYE_Y + dy), pupil, pupil)
        p.setBrush(Qt.BrushStyle.NoBrush)

    @staticmethod
    def _mouth(p: QPainter, kind: str, c: QColor) -> None:
        pen = QPen(c, 2.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        if kind == "smile":  # canvas: M122 108 Q 130 116 138 108
            path.moveTo(122, 108)
            path.quadTo(130, 116, 138, 108)
        elif kind == "grin":
            path.moveTo(116, 104)
            path.quadTo(130, 122, 144, 104)
        elif kind == "—":
            path.moveTo(122, 110)
            path.lineTo(138, 110)
        elif kind == "o":
            path.addEllipse(QPointF(130, 110), 4.5, 4.0)
        elif kind == "O":
            path.addEllipse(QPointF(130, 112), 7.0, 9.0)
        elif kind == "wave":
            path.moveTo(120, 110)
            path.cubicTo(124, 104, 128, 104, 130, 110)
            path.cubicTo(132, 116, 136, 116, 140, 110)
        elif kind == "zigzag":
            path.moveTo(119, 110)
            for i, x in enumerate((124.5, 130, 135.5, 141)):
                path.lineTo(x, 106 if i % 2 == 0 else 111)
        elif kind == "square":
            path.addRect(QRectF(124.5, 104, 11, 10))
        p.drawPath(path)

    @staticmethod
    def _extra(p: QPainter, kind: str, phase: int) -> None:
        if not kind:
            return
        dim = color(TEXT_DIM)
        if kind == "zz":
            dy = -3 if phase else 0
            p.setPen(dim)
            p.setFont(fonts.font("mono", 16))
            p.drawText(QPointF(226, 22 + dy), "z")
            p.setFont(fonts.font("mono", 12))
            p.drawText(QPointF(238, 10 + dy), "z")
        elif kind == "dots":
            p.setPen(Qt.PenStyle.NoPen)
            for i, x in enumerate((224, 234, 244)):
                c = QColor(dim)
                if i > phase:
                    c.setAlphaF(0.25)
                p.setBrush(c)
                p.drawEllipse(QPointF(x, 16), 2.4, 2.4)
            p.setBrush(Qt.BrushStyle.NoBrush)
        elif kind == "?":
            p.setPen(dim)
            p.setFont(fonts.font("mono", 22, 500))
            p.drawText(QPointF(228, 26), "?")
        elif kind == "!":
            p.setPen(color(WARN))
            p.setFont(fonts.font("mono", 22, 500))
            p.drawText(QPointF(232, 26), "!")
