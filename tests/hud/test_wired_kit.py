import random

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFontInfo, QImage, QPainter
from wired import fonts, kit, scene
from wired.mascot import EXPRESSIONS, SLEEP_PERIOD, Mascot, mouth_for_level
from wired.theme import CPU, GPU, HOT, SEG_OFF, WARN, color, tint


def img(w=400, h=200):
    im = QImage(w, h, QImage.Format.Format_ARGB32)
    im.fill(QColor("#000000"))
    return im


def test_fonts_load():
    ok = fonts.load()
    assert ok == {"mincho": True, "cond": True, "mono": True, "jp": True}
    assert fonts.load() == ok  # idempotente
    for key, fam in fonts.FAMILIES.items():
        assert QFontInfo(fonts.font(key, 20)).family() == fam
    f = fonts.font("cond", 22, 600, spacing=0.04)
    assert f.pixelSize() == 22 and f.weight() == 600
    with pytest.raises(KeyError):
        fonts.font("comic", 12)


def test_tint_led_off_uses_unit_colors():
    t = tint(CPU, "#ff3b6b", False)
    assert t.color.name() == CPU and t.seg.name() == CPU
    assert t.border.name() == "#3b2f55" and t.bg.name() == "#141120"
    assert tint(GPU, None, True).color.name() == GPU  # sem cor do OpenRGB = off


def test_tint_led_on():
    t = tint(CPU, "#ff3b6b", True)
    assert t.color.name() == "#ff3b6b" and t.seg.name() == "#ff3b6b"
    assert (t.border.name(), t.border.alpha()) == ("#ff3b6b", 0x88)
    assert (t.bg.name(), t.bg.alpha()) == ("#ff3b6b", 0x14)


def test_color_parses_css_alpha_and_tokens():
    c = color("#ff3b6b88")
    assert c.name() == "#ff3b6b" and c.alpha() == 0x88
    assert color("text-dim").name() == "#8f89a6"


@pytest.mark.parametrize("pct,lit", [(0, 0), (51, 12), (2, 0), (3, 1), (100, 24), (150, 24), (-5, 0)])
def test_lit_count_rounds_like_canvas(pct, lit):
    assert kit.lit_count(24, pct) == lit


def test_segment_colors_warn_and_hot():
    cols = [c.name() for c in kit.segment_colors(20, 100, CPU, warn_from=15)]
    assert cols[:15] == [CPU] * 15
    assert cols[15:17] == [WARN] * 2
    assert cols[17:] == [HOT] * 3
    cols = [c.name() for c in kit.segment_colors(20, 80, CPU, warn_from=15)]
    assert cols[15] == WARN and cols[16:] == [SEG_OFF] * 4
    assert [c.name() for c in kit.segment_colors(20, 100, GPU)] == [GPU] * 20


def test_segments_paints_lit_count():
    im = img(242, 10)
    p = QPainter(im)
    n = kit.segments(p, QRectF(0, 0, 242, 10), 24, 50, CPU)
    p.end()
    assert n == 12
    # segmento i começa em i*(8+2): 12º aceso, 13º apagado
    assert im.pixelColor(11 * 10 + 4, 5).name() == CPU
    assert im.pixelColor(12 * 10 + 4, 5).name() == SEG_OFF
    assert im.pixelColor(8, 5).name() == "#000000"  # gap de 2 px


def test_panel_chamfer_and_accent():
    im = img(200, 100)
    p = QPainter(im)
    kit.panel(p, QRectF(0, 0, 200, 100))
    p.end()
    assert im.pixelColor(199, 0).name() == "#000000"  # canto chanfrado
    assert im.pixelColor(0, 99).name() == "#000000"
    assert im.pixelColor(30, 1).name() == "#3a3646"  # traço 56×3
    assert im.pixelColor(100, 50).name() == "#0f0e15"


def test_scanlines_cached_and_periodic():
    pm = kit.scanlines_pixmap(10, 9)
    assert pm is kit.scanlines_pixmap(10, 9)
    im = pm.toImage()
    assert [im.pixelColor(0, y).alpha() > 0 for y in range(6)] == [True, False, False] * 2


def test_sparkline_skips_gaps_and_draws():
    im = img(100, 40)
    p = QPainter(im)
    kit.sparkline(p, QRectF(0, 0, 100, 40), [50, 50, None, 50, 50], "#ffffff", 2)
    kit.sparkline(p, QRectF(0, 0, 100, 40), [None], "#ffffff")  # nada para desenhar
    p.end()
    assert im.pixelColor(10, 20).red() > 100
    assert im.pixelColor(50, 20).red() < 30  # lacuna no meio


def test_scene_cache_and_standby_safe_area():
    a = scene.main_scene(540, 500, CPU)
    assert a is scene.main_scene(540, 500, CPU)
    assert a is not scene.main_scene(540, 500, "#ff3b6b")
    pm = scene.main_scene(300, 200, CPU, scale=4 / 3)
    assert (pm.width(), pm.height()) == (400, 267)
    assert scene.standby_text_safe(QRectF(160, 170, 900, 740))  # relógio
    assert scene.standby_text_safe(QRectF(1180, 170, 440, 740))  # coluna da direita
    assert not scene.standby_text_safe(QRectF(1700, 500, 100, 100))  # poste


def test_mascot_expressions_and_mouth():
    m = Mascot(now=0.0)
    assert m.sleeping and set(EXPRESSIONS) == {"sleeping", "listening", "thinking", "speaking",
                                                "happy", "confused", "alert"}
    with pytest.raises(ValueError):
        m.set_expression("angry")
    m.set_expression("speaking")
    for level, mouth in ((0.0, "—"), (0.149, "—"), (0.15, "o"), (0.49, "o"), (0.5, "O"), (2.0, "O")):
        m.set_level(level)
        assert m.mouth == mouth == mouth_for_level(min(level, 1.0))
    m.set_state("happy")  # apelidos do face.py
    assert m.mouth == "grin"


@pytest.mark.parametrize("expr", EXPRESSIONS)
def test_mascot_paints_every_expression(expr):
    im = img(260, 150)
    p = QPainter(im)
    m = Mascot(expr, now=0.0)
    m.set_level(0.8)
    m.paint(p, QRectF(0, 0, 260, 150), "#ff3b6b")
    p.end()
    blush = im.pixelColor(84, 89)  # traço do rubor na cor de acento
    assert blush.red() > 150 and blush.green() < 120


def redraws(m: Mascot, start: float, seconds: float, step: float = 0.005) -> list[float]:
    out, t = [], start
    while t < start + seconds:
        if m.tick(t)[0]:
            out.append(t)
        t += step
    return out


def test_sleeping_redraws_at_most_every_4s():
    m = Mascot("sleeping", rng=random.Random(1), now=0.0)
    times = redraws(m, 0.0, 20.0)
    assert 1 <= len(times) <= 6
    assert all(b - a >= SLEEP_PERIOD - 1e-6 for a, b in zip(times, times[1:], strict=False))


def test_awake_capped_at_30fps_and_speaking_at_least_15():
    m = Mascot("speaking", rng=random.Random(2), now=0.0)
    out, t, i = [], 0.0, 0
    while t < 2.0:
        m.set_level(0.8 if i % 2 else 0.0)  # boca troca a cada passo
        if m.tick(t)[0]:
            out.append(t)
        t += 0.005
        i += 1
    gaps = [b - a for a, b in zip(out, out[1:], strict=False)]
    assert min(gaps) >= 1 / 30 - 1e-6
    assert len(out) >= 2.0 * 15


def test_expression_change_redraws_immediately_even_asleep():
    m = Mascot("listening", rng=random.Random(3), now=0.0)
    m.tick(0.0)
    m.set_expression("sleeping")
    assert m.tick(0.01)[0]
    m.set_expression("alert")
    assert m.tick(0.05)[0]


def test_blink_and_glance_change_key():
    m = Mascot("listening", rng=random.Random(4), now=0.0)
    m.tick(0.0)
    t_blink = m._blink_at + 0.01
    assert m.blinking(t_blink) and not m.blinking(t_blink + 0.2)
    assert not Mascot("happy", now=0.0).blinking(Mascot("happy", now=0.0)._blink_at + 0.01)
    times = redraws(m, 0.04, 15.0)
    assert len(times) >= 2  # piscada (e olhar) pedem redesenho sozinhos
