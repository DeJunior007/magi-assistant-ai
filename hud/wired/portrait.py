"""Retrato da Condessa em camadas de imagem (busto anime), no lugar do mascote vetorial.

Mesma API e mesmo relógio do `Mascot` (piscar, olhar para os lados, boca pela voz, ≤ 30 fps
acordada, 1 redesenho a cada 4 s dormindo); só o desenho muda: em vez de traços, empilha PNGs com
fundo transparente, todos do mesmo tamanho e alinhados (um "canvas" comum):

    ~/.local/share/magi/condessa/          (ou $MAGI_PORTRAIT_DIR)
      base.png                 busto sem olhos e boca            obrigatório
      base/<expr>.png          busto de uma expressão            opcional (rubor, suor...)
      eyes/open.png            olhos abertos                     obrigatório
      eyes/half.png            meio fechados (piscada)           opcional (usa closed)
      eyes/closed.png          fechados (piscada e dormindo)     obrigatório
      eyes/<expr>/open.png ... olhos de uma expressão            opcional
      mouth/closed.png         boca fechada                      obrigatório
      mouth/small.png          entreaberta (fala baixa)          opcional (usa open)
      mouth/open.png           aberta (fala alta)                obrigatório
      mouth/<expr>.png         boca parada de uma expressão      opcional (sorriso, "o" do susto)
      extra/<expr>.png         por cima de tudo (zz, ?, !)       opcional
      portrait.toml            ajustes                           opcional

``<expr>`` é uma das 7 expressões (sleeping, listening, thinking, speaking, happy, confused,
alert). ``portrait.toml``: ``gaze_px`` (deslocamento dos olhos ao olhar para o lado, em pixels do
canvas, padrão 6), ``breath_px`` (sobe-e-desce do busto acordada, padrão 2; 0 desliga),
``breath_period`` (s, padrão 4.5) e ``fit`` ("contain" = inteiro no retângulo, padrão; "cover" =
preenche e corta as bordas).

Desempenho: cada combinação (expressão, olhos, boca, olhar, tamanho) é composta uma vez num
QPixmap do tamanho do dispositivo e reaproveitada; o quadro só desenha um pixmap.
"""

from __future__ import annotations

import logging
import math
import os
import random
import time
import tomllib
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

from .mascot import BLINK_LEN, EXPRESSIONS, FPS_AWAKE, Mascot

log = logging.getLogger(__name__)

DEFAULT_DIR = Path.home() / ".local/share/magi/condessa"
REQUIRED = ("base.png", "eyes/open.png", "eyes/closed.png", "mouth/closed.png", "mouth/open.png")
BREATH_FPS = 8.0
MOUTH_FILES = {"—": "closed", "o": "small", "O": "open"}


def portrait_dir() -> Path:
    return Path(os.environ.get("MAGI_PORTRAIT_DIR") or DEFAULT_DIR).expanduser()


def missing(folder: Path) -> list[str]:
    """Arquivos obrigatórios que faltam em ``folder`` (vazio = dá para usar)."""
    return [f for f in REQUIRED if not (folder / f).is_file()]


class PortraitAssets:
    """Camadas carregadas de uma pasta (ver o docstring do módulo)."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        if lacking := missing(self.folder):
            raise FileNotFoundError(f"retrato incompleto em {self.folder}: falta {', '.join(lacking)}")
        cfg_file = self.folder / "portrait.toml"
        cfg = tomllib.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.is_file() else {}
        self.gaze_px = float(cfg.get("gaze_px", 6))
        self.breath_px = float(cfg.get("breath_px", 2))
        self.breath_period = float(cfg.get("breath_period", 4.5))
        self.fit = str(cfg.get("fit", "contain"))
        self._cache: dict[str, QPixmap | None] = {}
        base = self.layer("base.png")
        assert base is not None
        self.size = base.size()

    def layer(self, rel: str) -> QPixmap | None:
        if rel not in self._cache:
            path = self.folder / rel
            pm = QPixmap(str(path)) if path.is_file() else None
            if pm is not None and pm.isNull():
                log.warning("retrato: não consegui ler %s", path)
                pm = None
            self._cache[rel] = pm
        return self._cache[rel]

    def first(self, *names: str) -> QPixmap | None:
        for n in names:
            if (pm := self.layer(n)) is not None:
                return pm
        return None

    def base(self, expr: str) -> QPixmap:
        pm = self.first(f"base/{expr}.png", "base.png")
        assert pm is not None
        return pm

    def eyes(self, expr: str, frame: str) -> QPixmap | None:
        alt = {"half": "closed"}.get(frame, frame)
        return self.first(f"eyes/{expr}/{frame}.png", f"eyes/{frame}.png",
                          f"eyes/{expr}/{alt}.png", f"eyes/{alt}.png")

    def mouth(self, expr: str, kind: str) -> QPixmap | None:
        """``kind``: "closed"/"small"/"open" (fala) ou "rest" (boca parada da expressão)."""
        if kind == "rest":
            return self.first(f"mouth/{expr}.png", "mouth/closed.png")
        alt = {"small": "open"}.get(kind, kind)
        return self.first(f"mouth/{kind}.png", f"mouth/{alt}.png")

    def extra(self, expr: str) -> QPixmap | None:
        return self.layer(f"extra/{expr}.png")


class Portrait(Mascot):
    """`Mascot` desenhado com as camadas de ``PortraitAssets``."""

    def __init__(self, assets: PortraitAssets, state: str = "sleeping", rng: random.Random | None = None,
                 now: float | None = None):
        super().__init__(state, rng, now)
        self.assets = assets

    # -- quadros
    def eye_frame(self, now: float | None = None) -> str:
        now = self._now if now is None else now
        if self.sleeping:
            return "closed"
        if not self.blinking(now):
            return "open"
        t = (now - self._blink_at) / BLINK_LEN
        return "closed" if 1 / 3 <= t < 2 / 3 else "half"

    def mouth_frame(self) -> str:
        if self.state == "speaking":
            return MOUTH_FILES[self.mouth]
        return "rest"

    def breath(self, now: float | None = None) -> int:
        """Deslocamento vertical (pixels do canvas, inteiro: muda poucas vezes por ciclo)."""
        now = self._now if now is None else now
        a = self.assets.breath_px
        if self.sleeping or a <= 0:
            return 0
        return round(a * math.sin(2 * math.pi * now / self.assets.breath_period))

    def _key(self, now: float) -> tuple:
        return (self.state, self.eye_frame(now), self.glance(now), self.mouth_frame(), self.breath(now),
                self.phase(now))

    def _next_event(self, now: float, frame: float) -> float:
        nxt = super()._next_event(now, frame)
        if self.eye_frame(now) != "open":  # piscada em 3 quadros (meio, fechado, meio)
            nxt = min(nxt, now + max(frame, BLINK_LEN / 3))
        if self.assets.breath_px > 0 and not self.sleeping:
            nxt = min(nxt, now + 1.0 / BREATH_FPS)
        return max(nxt, now + 1.0 / FPS_AWAKE)

    # -- desenho
    def target(self, rect: QRectF) -> QRectF:
        """Onde o canvas cai em ``rect`` (contain: inteiro e centrado; cover: preenche)."""
        sw, sh = self.assets.size.width(), self.assets.size.height()
        k = (max if self.assets.fit == "cover" else min)(rect.width() / sw, rect.height() / sh)
        w, h = sw * k, sh * k
        return QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h)

    def paint(self, p: QPainter, rect: QRectF, accent: str | QColor, now: float | None = None) -> None:
        now = self._now if now is None else now
        t = self.target(rect)
        dev = p.transform().mapRect(t)
        w, h = max(1, round(dev.width())), max(1, round(dev.height()))
        frame = _compose(self.assets, self.state, self.eye_frame(now), self.glance(now), self.mouth_frame(),
                         w, h)
        dy = self.breath(now) * t.height() / self.assets.size.height()
        p.save()
        p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(QRectF(t.left(), t.top() + dy, t.width(), t.height()), frame, QRectF(frame.rect()))
        p.restore()


@lru_cache(maxsize=96)
def _compose(assets: PortraitAssets, expr: str, eyes: str, glance: int, mouth: str, w: int,
             h: int) -> QPixmap:
    """Camadas empilhadas e reduzidas uma vez para ``w×h`` pixels."""
    size = assets.size
    full = QPixmap(size)
    full.fill(Qt.GlobalColor.transparent)
    p = QPainter(full)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawPixmap(0, 0, assets.base(expr))
    if (e := assets.eyes(expr, eyes)) is not None:
        p.drawPixmap(QPointF(glance * assets.gaze_px, 0), e)
    if (m := assets.mouth(expr, mouth)) is not None:
        p.drawPixmap(0, 0, m)
    if (x := assets.extra(expr)) is not None:
        p.drawPixmap(0, 0, x)
    p.end()
    return full.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def make_mascot(state: str = "sleeping", folder: Path | None = None) -> Mascot:
    """O retrato se a pasta tiver as camadas obrigatórias; senão o mascote vetorial."""
    folder = folder or portrait_dir()
    if is_parts(folder):
        try:
            return PartsPortrait(PartsAssets(folder), state)
        except Exception as e:  # noqa: BLE001 - arte quebrada não derruba o HUD
            log.warning("retrato em partes indisponível (%s); usando o mascote vetorial", e)
            return Mascot(state)
    if is_frames(folder):
        try:
            return FramePortrait(FrameAssets(folder), state)
        except Exception as e:  # noqa: BLE001 - arte quebrada não derruba o HUD
            log.warning("retrato em quadros indisponível (%s); usando o mascote vetorial", e)
            return Mascot(state)
    if missing(folder):
        return Mascot(state)
    try:
        return Portrait(PortraitAssets(folder), state)
    except Exception as e:  # noqa: BLE001 - arte quebrada não derruba o HUD
        log.warning("retrato da Condessa indisponível (%s); usando o mascote vetorial", e)
        return Mascot(state)


__all__ = ["DEFAULT_DIR", "EXPRESSIONS", "Portrait", "PortraitAssets", "make_mascot", "missing",
           "portrait_dir"]


# ---------------------------------------------------------------- quadros inteiros (folha de expressões)

FRAME_IDLE_EVERY = (6.0, 14.0)  # parada: de quanto em quanto tempo olha para algum lado
FRAME_IDLE_LEN = (1.2, 2.6)
NIGHT_HOURS = (22, 7)  # dormindo à noite: cara de sono; de dia, neutra


class FrameAssets:
    """Retrato em quadros inteiros (``portrait.toml`` com ``mode = "frames"``, ver
    ``hud/tools/portrait_sheet.py``): ``frames/NN.png`` e o mapeamento estado → quadro."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        cfg = tomllib.loads((self.folder / "portrait.toml").read_text(encoding="utf-8"))
        self.fit = str(cfg.get("fit", "contain"))
        frames = {str(k): int(v) for k, v in dict(cfg.get("frames", {})).items()}
        speaking = dict(cfg.get("speaking", {}))
        self.idle = [int(n) for n in dict(cfg.get("idle", {})).get("glances", [])]
        self.state_frame = frames
        self.talk = (int(speaking.get("closed", frames.get("listening", 1))),
                     int(speaking.get("open", frames.get("happy", 1))))
        self._cache: dict[int, QPixmap | None] = {}
        first = self.frame(frames.get("listening", 1))
        if first is None:
            raise FileNotFoundError(f"retrato em quadros sem frames/ em {self.folder}")
        self.size = first.size()

    def frame(self, n: int) -> QPixmap | None:
        if n not in self._cache:
            path = self.folder / "frames" / f"{n:02d}.png"
            pm = QPixmap(str(path)) if path.is_file() else None
            self._cache[n] = None if pm is None or pm.isNull() else pm
        return self._cache[n]


def is_frames(folder: Path) -> bool:
    toml = folder / "portrait.toml"
    try:
        cfg = tomllib.loads(toml.read_text(encoding="utf-8")) if toml.is_file() else {}
    except (OSError, ValueError):
        return False
    return cfg.get("mode") == "frames" and (folder / "frames").is_dir()


class FramePortrait(Mascot):
    """`Mascot` com um quadro inteiro por estado (folha de expressões). Falando, alterna boca
    fechada/aberta pelo volume; parada, olha para os lados de vez em quando (``[idle] glances``);
    dormindo, cara de sono só à noite."""

    TALL = True  # a tela de espera dá mais espaço (retrato grande, fala embaixo)

    def __init__(self, assets: FrameAssets, state: str = "sleeping", rng: random.Random | None = None,
                 now: float | None = None, hour: Callable[[], int] | None = None):
        super().__init__(state, rng, now)
        self.assets = assets
        self.hour = hour or (lambda: time.localtime().tm_hour)
        self._idle_at = self._now + self._rng.uniform(*FRAME_IDLE_EVERY)
        self._idle_end = -1.0
        self._idle_frame = 0

    def _resting(self) -> bool:
        return self.state in ("sleeping", "listening")

    def _advance_idle(self, now: float) -> None:
        if not self.assets.idle:
            return
        while now >= self._idle_at:
            self._idle_end = self._idle_at + self._rng.uniform(*FRAME_IDLE_LEN)
            self._idle_frame = self._rng.choice(self.assets.idle)
            self._idle_at = self._idle_end + self._rng.uniform(*FRAME_IDLE_EVERY)
            if self._idle_at <= now:
                self._idle_at = now + self._rng.uniform(*FRAME_IDLE_EVERY)

    def frame_number(self, now: float | None = None) -> int:
        now = self._now if now is None else now
        a = self.assets
        if self.state == "speaking":
            return a.talk[1] if self.mouth in ("o", "O") else a.talk[0]
        if self._resting():
            self._advance_idle(now)
            if self._idle_frame and now < self._idle_end:
                return self._idle_frame
        if self.state == "sleeping":
            h = self.hour()
            night = h >= NIGHT_HOURS[0] or h < NIGHT_HOURS[1]
            if night and "sleeping" in a.state_frame:
                return a.state_frame["sleeping"]
            return a.state_frame.get("listening", a.talk[0])
        return a.state_frame.get(self.state, a.state_frame.get("listening", a.talk[0]))

    def _key(self, now: float) -> tuple:
        return (self.state, self.frame_number(now))

    def _next_event(self, now: float, frame: float) -> float:
        nxt = super()._next_event(now, frame)
        if self._resting() and self.assets.idle:
            nxt = min(nxt, self._idle_end if self._idle_end > now else self._idle_at)
        return max(nxt, now + frame)

    def target(self, rect: QRectF) -> QRectF:
        sw, sh = self.assets.size.width(), self.assets.size.height()
        k = (max if self.assets.fit == "cover" else min)(rect.width() / sw, rect.height() / sh)
        w, h = sw * k, sh * k
        return QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h)

    def paint(self, p: QPainter, rect: QRectF, accent: str | QColor, now: float | None = None) -> None:
        now = self._now if now is None else now
        t = self.target(rect)
        dev = p.transform().mapRect(t)
        pm = _scaled_frame(self.assets, self.frame_number(now), max(1, round(dev.width())),
                           max(1, round(dev.height())))
        if pm is None:
            return
        p.save()
        p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawPixmap(t, pm, QRectF(pm.rect()))
        p.restore()


@lru_cache(maxsize=48)
def _scaled_frame(assets: FrameAssets, n: int, w: int, h: int) -> QPixmap | None:
    pm = assets.frame(n)
    if pm is None:
        return None
    return pm.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


# ---------------------------------------------------------------- partes (2.5D)

PARTS_ORDER = ("back", "tail_l", "tail_r", "arm_l", "arm_r", "body", "head")
PARTS_FPS = 60.0  # acordada: respira, balança o cabelo, olha
PARTS_FPS_SLEEP = 6.0  # dormindo à noite: só respira (barato); de dia parada segue a 60
BREATH_PERIOD = 4.2
GAZE_EVERY = (6.0, 14.0)
GAZE_LEN = (1.5, 3.2)
GAZE_EASE = 0.18  # quanto a cabeça anda em direção ao olhar a cada quadro
TAIL_PIVOTS = {"tail_l": (330.0, 110.0), "tail_r": (700.0, 110.0)}
HEAD_PIVOT = (512.0, 140.0)
NECK_PIVOT = (512.0, 660.0)  # a cabeça inclina a partir do pescoço
MOUTH_LEVELS = (0.18, 0.72)  # fala: abaixo = fechada; até o 2º = entreaberta; acima = aberta (pico)
MOUTH_HOLD = 0.07  # cada boca fica no ar pelo menos isto (s), sem piscar
BLUSH = "#ff6f8e"


def is_parts(folder: Path) -> bool:
    toml = folder / "portrait.toml"
    try:
        cfg = tomllib.loads(toml.read_text(encoding="utf-8")) if toml.is_file() else {}
    except (OSError, ValueError):
        return False
    return cfg.get("mode") == "parts" and (folder / "parts" / "head.png").is_file()


class PartsAssets:
    """Camadas do ``hud/tools/condessa_build.py``: partes, remendos de olhos/boca, extras e o mapa."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        cfg = tomllib.loads((self.folder / "portrait.toml").read_text(encoding="utf-8"))
        self.states: dict[str, dict] = {str(k): dict(v) for k, v in dict(cfg.get("states", {})).items()}
        self.speech = [str(m) for m in dict(cfg.get("speech", {})).get("mouths", ["C1", "C2", "C3"])]
        self.gaze_by_name = {str(k): dict(v) for k, v in dict(cfg.get("gaze", {})).items()}
        self.gazes = list(self.gaze_by_name.values())
        self._cache: dict[str, QPixmap | None] = {}
        head = self.pix("parts/head.png")
        if head is None:
            raise FileNotFoundError(f"retrato em partes sem parts/head.png em {self.folder}")
        self.size = head.size()

    def pix(self, rel: str) -> QPixmap | None:
        if rel not in self._cache:
            path = self.folder / rel
            pm = QPixmap(str(path)) if path.is_file() else None
            self._cache[rel] = None if pm is None or pm.isNull() else pm
        return self._cache[rel]

    def has(self, rel: str) -> bool:
        return self.pix(rel) is not None


GLOW_R = 470.0


@lru_cache(maxsize=8)
def _glow(accent: str, side: int, strength: float = 0.30) -> QPixmap:
    """Brilho radial pré-renderizado (o gradiente a cada quadro custava ~0,8 ms)."""
    pm = QPixmap(side, side)
    pm.fill(Qt.GlobalColor.transparent)
    g = QRadialGradient(QPointF(side / 2, side / 2), side / 2)
    c0, c1 = QColor(accent), QColor(accent)
    c0.setAlphaF(strength)
    c1.setAlphaF(0.0)
    g.setColorAt(0, c0)
    g.setColorAt(1, c1)
    q = QPainter(pm)
    q.setPen(Qt.PenStyle.NoPen)
    q.setBrush(g)
    q.drawEllipse(QRectF(0, 0, side, side))
    q.end()
    return pm


BACKDROP_FPS = 12.0
# cor do fundo pelo humor (None = cor de acento do HUD)
MOOD_COLORS = {"calm": None, "happy": "#f2a7c3", "love": "#ff8fb8", "stress": "#e8604a",
               "sad": "#6f8fe0", "focus": "#5fd0e0", "surprise": "#f0d070", "sleepy": "#7a6aa8"}
TINT_EASE = 0.6  # s para o fundo chegar à cor nova
VOICE_ATTACK, VOICE_RELEASE = 0.05, 0.35  # s: o fundo cresce rápido com a voz e volta devagar
VOICE_GROW = 0.10  # até +10% de tamanho na voz mais alta
BOB_HZ = 1.6  # balanço de cabeça na música favorita (~96 bpm)
# pensando (e a pausa no meio da fala, esperando ferramenta): o olhar vaga e a cabeça inclina
THINK_CYCLE = (("B13", 4.0, -3.0), ("F4", 5.0, -3.0), ("B13", 4.0, -3.0), ("F6", 6.0, 0.0),
               ("F1", -6.0, 0.0), ("F7", 0.0, 3.0))
THINK_STEP = 1.3  # s em cada olhar
THINK_TILT = 2.2  # graus a mais de inclinação
PONDER_AFTER = 1.0  # s de silêncio "falando" até virar cara de pensando
DOTS_AFTER = 0.8  # s pensando até as reticências aparecerem


def _render_backdrop(accent: QColor, side: int, now: float, env: float = 0.0, mood: float = 0.0) -> QPixmap:
    """``env``: voz (0..1) acende os anéis; ``mood``: 0 calma .. 1 humor forte (brilho mais intenso)."""
    pm = QPixmap(side, side)
    pm.fill(Qt.GlobalColor.transparent)
    q = QPainter(pm)
    q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    q.scale(side / 1024, side / 1024)
    glow = _glow(accent.name(), max(1, round(side * GLOW_R * 2 / 1024)), round(0.30 + 0.25 * mood, 2))
    q.drawPixmap(QRectF(512 - GLOW_R, 430 - GLOW_R, GLOW_R * 2, GLOW_R * 2), glow, QRectF(glow.rect()))
    for i, r in enumerate((250, 340, 430)):
        c = QColor(accent)
        c.setAlphaF(min(1.0, (0.30 - i * 0.07) * (1 + 1.2 * env + 0.6 * mood)))  # voz/humor acendem
        q.setPen(QPen(c, 3.0 + 2.0 * env))
        ang = math.radians(now * (4 + i * 2) * (1 if i % 2 == 0 else -1))
        pts = [QPointF(512 + r * math.cos(ang + k * math.pi / 3), 430 + r * math.sin(ang + k * math.pi / 3))
               for k in range(7)]
        q.drawPolyline(pts)
    q.end()
    return pm


@lru_cache(maxsize=64)
def _head_group(assets: PartsAssets, eyes: str, mouth: str, side: int) -> tuple[QPixmap, QRectF] | None:
    """Cabeça + olhos + boca numa imagem só, na caixa da cabeça (giram juntos: uma rotação só)."""
    head = _scaled_part(assets, "parts/head.png", side)
    if head is None:
        return None
    hpm, hbox = head
    pm = QPixmap(hpm.size())
    pm.fill(Qt.GlobalColor.transparent)
    q = QPainter(pm)
    q.drawPixmap(0, 0, hpm)
    k = side / 1024
    for rel in (f"eyes/{eyes}.png", f"mouth/{mouth}.png"):
        part = _scaled_part(assets, rel, side)
        if part is not None:
            ppm, pbox = part
            q.drawPixmap(round((pbox.left() - hbox.left()) * k), round((pbox.top() - hbox.top()) * k), ppm)
    q.end()
    return pm, hbox


@lru_cache(maxsize=8)
def _torso_group(assets: PartsAssets, side: int) -> tuple[QPixmap, QRectF] | None:
    """Braços + corpo numa imagem só (andam juntos com a respiração: um drawPixmap em vez de três)."""
    parts = [x for x in (_scaled_part(assets, f"parts/{n}.png", side) for n in ("arm_l", "arm_r", "body"))
             if x is not None]
    if not parts:
        return None
    box = parts[0][1]
    for _, b in parts[1:]:
        box = box.united(b)
    k = side / 1024
    pm = QPixmap(max(1, round(box.width() * k)), max(1, round(box.height() * k)))
    pm.fill(Qt.GlobalColor.transparent)
    q = QPainter(pm)
    for ppm, pbox in parts:
        q.drawPixmap(round((pbox.left() - box.left()) * k), round((pbox.top() - box.top()) * k), ppm)
    q.end()
    return pm, box


def _alpha_box(img: QImage) -> tuple[int, int, int, int] | None:
    """Caixa (x0, y0, x1, y1) dos pixels com alfa, ou None se vazia."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())[:, : w * 4]
    alpha = arr[:, 3::4] > 4
    rows, cols = np.where(alpha.any(axis=1))[0], np.where(alpha.any(axis=0))[0]
    if not len(rows):
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


@lru_cache(maxsize=128)
def _scaled_part(assets: PartsAssets, rel: str, side: int) -> tuple[QPixmap, QRectF] | None:
    """Camada no tamanho do dispositivo, recortada na caixa útil, e onde ela cai no quadro de 1024
    (desenhar só a caixa, e não o quadro inteiro transparente, corta o custo por quadro)."""
    pm = assets.pix(rel)
    if pm is None:
        return None
    scaled = pm.scaled(side, side, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    box = _alpha_box(scaled.toImage())
    if box is None:
        return None
    x0, y0, x1, y1 = box
    k = 1024 / side
    return scaled.copy(x0, y0, x1 - x0, y1 - y0), QRectF(x0 * k, y0 * k, (x1 - x0) * k, (y1 - y0) * k)


class PartsPortrait(Mascot):
    """Condessa 2.5D: partes animadas (respiração, cabelo em pêndulo, olhar com parallax),
    olhos/boca por estado e pela voz, piscada da expressão e efeitos desenhados em código."""

    TALL = True

    def __init__(self, assets: PartsAssets, state: str = "sleeping", rng: random.Random | None = None,
                 now: float | None = None, hour: Callable[[], int] | None = None):
        super().__init__(state, rng, now)
        self.assets = assets
        self.hour = hour or (lambda: time.localtime().tm_hour)
        self._gaze_at = self._now + self._rng.uniform(*GAZE_EVERY)
        self._gaze_end = -1.0
        self._gaze: dict | None = None
        self._head = [0.0, 0.0]  # deslocamento atual da cabeça (px do quadro de 1024)
        self._last_tick = -math.inf
        self._mouth = "C1"
        self._mouth_since = -math.inf
        self._bd: tuple | None = None  # fundo em cache: (chave, quando, pixmap)
        self._tint: list[float] | None = None  # cor atual do fundo (r, g, b), vai até a do humor
        self._env = 0.0  # envelope da voz (0..1): o fundo expande junto
        self._moodk = 0.0  # 0 calma .. 1 humor forte (o brilho do fundo acende)
        self._tick_at: float | None = None
        self.accent = QColor("#b4a0e6")
        self._voice_at = -math.inf  # última vez que a voz passou do ruído
        self._think_since: float | None = None
        self._think_k = 0.0  # 0..1, suaviza a entrada e a saída da cara de pensando

    def thinking(self, now: float) -> bool:
        """Pensando de verdade, ou "falando" em silêncio (frase de espera dita, ferramenta rodando)."""
        if self.state == "thinking":
            return True
        return self.state == "speaking" and self.level < 0.05 and now - self._voice_at > PONDER_AFTER

    def _think_look(self, now: float) -> tuple[str, float, float] | None:
        if not self.thinking(now):
            return None
        for _ in THINK_CYCLE:  # pula olhares sem arte
            eyes, dx, dy = THINK_CYCLE[int(now / THINK_STEP) % len(THINK_CYCLE)]
            if self.assets.has(f"eyes/{eyes}.png"):
                return eyes, dx, dy
            now += THINK_STEP
        return None

    def _reacting(self, now: float):
        """A reação em curso, se ela está parada (falando/pensando, a fala manda)."""
        r = self.reaction
        if r is None or now >= self.reaction_until or not self._resting():
            return None
        return r

    def _look_gaze(self, r) -> dict | None:
        if r is None or not r.look:
            return None
        from .reactions import LOOK_DIRS

        name = LOOK_DIRS.get(self.layout, LOOK_DIRS["main"]).get(r.look)
        return self.assets.gaze_by_name.get(name) if name else None

    def mood(self, now: float) -> str:
        r = self._reacting(now)
        if r is not None:
            return r.mood
        if self.thinking(now):
            return "focus"
        if self.state == "sleeping" and self._night():
            return "sleepy"
        from .reactions import MOOD_OF_STATE

        return MOOD_OF_STATE.get(self.state, "calm")

    # -- estado
    def _night(self) -> bool:
        h = self.hour()
        return h >= NIGHT_HOURS[0] or h < NIGHT_HOURS[1]

    def _resting(self) -> bool:
        return self.state == "listening" or (self.state == "sleeping" and not self._night())

    def _state_cfg(self) -> dict:
        st = self.state
        if st == "sleeping" and not self._night():
            st = "listening"
        return self.assets.states.get(st) or self.assets.states.get("listening") or {}

    def _advance_gaze(self, now: float) -> None:
        if not self.assets.gazes or not self._resting() or self._reacting(now) is not None:
            self._gaze = None
            return
        if self._gaze is not None and now >= self._gaze_end:
            self._gaze = None
            self._gaze_at = now + self._rng.uniform(*GAZE_EVERY)
        if self._gaze is None and now >= self._gaze_at:
            self._gaze = self._rng.choice(self.assets.gazes)
            self._gaze_end = now + self._rng.uniform(*GAZE_LEN)

    def eyes_id(self, now: float) -> str:
        cfg = self._state_cfg()
        if self.state == "sleeping" and self._night():
            closed = (cfg.get("blink") or ["B15", "B15"])[-1]
            return closed if self.assets.has(f"eyes/{closed}.png") else str(cfg.get("eyes", "B1"))
        if self.blinking(now):
            half, closed = (cfg.get("blink") or ["B2", "B3"])[:2]
            t = (now - self._blink_at) / BLINK_LEN
            return closed if 1 / 3 <= t < 2 / 3 else half
        think = self._think_look(now)
        if think is not None:
            return think[0]
        r = self._reacting(now)
        if r is not None:
            if r.eyes and self.assets.has(f"eyes/{r.eyes}.png"):
                return r.eyes
            look = self._look_gaze(r)
            if look is not None:
                return str(look.get("eyes", cfg.get("eyes", "B1")))
        if self._gaze is not None:
            return str(self._gaze.get("eyes", cfg.get("eyes", "B1")))
        return str(cfg.get("eyes", "B1"))

    def mouth_id(self, now: float | None = None) -> str:
        now = self._now if now is None else now
        if self.state != "speaking":
            r = self._reacting(now)
            if r is not None and r.mouth and self.assets.has(f"mouth/{r.mouth}.png"):
                return r.mouth
            return str(self._state_cfg().get("mouth", "C1"))
        if self.thinking(now):
            return "C1"  # pausa esperando a ferramenta: boca fechada, não um "o" no meio da fala
        mouths = self.assets.speech
        lvl = self.level
        i = 0 if lvl < MOUTH_LEVELS[0] else (1 if lvl < MOUTH_LEVELS[1] else 2)
        want = mouths[min(i, len(mouths) - 1)]
        if want != self._mouth and now - self._mouth_since >= MOUTH_HOLD:
            self._mouth, self._mouth_since = want, now
        return self._mouth

    # -- relógio
    def tick(self, now: float | None = None) -> tuple[bool, float]:
        now = time.monotonic() if now is None else now
        self._now = now
        self._advance(now)
        self._advance_gaze(now)
        dt = 0.0 if self._tick_at is None else max(0.0, min(0.25, now - self._tick_at))
        self._tick_at = now
        want = self.level if self.state == "speaking" else 0.0
        tau = VOICE_ATTACK if want > self._env else VOICE_RELEASE
        self._env += (want - self._env) * (1 - math.exp(-dt / tau)) if dt else 0.0
        self._ease_tint(now, dt)
        if self.level >= 0.05:
            self._voice_at = now
        think = self._think_look(now)
        if think is not None and self._think_since is None:
            self._think_since = now
        elif think is None:
            self._think_since = None
        if dt:
            self._think_k += ((1.0 if think else 0.0) - self._think_k) * (1 - math.exp(-dt / 0.35))
        gaze = self._look_gaze(self._reacting(now)) or self._gaze
        tgt = (float(gaze.get("dx", 0)), float(gaze.get("dy", 0))) if gaze else (0.0, 0.0)
        if think is not None:
            tgt = (think[1], think[2])
        self._head[0] += (tgt[0] - self._head[0]) * GAZE_EASE
        self._head[1] += (tgt[1] - self._head[1]) * GAZE_EASE
        fps = PARTS_FPS_SLEEP if self.sleeping and self._night() else PARTS_FPS
        frame = 1.0 / fps
        if now - self._last_tick < frame - 1e-6:
            return False, self._last_tick + frame
        self._last_tick = now
        return True, now + frame

    # -- desenho
    def target(self, rect: QRectF) -> QRectF:
        side = min(rect.width(), rect.height())
        return QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)

    def paint(self, p: QPainter, rect: QRectF, accent: str | QColor, now: float | None = None) -> None:
        now = self._now if now is None else now
        t = self.target(rect)
        k = t.width() / self.assets.size.width()
        side = max(1, round(p.transform().mapRect(t).width()))
        breath = math.sin(2 * math.pi * now / BREATH_PERIOD)
        hx, hy = self._head
        talk = self.level if self.state == "speaking" else 0.0
        head_dy = 2.0 * breath + 3.0 * talk  # falando, a cabeça acompanha a voz
        tilt = 0.6 * math.sin(now * 0.5) + 0.25 * math.sin(now * 1.3 + 0.7)  # inclinação lenta
        sway = 1.5 * math.sin(now * 0.35)  # o corpo balança de leve para os lados
        tilt += THINK_TILT * self._think_k  # pensando: cabeça de lado
        r = self._reacting(now)
        if r is not None and r.bob:  # curtindo a música: a cabeça vai no ritmo
            fade = min(1.0, (self.reaction_until - now) / 1.0, 1.0)
            beat = math.sin(2 * math.pi * BOB_HZ * now)
            tilt += 2.4 * fade * beat
            head_dy += 2.5 * fade * abs(beat)
        p.save()
        p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(t.topLeft())
        p.scale(k, k)

        def draw(rel: str, dx: float = 0.0, dy: float = 0.0, angle: float = 0.0,
                 pivot: tuple[float, float] = HEAD_PIVOT, head: bool = False,
                 part: tuple[QPixmap, QRectF] | None = None) -> None:
            part = part if part is not None else _scaled_part(self.assets, rel, side)
            if part is None:
                return
            pm, box = part
            p.save()
            if head:  # cabeça, olhos, boca, franja: giram juntos a partir do pescoço
                p.translate(*NECK_PIVOT)
                p.rotate(tilt)
                p.translate(-NECK_PIVOT[0], -NECK_PIVOT[1])
            p.translate(dx, dy)
            if angle:
                p.translate(*pivot)
                p.rotate(angle)
                p.translate(-pivot[0], -pivot[1])
            p.drawPixmap(box, pm, QRectF(pm.rect()))
            p.restore()

        self.accent = QColor(accent)
        self._backdrop(p, now, -0.9 * hx - 0.8 * sway, -0.7 * hy - 0.5 * head_dy)
        # ordem: cabelo de trás, marias-chiquinhas, braços, corpo, cabeça; as mechas que caem na frente
        # dos ombros vêm da franja (desenhada por último)
        draw("parts/back.png", -0.4 * hx + 0.5 * sway, -0.3 * hy + 1.5 * breath,
             0.3 * math.sin(now * 0.7) + 0.4 * tilt, head=False)
        for name, phase in (("tail_l", 0.0), ("tail_r", 1.3)):
            swing = 1.8 * math.sin(now * 1.05 + phase) + 0.5 * math.sin(now * 2.3 + phase * 2)
            draw(f"parts/{name}.png", 0.6 * hx + sway, 0.6 * hy + head_dy, swing + 0.6 * tilt,
                 TAIL_PIVOTS[name])
        draw("", sway, 3.0 * breath, part=_torso_group(self.assets, side))
        group = _head_group(self.assets, self.eyes_id(now), self.mouth_id(now), side)
        if group is not None:
            draw("", hx + sway, hy + head_dy, head=True, part=group)
        draw("parts/bangs.png", 1.25 * hx + sway, 1.2 * hy + head_dy, 0.6 * math.sin(now * 1.3),
             (512.0, 100.0), head=True)
        self._effects(p, now, QColor(accent), hx, hy + head_dy)
        if r is not None and r.effect:
            self._reaction_effect(p, now, r.effect, hx, hy + head_dy)
        if self._think_since is not None and now - self._think_since >= DOTS_AFTER:
            self._dots(p, now, hx, hy + head_dy)
        p.restore()

    def _ease_tint(self, now: float, dt: float) -> None:
        hexc = MOOD_COLORS.get(self.mood(now)) or self.accent.name()
        c = QColor(hexc)
        want = [c.redF(), c.greenF(), c.blueF()]
        if self._tint is None or not dt:
            self._tint = self._tint or want
            return
        k = 1 - math.exp(-dt / TINT_EASE)
        self._tint = [a + (b - a) * k for a, b in zip(self._tint, want, strict=True)]
        self._moodk += ((0.0 if self.mood(now) == "calm" else 1.0) - self._moodk) * k

    def tint(self) -> QColor:
        """Cor atual do fundo, em degraus (o brilho em cache não é refeito a cada quadro)."""
        r, g, b = (self._tint or [self.accent.redF(), self.accent.greenF(), self.accent.blueF()])
        q = lambda v: min(255, round(v * 255 / 6) * 6)  # noqa: E731
        return QColor(q(r), q(g), q(b))

    def _backdrop(self, p: QPainter, now: float, bx: float, by: float) -> None:
        """Fundo com parallax: brilho e hexágonos finos que andam ao contrário dela (profundidade).
        Muda de cor com o humor e cresce com a voz. Desenhado numa imagem a ``BACKDROP_FPS``
        (gira devagar); a cada quadro só é deslocado (e, falando, escalado)."""
        side = max(1, round(p.transform().m11() * 1024))
        tint = self.tint()
        key = (tint.name(), side, round(self._env * 4), round(self._moodk * 4))
        if self._bd is None or self._bd[0] != key and now - self._bd[1] >= 1 / 30 \
                or now - self._bd[1] >= 1 / BACKDROP_FPS:
            self._bd = (key, now, _render_backdrop(tint, side, now, self._env, round(self._moodk * 4) / 4))
        pm = self._bd[2]
        origin = p.transform().map(QPointF(bx, by))
        grow = 1.0 + VOICE_GROW * self._env
        p.save()
        p.resetTransform()
        if grow < 1.004:
            p.drawPixmap(round(origin.x()), round(origin.y()), pm)
        else:  # expande a partir do centro do brilho
            cx, cy = origin.x() + side * 512 / 1024, origin.y() + side * 430 / 1024
            w = side * grow
            p.drawPixmap(QRectF(cx - w * 512 / 1024, cy - w * 430 / 1024, w, w), pm, QRectF(pm.rect()))
        p.restore()

    def _dots(self, p: QPainter, now: float, hx: float, hy: float) -> None:
        """Reticências pulsando ao lado da cabeça (pensando / esperando a ferramenta)."""
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            ph = (now * 1.6 - i * 0.22) % 1.0
            lift = 10 * math.sin(math.pi * ph) if ph < 0.5 else 0.0
            c = QColor(self.tint())
            c.setAlphaF(0.45 + 0.55 * (lift / 10))
            p.setBrush(c)
            p.drawEllipse(QPointF(780 + i * 38 + hx, 250 - lift + hy), 13, 13)
        p.restore()

    def _reaction_effect(self, p: QPainter, now: float, kind: str, hx: float, hy: float) -> None:
        """Efeitos da reação (quadro de 1024): suor, notas, ?, !, rubor. Somem no fim."""
        from . import fonts

        alpha = max(0.0, min(1.0, (self.reaction_until - now) / 0.6))
        p.save()
        p.setOpacity(alpha)
        if kind == "sweat":  # gota escorrendo ao lado da testa
            x, y = 330 + hx, 300 + hy + 18 * ((now * 0.5) % 1.0)
            path = QPainterPath(QPointF(x, y - 30))
            path.cubicTo(QPointF(x + 19, y - 4), QPointF(x + 26, y + 16), QPointF(x, y + 16))
            path.cubicTo(QPointF(x - 26, y + 16), QPointF(x - 19, y - 4), QPointF(x, y - 30))
            p.setPen(QPen(QColor("#2a3550"), 3))
            p.setBrush(QColor(150, 200, 255, 210))
            p.drawPath(path)
        elif kind == "notes":  # notas subindo e sumindo
            for i in range(3):
                ph = (now / 2.4 + i / 3) % 1.0
                c = QColor("#ffd6e6")
                c.setAlphaF(max(0.0, 1.0 - ph))
                p.setPen(c)
                p.setFont(fonts.font("cond", 80 + i * 12, 700))
                x = 760 + i * 40 + 18 * math.sin(now * 2 + i)
                p.drawText(QPointF(x + hx, 330 - 160 * ph + hy), "♪" if i % 2 else "♫")
        elif kind in ("question", "bang"):
            sc = 1.0 + 0.08 * math.sin(now * 6)
            p.setPen(QColor("#e8b04a") if kind == "bang" else self.tint())
            p.setFont(fonts.font("cond", 100 * sc, 700))
            p.drawText(QPointF(770 + hx, 250 + hy), "!" if kind == "bang" else "?")
        elif kind == "blush":
            c = QColor(BLUSH)
            c.setAlphaF(0.6)
            p.setPen(QPen(c, 5))
            for cx in (420.0, 610.0):
                for i in range(4):
                    x = cx + hx + i * 14
                    p.drawLine(QPointF(x, 515 + hy), QPointF(x + 12, 495 + hy))
        p.restore()

    def _effects(self, p: QPainter, now: float, accent: QColor, hx: float, hy: float) -> None:
        """Detalhes desenhados em código, no quadro de 1024 (zz, ?, !, rubor)."""
        from . import fonts

        st = self.state
        p.save()
        if st == "happy":  # rubor: hachuras rosadas nas bochechas
            c = QColor(BLUSH)
            c.setAlphaF(0.6)
            p.setPen(QPen(c, 5))
            for cx in (420.0, 610.0):
                for i in range(4):
                    x = cx + hx + i * 14
                    p.drawLine(QPointF(x, 515 + hy), QPointF(x + 12, 495 + hy))
        if st == "sleeping" and self._night():  # zz subindo
            for i in range(3):
                ph = (now / 3.0 + i / 3) % 1.0
                c = QColor(accent)
                c.setAlphaF(max(0.0, 1.0 - ph))
                p.setPen(c)
                p.setFont(fonts.font("cond", 40 + i * 12, 600))
                p.drawText(QPointF(720 + i * 34 + 20 * ph, 230 - i * 40 - 70 * ph), "z")
        if st in ("confused", "alert"):  # ? ou ! pulsando ao lado da cabeça
            s = 1.0 + 0.08 * math.sin(now * 6)
            c = QColor("#e8b04a") if st == "alert" else QColor(accent)
            p.setPen(c)
            p.setFont(fonts.font("cond", 110 * s, 700))
            p.drawText(QPointF(760 + hx, 250 + hy), "!" if st == "alert" else "?")
        p.restore()
