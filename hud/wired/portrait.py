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

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

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
PARTS_FPS = 30.0  # acordada: respira, balança o cabelo, olha
PARTS_FPS_SLEEP = 6.0  # dormindo: só respira (barato)
BREATH_PERIOD = 4.2
GAZE_EVERY = (6.0, 14.0)
GAZE_LEN = (1.5, 3.2)
GAZE_EASE = 0.18  # quanto a cabeça anda em direção ao olhar a cada quadro
TAIL_PIVOTS = {"tail_l": (330.0, 110.0), "tail_r": (700.0, 110.0)}
HEAD_PIVOT = (512.0, 140.0)
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
        self.gazes = [dict(v) for v in dict(cfg.get("gaze", {})).values()]
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


@lru_cache(maxsize=128)
def _scaled_part(assets: PartsAssets, rel: str, side: int) -> QPixmap | None:
    pm = assets.pix(rel)
    if pm is None:
        return None
    return pm.scaled(side, side, Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)


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
        if not self.assets.gazes or not self._resting():
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
        if self._gaze is not None:
            return str(self._gaze.get("eyes", cfg.get("eyes", "B1")))
        return str(cfg.get("eyes", "B1"))

    def mouth_id(self) -> str:
        if self.state == "speaking":
            mouths = self.assets.speech
            lvl = self.level
            i = 0 if lvl < 0.15 else (1 if lvl < 0.5 else 2)
            return mouths[min(i, len(mouths) - 1)]
        return str(self._state_cfg().get("mouth", "C1"))

    # -- relógio
    def tick(self, now: float | None = None) -> tuple[bool, float]:
        now = time.monotonic() if now is None else now
        self._now = now
        self._advance(now)
        self._advance_gaze(now)
        tgt = (float(self._gaze.get("dx", 0)), float(self._gaze.get("dy", 0))) if self._gaze else (0.0, 0.0)
        self._head[0] += (tgt[0] - self._head[0]) * GAZE_EASE
        self._head[1] += (tgt[1] - self._head[1]) * GAZE_EASE
        fps = PARTS_FPS_SLEEP if self.sleeping else PARTS_FPS
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
        head_dy = 2.0 * breath
        p.save()
        p.setClipRect(rect, Qt.ClipOperation.IntersectClip)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(t.topLeft())
        p.scale(k, k)

        def draw(rel: str, dx: float = 0.0, dy: float = 0.0, angle: float = 0.0,
                 pivot: tuple[float, float] = HEAD_PIVOT) -> None:
            pm = _scaled_part(self.assets, rel, side)
            if pm is None:
                return
            p.save()
            p.translate(dx, dy)
            if angle:
                p.translate(*pivot)
                p.rotate(angle)
                p.translate(-pivot[0], -pivot[1])
            p.drawPixmap(QRectF(0, 0, 1024, 1024), pm, QRectF(pm.rect()))
            p.restore()

        # ordem: cabelo de trás, marias-chiquinhas, braços, corpo, cabeça; as mechas que caem na frente
        # dos ombros vêm da franja (desenhada por último)
        draw("parts/back.png", -0.4 * hx, -0.3 * hy + 1.5 * breath, 0.25 * math.sin(now * 0.7))
        for name, phase in (("tail_l", 0.0), ("tail_r", 1.3)):
            draw(f"parts/{name}.png", 0.6 * hx, 0.6 * hy + head_dy, 1.4 * math.sin(now * 1.05 + phase),
                 TAIL_PIVOTS[name])
        draw("parts/arm_l.png", 0, 3.5 * breath)
        draw("parts/arm_r.png", 0, 3.5 * breath)
        draw("parts/body.png", 0, 3.0 * breath)
        draw("parts/head.png", hx, hy + head_dy)
        draw(f"eyes/{self.eyes_id(now)}.png", hx, hy + head_dy)
        draw(f"mouth/{self.mouth_id()}.png", hx, hy + head_dy)
        draw("parts/bangs.png", 1.25 * hx, 1.2 * hy + head_dy, 0.5 * math.sin(now * 1.3), (512.0, 100.0))
        self._effects(p, now, QColor(accent), hx, hy + head_dy)
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
