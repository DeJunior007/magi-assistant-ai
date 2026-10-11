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


# -- espera viva: rótulo da ferramenta e lotes (spec §2.4) -----------------------------------


def test_ferramenta_vira_rotulo_do_thinking():
    from wired.main_screen import Snapshot, chip_label

    tp = TurnPhase()
    seq(tp, [(0.0, "listening"), (1.0, "thinking")])
    assert tp.chip_tool(1.0) is None
    tp.on_think("tool", "search", 2.0)
    assert (tp.chip(2.0), tp.chip_tool(2.0)) == ("thinking", "search")
    labels = {}
    for tool in ("search", "news_query", "steam_game", "spotify_play", "self_info", None):
        lbl, fg, lit = chip_label(Snapshot(chip="thinking", chip_tool=tool))
        labels[tool] = lbl
        assert (fg, lit) == chip_label(Snapshot(chip="thinking"))[1:]  # mesma cor/aceso
    assert labels["search"] == labels["news_query"] == "Searching · 検索中"
    assert labels["steam_game"] == "Checking · 確認中"
    assert labels["spotify_play"] == "Working · 作業中"
    assert labels["self_info"] == labels[None] == "Thinking · 思考中"
    # a ferramenta só vale no thinking: falando, o rótulo é o de sempre
    assert chip_label(Snapshot(chip="speaking", chip_tool="search"))[0].startswith("Speaking")
    # a fala começa: a ferramenta sai (thinking da síntese sem rótulo de ferramenta)
    tp.on_state("speaking", 5.0)
    assert (tp.chip(5.0), tp.chip_tool(5.0)) == ("thinking", None)


def test_ferramenta_fora_do_thinking_e_ignorada():
    tp = TurnPhase()
    tp.on_state("listening", 0.0)
    tp.on_think("tool", "search", 1.0)
    assert (tp.chip(1.0), tp.chip_tool(1.0)) == ("listening", None)


def test_lote_volta_a_thinking_ate_a_boca_mexer():
    tp = TurnPhase()
    chips = seq(tp, [(0.0, "thinking"), (1.0, "speaking"), (1.2, "mouth")])
    assert chips[-1] == "speaking"
    tp.on_think("lote", None, 3.0)
    assert tp.chip(3.0) == "thinking"
    assert tp.chip(3.0 + 2 * AUDIO_WAIT_S) == "thinking"  # sem som, segue pensando
    assert tp.deadline(3.0 + 2 * AUDIO_WAIT_S) is None
    tp.on_think("tool", "news_query", 4.0)  # ferramenta no meio dos lotes ganha rótulo
    assert tp.chip_tool(4.0) == "news_query"
    tp.on_mouth(0.5, 6.0)
    assert (tp.chip(6.0), tp.chip_tool(6.0)) == ("speaking", None)


def test_lote_por_speech_e_tempo_minimo():
    tp = TurnPhase()
    seq(tp, [(0.0, "thinking"), (1.0, "speaking"), (1.1, "speech")])
    tp.on_think("lote", None, 1.2)  # speaking mostrado há pouco: segura o tempo mínimo
    assert tp.chip(1.2) == "speaking"
    assert tp.deadline(1.2) == 1.1 + MIN_DWELL_S
    assert tp.chip(1.1 + MIN_DWELL_S) == "thinking"
    tp.on_speech(2.0)
    assert tp.chip(2.0) == "speaking"


def test_troca_de_rotulo_sem_piscar():
    tp = TurnPhase()
    tp.on_state("thinking", 0.0)
    tp.chip(0.0)
    tp.on_think("tool", "search", 1.0)
    assert tp.chip_tool(1.0) == "search"
    tp.on_think("tool", "rgb", 1.1)  # rajada de ferramentas: segura o rótulo mostrado
    assert tp.chip_tool(1.1) == "search"
    assert tp.deadline(1.1) == 1.0 + MIN_DWELL_S
    assert tp.chip_tool(1.0 + MIN_DWELL_S) == "rgb"
    tp.on_think("wait", None, 2.0)  # wait não mexe no chip
    assert (tp.chip(2.0), tp.chip_tool(2.0)) == ("thinking", "rgb")
