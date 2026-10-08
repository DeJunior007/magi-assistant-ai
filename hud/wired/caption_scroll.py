"""Rolagem da legenda da fala no card da Condessa (lógica pura, sem Qt).

A legenda quebrada em linhas cabe ``visible`` linhas na área sob o chip. Em vez de cortar com
reticências:

- **acompanhando** (``follow``): quando a fala ganha uma linha nova, o texto sobe suave
  (``ANIM_S``, ease-out) até a última linha; as de cima esmaecem (``alpha``);
- **lendo** (roda do mouse): o Pedro volta o texto inteiro da última fala; o acompanhamento
  pausa (o texto continua crescendo embaixo, a posição fica); volta sozinho ao chegar no fim
  ou quando começa outra fala.

O deslocamento é em linhas (``offset`` 0 = primeira linha no topo).
"""

from __future__ import annotations

ANIM_S = 0.28  # duração da subida de uma linha
SAME_PREFIX = 0.6  # texto novo que repete >= isso do anterior = mesma fala (ex.: fim da fala)


def _ease(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


class CaptionScroll:
    def __init__(self, visible: int, anim_s: float = ANIM_S) -> None:
        self.visible = max(1, int(visible))
        self.anim_s = anim_s
        self.text = ""
        self.n = 0
        self.follow = True
        self._from = 0.0
        self._to = 0.0
        self._t0 = 0.0

    # -- estado ----------------------------------------------------------------------------

    @property
    def max_off(self) -> int:
        return max(0, self.n - self.visible)

    def offset(self, now: float) -> float:
        if self.anim_s <= 0:
            return self._to
        return self._from + (self._to - self._from) * _ease((now - self._t0) / self.anim_s)

    def animating(self, now: float) -> bool:
        return self._from != self._to and now < self._t0 + self.anim_s

    def deadline(self, now: float) -> float | None:
        """Próximo quadro da animação (``None`` = parada)."""
        return now + 1 / 30 if self.animating(now) else None

    def _go(self, target: float, now: float, animate: bool = True) -> None:
        cur = self.offset(now)
        self._from = cur if animate else target
        self._to, self._t0 = target, now

    # -- eventos ---------------------------------------------------------------------------

    def feed(self, text: str | None, n_lines: int, now: float) -> bool:
        """Texto (e quantas linhas ele dá) a mostrar agora. ``True`` = mudou algo."""
        text = text or ""
        if text == self.text and n_lines == self.n:
            return False
        old = self.text
        self.text, self.n = text, max(0, n_lines)
        if old and text.startswith(old):  # a fala avançou
            if self.follow:
                if self.max_off != self._to:
                    self._go(self.max_off, now)
            else:
                self._go(min(self._to, self.max_off), now, animate=False)
            return True
        common = 0
        for a, b in zip(old, text, strict=False):
            if a != b:
                break
            common += 1
        if old and common >= SAME_PREFIX * len(old):  # mesma fala reescrita (fim, legenda inteira)
            self._go(self.max_off if self.follow else min(self._to, self.max_off), now, animate=False)
            return True
        # fala nova (ou começo vazio): do começo; texto longo inteiro de uma vez fica no topo
        self.follow = self.n <= self.visible
        self._go(0, now, animate=False)
        return True

    def wheel(self, lines: float, now: float) -> bool:
        """Roda do mouse: ``lines`` > 0 volta (sobe o texto), < 0 avança. ``True`` = mexeu."""
        if self.max_off == 0:
            return False
        tgt = min(float(self.max_off), max(0.0, round(self._to - lines)))
        if tgt == self._to:
            return False
        self._go(tgt, now)
        self.follow = tgt >= self.max_off  # chegou no fim: volta a acompanhar
        return True

    # -- desenho ---------------------------------------------------------------------------

    def alpha(self, i: int, now: float) -> float:
        """Opacidade da linha ``i``: as de cima esmaecem quando há texto escondido acima."""
        off = self.offset(now)
        rel = i - off  # 0 = no topo da área
        if rel < 0:
            return max(0.0, 0.6 * (1 + rel))
        if off <= 0.01 or rel >= 1:
            return 1.0
        return 0.6 + 0.4 * rel

    def hidden(self, now: float) -> tuple[bool, bool]:
        """(há texto acima, há texto abaixo) da janela."""
        off = self.offset(now)
        return off > 0.01, off < self.max_off - 0.01
