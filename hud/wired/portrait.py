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
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QTransform

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
PARTS_FPS = 60.0  # movimento rápido: falando, pensando, piscando, reagindo, olhar/cabeça indo
PARTS_FPS_IDLE = 40.0  # parada: só respiração e cabelo lento (ciclos de 2 s+), 40 já fica liso
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
        # "gl": malhas que entortam e pós-processamento na GPU (portrait_gl); "cpu": QPainter
        self.renderer = str(os.environ.get("MAGI_PORTRAIT_RENDERER") or cfg.get("renderer", "cpu"))
        speech = dict(cfg.get("speech", {}))
        raw_shapes = dict(speech.get("shapes", SHAPES_DEFAULT))
        self._raw_shapes = {str(k): [str(m) for m in v] for k, v in raw_shapes.items()}
        self._cache: dict[str, QPixmap | None] = {}
        head = self.pix("parts/head.png")
        if head is None:
            raise FileNotFoundError(f"retrato em partes sem parts/head.png em {self.folder}")
        self.size = head.size()
        # camadas opcionais da 2ª rodada de arte (H, O, V)
        self.live_eyes = all(self.has(r) for r in ("parts/iris.png", "parts/eye_open.png", "eyes/O1.png"))
        self.split_hair = all(self.has(f"parts/{n}.png") for n in ("bangs_c", "lock_l", "lock_r"))
        self.shapes = {band: [m for m in ms if self.has(f"mouth/{m}.png")]
                       for band, ms in self._raw_shapes.items()}
        self.shapes = {b: ms for b, ms in self.shapes.items() if ms} if any(
            m.startswith("V") for ms in self.shapes.values() for m in ms) else {}

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
# olhar livre (O1 + íris recortada): deslocamento da íris (px do quadro de 1024) por olhar
IRIS_FOR = {"B1": (0.0, 0.0), "F1": (-8.0, 0.0), "F6": (8.0, 0.0), "F4": (7.0, -5.0),
            "F3": (-7.0, 4.0), "F5": (7.0, 4.0), "F7": (0.0, 6.0), "B13": (7.0, -6.0)}
IRIS_EASE = 0.35  # a íris anda rápido (sacada), a cabeça vem atrás
SACCADE_EVERY = (0.7, 2.2)  # microssacadas parada: ±1 px de vez em quando
SYLLABLE_RISE = 0.15  # subida do volume depois de um vale = sílaba nova (troca o formato da boca)
SHAPES_DEFAULT = {"low": ["C2", "V2", "V5"], "mid": ["V1", "C2", "V3"], "high": ["C3", "V1", "V3"]}
DOTS_AFTER = 0.8  # s pensando até as reticências aparecerem
# ouvindo (gravando a fala do Pedro): acorda, chega para a frente, olhar fixo no centro e anéis de "escuta"
LISTEN_LEAN = 7.0  # px que a cabeça desce (inclinada para a frente, atenta)
LISTEN_TILT = -1.6  # graus: cabeça um pouco de lado, como quem presta atenção
LISTEN_EASE = 0.22  # s para entrar/sair da pose de escuta
LISTEN_WAKE = 0.45  # s do "acordar" (pulo rápido + brilho) ao ativar
LISTEN_RING = 1.4  # s de cada anel saindo do fundo
LISTEN_COLOR = "#5fd0e0"  # cor de foco (a mesma do humor "focus")


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
    eyes_part = _live_eyes(assets, eyes, side) if eyes.startswith("live:") else None
    for rel in (f"eyes/{eyes}.png", f"mouth/{mouth}.png"):
        part = eyes_part if rel.startswith("eyes/live:") else _scaled_part(assets, rel, side)
        if part is not None:
            ppm, pbox = part
            q.drawPixmap(round((pbox.left() - hbox.left()) * k), round((pbox.top() - hbox.top()) * k), ppm)
    q.end()
    return pm, hbox


@lru_cache(maxsize=512)
def _live_eyes(assets: PartsAssets, key: str, side: int) -> tuple[QPixmap, QRectF] | None:
    """Olhos sem íris (O1) com a íris deslocada (``live:dx:dy``), recortada pela abertura do olho."""
    base = _scaled_part(assets, "eyes/O1.png", side)
    iris = _scaled_part(assets, "parts/iris.png", side)
    opening = _scaled_part(assets, "parts/eye_open.png", side)
    if base is None or iris is None or opening is None:
        return None
    _, dx, dy = key.split(":")
    bpm, bbox = base
    k = side / 1024
    layer = QPixmap(bpm.size())
    layer.fill(Qt.GlobalColor.transparent)
    q = QPainter(layer)
    ipm, ibox = iris
    ix = round((ibox.left() - bbox.left() + float(dx)) * k)
    iy = round((ibox.top() - bbox.top() + float(dy)) * k)
    q.drawPixmap(ix, iy, ipm)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    opm, obox = opening
    q.drawPixmap(round((obox.left() - bbox.left()) * k), round((obox.top() - bbox.top()) * k), opm)
    q.end()
    pm = QPixmap(bpm.size())
    pm.fill(Qt.GlobalColor.transparent)
    q = QPainter(pm)
    q.drawPixmap(0, 0, bpm)
    q.drawPixmap(0, 0, layer)
    q.end()
    return pm, bbox


# braço da reação (extra/P*.png) → braços da base que ele substitui (P9–P12: o da direita da imagem)
ARM_REPLACES = {"P13": ("arm_l", "arm_r")}
ARM_REPLACES_DEFAULT = ("arm_r",)


def arms_replaced(arm: str | None) -> tuple[str, ...]:
    """Braços da base escondidos enquanto o braço de reação ``arm`` aparece (nenhum sem braço)."""
    return ARM_REPLACES.get(arm, ARM_REPLACES_DEFAULT) if arm else ()


@lru_cache(maxsize=8)
def _torso_group(assets: PartsAssets, side: int, skip: tuple = ()) -> tuple[QPixmap, QRectF] | None:
    """Braços + corpo numa imagem só (andam juntos com a respiração: um drawPixmap em vez de três).
    ``skip``: braços da base que um braço de reação substitui (não desenha os dois ao mesmo tempo)."""
    parts = [x for x in (_scaled_part(assets, f"parts/{n}.png", side)
                         for n in ("arm_l", "arm_r", "body") if n not in skip)
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


def _effects_of(r) -> tuple[str, ...]:
    """Até 3 efeitos do passo (``efeitos``, por nome ou ID D*); sem eles, o ``effect`` antigo."""
    if r is None:
        return ()
    from .reacoes.contratos import EFEITO

    kinds = tuple(getattr(r, "efeitos", ()) or ((r.effect,) if r.effect else ()))
    return tuple(EFEITO.get(k, k) for k in kinds)[:3]


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
        self._iris = [0.0, 0.0]  # deslocamento atual da íris (olhar livre)
        self._gl = None
        if assets.renderer == "gl":
            from .portrait_gl import GLPortrait

            self._gl = GLPortrait(assets.folder)
        self._drag = [0.0, 0.0]  # inércia do cabelo na GPU (contra o movimento da cabeça)
        self._prev_head: tuple[float, float, float] | None = None
        self.glitch = 0.0  # 0..1: interferência de sinal (núcleo fora do ar)
        self._saccade = (0.0, 0.0)
        self._saccade_at = self._now + self._rng.uniform(*SACCADE_EVERY)
        self._valley = 0.0  # menor volume desde a última sílaba
        self._syll = 0
        self._listen_since: float | None = None  # quando ativou (ouvindo); None = não está ouvindo
        self._listen_k = 0.0  # 0..1, suaviza a entrada e a saída da pose de escuta

    def set_expression(self, expr: str) -> None:
        was = self.state
        super().set_expression(expr)
        if expr == "listening" and was != "listening":  # acordou: pisca já e larga o olhar solto
            self._listen_since = self._now
            self._blink_at = self._now
            self._gaze = None
        elif expr != "listening":
            self._listen_since = None

    set_state = set_expression

    def _fast(self, now: float, head_target: tuple[float, float]) -> bool:
        """Precisa de 60 fps agora? (fala, ouvindo, pensando, piscada, reação ou olhar/cabeça em trânsito)"""
        if self.state in ("speaking", "thinking", "listening") or self.blinking(now) \
                or self._reacting(now) is not None:
            return True
        moving_head = abs(head_target[0] - self._head[0]) + abs(head_target[1] - self._head[1]) > 0.4
        return moving_head or self._think_k > 0.02 or self._listen_k > 0.02

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
        if r is None or now >= self.reaction_until:
            return None
        if self._resting():
            return r
        noturna = getattr(r, "noturna", False) and self.state == "sleeping" and self._night()
        return r if noturna else None

    @staticmethod
    def _extra(r, name: str) -> str | None:
        """Extra de corpo da reação (``sway``, ``braco:P9``...): o valor depois de ``:``, ``""`` sem."""
        for c in getattr(r, "corpo", ()) if r is not None else ():
            key, _, val = str(c).partition(":")
            if key == name:
                return val
        return None

    def _iris_extra(self, r) -> tuple[float, float] | None:
        """``iris:<olhar>``: a sacada do O1 para um olhar nomeado (gaze do toml ou olho F*/B*)."""
        name = self._extra(r, "iris")
        if not name or not self.assets.live_eyes:
            return None
        gaze = self.assets.gaze_by_name.get(name)
        eyes = str(gaze.get("eyes", "")) if gaze else name
        return IRIS_FOR.get(eyes)

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
        if self.thinking(now) or self.state == "listening":
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
        """Parada (dormindo de dia): olhares soltos e reações do HUD. Ouvindo não: ela está atenta."""
        return self.state == "sleeping" and not self._night()

    @property
    def listen_k(self) -> float:
        """Força da pose de escuta (0..1): sobe ao ativar, desce ao sair."""
        return self._listen_k

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
        """Olho a desenhar: o da expressão ou, com o olhar livre, ``live:dx:dy`` (íris solta)."""
        want = self._eye_target(now)
        live = want in IRIS_FOR or self._iris_extra(self._reacting(now)) is not None
        if self.assets.live_eyes and live and not self.blinking(now):
            return f"live:{round(self._iris[0])}:{round(self._iris[1])}"
        return want

    def _eye_target(self, now: float) -> str:
        cfg = self._state_cfg()
        if self.state == "sleeping" and self._night() and self._reacting(now) is None:
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
        shapes = self.assets.shapes
        if i and shapes:  # cada sílaba troca o formato (é, i, ó, m...) dentro da faixa de volume
            band = shapes.get("high" if i == 2 else ("mid" if lvl >= (MOUTH_LEVELS[0] + MOUTH_LEVELS[1]) / 2
                                                     else "low")) or shapes.get("mid") or []
            if band:
                want = band[self._syll % len(band)]
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
        lvl = self.level if self.state == "speaking" else 0.0
        self._valley = min(self._valley, lvl)
        if lvl - self._valley > SYLLABLE_RISE:
            self._syll += 1
            self._valley = lvl
        if self.assets.live_eyes:
            target = self._eye_target(now)
            if self.state == "listening":  # olhar fixo no Pedro: sem microssacadas
                self._saccade = (0.0, 0.0)
            elif now >= self._saccade_at:
                self._saccade = (self._rng.uniform(-1.2, 1.2), self._rng.uniform(-0.8, 0.8))
                self._saccade_at = now + self._rng.uniform(*SACCADE_EVERY)
            tx, ty = self._iris_extra(self._reacting(now)) or IRIS_FOR.get(target, (0.0, 0.0))
            tx, ty = tx + self._saccade[0], ty + self._saccade[1]
            self._iris[0] += (tx - self._iris[0]) * IRIS_EASE
            self._iris[1] += (ty - self._iris[1]) * IRIS_EASE
        think = self._think_look(now)
        if think is not None and self._think_since is None:
            self._think_since = now
        elif think is None:
            self._think_since = None
        if dt:
            self._think_k += ((1.0 if think else 0.0) - self._think_k) * (1 - math.exp(-dt / 0.35))
            want = 1.0 if self.state == "listening" else 0.0
            self._listen_k += (want - self._listen_k) * (1 - math.exp(-dt / LISTEN_EASE))
        gaze = self._look_gaze(self._reacting(now)) or self._gaze
        tgt = (float(gaze.get("dx", 0)), float(gaze.get("dy", 0))) if gaze else (0.0, 0.0)
        if think is not None:
            tgt = (think[1], think[2])
        elif self.state == "listening":  # de frente, chegando para a frente
            tgt = (0.0, LISTEN_LEAN)
        self._head[0] += (tgt[0] - self._head[0]) * GAZE_EASE
        self._head[1] += (tgt[1] - self._head[1]) * GAZE_EASE
        if self._gl is not None and dt:
            hx, hy = self._head
            if self._prev_head is not None:
                vx, vy = (hx - self._prev_head[0]) / dt, (hy - self._prev_head[1]) / dt
                k = 1 - math.exp(-dt / 0.25)
                self._drag[0] += (max(-14.0, min(14.0, -0.9 * vx)) - self._drag[0]) * k
                self._drag[1] += (max(-8.0, min(8.0, -0.6 * vy)) - self._drag[1]) * k
            self._prev_head = (hx, hy, now)
        if self.sleeping and self._night():
            fps = PARTS_FPS_SLEEP
        else:
            fps = PARTS_FPS if self._fast(now, tgt) else PARTS_FPS_IDLE
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
        lk = self._listen_k
        if lk:  # ouvindo: o balanço some (atenta) e a cabeça fica um pouco de lado
            tilt = tilt * (1 - 0.7 * lk) + LISTEN_TILT * lk
            sway *= 1 - 0.7 * lk
            head_dy += self._wake(now) * -6.0  # o "pulo" de quem acordou
        r = self._reacting(now)
        fade = min(1.0, (self.reaction_until - now) / 1.0) if r is not None else 0.0
        if r is not None and (r.bob or self._extra(r, "bob") is not None):  # curtindo: cabeça no ritmo
            beat = math.sin(2 * math.pi * BOB_HZ * now)
            tilt += 2.4 * fade * beat
            head_dy += 2.5 * fade * abs(beat)
        if self._extra(r, "sway") is not None:  # o corpo vai de um lado para o outro
            sway += 7.0 * fade * math.sin(now * 2.2)
        tails_k = 1.0 + 1.4 * fade if self._extra(r, "tails") is not None else 1.0
        p.save()
        p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(t.topLeft())
        p.scale(k, k)
        gl = self._gl
        ops: list = []  # na GPU: camadas a desenhar (portrait_gl.GLOp)
        # na GPU o cabelo entorta pela malha; a rotação rígida fica só como base
        rigid = 0.45 if gl is not None else 1.0

        def xform(box: QRectF, dx: float, dy: float, angle: float, pivot: tuple[float, float],
                  head: bool, child: float) -> QTransform:
            x = QTransform()
            if head:  # cabeça, olhos, boca, franja: giram juntos a partir do pescoço
                x.translate(*NECK_PIVOT)
                x.rotate(tilt)
                x.translate(-NECK_PIVOT[0], -NECK_PIVOT[1])
            x.translate(dx, dy)
            if angle:
                x.translate(*pivot)
                x.rotate(angle)
                x.translate(-pivot[0], -pivot[1])
            if child:
                top = (box.center().x(), box.top() + 4)
                x.translate(*top)
                x.rotate(child)
                x.translate(-top[0], -top[1])
            return x

        def draw(rel: str, dx: float = 0.0, dy: float = 0.0, angle: float = 0.0,
                 pivot: tuple[float, float] = HEAD_PIVOT, head: bool = False,
                 part: tuple[QPixmap, QRectF] | None = None, child: float = 0.0,
                 deform: tuple | None = None) -> None:
            """``child``: ângulo extra em volta do topo da peça (2º segmento). ``deform`` (GPU):
            ``(1, raiz y, comprimento, amplitude, fase, frequência)``, ``(2,)`` respiração ou
            ``(3, (dx, dy))`` íris."""
            part = part if part is not None else _scaled_part(self.assets, rel, side)
            if part is None:
                return
            pm, box = part
            x = xform(box, dx, dy, angle, pivot, head, child)
            if gl is not None:
                from .portrait_gl import GLOp

                kind, *rest = deform or (0,)
                op = GLOp(rel, x, kind)
                if kind == 1:  # cabelo
                    root, length, amp, phase, freq = rest
                    op.hair, op.freq = (root, length, amp, phase), freq
                elif kind == 3:  # íris
                    op.iris = rest[0]
                ops.append(op)
                return
            p.save()
            p.setTransform(x, True)
            p.drawPixmap(box, pm, QRectF(pm.rect()))
            p.restore()

        def box_of(rel: str) -> QRectF:
            got = _scaled_part(self.assets, rel, side)
            return got[1] if got else QRectF(0, 0, 1024, 1024)

        def hair(rel: str, amp: float, phase: float, freq: float, root: float | None = None) -> tuple:
            b = box_of(rel)
            top = b.top() if root is None else root
            return (1, top, max(60.0, b.bottom() - top), amp, phase, freq)

        self.accent = QColor(accent)
        self._backdrop(p, now, -0.9 * hx - 0.8 * sway, -0.7 * hy - 0.5 * head_dy)
        if lk > 0.02:  # anéis de escuta saindo do fundo, atrás dela (nas duas vias: CPU e GPU)
            self._listen_rings(p, now, lk)
        # ordem: cabelo de trás, marias-chiquinhas, braços, corpo, cabeça; as mechas que caem na frente
        # dos ombros vêm da franja (desenhada por último)
        back = (-0.4 * hx + 0.5 * sway, -0.3 * hy + 1.5 * breath,
                (0.3 * math.sin(now * 0.7) + 0.4 * tilt) * rigid)
        back_def = hair("parts/back.png", 7.0, 0.3, 0.8)
        draw("parts/back.png", *back, head=False, deform=back_def)
        back_tip = (0.9 * math.sin(now * 0.7 - 0.9) + 0.3 * tilt) if gl is None else 0.0
        draw("parts/back_tip.png", *back, child=back_tip, deform=back_def)
        for name, phase in (("tail_l", 0.0), ("tail_r", 1.3)):
            swing = tails_k * (1.8 * math.sin(now * 1.05 + phase) + 0.5 * math.sin(now * 2.3 + phase * 2))
            pivot = TAIL_PIVOTS[name]
            args = (0.6 * hx + sway, 0.6 * hy + head_dy, (swing + 0.6 * tilt) * rigid, pivot)
            tail_def = hair(f"parts/{name}.png", 13.0, phase, 1.05, root=pivot[1])
            draw(f"parts/{name}.png", *args, deform=tail_def)
            # ponta: o mesmo balanço atrasado e maior (o cabelo dobra como chicote); na GPU, a malha
            tip = 2.4 * math.sin(now * 1.05 + phase - 1.0) + 0.6 * math.sin(now * 2.3 + phase * 2 - 1.4)
            draw(f"parts/{name}_tip.png", *args, child=(tip - 0.6 * swing) if gl is None else 0.0,
                 deform=tail_def)
        arm = self._extra(r, "braco")
        arm = arm if arm and self.assets.has(f"extra/{arm}.png") else None  # sem a arte, braço da base
        skip = arms_replaced(arm)
        if gl is not None:  # braços acompanham a respiração; o peito deforma
            for name in ("arm_l", "arm_r"):
                if name not in skip:
                    draw(f"parts/{name}.png", sway, 3.0 * breath)
            draw("parts/body.png", sway, 0.0, deform=(2,))
        else:
            draw("", sway, 3.0 * breath, part=_torso_group(self.assets, side, skip))
        if arm:  # braço da reação (P9–P13) no lugar do braço da base
            draw(f"extra/{arm}.png", sway, 3.0 * breath)
        # cabeça, olhos e boca em três desenhos com a mesma transformação (antes eram remontados
        # juntos a cada troca: com a íris solta isso virava uma remontagem por quadro)
        hpos = (hx + sway, hy + head_dy)
        eyes = self.eyes_id(now)
        draw("parts/head.png", *hpos, head=True)
        if eyes.startswith("live:") and gl is not None:
            draw("eyes/O1.png", *hpos, head=True)
            draw("parts/iris.png", *hpos, head=True, deform=(3, (self._iris[0], self._iris[1])))
        else:
            eyes_part = (_live_eyes(self.assets, eyes, side) if eyes.startswith("live:")
                         else _scaled_part(self.assets, f"eyes/{eyes}.png", side))
            if eyes_part is not None:
                draw(f"eyes/{eyes}.png", *hpos, head=True, part=eyes_part)
        mouth = f"mouth/{self.mouth_id(now)}.png"
        mouth_part = _scaled_part(self.assets, mouth, side)
        if mouth_part is not None:
            draw(mouth, *hpos, head=True, part=mouth_part)
        if self.assets.split_hair:  # mechas laterais e franja com pêndulo próprio, presilha junto
            for name, phase in (("lock_l", 0.4), ("lock_r", 2.0)):
                swing = 1.3 * math.sin(now * 0.9 + phase) + 0.4 * math.sin(now * 2.1 + phase)
                draw(f"parts/{name}.png", 1.15 * hx + sway, 1.1 * hy + head_dy, head=True,
                     child=(swing - 0.5 * tilt) * rigid, deform=hair(f"parts/{name}.png", 6.0, phase, 0.9))
            bangs = (1.25 * hx + sway, 1.2 * hy + head_dy, 0.6 * math.sin(now * 1.3) * rigid, (512.0, 100.0))
            draw("parts/bangs_c.png", *bangs, head=True, deform=hair("parts/bangs_c.png", 2.5, 0.0, 1.3))
            draw("parts/clip.png", *bangs, head=True)
        else:
            draw("parts/bangs.png", 1.25 * hx + sway, 1.2 * hy + head_dy, 0.6 * math.sin(now * 1.3),
                 (512.0, 100.0), head=True, deform=hair("parts/bangs.png", 3.0, 0.0, 1.3))
        fone = "E2" if self._extra(r, "fone_on") is not None else (
            "E3" if self._extra(r, "fone_off") is not None else None)
        if fone is not None:  # fone na cabeça (E2) ou tirando (E3); sem o asset, nada
            rel = f"extra/{fone}.png"
            if fone == "E2" and not self.assets.has(rel):
                rel = "extra/fone.png"
            draw(rel, *hpos, head=True)
        if gl is not None and not self._paint_gl(p, gl, ops, now, side, breath, r):
            self._gl = None  # GPU falhou: daqui em diante, CPU
        self._effects(p, now, QColor(accent), hx, hy + head_dy)
        for kind in _effects_of(r):
            self._reaction_effect(p, now, kind, hx, hy + head_dy)
        if self._think_since is not None and now - self._think_since >= DOTS_AFTER:
            self._dots(p, now, hx, hy + head_dy)
        if lk > 0.02:
            self._listen_meter(p, now, lk, hx, hy + head_dy)
        p.restore()

    def _paint_gl(self, p: QPainter, gl, ops: list, now: float, side: int, breath: float, r) -> bool:
        """Desenha as camadas na GPU e cola a imagem no lugar do retrato (quadro de 1024 atual)."""
        from .portrait_gl import Post

        tint = self.tint()
        post = Post(rim=0.3 + 0.25 * self._moodk, rim_color=(tint.redF(), tint.greenF(), tint.blueF()),
                    glitch=self.glitch)
        if r is not None and r.mood == "surprise":  # susto: as cores se separam e voltam
            post.aberr = 3.0 * max(0.0, min(1.0, (self.reaction_until - now) / 1.5))
        img = gl.render(side, ops, now, tuple(self._drag), 3.0 * breath, post)
        if img is None:
            return False
        origin = p.transform().map(QPointF(0, 0))
        p.save()
        p.resetTransform()
        p.drawImage(round(origin.x()), round(origin.y()), img)
        p.restore()
        return True

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

    def _wake(self, now: float) -> float:
        """Curva do "acordar" (0..1..0) nos primeiros ``LISTEN_WAKE`` s de escuta."""
        if self._listen_since is None:
            return 0.0
        t = (now - self._listen_since) / LISTEN_WAKE
        return math.sin(math.pi * t) if 0.0 <= t < 1.0 else 0.0

    def _listen_rings(self, p: QPainter, now: float, k: float) -> None:
        """Ondas de "estou ouvindo": anéis finos que nascem atrás da cabeça e se abrem (quadro de 1024).
        Ao ativar, um anel mais forte estoura primeiro."""
        cx, cy = 512.0, 360.0
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        since = self._listen_since if self._listen_since is not None else now
        for i in range(3):
            ph = ((now - since) / LISTEN_RING + i / 3) % 1.0
            c = QColor(LISTEN_COLOR)
            c.setAlphaF(0.8 * k * (1 - ph) ** 1.3)
            p.setPen(QPen(c, 8 - 4 * ph))
            rad = 250 + 260 * ph
            p.drawEllipse(QPointF(cx, cy), rad, rad)
        wake = self._wake(now)
        if wake:
            c = QColor(LISTEN_COLOR)
            c.setAlphaF(0.8 * wake)
            p.setPen(QPen(c, 10))
            rad = 230 + 200 * (now - since) / LISTEN_WAKE
            p.drawEllipse(QPointF(cx, cy), rad, rad)
        p.restore()

    def _listen_meter(self, p: QPainter, now: float, k: float, hx: float, hy: float) -> None:
        """Barras de áudio ao lado da cabeça, na cor de foco (pulsam sozinhas; com som, sobem mais)."""
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        c = QColor(LISTEN_COLOR)
        c.setAlphaF(0.9 * k)
        p.setBrush(c)
        base = 0.35 + 0.65 * min(1.0, self.level * 1.5)
        for i in range(5):
            wob = 0.5 + 0.5 * math.sin(now * (7.0 + 1.7 * i) + i * 1.9) * math.sin(now * 2.3 + i)
            h = 18 + 70 * base * abs(wob) * (1.0 - 0.15 * abs(i - 2))
            x = 790 + i * 24 + hx
            p.drawRoundedRect(QRectF(x, 250 + hy - h / 2, 13, h), 6.5, 6.5)
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
        """Efeitos da reação (quadro de 1024): suor, notas, ?, !, rubor. Somem no fim. Com a arte
        ``extra/D*.png`` (R3.1, ``condessa_build``) o PNG entra no lugar do desenho em código."""
        from . import fonts
        from .reacoes.contratos import EFEITO

        alpha = max(0.0, min(1.0, (self.reaction_until - now) / 0.6))
        p.save()
        p.setOpacity(alpha)
        ident = next((k for k, v in EFEITO.items() if v == kind), None)
        pm = self.assets.pix(f"extra/{ident}.png") if ident else None
        if pm is not None:  # quadro inteiro de 1024, acompanha a cabeça
            p.drawPixmap(QRectF(hx, hy, 1024, 1024), pm, QRectF(pm.rect()))
        elif kind == "sweat":  # gota escorrendo ao lado da testa
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
        elif kind == "zz":  # zz subindo (cochilo da reação)
            for i in range(3):
                ph = (now / 3.0 + i / 3) % 1.0
                c = self.tint()
                c.setAlphaF(max(0.0, 1.0 - ph))
                p.setPen(c)
                p.setFont(fonts.font("cond", 40 + i * 12, 600))
                p.drawText(QPointF(720 + i * 34 + 20 * ph + hx, 230 - i * 40 - 70 * ph + hy), "z")
        elif kind == "tear":  # lágrima descendo do canto do olho
            x, y = 445 + hx, 470 + hy + 60 * ((now * 0.4) % 1.0)
            path = QPainterPath(QPointF(x, y - 18))
            path.cubicTo(QPointF(x + 12, y - 2), QPointF(x + 14, y + 10), QPointF(x, y + 10))
            path.cubicTo(QPointF(x - 14, y + 10), QPointF(x - 12, y - 2), QPointF(x, y - 18))
            p.setPen(QPen(QColor("#2a3550"), 2))
            p.setBrush(QColor(170, 215, 255, 220))
            p.drawPath(path)
        elif kind == "vein":  # veia de raiva (cruz de quatro arcos) na testa
            sc = 1.0 + 0.1 * abs(math.sin(now * 5))
            cx, cy, r0 = 640 + hx, 250 + hy, 22 * sc
            p.setPen(QPen(QColor("#d23a3a"), 7))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for ang in (45, 135, 225, 315):
                ox, oy = r0 * math.cos(math.radians(ang)), r0 * math.sin(math.radians(ang))
                p.drawArc(QRectF(cx + ox - r0, cy + oy - r0, 2 * r0, 2 * r0), (ang + 180 - 45) * 16, 90 * 16)
        elif kind == "sparkle":  # brilhos de quatro pontas piscando em volta
            for i, (sx, sy) in enumerate(((300, 260), (760, 220), (800, 420))):
                k = 0.5 + 0.5 * math.sin(now * 4 + i * 2.1)
                s = 14 + 18 * k
                c = QColor("#fff3c4")
                c.setAlphaF(0.4 + 0.6 * k)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(c)
                x, y = sx + hx, sy + hy
                star = QPainterPath(QPointF(x, y - s))
                for px, py in ((x + s / 4, y - s / 4), (x + s, y), (x + s / 4, y + s / 4), (x, y + s),
                               (x - s / 4, y + s / 4), (x - s, y), (x - s / 4, y - s / 4), (x, y - s)):
                    star.lineTo(QPointF(px, py))
                p.drawPath(star)
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
