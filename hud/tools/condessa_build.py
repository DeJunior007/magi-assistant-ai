"""Pasta de imagens da Condessa (fundo verde, nomeadas pelo ID da checklist) → camadas do 2.5D.

Uso: python3 hud/tools/condessa_build.py [PASTA] [--out ~/.local/share/magi/condessa]

Entrada (``docs/design/CONDESSA-RETRATO.md`` e a checklist "Arte da Condessa"): A1 (base), B2..B15
(olhos), F1..F7 (olhares), C2..C14 (bocas), E1 (franja), E2 (fone), P1/P2/P3 (cabelo de trás e
marias-chiquinhas), P5 (rosto sem cabelo), P6 (corpo), P7/P8 (braços). Qualquer tamanho quadrado
(normaliza para 1024); .jpg ou .png.

Saída (lida por ``wired.portrait.PartsPortrait``):
- ``parts/<nome>.png``: partes recortadas pelo verde (chroma key, ``despill`` do verde vazado e
  ``defringe`` da orla com a cor de dentro); ``head`` é o P5 da cabeça até o pescoço, ``body`` o P6,
  e a junta entre os dois é esfumada. Mechas/franja/presilha (H1–H4 → ``lock_l``, ``lock_r``,
  ``bangs_c``, ``clip``): silhueta da H alinhada contra a A1, cor da A1 (``split_hair``); pontas
  (H5–H7 → ``*_tip``) com o segmento-pai cortado abaixo da junta (``build_tips``).
- ``eyes/<ID>.png`` e ``mouth/<ID>.png``: "remendos" — a região dos olhos/boca da variação, com a
  borda esfumada, no quadro inteiro (o resto transparente). A1 dá os neutros (B1, C1).
- ``extra/fone.png``: o que o E2 tem de diferente da base (o fone).
- ``portrait.toml``: ``mode = "parts"`` e o mapeamento estado → olhos/boca (só é escrito se não existir).

Roda com o Python do sistema (Pillow + numpy), como o HUD.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

SIZE = 1024
EYES_BOX = (300, 290, 740, 495)
MOUTH_BOX = (440, 488, 600, 592)
FEATHER = 16
HEAD_SPLIT = (690, 730)  # y onde a cabeça (P5, com pescoço e gola) passa a ser o corpo (P6)
DIFF_MIN = 60  # diferença de cor (soma RGB) que conta como "mudou" no E2
FADE_BOTTOM = 0.14  # o busto some aos poucos embaixo (sem corte reto no painel)
NECK_X = (370, 660)  # abaixo do queixo a cabeça (P5) fica só com pescoço e gola
CHIN_Y = 560
ARMS = ("P7", "P8")
ARM_TOP_Y = 740  # os braços só aparecem abaixo disto (acima, o ombro é do corpo)
PARTS = {"P1": "back", "P2": "tail_l", "P3": "tail_r", "P7": "arm_l", "P8": "arm_r", "P6": "body",
         "E1": "bangs"}
# pontas (H5–H7): a parte de baixo do segmento-pai, com junta esfumada (cabelo em dois segmentos)
TIPS = {"H5": ("P2", "tail_l"), "H6": ("P3", "tail_r"), "H7": ("P1", "back")}
JOINT_FADE = 28  # px de transição entre o segmento de cima e a ponta
IRIS_DIFF = 70  # diferença A1 × O1 que conta como íris
CHOKE = 0.08  # alfa abaixo disto (halo do verde) some; o resto é reescalado
SOLID = 0.95  # alfa a partir do qual o pixel é "de dentro" (fonte de cor do defringe)
HUE_K = 0.5  # teto do verde no opaco: lo + HUE_K·(hi − lo) de vermelho/azul (ver despill)
DEFRINGE_R = 3  # raio (px) da vizinhança que dá a cor da orla
RING = 1  # px logo dentro da orla tratados como orla (o verde vaza um pouco para dentro)
# mechas regeneradas pela IA (H1–H4): só a silhueta vale; a cor vem da A1 (ver split_hair)
SPLIT = {"H1": "lock_l", "H2": "lock_r", "H3": "bangs_c", "H4": "clip"}
SHIFT_MAX = 8  # busca do deslocamento ótimo da silhueta contra a A1 (±px)

DEFAULT_TOML = """\
# Condessa em partes (2.5D). Olhos/bocas = IDs da checklist (eyes/<ID>.png, mouth/<ID>.png).
mode = "parts"
renderer = "gl"                # malhas e pós-processamento na GPU (portrait_gl); "cpu" volta

[states]                       # olhos, boca parada, piscada (meio, fechado)
listening = { eyes = "B1", mouth = "C1", blink = ["B2", "B3"] }
speaking  = { eyes = "B1", mouth = "C1", blink = ["B2", "B3"] }
thinking  = { eyes = "B13", mouth = "C7", blink = ["B2", "B3"] }
happy     = { eyes = "B4", mouth = "C6", blink = ["B5", "B5"] }
confused  = { eyes = "B10", mouth = "C7", blink = ["B11", "B12"] }
alert     = { eyes = "B6", mouth = "C8", blink = ["B7", "B8"] }
sleeping  = { eyes = "B14", mouth = "C1", blink = ["B15", "B15"] }   # noite: dormindo (B15)

[speech]                       # boca da fala pelo volume: fechada, entreaberta, aberta
mouths = ["C1", "C2", "C3"]

[gaze]                         # olhares quando parada (olho, deslocamento da cabeça em px)
left = { eyes = "F1", dx = -6, dy = 0 }
right = { eyes = "F6", dx = 6, dy = 0 }
up_right = { eyes = "F4", dx = 5, dy = -3 }
down_left = { eyes = "F3", dx = -5, dy = 3 }
down_right = { eyes = "F5", dx = 5, dy = 3 }
down = { eyes = "F7", dx = 0, dy = 4 }
"""


def load(folder: Path, ident: str) -> Image.Image | None:
    for name in (ident, ident.lower()):
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            p = folder / f"{name}{ext}"
            if p.exists():
                im = Image.open(p).convert("RGB")
                return im if im.size == (SIZE, SIZE) else im.resize((SIZE, SIZE), Image.LANCZOS)
    return None


def _box(x: np.ndarray, r: int) -> np.ndarray:
    """Média numa janela (2r+1)² (somas acumuladas; borda repetida). Funciona com float e canais."""
    pad = [(r, r), (r, r)] + [(0, 0)] * (x.ndim - 2)
    c = np.pad(x.astype(np.float64), pad, mode="edge").cumsum(0).cumsum(1)
    c = np.pad(c, [(1, 0), (1, 0)] + [(0, 0)] * (x.ndim - 2))
    n = 2 * r + 1
    s = c[n:, n:] - c[:-n, n:] - c[n:, :-n] + c[:-n, :-n]
    return (s / (n * n)).astype(np.float32)


def _inner(alpha: np.ndarray, ring: int = RING) -> np.ndarray:
    """Alfa erodido ``ring`` px (mínimo na janela): o anel logo dentro da orla também conta como
    orla. Ali o JPEG/IA já misturou o verde (castanho-oliva, mas "opaco" pela conta do alfa)."""
    im = Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(2 * ring + 1))
    return np.asarray(im).astype(np.float32) / 255


def despill(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Tira o verde vazado. Por dentro o verde fica no máximo a meio caminho entre o menor e o
    maior de vermelho/azul (pele, rosa e branco já são assim: na A1 só ~600 pixels de orla oliva
    passavam disso). Na orla e no anel logo dentro dela o teto é o menor dos dois: o cabelo tem o
    verde como menor canal, e rosa ou contorno escuro + verde vira vinho, não oliva/castanho.
    A personagem não tem verde nem amarelo."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lo, hi = np.minimum(r, b), np.maximum(r, b)
    out = rgb.copy()
    k = np.where(_inner(alpha) < SOLID, 0.0, HUE_K)
    out[..., 1] = np.minimum(g, lo + (hi - lo) * k)
    return out


def defringe(rgb: np.ndarray, alpha: np.ndarray, radius: int = DEFRINGE_R) -> np.ndarray:
    """Orla com a cor de dentro: cada pixel da orla (e do anel logo dentro dela) puxa a cor média
    dos pixels bem de dentro na vizinhança (dilatação da cor pré-multiplicada), tanto mais quanto
    mais perto da borda. Fio fino sem miolo por perto fica com a própria cor (só sem o verde) — não
    come fio nem mexe no alfa."""
    inner = _inner(alpha)
    solid = (inner >= SOLID).astype(np.float32)
    w = _box(_box(solid, radius), radius)
    near = _box(_box(rgb * solid[..., None], radius), radius) / np.maximum(w, 1e-6)[..., None]
    k = np.where((inner < SOLID) & (w > 0.02), 1 - inner * alpha, 0)[..., None]
    return rgb * (1 - k) + near * k


def chroma(im: Image.Image, lo: float = 18.0, hi: float = 70.0) -> Image.Image:
    """Tira o fundo verde: alfa pela dominância do verde (com um leve aperto na orla, que some
    com o halo mais fraco), verde vazado tirado (``despill``) e orla recolorida pelos vizinhos
    de dentro (``defringe``) — sem isso os fios ficavam com contorno verde/oliva no HUD."""
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    d = a[..., 1] - np.maximum(a[..., 0], a[..., 2])
    alpha = np.clip((hi - d) / (hi - lo), 0, 1)
    alpha = np.clip((alpha - CHOKE) / (1 - CHOKE), 0, 1)
    rgb = despill(defringe(despill(a, alpha), alpha), alpha)  # a média dos vizinhos não traz verde
    return Image.fromarray(np.dstack([rgb, alpha * 255]).round().clip(0, 255).astype(np.uint8), "RGBA")


def rect_mask(box: tuple[int, int, int, int], feather: int = FEATHER) -> np.ndarray:
    m = Image.new("L", (SIZE, SIZE), 0)
    x0, y0, x1, y1 = box
    m.paste(255, (x0 + feather, y0 + feather, x1 - feather, y1 - feather))
    return np.asarray(m.filter(ImageFilter.GaussianBlur(feather / 2))).astype(np.float32) / 255


def patch(im: Image.Image, mask: np.ndarray) -> Image.Image:
    """Remendo: a imagem recortada pelo verde (mesmo despill/defringe das partes) só dentro de ``mask``."""
    return with_alpha(chroma(im), mask)


def not_shirt(base: Image.Image) -> np.ndarray:
    """0 onde a base mostra camisa/gola/gravata (o braço gerado às vezes invade o tronco), 1 fora."""
    a = np.asarray(base).astype(np.int32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    lo, hi = np.minimum(np.minimum(r, g), b), np.maximum(np.maximum(r, g), b)
    white = (lo > 165) & (hi - lo < 28)
    tie = (r > 120) & (g < 60) & (b < 80) & (r - b > 70)
    m = Image.fromarray(((white | tie) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))
    m = np.asarray(m.filter(ImageFilter.GaussianBlur(3))).astype(np.float32) / 255
    return 1.0 - m


def arm_area(base: Image.Image) -> np.ndarray:
    """Onde um braço pode aparecer: abaixo do ombro (o ombro já vem inteiro no corpo, P6) e nunca
    sobre a camisa. Corta ombros que a IA desenhou altos demais (viravam borrão entre as mechas)."""
    y = np.arange(SIZE, dtype=np.float32)[:, None]
    below = np.clip((y - ARM_TOP_Y) / 30, 0, 1) * np.ones((1, SIZE), np.float32)
    return below * not_shirt(base)


def neck_only() -> np.ndarray:
    """1 em cima do queixo; abaixo, só a faixa do pescoço/gola (as laterais ficam com as mechas)."""
    m = Image.new("L", (SIZE, SIZE), 0)
    m.paste(255, (0, 0, SIZE, CHIN_Y))
    m.paste(255, (NECK_X[0], 0, NECK_X[1], SIZE))
    return np.asarray(m.filter(ImageFilter.GaussianBlur(10))).astype(np.float32) / 255


def bottom_fade() -> np.ndarray:
    y = np.arange(SIZE, dtype=np.float32)[:, None]
    start = SIZE * (1 - FADE_BOTTOM)
    return np.clip((SIZE - y) / (SIZE - start), 0, 1) * np.ones((1, SIZE), np.float32)


def with_alpha(im: Image.Image, factor: np.ndarray) -> Image.Image:
    rgba = np.asarray(im).astype(np.float32).copy()
    rgba[..., 3] *= factor
    return Image.fromarray(rgba.astype(np.uint8), "RGBA")


def build(src: Path, out: Path) -> list[str]:
    report: list[str] = []
    base = load(src, "A1")
    if base is None:
        raise SystemExit(f"falta A1 em {src}")
    for d in ("parts", "eyes", "mouth", "extra"):
        (out / d).mkdir(parents=True, exist_ok=True)
    for ident, name in PARTS.items():
        im = load(src, ident)
        if im is None:
            report.append(f"falta {ident} ({name})")
            continue
        factor = bottom_fade() * (arm_area(base) if ident in ARMS else 1.0)
        with_alpha(chroma(im), factor).save(out / "parts" / f"{name}.png")
    # cabeça = P5 até o pescoço; o corpo vem do P6 (junta esfumada)
    head = load(src, "P5")
    if head is None:
        report.append("falta P5 (head)")
    else:
        y = np.arange(SIZE, dtype=np.float32)[:, None]
        fade = np.clip((HEAD_SPLIT[1] - y) / (HEAD_SPLIT[1] - HEAD_SPLIT[0]), 0, 1) * np.ones((1, SIZE))
        with_alpha(chroma(head), fade * neck_only()).save(out / "parts" / "head.png")
    eyes, mouth = rect_mask(EYES_BOX), rect_mask(MOUTH_BOX)
    patch(base, eyes).save(out / "eyes" / "B1.png")
    patch(base, mouth).save(out / "mouth" / "C1.png")
    for ident in [f"B{i}" for i in range(2, 16)] + [f"F{i}" for i in range(1, 8)]:
        im = load(src, ident)
        (patch(im, eyes).save(out / "eyes" / f"{ident}.png") if im else report.append(f"falta {ident}"))
    for ident in [f"C{i}" for i in range(2, 15)] + [f"V{i}" for i in range(1, 7)]:
        im = load(src, ident)
        (patch(im, mouth).save(out / "mouth" / f"{ident}.png") if im else report.append(f"falta {ident}"))
    fone = load(src, "E2")
    if fone is not None:
        diff = np.abs(np.asarray(fone).astype(int) - np.asarray(base).astype(int)).sum(axis=2) > DIFF_MIN
        m = Image.fromarray((diff * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
        m = np.asarray(m.filter(ImageFilter.GaussianBlur(2))).astype(np.float32) / 255
        with_alpha(chroma(fone), m).save(out / "extra" / "fone.png")
    report += split_hair(src, out, base)
    report += build_tips(src, out)
    report += build_eyes_brows(src, out, base)
    toml = out / "portrait.toml"
    if not toml.exists() or "mode = \"parts\"" not in toml.read_text(encoding="utf-8"):
        toml.write_text(DEFAULT_TOML, encoding="utf-8")
    return report


def _alpha(im: Image.Image) -> np.ndarray:
    return np.asarray(im).astype(np.float32)[..., 3] / 255


def build_tips(src: Path, out: Path) -> list[str]:
    """Pontas do cabelo: a ponta (H5–H7, recorte alinhado da base) entra esfumada a partir da
    junta, e o segmento-pai (P2/P3/P1) só some nas mesmas colunas depois que a ponta já está
    inteira. Antes os dois esfumavam na mesma faixa (meio a meio = só 75% de cobertura): a junta
    ficava translúcida e, com o balanço, mostrava os dois segmentos como fantasma."""
    report = []
    y = np.arange(SIZE, dtype=np.float32)[:, None]
    for tip_id, (_parent_id, parent_name) in TIPS.items():
        tip = load(src, tip_id)
        parent_path = out / "parts" / f"{parent_name}.png"
        if tip is None or not parent_path.exists():
            continue
        tip_rgba = with_alpha(chroma(tip), bottom_fade())
        a = _alpha(tip_rgba)
        rows = np.where(a.max(axis=1) > 0.5)[0]
        if not len(rows):
            report.append(f"{tip_id} vazio")
            continue
        joint = float(rows[0])
        ramp = np.clip((y - joint) / JOINT_FADE, 0, 1) * np.ones((1, SIZE), np.float32)
        gone = np.clip((y - joint - JOINT_FADE) / JOINT_FADE, 0, 1) * np.ones((1, SIZE), np.float32)
        cols = Image.fromarray(((a > 0.3) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(15))
        cols = np.asarray(cols.filter(ImageFilter.GaussianBlur(6))).astype(np.float32) / 255
        with_alpha(tip_rgba, ramp).save(out / "parts" / f"{parent_name}_tip.png")
        parent = Image.open(parent_path).convert("RGBA")
        with_alpha(parent, 1 - gone * cols).save(parent_path)
    return report


def _shift(x: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """``x`` deslocado (dx, dy) px, com zero no que entra pela borda."""
    out = np.zeros_like(x)
    h, w = x.shape[:2]
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = \
        x[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


def best_shift(rgba: np.ndarray, ref: np.ndarray, reach: int = SHIFT_MAX) -> tuple[int, int, float, float]:
    """Deslocamento inteiro (dx, dy) de ``rgba`` que mais o aproxima de ``ref`` (RGBA, 0–1) no
    que os dois têm de opaco. Devolve (dx, dy, erro sem deslocar, erro no melhor), erro em 0–255."""
    ys, xs = np.nonzero(rgba[..., 3] > SOLID)
    if not len(ys):
        return 0, 0, 0.0, 0.0
    y0, y1 = max(ys.min() - reach, 0), min(ys.max() + reach + 1, SIZE)
    x0, x1 = max(xs.min() - reach, 0), min(xs.max() + reach + 1, SIZE)
    crop, rc = rgba[y0:y1, x0:x1], ref[y0:y1, x0:x1]

    def err(dx: int, dy: int) -> float:
        sh = _shift(crop, dx, dy)
        m = (sh[..., 3] > SOLID) & (rc[..., 3] > SOLID)
        return float(np.abs(sh[..., :3] - rc[..., :3])[m].mean() * 255) if m.any() else 1e9

    scores = {(dx, dy): err(dx, dy) for dy in range(-reach, reach + 1) for dx in range(-reach, reach + 1)}
    dx, dy = min(scores, key=scores.__getitem__)
    return dx, dy, scores[(0, 0)], scores[(dx, dy)]


def split_hair(src: Path, out: Path, base: Image.Image) -> list[str]:
    """Mechas laterais, franja central e presilha (H1–H4) soltas. A IA redesenhou essas imagens:
    mesmo no melhor deslocamento os fios não batem com a A1 (erro médio 16–18 de 255 contra ~6 das
    pontas H5–H7, que são recorte da base), e por cima do cabelo de trás (P1) e da cabeça (P5) isso
    aparecia como fios duplicados, meio transparentes ("fantasma"). Então da H só vale a silhueta
    (alinhada pelo deslocamento ótimo e endurecida, para não ter meia-transparência por cima de
    outro cabelo); a cor é a da A1 — em repouso fica igual à base."""
    report = []
    ref_im = chroma(base)
    ref = np.asarray(ref_im).astype(np.float32) / 255
    for ident, name in SPLIT.items():
        im = load(src, ident)
        if im is None:
            report.append(f"falta {ident} ({name})")
            continue
        rgba = np.asarray(chroma(im)).astype(np.float32) / 255
        dx, dy, e0, e1 = best_shift(rgba, ref)
        a = _shift(rgba[..., 3], dx, dy)
        hard = np.clip((a - 0.25) / 0.5, 0, 1)
        hard = hard * hard * (3 - 2 * hard)  # smoothstep: borda de ~1 px, sem meia-transparência larga
        soft = Image.fromarray((hard * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.7))
        m = np.asarray(soft).astype(np.float32) / 255 * ref[..., 3] * bottom_fade()
        with_alpha(ref_im, m).save(out / "parts" / f"{name}.png")
        report.append(f"{ident} ({name}): silhueta deslocada ({dx:+d}, {dy:+d}) px, "
                      f"erro {e0:.1f} → {e1:.1f}; cor da A1")
    return report


def _largest(mask: np.ndarray, keep: int = 2) -> np.ndarray:
    """As ``keep`` maiores manchas de ``mask`` (flood fill do Pillow; sem scipy)."""
    from PIL import ImageDraw

    img = Image.fromarray((mask * 255).astype(np.uint8)).copy()  # cópia: o flood fill escreve nela
    areas: list[tuple[int, int]] = []
    label = 1
    ys, xs = np.nonzero(np.asarray(img) == 255)
    for y0, x0 in zip(ys, xs, strict=True):
        if label > 250:
            break
        if img.getpixel((int(x0), int(y0))) != 255:
            continue
        ImageDraw.floodfill(img, (int(x0), int(y0)), label)
        areas.append((int((np.asarray(img) == label).sum()), label))
        label += 1
    best = {lab for _, lab in sorted(areas, reverse=True)[:keep]}
    arr = np.asarray(img)
    return np.isin(arr, list(best)) if best else np.zeros_like(mask, bool)


def build_eyes_brows(src: Path, out: Path, base: Image.Image) -> list[str]:
    """Olhar livre: a O1 (olhos sem íris) dá o contorno de cada olho (as 2 maiores manchas
    brancas, limpas dos fios da franja) e, dentro dele, a diferença A1 × O1 é a íris.
    Sobrancelhas soltas (O2) ficaram de fora: nesta arte a franja cobre quase tudo e a diferença
    pegava fios de cabelo, não sobrancelha."""
    report = []
    o1 = load(src, "O1")
    if o1 is None:
        return ["falta O1 (olhar livre)"]
    b = np.asarray(base).astype(np.int32)
    a = np.asarray(o1).astype(np.int32)
    box = np.zeros((SIZE, SIZE), bool)
    x0, y0, x1, y1 = EYES_BOX
    box[y0:y1, x0:x1] = True
    lo = a.min(axis=2)
    # branco do olho: claro, quase sem cor e com azul >= verde (a pele clara tem azul < verde)
    white = (lo > 160) & (a.max(axis=2) - lo < 30) & (a[..., 2] >= a[..., 1] - 3) & box
    clean = Image.fromarray((white * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(5))
    clean = clean.filter(ImageFilter.MaxFilter(5))
    eyes = _largest(np.asarray(clean) > 127)
    if eyes.sum() < 800:
        return ["O1: não achei o contorno dos olhos"]
    grown = np.asarray(Image.fromarray((eyes * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))) > 127
    iris = (np.abs(a - b).sum(axis=2) > IRIS_DIFF) & grown
    # abertura = branco do olho + a íris parada (nunca corta a íris em repouso), sem buracos
    opening = Image.fromarray(((eyes | iris) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))
    opening = opening.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(0.8))
    iris_m = Image.fromarray((iris * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))
    iris_m = np.asarray(iris_m.filter(ImageFilter.GaussianBlur(0.8))).astype(np.float32) / 255
    patch(base, iris_m).save(out / "parts" / "iris.png")
    Image.merge("RGBA", [opening] * 4).save(out / "parts" / "eye_open.png")
    patch(o1, rect_mask(EYES_BOX)).save(out / "eyes" / "O1.png")
    for stale in ("brow_l.png", "brow_r.png"):
        (out / "parts" / stale).unlink(missing_ok=True)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src", nargs="?", type=Path, default=Path("~/Downloads/Condessa"))
    ap.add_argument("--out", type=Path, default=Path("~/.local/share/magi/condessa"))
    args = ap.parse_args()
    report = build(args.src.expanduser(), args.out.expanduser())
    print("\n".join(report) or "tudo montado")
    print(f"camadas em {args.out.expanduser()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
