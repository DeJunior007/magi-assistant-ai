"""R0.4: catálogo das 110 reações (CA-05, R1, R5, R8)."""

from __future__ import annotations

import re

from wired.reacoes import catalogo
from wired.reacoes.contratos import CORPO, EFEITO, Classe

_FAIXAS = {"B": 17, "C": 14, "F": 7, "V": 6, "D": 9, "P": 13}
_N = set(range(1, 91)) | {f"I{i}" for i in range(1, 21)}
_SINAIS = {"A", "B", "C", "D", "E", "F", "fan", "restart", "capturas", "datas", "P13"}


def _asset_ok(ident: str, letras: str) -> bool:
    m = re.fullmatch(r"([A-Z])(\d+)", ident)
    if not m or m[1] not in letras:
        return False
    k = int(m[2])
    return (2 if m[1] == "P" else 1) <= k <= _FAIXAS[m[1]]


def test_110_itens_chaves_unicas():
    assert len(catalogo.TODAS) == 110
    assert len(catalogo.DEFS) == 110
    assert {d.n for d in catalogo.TODAS} == _N
    for k, d in catalogo.DEFS.items():
        assert k == (d.chave if d.variante is None else (d.chave, d.variante))
        assert re.fullmatch(r"[a-z][a-z0-9_]*", d.chave)


def test_87_ativas_e_ca05():
    assert len(catalogo.ATIVAS) == 87
    for k, d in catalogo.DEFS.items():
        if d.sinal is not None:  # CA-05
            assert d.sinal in _SINAIS and k not in catalogo.ATIVAS
        if d.substituida:
            assert d.n in (49, 68) and k not in catalogo.ATIVAS
    assert sum(d.substituida for d in catalogo.TODAS) == 2


def test_passos_e_assets_validos():
    nomes_efeito = set(EFEITO.values())
    fixos = {c for c in CORPO if not c.endswith(":")}
    for d in catalogo.TODAS:
        assert 1 <= len(d.passos) <= 4, d.chave
        assert d.classes and d.cooldown_s > 0
        for p in d.passos:
            assert p.ms > 0
            assert p.eyes is None or _asset_ok(p.eyes, "BF"), (d.chave, p.eyes)
            assert p.mouth is None or _asset_ok(p.mouth, "CV"), (d.chave, p.mouth)
            assert len(p.efeitos) <= 3 and set(p.efeitos) <= nomes_efeito
            for c in p.corpo:
                if c.startswith("braco:"):
                    assert _asset_ok(c[6:], "P"), c
                elif c.startswith("iris:"):
                    assert _asset_ok(c[5:], "BF"), c
                else:
                    assert c in fixos, c


def test_classes_do_spec():
    por_n = {d.n: d for d in catalogo.TODAS}
    for n in (35, 37, 39, 53, 75, "I6", 20, 57, 62):
        # VOLTA/VITORIA não têm posto no governador: vêm junto com PEDRO ou SISTEMA
        assert por_n[n].classes & {Classe.PEDRO, Classe.SISTEMA}, n
    for n in (8, 16, 78, 83, 84, 85, "I14", "I15"):
        assert Classe.ZOEIRA in por_n[n].classes
    for n in (17, 18, 19):
        assert Classe.SONO in por_n[n].classes
    assert por_n[24].cooldown_s == 180.0 and por_n[64].cooldown_s == 3.0
    assert catalogo.DEFS[("musica_triste", "chopin")].n == "I12"
    assert catalogo.DEFS["hot"].n == 34 and catalogo.DEFS[("hot", "alivio")].n == 35
