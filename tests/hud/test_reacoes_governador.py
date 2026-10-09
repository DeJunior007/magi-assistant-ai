"""Governador e registro das reações (R0.2): uma linha do spec §3 por teste, CA-03 e CA-07."""

from __future__ import annotations

import json
import random

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


def test_passiva_intervalo_40s():
    a, b = mk("a", C.PASSIVA), mk("b", C.PASSIVA)
    ctx = ctx_de(a, b)
    assert esc(ctx, T0, "a") == "a"
    assert esc(ctx, T0 + 39, "b") is None
    assert esc(ctx, T0 + 40, "b") == "b"


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
            assert all(t - t2 >= 40 for t2, d2, _ in antes if C.PASSIVA in d2.classes)
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
