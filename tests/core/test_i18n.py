"""Idioma da fala (``[speech] language``, ``magi.core.i18n``): tabela en-GB e os dois funis."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from types import SimpleNamespace

import pytest

from magi.agent.prompt import load_persona
from magi.agent.tools.news import _GREETING
from magi.common.contracts import ActionResult, CardLevel, CardMsg, SubtitleMsg, TurnState
from magi.core import i18n
from magi.core.proactive.sink import Outcome, ProactiveSink
from magi.core.turn import TurnDeps, TurnMachine, TurnPipeline


@pytest.fixture
def en() -> Iterator[None]:
    i18n.configure("en-gb")
    yield
    i18n.configure("pt-br")


@pytest.mark.usefixtures("en")
def test_frase_fixa():
    assert i18n.tr("Pulando.") == "Skipping."
    assert i18n.tr("Tem certeza? Diz confirma.") == "Are you sure? Say confirm."


@pytest.mark.usefixtures("en")
def test_template_com_nome_de_jogo():
    assert i18n.tr("Abrindo Hollow Knight: Silksong.") == "Opening Hollow Knight: Silksong."
    # o modelo mais específico ganha do genérico "Tocando {track}."
    assert i18n.tr("Tocando o álbum Hybrid Theory, de Linkin Park.") == (
        "Playing the album Hybrid Theory, by Linkin Park."
    )


@pytest.mark.usefixtures("en")
def test_template_com_valor_traduzido():
    assert i18n.tr("Coloquei Numb, de Linkin Park, pra focar.") == (
        "I put on Numb, by Linkin Park, to help you focus."
    )


@pytest.mark.usefixtures("en")
def test_frase_desconhecida_volta_igual_e_vai_ao_log(caplog):
    with caplog.at_level(logging.INFO, logger="magi.core.i18n"):
        assert i18n.tr("Uma frase que ninguém previu.") == "Uma frase que ninguém previu."
        i18n.tr("Uma frase que ninguém previu.")
    assert [r.getMessage() for r in caplog.records].count("sem tradução: Uma frase que ninguém previu.") == 1


@pytest.mark.usefixtures("en")
def test_resposta_ja_em_ingles_volta_igual():
    text = "Silksong came out in September. It's a great one."
    assert i18n.tr(text) == text


@pytest.mark.usefixtures("en")
def test_varias_frases_misturadas():
    text = "Beleza. O SSD tá quase cheio: 93% ocupado, só 12 GB livres. Bora liberar espaço. Frase nova."
    assert i18n.tr(text) == (
        "Alright. The SSD is nearly full: 93% used, only 12 GB free. Let's free up some space. Frase nova."
    )


@pytest.mark.usefixtures("en")
def test_varias_linhas_e_resultado():
    result = i18n.tr_result(ActionResult(ok=True, speech="Pausado.", full_text="Pausado.\nHUD fechado."))
    assert result.speech == "Paused."
    assert result.full_text == "Paused.\nHUD closed."


def test_pt_br_nao_traduz():
    i18n.configure("pt-br")
    assert i18n.language_name() == "português do Brasil"
    assert i18n.tr("Pulando.") == "Pulando."
    result = ActionResult(ok=True, speech="Pulando.")
    assert i18n.tr_result(result) is result


def test_idioma_sem_tabela_cai_para_pt_br():
    i18n.configure("xx-yy")
    assert i18n.language() == "pt-br"


def test_persona_ganha_linha_de_idioma(en):
    assert "inglês britânico" in load_persona()
    i18n.configure("pt-br")
    assert "Idioma:" not in load_persona()


def test_cumprimento_em_ingles_sai():
    assert _GREETING.sub("", "Good evening, Pedro. Silksong is out.") == "Silksong is out."
    assert _GREETING.sub("", "Hello! Silksong is out.") == "Silksong is out."


# ---------------------------------------------------------------------------------------------
# Funis de fala
# ---------------------------------------------------------------------------------------------


class FakeHud:
    def __init__(self) -> None:
        self.sent: list = []

    async def send(self, msg) -> None:
        self.sent.append(msg)


class FakeSpeaker:
    def __init__(self) -> None:
        self.said: list[str] = []

    async def say(self, text, link, *, personal) -> None:
        self.said.append(text)


@pytest.mark.usefixtures("en")
async def test_deliver_do_turno_traduz():
    hud, speaker = FakeHud(), FakeSpeaker()
    link = SimpleNamespace(hello=SimpleNamespace(satellite="pc"))
    machine = TurnMachine(link, hud, TurnPipeline(TurnDeps(speaker=speaker)))
    machine._state = TurnState.THINKING
    await machine._deliver(ActionResult(ok=True, speech="Abrindo Hades."))
    assert speaker.said == ["Opening Hades."]
    assert any(isinstance(m, SubtitleMsg) and m.text == "Opening Hades." for m in hud.sent)


@pytest.mark.usefixtures("en")
async def test_sink_traduz_fala_e_card():
    hud = FakeHud()
    sink = ProactiveSink(hud)  # sem satélites: vai para a tela
    card = CardMsg(CardLevel.ALTA, "Controle com 10% de bateria")
    out = await sink.deliver("battery", "Bateria do controle em 10%. Bom pôr pra carregar.", card)
    assert out is Outcome.SCREEN
    assert hud.sent == [
        CardMsg(CardLevel.ALTA, "Controller at 10% battery"),
        SubtitleMsg("Controller battery at 10%. Best put it on charge."),
    ]
