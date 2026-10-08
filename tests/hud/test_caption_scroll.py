"""Legenda da Condessa: rolagem suave/leitura para trás (``caption_scroll``) e começo sem pisca."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize
from speech_caption import LEAD_S, PENDING_S, SpeechCaption
from wired.caption_scroll import ANIM_S, CaptionScroll

from .test_wired_integration import make_hud  # noqa: F401 - fixture do HUD real

FRASE = "Uma aranha tem oito patas."


# -- rolagem -----------------------------------------------------------------------------------

def test_acompanha_a_fala_subindo_suave():
    cs = CaptionScroll(2)
    cs.feed("", 0, 0.0)
    cs.feed("a", 1, 0.0)
    cs.feed("a b", 2, 0.1)
    assert cs.offset(0.1) == 0 and cs.follow
    cs.feed("a b c", 3, 1.0)  # linha nova: sobe uma linha animando
    assert 0 < cs.offset(1.0 + ANIM_S / 3) < 1 and cs.animating(1.05)
    assert cs.offset(1.0 + ANIM_S) == 1 and cs.deadline(1.0 + ANIM_S) is None
    assert cs.alpha(0, 2.0) == 0.0 or cs.alpha(0, 2.0) < 0.5  # a de cima sumindo
    assert cs.alpha(1, 2.0) < 1.0 and cs.alpha(2, 2.0) == 1.0  # a antiga esmaece, a atual inteira


def test_roda_volta_para_ler_pausa_e_retoma_no_fim():
    cs = CaptionScroll(2)
    cs.feed("", 0, 0.0)
    for i in range(1, 7):
        cs.feed("x" * i, i, float(i))
    assert cs.offset(10.0) == 4
    assert cs.wheel(3, 10.0) and not cs.follow  # voltou 3 linhas: acompanhamento pausado
    assert cs.offset(10.0 + ANIM_S) == 1
    cs.feed("x" * 7, 7, 11.0)  # a fala continua: a posição de leitura fica
    assert cs.offset(11.0 + ANIM_S) == 1 and not cs.follow
    assert cs.wheel(5, 12.0) and cs.offset(12.0 + ANIM_S) == 0  # volta até o começo
    assert not cs.wheel(1, 12.5)  # já no começo: nada
    cs.wheel(-10, 12.0)  # rolou até o fim: volta a acompanhar
    assert cs.follow and cs.offset(12.0 + ANIM_S) == cs.max_off == 5


def test_fala_nova_volta_ao_automatico():
    cs = CaptionScroll(2)
    cs.feed("aaaa", 4, 0.0)
    cs.wheel(1, 1.0)
    cs.feed("", 0, 2.0)  # começou outra fala (legenda vazia até a 1ª palavra)
    cs.feed("b", 1, 2.1)
    assert cs.follow and cs.offset(2.1) == 0


def test_texto_longo_inteiro_comeca_do_topo_e_fim_da_fala_nao_pula():
    cs = CaptionScroll(2)
    cs.feed("Resposta só em texto bem comprida", 5, 0.0)
    assert cs.offset(0.0) == 0 and not cs.follow  # lê do começo; roda para baixo
    cs2 = CaptionScroll(2)
    cs2.feed("", 0, 0.0)
    for i in range(1, 5):
        cs2.feed("frase dita " * i, i, float(i))
    cs2.feed("frase dita " * 4 + "fim.", 4, 5.0)  # legenda inteira no fim (mesma fala): segue no fim
    assert cs2.offset(5.0) == cs2.max_off == 2 and cs2.follow


# -- começo da fala sem pisca ------------------------------------------------------------------

def test_subtitle_antes_do_speaking_nao_aparece_inteiro():
    sc = SpeechCaption()
    sc.on_subtitle("Fala anterior.")
    sc.on_subtitle(FRASE, 10.0)  # o núcleo manda a legenda logo antes de entrar em speaking
    assert sc.text(10.0) == "Fala anterior."  # nada de pintar a fala nova inteira
    sc.on_state("speaking", 10.01)
    assert sc.text(10.02) == ""  # nasce vazia
    sc.on_speech(FRASE, 2.0, 10.5)
    assert sc.text(11.5 - LEAD_S) == "Uma aranha tem"


def test_resposta_so_em_texto_aparece_no_prazo_ou_no_proximo_estado():
    sc = SpeechCaption()
    sc.on_subtitle(FRASE, 0.0)
    assert sc.text(0.0) == "" and sc.deadline(0.0) is not None
    assert sc.text(PENDING_S) == FRASE
    sc2 = SpeechCaption()
    sc2.on_subtitle(FRASE, 0.0)
    sc2.on_state("listening", 0.1)  # continuação sem fala: inteira na hora
    assert sc2.text(0.1) == FRASE


def test_estimativa_nao_encolhe_quando_chega_o_primeiro_aviso():
    sc = SpeechCaption()
    sc.on_subtitle(FRASE, 0.0)
    sc.on_state("speaking", 0.0)
    sc.on_mouth(0.1)
    shown = sc.text(1.0)
    assert shown.startswith("Uma aranha")
    sc.on_speech(FRASE, 2.0, 1.0)  # aviso atrasado: a revelação recomeçaria do zero
    assert sc.text(1.05) == shown  # segura o que já estava
    assert sc.text(3.0) == FRASE


# -- HUD ---------------------------------------------------------------------------------------

def test_gamerhud_sequencia_real_sem_pisca_e_roda_na_legenda(make_hud, monkeypatch):  # noqa: F811
    import gamerhud
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QWheelEvent
    from wired.main_screen import TALK

    clock = [100.0]
    monkeypatch.setattr(gamerhud.time, "monotonic", lambda: clock[0])
    w = make_hud()
    w.view = "full"
    w.on_face_state("listening")
    w.on_face_state("thinking")
    seen = []
    w.on_face_subtitle(FRASE, FRASE)  # núcleo: subtitle, depois o estado de fala
    seen.append(w.wired.snap.caption)
    w.on_face_state("happy")  # resposta com expressão
    seen.append(w.wired.snap.caption)
    clock[0] = 100.3
    w.on_face_speech(FRASE, 2.0, 0)
    seen.append(w.wired.snap.caption)
    assert FRASE not in seen  # a frase inteira nunca aparece antes de ser dita
    assert w.speech_caption.speaking  # "happy" na resposta não encerra a legenda
    long = " ".join(["palavra"] * 60)
    clock[0] = 103.0
    w.on_face_speech(long, 1.0, 1)
    clock[0] = 105.0
    w.caption_tick()
    clock[0] = 110.0  # o terminal digita o texto longo (1 caractere por vez) até alcançar a fala
    w.caption_tick()
    main = w.wired.main
    assert main.cap.max_off > 0 and main.cap.follow
    s = main.scale(w.size())
    pos = QPointF(TALK.center().x() * s, TALK.center().y() * s)
    ev = QWheelEvent(pos, pos, QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev)
    assert ev.isAccepted() and not main.cap.follow
    fora = QPointF(10, 10)
    ev2 = QWheelEvent(fora, fora, QPoint(), QPoint(0, 120), Qt.MouseButton.NoButton,
                      Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev2)
    assert not ev2.isAccepted()
    assert QSize(w.size()).width() > 0
