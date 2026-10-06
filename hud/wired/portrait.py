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
import tomllib
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

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
    if missing(folder):
        return Mascot(state)
    try:
        return Portrait(PortraitAssets(folder), state)
    except Exception as e:  # noqa: BLE001 - arte quebrada não derruba o HUD
        log.warning("retrato da Condessa indisponível (%s); usando o mascote vetorial", e)
        return Mascot(state)


__all__ = ["DEFAULT_DIR", "EXPRESSIONS", "Portrait", "PortraitAssets", "make_mascot", "missing",
           "portrait_dir"]
