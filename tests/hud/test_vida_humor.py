"""V0.2 — Humor da Condessa (spec §2, acordo §1): CA-V1 e CA-V2 (parte do humor)."""

from __future__ import annotations

import json

import pytest
from wired.reacoes import estado
from wired.reacoes.estado import EVENTOS, Estado, Humor, Postura
from wired.reacoes.vida import VIDA_PADRAO, Evento, Faixa, Fone

T0 = 1_000_000.0
BASE = VIDA_PADRAO["humor"]["base_animo"]


def ev(tipo: str, fonte: str = "x", em: float = T0) -> Evento:
    return Evento(tipo, fonte, em)


def humor(animo: float = BASE) -> Humor:
    h = Humor()
    h.animo = animo
    h.energia_nivel = 0.5
    return h


# ── CA-V1: tabela de Δ ─────────────────────────────────────────────────────
@pytest.mark.parametrize("tipo", sorted(EVENTOS))
def test_tabela_delta(tipo):
    h = humor(0.0)
    d_animo, d_energia, _ = EVENTOS[tipo]
    assert h.aplicar(ev(tipo), T0) == pytest.approx(d_animo)
    assert h.animo == pytest.approx(d_animo)
    assert h.energia_nivel == pytest.approx(0.5 + d_energia)


def test_tabela_transcreve_acordo():
    assert EVENTOS["ado"][:2] == (0.30, 0.15)
    assert EVENTOS["faixa_nota_menos2"][0] == -0.20
    assert EVENTOS["jogo_abriu"][:2] == (0.05, 0.25)


def test_evento_desconhecido_nao_mexe():
    h = humor(0.0)
    assert h.aplicar(ev("nao_existe"), T0) == 0.0


def test_causas_no_medidor():
    h = humor(0.0)
    for i, t in enumerate(["commit", "faxina", "tag_elogio", "ado"]):
        h.aplicar(ev(t, fonte=t), T0 + i)
    valor, cor, momento, causas = h.medidor()
    assert valor == pytest.approx(h.animo)
    assert cor.startswith("#")
    assert [c.texto for c in causas] == ["faxina", "elogio", "Ado"]
    assert causas[-1].delta == pytest.approx(0.30)


# ── habituação ─────────────────────────────────────────────────────────────
def test_habituacao_mesmo_tipo_em_30_min():
    h = humor(0.0)
    d = [h.aplicar(ev("commit", fonte=f"f{i}"), T0 + i * 60) for i in range(3)]
    assert d == pytest.approx([0.10, 0.06, 0.036])


def test_habituacao_some_depois_da_janela():
    h = humor(0.0)
    h.aplicar(ev("commit", "a"), T0)
    assert h.aplicar(ev("commit", "b"), T0 + 31 * 60) == pytest.approx(0.10)


@pytest.mark.parametrize("tipo", ["ado", "favorita"])
def test_ado_e_favorita_nao_habituam(tipo):
    h = humor(-0.5)
    assert h.aplicar(ev(tipo, "a"), T0) == pytest.approx(0.30)
    assert h.aplicar(ev(tipo, "b"), T0 + 60) == pytest.approx(0.30)


def test_clique_carinhoso_ate_3_por_hora():
    h = humor(0.0)
    ds = [h.aplicar(ev("clique_carinho", f"f{i}"), T0 + i) for i in range(4)]
    assert ds[3] == 0.0 and ds[0] == pytest.approx(0.05)


# ── trava por fonte ────────────────────────────────────────────────────────
def test_trava_por_fonte_na_hora():
    h = humor(-1.0)
    total = sum(h.aplicar(ev("ado", "musica"), T0 + i) for i in range(4))
    assert total == pytest.approx(0.6)
    # outra fonte não é travada
    assert h.aplicar(ev("tag_elogio", "pedro"), T0 + 5) == pytest.approx(0.25)
    # depois de uma hora a fonte libera
    assert h.aplicar(ev("ado", "musica"), T0 + 3601) == pytest.approx(0.30)


def test_trava_negativa_por_fonte():
    h = humor(1.0)
    total = sum(h.aplicar(ev(t, "musica"), T0 + i)
                for i, t in enumerate(["faixa_nota_menos2", "birra", "faixa_nota_menos1",
                                       "faixa_nota_menos2", "birra", "faixa_nota_menos1",
                                       "faixa_nota_menos2", "birra"]))
    assert total == pytest.approx(-0.6)


# ── piso de sistema e teto do Pedro mal ────────────────────────────────────
def test_piso_de_sistema():
    h = humor(-0.25)
    assert h.aplicar(ev("fps_episodio", "sistema"), T0) == pytest.approx(-0.05)
    assert h.animo == pytest.approx(-0.3)
    assert h.aplicar(ev("claude_erro", "sistema"), T0 + 1) == 0.0
    # outra fonte desce normalmente
    assert h.aplicar(ev("birra", "musica"), T0 + 2) == pytest.approx(-0.15)


def test_teto_com_pedro_mal():
    h = humor(0.2)
    h.tick(T0, 10, {"pedro_mal": True})
    h.aplicar(ev("ado", "musica"), T0)
    assert h.animo == pytest.approx(0.3)
    h.tick(T0 + 1, 10, {})
    assert h.aplicar(ev("favorita", "m2"), T0 + 1) > 0.25


# ── meia-vida assimétrica ──────────────────────────────────────────────────
def test_meia_vida_acima_25_min():
    h = humor(BASE + 0.4)
    h.tick(T0, 10, {})
    h.tick(T0 + 25 * 60, 10, {})
    assert h.animo == pytest.approx(BASE + 0.2)


def test_meia_vida_abaixo_8_min():
    h = humor(BASE - 0.4)
    h.tick(T0, 10, {})
    h.tick(T0 + 8 * 60, 10, {})
    assert h.animo == pytest.approx(BASE - 0.2)


def test_meia_vida_em_passos_de_5s_igual():
    h = humor(BASE + 0.4)
    h.tick(T0, 10, {})
    for i in range(1, 25 * 12 + 1):
        h.tick(T0 + i * 5, 10, {})
    assert h.animo == pytest.approx(BASE + 0.2)


# ── silêncio só na energia; Pedro sumido no ânimo ──────────────────────────
def test_silencio_nao_mexe_no_animo_so_na_energia():
    h = humor(BASE)
    h.tick(T0, 10, {"silencio_min": 0})
    e0 = h.energia
    h.tick(T0 + 1, 10, {"silencio_min": 30})
    assert h.animo == pytest.approx(BASE)
    assert h.energia == pytest.approx(e0 - 0.10, abs=1e-3)
    h.tick(T0 + 2, 10, {"silencio_min": 300})
    assert h.animo == pytest.approx(BASE)
    assert h.energia == pytest.approx(e0 - 0.20, abs=1e-3)


def test_pedro_sumido():
    h = humor(BASE)
    h.cfg["meia_vida_abaixo_min"] = 1e12  # isola o decaimento
    h.tick(T0, 10, {"pedro_ausente_min": 44})
    assert h.animo == pytest.approx(BASE)
    h.tick(T0, 10, {"pedro_ausente_min": 45})
    assert h.animo == pytest.approx(BASE - 0.05)
    h.tick(T0, 10, {"pedro_ausente_min": 59})
    assert h.animo == pytest.approx(BASE - 0.05)
    h.tick(T0, 10, {"pedro_ausente_min": 75})
    assert h.animo == pytest.approx(BASE - 0.15)
    assert h.medidor()[3][-1].texto == "Pedro sumido"
    h.tick(T0, 10, {"pedro_ausente_min": 0})
    assert h.sumido_aplicados == 0


# ── energia ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("hora", "alvo"), [(9, 0.7), (13, 0.55), (15, 0.7), (20, 0.6),
                                            (23, 0.4), (1, 0.4), (3, 0.2), (8, 0.7)])
def test_energia_alvo_pela_hora(hora, alvo):
    assert Humor()._alvo_energia(hora) == alvo


def test_energia_meia_vida_e_bonus():
    h = humor()
    h.energia_nivel = 0.9
    h.tick(T0, 10, {})
    h.tick(T0 + 15 * 60, 10, {})
    assert h.energia_nivel == pytest.approx(0.8)  # alvo 0,7, desvio 0,2 → 0,1
    h.tick(T0 + 15 * 60, 10, {"musica_nota": 1, "jogo": True})
    assert h.energia == pytest.approx(1.0)  # 0,8 + 0,3, preso em 1
    h.tick(T0 + 15 * 60, 10, {"musica_nota": 0})
    assert h.energia == pytest.approx(0.8)


# ── histerese de faixa ─────────────────────────────────────────────────────
def test_faixa_histerese_e_60s():
    h = humor(BASE)
    assert h.faixa(T0) == Faixa.CONTENTE
    h.animo = 0.52  # passou do limiar, mas dentro da histerese
    assert h.faixa(T0) == Faixa.CONTENTE
    h.animo = 0.56
    assert h.faixa(T0) == Faixa.CONTENTE  # 60 s na faixa nova
    assert h.faixa(T0 + 59) == Faixa.CONTENTE
    assert h.faixa(T0 + 60) == Faixa.RADIANTE
    h.animo = 0.47  # dentro da histerese para baixo
    assert h.faixa(T0 + 200) == Faixa.RADIANTE


def test_faixa_volta_cancela_pendente():
    h = humor(-0.45)
    h._faixa = Faixa.NEUTRA
    assert h.faixa(T0) == Faixa.NEUTRA
    h.animo = -0.2
    assert h.faixa(T0 + 40) == Faixa.NEUTRA
    h.animo = -0.45
    assert h.faixa(T0 + 70) == Faixa.NEUTRA  # contagem recomeçou
    assert h.faixa(T0 + 130) == Faixa.EMBURRADA
    assert h.medidor()[1] == estado.COR_FAIXA[Faixa.EMBURRADA]


def test_numeros_vem_do_cfg():
    h = Humor({"base_animo": 0.0, "limiar": {"radiante": 0.3}})
    assert h.animo == 0.0 and h.cfg["limiar"]["contente"] == 0.05
    h.animo = 0.4
    h.faixa(T0)
    assert h.faixa(T0 + 60) == Faixa.RADIANTE


# ── CA-V2: persistência ────────────────────────────────────────────────────
def test_salvar_carregar_mantem_tudo(tmp_path):
    h = humor(0.0)
    h.aplicar(ev("commit", "claude"), T0)
    h.aplicar(ev("ado", "musica"), T0 + 1)
    h.momento = "curtindo"
    h.faixa(T0 + 2)
    e = Estado(h, Postura(Fone.CABECA, "música"), {"cenas": [T0], "negativas": 2})
    e.salvar(T0 + 2)
    assert estado.ESTADO_FILE.exists()
    assert not estado.ESTADO_FILE.with_name(estado.ESTADO_FILE.name + ".tmp").exists()
    r = Estado.carregar(T0 + 2)
    assert r.humor.animo == pytest.approx(h.animo)
    assert [c.texto for c in r.humor.causas] == ["commit", "Ado"]
    assert r.postura == Postura(Fone.CABECA, "música")
    assert r.governador == {"cenas": [T0], "negativas": 2}
    assert r.humor.medidor()[2] == "curtindo"
    # a habituação sobrevive ao reinício
    assert r.humor.aplicar(ev("commit", "outra"), T0 + 3) == pytest.approx(0.06)


def test_carregar_aplica_decaimento_do_tempo_fechado(tmp_path):
    p = tmp_path / "e.json"
    Estado(humor(BASE - 0.4)).salvar(T0, p)
    r = Estado.carregar(T0 + 8 * 60, path=p)
    assert r.humor.animo == pytest.approx(BASE - 0.2)


@pytest.mark.parametrize("conteudo", ["", "{", "[]", json.dumps({"humor": {"animo": "x"}}),
                                      json.dumps({"salvo_em": 1, "humor": {}})])
def test_estado_invalido_volta_a_base(tmp_path, conteudo):
    p = tmp_path / "e.json"
    p.write_text(conteudo)
    r = Estado.carregar(T0, path=p)
    assert r.humor.animo == BASE and r.governador == {} and r.postura == Postura()


def test_sem_arquivo_volta_a_base():
    r = Estado.carregar(T0)
    assert r.humor.animo == BASE
