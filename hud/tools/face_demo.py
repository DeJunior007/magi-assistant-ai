#!/usr/bin/env python3
"""Renderiza cada expressão do rosto em PNG (grande e pequeno, accent laranja e azul).

    uv run python hud/tools/face_demo.py [pasta]   # padrão: /tmp/magi-face-demo/

Use com a sessão gráfica normal (Wayland/X11): com QT_QPA_PLATFORM=offscreen o fontconfig pode
escolher outras fontes. O script imprime a fonte realmente usada para os glifos e a legenda.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from face import EXPRESSIONS, FADE_LEN, Face  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QRawFont  # noqa: E402

SIZES = {"big": (1280, 1440), "small": (160, 100)}
ACCENTS = {"orange": QColor("#ff8c1a"), "blue": QColor("#6a6aff")}
SUBTITLES = {
    "sleeping": "",
    "listening": "Pode falar, estou ouvindo.",
    "thinking": "Hmm… deixa eu ver isso aqui.",
    "speaking": "Boa noite! A partida começa em dez minutos e o Discord já está aberto.",
    "happy": "Ganhamos! GG!",
    "confused": "Não entendi muito bem… pode repetir?",
    "alert": "A GPU passou de 90 graus! 気をつけて！",
}
# (nome no arquivo, expressão, nível da boca)
SHOTS = [(e, e, 0.0) for e in EXPRESSIONS if e != "speaking"] + [
    ("speaking-low", "speaking", 0.05),
    ("speaking-mid", "speaking", 0.3),
    ("speaking-high", "speaking", 0.8),
]


def render(name: str, expr: str, level: float, size: tuple[int, int], accent: QColor) -> QImage:
    t0 = 1000.0
    face = Face("listening" if expr == "sleeping" else "sleeping", rng=random.Random(1), now=t0)
    face.set_state(expr)
    face.set_mouth_level(level)
    face.set_subtitle(SUBTITLES[expr])
    face.tick(t0 + FADE_LEN + 0.05)  # depois do cross-fade, antes da 1ª piscada
    img = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("black"))
    p = QPainter(img)
    face.paint(p, QRectF(0, 0, *size), accent)
    p.end()
    return img


def main() -> None:
    app = QGuiApplication(sys.argv[:1])
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/magi-face-demo")
    out.mkdir(parents=True, exist_ok=True)
    probe = Face()
    for kind in ("glyph", "serif"):
        raw = QRawFont.fromFont(probe.font(kind, 40))
        print(f"fonte {kind}: {raw.familyName()} (plataforma {app.platformName()})")
    for size_name, size in SIZES.items():
        for acc_name, accent in ACCENTS.items():
            for name, expr, level in SHOTS:
                path = out / f"{size_name}-{acc_name}-{name}.png"
                render(name, expr, level, size, accent).save(str(path))
    print(f"{len(SIZES) * len(ACCENTS) * len(SHOTS)} PNGs em {out}")


if __name__ == "__main__":
    main()
