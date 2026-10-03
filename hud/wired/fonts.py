"""Fontes do handoff (OFL, em `hud/fonts/`) registradas uma vez no QFontDatabase.

Chaves: "mincho" (Shippori Mincho 700), "cond" (Barlow Condensed 500/600), "mono" (JetBrains
Mono 400/500, arquivo variável) e "jp" (Zen Kaku Gothic New 400/500). Tamanhos em px lógicos.
Precisa de um QGuiApplication criado antes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"

FAMILIES = {
    "mincho": "Shippori Mincho",
    "cond": "Barlow Condensed",
    "mono": "JetBrains Mono",
    "jp": "Zen Kaku Gothic New",
}
DEFAULT_WEIGHT = {"mincho": 700, "cond": 500, "mono": 400, "jp": 400}
FILES = {
    "mincho": ["ShipporiMincho-Bold.ttf"],
    "cond": ["BarlowCondensed-Medium.ttf", "BarlowCondensed-SemiBold.ttf"],
    "mono": ["JetBrainsMono[wght].ttf"],
    "jp": ["ZenKakuGothicNew-Regular.ttf", "ZenKakuGothicNew-Medium.ttf"],
}
# se o arquivo faltar, cai num parente do sistema
FALLBACK = {
    "mincho": ["Noto Serif CJK JP", "serif"],
    "cond": ["Noto Sans", "sans-serif"],
    "mono": ["Noto Sans Mono", "monospace"],
    "jp": ["Noto Sans CJK JP", "sans-serif"],
}
VARIABLE = {"mono"}  # pesos pelo eixo "wght"

_loaded: dict[str, bool] | None = None
_fonts: dict[tuple, QFont] = {}


def load() -> dict[str, bool]:
    """Registra as fontes (idempotente). Devolve {chave: carregou}."""
    global _loaded
    if _loaded is None:
        ok = {}
        for key, names in FILES.items():
            got = False
            for n in names:
                fid = QFontDatabase.addApplicationFont(str(FONT_DIR / n))
                got = got or (fid >= 0 and FAMILIES[key] in QFontDatabase.applicationFontFamilies(fid))
            ok[key] = got
        _loaded = ok
    return dict(_loaded)


def font(key: str, px: float, weight: int | None = None, spacing: float = 0.0) -> QFont:
    """QFont da família `key` com `px` lógicos; `spacing` em em (letter-spacing do CSS)."""
    if key not in FAMILIES:
        raise KeyError(f"família desconhecida: {key}")
    weight = DEFAULT_WEIGHT[key] if weight is None else int(weight)
    ck = (key, round(px * 4) / 4, weight, round(spacing, 4))
    f = _fonts.get(ck)
    if f is None:
        loaded = load()
        f = QFont()
        f.setFamilies([FAMILIES[key], *FALLBACK[key]] if loaded.get(key) else FALLBACK[key])
        f.setPixelSize(max(1, round(px)))  # só inteiro; a escala 4/3 vem do painter
        f.setWeight(QFont.Weight(weight))
        if key in VARIABLE and hasattr(f, "setVariableAxis"):
            f.setVariableAxis(QFont.Tag("wght"), float(weight))
        f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)  # escala 4/3 sem saltos
        f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        if spacing:
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, px * spacing)
        _fonts[ck] = f
    return QFont(f)
