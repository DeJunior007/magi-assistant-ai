"""Pose de pensar (espera viva, spec §2.1/§2.3, CA-02)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hud.wired import pensando
from hud.wired.pensando import THINK_CYCLE, pose
from magi.common.contracts import THINK_TOOLS

ROOT = Path(__file__).resolve().parents[2]


def tudo(_: str) -> bool:
    return True


def sem(*faltam: str):
    return lambda p: p not in {f"eyes/{x}.png" for x in faltam}


@pytest.mark.parametrize(("t", "etapa"), [(0.0, "hm"), (1.19, "hm"), (1.21, "pensando"),
                                          (3.49, "pensando"), (3.51, "concentrada")])
def test_etapas_pelo_tempo(t, etapa):
    assert pose(t, None, 0, tudo).etapa == etapa


def test_tabela_das_etapas():
    hm = pose(0.5, None, 0, tudo)
    assert hm.ciclo == (("F4", 5.0, -3.0),) and hm.tilt == 3.0
    assert hm.efeitos == () and hm.corpo == ()
    p = pose(2.0, None, 0, tudo)
    assert p.ciclo == THINK_CYCLE and p.passo_s == 1.3 and p.tilt == 2.2
    assert p.efeitos == ("dots",) and p.corpo == ("sway",)
    c = pose(10.0, None, 0, tudo)
    assert [o for o, _, _ in c.ciclo] == ["B18", "B13"]
    assert c.passo_s == 2.0 and c.tilt == 1.5
    assert c.efeitos == ("dots",) and c.corpo == ("bob_lento", "braco:P14")


def test_concentrada_sem_b18():
    c = pose(4.0, None, 0, sem("B18"))
    assert [o for o, _, _ in c.ciclo] == ["B13", "F7"]


@pytest.mark.parametrize("t", [0.0, 0.5, 1.19, 2.0, 5.0])
def test_lote_nunca_volta_ao_hm(t):
    assert pose(t, None, 1, tudo).etapa != "hm"
    assert pose(t, None, 3, tudo).etapa != "hm"


def test_lote_conta_do_aviso():
    assert pose(0.0, None, 1, tudo).etapa == "pensando"
    assert pose(3.51, None, 1, tudo).etapa == "concentrada"


def test_asset_ausente_sai_do_ciclo():
    p = pose(2.0, None, 0, sem("F6", "F1"))
    assert [o for o, _, _ in p.ciclo] == ["B13", "F4", "B13", "F7"]
    c = pose(5.0, None, 0, sem("B18", "F7"))
    assert [o for o, _, _ in c.ciclo] == ["B13"]


def test_ciclo_vazio_volta_ao_think_cycle():
    nada = lambda _: False  # noqa: E731
    for t in (0.0, 2.0, 5.0):
        assert pose(t, None, 0, nada).ciclo == THINK_CYCLE
    assert pose(0.0, None, 0, sem("F4")).ciclo == THINK_CYCLE


@pytest.mark.parametrize(("tool", "painel"), [
    ("news_query", "radio"),
    ("spotify_play", "player"), ("spotify_pick", "player"), ("spotify_control", "player"),
    ("open_game", "fps"), ("close_game", "fps"), ("game_help", "fps"), ("steam_game", "fps"),
    ("rgb", "led"),
    *[(t, None) for t in ("search", "self_info", "screenshot", "hud", "volume", "remember",
                          "forget", "other")],
    (None, None),
])
def test_ferramenta_olhar(tool, painel):
    for t in (0.5, 2.0, 5.0):
        p = pose(t, tool, 0, tudo)
        assert p.look == painel
    if painel:  # o olhar não troca a etapa nem o ciclo
        assert pose(2.0, tool, 0, tudo).ciclo == THINK_CYCLE


def test_tabela_cobre_think_tools():
    assert set(pensando.TOOL_PAINEL) <= THINK_TOOLS
    assert pensando.OLHAR_PAINEL_S == 1.5


def _const(path: Path, nome: str):
    for no in ast.parse(path.read_text()).body:
        if isinstance(no, ast.Assign) and any(getattr(t, "id", None) == nome for t in no.targets):
            return ast.literal_eval(no.value)
    raise KeyError(nome)


def test_copias_batem_com_o_retrato_e_look_dirs():
    portrait = ROOT / "hud/wired/portrait.py"
    assert _const(portrait, "THINK_CYCLE") == THINK_CYCLE
    assert _const(portrait, "THINK_STEP") == pensando.THINK_STEP
    assert _const(portrait, "THINK_TILT") == pensando.THINK_TILT
    dirs = _const(ROOT / "hud/wired/reactions.py", "LOOK_DIRS")
    for painel in pensando.TOOL_PAINEL.values():
        assert painel in dirs["main"] and painel in dirs["idle"]
