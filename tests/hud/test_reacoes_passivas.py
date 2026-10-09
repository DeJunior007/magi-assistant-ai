"""R1.1: passivas sorteadas pelo humor (spec §4–§5, acordo §4)."""

from __future__ import annotations

import random
from collections import Counter
from types import SimpleNamespace

import pytest

from hud.wired.reacoes import catalogo, humor, passivas
from hud.wired.reacoes.contratos import Disparo
from hud.wired.reacoes.governador import Estado


def _ctx(**kw) -> dict:
    base = {
        "defs": {k: catalogo.DEFS[k] for k in catalogo.ATIVAS},
        "estado": Estado(), "agora": 1000.0, "relogio": 1.7e9, "hora": 15, "madrugada": False,
        "humor": 3, "jogo": False, "claude": True, "musica_nota": 0, "faixa": None,
        "veredito": None, "desligadas": frozenset(), "_passivas_inicio": 0.0,
    }
    base.update(kw)
    return base


def _contagem(ctx: dict, n: int, seed: int = 1) -> Counter:
    rng = random.Random(seed)
    out: Counter = Counter()
    for _ in range(n):
        d = passivas.sortear(ctx, ctx["agora"], rng)
        if d is not None:
            out[d.chave] += 1
    return out


def test_primeiro_minuto_sem_passiva():
    ctx = _ctx()
    del ctx["_passivas_inicio"]
    rng = random.Random(1)
    assert all(passivas.sortear(ctx, 1000.0 + t, rng) is None for t in range(0, 60, 10))
    assert any(passivas.sortear(ctx, 1060.0, rng) for _ in range(50))


def test_passivas_estao_no_catalogo_ativo():
    for n, chave in passivas.PASSIVAS.items():
        assert chave in catalogo.ATIVAS
        assert catalogo.DEFS[chave].n == n
    assert sorted(passivas.PASSIVAS) == [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 21, 22, 23]


@pytest.mark.parametrize("chave", sorted(passivas.PASSIVAS.values()))
def test_ca04_cada_passiva_sai_no_sorteio(chave):
    c = _contagem(_ctx(), 3000)
    assert c[chave] > 0


def test_sorteio_devolve_disparo_ou_nada():
    rng = random.Random(3)
    saidas = [passivas.sortear(_ctx(), 1000.0, rng) for _ in range(200)]
    assert any(s is None for s in saidas)
    assert all(isinstance(s, Disparo) and s.motivo == "passiva" for s in saidas if s is not None)


def test_pedro_mal_nunca_escolhe_zoeira():
    ctx = _ctx(humor=1)
    assert humor.PEDRO_MAL in humor.fatores(ctx)
    rng = random.Random(7)
    vistos = Counter()
    for _ in range(10_000):
        d = passivas.sortear(ctx, ctx["agora"], rng)
        if d is not None:
            vistos[d.chave] += 1
    assert vistos["beicinho"] == 0 and vistos["soprando_franja"] == 0
    assert vistos["piscada_gato"] > vistos["piscada_dupla"]


def test_madrugada_bloqueia_zoeira():
    ps = passivas.pesos(_ctx(madrugada=True))
    assert "beicinho" not in ps and "soprando_franja" not in ps


def test_favorita_do_dia_nunca_favorece_corando():
    verd = SimpleNamespace(artist="ado", note=1)
    ctx = _ctx(faixa=("Usseewa", "Ado"), veredito=verd, favorita_dia="ado", musica_nota=1)
    ativos = humor.fatores(ctx)
    assert humor.FAVORITA_DIA in ativos
    assert humor.peso("corando", ativos) == 1.0
    assert humor.peso("cabeca_ritmo", ativos) > humor.peso("corando", ativos)
    for f in humor.PESOS:
        assert "corando" not in humor.FAVORECE[f]


def test_os_12_fatores_tem_peso_do_acordo():
    assert len(humor.PESOS) == 12 and set(humor.FAVORECE) == set(humor.PESOS)
    assert humor.PESOS[humor.PEDRO_MAL] == 9 and humor.PESOS[humor.FAVORITA_DIA] == 8
    assert humor.PESOS[humor.MANHA] == 3 and humor.PESOS[humor.MADRUGADA] == 7


def test_pc_com_problema_tira_sorriso_e_cantarolando():
    ps = passivas.pesos(_ctx(pc_problema=True))
    assert "sorriso_canto" not in ps and "cantarolando" not in ps
    assert ps["suspiro"] == 1 + humor.PESOS[humor.PC_PROBLEMA]


def test_musica_que_gosta_e_que_odeia():
    gosta = humor.fatores(_ctx(faixa=("a", "b"), musica_nota=2))
    assert {humor.MUSICA, humor.MUSICA_GOSTA} <= set(gosta)
    odeia = humor.fatores(_ctx(faixa=("a", "b"), musica_nota=-1))
    assert humor.MUSICA_ODEIA in odeia and humor.MUSICA_GOSTA not in odeia
    assert humor.peso("beicinho", odeia) == 1 + humor.PESOS[humor.MUSICA_ODEIA]


def test_manha_so_na_primeira_hora_do_bom_dia():
    est = Estado()
    est.toques["bom_dia"].append(1000.0)
    assert humor.MANHA in humor.fatores(_ctx(estado=est, agora=1500.0))
    assert humor.MANHA not in humor.fatores(_ctx(estado=est, agora=1000.0 + 3700))


def test_vitoria_recente_por_variante_e_por_chave():
    est = Estado()
    est.ultimo = Disparo("claude", "fim", variante="terminou")
    ctx = _ctx(estado=est, agora=100.0)
    assert humor.VITORIA in humor.fatores(ctx)
    ctx["agora"] = 100.0 + 601
    assert humor.VITORIA not in humor.fatores(ctx)
    est2 = Estado()
    est2.ultimo = Disparo("hot", "quente")  # o alerta, não o alívio
    assert humor.VITORIA not in humor.fatores(_ctx(estado=est2))
    est2.toques["rede_voltou"].append(950.0)
    assert humor.VITORIA in humor.fatores(_ctx(estado=est2, agora=1000.0))


def test_silencio_longo_precisa_de_30_min():
    ctx = _ctx(claude=False, faixa=None, agora=0.0)
    assert humor.SILENCIO not in humor.fatores(ctx)
    ctx["agora"] = 30 * 60.0
    assert humor.SILENCIO in humor.fatores(ctx)
    ctx["claude"] = True
    assert humor.SILENCIO not in humor.fatores(ctx)


def test_desempenho_em_jogo_reduz_a_chance_pela_metade():
    ctx = _ctx(jogo=True, agora=0.0)
    humor.fatores(ctx)
    ctx["agora"] = 301.0
    assert humor.DESEMPENHO_JOGO in humor.fatores(ctx)
    normal = sum(_contagem(_ctx(), 4000).values())
    jogo = sum(_contagem(ctx, 4000).values())
    assert 0.35 < jogo / normal < 0.65


def test_sessao_longa_pela_atividade():
    class Ativ:
        def parado_s(self, agora):
            return 10.0

    ctx = _ctx(atividade=Ativ(), relogio=0.0)
    assert humor.SESSAO_LONGA not in humor.fatores(ctx)
    ctx["relogio"] = 3 * 3600.0
    assert humor.SESSAO_LONGA in humor.fatores(ctx)


def test_desligadas_e_cooldown_ficam_fora():
    est = Estado()
    est.toques["suspiro"].append(990.0)
    ps = passivas.pesos(_ctx(estado=est, desligadas=frozenset({"beicinho"})))
    assert "beicinho" not in ps and "suspiro" not in ps and "piscada_dupla" in ps
