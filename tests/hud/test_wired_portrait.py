"""Retrato em camadas da Condessa: arte sintética (quadrados coloridos) num diretório temporário."""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from wired.mascot import BLINK_LEN, Mascot
from wired.portrait import Portrait, PortraitAssets, make_mascot, missing

SIZE = 64
# camada -> (cor, retângulo x, y, w, h no canvas 64×64)
LAYERS = {
    "base.png": ("#404040", (0, 0, 64, 64)),
    "eyes/open.png": ("#00ff00", (16, 16, 32, 8)),
    "eyes/half.png": ("#008800", (16, 16, 32, 8)),
    "eyes/closed.png": ("#0000ff", (16, 16, 32, 8)),
    "mouth/closed.png": ("#ff0000", (24, 44, 16, 6)),
    "mouth/small.png": ("#ff8800", (24, 44, 16, 6)),
    "mouth/open.png": ("#ffff00", (24, 44, 16, 6)),
    "mouth/happy.png": ("#ff00ff", (24, 44, 16, 6)),
    "extra/sleeping.png": ("#ffffff", (52, 2, 8, 8)),
}


def write(folder: Path, layers=LAYERS, toml: str = "breath_px = 0\n") -> Path:
    for rel, (c, (x, y, w, h)) in layers.items():
        img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.fillRect(x, y, w, h, QColor(c))
        p.end()
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        assert img.save(str(folder / rel))
    (folder / "portrait.toml").write_text(toml)
    return folder


def render(m: Mascot, now: float) -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.black)
    p = QPainter(img)
    m.paint(p, QRectF(0, 0, SIZE, SIZE), "#b392f0", now)
    p.end()
    return img


def at(img: QImage, x: int, y: int) -> str:
    return QColor(img.pixel(x, y)).name()


def test_faltando_cai_no_mascote_vetorial(tmp_path):
    assert set(missing(tmp_path)) == {"base.png", "eyes/open.png", "eyes/closed.png", "mouth/closed.png",
                                      "mouth/open.png"}
    m = make_mascot("sleeping", tmp_path)
    assert type(m) is Mascot


def test_camadas_por_estado(tmp_path):
    m = make_mascot("listening", write(tmp_path))
    assert isinstance(m, Portrait)
    m._blink_at = 100.0
    img = render(m, 1.0)
    assert at(img, 32, 20) == "#00ff00" and at(img, 32, 47) == "#ff0000" and at(img, 4, 4) == "#404040"
    # piscada: meio, fechado, meio
    assert m.eye_frame(100.0 + BLINK_LEN * 0.1) == "half"
    assert at(render(m, 100.0 + BLINK_LEN * 0.5), 32, 20) == "#0000ff"
    # fala: boca pelo nível
    m.set_expression("speaking")
    for level, c in ((0.0, "#ff0000"), (0.3, "#ff8800"), (0.9, "#ffff00")):
        m.set_level(level)
        assert at(render(m, 1.0), 32, 47) == c
    # boca parada da expressão
    m.set_expression("happy")
    assert at(render(m, 1.0), 32, 47) == "#ff00ff"
    # dormindo: olhos fechados e o "zz" por cima
    m.set_expression("sleeping")
    img = render(m, 1.0)
    assert at(img, 32, 20) == "#0000ff" and at(img, 55, 5) == "#ffffff"


def test_meio_fechado_opcional_e_olhar(tmp_path):
    layers = {k: v for k, v in LAYERS.items() if k != "eyes/half.png"}
    assets = PortraitAssets(write(tmp_path, layers, "breath_px = 0\ngaze_px = 8\n"))
    m = Portrait(assets, "listening", rng=random.Random(1), now=0.0)
    assert assets.eyes("listening", "half") is assets.layer("eyes/closed.png")
    m._glance_end, m._glance_dir = 1e9, 1
    img = render(m, 1.0)
    assert at(img, 18, 20) == "#404040" and at(img, 52, 20) == "#00ff00"  # olhos 8 px à direita


def test_respira_acordada_e_para_dormindo(tmp_path):
    m = Portrait(PortraitAssets(write(tmp_path, toml="breath_px = 3\nbreath_period = 4\n")), "listening",
                 rng=random.Random(2), now=0.0)
    assert {m.breath(t / 10) for t in range(40)} >= {-3, 3}
    redraw, nxt = m.tick(0.5)
    assert redraw and nxt <= 0.5 + 1 / 8 + 1e-6
    m.set_expression("sleeping")
    assert m.breath(1.0) == 0
    m.tick(10.0)
    assert m.tick(10.5) == (False, 14.0)  # dormindo: 1 redesenho a cada 4 s (R17.4)


@pytest.mark.parametrize("fit", ["contain", "cover"])
def test_encaixe(tmp_path, fit):
    m = Portrait(PortraitAssets(write(tmp_path, toml=f'fit = "{fit}"\nbreath_px = 0\n')), "listening")
    r = m.target(QRectF(0, 18, 64, 28))
    if fit == "contain":  # inteiro e centrado
        assert (r.left(), r.top(), r.width(), r.height()) == (18.0, 18.0, 28.0, 28.0)
    else:  # preenche a largura e corta em cima/embaixo
        assert (r.left(), r.width(), r.height()) == (0.0, 64.0, 64.0)


def write_frames(folder: Path, n: int = 16) -> Path:
    from wired.portrait import FrameAssets  # noqa: F401 - garante o import do módulo

    (folder / "frames").mkdir(parents=True)
    for k in range(1, n + 1):
        img = QImage(32, 32, QImage.Format.Format_ARGB32)
        img.fill(QColor(k * 10, 0, 0))
        assert img.save(str(folder / "frames" / f"{k:02d}.png"))
    (folder / "portrait.toml").write_text(
        'mode = "frames"\n[frames]\nsleeping = 12\nlistening = 1\nthinking = 15\nhappy = 3\n'
        "[speaking]\nclosed = 2\nopen = 3\n[idle]\nglances = [5, 6]\n"
    )
    return folder


def test_quadros_por_estado_fala_e_noite(tmp_path):
    from wired.portrait import FramePortrait

    hour = [14]
    m = make_mascot("listening", write_frames(tmp_path))
    assert isinstance(m, FramePortrait) and m.TALL
    m.hour = lambda: hour[0]
    m._idle_at = 1e9
    assert m.frame_number(1.0) == 1
    m.set_expression("thinking")
    assert m.frame_number(1.0) == 15
    m.set_expression("alert")  # sem quadro próprio: neutra
    assert m.frame_number(1.0) == 1
    m.set_expression("speaking")
    m.set_level(0.05)
    assert m.frame_number(1.0) == 2
    m.set_level(0.8)
    assert m.frame_number(1.0) == 3
    m.set_expression("sleeping")
    assert m.frame_number(1.0) == 1  # de dia, dormindo = neutra
    hour[0] = 23
    assert m.frame_number(1.0) == 12  # à noite, cara de sono
    img = render(m, 1.0)
    assert QColor(img.pixel(32, 32)).red() == 120  # quadro 12 desenhado


def test_olhares_quando_parada(tmp_path):
    m = make_mascot("listening", write_frames(tmp_path))
    m._idle_at = 10.0
    assert m.frame_number(5.0) == 1
    assert m.frame_number(10.5) in (5, 6)  # olhando para um lado
    assert m.frame_number(m._idle_end + 0.01) == 1  # volta
    m.set_expression("speaking")
    assert m.frame_number(m._idle_at + 0.1) in (2, 3)  # falando não olha para os lados


def write_parts(folder: Path) -> Path:
    files = ["parts/head.png", "parts/body.png", "parts/back.png", "eyes/B1.png", "eyes/B2.png",
             "eyes/B3.png",
             "eyes/B4.png", "eyes/B14.png", "eyes/F1.png", "mouth/C1.png", "mouth/C2.png", "mouth/C3.png",
             "mouth/C6.png"]
    for rel in files:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        img.fill(QColor(200, 100, 100))
        assert img.save(str(folder / rel))
    (folder / "portrait.toml").write_text(
        'mode = "parts"\n[states]\n'
        'listening = { eyes = "B1", mouth = "C1", blink = ["B2", "B3"] }\n'
        'happy = { eyes = "B4", mouth = "C6", blink = ["B4", "B4"] }\n'
        'sleeping = { eyes = "B14", mouth = "C1", blink = ["B15", "B15"] }\n'
        '[speech]\nmouths = ["C1", "C2", "C3"]\n[gaze]\nleft = { eyes = "F1", dx = -6, dy = 0 }\n'
    )
    return folder


def test_partes_olhos_boca_e_noite(tmp_path):
    from wired.portrait import PartsPortrait

    hour = [12]
    m = make_mascot("listening", write_parts(tmp_path))
    assert isinstance(m, PartsPortrait) and m.TALL
    m.hour = lambda: hour[0]
    m._blink_at, m._gaze_at = 100.0, 1e9
    assert (m.eyes_id(1.0), m.mouth_id()) == ("B1", "C1")
    assert m.eyes_id(100.0 + BLINK_LEN * 0.1) == "B2" and m.eyes_id(100.0 + BLINK_LEN * 0.5) == "B3"
    m.set_expression("speaking")
    m.set_level(0.3)
    assert m.mouth_id() == "C2"
    m.set_level(0.9)
    assert m.mouth_id() == "C3"
    m.set_expression("sleeping")
    assert m.eyes_id(1.0) == "B1"  # de dia, dormindo = parada e respirando
    hour[0] = 23
    assert m.eyes_id(1.0) == "B14"  # à noite; sem B15 ainda, usa a sonolenta
    assert m.tick(5.0)[0] and render(m, 5.0) is not None


def test_partes_olhar_move_a_cabeca(tmp_path):
    m = make_mascot("listening", write_parts(tmp_path))
    m.hour = lambda: 12
    m._blink_at, m._gaze_at = 1e9, 0.0
    for i in range(40):
        m.tick(1.0 + i)
        m._gaze_end = 1e9
    assert m.eyes_id(50.0) == "F1" and m._head[0] < -5  # olhou para a esquerda e a cabeça foi junto
