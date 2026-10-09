"""Recorte da arte da Condessa (hud/tools/condessa_build.py) com imagens sintéticas: verde vazado,
orla recolorida, fio fino preservado, alinhamento das mechas e junta das pontas sem translucidez."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image

_PATH = Path(__file__).resolve().parents[2] / "hud" / "tools" / "condessa_build.py"
_spec = importlib.util.spec_from_file_location("condessa_build_t", _PATH)
cb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cb)

KEY = np.array([11, 243, 7], np.float32)  # o verde do fundo medido na A1
PINK = np.array([230, 80, 130], np.float32)  # cabelo
DARK = np.array([40, 12, 20], np.float32)  # contorno


def canvas(n: int = 40) -> np.ndarray:
    return np.ones((n, n, 3), np.float32) * KEY


def rgba(a: np.ndarray) -> np.ndarray:
    return np.asarray(cb.chroma(Image.fromarray(a.round().clip(0, 255).astype(np.uint8)))).astype(np.float32)


def olive(px: np.ndarray) -> bool:
    """Verde acima do menor entre vermelho e azul por mais de um arredondamento."""
    return bool(px[1] > min(px[0], px[2]) + 2)


def test_fundo_some_e_miolo_fica_intacto():
    a = canvas()
    a[10:30, 10:30] = PINK
    out = rgba(a)
    assert out[0, 0, 3] == 0
    assert out[20, 20, 3] == 255
    assert np.allclose(out[20, 20, :3], PINK, atol=1)


def test_orla_misturada_com_verde_vira_a_cor_de_dentro():
    a = canvas()
    a[10:30, 10:30] = PINK
    a[10:30, 30] = 0.5 * PINK + 0.5 * KEY  # pixel de borda meio a meio
    a[10:30, 31] = 0.25 * PINK + 0.75 * KEY
    out = rgba(a)
    for x in (30, 31):
        px = out[20, x]
        if px[3] > 0:
            assert not olive(px[:3]), px
            assert abs(px[0] - PINK[0]) < 40 and abs(px[2] - PINK[2]) < 40, px  # puxou o rosa de dentro


def test_contorno_escuro_misturado_nao_fica_oliva():
    a = canvas()
    a[10:30, 10:30] = PINK
    a[10:30, 29] = DARK  # linha do desenho na borda
    a[10:30, 30] = 0.6 * DARK + 0.4 * KEY  # contorno + verde = castanho-oliva no JPEG
    out = rgba(a)
    for x in (29, 30):
        if out[20, x, 3] > 0:
            assert not olive(out[20, x, :3]), out[20, x]


def test_fio_fino_solto_mantem_alfa_e_perde_o_verde():
    a = canvas()
    a[5:35, 20] = 0.7 * PINK + 0.3 * KEY  # fio de 1 px sem miolo opaco por perto
    out = rgba(a)
    assert out[20, 20, 3] > 100  # não foi comido
    assert not olive(out[20, 20, :3]), out[20, 20]


def test_pele_e_branco_opacos_nao_mudam():
    a = canvas()
    a[5:35, 5:20] = (250, 220, 200)  # pele
    a[5:35, 20:35] = (240, 240, 245)  # camisa
    out = rgba(a)
    assert np.allclose(out[20, 12, :3], (250, 220, 200), atol=1)
    assert np.allclose(out[20, 27, :3], (240, 240, 245), atol=1)


def test_box_e_media_da_janela():
    x = np.zeros((9, 9), np.float32)
    x[4, 4] = 9.0
    m = cb._box(x, 1)
    assert m[4, 4] == 1.0 and m[3, 3] == 1.0 and m[2, 2] == 0.0


def test_best_shift_acha_o_deslocamento():
    rng = np.random.default_rng(1)
    ref = np.zeros((cb.SIZE, cb.SIZE, 4), np.float32)
    ref[300:400, 300:400, :3] = rng.random((100, 100, 3))
    ref[300:400, 300:400, 3] = 1
    moved = cb._shift(ref, -3, 5)
    dx, dy, e0, e1 = cb.best_shift(moved, ref, reach=6)
    assert (dx, dy) == (3, -5)
    assert e1 < 0.5 < e0


def _tip_setup(tmp_path: Path) -> tuple[Path, Path]:
    """Pai (P2) opaco nas colunas 400–600; ponta (H5) da linha 500 para baixo nas mesmas colunas."""
    src, out = tmp_path / "src", tmp_path / "out"
    (out / "parts").mkdir(parents=True)
    src.mkdir()
    parent = np.zeros((cb.SIZE, cb.SIZE, 4), np.uint8)
    parent[100:800, 400:600] = (*PINK.astype(np.uint8), 255)
    Image.fromarray(parent, "RGBA").save(out / "parts" / "tail_l.png")
    tip = np.ones((cb.SIZE, cb.SIZE, 3), np.uint8) * KEY.astype(np.uint8)
    tip[500:800, 400:600] = PINK.astype(np.uint8)
    Image.fromarray(tip).save(src / "H5.png")
    return src, out


def test_junta_da_ponta_nao_fica_translucida(tmp_path):
    src, out = _tip_setup(tmp_path)
    cb.build_tips(src, out)
    pa = np.asarray(Image.open(out / "parts" / "tail_l.png"))[..., 3] / 255
    ta = np.asarray(Image.open(out / "parts" / "tail_l_tip.png"))[..., 3] / 255
    col = 500
    cover = 1 - (1 - pa[:, col]) * (1 - ta[:, col])  # cobertura das duas camadas juntas
    assert cover[480:700].min() > 0.98  # antes: ~0.75 no meio da junta
    assert pa[500 + 2 * cb.JOINT_FADE + 5, col] < 0.05  # o pai some depois que a ponta entrou


def test_cabelo_atras_do_corpo_nao_aparece_no_esmaecimento(tmp_path):
    """Na faixa do esmaecimento o corpo fica translúcido: o cabelo de trás que ele cobre não pode
    aparecer pela camisa (eram as pontas fantasma no busto); fora do corpo e acima da faixa, intacto."""
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    (out / "parts").mkdir(parents=True)
    body = np.ones((cb.SIZE, cb.SIZE, 3), np.uint8) * KEY.astype(np.uint8)
    body[600:, 300:700] = 235  # camisa branca até embaixo
    Image.fromarray(body).save(src / "P6.png")
    hair = np.zeros((cb.SIZE, cb.SIZE, 4), np.uint8)
    hair[100:, 200:800] = [*PINK.astype(np.uint8), 255]
    Image.fromarray(hair, "RGBA").save(out / "parts" / "back.png")
    cb.hide_behind_body(src, out, Image.fromarray(body))
    a = np.asarray(Image.open(out / "parts" / "back.png"))[..., 3] / 255
    low = int(cb.SIZE * (1 - cb.FADE_BOTTOM)) + 20
    assert a[low:, 330:670].max() < 0.02  # atrás da camisa, na faixa: some
    assert a[low:, 210:280].min() > 0.98  # fora do corpo: fica
    assert a[650:800, 330:670].min() > 0.98  # acima da faixa: o corpo é opaco, nada muda


# --- R3.1: arte nova (D1–D9, E3, B16/B17, P9–P13) --------------------------------------------------

NOVOS = ("D1", "D2", "D6", "D7", "D8", "D9", "E3", "B16", "B17", "P9", "P10", "P11", "P12", "P13")


def _busto() -> np.ndarray:
    a = np.ones((cb.SIZE, cb.SIZE, 3), np.float32) * KEY
    a[200:900, 250:780] = PINK  # busto liso
    return a


def _save(folder: Path, ident: str, a: np.ndarray) -> None:
    Image.fromarray(a.round().clip(0, 255).astype(np.uint8)).save(folder / f"{ident}.png")


def _arte_nova(tmp_path: Path) -> tuple[Path, Path]:
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    _save(src, "A1", _busto())
    for ident in NOVOS:
        if ident.startswith("D"):  # só o detalhe no verde
            a = np.ones((cb.SIZE, cb.SIZE, 3), np.float32) * KEY
            a[100:160, 800:860] = DARK
        else:  # busto inteiro com a mudança (inpainting)
            a = _busto()
            a[600:700, 300:700] = DARK
        _save(src, ident, a)
    return src, out


def test_build_gera_os_ids_novos(tmp_path):
    src, out = _arte_nova(tmp_path)
    report = cb.build(src, out)
    for ident in ("D1", "D2", "D6", "D7", "D8", "D9", "E3", "P9", "P10", "P11", "P12", "P13"):
        assert (out / "extra" / f"{ident}.png").is_file(), ident
        assert f"falta {ident} (opcional)" not in report
    for ident in ("B16", "B17"):
        assert (out / "eyes" / f"{ident}.png").is_file()
    # detalhe solto: recorte pelo verde (o fundo some, o detalhe fica)
    d1 = np.asarray(Image.open(out / "extra" / "D1.png"))
    assert d1[130, 830, 3] == 255 and d1[500, 500, 3] == 0
    # busto inteiro: só a diferença da A1 (o resto do busto não vira camada)
    p13 = np.asarray(Image.open(out / "extra" / "P13.png"))
    assert p13[650, 500, 3] > 200 and p13[300, 500, 3] == 0


def test_build_sem_os_novos_nao_quebra_e_apaga_o_antigo(tmp_path):
    src, out = _arte_nova(tmp_path)
    cb.build(src, out)
    for ident in NOVOS:
        (src / f"{ident}.png").unlink()
    report = cb.build(src, out)
    for ident in cb.EXTRAS:
        assert f"falta {ident} (opcional)" in report
        assert not (out / "extra" / f"{ident}.png").exists()  # retrato volta ao efeito em código


def test_i20_entra_em_ativas_com_p13(tmp_path, monkeypatch):
    from hud.wired.reacoes import catalogo

    assert "bracos_cruzados" not in catalogo.ativas(lambda rel: False)
    assert "bracos_cruzados" in catalogo.ativas(lambda rel: rel == "extra/P13.png")
    assert catalogo.ativas(lambda rel: True) - catalogo.ativas(lambda rel: False) == {"bracos_cruzados"}
    monkeypatch.setenv("MAGI_PORTRAIT_DIR", str(tmp_path))
    assert "bracos_cruzados" not in catalogo.ativas()
    (tmp_path / "extra").mkdir()
    (tmp_path / "extra" / "P13.png").write_bytes(b"png")
    assert "bracos_cruzados" in catalogo.ativas()


def test_efeito_usa_o_png_quando_existe():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from hud.wired.portrait import PartsPortrait

    pm = MagicMock()
    from PySide6.QtCore import QRect

    pm.rect.return_value = QRect(0, 0, 1024, 1024)
    for tem, desenha in ((True, True), (False, False)):
        assets = SimpleNamespace(pix=lambda rel, tem=tem: pm if tem and rel == "extra/D8.png" else None)
        me = SimpleNamespace(assets=assets, reaction_until=10.0)
        p = MagicMock()
        PartsPortrait._reaction_effect(me, p, 1.0, "vein", 0.0, 0.0)
        assert p.drawPixmap.called is desenha
        assert p.drawArc.called is not desenha  # sem o PNG, a veia em código


def test_recorte_de_braco_ignora_fio_de_cabelo_e_tapa_buraco():
    """Braço/fone pela diferença: fio fino e lasca cor de cabelo saem; buraco pequeno é tapado."""
    size = cb.SIZE
    mask = np.zeros((size, size), np.float32)
    mask[400:800, 600:760] = 1.0          # braço: mancha grande
    mask[560:600, 660:700] = 0.0          # buraco pequeno dentro dele (pele sobre pele)
    mask[100:110, 50:900] = 1.0           # fio de cabelo: fino e comprido
    rgb = np.zeros((size, size, 3), np.uint8)
    rgb[...] = (240, 200, 180)            # pele
    rgb[200:330, 100:230] = (225, 60, 110)  # lasca grande com cor de cabelo
    mask[200:330, 100:230] = 1.0
    keep = cb.only_blobs(mask, Image.fromarray(rgb))
    assert keep[600, 680] > 0.9 and keep[580, 680] > 0.9   # braço e o buraco tapado
    assert keep[105, 300] < 0.1                            # fio sumiu
    assert keep[265, 165] < 0.1                            # lasca cor de cabelo sumiu
    hair = cb.hair_colored(Image.fromarray(rgb))
    assert hair[265, 165] and not hair[600, 680]
