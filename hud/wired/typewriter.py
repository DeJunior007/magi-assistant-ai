"""Fala da Condessa digitada 1 caractere por vez no terminal do card (lógica pura, sem Qt).

A legenda sincronizada (``speech_caption.SpeechCaption``) entrega o texto já dito, palavra a
palavra, no tempo do áudio. Aqui ele vira digitação: o texto mostrado persegue esse alvo
caractere a caractere, com um atraso pequeno (``LAG_S``), então a velocidade acompanha a da fala
(~15 caracteres/s) sem saltos de palavra inteira. Atrasou muito (texto longo de uma vez, fim da
fala) → acelera; nunca abaixo de ``MIN_CPS``. Alvo novo que não continua o anterior (outra fala)
recomeça do ponto em comum. Parado (tudo digitado) não há prazo: nada a redesenhar.
"""

from __future__ import annotations

import math

LAG_S = 0.35  # atraso de perseguição: backlog / LAG_S = caracteres por segundo
MIN_CPS = 14.0  # velocidade mínima (o fim do texto não se arrasta)
MAX_FPS = 30.0


def common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


class Typewriter:
    def __init__(self, lag: float = LAG_S, min_cps: float = MIN_CPS) -> None:
        self.lag = lag
        self.min_cps = min_cps
        self.target = ""
        self.n = 0.0  # caracteres digitados (fração = o próximo a caminho)
        self._t: float | None = None

    @property
    def shown(self) -> str:
        return self.target[:int(self.n)]

    @property
    def typing(self) -> bool:
        return int(self.n) < len(self.target)

    def _advance(self, now: float) -> None:
        dt = 0.0 if self._t is None else now - self._t
        self._t = now if self._t is None else max(self._t, now)
        if dt <= 0:
            return
        total = len(self.target)
        b = total - self.n
        if b <= 0:
            self.n = float(total)
            return
        knee = self.min_cps * self.lag  # abaixo disso, velocidade constante
        if b > knee:
            t_knee = self.lag * math.log(b / knee)
            if dt < t_knee:
                self.n = total - b * math.exp(-dt / self.lag)
                return
            dt -= t_knee
            b = knee
        self.n = total - max(0.0, b - self.min_cps * dt)

    def feed(self, text: str | None, now: float) -> bool:
        """Alvo atual (o texto já dito) em ``now``. ``True`` = o texto mostrado mudou."""
        before = self.shown
        self._advance(now)
        text = text or ""
        if text != self.target:
            keep = common_prefix(self.shown, text)
            self.target = text
            self.n = float(min(int(self.n), keep))
        return self.shown != before

    def deadline(self, now: float) -> float | None:
        """Próximo quadro da digitação (``None`` = tudo digitado)."""
        return now + 1 / MAX_FPS if self.typing else None


__all__ = ["LAG_S", "MIN_CPS", "Typewriter", "common_prefix"]
