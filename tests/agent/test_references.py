from __future__ import annotations

from magi.agent.references import clean, forced, spoken_sentence


def test_corta_as_caudas_reais():
    assert clean("Oito, Pedro. Se tiver nove, aí é bug de NERV.") == "Oito, Pedro."
    assert clean("Feito, Pedro. Vermelho no clima de NERV.") == "Feito, Pedro."
    assert clean("Feito, vermelho no clima de NERV.") == "Feito."
    assert clean("Faltam 34 conquistas. Platinar sem sofrimento é lenda nível EVA dar errado.") == (
        "Faltam 34 conquistas.")


def test_falando_de_evangelion_libera():
    assert clean("O Shinji entra no EVA no episódio 1.", "quando o shinji entra no eva?") == (
        "O Shinji entra no EVA no episódio 1.")
    assert not forced("A Ayanami achou isso.", "")  # o agente de notícias não é termo proibido


def test_meio_da_frase_passa_e_so_loga():
    text = "O EVA do seu PC está ótimo hoje."
    assert clean(text) == text


def test_streaming_frase_a_frase():
    assert spoken_sentence("Se tiver nove, aí é bug de NERV.", 1) is None
    assert spoken_sentence("Feito, vermelho no clima de NERV.", 0) == "Feito."
    assert spoken_sentence("Oito patas.", 1) == "Oito patas."
