"""V0.6: episódio de jogo (spec §7, acordo §5) e o det_sistema usando-o (CA-V7)."""

from __future__ import annotations

from hud.wired.main_screen import Snapshot
from hud.wired.reacoes import det_sistema
from hud.wired.reacoes.episodio import Episodio

COBRANCA = {("hot", None), ("fps_drop", None), ("eu_avisei", None), ("fps_drop", "vergonha")}
RECUPERACAO = {("hot", "alivio"), ("fps_drop", "recuperou")}


def test_fps_e_calor_sao_um_episodio_com_fim_de_3_min_e_novo_so_apos_10():
    ep = Episodio()
    assert ep.atualizar({"quente": True}, 0) == "inicio"
    assert ep.atualizar({"fps_baixo": True}, 30) is None  # mesmo episódio
    assert ep.atualizar({}, 40) is None
    assert ep.atualizar({}, 40 + 179) is None
    assert ep.atualizar({}, 40 + 180) == "fim"
    assert ep.atualizar({"quente": True}, 400) is None  # < 10 min do fim: reabre, não é novo
    ep.atualizar({}, 410)
    ep.atualizar({}, 600)
    assert ep.atualizar({"fps_baixo": True}, 600 + 601) == "inicio"


def test_primeiro_episodio_vira_cena_os_seguintes_viram_estado():
    ep = Episodio()
    ep.game_on(0)
    ep.atualizar({"quente": True}, 0)
    assert not ep.estado
    assert ep.pode_emitir("hot", 0)
    assert not ep.pode_emitir("fps_drop", 5)  # repetido no episódio
    assert ep.estado
    ep.atualizar({}, 10)
    ep.atualizar({}, 200)  # fim
    ep.atualizar({"fps_baixo": True}, 900)  # episódio novo
    assert ep.estado and not ep.pode_emitir("fps_drop", 900)


def test_tetos_por_partida_e_numeros_do_vida():
    ep = Episodio({"jogo": {"cobrancas_partida": 1, "recuperacoes_partida": 2}})
    assert ep.pode_emitir("eu_avisei", 0)
    assert not ep.pode_emitir("fps_drop:vergonha", 1)
    assert ep.pode_emitir("hot:alivio", 2) and ep.pode_emitir("fps_drop:recuperou", 3)
    assert not ep.pode_emitir("hot:alivio", 4)
    assert ep.pode_emitir("sem_tropeco", 5)  # fora dos tetos
    ep.game_on(10)
    assert ep.pode_emitir("eu_avisei", 11)


def test_relatorio_pos_batalha():
    ep = Episodio()
    ep.game_on(0)
    assert ep.game_off(100) == "vitoria"
    ep.game_on(200)
    ep.atualizar({"fps_baixo": True}, 210)
    assert ep.game_off(300) == "eu_avisei"
    ep.game_on(400)
    ep.atualizar({"quente": True}, 410)
    assert ep.game_off(500, pedro_mal=True) == "desconfiada"


def _rodar_partida(pedro_mal: bool = False):
    """1 h de jogo oscilando: a cada 4 min o FPS cai 20 s e a temperatura passa de 85 °C."""
    ctx: dict = {"agora": 0.0, "pedro_mal": pedro_mal}
    base = {"net_ip": "192.168.0.2", "cpu": 10.0, "ram": 40.0}
    ant, emitidos = None, []

    def tick(t: float, **campos):
        nonlocal ant
        snap = Snapshot(**(base | campos))
        ctx["agora"] = t
        era_quente = bool(ctx.get("_sistema_quente"))
        out = det_sistema.detectar(ant, snap, ctx)
        ant = snap
        cala = ctx["_sistema_cala"]
        if ctx["_sistema_quente"] and not era_quente and "hot" not in cala:  # 34 pelo fire antigo
            emitidos.append(("hot", None))
        if ctx.get("_sistema_fps_baixo") == 2 and "fps_drop" not in cala:  # 36 pelo fire antigo
            emitidos.append(("fps_drop", None))
        emitidos.extend((d.chave, d.variante) for d in out)
        return out

    tick(0.0)
    t = 1.0
    while t <= 3600:
        fase = t % 240
        ruim = fase < 20
        quente = 60 <= fase < 120
        tick(t, gaming=True, fps=30.0 if ruim else 100.0, fps_avg=100.0,
             cpu_temp=90.0 if quente else 70.0)
        t += 5
    fim = tick(3601.0, gaming=False)
    cala_final = ctx["_sistema_cala"]
    return emitidos, fim, cala_final


def test_CA_V7_uma_hora_oscilando():
    emitidos, fim, cala = _rodar_partida()
    partida = emitidos[: len(emitidos) - len(fim)]
    assert sum(e in COBRANCA for e in partida) <= 2
    assert sum(e in RECUPERACAO for e in partida) <= 1
    assert sum(e in COBRANCA for e in partida) >= 1  # o 1º episódio vira cena
    assert [(d.chave, d.motivo) for d in fim] == [("eu_avisei", "relatório pós-batalha")]
    assert "game_off" in cala


def test_CA_V7_relatorio_com_pedro_mal_e_desconfiada():
    _, fim, _ = _rodar_partida(pedro_mal=True)
    assert [d.chave for d in fim] == ["desconfiada"]


def test_partida_limpa_deixa_o_game_off_antigo_como_vitoria():
    ctx: dict = {"agora": 0.0}
    base = {"net_ip": "192.168.0.2", "cpu": 10.0, "ram": 40.0}
    det_sistema.detectar(None, Snapshot(**base), ctx)
    jogo = base | {"gaming": True, "fps": 100.0, "fps_avg": 100.0}
    for t in range(1, 600, 10):
        ctx["agora"] = float(t)
        det_sistema.detectar(None, Snapshot(**jogo), ctx)
    ctx["agora"] = 700.0
    out = det_sistema.detectar(None, Snapshot(**base), ctx)
    assert out == [] and "game_off" not in ctx["_sistema_cala"]
