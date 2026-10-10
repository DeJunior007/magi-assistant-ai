"""V0.4: rosto de repouso, fone persistente, crossfade e o medidor dela (spec §4, §10; CA-V5, CA-V8)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage, QPainter
from wired.main_screen import MainScreen, Snapshot, causas_linhas, momento_nome
from wired.mascot import BLINK_LEN
from wired.portrait import XFADE, PartsAssets, PartsPortrait
from wired.reacoes import estado
from wired.reacoes.repouso import Postura, fone_alvo, rosto
from wired.reacoes.vida import Faixa, Filtro, Fone, Momento, Repouso
from wired.standby_screen import StandbyScreen

CAB, PES = Postura(Fone.CABECA), Postura(Fone.PESCOCO)


# ── rosto (acordo §2) ────────────────────────────────────────────────────────
@pytest.mark.parametrize(("faixa", "olho", "boca", "fundo"), [
    (Faixa.RADIANTE, "B1", "C5", "happy"), (Faixa.CONTENTE, "B1", "C10", "calm"),
    (Faixa.NEUTRA, "B1", "C1", "calm"), (Faixa.EMBURRADA, "B7", "C9", "calm"),
])
def test_tabela_de_faixas(faixa, olho, boca, fundo):
    r = rosto(Momento.A_TOA, faixa, set(), PES, {})
    assert (r.eyes, r.mouth, r.mood, r.fone, r.sway) == (olho, boca, fundo, Fone.PESCOCO, False)


def test_madrugada_energia_e_sad():
    r = rosto(Momento.A_TOA, Faixa.CONTENTE, {Filtro.MADRUGADA}, PES, {"energia": 0.2})
    assert (r.eyes, r.mouth) == ("B2", "C5")  # C10→C5; energia < 0,3 → B2
    assert rosto(Momento.A_TOA, Faixa.EMBURRADA, {Filtro.MADRUGADA}, PES, {"animo": -0.6}).mood == "sad"
    assert rosto(Momento.A_TOA, Faixa.EMBURRADA, set(), PES, {"animo": -0.9}).mood == "calm"


def test_musica_com_fone_sorri_pela_faixa_inteira():
    assert rosto(Momento.CURTINDO, Faixa.EMBURRADA, set(), CAB, {"musica_nota": 1}).eyes == "B2"
    assert rosto(Momento.CURTINDO, Faixa.NEUTRA, set(), CAB, {"musica_nota": 2}).eyes == "B4"
    assert rosto(Momento.CURTINDO, Faixa.NEUTRA, set(), PES, {"musica_nota": 2}).eyes == "B1"  # sem fone


def test_faixa_de_agua_fora_de_conversa_e_jogo():
    ctx = {"musica_nota": 0, "faixa_agua": True}
    r = rosto(Momento.OUVINDO, Faixa.NEUTRA, set(), CAB, ctx)
    assert (r.eyes, r.sway) == ("B3", True)
    assert not rosto(Momento.JOGANDO, Faixa.NEUTRA, set(), CAB, ctx).sway
    assert not rosto(Momento.OUVINDO, Faixa.NEUTRA, set(), CAB, {**ctx, "musica_nota": -1}).sway


def test_pedro_mal_episodio_alerta_e_p10():
    r = rosto(Momento.CURTINDO, Faixa.RADIANTE, {Filtro.PEDRO_MAL}, CAB, {"musica_nota": 2})
    assert (r.eyes, r.mouth, r.mood) == ("B1", "C1", "calm") and "olhando_pedro" in r.efeitos
    r = rosto(Momento.JOGANDO, Faixa.NEUTRA, set(), PES, {"episodio": True})
    assert r.mood == "stress" and "sweat" in r.efeitos
    assert rosto(Momento.ALERTA, Faixa.RADIANTE, set(), PES, {}).mood == "stress"
    assert "braco:P10" not in rosto(Momento.TRABALHANDO_JUNTO, Faixa.NEUTRA, set(), PES,
                                    {"momento_ha_s": 60}).efeitos
    assert "braco:P10" in rosto(Momento.TRABALHANDO_JUNTO, Faixa.NEUTRA, set(), PES,
                                {"momento_ha_s": 121}).efeitos
    assert "braco:P10" in rosto(Momento.ESTUDANDO, Faixa.NEUTRA, set(), PES, {}).efeitos


def test_fone_ca_v5():
    assert fone_alvo(Momento.A_TOA, {}) == Fone.PESCOCO  # sem música, nunca E2
    assert fone_alvo(Momento.OUVINDO, {"musica_nota": 0}) == Fone.CABECA
    assert fone_alvo(Momento.CONVERSA, {"musica_nota": 2}) == Fone.PESCOCO
    assert fone_alvo(Momento.ATURANDO, {"musica_nota": -1, "faixa_ha_s": 3}) == Fone.CABECA
    assert fone_alvo(Momento.ATURANDO, {"musica_nota": -1, "faixa_ha_s": 8}) == Fone.PESCOCO
    assert fone_alvo(Momento.ATURANDO, {"musica_nota": -2, "faixa_ha_s": 0}) == Fone.PESCOCO


# ── retrato (design §3) ──────────────────────────────────────────────────────
def _parts(folder: Path) -> PartsPortrait:
    for rel in ["parts/head.png", "parts/body.png", "eyes/B1.png", "eyes/B2.png", "eyes/B3.png",
                "eyes/B7.png", "eyes/B14.png", "mouth/C1.png", "mouth/C5.png", "mouth/C9.png",
                "extra/E3.png", "extra/fone.png"]:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        img.fill(QColor(200, 100, 100))
        assert img.save(str(folder / rel))
    (folder / "portrait.toml").write_text(
        'mode = "parts"\n[states]\nlistening = { eyes = "B1", mouth = "C1", blink = ["B2", "B3"] }\n'
        'sleeping = { eyes = "B14", mouth = "C1", blink = ["B15", "B15"] }\n')
    m = PartsPortrait(PartsAssets(folder), "sleeping", now=0.0)
    m.hour = lambda: 14  # parada de dia
    return m


def _rep(**kw) -> Repouso:
    return Repouso(**{"eyes": "B1", "mouth": "C1", "fone": Fone.PESCOCO, "mood": "calm", **kw})


def test_sem_repouso_fica_como_antes(tmp_path):
    m = _parts(tmp_path)
    assert m.rest is None and m.mouth_id(1.0) == "C1" and not m.blinking(1.0)


def test_set_rest_e_troca_dentro_da_piscada(tmp_path):
    m = _parts(tmp_path)
    m.set_rest(_rep(eyes="B7", mouth="C9"))  # o primeiro entra já
    assert (m.eyes_id(0.5), m.mouth_id(0.5), m.mood(0.5)) == ("B7", "C9", "calm")
    m.set_rest(_rep(mouth="C5", mood="happy"))
    assert m.mouth_id(0.5) == "C9"  # espera a piscada
    t = m._blink_at
    assert t <= 0.3 + 1e-9
    m.tick(t + BLINK_LEN / 2)
    assert m.blinking(t + BLINK_LEN / 2) and m.mouth_id(t + BLINK_LEN / 2) == "C5"
    assert m.mood(t + 1.0) == "happy"
    # corpo vivo: segue piscando a cada 3–6 s
    blinks = 0
    for k in range(1, 1200):
        now = t + k / 60
        m.tick(now)
        blinks += m.blinking(now) and not m.blinking(now - 1 / 60)
    assert 2 <= blinks <= 7


def test_agua_abre_os_olhos_de_vez_em_quando(tmp_path):
    m = _parts(tmp_path)
    m.set_rest(_rep(eyes="B3", sway=True))
    m._blink_at = 1e9  # sem piscar no meio
    seen = set()
    for k in range(0, 40 * 30):
        now = k / 30
        m.tick(now)
        seen.add(m.eyes_id(now))
    assert seen == {"B2", "B3"}


def test_crossfade_120ms(tmp_path):
    m = _parts(tmp_path)
    assert m._fade("mouth", "C1", 0.0) == (None, 1.0)
    assert m._fade("mouth", "C9", 1.0) == ("C1", 0.0)
    prev, k = m._fade("mouth", "C9", 1.0 + XFADE / 2)
    assert prev == "C1" and k == pytest.approx(0.5)
    assert m._fade("mouth", "C9", 1.0 + XFADE) == (None, 1.0)
    assert XFADE == pytest.approx(0.12)


def test_fone_persistente_e_reacao_por_cima(tmp_path):
    m = _parts(tmp_path)
    img = QImage(64, 128, QImage.Format.Format_ARGB32)
    for fone in (Fone.CABECA, Fone.PESCOCO):
        m.set_rest(_rep(fone=fone))
        p = QPainter(img)
        m.paint(p, img.rect().toRectF(), "#b392f0", 1.0)  # sem erro com E2 (fone.png) e E3
        p.end()
    assert m.rest.fone == Fone.PESCOCO


# ── medidor (acordo §6, CA-V8) ───────────────────────────────────────────────
SIZE = QSize(1920, 1080)
NOW = datetime(2026, 10, 10, 15, 0, 0)


def _snap(**kw) -> Snapshot:
    base = {"mood_dela": 0.4, "mood_dela_cor": estado.COR_FAIXA[Faixa.CONTENTE],
            "momento": "trabalhando_junto",
            "causas": (("commit", 0.05, 30.0), ("faxina", 0.03, 400.0), ("Ado", 0.30, 7300.0))}
    return Snapshot(**{**base, **kw})


def _paint(sc, snap, region=None):
    img = QImage(SIZE, QImage.Format.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    sc.paint(p, SIZE, snap, NOW, mono=0.0, region=region)
    p.end()


def test_cor_da_faixa_e_a_do_fundo():
    assert estado.COR_FAIXA[Faixa.RADIANTE] == "#f2a7c3"  # happy
    assert estado.COR_FAIXA[Faixa.EMBURRADA] == estado.COR_FAIXA[Faixa.NEUTRA]  # calm = acento


def test_causas_e_nome_do_momento():
    assert causas_linhas(_snap().causas) == ["+0,30 Ado · há 2 h", "+0,03 faxina · há 6 min",
                                             "+0,05 commit · agora"]
    assert momento_nome("a_toa") == "à toa" and momento_nome("jogando") == "pilotando"


@pytest.mark.parametrize("cls", [MainScreen, StandbyScreen])
def test_medidor_segue_o_animo_e_hover_mostra_causas(cls):
    sc = cls()
    snap = _snap()
    _paint(sc, snap)
    assert not sc.dirty_regions(snap, NOW, SIZE)
    mood = sc.groups()["mood"][0]
    assert set(sc.dirty_regions(_snap(mood_dela=-0.5), NOW, SIZE)) >= set(sc.group_rects("mood", SIZE))
    assert sc.dirty_regions(_snap(momento="tedio"), NOW, SIZE)
    # hover: a caixa das causas aparece por cima e some ao sair
    s = SIZE.width() / 1920
    assert sc.hover_test(QPoint(round(mood.center().x() * s), round(mood.center().y() * s)), SIZE) == "mood"
    assert sc.set_hover("mood")
    tip = sc.group_rects("mood_tip", SIZE)
    assert tip and set(sc.dirty_regions(snap, NOW, SIZE)) >= set(tip)
    for r in sc.dirty_regions(snap, NOW, SIZE):
        _paint(sc, snap, r)
    assert not sc.dirty_regions(snap, NOW, SIZE)
    assert sc.set_hover(None) and sc.dirty_regions(snap, NOW, SIZE)
    # sem o dado dela, o termômetro antigo continua
    _paint(sc, Snapshot(mood=3))
