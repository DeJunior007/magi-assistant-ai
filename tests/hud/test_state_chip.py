"""Chip de estado da Condessa: fase do turno estável (``turn_phase``) e o chip no gamerhud."""

from __future__ import annotations

from turn_phase import AUDIO_WAIT_S, MIN_DWELL_S, TurnPhase

from .test_wired_integration import make_hud  # noqa: F401 - fixture do HUD real


def seq(tp: TurnPhase, events: list[tuple[float, str]]) -> list[str]:
    out = []
    for t, ev in events:
        if ev == "mouth":
            tp.on_mouth(0.5, t)
        elif ev == "speech":
            tp.on_speech(t)
        else:
            tp.on_state(ev, t)
        out.append(tp.chip(t))
    return out


def test_turno_comum_listening_thinking_speaking_standby():
    tp = TurnPhase()
    chips = seq(tp, [(0.0, "listening"), (2.0, "thinking"), (4.0, "speaking"), (4.3, "mouth"),
                     (8.0, "sleeping")])
    assert chips == ["listening", "thinking", "thinking", "speaking", "idle"]


def test_falando_so_quando_o_audio_comeca_ou_depois_da_espera():
    tp = TurnPhase()
    seq(tp, [(0.0, "listening"), (1.0, "thinking"), (2.0, "speaking")])
    assert tp.chip(2.5) == "thinking"  # sintetizando a voz: ainda pensando
    assert tp.deadline(2.5) == 2.0 + AUDIO_WAIT_S
    assert tp.chip(2.0 + AUDIO_WAIT_S) == "speaking"  # sem boca nem aviso: assume que falou


def test_expressao_na_resposta_e_fala_e_nao_standby():
    tp = TurnPhase()
    chips = seq(tp, [(0.0, "listening"), (1.0, "thinking"), (2.0, "happy"), (2.1, "speech"),
                     (3.0, "mouth"), (3.2, "confused")])  # expressão no meio da fala (1.24)
    assert chips[2:] == ["thinking", "speaking", "speaking", "speaking"]
    assert tp.speaking


def test_alert_depois_da_fala_e_confirmacao_ouvindo():
    tp = TurnPhase()
    seq(tp, [(0.0, "listening"), (1.0, "thinking"), (2.0, "speaking"), (2.2, "mouth")])
    tp.on_state("alert", 5.0)  # boca parada há tempo: confirming
    assert tp.chip(5.0) == "listening" and not tp.speaking
    tp2 = TurnPhase()
    seq(tp2, [(0.0, "thinking"), (1.0, "speaking"), (1.2, "mouth")])
    tp2.on_state("alert", 1.3)  # boca mexendo: expressão da fala
    assert tp2.chip(1.6) == "speaking"


def test_dispensada_e_followup():
    tp = TurnPhase()
    assert seq(tp, [(0.0, "listening"), (3.0, "happy")]) == ["listening", "idle"]
    tp2 = TurnPhase()
    chips = seq(tp2, [(0.0, "listening"), (1.0, "thinking"), (2.0, "speaking"), (2.1, "mouth"),
                      (5.0, "listening"), (9.0, "sleeping")])  # continuação e depois dorme
    assert chips[-2:] == ["listening", "idle"]


def test_tempo_minimo_sem_piscar():
    tp = TurnPhase()
    tp.on_state("listening", 0.0)
    tp.on_state("thinking", 0.05)  # trocas em rajada: o chip segura cada fase um pouco
    assert tp.chip(0.05) == "listening"
    assert tp.deadline(0.05) == MIN_DWELL_S
    assert tp.chip(MIN_DWELL_S) == "thinking"
    tp.on_state("sleeping", MIN_DWELL_S + 0.01)
    assert tp.chip(MIN_DWELL_S + 0.01) == "thinking"
    assert tp.chip(2 * MIN_DWELL_S + 0.01) == "idle"


def test_aviso_proativo_falado_com_expressao():
    tp = TurnPhase()
    tp.on_state("happy", 0.0)  # announce(expression=happy) saindo de sleeping
    assert tp.speaking and tp.chip(0.0) == "speaking"


def test_gamerhud_chip_segue_a_fase(make_hud, monkeypatch):  # noqa: F811 - fixture
    import gamerhud
    from wired.main_screen import chip_label

    clock = [100.0]
    monkeypatch.setattr(gamerhud.time, "monotonic", lambda: clock[0])
    w = make_hud()
    w.on_face_state("listening")
    assert chip_label(w.wired.snap)[0].startswith("Listening")
    clock[0] = 102.0
    w.on_face_state("thinking")
    clock[0] = 104.0
    w.on_face_state("happy")  # resposta falada com expressão
    assert chip_label(w.wired.snap)[0].startswith("Thinking")  # voz ainda sintetizando
    clock[0] = 104.2
    w.on_face_mouth(0.6)
    w.caption_tick()
    assert chip_label(w.wired.snap)[0].startswith("Speaking")
    clock[0] = 108.0
    w.on_face_state("sleeping")
    assert chip_label(w.wired.snap)[0].startswith("Standby")
