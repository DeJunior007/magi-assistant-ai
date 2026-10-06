"""Dia e noite do cenário e o animador (sem relógio real: horários e ``mono`` fixos)."""

from __future__ import annotations

import random
from datetime import datetime

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QGuiApplication
from wired import scene, sky


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QGuiApplication.instance() or QGuiApplication([])


def at(h: int, m: int = 0) -> sky.Sky:
    return sky.sky_at(datetime(2026, 10, 6, h, m))


def test_paleta_por_hora():
    assert at(2) == sky.NIGHT and at(12) == sky.DAY
    dawn = at(6)
    assert dawn == sky.DAWN
    meio = at(5, 30)  # entre noite e amanhecer: interpolado
    assert sky.NIGHT.lights > meio.lights > sky.DAWN.lights
    assert at(12, 1) == at(12, 4)  # arredondado a 5 min (cache muda pouco)
    assert sky.DAY.sun > 0 and sky.DAY.moon == 0 and sky.NIGHT.moon == 1


def test_fundo_cacheado_por_paleta():
    a = scene.main_scene(540, 500, "#b392f0", 1.0, sky.DAY, live=False)
    assert a is scene.main_scene(540, 500, "#b392f0", 1.0, sky.DAY, live=False)
    assert a is not scene.main_scene(540, 500, "#b392f0", 1.0, sky.NIGHT, live=False)


def test_janelas_seguem_a_hora_e_trocam_aos_poucos():
    a = scene.SceneAnimator("main", random.Random(1), mono=0)
    a.set_sky(sky.NIGHT)
    a._fill_to_target()
    noite = sum(a.lit)
    a.set_sky(sky.DAY)
    for t in range(1, 2000, 7):  # ~4 h a cada 7 s: vai apagando uma de cada vez
        a.tick(float(t))
    assert sum(a.lit) == round(sky.DAY.lights * len(a.windows)) < noite


def test_passaro_aparece_e_vai_embora():
    a = scene.SceneAnimator("main", random.Random(2), mono=0)
    seen = False
    for t in range(0, 3000, 5):
        a.tick(float(t))
        seen = seen or a.bird is not None
    assert seen


def test_ritmo_e_regioes_da_espera_fora_do_texto():
    a = scene.SceneAnimator("standby", random.Random(3), mono=0)
    redraw, nxt = a.tick(10.0)
    assert redraw and abs(nxt - (10.0 + 1 / scene.FPS)) < 1e-6
    assert a.tick(10.01)[0] is False
    clock = QRectF(160, 170, 900, 740)
    assert all(not r.intersects(clock) for r in a.regions(QRectF(0, 0, 1920, 1080)))
