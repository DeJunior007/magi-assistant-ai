import random

import pytest
from face import EXPRESSIONS, FADE_LEN, SLEEP_PERIOD, Face, legible, mouth_for_level, wrap_lines
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFontMetricsF, QGuiApplication, QImage, QPainter


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QGuiApplication.instance() or QGuiApplication([])


@pytest.mark.parametrize("level,mouth", [
    (0.0, "—"), (0.149, "—"), (0.15, "o"), (0.3, "o"), (0.499, "o"), (0.5, "O"), (1.0, "O"),
])
def test_mouth_for_level(level, mouth):
    assert mouth_for_level(level) == mouth


def test_seven_expressions():
    assert set(EXPRESSIONS) == {"sleeping", "listening", "thinking", "speaking", "happy",
                                "confused", "alert"}
    with pytest.raises(ValueError):
        Face().set_state("angry")


def redraws(face: Face, start: float, seconds: float, step: float = 0.005) -> list[float]:
    """Simula um timer rápido chamando tick; devolve os instantes em que pediu redesenho."""
    out, t = [], start
    while t < start + seconds:
        redraw, deadline = face.tick(t)
        assert deadline > t
        if redraw:
            out.append(t)
        t += step
    return out


def test_sleeping_redraws_at_most_every_4s():
    face = Face("sleeping", rng=random.Random(0), now=0.0)
    face.set_subtitle("algo mudou")  # mudanças dormindo também esperam a janela de 4 s
    times = redraws(face, 0.0, 30.0, step=0.05)
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert times and all(g >= SLEEP_PERIOD - 1e-9 for g in gaps)
    assert len(times) <= 30 / SLEEP_PERIOD + 1


def test_sleeping_deadline_is_far():
    face = Face("sleeping", now=0.0)
    face.tick(0.0)
    redraw, deadline = face.tick(0.5)
    assert not redraw and deadline >= SLEEP_PERIOD


def test_awake_never_exceeds_30fps_and_blinks():
    face = Face("speaking", rng=random.Random(1), now=0.0)
    times = []
    t = 0.0
    while t < 20.0:
        face.set_mouth_level(random.random())  # boca mudando o tempo todo
        if face.tick(t)[0]:
            times.append(t)
        t += 0.002
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert min(gaps) >= 1 / 30 - 1e-6
    assert len(times) > 15 * 20  # boca acompanha a voz a >= 15 quadros/s (R17.2)


def test_awake_idle_blinks_and_sleeps_between():
    face = Face("listening", rng=random.Random(2), now=0.0)
    blinks = 0
    t, was = 0.0, False
    while t < 30.0:
        face.tick(t)
        now_blink = face._blinking(t)
        blinks += now_blink and not was
        was = now_blink
        t += 1 / 120
    assert 30 / 6 - 1 <= blinks <= 30 / 3 + 1
    # parada (sem piscar/olhar/fade), o prazo seguinte pula para o próximo evento
    face = Face("happy", rng=random.Random(3), now=0.0)
    face.tick(1.0)
    redraw, deadline = face.tick(1.04)
    assert not redraw and deadline > 1.04 + 1 / 30


def test_entering_sleep_redraws_immediately_then_waits():
    face = Face("speaking", now=0.0)
    face.tick(0.0)
    face.set_state("sleeping")
    assert face.tick(0.04)[0]
    assert not face.tick(1.0)[0]


def test_crossfade_requests_frames_then_settles():
    face = Face("sleeping", rng=random.Random(4), now=0.0)
    face.tick(0.0)
    face.set_state("happy")
    times = redraws(face, 0.01, FADE_LEN + 0.3)
    in_fade = [t for t in times if t < 0.01 + FADE_LEN]
    assert len(in_fade) >= 3
    assert face._prev is None


def test_mouth_glyph_follows_level_only_when_speaking():
    face = Face("speaking", now=0.0)
    face.set_mouth_level(0.9)
    assert face._mouth("speaking") == "O"
    assert face._mouth("happy") == "‿"


def test_wrap_lines_two_lines_keeps_tail():
    font = Face().font("serif", 20)
    fm = QFontMetricsF(font)
    text = " ".join(f"palavra{i}" for i in range(40))
    lines = wrap_lines(text, fm, 200)
    assert len(lines) == 2
    assert lines[0].startswith("…") and lines[1].endswith("palavra39")
    assert all(fm.horizontalAdvance(line) <= 200 for line in lines)
    assert wrap_lines("", fm, 200) == []
    assert len(wrap_lines("日本語の字幕はスペースがなくても折り返す" * 3, fm, 120)) == 2


@pytest.mark.parametrize("size", [(1280, 1440), (160, 100), (1, 1)])
def test_paint_every_expression(size):
    accent = QColor("#ff8c1a")
    for expr in EXPRESSIONS:
        face = Face("listening" if expr == "sleeping" else "sleeping", now=0.0)
        face.set_state(expr)
        face.set_mouth_level(0.7)
        face.set_subtitle("Legenda de teste 字幕 com um texto comprido o bastante para quebrar")
        for t in (0.05, 0.5):  # durante e depois do cross-fade
            face.tick(t)
            img = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img)
            face.paint(p, QRectF(0, 0, *size), accent)
            face.paint(p, QRectF(0, 0, *size), accent, subtitle=True)
            p.end()
        if size[0] > 100:
            assert not img.isNull() and img.pixelColor(size[0] // 2, size[1] // 3).isValid()


def test_paint_draws_something():
    face = Face("happy", now=0.0)
    face.tick(1.0)
    img = QImage(320, 200, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    face.paint(p, QRectF(0, 0, 320, 200), QColor("#6a6aff"))
    p.end()
    lit = sum(img.pixelColor(x, y).alpha() > 0 for x in range(0, 320, 4) for y in range(0, 200, 4))
    assert lit > 50


def test_legible_lightens_dark_accent():
    dark = QColor("#2020a0")
    assert legible(dark) != dark
    assert legible(QColor("#ff8c1a")) == QColor("#ff8c1a")
