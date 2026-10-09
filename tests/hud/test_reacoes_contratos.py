"""R0.1: contratos e esqueleto do pacote ``wired.reacoes``."""

from __future__ import annotations

import dataclasses
import importlib
import random

import pytest
from wired import reacoes
from wired.reacoes import catalogo, governador, humor, passivas
from wired.reacoes.contratos import EFEITO, Classe, Def, Disparo, Passo
from wired.reactions import REACTIONS, Reaction

DETS = ("det_tempo", "det_musica", "det_sistema", "det_claude", "det_entrada", "det_conversa",
        "det_volume", "det_notif", "det_extras")
STUBS = DETS + ("passivas", "humor", "atividade", "governador", "registro", "catalogo")


def test_efeito_d1_a_d9():
    assert sorted(EFEITO) == [f"D{i}" for i in range(1, 10)]
    nomes = {"blush", "sweat", "zz", "question", "bang", "notes", "tear", "vein", "sparkle"}
    assert set(EFEITO.values()) == nomes


def test_classes():
    assert len(Classe) == 13
    assert Classe.NOTURNA == "noturna"


def test_passo_def_disparo():
    p = Passo(800, "B2", "C5", "player", ("blush",), ("sway",))
    d = Def("piscada_dupla", 1, "Piscada dupla", (p, Passo(200)), frozenset({Classe.PASSIVA}))
    assert d.mood == "calm" and d.prio == 1 and d.cooldown_s == 600.0
    assert d.sinal is None and d.fala is None and not d.substituida
    assert d.ms == 1000
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.ms = 1  # type: ignore[misc]
    a, b = Disparo("x", "teste"), Disparo("x", "teste")
    a.fmt["k"] = 1
    assert b.fmt == {} and a.variante is None


def test_detectores_registrados():
    assert len(reacoes.DETECTORES) == len(DETS)
    for nome in DETS:
        mod = importlib.import_module(f"wired.reacoes.{nome}")
        assert mod.detectar in reacoes.DETECTORES
        assert mod.detectar(None, None, {}) == []


@pytest.mark.parametrize("nome", STUBS)
def test_stub_tem_dono(nome):
    doc = importlib.import_module(f"wired.reacoes.{nome}").__doc__
    assert doc and "Dono: R" in doc


def test_stubs_vazios():
    d = Def("x", "I1", "X", (Passo(100),), frozenset())
    assert governador.escolher([Disparo("x", "t")], 0.0, {}) is None
    assert governador.aplicar_bloqueios(d, {}) == d.passos
    assert passivas.sortear({}, 0.0, random.Random(1)) is None
    assert humor.fatores({}) == {}
    assert isinstance(catalogo.DEFS, dict) and isinstance(catalogo.ATIVAS, frozenset)


def test_reaction_ganha_efeitos_e_corpo():
    r = Reaction("x", effect="blush", efeitos=("blush", "sparkle"), corpo=("sway",))
    assert r.effect == "blush" and r.efeitos == ("blush", "sparkle") and r.corpo == ("sway",)
    assert REACTIONS["music_love"].efeitos == () and REACTIONS["music_love"].corpo == ()
    assert REACTIONS["music_love"].effect == "notes" and REACTIONS["music_love"].bob
