"""Legenda que se escreve conforme a Condessa fala (``speech_caption`` e o gamerhud)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from speech_caption import FALLBACK_CPS, FALLBACK_WAIT_S, LEAD_S, MAX_FPS, SpeechCaption, reveal_words
from wired.integration import WiredUI

from .test_wired_integration import make_hud  # noqa: F401 - fixture do HUD real

FRASE = "Uma aranha tem oito patas."


def test_revela_por_palavra_sem_cortar():
    assert reveal_words(FRASE, 0.0) == ""
    assert reveal_words(FRASE, 0.01) == "Uma"  # a palavra entra inteira quando começa
    assert reveal_words(FRASE, 0.5) == "Uma aranha tem"  # "oito" começa depois da metade
    assert reveal_words(FRASE, 0.99) == FRASE
    assert reveal_words(FRASE, 1.5) == FRASE


def falando(now: float = 0.0) -> SpeechCaption:
    sc = SpeechCaption()
    sc.on_state("speaking", now)
    return sc


def test_revela_proporcional_a_duracao_da_frase():
    sc = falando()
    sc.on_speech(FRASE, 2.0, 10.0)
    assert sc.text(10.0 - LEAD_S) == ""  # antes do som (já descontado o adiantamento)
    assert sc.text(11.0 - LEAD_S) == "Uma aranha tem"  # meio da frase
    assert sc.text(12.0) == FRASE  # fim
    assert sc.deadline(12.0) is None  # parada: nada a redesenhar


def test_frases_ditas_ficam_inteiras_e_a_atual_se_escreve():
    sc = falando()
    sc.on_speech("Primeira.", 1.0, 0.0)
    sc.on_speech("Segunda frase aqui.", 2.0, 1.0)
    assert sc.text(1.0 - LEAD_S) == "Primeira."
    assert sc.text(2.0) == "Primeira. Segunda frase"
    sc.on_subtitle("Primeira. Segunda frase aqui.")  # chega no meio (fala por frase): segue revelando
    assert sc.text(2.0) == "Primeira. Segunda frase"
    sc.on_state("followup", 2.1)  # acabou a fala: inteira
    assert sc.text(2.1) == "Primeira. Segunda frase aqui."


def test_interrompida_mostra_inteiro_e_avisos_atrasados_sao_ignorados():
    sc = falando()
    sc.on_subtitle("Oi, tudo bem?")
    sc.on_speech("Oi, tudo bem?", 3.0, 0.0)
    sc.on_state("listening", 0.5)
    assert sc.text(0.5) == "Oi, tudo bem?"
    sc.on_speech("Atrasada.", 1.0, 0.6)
    assert sc.text(0.7) == "Oi, tudo bem?" and sc.deadline(0.7) is None


def test_resposta_so_em_texto_aparece_inteira():
    sc = SpeechCaption()
    sc.on_subtitle("Abri o painel de CPU.")
    assert sc.text(0.0) == "Abri o painel de CPU." and sc.deadline(0.0) is None


def test_sem_aviso_de_frase_estima_15_caracteres_por_segundo():
    sc = SpeechCaption()
    sc.on_subtitle(FRASE)  # chega antes do speaking (fala no fim)
    sc.on_state("speaking", 0.0)
    assert sc.text(0.5) == ""  # sem boca ainda: espera a síntese
    assert sc.on_mouth(0.5) and not sc.on_mouth(0.6)  # só o primeiro nível conta
    t = 0.5 + 10 / FALLBACK_CPS - LEAD_S  # 10 caracteres depois do áudio começar
    assert sc.text(t) == "Uma aranha"
    assert sc.text(0.5 + len(FRASE) / FALLBACK_CPS) == FRASE
    sc.on_state("sleeping", 1.0)  # a fala acabou antes da estimativa: o resto aparece inteiro
    assert sc.text(1.0) == FRASE


def test_sem_boca_comeca_depois_da_espera():
    sc = SpeechCaption()
    sc.on_subtitle(FRASE)
    sc.on_state("speaking", 0.0)
    assert sc.text(FALLBACK_WAIT_S + 0.01) == "Uma"
    assert sc.deadline(0.0) == pytest.approx(FALLBACK_WAIT_S - LEAD_S)


def test_duracao_ausente_usa_a_velocidade_estimada():
    sc = falando()
    sc.on_speech(FRASE, None, 0.0)
    assert sc.text(len(FRASE) / FALLBACK_CPS) == FRASE
    assert sc.text(0.3) == "Uma aranha"


def test_ritmo_por_palavra_e_no_maximo_30_hz():
    sc = falando()
    sc.on_speech(FRASE, 2.6, 0.0)  # 26 caracteres → 0,1 s por caractere
    now = 0.0
    dl = sc.deadline(now)
    assert dl == pytest.approx(0.4 - LEAD_S, abs=1e-3)  # "aranha" começa no caractere 4
    sc2 = falando()
    sc2.on_speech("a b c d e f", 0.01, 0.0)
    assert sc2.deadline(-1.0) >= -1.0 + 1 / MAX_FPS


# -- HUD -------------------------------------------------------------------------------------

def test_wired_redesenha_so_a_legenda():
    ui = WiredUI()
    size = QSize(3440, 1440)
    rects = ui.caption_rects("Uma", "full", size)
    assert rects == ui.main.group_rects("talk", size) and rects
    assert ui.caption == ui.snap.caption == "Uma"
    assert ui.caption_rects("Uma", "full", size) == []  # nada mudou
    assert ui.caption_rects("Uma aranha", "idle", size) == ui.standby.group_rects("talk", size)


def test_gamerhud_escreve_a_legenda_conforme_a_fala(make_hud, monkeypatch):  # noqa: F811 - fixture
    import gamerhud

    clock = [100.0]
    monkeypatch.setattr(gamerhud.time, "monotonic", lambda: clock[0])
    w = make_hud()
    w.on_face_state("speaking")
    w.on_face_speech(FRASE, 2.0, 0)
    assert w.wired.snap.caption == "Uma" and w.caption_timer.isActive()
    clock[0] = 101.0
    w.caption_tick()
    assert w.wired.snap.caption == "Uma aranha tem"
    w.on_face_subtitle(FRASE, FRASE + " Mais detalhes.")
    assert w.wired.snap.caption == "Uma aranha tem"  # subtitle no meio não atropela a fala
    clock[0] = 102.5
    w.caption_tick()
    assert w.wired.snap.caption == FRASE and not w.caption_timer.isActive()
    w.on_face_state("sleeping")
    assert w.wired.snap.caption == FRASE
