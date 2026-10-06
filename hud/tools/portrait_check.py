"""Confere a arte do retrato da Condessa e, opcionalmente, salva uma prancha com os estados.

Uso: uv run python -m hud.tools.portrait_check [prancha.png] [--dir PASTA]

Sem a pasta completa, lista o que falta (docs/design/CONDESSA-RETRATO.md). Com ela, avisa camadas
de tamanho diferente da base e desenha cada expressão (olhos abertos, piscada, boca da fala em 3
níveis) no tamanho do painel, para revisar antes de abrir o HUD.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402
from wired import fonts  # noqa: E402
from wired.mascot import BLINK_LEN, EXPRESSIONS  # noqa: E402
from wired.portrait import Portrait, PortraitAssets, missing, portrait_dir  # noqa: E402
from wired.theme import BG, TEXT_DIM, color  # noqa: E402

CELL_W, CELL_H, LABEL_H = 390.0, 225.0, 22.0


def check(folder: Path) -> list[str]:
    """Problemas encontrados (vazio = ok)."""
    lacking = missing(folder)
    if lacking:
        return [f"falta {f}" for f in lacking]
    assets = PortraitAssets(folder)
    problems = []
    for path in sorted(folder.rglob("*.png")):
        rel = path.relative_to(folder).as_posix()
        pm = assets.layer(rel)
        if pm is None:
            problems.append(f"{rel}: não consegui ler")
        elif pm.size() != assets.size:
            problems.append(f"{rel}: {pm.width()}×{pm.height()}, a base é "
                            f"{assets.size.width()}×{assets.size.height()}")
    return problems


def sheet(folder: Path, out: Path) -> None:
    assets = PortraitAssets(folder)
    columns = [("aberto", None, 0.0), ("piscada", "blink", 0.0), ("fala —", "speak", 0.05),
               ("fala o", "speak", 0.3), ("fala O", "speak", 0.9)]
    img = QImage(round(CELL_W * len(columns)), round((CELL_H + LABEL_H) * len(EXPRESSIONS)),
                 QImage.Format.Format_ARGB32)
    img.fill(color(BG))
    p = QPainter(img)
    p.setFont(fonts.font("mono", 12))
    for row, expr in enumerate(EXPRESSIONS):
        for col, (title, mode, level) in enumerate(columns):
            m = Portrait(assets, "speaking" if mode == "speak" else expr, now=0.0)
            m._blink_at = 0.0 if mode == "blink" else 1e9
            m.set_level(level)
            x, y = col * CELL_W, row * (CELL_H + LABEL_H)
            p.setPen(QColor(color(TEXT_DIM)))
            who = "speaking" if mode == "speak" else expr  # a fala sempre usa o estado speaking
            p.drawText(QRectF(x + 8, y, CELL_W, LABEL_H), f"{who} · {title}")
            now = BLINK_LEN / 2 if mode == "blink" else 0.5
            m.paint(p, QRectF(x, y + LABEL_H, CELL_W, CELL_H), "#b392f0", now)
    p.end()
    img.save(str(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", type=Path, help="salva a prancha neste PNG")
    ap.add_argument("--dir", type=Path, default=None, help="pasta das camadas")
    args = ap.parse_args()
    folder = (args.dir or portrait_dir()).expanduser()
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841
    fonts.load()
    problems = check(folder)
    if problems:
        print(f"{folder}:")
        print("\n".join(f"  - {x}" for x in problems))
        if missing(folder):
            print("veja docs/design/CONDESSA-RETRATO.md")
            return 1
    else:
        print(f"{folder}: ok")
    if args.out:
        sheet(folder, args.out)
        print(f"prancha: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
