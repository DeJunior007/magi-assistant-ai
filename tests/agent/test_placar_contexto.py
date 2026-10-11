"""V1.9: o placar e o "isso foi sem sentido" no contexto do agente — só o número que o HUD gravou."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from magi.agent.prompt import SELF_MAX_TOKENS, estimate_tokens
from magi.agent.self_model import (
    SelfModel,
    condessa_linhas,
    placar_texto,
    ultima_expressao_s,
)
from magi.common.contracts import TurnTagMsg
from magi.memory.turn_tag import classify

# quarta-feira 14/10/2026 15:00 (hora local): semana ISO de 12/10 a 18/10
AGORA = time.mktime(datetime(2026, 10, 14, 15, 0).timetuple())


def _estado(tmp_path: Path, dias: dict) -> Path:
    p = tmp_path / "condessa-estado.json"
    p.write_text(json.dumps({"salvo_em": AGORA, "placar": {"dias": dias, "ultimos": []}}), encoding="utf-8")
    return p


def test_placar_do_estado_do_hud(tmp_path):
    p = _estado(tmp_path, {
        "2026-10-14": {"ela": 3, "ele": 2}, "2026-10-12": {"ela": 1, "ele": 4},
        "2026-10-11": {"ela": 9, "ele": 9},  # semana passada: fora
    })
    assert placar_texto(p, AGORA) == "Condessa 3 × 2 Pedro · semana 4 × 6"


def test_madrugada_conta_no_dia_anterior(tmp_path):
    p = _estado(tmp_path, {"2026-10-13": {"ela": 2, "ele": 1}})
    madrugada = time.mktime(datetime(2026, 10, 14, 3, 0).timetuple())
    assert placar_texto(p, madrugada).startswith("Condessa 2 × 1 Pedro")


@pytest.mark.parametrize("conteudo", [None, "{", json.dumps({"humor": {}}), json.dumps({"placar": []})])
def test_sem_estado_nao_ha_numero(tmp_path, conteudo):
    p = tmp_path / "condessa-estado.json"
    if conteudo is not None:
        p.write_text(conteudo, encoding="utf-8")
    assert placar_texto(p, AGORA) is None
    linhas = condessa_linhas(p, tmp_path / "nada.jsonl", AGORA)
    assert "não sei" in linhas[0] and not any(c.isdigit() for c in linhas[0])


def _registro(tmp_path: Path, *linhas: dict) -> Path:
    p = tmp_path / "reacoes.jsonl"
    p.write_text("".join(json.dumps(x) + "\n" for x in linhas), encoding="utf-8")
    return p


def test_ultima_expressao_ignora_linhas_que_nao_sao_expressao(tmp_path):
    p = _registro(tmp_path, {"t": AGORA - 40, "tipo": "gesto"}, {"t": AGORA - 5, "tipo": "placar"},
                  {"t": AGORA - 2, "tipo": "repouso"})
    assert ultima_expressao_s(p, AGORA) == pytest.approx(40)
    assert ultima_expressao_s(tmp_path / "nada.jsonl", AGORA) is None


@pytest.mark.parametrize("idade, anotado", [(30, True), (90, False)])
def test_sem_sentido_com_e_sem_alvo(tmp_path, idade, anotado):
    reg = _registro(tmp_path, {"t": AGORA - idade, "tipo": "cena"})
    linha = condessa_linhas(tmp_path / "x.json", reg, AGORA)[1]
    assert ("hm, anotado" in linha) is anotado
    assert ("não sabe do que ele fala" in linha) is not anotado


def test_about_section_leva_o_placar_e_cabe_no_teto(tmp_path):
    p = _estado(tmp_path, {"2026-10-14": {"ela": 1, "ele": 0}})
    m = SelfModel(raw={"user": {"name": "Pedro"}},
                  condessa=lambda: condessa_linhas(p, tmp_path / "nada.jsonl", AGORA))
    about = m.about_section()
    assert "Placar com ele (HUD): Condessa 1 × 0 Pedro · semana 1 × 0." in about
    assert about.rstrip().endswith("Fora disso, não ofereça.")
    assert estimate_tokens(about) <= SELF_MAX_TOKENS


def test_about_section_fonte_quebrada_diz_que_nao_sabe():
    def quebra() -> list[str]:
        raise OSError("disco")

    about = SelfModel(raw={}, condessa=quebra).about_section()
    assert "Placar com ele: não sei agora" in about
    assert "Placar" not in SelfModel(raw={}).about_section()  # sem fonte ligada: nada


@pytest.mark.parametrize("frase", ["isso foi sem sentido", "Essa foi meio sem sentido, Condessa!",
                                   "ai, isso ficou totalmente sem sentido"])
def test_frase_vira_tag_sem_sentido(frase):
    assert classify(frase) == "sem_sentido"
    assert TurnTagMsg("sem_sentido").to_dict() == {"t": "turn_tag", "v": "sem_sentido"}


def test_frase_sem_sentido_nao_pega_outras():
    assert classify("o filme não faz sentido") is None
    assert classify("valeu, mandou bem") == "elogio"
