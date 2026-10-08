"""Konsole expandido troca de lugar com o cam 01: a Condessa, o LOAD HISTORY e o UNIT SPEC nunca
são cobertos; a câmera (escalada, sem cortar) vai para o slot do card KONSOLE."""

from datetime import datetime

from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QImage, QPainter
from wired import konsole_view as kv
from wired import main_screen as ms
from wired.main_screen import MainScreen, Snapshot, dev_rect

SIZE = QSize(2560, 1440)
S = 2560 / 1920
NOW = datetime(2026, 10, 3, 19, 11, 42)


def render(sc, snap, region=None, img=None):
    if img is None:
        img = QImage(SIZE, QImage.Format.Format_RGB32)
        img.fill(0)
    p = QPainter(img)
    sc.paint(p, SIZE, snap, NOW, mono=0.0, region=region)
    p.end()
    return img


def swapped(on=True):
    sc = MainScreen()
    sc.kon_swap = on
    return sc


def test_expandido_e_a_caixa_do_cam01():
    assert kv.EXPANDED_RECT == ms.CAM == ms.SCENE
    assert kv.CARD_RECT == ms.KONSOLE == ms.CAM_SLOT
    for card in (ms.CONDESSA, ms.HIST, ms.SPEC):
        assert not kv.EXPANDED_RECT.intersects(card)


def test_camera_cabe_inteira_no_slot():
    r = ms.CAM_SWAPPED
    assert ms.CAM_SLOT.contains(r)
    assert abs(r.width() / r.height() - ms.SCENE.width() / ms.SCENE.height()) < 1e-6   # sem cortar
    assert abs(r.width() - ms.CAM_SLOT.width()) < 0.01   # ocupa a largura toda do slot


def test_grupos_trocados():
    sc = swapped()
    g = sc.groups()
    assert "konsole" not in g and "konsole_status" not in g
    for name in ("scene",):
        assert g[name] and all(ms.CAM_SLOT.contains(r) for r in g[name])
    rec = g["clock"][1]
    assert ms.CAM_SWAPPED.contains(rec)
    assert all(ms.CAM_SLOT.contains(r) for r in sc.scene_rects())
    assert "konsole" in swapped(False).groups()


def test_camera_desenhada_no_slot_do_konsole():
    snap = Snapshot()
    a = render(swapped(False), snap)
    b = render(swapped(True), snap)
    slot = dev_rect(ms.CAM_SWAPPED, S).adjusted(4, 4, -4, -4)
    assert a.copy(slot) != b.copy(slot)
    # o cenário miniatura é o mesmo do cam 01: cores do slot trocado ≈ cores do cam 01 original
    cam = dev_rect(ms.SCENE, S)
    k = ms.CAM_SWAP_K
    for fx, fy in ((0.3, 0.3), (0.5, 0.5), (0.7, 0.8), (0.2, 0.9)):
        pa = a.pixelColor(round(cam.left() + fx * cam.width()), round(cam.top() + fy * cam.height()))
        q = ms.CAM_SWAPPED
        pb = b.pixelColor(round((q.left() + fx * ms.SCENE.width() * k) * S),
                          round((q.top() + fy * ms.SCENE.height() * k) * S))
        assert abs(pa.lightness() - pb.lightness()) < 40
    # a caixa do cam 01 fica livre para o Konsole (o painel não desenha a câmera lá)
    inner = dev_rect(ms.SCENE, S).adjusted(40, 40, -40, -40)
    seen = {b.pixel(x, y) & 0xFFFFFF for y in range(inner.top(), inner.bottom(), 17)
            for x in range(inner.left(), inner.right(), 17)}
    assert len(seen) < 12   # só fundo + scanlines/vinheta


def test_condessa_load_history_e_unit_spec_intocados():
    snap = Snapshot()
    a = render(swapped(False), snap)
    b = render(swapped(True), snap)
    for card in (ms.CONDESSA, ms.HIST, ms.SPEC):
        r = dev_rect(card, S)
        assert a.copy(r) == b.copy(r)


def test_troca_repinta_so_as_duas_caixas_igual_a_completa():
    snap = Snapshot()
    sc = swapped(False)
    img = render(sc, snap)
    assert sc.dirty_regions(snap, NOW, SIZE) == []
    for on in (True, False, True):
        sc.kon_swap = on
        assert sc.dirty_regions(snap, NOW, SIZE) == []   # a troca não refaz a tela inteira
        for r in (dev_rect(kv.EXPANDED_RECT, S), dev_rect(kv.CARD_RECT, S)):
            render(sc, snap, region=r, img=img)
        full = render(swapped(on), snap)
        assert img == full
    # parcial dentro do slot trocado (tick do cenário) também bate com a completa
    reg = QRect(dev_rect(ms.CAM_SLOT, S).left(), 900, 400, 300)
    render(sc, snap, region=reg, img=img)
    assert img.copy(reg) == render(swapped(True), snap).copy(reg)


def test_cliques_trocados():
    sc = swapped()
    s = SIZE.width() / 1920
    c = ms.CAM_SWAPPED.center()
    assert sc.hit_test(QPointF(c.x() * s, c.y() * s), SIZE) == "cam"
    assert swapped(False).hit_test(QPointF(c.x() * s, c.y() * s), SIZE) == "konsole"
    v = kv.KonsoleView()
    assert v.hit_expanded(c) == "cam"
    assert v.hit_expanded(kv.EXPANDED_RECT.center()) == "term"
    assert v.hit_expanded(ms.CONDESSA.center()) is None
