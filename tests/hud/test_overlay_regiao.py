"""O1.2: região de entrada do overlay (CA-O3) e o retrato sem fundo (``PartsPortrait.fundo``)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from wired.overlay import regiao_entrada


def circulo(w: int, h: int, cx: int, cy: int, r: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(200, 100, 100))
    p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
    p.end()
    return img


def regiao(rects) -> QRegion:
    reg = QRegion()
    for r in rects:
        reg = reg.united(r)
    return reg


def test_circulo_coberto_dilatado_sem_os_cantos():
    img = circulo(200, 230, 100, 115, 50)
    rects = regiao_entrada(img)
    assert 0 < len(rects) <= 64
    reg = regiao(rects)
    for y in range(0, 230, 3):  # todo pixel opaco do círculo entra
        for x in range(0, 200, 3):
            if QColor.fromRgba(img.pixel(x, y)).alpha() >= 76:
                assert reg.contains(QPoint(x, y))
    # dilatado: uma célula (8 px) além da borda ainda entra; bem longe, não
    assert reg.contains(QPoint(100 + 50 + 4, 115))
    assert reg.contains(QPoint(100, 115 - 50 - 4))
    for x, y in ((0, 0), (199, 0), (0, 229), (199, 229), (100, 20), (20, 115)):
        assert not reg.contains(QPoint(x, y))
    for r in rects:  # dentro da imagem
        assert img.rect().contains(r)


def test_vazia_e_nula():
    img = QImage(64, 64, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    assert regiao_entrada(img) == []
    assert regiao_entrada(QImage()) == []


def test_limiar_ignora_alfa_baixo():
    img = QImage(64, 64, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255, 40))  # véu quase transparente (~16%)
    assert regiao_entrada(img) == []
    assert regiao_entrada(img, limiar=30) == [img.rect()]


def test_muitos_pedacos_cabem_em_64():
    img = QImage(256, 256, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    for y in range(0, 256, 24):  # tabuleiro de pontos: em grade 8 viraria centenas de trechos
        for x in range(0, 256, 24):
            p.fillRect(x + (y // 24 % 2) * 12, y, 2, 2, QColor("white"))
    p.end()
    rects = regiao_entrada(img)
    assert 0 < len(rects) <= 64
    reg = regiao(rects)
    assert reg.contains(QPoint(0, 0))


def write_parts(folder: Path) -> Path:
    """Arte de teste em partes: camadas transparentes com um miolo opaco (cantos vazios)."""
    files = ["parts/head.png", "parts/body.png", "parts/back.png", "eyes/B1.png", "eyes/B2.png",
             "eyes/B3.png", "eyes/B14.png", "mouth/C1.png", "mouth/C2.png", "mouth/C3.png"]
    for rel in files:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        img = QImage(1024, 1024, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.fillRect(384, 384, 256, 256, QColor(200, 100, 100))
        p.end()
        assert img.save(str(folder / rel))
    (folder / "portrait.toml").write_text(
        'mode = "parts"\nrenderer = "cpu"\n[states]\n'
        'sleeping = { eyes = "B14", mouth = "C1", blink = ["B2", "B3"] }\n'
        'listening = { eyes = "B1", mouth = "C1", blink = ["B2", "B3"] }\n'
        '[speech]\nmouths = ["C1", "C2", "C3"]\n'
    )
    return folder


def pinta(fundo: bool, folder: Path) -> QImage:
    from wired.portrait import PartsAssets, PartsPortrait

    m = PartsPortrait(PartsAssets(folder), "sleeping", now=0.0, hour=lambda: 12)
    m.fundo = fundo
    img = QImage(120, 138, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    m.paint(p, QRectF(0, 0, 120, 138), "#b392f0", 1.0)
    p.end()
    return img


def test_retrato_sem_fundo_tem_cantos_transparentes(tmp_path, monkeypatch):
    monkeypatch.delenv("MAGI_PORTRAIT_RENDERER", raising=False)
    folder = write_parts(tmp_path)
    from wired.portrait import PartsAssets, PartsPortrait

    assert PartsPortrait(PartsAssets(folder)).fundo is True  # padrão: com fundo
    cantos = ((1, 1), (118, 1), (1, 136), (118, 136))
    sem = pinta(False, folder)
    assert all(QColor.fromRgba(sem.pixel(x, y)).alpha() == 0 for x, y in cantos)
    assert regiao_entrada(sem)  # a silhueta ainda aparece
    com = pinta(True, folder)  # o fundo (brilho/hexágonos) pinta muito além da silhueta

    def visiveis(img: QImage) -> int:
        return sum(QColor.fromRgba(img.pixel(x, y)).alpha() > 0
                   for y in range(0, img.height(), 2) for x in range(0, img.width(), 2))

    assert visiveis(com) > 3 * visiveis(sem)
