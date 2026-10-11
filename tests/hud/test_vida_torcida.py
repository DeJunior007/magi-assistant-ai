"""Piso da ``torcida`` (V1.6, acordo placar-e-jogo §1)."""

from __future__ import annotations

import random

from hud.wired.reacoes.governador import Governador, Pedido, Tipo
from hud.wired.reacoes.torcida import VARIANTES, Torcida
from hud.wired.reacoes.vida import Momento

J = Momento.JOGANDO
MIN = 60.0


def novo(t0=0.0):
    t = Torcida()
    t.atualizar(t0, jogo=True, presente=True)
    return t, Governador()


def test_30_min_forca_o_slot_e_antes_nao():
    t, gv = novo()
    assert t.no_slot(29 * MIN, J, gv) is None
    e = t.no_slot(30 * MIN, J, gv)
    assert e is not None and not e.fora_de_slot
    assert e.causa == "jogando_sem_positiva:30"
    assert e.delta_animo == 0.03


def test_45_min_fura_o_slot_e_antes_nao():
    t, gv = novo()
    assert t.fora_do_slot(44 * MIN, J, gv) is None
    e = t.fora_do_slot(45 * MIN, J, gv)
    assert e is not None and e.fora_de_slot and e.causa == "jogando_sem_positiva:45"


def test_so_em_jogando_e_positiva_zera():
    t, gv = novo()
    assert t.no_slot(31 * MIN, Momento.CURTINDO, gv) is None
    t.positiva(31 * MIN)
    assert t.no_slot(40 * MIN, J, gv) is None
    assert t.no_slot(61 * MIN, J, gv) is not None


def test_relogio_pausa_sem_jogo_ou_sem_pedro():
    t, gv = novo()
    t.atualizar(20 * MIN, jogo=True, presente=False)
    t.atualizar(50 * MIN, jogo=True, presente=True)
    assert t.minutos(59 * MIN) == 29.0
    assert t.no_slot(59 * MIN, J, gv) is None
    assert t.no_slot(60 * MIN, J, gv) is not None


def test_intervalo_30_min_entre_torcidas():
    t, gv = novo()
    assert t.fora_do_slot(45 * MIN, J, gv) is not None
    # relógio zerado; mesmo vencendo de novo, a 2ª só depois de 30 min da 1ª
    t2 = Torcida()
    t2.registrar(0.0, None)  # torcida do sorteio às 0
    t2.atualizar(0.0, jogo=True, presente=True)
    t2._acum = 50 * MIN  # relógio já vencido
    gv2 = Governador()
    assert t2.fora_do_slot(29 * MIN, J, gv2) is None
    assert t2.fora_do_slot(30 * MIN, J, gv2) is not None


def test_fura_respeita_25s_e_pos_cena_mas_nao_o_passiva_min():
    t, gv = novo()
    gv.registrar(Pedido(Tipo.CENA, "episodio"), 45 * MIN - 30)
    assert t.fora_do_slot(45 * MIN, J, gv) is None  # 60 s pós-cena
    gv2 = Governador()
    gv2.registrar(Pedido(Tipo.GESTO, "sacada_olhar"), 45 * MIN - 10)
    t2, _ = novo()
    assert t2.fora_do_slot(45 * MIN, J, gv2) is None  # 25 s entre expressões
    assert t2.fora_do_slot(45 * MIN + 30, J, gv2) is not None  # passiva_min não vale fora de slot


def test_ocupa_a_vaga_no_teto_nao_soma():
    t, gv = novo()
    base = 45 * MIN - 3600 + 60
    for i in range(11):
        gv.registrar(Pedido(Tipo.GESTO, f"g{i}"), base + i * 60)
    e = t.fora_do_slot(45 * MIN, J, gv)
    assert e is not None
    assert gv._na_hora(45 * MIN, Tipo.GESTO) == 12
    # teto cheio (12/h com ela): nem outra passiva nem outra torcida
    assert gv.motivo(Pedido(Tipo.GESTO, "x", fora_de_slot=True), 45 * MIN + 30) == "passivas_hora"
    t2, _ = novo()
    assert t2.fora_do_slot(45 * MIN + 30, J, gv) is None


def test_variantes_alternam():
    t = Torcida()
    gv = Governador()
    t.atualizar(0.0, jogo=True, presente=True)
    vistas = []
    agora = 0.0
    for _ in range(6):
        agora += 46 * MIN
        e = t.fora_do_slot(agora, J, gv, rng=random.Random(7))
        assert e is not None
        vistas.append(e.var)
    assert all(a != b for a, b in zip(vistas, vistas[1:], strict=False))
    assert set(vistas) == set(VARIANTES)


def test_exportar_importar():
    t, _ = novo()
    t.registrar(10 * MIN, "punho")
    d = t.exportar(20 * MIN)
    t2 = Torcida()
    t2.importar(d)
    assert t2.minutos(0) == 10.0 and t2.variante() != "punho"
