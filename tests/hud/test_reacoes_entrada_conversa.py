"""R1.5: detectores de entrada (5, 64, 66) e conversa (71–73, 79, I18) — spec §5, acordo §1/§2."""

from __future__ import annotations

import pytest

from hud.wired.main_screen import Snapshot, Track
from hud.wired.reacoes import catalogo, det_conversa, det_entrada
from hud.wired.reactions import Taste


class FakeTaste:
    def section(self, name: str) -> dict:
        assert name == "listas"
        return {"noticia_boa": ["vitoria", "recorde", "cura"],
                "noticia_ruim": ["morte", "crise", "desastre"],
                "noticia_absurda": ["bizarro", "inusitado"]}


class Sim:
    def __init__(self, det, **ctx):
        self.det = det
        self.ctx: dict = {"agora": 0.0, "humor": 3, "taste": FakeTaste()} | ctx
        self.ant = None

    def tick(self, t: float, **campos) -> list[tuple[str, str | None]]:
        snap = Snapshot(**campos)
        self.ctx["agora"] = t
        out = self.det.detectar(self.ant, snap, self.ctx)
        self.ant = snap
        for d in out:
            k = (d.chave, d.variante) if d.variante else d.chave
            assert k in catalogo.ATIVAS, k
        return [(d.chave, d.variante) for d in out]


def news(*titulos: str) -> list[tuple[str, str]]:
    return [("12:00", t) for t in titulos]


# ---------------------------------------------------------------- det_entrada


def test_5_sacada_para_faixa_nova():
    s = Sim(det_entrada)
    s.tick(0.0, track=Track("A", "x", playing=True))
    assert s.tick(1.0, track=Track("A", "x", playing=True)) == []
    assert s.tick(2.0, track=Track("B", "x", playing=True)) == [("seguir_cursor", None)]


def test_5_sacada_para_manchete_e_fps():
    s = Sim(det_entrada)
    s.tick(0.0, news=news("velha"))
    assert s.tick(1.0, news=news("nova", "velha")) == [("seguir_cursor", None)]
    out = det_entrada.detectar(Snapshot(), Snapshot(fps=60.0), s.ctx)
    assert [(d.chave, d.fmt["card"]) for d in out] == [("seguir_cursor", "fps")]


def test_5_nao_sai_no_primeiro_snapshot():
    s = Sim(det_entrada)
    assert s.tick(0.0, track=Track("A", "x"), news=news("x"), fps=60.0) == []


def test_64_escalada_no_terceiro_clique_em_5_s():
    s = Sim(det_entrada)
    s.ctx["cliques"] = [(10.0, "led")]
    assert s.tick(10.0) == []  # 1º: fire antigo do Reactor
    s.ctx["cliques"] += [(11.0, "led")]
    assert s.tick(11.0) == []
    s.ctx["cliques"] += [(12.0, "next"), (13.0, "led")]
    assert s.tick(13.0) == [("led", None)]
    assert s.tick(14.0) == []  # clique já tratado


def test_64_cliques_espacados_nao_escalam():
    s = Sim(det_entrada)
    s.ctx["cliques"] = [(0.0, "led"), (6.0, "led"), (12.0, "led")]
    assert s.tick(12.0) == []


def test_66_clique_com_musica():
    s = Sim(det_entrada)
    s.tick(0.0, track=Track("A", "x", playing=True))
    s.ctx["cliques"] = [(1.0, "led")]
    assert s.tick(1.0, track=Track("A", "x", playing=True)) == [("led", "fone")]
    s.ctx["cliques"] += [(2.0, "led")]
    assert s.tick(2.0, track=Track("A", "x", playing=False)) == []  # pausada não conta


def test_entrada_sem_cliques_no_ctx():
    s = Sim(det_entrada)
    assert s.tick(0.0) == [] and s.tick(1.0) == []


# ---------------------------------------------------------------- det_conversa


@pytest.mark.parametrize("manchete, chave", [
    ("Time conquista vitória histórica", "noticia_boa"),
    ("Crise no mercado de chips", "noticia_ruim"),
    ("Caso bizarro em cidade do interior", "noticia_absurda"),
])
def test_71_72_73_manchete_nova(manchete, chave):
    s = Sim(det_conversa)
    s.tick(0.0, news=news("velha"))
    assert s.tick(1.0, news=news(manchete, "velha")) == [(chave, None)]
    assert s.tick(2.0, news=news(manchete, "velha")) == []


def test_manchete_neutra_nao_reage():
    s = Sim(det_conversa)
    s.tick(0.0, news=news("velha"))
    assert s.tick(1.0, news=news("Governo publica edital")) == []


@pytest.mark.parametrize("manchete", [
    "Morte bizarra em zoológico", "Desastre inusitado na ponte", "Acidente bizarro deixa feridos",
    "Recorde de mortes em desastre", "Vitória após tragédia no estádio",
])
def test_72_73_morte_ou_desastre_nunca_vira_riso(manchete):
    s = Sim(det_conversa)
    s.tick(0.0, news=news("velha"))
    out = s.tick(1.0, news=news(manchete))
    assert out == [("noticia_ruim", None)]  # nunca 71/73 (riso/zoeira)


def test_conversa_usa_listas_do_gosto_real():
    s = Sim(det_conversa, taste=Taste())
    s.tick(0.0, news=news("velha"))
    assert s.tick(1.0, news=news("Cientistas anunciam cura")) == [("noticia_boa", None)]


def test_conversa_sem_gosto_usa_recaida():
    s = Sim(det_conversa, taste=None)
    s.tick(0.0, news=news("velha"))
    assert s.tick(1.0, news=news("Guerra comercial")) == [("noticia_ruim", None)]


def test_79_humor_cai_para_1():
    s = Sim(det_conversa)
    s.tick(0.0)
    assert s.tick(1.0) == []
    s.ctx["humor"] = 1
    assert s.tick(2.0) == [("triste_leve", None)]
    s.ctx["humor"] = 0
    assert s.tick(3.0) == []  # continua baixo: não repete
    s.ctx["humor"] = 2
    s.tick(4.0)
    s.ctx["humor"] = 1
    assert s.tick(5.0) == [("triste_leve", None)]


def test_79_sem_texto_nem_lagrima():
    d = catalogo.DEFS["triste_leve"]
    assert d.fala is None
    assert not any("tear" in p.efeitos or "D7" in p.efeitos for p in d.passos)


def test_79_humor_baixo_desde_o_inicio_nao_dispara():
    s = Sim(det_conversa, humor=1)
    assert s.tick(0.0) == [] and s.tick(1.0) == []


def test_i18_magui_volta_de_falando_para_parada():
    s = Sim(det_conversa)
    s.tick(0.0, magui_state="speaking")
    assert s.tick(1.0, magui_state="speaking") == []
    assert s.tick(2.0, magui_state="sleeping") == [("esperando_resposta", None)]


def test_i18_falando_para_ouvindo_nao_conta():
    s = Sim(det_conversa)
    s.tick(0.0, magui_state="speaking")
    assert s.tick(1.0, magui_state="listening") == []


def test_5_jogando_nao_desvia_para_player():
    s = Sim(det_entrada, jogo=True)
    s.tick(0.0, track=Track("A", "x", playing=True), gaming=True, fps=140.0)
    assert s.tick(1.0, track=Track("B", "x", playing=True), gaming=True, fps=140.0) == []


# ---------------------------------------------------------------- V1.9: "isso foi sem sentido" por voz


def test_v19_tag_sem_sentido_vira_pedido_e_nao_reacao():
    s = Sim(det_conversa)
    assert s.tick(10.0, turn_tag=("sem_sentido", 9.0)) == []
    assert s.ctx["sem_sentido_voz"] == 9.0
    s.ctx.pop("sem_sentido_voz")
    assert s.tick(11.0, turn_tag=("sem_sentido", 9.0)) == []  # a mesma tag não pede de novo
    assert "sem_sentido_voz" not in s.ctx


def test_v19_tag_velha_nao_pede():
    s = Sim(det_conversa)
    assert s.tick(100.0, turn_tag=("sem_sentido", 50.0)) == []
    assert "sem_sentido_voz" not in s.ctx


def _reactor(tmp_path, relogio):
    import json as _json
    import random

    from wired.reactions import Reactor
    from wired.reactions import Taste as _Taste

    g = tmp_path / "genres.json"
    g.write_text(_json.dumps({}), encoding="utf-8")
    t = tmp_path / "gosto.toml"
    t.write_text("", encoding="utf-8")
    r = Reactor(_Taste(g, t), cleanup_file=tmp_path / "cleanup.json", seen_file=tmp_path / "seen.json",
                clock=lambda: relogio[0], rng=random.Random(3), detectores=(det_conversa_wired(),),
                sortear=lambda ctx, agora, rng: None, registro_file=tmp_path / "r.jsonl",
                estado_file=tmp_path / "estado.json", sem_sentido_file=tmp_path / "ss.jsonl",
                boot_id="boot-1")
    r.favorite_of_day = lambda: ""
    return r


def det_conversa_wired():
    from wired.reacoes import det_conversa as dc

    return dc.detectar


def _marcas(tmp_path) -> list[dict]:
    import json as _json

    p = tmp_path / "ss.jsonl"
    return [_json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.mark.parametrize("idade, alvo", [(30.0, "cabeca_ritmo"), (90.0, None)])
def test_v19_voz_marca_ultima_expressao_da_janela(tmp_path, idade, alvo):
    relogio = [1_800_000_000.0]
    r = _reactor(tmp_path, relogio)
    r.observe(Snapshot(), 0.0, 15)
    r._expressoes = [{"t": relogio[0] - idade, "chave": "cabeca_ritmo", "tipo": "gesto"}]
    r.observe(Snapshot(turn_tag=("sem_sentido", 1.0)), 1.5, 15)
    m = _marcas(tmp_path)
    assert len(m) == 1 and m[0]["gesto"] == "voz"
    if alvo is None:  # sem expressão em ≤ voz_janela_s (60): alvo nenhum, o núcleo diz que não sabe
        assert m[0]["alvo"] == "nenhum"
    else:
        assert m[0]["alvo"]["chave"] == alvo


def test_v19_voz_sem_nenhuma_expressao(tmp_path):
    r = _reactor(tmp_path, [1_800_000_000.0])
    linha = r.sem_sentido_voz(5.0)
    assert linha["alvo"] == "nenhum" and linha["gesto"] == "voz"
