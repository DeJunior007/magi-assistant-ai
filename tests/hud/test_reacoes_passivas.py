"""V0.7: passivas por momento e faixa (spec §3, §6, §9; acordo §3–§4)."""

from __future__ import annotations

import random
from collections import Counter

import pytest

from hud.wired.reacoes import catalogo, humor, momento, passivas
from hud.wired.reacoes.contratos import Disparo
from hud.wired.reacoes.vida import Faixa, Fone, Momento

TODAS_CAUSAS = {c: 1000.0 for c in passivas.CAUSAS_NEGATIVAS}


def _ctx(**kw) -> dict:
    base = {
        "agora": 1000.0, "hora": 15, "humor_pedro": 3, "musica_nota": None,
        "_passivas_inicio": 0.0, "ultima_expressao_em": 1000.0,
    }
    base.update(kw)
    return base


def _forcar(ctx: dict, n: int, seed: int = 1, agora: float = 1000.0) -> Counter:
    """``n`` sorteios com a hora marcada vencida (sem cota da hora, sem piso)."""
    rng = random.Random(seed)
    out: Counter = Counter()
    for _ in range(n):
        ctx["_passivas_proxima"] = agora
        ctx["_passivas_usos"] = []
        d = passivas.sortear(ctx, agora, rng)
        if d is not None:
            out[d.chave] += 1
    return out


# sinais que deixam caber o máximo de passivas em cada momento
_RICO = {
    "animo": 0.6, "energia": 0.2, "momento_ha_s": 2000.0, "pedro_inativo_s": 2000.0,
    "dancante": True, "claude_demorando": True, "causas": TODAS_CAUSAS,
}


@pytest.mark.parametrize("m", [m for m in Momento if momento.GRUPOS[m]])
@pytest.mark.parametrize("f", list(Faixa))
@pytest.mark.parametrize("nota", [None, 1])
def test_10000_sorteios_nunca_saem_do_grupo(m, f, nota):
    ctx = _ctx(momento=m, faixa_humor=f, musica_nota=nota, **_RICO)
    c = _forcar(ctx, 10_000)
    assert set(c) <= set(momento.GRUPOS[m]) - passivas.FAIXA_BLOQUEIA[f]


@pytest.mark.parametrize("m", [Momento.CONVERSA, Momento.ALERTA])
def test_momentos_sem_passiva(m):
    ctx = _ctx(momento=m, **_RICO)
    assert not _forcar(ctx, 500)
    assert passivas.media_s(ctx) is None


def test_nomes_dos_grupos_estao_no_catalogo():
    for m, grupo in momento.GRUPOS.items():
        for chave in grupo:
            assert chave in catalogo.DEFS, (m, chave)


def test_nenhuma_negativa_sem_causa():
    for m in (Momento.ESPERANDO, Momento.ATURANDO, Momento.TEDIO):
        ctx = _ctx(momento=m, musica_nota=-2 if m == Momento.ATURANDO else None,
                   momento_ha_s=4000.0)
        assert not set(_forcar(ctx, 3000)) & set(passivas.NEGATIVAS), m
    com = _forcar(_ctx(momento=Momento.ESPERANDO, claude_esperando=True), 3000)
    assert com["impaciente"] > 0 and com["soprando_franja"] > 0
    antiga = _forcar(_ctx(momento=Momento.ESPERANDO, causas={"claude_esperando": 1000.0 - 121}), 3000)
    assert antiga["impaciente"] == 0
    beicinho = _forcar(_ctx(momento=Momento.TEDIO, ei_ignorado=True), 3000)
    assert beicinho["beicinho"] > 0


@pytest.mark.parametrize("filtro", [{"hora": 23}, {"humor_pedro": 1}, {"madrugada": True}])
def test_negativa_nunca_sob_filtro(filtro):
    ctx = _ctx(momento=Momento.ESPERANDO, claude_esperando=True, causas=TODAS_CAUSAS, **filtro)
    assert not set(_forcar(ctx, 3000)) & set(passivas.NEGATIVAS)


@pytest.mark.parametrize("m", [Momento.CURTINDO, Momento.OUVINDO, Momento.JOGANDO, Momento.NO_FLOW])
def test_fone_e_ritmo_so_com_musica_e_e2(m):
    sem = _forcar(_ctx(momento=m, dancante=True), 3000)
    assert not set(sem) & passivas.FONE_RITMO
    pescoco = _forcar(_ctx(momento=m, musica_nota=2, dancante=True, fone=Fone.PESCOCO), 3000)
    assert not set(pescoco) & passivas.FONE_RITMO
    cabeca = _forcar(_ctx(momento=m, musica_nota=2, dancante=True, fone=Fone.CABECA), 3000)
    assert set(cabeca) & passivas.FONE_RITMO


def test_formato_antigo_do_reactor_faixa_none_e_sem_musica():
    ctx = _ctx(momento=Momento.CURTINDO, musica_nota=1, faixa=None)
    assert not humor.tem_musica(ctx) and humor.fone(ctx) == Fone.PESCOCO
    assert not set(_forcar(ctx, 2000)) & passivas.FONE_RITMO


def test_emburrada_nao_sorri():
    ctx = _ctx(momento=Momento.A_TOA, faixa_humor=Faixa.EMBURRADA, animo=0.6)
    assert _forcar(ctx, 3000)["sorriso_canto"] == 0
    ctx["faixa_humor"] = Faixa.RADIANTE
    assert _forcar(ctx, 3000)["sorriso_canto"] > 0


def test_piso_de_vida_6_min():
    vida = {"passiva_media_min": {"a_toa": 600}}  # média enorme: só o piso faz sair
    ctx = _ctx(momento=Momento.A_TOA, vida=vida, ultima_expressao_em=None)
    del ctx["_passivas_inicio"]
    rng = random.Random(5)
    saidas = [t for t in range(0, 3 * 3600, 10) if passivas.sortear(ctx, float(t), rng)]
    assert saidas and saidas[0] <= 6 * 60 + 10
    assert max(b - a for a, b in zip(saidas, saidas[1:], strict=False)) <= 6 * 60 + 10


def test_piso_com_grupo_vazio_vira_atencao():
    vida = {"passiva_media_min": {"a_toa": 600}}
    ctx = _ctx(momento=Momento.A_TOA, vida=vida, desligadas=frozenset(momento.GRUPOS[Momento.A_TOA]),
               ultima_expressao_em=0.0)
    d = passivas.sortear(ctx, 400.0, random.Random(1))
    assert d == Disparo(passivas.ATENCAO, "piso")


@pytest.mark.parametrize("m", [Momento.CONVERSA, Momento.JOGANDO])
def test_sem_piso_em_conversa_e_jogo(m):
    ctx = _ctx(momento=m, vida={"passiva_media_min": {"jogando": 600}}, ultima_expressao_em=0.0)
    rng = random.Random(2)
    assert not any(passivas.sortear(ctx, float(t), rng) for t in range(60, 1800, 10))


def test_piso_nao_vale_com_pedro_sumido():
    ctx = _ctx(momento=Momento.PEDRO_SUMIU, vida={"passiva_media_min": {"pedro_sumiu": 600}},
               ultima_expressao_em=0.0)
    assert not passivas.piso_vencido(ctx, 1000.0, Momento.PEDRO_SUMIU)


def test_intervalo_pela_media_do_momento_e_energia():
    def media(**kw):
        ctx = _ctx(momento=Momento.OUVINDO, **kw)
        rng = random.Random(9)
        tot = 0.0
        for _ in range(4000):
            passivas._agendar(ctx, 0.0, Momento.OUVINDO, rng)
            tot += ctx["_passivas_proxima"]
        return tot / 4000

    normal = media(energia=0.5)
    assert normal == pytest.approx(90 + 300 * 2.718281828 ** -0.3, rel=0.08)
    assert media(energia=0.8) < normal < media(energia=0.1)
    assert media(energia=0.5, hora=23) > normal
    assert passivas.media_s(_ctx(momento=Momento.CURTINDO)) == pytest.approx(3.5 * 60)


def test_minimo_90s_e_no_maximo_12_por_hora():
    ctx = _ctx(momento=Momento.CURTINDO, musica_nota=1, fone=Fone.CABECA,
               vida={"passiva_media_min": {"curtindo": 0.01}})
    rng = random.Random(4)
    saidas = []
    for t in range(60, 60 + 2 * 3600, 10):
        d = passivas.sortear(ctx, float(t), rng)
        if d is not None and d.chave != passivas.ATENCAO:
            saidas.append(t)
    assert min(b - a for a, b in zip(saidas, saidas[1:], strict=False)) >= 90
    assert all(sum(1 for s in saidas if t <= s < t + 3600) <= 12 for t in saidas)


def test_peso_cai_com_o_uso():
    ctx = _ctx(momento=Momento.A_TOA)
    ctx["_passivas_usos"] = [(900.0, "sacada_olhar"), (950.0, "sacada_olhar")]
    ps = passivas.pesos(ctx, 1000.0)
    assert ps["sacada_olhar"] == pytest.approx(0.09) and ps["piscada_dupla"] == 1.0


def test_primeiro_minuto_sem_passiva():
    ctx = _ctx(momento=Momento.A_TOA)
    del ctx["_passivas_inicio"]
    rng = random.Random(1)
    assert all(passivas.sortear(ctx, 1000.0 + t, rng) is None for t in range(0, 60, 10))


def test_catalogo_ativo_desligadas_e_cooldown():
    from hud.wired.reacoes.governador import Estado

    est = Estado()
    est.toques["sacada_olhar"].append(990.0)
    ctx = _ctx(momento=Momento.A_TOA, estado=est, desligadas=frozenset({"piscada_gato"}),
               defs={k: catalogo.DEFS[k] for k in catalogo.ATIVAS})
    ps = passivas.permitidas(ctx, 1000.0)
    assert "sacada_olhar" not in ps and "piscada_gato" not in ps and "piscada_dupla" in ps


def test_humor_so_le_momento_e_faixa():
    assert humor.fatores({}) == {}
    assert humor.fatores({"momento": "tedio", "faixa_humor": "neutra"}) == {
        "momento": "tedio", "faixa": "neutra",
    }
    assert humor.momento({"musica_nota": 2}) == Momento.CURTINDO
    assert humor.faixa({}) == Faixa.CONTENTE


_NOVAS = {
    "mao_no_queixo": (Momento.TRABALHANDO_JUNTO, Momento.ESTUDANDO),
    "sacada_player": (Momento.ATURANDO,),
    "flagra_no_forum": (Momento.TEDIO,),
}


def test_v11_tres_passivas_no_catalogo_e_nos_grupos():
    for chave, momentos in _NOVAS.items():
        d = catalogo.DEFS[chave]
        assert catalogo.Classe.PASSIVA in d.classes and d.sinal is None
        assert {m for m, g in momento.GRUPOS.items() if chave in g} == set(momentos)
    assert "flagra_no_forum" in momento.ZOEIRA


def test_v11_asset_ausente_pula_o_extra():
    # sem nenhum PNG extra, as 3 seguem ativas: o braço P10 é só extra de corpo (o retrato usa o
    # braço da base quando falta ``extra/P10.png``) e os olhares são para painéis que já existem
    sem_arte = catalogo.ativas(lambda _rel: False)
    assert set(_NOVAS) <= sem_arte
    passos = catalogo.DEFS["mao_no_queixo"].passos
    assert any("braco:P10" in p.corpo for p in passos)
    assert all(p.eyes and p.mouth for p in passos)  # o rosto anda sozinho, sem o braço
    assert {p.look for p in catalogo.DEFS["sacada_player"].passos} >= {"player"}


@pytest.mark.parametrize("chave", list(_NOVAS))
def test_v11_sorteio_das_novas_fica_no_grupo(chave):
    for m in _NOVAS[chave]:
        ctx = _ctx(momento=m, faixa_humor=Faixa.CONTENTE, musica_nota=-1 if m == Momento.ATURANDO else None,
                   **_RICO)
        c = _forcar(ctx, 2000)
        assert c[chave] > 0, (chave, m)
        assert set(c) <= set(momento.GRUPOS[m])
