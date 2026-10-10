"""Governador e registro das reações (R0.2): uma linha do spec §3 por teste, CA-03 e CA-07."""

from __future__ import annotations

import json
import random

import pytest

from hud.wired.reacoes import governador as g
from hud.wired.reacoes import registro
from hud.wired.reacoes.contratos import Classe, Def, Disparo, Passo

C = Classe
T0 = 1_000_000.0


def mk(chave, *classes, n=1, prio=1, cooldown=600.0, mood="calm", efeitos=(), mouth=None):
    return Def(chave, n, chave, (Passo(1000, mouth=mouth, efeitos=tuple(efeitos)),),
               frozenset(classes), mood=mood, prio=prio, cooldown_s=cooldown)


def ctx_de(*defs, **kw):
    kw.setdefault("hora", 12)
    return {"defs": {d.chave: d for d in defs}, **kw}


def esc(ctx, agora, *chaves):
    d = g.escolher([Disparo(c, "teste") for c in chaves], agora, ctx)
    return d.chave if d else None


def test_passiva_intervalo_90s_do_vida():  # acordo 2026-10-10 §4: era 40 s
    a, b = mk("a", C.PASSIVA), mk("b", C.PASSIVA)
    ctx = ctx_de(a, b)
    assert esc(ctx, T0, "a") == "a"
    assert esc(ctx, T0 + 89, "b") is None
    assert esc(ctx, T0 + 90, "b") == "b"
    ctx = ctx_de(a, b, vida={"passiva_min_s": 120})  # o [vida] do Pedro por cima
    assert esc(ctx, T0, "a") == "a"
    assert esc(ctx, T0 + 90, "b") is None


def test_rara_1_por_hora():
    r = mk("r", C.PASSIVA, C.RARA)
    ctx = ctx_de(r)
    assert esc(ctx, T0, "r") == "r"
    assert esc(ctx, T0 + 3599, "r") is None
    assert esc(ctx, T0 + 3600, "r") == "r"


def test_diaria_1_por_dia():
    d = mk("d", C.PASSIVA, C.DIARIA)
    ctx = ctx_de(d)
    assert esc(ctx, T0, "d") == "d"
    assert esc(ctx, T0 + 86399, "d") is None
    assert esc(ctx, T0 + 86400, "d") == "d"


def test_cooldown_por_chave_e_variante():
    a = mk("a", C.TEMPO, cooldown=180)
    ctx = ctx_de(a)
    ctx["defs"][("a", "v")] = mk("a", C.TEMPO, cooldown=180)
    assert esc(ctx, T0, "a") == "a"
    assert g.escolher([Disparo("a", "x", variante="v")], T0 + 179, ctx) is None
    assert g.escolher([Disparo("a", "x", variante="v")], T0 + 180, ctx) is not None


def test_teto_8_ativas_por_hora_e_sistema_fura():
    defs = [mk(f"a{i}", C.TEMPO) for i in range(9)] + [mk("s", C.SISTEMA), mk("v", C.VOLTA)]
    ctx = ctx_de(*defs)
    for i in range(8):
        assert esc(ctx, T0 + i, f"a{i}") == f"a{i}"
    assert esc(ctx, T0 + 10, "a8") is None
    assert esc(ctx, T0 + 11, "s") == "s"
    assert esc(ctx, T0 + 12, "v") == "v"
    assert esc(ctx, T0 + 3600, "a8") == "a8"


def test_prioridade_no_mesmo_tick():
    s, p, m, t, pa = (mk("s", C.SISTEMA), mk("p", C.PEDRO), mk("m", C.MUSICA),
                      mk("t", C.TEMPO), mk("pa", C.PASSIVA))
    assert esc(ctx_de(s, p, m, t, pa), T0, "pa", "t", "m", "p", "s") == "s"
    assert esc(ctx_de(p, m, t, pa), T0, "pa", "t", "m", "p") == "p"
    assert esc(ctx_de(m, t, pa), T0, "pa", "t", "m") == "m"
    assert esc(ctx_de(t, pa), T0, "pa", "t") == "t"
    baixo, alto = mk("baixo", C.TEMPO, prio=1), mk("alto", C.TEMPO, prio=3)
    assert esc(ctx_de(baixo, alto), T0, "baixo", "alto") == "alto"


def test_fila_1_slot_30s_so_volta_e_vitoria():
    v, t = mk("v", C.PEDRO, C.VOLTA), mk("t", C.TEMPO)
    ctx = ctx_de(v, t, parada=False)
    assert esc(ctx, T0, "v", "t") is None
    ctx["parada"] = True
    assert esc(ctx, T0 + 30) == "v"
    assert esc(ctx, T0 + 31) is None  # a fila esvaziou; "t" não entrou nela
    ctx2 = ctx_de(v, parada=False)
    esc(ctx2, T0, "v")
    ctx2["parada"] = True
    assert esc(ctx2, T0 + 31) is None  # venceu


def test_blush_1_por_hora_e_livres():
    a = mk("a", C.TEMPO, efeitos=("blush",))
    b = mk("b", C.TEMPO, efeitos=("blush",))
    livre = mk("l", C.TEMPO, n=74, efeitos=("blush",))
    ctx = ctx_de(a, b, livre)
    assert esc(ctx, T0, "a") == "a"
    assert esc(ctx, T0 + 1, "b") is None
    assert esc(ctx, T0 + 2, "l") == "l"
    assert esc(ctx, T0 + 3600, "b") == "b"


def test_lagrima_so_de_noite_e_1_por_dia():
    a = Def("a", 29, "a", (Passo(500, efeitos=("tear", "zz")),), frozenset({C.TEMPO}),
            cooldown_s=0)
    ctx = ctx_de(a, hora=12)
    d = g.escolher([Disparo("a", "x")], T0, ctx)
    assert d is not None and g.aplicar_bloqueios(d, ctx)[0].efeitos == ("zz",)
    ctx["hora"] = 23
    d = g.escolher([Disparo("a", "x")], T0 + 10, ctx)
    assert g.aplicar_bloqueios(d, ctx)[0].efeitos == ("tear", "zz")
    d = g.escolher([Disparo("a", "x")], T0 + 20, ctx)
    assert d is not None and g.aplicar_bloqueios(d, ctx)[0].efeitos == ("zz",)


def test_zoeira_barrada_humor_baixo_ou_noite():
    z = mk("z", C.PEDRO, C.ZOEIRA)
    assert esc(ctx_de(z, humor=3), T0, "z") == "z"
    assert esc(ctx_de(z, humor=1), T0, "z") is None
    assert esc(ctx_de(z, hora=23), T0, "z") is None
    assert esc(ctx_de(z, hora=4), T0, "z") is None


def test_cobranca_troca_boca():
    c = Def("c", 34, "c", (Passo(100, mouth="C8"), Passo(100, mouth="C11"),
                           Passo(100, mouth="C3")), frozenset({C.PEDRO, C.COBRANCA}))
    bocas = lambda ctx: [p.mouth for p in g.aplicar_bloqueios(c, ctx)]  # noqa: E731
    assert bocas({"hora": 12, "humor": 3}) == ["C8", "C11", "C3"]
    assert bocas({"hora": 12, "humor": 1}) == ["C9", "C9", "C3"]
    assert bocas({"hora": 2, "humor": 4}) == ["C9", "C9", "C3"]


def test_sono_barrada():
    s = mk("s", C.TEMPO, C.SONO)
    assert esc(ctx_de(s), T0, "s") == "s"
    assert esc(ctx_de(s, jogo=True), T0, "s") is None
    assert esc(ctx_de(s, claude=True), T0, "s") is None
    assert esc(ctx_de(s, musica_nota=1), T0, "s") is None


def test_rara_barrada_com_jogo():
    r = mk("r", C.PASSIVA, C.RARA)
    assert esc(ctx_de(r, jogo=True), T0, "r") is None


def test_ado_sem_blush_nem_love():
    b = mk("b", C.MUSICA, efeitos=("blush",))
    lv = mk("lv", C.MUSICA, mood="love")
    livre = mk("l", C.MUSICA, n=62, efeitos=("blush",))
    ok = mk("ok", C.MUSICA)
    ctx = ctx_de(b, lv, livre, ok, ado=True)
    assert esc(ctx, T0, "b") is None
    assert esc(ctx, T0, "lv") is None
    assert esc(ctx, T0, "l") is None
    assert esc(ctx, T0, "ok") == "ok"


def test_desligadas_do_pedro():
    s = mk("s", C.SISTEMA)
    assert esc(ctx_de(s, desligadas=["s"]), T0, "s") is None


def _catalogo():
    rng = random.Random(7)
    defs, n = [], 0
    for cls in ([C.PASSIVA], [C.PASSIVA, C.RARA], [C.PASSIVA, C.DIARIA], [C.TEMPO],
                [C.MUSICA], [C.PEDRO], [C.SISTEMA], [C.PEDRO, C.VOLTA], [C.PEDRO, C.VITORIA],
                [C.PEDRO, C.ZOEIRA], [C.TEMPO, C.SONO], [C.PEDRO, C.COBRANCA]):
        for _ in range(3):
            n += 1
            ef = rng.choice([(), ("blush",), ("tear",), ("sweat",)])
            num = rng.choice([n, n, 74]) if "blush" in ef else n
            defs.append(Def(f"k{n}", num, f"k{n}", (Passo(800, mouth="C8", efeitos=ef),),
                            frozenset(cls), mood=rng.choice(["calm", "love"]),
                            prio=rng.randint(1, 3), cooldown_s=rng.choice([3.0, 180.0, 600.0])))
    return defs


def test_ca03_24h_simuladas_sem_violar_regras():
    defs = _catalogo()
    rng = random.Random(42)
    ctx = {"defs": {d.chave: d for d in defs}}
    toques = []
    for s in range(0, 86400, 2):
        agora = T0 + s
        hora = (s // 3600) % 24
        ctx.update(hora=hora, humor=rng.randint(0, 5), jogo=rng.random() < 0.2,
                   claude=rng.random() < 0.2, musica_nota=rng.choice([0, 0, 1]),
                   ado=rng.random() < 0.2, parada=rng.random() < 0.9, desligadas=["k1"])
        disp = [Disparo(rng.choice(defs).chave, "sim") for _ in range(rng.randint(0, 3))]
        d = g.escolher(disp, agora, ctx)
        if d is None:
            continue
        passos = g.aplicar_bloqueios(d, ctx)
        toques.append((agora, d, dict(ctx), passos))

    assert len(toques) > 100
    for i, (t, d, c, passos) in enumerate(toques):
        antes = [(t2, d2, p2) for t2, d2, _, p2 in toques[:i]]
        hora_ = [(t2, d2) for t2, d2, _ in antes if t - t2 < 3600]
        assert d.chave != "k1"
        if C.PASSIVA in d.classes:
            assert all(t - t2 >= 90 for t2, d2, _ in antes if C.PASSIVA in d2.classes)
        else:
            assert all(t - t2 >= d.cooldown_s for t2, d2, _ in antes if d2.chave == d.chave)
            if not g.furou_cota(d):
                assert sum(1 for _, d2 in hora_ if C.PASSIVA not in d2.classes
                           and not g.furou_cota(d2)) < 8
        if C.RARA in d.classes:
            assert not c["jogo"] and all(d2.chave != d.chave for _, d2 in hora_)
        if C.DIARIA in d.classes:
            assert all(d2.chave != d.chave for _, d2, _ in antes)
        if g.tem_efeito(d, "blush") and d.n not in g.BLUSH_LIVRE:
            assert not any(g.tem_efeito(d2, "blush") and d2.n not in g.BLUSH_LIVRE
                           for _, d2 in hora_)
        if c["ado"]:
            assert not g.tem_efeito(d, "blush") and d.mood != "love"
        noite = g.noite(c["hora"])
        if C.ZOEIRA in d.classes:
            assert c["humor"] > 1 and not noite
        if C.SONO in d.classes:
            assert not (c["jogo"] or c["claude"] or c["musica_nota"] >= 1)
        if C.COBRANCA in d.classes and (c["humor"] <= 1 or noite):
            assert all(p.mouth == "C9" for p in passos)
        if any("tear" in p.efeitos for p in passos):
            assert noite
            assert not any(any("tear" in p.efeitos for p in p2) for _, _, p2 in antes)
        if not c["parada"]:
            raise AssertionError("aprovou com a Magui ocupada")


def test_ca07_registro_uma_linha_por_reacao(tmp_path):
    arq = tmp_path / "estado" / "reacoes.jsonl"
    s, t = mk("s", C.SISTEMA), mk("t", C.TEMPO)
    registro.gravar(s, Disparo("s", "disco cheio"), T0, arq)
    registro.gravar(t, Disparo("t", "meia-noite", variante="v"), T0 + 1, arq)
    linhas = [json.loads(x) for x in arq.read_text().splitlines()]
    assert [x["chave"] for x in linhas] == ["s", "t"]
    assert [x["furou_cota"] for x in linhas] == [True, False]
    assert linhas[0]["motivo"] == "disco cheio" and linhas[1]["variante"] == "v"
    assert {"t", "hora", "n"} <= linhas[0].keys()


def test_registro_gira_em_5mb(tmp_path, monkeypatch):
    arq = tmp_path / "reacoes.jsonl"
    monkeypatch.setattr(registro, "GIRO_BYTES", 200)
    t = mk("t", C.TEMPO)
    for i in range(10):
        registro.gravar(t, Disparo("t", "x" * 50), T0 + i, arq)
    assert (tmp_path / "reacoes.jsonl.1").exists()
    assert arq.stat().st_size < 400


def test_reacao_antiga_entra_no_registro(tmp_path):
    import json

    from wired.reactions import Reactor

    log = tmp_path / "r.jsonl"
    r = Reactor(clock=lambda: 1000.0, registro_file=log)
    r.fire("hot", 1.0)
    r.fire("player", 10.0)  # olhada de clique: fora do registro
    linhas = [json.loads(x) for x in log.read_text().splitlines()]
    assert [(x["chave"], x["motivo"]) for x in linhas] == [("hot", "antiga")]


# --- Governador v2 (V0.5; spec §5–§6, acordo §4) ----------------------------------------------------

T = g.Tipo
P = g.Pedido


def cena(chave="c", familia=None, **kw):
    return P(T.CENA, chave, familia=familia, **kw)


def gesto(chave="p"):
    return P(T.GESTO, chave)


def test_v2_25s_entre_expressoes():
    gv = g.Governador()
    assert gv.aprovar(P(T.ATIVA_SOLTA, "a"), T0)
    assert gv.motivo(cena(), T0 + 24) == "min_entre_expressoes"
    assert gv.aprovar(cena(), T0 + 25)


def test_v2_60s_sem_passiva_depois_de_cena():
    gv = g.Governador()
    assert gv.aprovar(cena(), T0)
    assert gv.motivo(gesto(), T0 + 59) == "pausa_apos_cena"
    assert gv.motivo(P(T.ATIVA_SOLTA, "a"), T0 + 30) is None  # a pausa é só de passiva
    assert gv.aprovar(gesto(), T0 + 60)


def test_v2_cenas_8_por_hora_janela_de_parede():
    gv = g.Governador()
    for i in range(8):
        assert gv.aprovar(cena(f"c{i}"), T0 + i * 30)
    assert gv.motivo(cena("c9"), T0 + 600) == "cenas_hora"
    assert gv.aprovar(cena("c9"), T0 + 3600)  # a primeira saiu da janela


def test_v2_passivas_90s_e_12_por_hora():
    gv = g.Governador()
    assert gv.aprovar(gesto("a"), T0)
    assert gv.motivo(gesto("b"), T0 + 89) == "passiva_min"
    for i in range(1, 12):
        assert gv.aprovar(gesto(f"g{i}"), T0 + i * 90)
    assert gv.motivo(gesto("z"), T0 + 12 * 90) == "passivas_hora"


def test_v2_mesma_passiva_peso_03_por_uso():
    gv = g.Governador()
    assert gv.peso("a", T0) == 1
    gv.aprovar(gesto("a"), T0)
    gv.aprovar(gesto("a"), T0 + 100)
    assert gv.peso("a", T0 + 200) == pytest.approx(0.09)
    assert gv.peso("b", T0 + 200) == 1
    assert gv.peso("a", T0 + 100 + 3600) == 1


def test_v2_mesmo_tipo_de_cena_absorvido_30s_musica_90s():
    gv = g.Governador()
    assert gv.aprovar(cena("x", "claude"), T0)
    assert gv.motivo(cena("y", "claude"), T0 + 29) == "mesma_familia"
    assert gv.pode(cena("y", "claude"), T0 + 30)
    assert gv.aprovar(cena("m", "musica"), T0 + 30)
    assert gv.motivo(cena("n", "musica"), T0 + 119) == "mesma_familia"
    assert gv.pode(cena("n", "musica"), T0 + 120)


@pytest.mark.parametrize("motivo", sorted(g.FURA_TUDO))
def test_v2_furam_tudo(motivo):
    gv = g.Governador()
    for i in range(8):
        gv.aprovar(cena(f"c{i}"), T0 + i * 30)
    assert gv.aprovar(cena("f", fura=motivo), T0 + 211)  # 1 s depois e com a cota cheia
    assert gv.motivo(cena("f", fura="qualquer"), T0 + 212) == "fura_desconhecido"


def test_v2_atencao_e_corpo_fora_de_cota():
    gv = g.Governador()
    assert gv.aprovar(cena(), T0)
    assert gv.aprovar(P(T.ATENCAO, "iris"), T0 + 1)
    assert gv.aprovar(P(T.CORPO, "respira"), T0 + 2)
    assert gv.aprovar(cena("d"), T0 + 25)  # a atenção não empurra o mínimo de 25 s


def test_v2_negativas_com_causa_120s_e_3_por_hora():
    gv = g.Governador()
    neg = P(T.ATIVA_SOLTA, "suspiro", negativa=True, causas=frozenset({"claude_demorando"}))
    assert gv.motivo(neg, T0, {}) == "negativa_sem_causa"
    ctx = {"causas": {"claude_demorando": T0 - 121}}
    assert gv.motivo(neg, T0, ctx) == "negativa_sem_causa"  # causa velha
    ctx = {"causas": {"pulo_faixa_amada": T0 - 10}}
    assert gv.motivo(neg, T0, ctx) == "negativa_sem_causa"  # causa de outra lista
    assert gv.motivo(neg, T0, {"causas": {"claude_demorando": T0 - 10},
                               "filtros": ["madrugada"]}) == "negativa_sob_filtro"
    for i in range(3):
        agora = T0 + i * 100
        assert gv.aprovar(neg, agora, {"causas": {"claude_demorando": agora - 5}})
    agora = T0 + 400
    assert gv.motivo(neg, agora, {"causas": {"claude_demorando": agora}}) == "negativas_hora"


def test_v2_causas_recentes():
    ctx = {"causas": {"ignorada": T0 - 120, "episodio_jogo": T0 - 121, "outra": T0}}
    assert g.causas_recentes(ctx, T0) == {"ignorada"}


def test_v2_truque_1_por_dia():
    gv = g.Governador()
    assert gv.aprovar(cena("t", truque=True), T0)
    assert gv.motivo(cena("t2", truque=True), T0 + 3600) == "truque_dia"
    assert gv.pode(cena("t2", truque=True), T0 + 86400)


def test_v2_piso_de_vida_6min():
    gv = g.Governador()
    gv.aprovar(gesto(), T0)
    assert not gv.piso_vencido(T0 + 360)
    assert gv.piso_vencido(T0 + 361)
    assert not gv.piso_vencido(T0 + 361, {"momento": "conversa"})
    assert not gv.piso_vencido(T0 + 361, {"pedro_presente": False})
    gv.aprovar(P(T.ATENCAO, "iris"), T0 + 300)
    assert not gv.piso_vencido(T0 + 600)


def test_v2_numeros_do_vida_com_o_pedro_por_cima():
    gv = g.Governador({"min_entre_expressoes_s": 40})
    gv.aprovar(cena(), T0)
    assert gv.motivo(cena("d"), T0 + 30) == "min_entre_expressoes"
    assert gv.cfg["cenas_hora"] == 8  # o resto vem do VIDA_PADRAO


def test_ca_v2_contadores_sobrevivem_ao_reinicio():
    gv = g.Governador()
    for i in range(8):
        gv.aprovar(cena(f"c{i}", "claude", truque=i == 0), T0 + i * 30)
    dados = json.loads(json.dumps(gv.exportar()))
    novo = g.Governador()
    novo.importar(dados, agora=T0 + 600)  # reiniciou 6 min depois: a janela é de parede
    assert novo.motivo(cena("x"), T0 + 600) == "cenas_hora"
    assert novo.motivo(cena("t", truque=True, fura=None), T0 + 7200) == "truque_dia"
    velho = g.Governador()
    velho.importar(dados, agora=T0 + 2 * 86400)
    assert velho.hist == []


def test_v2_24h_simuladas_sem_violacao():
    rng = random.Random(7)
    gv = g.Governador()
    ok = []
    causas = {}
    for s in range(0, 86400, 3):
        agora = T0 + s
        if rng.random() < 0.01:
            causas[rng.choice(sorted(g.CAUSAS_NEGATIVAS))] = agora
        ctx = {"causas": causas, "filtros": ["madrugada"] if rng.random() < 0.1 else []}
        tipo = rng.choice(list(T))
        p = P(tipo, rng.choice("abcd"), familia=rng.choice([None, "musica", "claude"]),
              negativa=rng.random() < 0.2, truque=rng.random() < 0.01,
              fura=rng.choice(sorted(g.FURA_TUDO)) if rng.random() < 0.005 else None)
        if gv.aprovar(p, agora, ctx):
            ok.append((agora, p, causas.copy(), ctx["filtros"]))
    assert len(ok) > 500
    v = g.VIDA_PADRAO
    for i, (t, p, cs, filtros) in enumerate(ok):
        if p.fura or p.tipo not in g.EXPRESSOES:
            continue
        antes = [(t2, p2) for t2, p2, _, _ in ok[:i] if p2.tipo != T.CORPO]
        hora = [(t2, p2) for t2, p2 in antes if t - t2 < 3600]
        expr = [t2 for t2, p2 in antes if p2.tipo in g.EXPRESSOES]
        assert not expr or t - expr[-1] >= v["min_entre_expressoes_s"]
        if p.tipo == T.CENA:
            assert sum(1 for _, p2 in hora if p2.tipo == T.CENA) < v["cenas_hora"]
        if p.tipo == T.GESTO:
            assert all(t - t2 >= v["pausa_apos_cena_s"] for t2, p2 in antes if p2.tipo == T.CENA)
            assert all(t - t2 >= v["passiva_min_s"] for t2, p2 in antes if p2.tipo == T.GESTO)
            assert sum(1 for _, p2 in hora if p2.tipo == T.GESTO) < v["passivas_hora"]
        if p.negativa:
            assert not filtros and any(0 <= t - em <= 120 for em in cs.values())
            assert sum(1 for _, p2 in hora if p2.negativa) < v["negativas_hora"]
        if p.truque:
            assert not any(p2.truque for t2, p2 in antes if t - t2 < 86400)
