"""Rosto da Magui feito de caracteres (estilo kaomoji), desenhado com QPainter.

Não depende da classe HUD: quem integra chama `set_*` quando chegam mensagens, `tick(now)` no
timer (redesenha a região do rosto só quando ele pede) e `paint(painter, rect, accent)` no
paintEvent. Acordada, a animação pede no máximo 30 quadros/s; dormindo, 1 quadro a cada 4 s
(R17.3, R17.4).

    face = Face()
    face.set_state("speaking"); face.set_mouth_level(0.42); face.set_subtitle("…")
    redraw, deadline = face.tick(time.monotonic())
    face.paint(painter, QRectF(...), theme.accent)
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QRadialGradient

EXPRESSIONS = ("sleeping", "listening", "thinking", "speaking", "happy", "confused", "alert")

FPS_AWAKE = 30.0
SLEEP_PERIOD = 4.0  # R17.4: dormindo, no máximo 1 redesenho a cada 4 s
BLINK_EVERY = (3.0, 6.0)
BLINK_LEN = 0.12
GLANCE_EVERY = (5.0, 12.0)
GLANCE_LEN = (0.7, 1.5)
FADE_LEN = 0.15

WHITE = QColor("#f4ede4")
GLYPH_FAMILIES = ["Noto Sans Mono CJK JP", "Noto Sans CJK JP", "Noto Sans Mono", "Hack", "monospace"]
SERIF_FAMILIES = ["Noto Serif CJK JP", "Noto Serif", "serif"]


def mouth_for_level(level: float) -> str:
    """Boca falando conforme o volume (0..1): < 0,15 "—", < 0,5 "o", senão "O" (R17.2)."""
    if level < 0.15:
        return "—"
    if level < 0.5:
        return "o"
    return "O"


@dataclass(frozen=True)
class Look:
    eyes: str  # glifo dos dois olhos
    mouth: str
    extra: str = ""  # símbolo flutuante (z z, ?, !, · · ·)
    eye_scale: float = 1.0
    mouth_scale: float = 1.0
    blinks: bool = True
    # sobrancelhas "⌒": (subida, inclinação em graus) da esquerda e da direita
    brows: tuple[tuple[float, float], tuple[float, float]] = ((0.0, 0.0), (0.0, 0.0))


LOOKS = {
    "sleeping": Look("—", "‿", "z z", eye_scale=0.8, blinks=False,
                     brows=((-0.04, 6.0), (-0.04, -6.0))),
    "listening": Look("◉", "—", eye_scale=0.9, mouth_scale=0.8, brows=((0.05, 0.0), (0.05, 0.0))),
    "thinking": Look("◔", "~", "· · ·", brows=((0.10, -8.0), (-0.02, 6.0))),
    "speaking": Look("◕", "—"),
    "happy": Look("^", "‿", eye_scale=1.05, blinks=False, brows=((0.08, -4.0), (0.08, 4.0))),
    "confused": Look("•", "_", "?", eye_scale=1.0, mouth_scale=1.3,
                     brows=((-0.02, 12.0), (0.12, -6.0))),
    "alert": Look("⊙", "□", "!", eye_scale=1.0, mouth_scale=0.75,
                  brows=((0.16, -6.0), (0.16, 6.0))),
}


def legible(accent: QColor) -> QColor:
    """Clareia cores muito escuras (azul/roxo puros) para não sumirem no fundo preto."""
    c = QColor(accent)

    def lin(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    for _ in range(40):
        if 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue()) >= 0.2:
            break
        c = QColor(c.red() + (255 - c.red()) // 10 + 1, c.green() + (255 - c.green()) // 10 + 1,
                   c.blue(), c.alpha())
    return c


def _font(families: list[str], px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(families)
    f.setPixelSize(max(1, round(px)))
    f.setWeight(weight)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return f


def wrap_lines(text: str, fm: QFontMetricsF, width: float, max_lines: int = 2) -> list[str]:
    """Quebra por palavras (ou por caractere, para texto sem espaço) em até `max_lines`.

    Se não couber, mantém o FIM do texto (legenda ao vivo) e começa com "…".
    """
    text = " ".join(text.split())
    if not text:
        return []
    lines: list[str] = []
    cur = ""
    for word in text.split(" "):
        cand = f"{cur} {word}" if cur else word
        if fm.horizontalAdvance(cand) <= width:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        cur = ""
        for ch in word:  # palavra maior que a linha (ou japonês sem espaços)
            if fm.horizontalAdvance(cur + ch) > width and cur:
                lines.append(cur)
                cur = ""
            cur += ch
    if cur:
        lines.append(cur)
    if len(lines) <= max_lines:
        return lines
    lines = lines[-max_lines:]
    first = lines[0]
    while first and fm.horizontalAdvance("…" + first) > width:
        first = first[1:]
    lines[0] = "…" + first.lstrip()
    return lines


class Face:
    """Estado e desenho do rosto. Tempo em segundos de `time.monotonic()`."""

    def __init__(self, state: str = "sleeping", rng: random.Random | None = None,
                 now: float | None = None):
        if state not in LOOKS:
            raise ValueError(f"expressão desconhecida: {state}")
        self._rng = rng or random.Random()
        self._now = time.monotonic() if now is None else now
        self.state = state
        self._prev: str | None = None  # expressão saindo durante o fade
        self._fade_start = -1.0
        self.mouth_level = 0.0
        self.subtitle = ""
        self._blink_at = self._now + self._rng.uniform(*BLINK_EVERY)
        self._glance_at = self._now + self._rng.uniform(*GLANCE_EVERY)
        self._glance_end = -1.0
        self._glance_dir = 0
        self._dirty = True
        self._force = False  # troca de expressão: redesenha já, mesmo entrando no sono
        self._last_key: tuple | None = None
        self._last_draw = -math.inf
        self._fonts: dict[tuple, QFont] = {}

    # ------------------------------------------------------------ entrada

    def set_state(self, expr: str) -> None:
        if expr not in LOOKS:
            raise ValueError(f"expressão desconhecida: {expr}")
        if expr == self.state:
            return
        # entrar no sono é instantâneo (sem fade a 30 fps); acordar faz cross-fade
        self._prev = None if expr == "sleeping" else self.state
        self._fade_start = self._now
        self.state = expr
        if self.state != "sleeping":
            self._blink_at = max(self._blink_at, self._now + 0.8)
        self._dirty = True
        self._force = True

    def set_mouth_level(self, level: float) -> None:
        self.mouth_level = min(1.0, max(0.0, float(level)))

    def set_subtitle(self, text: str) -> None:
        text = text or ""
        if text != self.subtitle:
            self.subtitle = text
            self._dirty = True

    @property
    def sleeping(self) -> bool:
        return self.state == "sleeping"

    # ------------------------------------------------------------ animação

    def _advance(self, now: float) -> None:
        """Agenda piscadas e olhares; só anda quando acordada."""
        if self.sleeping:
            return
        while now >= self._blink_at + BLINK_LEN:
            self._blink_at += self._rng.uniform(*BLINK_EVERY)
            if self._blink_at + BLINK_LEN <= now:  # dormiu/acordou: reagenda a partir de agora
                self._blink_at = now + self._rng.uniform(*BLINK_EVERY)
        while now >= self._glance_at:
            self._glance_end = self._glance_at + self._rng.uniform(*GLANCE_LEN)
            self._glance_dir = self._rng.choice((-1, 1))
            self._glance_at = self._glance_end + self._rng.uniform(*GLANCE_EVERY)
            if self._glance_at <= now:
                self._glance_at = now + self._rng.uniform(*GLANCE_EVERY)

    def _blinking(self, now: float) -> bool:
        return (not self.sleeping and LOOKS[self.state].blinks
                and self._blink_at <= now < self._blink_at + BLINK_LEN)

    def _glance(self, now: float) -> int:
        if self.sleeping or self.state == "alert" or now >= self._glance_end:
            return 0
        return self._glance_dir

    def _fade(self, now: float) -> float:
        """Progresso 0..1 do cross-fade; 1 quando não há transição."""
        if self._prev is None:
            return 1.0
        p = (now - self._fade_start) / FADE_LEN
        if p >= 1.0:
            self._prev = None
            return 1.0
        return max(0.0, p)

    def _mouth(self, expr: str) -> str:
        if expr == "speaking":
            return mouth_for_level(self.mouth_level)
        return LOOKS[expr].mouth

    def _phase(self, now: float) -> int:
        """Fase dos símbolos animados (z z sobe, · · · enche)."""
        if self.sleeping:
            return int(now // SLEEP_PERIOD) % 2
        if self.state == "thinking":
            return int(now / 0.4) % 3
        return 0

    def _key(self, now: float) -> tuple:
        fade = self._fade(now)
        return (self.state, self._prev, round(fade * 12) if fade < 1 else 12,
                self._blinking(now), self._glance(now), self._mouth(self.state),
                self._phase(now), self.subtitle)

    def tick(self, now: float | None = None) -> tuple[bool, float]:
        """Avança a animação. Retorna (precisa_redesenhar, próximo_prazo).

        `próximo_prazo` é o instante (mesmo relógio de `now`) em que vale chamar `tick` de novo.
        Acordada nunca pede mais que 30 quadros/s; dormindo, no máximo 1 a cada 4 s.
        """
        now = time.monotonic() if now is None else now
        self._now = now
        frame = 1.0 / FPS_AWAKE
        if self.sleeping:
            nxt = self._last_draw + SLEEP_PERIOD
            if self._force:
                self._commit(now, self._key(now))
                return True, now + SLEEP_PERIOD
            if now < nxt:
                return False, nxt
            key = self._key(now)
            if self._dirty or key != self._last_key:
                self._commit(now, key)
                return True, now + SLEEP_PERIOD
            # nada mudou: acorda de novo na virada da fase do "z z"
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
        if self._prev is not None or self.state == "speaking":
            return now + frame  # fade em curso ou boca seguindo o áudio (R17.2: >= 15/s)
        events = [self._blink_at, self._blink_at + BLINK_LEN, self._glance_at]
        if self._glance_end > now:
            events.append(self._glance_end)
        if self.state == "thinking":
            events.append((now // 0.4 + 1) * 0.4)
        nxt = min(e for e in events if e > now) if any(e > now for e in events) else now + 1.0
        return max(nxt, now + frame)

    # ------------------------------------------------------------ desenho

    def font(self, kind: str, px: float) -> QFont:
        """Fontes em cache: "glyph" (mono CJK), "serif" (legenda) e "thin" (contorno)."""
        key = (kind, round(px))
        f = self._fonts.get(key)
        if f is None:
            if kind == "serif":
                f = _font(SERIF_FAMILIES, px, QFont.Weight.Medium)
            elif kind == "thin":
                f = _font(SERIF_FAMILIES, px, QFont.Weight.ExtraLight)
            else:
                f = _font(GLYPH_FAMILIES, px, QFont.Weight.Normal)
            self._fonts[key] = f
        return f

    def _glyph(self, p: QPainter, center: QPointF, text: str, px: float, color: QColor,
               kind: str = "glyph", angle: float = 0.0) -> None:
        p.setFont(self.font(kind, px))
        p.setPen(color)
        box = QRectF(-px * 2, -px, px * 4, px * 2)
        p.save()
        p.translate(center)
        if angle:
            p.rotate(angle)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.restore()

    def paint(self, painter: QPainter, rect: QRectF, accent: QColor,
              subtitle: bool | None = None) -> None:
        """Desenha o rosto e a legenda dentro de `rect`, sem fundo.

        `accent` é a cor do tema (bochechas e detalhes). `subtitle=None` mostra a legenda só
        quando o retângulo tem altura para ela (>= 200 px); o rosto pequeno do cabeçalho fica limpo.
        """
        now = self._now
        if subtitle is None:
            subtitle = rect.height() >= 200
        accent = legible(accent)
        p = painter
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setClipRect(rect)

        sub_px = min(52.0, max(9.0, rect.height() * 0.036))
        sub_h = sub_px * 1.4 * 2 + sub_px * 0.8 if subtitle else 0.0
        face_h = 1.8 if not subtitle else 2.05  # com legenda, deixa um respiro abaixo do contorno
        s = min(rect.width() / 3.3, (rect.height() - sub_h) / face_h)
        top = rect.y() + (rect.height() - face_h * s - sub_h) / 2  # rosto + legenda centrados juntos
        c = QPointF(rect.center().x(), top + 0.92 * s)
        sub_area = QRectF(rect.x(), top + face_h * s, rect.width(), sub_h)

        fade = self._fade(now)
        if self._prev is not None and fade < 1.0:
            ease = fade * fade * (3 - 2 * fade)
            p.setOpacity(1.0 - ease)
            self._paint_face(p, c, s, accent, self._prev, now, current=False)
            p.setOpacity(ease)
        self._paint_face(p, c, s, accent, self.state, now)
        p.setOpacity(1.0)

        if subtitle and self.subtitle:
            self._paint_subtitle(p, sub_area, sub_px)
        p.restore()

    def _paint_face(self, p: QPainter, c: QPointF, s: float, accent: QColor, expr: str,
                    now: float, current: bool = True) -> None:
        look = LOOKS[expr]
        white = QColor(WHITE)
        soft = QColor(WHITE)
        soft.setAlphaF(0.85)
        dim = QColor(WHITE)
        dim.setAlphaF(0.38)
        blink = current and self._blinking(now)
        glance = self._glance(now) if current else 0
        phase = self._phase(now) if current else 0
        dx = glance * 0.08 * s

        # contorno: parênteses finos, como num kaomoji
        for sx, ch in ((-1, "("), (1, ")")):
            self._glyph(p, QPointF(c.x() + sx * 1.12 * s, c.y() + 0.02 * s), ch, 1.5 * s, dim, "thin")

        # bochechas: brilho suave + "//" na cor do tema
        for sx in (-1, 1):
            bc = QPointF(c.x() + sx * 0.70 * s, c.y() + 0.20 * s)
            g = QRadialGradient(bc, 0.30 * s)
            glow = QColor(accent)
            glow.setAlphaF(0.34)
            g.setColorAt(0.0, glow)
            glow.setAlphaF(0.0)
            g.setColorAt(1.0, glow)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawEllipse(bc, 0.32 * s, 0.22 * s)
            self._glyph(p, bc, "//", 0.22 * s, accent)

        # sobrancelhas e olhos
        ex, ey = 0.46 * s, c.y() - 0.14 * s
        eye = "—" if blink else look.eyes
        epx = 0.52 * s * (0.7 if blink else look.eye_scale)
        for i, sx in enumerate((-1, 1)):
            rise, tilt = look.brows[i]
            bp = QPointF(c.x() + sx * (ex + 0.02 * s) + dx * 0.5, ey - (0.38 + rise) * s)
            self._glyph(p, bp, "⌒", 0.34 * s, soft, angle=tilt)
            self._glyph(p, QPointF(c.x() + sx * ex + dx, ey), eye, epx, white)

        # boca ("o"/"O" na serifada, mais redondos que os da mono)
        mouth = self._mouth(expr)
        kind = "serif" if mouth in ("o", "O") else "glyph"
        mpx = 0.40 * s * look.mouth_scale * (0.95 if kind == "serif" else 1.0)
        self._glyph(p, QPointF(c.x() + dx * 0.4, c.y() + 0.36 * s), mouth, mpx, white, kind)

        # detalhe flutuante, na cor do tema
        if expr == "sleeping":
            for i, (ox, oy, k) in enumerate(((1.28, -0.50, 0.24), (1.42, -0.80, 0.32))):
                lift = 0.07 * s if (phase + i) % 2 else 0.0
                col = QColor(accent)
                col.setAlphaF(0.6 + 0.4 * i)
                self._glyph(p, QPointF(c.x() + ox * s, c.y() + oy * s - lift), "z", k * s, col)
        elif expr == "thinking":
            for i in range(phase + 1):
                self._glyph(p, QPointF(c.x() + (1.28 + 0.16 * i) * s, c.y() - (0.55 + 0.12 * i) * s),
                            "·", (0.30 + 0.06 * i) * s, accent)
        elif look.extra:
            self._glyph(p, QPointF(c.x() + 1.38 * s, c.y() - 0.66 * s), look.extra, 0.44 * s,
                        accent, angle=12.0)

    def _paint_subtitle(self, p: QPainter, area: QRectF, px: float) -> None:
        font = self.font("serif", px)
        fm = QFontMetricsF(font)
        width = area.width() * 0.92
        lines = wrap_lines(self.subtitle, fm, width)
        p.setFont(font)
        p.setPen(QColor(WHITE))
        lh = px * 1.35
        top = area.y() + px * 0.4
        for i, line in enumerate(lines):
            box = QRectF(area.x(), top + i * lh, area.width(), lh)
            p.drawText(box, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, line)
