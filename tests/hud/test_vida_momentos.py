"""CA-V3: momentos (spec §3, acordo §3) — uma linha da tabela por teste, desempates, histerese."""

import pytest
from wired.reacoes import momento as m
from wired.reacoes.vida import VIDA_PADRAO, Filtro, Momento, mesclar

M = Momento

LINHAS = [
    (M.CONVERSA, {"magui_ativa": True}),
    (M.CONVERSA, {"turno_pedro_ha_s": 60}),
    (M.ALERTA, {"alerta": "disco_cheio"}),
    (M.JOGANDO, {"jogo": "fifa"}),
    (M.ESPERANDO, {"claude_esperando": True}),
    (M.NO_FLOW, {"claude_rodando": True, "musica_nota": 0}),
    (M.NO_FLOW, {"lm_on": True, "musica_nota": 2}),
    (M.TRABALHANDO_JUNTO, {"claude_rodando": True}),
    (M.ESTUDANDO, {"lm_on": True}),
    (M.CURTINDO, {"musica_nota": 1}),
    (M.ATURANDO, {"musica_nota": -1}),
    (M.OUVINDO, {"musica_nota": 0}),
    (M.PEDRO_SUMIU, {"pedro_inativo_s": 600}),
    (M.TEDIO, {"pedro_inativo_s": 30, "sem_musica_ha_s": 900}),
    (M.A_TOA, {"pedro_inativo_s": 30, "sem_musica_ha_s": 300}),
]


@pytest.mark.parametrize(("esperado", "ctx"), LINHAS)
def test_uma_linha_da_tabela(esperado, ctx):
    assert m.bruto(ctx) == esperado
    assert m.decidir(dict(ctx), None, 0.0) == esperado


@pytest.mark.parametrize(
    ("esperado", "ctx"),
    [
        (M.CONVERSA, {"turno_pedro_ha_s": 10, "alerta": "rede", "jogo": "x"}),
        (M.ALERTA, {"alerta": "popup", "jogo": "x", "claude_esperando": True}),
        (M.JOGANDO, {"jogo": "x", "claude_esperando": True, "musica_nota": 2}),
        (M.ESPERANDO, {"claude_esperando": True, "claude_rodando": True}),
        (M.NO_FLOW, {"claude_rodando": True, "lm_on": True, "musica_nota": 1}),
        (M.ATURANDO, {"claude_rodando": True, "musica_nota": -1}),
        (M.TRABALHANDO_JUNTO, {"claude_rodando": True, "lm_on": True}),
        (M.CURTINDO, {"musica_nota": 2, "pedro_inativo_s": 9999}),
        (M.PEDRO_SUMIU, {"pedro_inativo_s": 700, "sem_musica_ha_s": 9999}),
        (M.A_TOA, {"turno_pedro_ha_s": 120, "sem_musica_ha_s": 100}),
        (M.A_TOA, {"claude_rodando": False, "lm_on": False}),
    ],
)
def test_desempates_pela_prioridade(esperado, ctx):
    assert m.bruto(ctx) == esperado


def test_histerese_30s_estavel():
    memo: dict = {}
    ctx = {"musica_nota": 1, "memo": memo}
    assert m.decidir(ctx, M.A_TOA, 100.0) == M.A_TOA
    assert m.decidir(ctx, M.A_TOA, 129.0) == M.A_TOA
    assert m.decidir(ctx, M.A_TOA, 130.0) == M.CURTINDO
    assert memo == {}


def test_histerese_recomeca_se_o_candidato_muda():
    memo: dict = {}
    assert m.decidir({"musica_nota": 1, "memo": memo}, M.A_TOA, 0.0) == M.A_TOA
    assert m.decidir({"musica_nota": -1, "memo": memo}, M.A_TOA, 20.0) == M.A_TOA
    assert m.decidir({"musica_nota": -1, "memo": memo}, M.A_TOA, 45.0) == M.A_TOA
    assert m.decidir({"musica_nota": -1, "memo": memo}, M.A_TOA, 50.0) == M.ATURANDO


def test_histerese_volta_ao_anterior_zera_candidato():
    memo: dict = {}
    m.decidir({"musica_nota": 1, "memo": memo}, M.A_TOA, 0.0)
    assert m.decidir({"memo": memo}, M.A_TOA, 10.0) == M.A_TOA
    assert "candidato" not in memo


def test_estavel_vem_do_vida():
    vida = mesclar(VIDA_PADRAO, {"momento_estavel_s": 5})
    memo: dict = {}
    ctx = {"musica_nota": 1, "memo": memo, "vida": vida}
    m.decidir(ctx, M.A_TOA, 0.0)
    assert m.decidir(ctx, M.A_TOA, 5.0) == M.CURTINDO


@pytest.mark.parametrize(
    "ctx", [{"magui_ativa": True}, {"alerta": "rede_caiu"}, {"jogo": "fifa"}]
)
def test_imediatos_nao_esperam(ctx):
    assert m.decidir({**ctx, "memo": {}}, M.CURTINDO, 0.0) == m.bruto(ctx)


def test_limiar_do_gosto_por_cima():
    vida = mesclar(VIDA_PADRAO, {"momentos": {"tedio_sem_musica_s": 1200}})
    assert m.bruto({"sem_musica_ha_s": 900, "vida": vida}) == M.A_TOA
    assert m.bruto({"sem_musica_ha_s": 1200, "vida": vida}) == M.TEDIO


@pytest.mark.parametrize(
    ("hora", "madrugada"), [(21, False), (22, True), (0, True), (3, True), (4, False), (12, False)]
)
def test_filtro_madrugada(hora, madrugada):
    assert (Filtro.MADRUGADA in m.filtros({"hora": hora})) is madrugada


@pytest.mark.parametrize(("hp", "mal"), [(0, True), (1, True), (2, False), (4, False), (None, False)])
def test_filtro_pedro_mal(hp, mal):
    assert (Filtro.PEDRO_MAL in m.filtros({"humor_pedro": hp})) is mal


def test_media_min_do_vida():
    assert m.MEDIA_MIN[M.CURTINDO] == 3.5
    assert m.media_min(M.CONVERSA) is None
    vida = mesclar(VIDA_PADRAO, {"passiva_media_min": {"curtindo": 2}})
    assert m.media_min(M.CURTINDO, vida) == 2.0
    assert set(m.GRUPOS) == set(Momento)
    assert m.GRUPOS[M.CONVERSA] == () and m.GRUPOS[M.ALERTA] == ()


def test_cabeca_ritmo_so_com_nota_1():
    assert "cabeca_ritmo" not in m.passivas(M.JOGANDO, {"musica_nota": 0})
    assert "cabeca_ritmo" in m.passivas(M.JOGANDO, {"musica_nota": 1})
    assert "cabeca_ritmo" not in m.passivas(M.OUVINDO, {"musica_nota": 0})
    assert "cabeca_ritmo" in m.passivas(M.OUVINDO, {"musica_nota": 0, "dancante": True})


def test_franja_uma_por_espera_e_por_faixa():
    assert "soprando_franja" in m.passivas(M.ESPERANDO, {})
    assert "soprando_franja" not in m.passivas(M.ESPERANDO, {"franja_na_espera": 1})
    assert "soprando_franja" not in m.passivas(M.ATURANDO, {"musica_nota": -1, "franja_na_faixa": 1})
    assert "soprando_franja" not in m.passivas(M.TRABALHANDO_JUNTO, {})
    assert "soprando_franja" in m.passivas(M.TRABALHANDO_JUNTO, {"claude_demorando": True})
    assert "cantando_junto" not in m.passivas(M.CURTINDO, {"musica_nota": 1, "cantando_na_faixa": 1})


def test_p10_depois_de_2_min():
    assert "mao_no_queixo" not in m.passivas(M.ESTUDANDO, {"momento_ha_s": 60})
    assert "mao_no_queixo" in m.passivas(M.ESTUDANDO, {"momento_ha_s": 120})


def test_ociosa_feliz():
    assert "sorriso_canto" not in m.passivas(M.A_TOA, {"animo": 0.3})
    feliz = m.passivas(M.A_TOA, {"animo": 0.4})
    assert "sorriso_canto" in feliz and "rindo_sozinha" not in feliz
    assert {"sorriso_canto", "rindo_sozinha"} <= set(m.passivas(M.A_TOA, {"animo": 0.6}))


def test_pedro_sumiu_bocejo_e_cochilo():
    base = {"pedro_inativo_s": 900, "energia": 0.5}
    assert not {"bocejo", "cochilo"} & set(m.passivas(M.PEDRO_SUMIU, base))
    assert "bocejo" in m.passivas(M.PEDRO_SUMIU, {**base, "energia": 0.35})
    cansada = {"pedro_inativo_s": 1800, "energia": 0.2}
    assert "cochilo" in m.passivas(M.PEDRO_SUMIU, cansada)
    assert "cochilo" not in m.passivas(M.PEDRO_SUMIU, {**cansada, "musica_nota": 1})
    assert "cantarolando" not in m.passivas(M.PEDRO_SUMIU, {**cansada, "musica_nota": 0})


@pytest.mark.parametrize(
    ("ctx", "degrau"),
    [
        ({"momento_ha_s": 600}, None),
        ({"momento_ha_s": 900}, "encarando"),
        ({"momento_ha_s": 1000, "encarando_feito": True}, None),
        ({"momento_ha_s": 1800, "encarando_feito": True}, "ei_to_aqui"),
        ({"momento_ha_s": 2400, "encarando_feito": True, "ei_to_aqui_ha_s": 600}, None),
        ({"momento_ha_s": 4000, "encarando_feito": True, "ei_to_aqui_ha_s": 1800}, "ei_to_aqui"),
        ({"momento_ha_s": 2400, "encarando_feito": True, "ei_ignorado": True}, "beicinho"),
    ],
)
def test_escada_do_tedio(ctx, degrau):
    assert m.escada_tedio(ctx) == degrau
    escada = {"encarando", "ei_to_aqui", "beicinho"} & set(m.passivas(M.TEDIO, ctx))
    assert escada == ({degrau} if degrau else set())


def test_filtros_tiram_zoeira_e_negativa():
    ctx = {"momento_ha_s": 2400, "encarando_feito": True, "ei_ignorado": True}
    assert "beicinho" not in m.passivas(M.TEDIO, {**ctx, "hora": 23})
    assert "flagra_no_forum" not in m.passivas(M.TEDIO, {**ctx, "hora": 23})
    assert "flagra_no_forum" in m.passivas(M.TEDIO, {**ctx, "hora": 15})
    espera = m.passivas(M.ESPERANDO, {"humor_pedro": 0})
    assert "impaciente" not in espera and "soprando_franja" not in espera


def test_sinais_do_reactor():
    s = m.sinais(
        1000.0, parado_s=30.0, ultimo_turno_pedro=900.0, ultima_musica=None, lm_on=True,
        claude_rodando=True, alerta=None, faixa_agua="ok",
    )
    assert s["pedro_inativo_s"] == 30.0 and s["turno_pedro_ha_s"] == 100.0
    assert s["sem_musica_ha_s"] == float("inf") and s["faixa_agua"] == "ok"
    assert m.bruto(s) == M.CONVERSA
    s = m.sinais(1000.0, parado_s=None, ultimo_turno_pedro=None, ultima_musica=100.0)
    assert s["sem_musica_ha_s"] == 900.0 and s["turno_pedro_ha_s"] is None
    assert m.bruto(s) == M.TEDIO
    tocando = m.sinais(1000.0, parado_s=0, ultimo_turno_pedro=None, ultima_musica=1.0, musica_nota=0)
    assert tocando["sem_musica_ha_s"] == 0.0
