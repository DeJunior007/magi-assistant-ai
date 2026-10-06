"""Folha de expressões (grade N×N) → quadros PNG sem fundo para o retrato da Condessa.

Uso:
    python3 hud/tools/portrait_sheet.py FOLHA.png [--grid 4] [--out ~/.local/share/magi/condessa]

1. Acha a grade pelos separadores escuros (linhas/colunas quase pretas) ou divide igual.
2. Em cada quadro, o fundo é o que tem a cor do canto **e** está ligado às bordas de cima e dos
   lados (não à de baixo, onde o busto encosta): a camisa branca não some junto. Folha que já vem
   com fundo transparente (removedor dedicado: Photopea, Krita, remove.bg) só é recortada.
3. Borda suave: perto do fundo, a opacidade cai com a distância de cor ao fundo e a cor é
   "descontaminada" (tira o cinza do fundo), para o cabelo não ganhar halo claro no HUD escuro.
4. Grava ``frames/01.png`` … ``NN.png`` (ordem de leitura) e, se não existir, um ``portrait.toml``
   de modo "frames" com o mapeamento padrão para a folha de 16 (ajuste à vontade).

Roda com o Python do sistema (Pillow + numpy), como o HUD.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

DEFAULT_TOML = """\
# Retrato em quadros inteiros (folha de expressões 4x4). Números = frames/NN.png, em ordem de leitura.
mode = "frames"
fit = "contain"

[frames]
sleeping = 12      # olhos semicerrados
listening = 1      # neutra, de frente
thinking = 15      # mão no queixo
happy = 3          # sorriso aberto
confused = 14      # susto, gota de suor
alert = 4          # séria

[speaking]         # fala: alterna pelo volume da voz
closed = 2
open = 3

[idle]             # olhares de vez em quando, acordada e calada
glances = [5, 6, 7, 11]
"""


EDGE_PX = 4
FADE_FRAC = 0.14
SIDE_FADE_FRAC = 0.05


def grid_lines(a: np.ndarray, n: int) -> tuple[list[int], list[int]]:
    """Bordas internas dos quadros: separadores escuros, ou divisão igual se não achar."""
    dark = a.sum(axis=2) < 150

    def find(frac: np.ndarray, size: int) -> list[int]:
        idx = np.where(frac > 0.6)[0]
        groups: list[list[int]] = []
        for i in idx:
            if groups and i - groups[-1][-1] <= 1:
                groups[-1].append(int(i))
            else:
                groups.append([int(i)])
        if len(groups) == n + 1:
            return [g[0] if k == n else g[-1] + 1 for k, g in enumerate(groups)]
        return [round(k * size / n) for k in range(n + 1)]

    h, w = dark.shape
    return find(dark.mean(axis=0), w), find(dark.mean(axis=1), h)


def border_fill(cand: np.ndarray) -> np.ndarray:
    """Pixels de ``cand`` ligados às bordas de cima e dos lados (4-vizinhança). A de baixo fica de
    fora: é onde o busto encosta, e a camisa branca é parecida demais com o fundo."""
    reach = np.zeros_like(cand)
    reach[0, :], reach[:, 0], reach[:, -1] = cand[0, :], cand[:, 0], cand[:, -1]
    while True:
        grow = reach.copy()
        grow[1:, :] |= reach[:-1, :]
        grow[:-1, :] |= reach[1:, :]
        grow[:, 1:] |= reach[:, :-1]
        grow[:, :-1] |= reach[:, 1:]
        grow &= cand
        if (grow == reach).all():
            return reach
        reach = grow


def cutout(cell: Image.Image, tol: float = 14.0, band: int = 3) -> Image.Image:
    """Tira o fundo ligado à borda e suaviza a orla."""
    a = np.asarray(cell.convert("RGB")).astype(np.float32)
    h, w, _ = a.shape
    edges = np.concatenate([a[0, :], a[:, 0], a[:, -1]])
    light = edges[edges.sum(axis=1) > 450]  # cor do fundo: os pixels claros da borda
    bg = np.median(light if len(light) else edges, axis=0)
    dist = np.sqrt(((a - bg) ** 2).sum(axis=2))
    bgmask = border_fill(dist < tol)
    # orla: até ``band`` px do fundo, opacidade pela distância de cor (0 no fundo → 1 longe dele)
    m = Image.fromarray((bgmask * 255).astype(np.uint8))
    near = np.asarray(m.filter(ImageFilter.MaxFilter(2 * band + 1))) > 0
    alpha = np.ones((h, w), np.float32)
    alpha[bgmask] = 0.0
    edge = near & ~bgmask
    alpha[edge] = np.clip((dist[edge] - tol) / (tol * 3.0), 0.0, 1.0)
    # descontamina: tira a parte do fundo da cor da orla (c = a·f + (1-a)·bg → f)
    out = a.copy()
    k = edge & (alpha > 0.05)
    out[k] = np.clip((a[k] - (1 - alpha[k, None]) * bg) / alpha[k, None], 0, 255)
    alpha[:EDGE_PX, :] = 0  # resto do separador da folha nas bordas de cima e dos lados
    alpha[:, :EDGE_PX] = 0
    alpha[:, -EDGE_PX:] = 0
    fade = max(1, int(h * FADE_FRAC))  # embaixo: o busto some aos poucos no painel
    alpha[-fade:, :] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)[:, None]
    side = max(1, int(w * SIDE_FADE_FRAC))  # laterais: o cabelo cortado reto pela folha some aos poucos
    ramp = np.linspace(0.0, 1.0, side, dtype=np.float32)
    alpha[:, :side] *= ramp[None, :]
    alpha[:, -side:] *= ramp[::-1][None, :]
    img = Image.fromarray(np.dstack([out, alpha * 255]).astype(np.uint8), "RGBA")
    img.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(0.6)))
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sheet", type=Path)
    ap.add_argument("--grid", type=int, default=4)
    ap.add_argument("--out", type=Path, default=Path("~/.local/share/magi/condessa"))
    ap.add_argument("--inset", type=int, default=6, help="px cortados de cada lado do quadro (separador)")
    args = ap.parse_args()
    out = args.out.expanduser()
    (out / "frames").mkdir(parents=True, exist_ok=True)
    raw = Image.open(args.sheet)
    # folha já transparente (removedor de fundo dedicado): só recorta a grade, sem mexer no fundo
    transparent = raw.mode in ("RGBA", "LA") and np.asarray(raw.getchannel("A")).min() < 250
    sheet = raw.convert("RGBA") if transparent else raw.convert("RGB")
    xs, ys = grid_lines(np.asarray(sheet.convert("RGB")).astype(int), args.grid)
    k = 0
    for r in range(args.grid):
        for c in range(args.grid):
            k += 1
            box = (xs[c] + args.inset, ys[r] + args.inset, xs[c + 1] - args.inset, ys[r + 1] - args.inset)
            cell = sheet.crop(box)
            (cell if transparent else cutout(cell)).save(out / "frames" / f"{k:02d}.png")
    toml = out / "portrait.toml"
    if not toml.exists():
        toml.write_text(DEFAULT_TOML, encoding="utf-8")
    print(f"{k} quadros em {out / 'frames'}; mapeamento em {toml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
