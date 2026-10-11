"""V1.5: “isso foi sem sentido” (acordo-pj §4) — gravação, desfazer, fator/piso/janela, pauta."""

from __future__ import annotations

import json
import random
from collections import Counter

from wired.reacoes import passivas, sem_sentido
from wired.reacoes.sem_sentido import REACAO, SemSentido
from wired.reacoes.vida import VIDA_PADRAO, Momento

DIA = 86400.0
T0 = 1_800_000_000.0


def _alvo(chave="cabeca_ritmo", tipo="gesto", momento="jogando", t=T0 - 30, **kw) -> dict:
    return {"t": t, "hora": "x", "chave": chave, "n": 1, "variante": None, "motivo": "passiva",
            "furou_cota": False, "tipo": tipo, "momento": momento, "filtros": [], "faixa": "neutra",
            "animo": 0.1, "energia": 0.6, "causa": None, "semente": 7, **kw}


def _linhas() -> list[dict]:
    txt = sem_sentido.SEM_SENTIDO_FILE.read_text(encoding="utf-8")
    return [json.loads(x) for x in txt.splitlines()]


def test_caminho_isolado_pelo_conftest(tmp_path):
    assert str(sem_sentido.SEM_SENTIDO_FILE).startswith(str(tmp_path))


def test_grava_linha_de_origem_inteira_hora_e_gesto():
    s = SemSentido()
    alvo = _alvo()
    s.marcar(alvo, "hover", T0)
    (linha,) = _linhas()
    assert linha["alvo"] == alvo  # a linha de origem inteira
    assert linha["t"] == T0 and linha["hora"] and linha["gesto"] == "hover"


def test_sem_expressao_alvo_nenhum():
    s = SemSentido()
    s.marcar(None, "atalho", T0)
    assert _linhas()[0]["alvo"] == "nenhum"
    assert s.ajustes(T0) == 0 and s.pauta(T0) == []


def test_desfazer_em_ate_desfazer_s():
    s = SemSentido()
    alvo = _alvo()
    s.marcar(alvo, "hover", T0)
    r = s.marcar(alvo, "hover", T0 + VIDA_PADRAO["sem_sentido"]["desfazer_s"])
    assert r["desfeito"] == T0
    assert s.ajustes(T0 + 10) == 0
    assert [("desfeito" in x) for x in _linhas()] == [False, True]
    # recarregado do arquivo, continua desfeito
    assert SemSentido().ajustes(T0 + 10) == 0


def test_depois_do_prazo_marca_de_novo():
    s = SemSentido()
    alvo = _alvo()
    s.marcar(alvo, "hover", T0)
    s.marcar(alvo, "hover", T0 + 6)
    assert s.desfazer(T0 + 20) is None
    assert s.fatores(Momento.JOGANDO, T0 + 20) == {"cabeca_ritmo": 0.7 ** 2}


def test_fator_por_variante_e_momento_com_piso_e_janela():
    s = SemSentido()
    for i in range(5):
        s.marcar(_alvo(t=T0 - i), "hover", T0 + i * 10)
    s.marcar(_alvo(chave="bocejo", momento="tedio"), "atalho", T0 + 100)
    agora = T0 + 200
    assert s.fatores(Momento.JOGANDO, agora) == {"cabeca_ritmo": 0.3}  # 0,7^5 < piso
    assert s.fatores(Momento.TEDIO, agora) == {"bocejo": 0.7}
    assert s.fatores(Momento.CONVERSA, agora) == {}
    assert s.ajustes(agora) == 2
    # volta sozinho quando a marca sai da janela de 7 dias
    assert s.fatores(Momento.TEDIO, T0 + 100 + 7 * DIA) == {}
    assert s.ajustes(T0 + 7 * DIA + 200) == 0


def test_cenas_e_negativas_nao_mudam_peso_e_vao_direto_para_pauta():
    s = SemSentido(negativas=passivas.NEGATIVAS)
    s.marcar(_alvo(chave="episodio", tipo="cena"), "hover", T0)
    s.marcar(_alvo(chave="suspiro", momento="esperando", t=T0 - 1), "hover", T0 + 10)
    assert s.fatores(Momento.JOGANDO, T0 + 20) == {}
    assert s.fatores(Momento.ESPERANDO, T0 + 20) == {}
    pauta = {i["chave"]: i for i in s.pauta(T0 + 20)}
    assert set(pauta) == {"episodio", "suspiro"} and all(i["por_regra"] for i in pauta.values())


def test_pauta_por_marcas_ou_fracao():
    s = SemSentido()
    for i in range(2):
        s.marcar(_alvo(t=T0 - i), "hover", T0 + i * 10)
    agora = T0 + 100
    assert s.pauta(agora) == []
    assert s.pauta(agora, {"cabeca_ritmo": 20}) == []  # 2/20 = 10 %
    (item,) = s.pauta(agora, {"cabeca_ritmo": 10})  # 2/10 = 20 %
    assert item["marcas"] == 2 and len(item["linhas"]) == 2
    s.marcar(_alvo(t=T0 - 5), "voz", T0 + 50)
    assert [i["chave"] for i in s.pauta(agora)] == ["cabeca_ritmo"]  # ≥ 3 marcas
    assert s.exportar(agora)["ajustes"] == {"jogando:cabeca_ritmo": 0.7 ** 3}


def test_numeros_vem_do_vida():
    s = SemSentido(vida={"sem_sentido": {"fator": 0.5, "piso": 0.4}})
    s.marcar(_alvo(), "hover", T0)
    assert s.fatores(Momento.JOGANDO, T0 + 1) == {"cabeca_ritmo": 0.5}


def test_reacao_sem_animo_placar_ou_ritmo():
    assert REACAO.rosto == "B7 C12 ?" and REACAO.ms == 700
    assert REACAO.animo == 0 and not REACAO.placar and not REACAO.ritmo


def test_nunca_escreve_no_gosto_nem_mexe_no_vida(tmp_path, monkeypatch):
    gosto = tmp_path / "condessa-gosto.toml"
    gosto.write_text("[vida]\n", encoding="utf-8")
    antes = json.dumps(VIDA_PADRAO, sort_keys=True, default=str)
    vida = {"sem_sentido": dict(VIDA_PADRAO["sem_sentido"])}
    s = SemSentido(vida=vida)
    for i in range(4):
        s.marcar(_alvo(t=T0 - i), "hover", T0 + i * 10)
    s.pauta(T0 + 100)
    assert gosto.read_text(encoding="utf-8") == "[vida]\n"
    assert json.dumps(VIDA_PADRAO, sort_keys=True, default=str) == antes
    assert vida == {"sem_sentido": dict(VIDA_PADRAO["sem_sentido"])}
    assert set(p.name for p in tmp_path.rglob("*") if p.is_file()) == {"condessa-gosto.toml",
                                                                         "sem-sentido.jsonl"}


def _ctx(**kw) -> dict:
    base = {"agora": 1000.0, "hora": 15, "humor_pedro": 3, "musica_nota": None,
            "_passivas_inicio": 0.0, "ultima_expressao_em": 1000.0, "momento": Momento.TEDIO}
    base.update(kw)
    return base


def _contar(fatores, n=3000) -> Counter:
    ctx, rng, c = _ctx(), random.Random(3), Counter()
    for _ in range(n):
        ctx["_passivas_proxima"] = 1000.0
        ctx["_passivas_usos"] = []
        d = passivas.sortear(ctx, 1000.0, rng, fatores)
        if d is not None:
            c[d.chave] += 1
    return c


def test_passivas_sem_fatores_igual_a_hoje():
    ctx = _ctx()
    assert passivas.pesos(ctx, 1000.0) == passivas.pesos(ctx, 1000.0, None)
    assert _contar(None) == _contar({})


def test_passivas_aceitam_fatores():
    ctx = _ctx()
    pesos = passivas.pesos(ctx, 1000.0)
    alvo = sorted(pesos)[0]
    ajust = passivas.pesos(ctx, 1000.0, {alvo: 0.3})
    assert ajust[alvo] == pesos[alvo] * 0.3
    assert {k: v for k, v in ajust.items() if k != alvo} == {k: v for k, v in pesos.items() if k != alvo}
    antes, depois = _contar(None), _contar({alvo: 0.3})
    assert depois[alvo] < antes[alvo] and depois[alvo] > 0  # nunca some
