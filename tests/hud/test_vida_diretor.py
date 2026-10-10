"""Diretor de cenas (V0.10): spec §8, acordo §4–§5, CA-V4."""

from __future__ import annotations

import random

import pytest
from wired.reacoes import catalogo
from wired.reacoes.contratos import Disparo
from wired.reacoes.diretor import Diretor
from wired.reacoes.estado import Estado
from wired.reacoes.governador import Tipo
from wired.reacoes.vida import Fone, Momento

T0 = 1_791_590_700.0

# Rajada real das 21:05 (~/.local/state/magi/reacoes.jsonl, 2026-10-09T21:05:08–21:06:23), sem as
# passivas (que vêm do sorteio, não de disparo): (t, chave, motivo).
RAJADA_2105 = (
    (1791590708.406323, "hud_acordou", "primeiro snapshot"),
    (1791590708.4544415, "hud_acordou", "primeiro snapshot"),
    (1791590711.044219, "music_love", "antiga"),
    (1791590715.0184014, "music_love", "antiga"),
    (1791590723.015966, "music_love", "antiga"),
    (1791590733.7961535, "ideia", "HEAD f4a54b5 → c517d66"),
    (1791590738.0142705, "piscadinha", "agora_sim"),
    (1791590764.0419192, "cantando_junto", "cantando"),
    (1791590783.0188124, "refrao", "sem_pulo_60s"),
)


def _dir(**kw) -> Diretor:
    return Diretor(Estado(), rng=random.Random(1), **kw)


def _rodar(d: Diretor, eventos, ate: float, ctx: dict | None = None, passo: float = 0.5):
    """Replay: ticks de ``passo`` s; devolve (cenas, atenções)."""
    eventos = sorted(eventos, key=lambda e: e[0])
    t = eventos[0][0] if eventos else T0
    i, cenas, atencoes = 0, [], []
    while t <= ate:
        lote = []
        while i < len(eventos) and eventos[i][0] <= t:
            ev = eventos[i]
            lote.append(Disparo(ev[1], ev[2], *(ev[3:4] or (None,)), fmt=ev[4] if len(ev) > 4 else {}))
            i += 1
        if lote:
            d.receber(lote, t, ctx)
        if (c := d.proxima(t, ctx)) is not None:
            cenas.append((t, c))
        while (a := d.atencao(t)) is not None:
            atencoes.append((t, a))
        t += passo
    return cenas, atencoes


def _ev(dt, chave, variante=None, **fmt):
    return (T0 + dt, chave, "teste", variante, fmt)


def _cenas_gov(d: Diretor) -> int:
    return sum(1 for h in d.gov.hist if h[1] == Tipo.CENA)


# -- CA-V4 --------------------------------------------------------------------------------------------
def test_ca_v4_rajada_real_2105_vira_uma_cena():
    d = _dir()
    cenas, atencoes = _rodar(d, RAJADA_2105, RAJADA_2105[-1][0] + 5)
    assert _cenas_gov(d) == 1  # uma CENA só
    assert cenas[0][1].tipo == "musica_comecou" and cenas[0][1].ramo == "2"
    # nenhuma outra reação de música se expressou; o commit (outra causa) só depois dos 25 s
    assert all(c.tipo == "ideia" for _, c in cenas[1:])
    assert all(t - cenas[0][0] >= 25 for t, _ in cenas[1:])
    assert not any(h[1] == Tipo.ATIVA_SOLTA and h[3] == "musica" for h in d.gov.hist)
    assert {a for _, a in atencoes} >= {"player"}  # o resto virou atenção dirigida
    assert d.estado.postura.fone == Fone.CABECA
    assert 400 <= d.atencao_ms <= 600


# -- regras do §4 ---------------------------------------------------------------------------------------
def test_coalescencia_3s_mesma_causa_uma_cena():
    d = _dir()
    evs = [_ev(0, "musica_comecou", causa="faixa:x", nota=1), _ev(1, "music_like", causa="faixa:x"),
           _ev(2.5, "music_love", causa="faixa:x")]
    cenas, _ = _rodar(d, evs, T0 + 10)
    assert len(cenas) == 1 and cenas[0][0] >= T0 + 3  # esperou a janela


def test_familia_absorvida_vira_atencao():
    d = _dir()
    evs = [_ev(0, "jogo_abriu"), _ev(28, "episodio", primeiro=True)]
    cenas, atencoes = _rodar(d, evs, T0 + 40)
    assert [c.tipo for _, c in cenas] == ["jogo_abriu"]
    assert any(a == "fps" for _, a in atencoes)
    cenas2, _ = _rodar(d, [_ev(70, "episodio", primeiro=True)], T0 + 80)
    assert [c.tipo for _, c in cenas2] == ["episodio"]  # passou dos 30 s da família


def test_de_novo_mesma_causa_em_menos_de_10_min():
    d = _dir()
    cenas, _ = _rodar(d, [_ev(0, "claude_terminou", dur_s=600, causa="claude:sessao")], T0 + 5)
    cenas2, _ = _rodar(d, [_ev(120, "claude_terminou", dur_s=600, causa="claude:sessao")], T0 + 130)
    assert cenas[0][1].tipo == "claude_terminou"
    assert cenas2[0][1].tipo == "de_novo"
    assert [(p.eyes, p.mouth, p.ms) for p in cenas2[0][1].passos] == [("B7", "C12", 1000)]


def test_claude_rapido_so_atencao():
    d = _dir()
    cenas, atencoes = _rodar(d, [_ev(0, "claude_terminou", dur_s=60)], T0 + 5)
    assert cenas == [] and [a for _, a in atencoes] == ["claude"]


def test_suprimido_em_jogo_vira_atencao():
    d = _dir()
    ctx = {"momento": Momento.JOGANDO}
    cenas, atencoes = _rodar(d, [_ev(0, "musica_comecou", nota=2)], T0 + 5, ctx)
    assert cenas == [] and [a for _, a in atencoes] == ["player"]


def test_fila_uma_vaga_e_obsolescencia():
    d = _dir()
    evs = [_ev(0, "jogo_abriu"), _ev(5, "musica_comecou", nota=1, causa="a"),
           _ev(6, "claude_terminou", dur_s=900, causa="c")]
    cenas, _ = _rodar(d, evs, T0 + 40)
    tipos = [c.tipo for _, c in cenas]
    assert tipos[0] == "jogo_abriu"
    assert d.fila is None
    # a música (nível 2) entrou na fila e tocou depois dos 25 s; o Claude (nível 3) foi absorvido
    assert tipos == ["jogo_abriu", "musica_comecou"]
    assert cenas[1][0] - cenas[0][0] >= 25
    d2 = _dir()
    _rodar(d2, [_ev(0, "jogo_abriu"), _ev(5, "musica_comecou", nota=1)], T0 + 9)
    assert d2.fila is not None
    d2.fila = (d2.fila[0], T0 - 100)  # passou de 30 s na fila: descartada
    assert d2.proxima(T0 + 30) is None and d2.fila is None


def test_interrupcao_nivel1_sai_por_b1c1_e_nao_recomeca():
    d = _dir()
    d.estado.postura.fone = Fone.PESCOCO
    cenas, _ = _rodar(d, [_ev(0, "musica_comecou", nota=2), _ev(4.5, "pedro_fala")], T0 + 30)
    assert [c.tipo for _, c in cenas] == ["musica_comecou", "pedro_fala"]
    fala = cenas[1][1]
    assert fala.ramo == "com_fone" and fala.nivel == 1
    assert (fala.passos[0].eyes, fala.passos[0].mouth, fala.passos[0].ms) == ("B1", "C1", 200)
    assert d.estado.postura.fone == Fone.PESCOCO  # troca atômica: a cena inteira manda
    assert cenas[1][0] - cenas[0][0] < 3  # nível 1 não espera a coalescência


def test_pedro_fala_recoloca_fone_10s_depois_com_musica():
    d = _dir()
    d.estado.postura.fone = Fone.CABECA
    ctx = {"musica": True}
    cenas, _ = _rodar(d, [_ev(0, "pedro_fala"), _ev(20, "resposta_fim")], T0 + 40, ctx)
    assert [c.tipo for _, c in cenas] == ["pedro_fala", "recoloca_fone"]
    assert cenas[1][0] - (T0 + 20) >= 10
    assert d.estado.postura.fone == Fone.CABECA


def test_sortear_passiva_por_peso_e_negativa_com_causa():
    d = _dir()
    contagem = {"respirar": 0, "suspiro": 0}
    for i in range(200):
        d2 = _dir()
        d2.rng = random.Random(i)
        k = d2.sortear_passiva(["respirar", "suspiro"], T0)
        assert k == "respirar"  # suspiro sem causa nunca
        contagem[k] += 1
    k = d.sortear_passiva(["respirar"], T0)
    assert k == "respirar" and d.gov.peso("respirar", T0 + 1) == pytest.approx(0.3)
    d.causas["faixa_nota_menos1"] = T0 + 100
    ok = d.sortear_passiva(["suspiro"], T0 + 100)
    assert ok == "suspiro"
    d3 = _dir()
    d3.causas["faixa_nota_menos1"] = T0
    assert d3.sortear_passiva(["suspiro"], T0, {"filtros": ("pedro_mal",)}) is None


# -- uma por cena do §5 ---------------------------------------------------------------------------------
@pytest.mark.parametrize(("nota", "ado", "ramo", "olhos"), [
    (2, False, "2", "B5"), (2, True, "2_ado", "B16"), (1, False, "1", "B2"), (0, False, "0", "B1"),
])
def test_musica_comecou_climax_pela_nota(nota, ado, ramo, olhos):
    d = _dir()
    cenas, _ = _rodar(d, [_ev(0, "musica_comecou", nota=nota, ado=ado)], T0 + 5)
    c = cenas[0][1]
    assert (c.tipo, c.ramo) == ("musica_comecou", ramo)
    assert c.passos[0].look == "player" and "fone_on" in c.passos[1].corpo
    assert c.passos[-1].eyes == olhos
    assert "blush" not in c.passos[-1].efeitos


def test_musica_menos1_poe_fone_da_chance_e_tira():
    d = _dir(cfg={"musica_nota_menos1_chance_s": 8})
    cenas, _ = _rodar(d, [_ev(0, "music_meh")], T0 + 5)
    c = cenas[0][1]
    assert c.ramo == "-1" and c.passos[1].ms == 8000 and "fone_on" in c.passos[1].corpo
    assert "fone_off" in c.passos[-1].corpo and d.estado.postura.fone == Fone.PESCOCO
    assert "faixa_nota_menos1" in d.causas


def test_musica_menos2_nem_coloca():
    d = _dir()
    cenas, _ = _rodar(d, [_ev(0, "music_hate")], T0 + 5)
    c = cenas[0][1]
    assert c.ramo == "-2" and not any("fone_on" in p.corpo for p in c.passos)
    assert "braco:P13" in c.passos[-1].corpo


def test_faixa_trocou_so_climax():
    d = _dir()
    d.estado.postura.fone = Fone.CABECA
    cenas, _ = _rodar(d, [_ev(0, "music_love")], T0 + 5)
    c = cenas[0][1]
    assert c.tipo == "faixa_trocou" and len(c.passos) == 1 and c.passos[0].eyes == "B5"


def test_pulos_tres_seguidos_uma_cena():
    d = _dir()
    evs = [_ev(0, "pulo", tocou_s=10, causa="p1"), _ev(10, "pulo", tocou_s=5, causa="p2"),
           _ev(20, "pulo", tocou_s=5, causa="p3")]
    cenas, atencoes = _rodar(d, evs, T0 + 30)
    assert [c.tipo for _, c in cenas] == ["impaciente"]
    assert len(atencoes) >= 1


def test_musica_parou_tira_fone_e_olha_pedro():
    d = _dir()
    d.estado.postura.fone = Fone.CABECA
    cenas, _ = _rodar(d, [_ev(0, "musica_parou")], T0 + 5)
    c = cenas[0][1]
    assert "fone_off" in c.passos[0].corpo and c.passos[0].ms == 1000
    assert d.estado.postura.fone == Fone.PESCOCO


def test_jogo_abriu_cockpit():
    d = _dir()
    cenas, _ = _rodar(d, [_ev(0, "game_on")], T0 + 5)
    c = cenas[0][1]
    assert c.tipo == "jogo_abriu" and catalogo.CENAS[("jogo_abriu", None)].mood == "focus"
    assert (c.passos[0].eyes, c.passos[0].mouth, c.passos[0].ms) == ("B1", "C10", 800)


def test_episodio_primeiro_cena_depois_estado():
    d = _dir()
    cenas, _ = _rodar(d, [_ev(0, "hot", primeiro=True)], T0 + 5)
    assert cenas[0][1].tipo == "episodio" and "episodio_jogo" in d.causas
    cenas2, atencoes = _rodar(d, [_ev(200, "fps_drop", primeiro=False)], T0 + 210)
    assert cenas2 == [] and [a for _, a in atencoes] == ["fps"]


@pytest.mark.parametrize(("fmt", "ramo"), [
    ({}, "limpo"), ({"episodios": 2}, "episodios"), ({"episodios": 1, "pedro_mal": True}, "pedro_mal"),
])
def test_jogo_fechou_relatorio(fmt, ramo):
    d = _dir()
    cenas, _ = _rodar(d, [_ev(0, "game_off", **fmt)], T0 + 5)
    assert (cenas[0][1].tipo, cenas[0][1].ramo) == ("jogo_fechou", ramo)


@pytest.mark.parametrize(("cochilou", "ramo", "olhos"),
                         [(True, "cochilou", "B9"), (False, "orgulhosa", "F1")])
def test_pedro_voltou_corta_e_escolhe_ramo(cochilou, ramo, olhos):
    d = _dir()
    evs = [_ev(0, "musica_comecou", nota=2), _ev(4.5, "pedro_voltou", cochilou=cochilou)]
    cenas, _ = _rodar(d, evs, T0 + 10)
    c = cenas[-1][1]
    assert (c.tipo, c.ramo, c.nivel) == ("pedro_voltou", ramo, 1)
    assert c.passos[1].eyes == olhos  # passos[0] é a saída B1 C1 200
    if not cochilou:
        assert [(p.eyes, p.mouth) for p in c.passos[-2:]] == [("B1", "C10"), ("B4", "C5")]


def test_claude_terminou_longo_brilho():
    d = _dir()
    cenas, _ = _rodar(d, [_ev(0, "claude", dur_s=400)], T0 + 5)
    c = cenas[0][1]
    assert c.tipo == "claude_terminou" and "sparkle" in c.passos[-1].efeitos


def test_truque_de_salao_aplauso_e_ignorado():
    ctx = {"momento": Momento.A_TOA, "inatividade_s": 10}
    d = _dir()
    assert d.truque(T0, {"momento": Momento.JOGANDO, "inatividade_s": 10}) is None
    assert d.truque(T0, {"momento": Momento.A_TOA, "inatividade_s": 120}) is None
    antes = d.estado.humor.animo
    assert d.truque(T0, ctx).tipo == "truque"
    assert d.clique(T0 + 5) is True and d.estado.humor.animo > antes
    assert d.truque(T0 + 3600, ctx) is None  # ≤ 1/dia
    d2 = _dir()
    d2.truque(T0, ctx)
    assert d2.proxima(T0 + 5) is None
    c = d2.proxima(T0 + 11)
    assert (c.tipo, c.ramo) == ("truque", "ignorado") and "truque_ignorado" in d2.causas


def test_roteiros_validos():
    for (tipo, _ramo), d in catalogo.CENAS.items():
        assert 1 <= len(d.passos) <= 4, tipo
        for p in d.passos:
            assert p.ms > 0 and (p.eyes is None or p.eyes[0] in "BF")
            assert p.look is None or p.look in {"player", "fps", "claude", "radio", "net", "magi"}
