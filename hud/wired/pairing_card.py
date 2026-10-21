"""Cartão do código de pareamento do celular no painel e na espera (ayanami-central Y6.6c).

O núcleo manda ``{"t":"card","level":"alta","title":"Código de pareamento 123 456",
"url":"…/app/#/parear?c=123456","source":"pareamento"}`` (``AvisosAyanami.codigo_pareamento``).
O HUD desenha um cartão próprio no lugar do ``LAST SESSION`` (por cima dele): o código grande,
"vale 5 min" e o link. Some em ``SHOW_S`` (o código vale 5 min), ao ser clicado ou quando outro
código chega. Sem QR: o HUD não tem gerador (sem dependência nova). Nada vai a disco nem a log.

Puro (sem Qt) até ``paint_card``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SOURCE = "pareamento"
SHOW_S = 300.0   # o código vale 5 min (Ayanami, /v1/pareamento)
HEADER = "PAREAR CELULAR"
VALIDADE = "vale 5 min · uso único"

_DIGITOS = re.compile(r"\d[\d ]*\d|\d")


def is_pairing(card: Mapping[str, Any]) -> bool:
    return card.get("source") == SOURCE


def code_of(card: Mapping[str, Any]) -> str:
    """O código como o HUD mostra (``"123 456"``): do ``?c=`` do link, senão os dígitos do título."""
    m = re.search(r"[?&]c=(\d+)", str(card.get("url") or ""))
    digits = m.group(1) if m else "".join(_DIGITOS.findall(str(card.get("title") or ""))).replace(" ", "")
    return f"{digits[:3]} {digits[3:]}" if len(digits) == 6 else digits


@dataclass
class PairingCard:
    show_s: float = SHOW_S
    card: dict[str, Any] | None = None
    at: float | None = None

    def set(self, card: Mapping[str, Any], now: float) -> None:
        self.card, self.at = dict(card), now

    def current(self, now: float) -> dict[str, Any] | None:
        if self.card is None or self.at is None or now - self.at >= self.show_s:
            return None
        return self.card

    def deadline(self) -> float | None:
        return None if self.at is None else self.at + self.show_s

    def close(self) -> None:
        self.card = self.at = None


def card_key(card: Mapping[str, Any] | None) -> tuple:
    return (None,) if card is None else (card.get("title"), card.get("url"))


def paint_card(p, rect, card: Mapping[str, Any], *, px: float = 11.0, pad: float = 10.0) -> None:
    """Fundo opaco, borda ``TEXT_DIM``; cabeçalho com ×, código grande, validade e link."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QFontMetricsF, QPen

    from .fonts import font
    from .theme import BG, TEXT, TEXT_DIM, color

    r = QRectF(rect)
    small = font("mono", px)
    fs = QFontMetricsF(small)
    er = Qt.TextElideMode.ElideMiddle
    inner = r.width() - 2 * pad
    x = r.left() + pad
    p.save()
    p.fillRect(r, color(BG))
    pen = QPen(color(TEXT_DIM))
    pen.setWidthF(1.0)
    p.setPen(pen)
    p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
    p.setFont(small)
    y = r.top() + pad + fs.ascent()
    p.drawText(QPointF(x, y), HEADER)
    p.drawText(QPointF(r.right() - pad - fs.horizontalAdvance("×"), y), "×")
    # código: o maior que couber entre o cabeçalho e a linha de baixo
    room = r.bottom() - pad - fs.height() - (y + fs.descent()) - 2
    big = font("mono", max(px, min(room * 0.8, px * 3.2)), 700)
    fb = QFontMetricsF(big)
    p.setFont(big)
    p.setPen(color(TEXT))
    code = code_of(card)
    yc = y + fs.descent() + (room + fb.ascent() - fb.descent()) / 2
    p.drawText(QPointF(x, yc), code)
    p.setFont(small)
    p.setPen(color(TEXT_DIM))
    p.drawText(QPointF(r.right() - pad - fs.horizontalAdvance(VALIDADE), yc), VALIDADE)
    url = str(card.get("url") or "")
    if url:
        p.drawText(QPointF(x, r.bottom() - pad - fs.descent()), fs.elidedText(url, er, inner))
    p.restore()


__all__ = ["HEADER", "SHOW_S", "SOURCE", "PairingCard", "card_key", "code_of", "is_pairing",
           "paint_card"]
