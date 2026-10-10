"""R0.5: ligação no Reactor — detectores + passivas -> governador -> sequência (CA-02, CA-08)."""

from __future__ import annotations

import json
import random
import time
from dataclasses import replace

from wired.main_screen import Snapshot, Track
from wired.reacoes import DETECTORES
from wired.reacoes.catalogo import ATIVAS, DEFS
from wired.reacoes.contratos import Classe, Def, Disparo, Passo
from wired.reactions import PASSIVA_A_CADA, Reactor, Taste

QUATRO = Def("teste4", "T", "Quatro passos", (
    Passo(1000, "B9", "C7", efeitos=("bang",)),
    Passo(500, "B5", "C13", look="player", efeitos=("blush", "notes"), corpo=("bob",)),
    Passo(2000, "F1", None, corpo=("iris:F1", "braco:P9")),
    Passo(250, "B1", "C1"),
), frozenset({Classe.PEDRO, Classe.NOTURNA}), mood="surprise", cooldown_s=1.0)
COBRA = Def("cobra", "T2", "Cobrança", (Passo(800, "B6", "C8"),),
            frozenset({Classe.PEDRO, Classe.COBRANCA}), cooldown_s=1.0)


def make(tmp_path, detectores=(), sortear=None, defs=None):
    g = tmp_path / "genres.json"
    g.write_text(json.dumps({"ado": {"genres": ["j-rock"]}}), encoding="utf-8")
    t = tmp_path / "gosto.toml"
    t.write_text("", encoding="utf-8")
    return Reactor(Taste(g, t), cleanup_file=tmp_path / "cleanup.json", seen_file=tmp_path / "seen.json",
                   clock=lambda: 1_800_000_000.0, rng=random.Random(1), detectores=detectores,
                   sortear=sortear or (lambda ctx, agora, rng: None),
                   defs={"teste4": QUATRO, "cobra": COBRA} if defs is None else defs,
                   registro_file=tmp_path / "reacoes.jsonl")


def snap(**kw) -> Snapshot:
    return replace(Snapshot(), **kw)


def ate(r, t0, t1, hour=15, **kw):
    """Ticks de 1 s de ``t0`` a ``t1`` (o diretor junta os disparos por 3 s antes de decidir)."""
    for t in range(int(t0), int(t1) + 1):
        r.observe(snap(**kw), float(t), hour)


def test_sequencia_de_4_passos_passo_certo_no_inicio_meio_e_fim(tmp_path):
    r = make(tmp_path)
    r.tocar(QUATRO, Disparo("teste4", "teste"), 100.0)
    assert r.until == 100.0 + 3.75
    inicio = 100.0
    for p in QUATRO.passos:
        for t in (inicio, inicio + p.ms / 2000.0, inicio + p.ms / 1000.0 - 0.001):
            cur = r.active(t)
            assert (cur.eyes, cur.mouth, cur.look, cur.efeitos, cur.corpo) == (
                p.eyes, p.mouth, p.look, p.efeitos, p.corpo), t
            assert cur.name == "teste4" and cur.mood == "surprise" and cur.noturna
            assert cur.effect == (p.efeitos[0] if p.efeitos else None)
        inicio += p.ms / 1000.0
    assert r.active(100.0 + 1.5).eyes == "F1"  # fim exato do 2º passo = começo do 3º
    assert r.active(100.0 + 1.0).bob  # "bob" no corpo vira o balanço de sempre
    assert r.active(103.75) is None and r.active(100.5) is None  # acabou e não volta


def test_mesmo_passo_devolve_o_mesmo_rosto(tmp_path):
    r = make(tmp_path)
    r.tocar(QUATRO, Disparo("teste4", "teste"), 0.0)
    assert r.active(0.1) is r.active(0.9)
    assert r.active(0.9) is not r.active(1.1)


def test_ctx_unico_entre_ticks_e_detector_quebrado(tmp_path):
    vistos = []

    def det(anterior, s, ctx):
        vistos.append(ctx)
        return [Disparo("teste4", "teste")] if s.gaming and not anterior.gaming else []

    r = make(tmp_path, detectores=[lambda a, s, c: 1 / 0, det])  # detector quebrado é ignorado
    r.observe(snap(), 0.0, 15)
    ate(r, 1, 4, gaming=True)
    assert r.active(4.0).name == "game_on"  # a antiga (roteiro do cockpit) vence a ativa solta
    assert len({id(c) for c in vistos}) == 1  # o mesmo ctx entre ticks
    ctx = vistos[-1]
    assert ctx["estado"] is r.estado and ctx["hora"] == 15 and ctx["jogo"] is True
    assert set(ctx) >= {"defs", "agora", "relogio", "madrugada", "humor", "claude", "musica_nota", "ado",
                        "faixa", "faixa_desde", "veredito", "magui", "parada", "atividade", "taste",
                        "desligadas"}


def test_governador_aprovado_toca_quando_parada(tmp_path):
    r = make(tmp_path, detectores=[lambda a, s, c: [Disparo("teste4", "teste")]])
    ate(r, 0, 4)
    assert r.active(4.0).name == "teste4" and r.active(4.0).eyes == "B9"
    linha = json.loads((tmp_path / "reacoes.jsonl").read_text().splitlines()[-1])
    assert "teste4" in json.dumps(linha)
    r.observe(snap(), 5.0, 15)  # ocupada: não recomeça a sequência
    assert r.active(5.0).eyes == "B5"
    r2 = make(tmp_path, detectores=[lambda a, s, c: [Disparo("teste4", "teste")]])
    ate(r2, 0, 4, magui_state="speaking")
    assert r2.active(4.0) is None  # falando: nada novo


def test_bloqueio_de_cobranca_aplicado_no_passo(tmp_path):
    r = make(tmp_path, detectores=[lambda a, s, c: [Disparo("cobra", "teste")]])
    ate(r, 0, 4, hour=23)  # 22h–04h: C8 -> C9
    assert r.active(4.0).mouth == "C9"


def test_passivas_a_cada_10_s(tmp_path):
    chamadas = []

    def sortear(ctx, agora, rng):
        chamadas.append(agora)
        return None

    r = make(tmp_path, sortear=sortear)
    r.observe(snap(), 0.0, 15)
    for i in range(1, 31):
        r.observe(snap(), float(i), 15)
    base = r._rel(0.0)  # as passivas andam no relógio da vida
    assert [c - base for c in chamadas] == [1.0, 1.0 + PASSIVA_A_CADA, 1.0 + 2 * PASSIVA_A_CADA]


def test_musica_antiga_vence_e_sequencia_cede_a_prioridade(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    r.tocar(QUATRO, Disparo("teste4", "teste"), 0.5)
    ate(r, 1, 4, track=Track("Usseewa", "Ado"))  # a cena da música corta a sequência solta
    assert r.active(4.0).name == "music_love"
    assert r.ctx["ado"] is True and r.ctx["musica_nota"] == 2


def test_ca08_tick_com_todos_os_detectores_ate_2ms(tmp_path):
    r = make(tmp_path, detectores=DETECTORES, sortear=None, defs={k: DEFS[k] for k in ATIVAS})
    r.observe(snap(), 0.0, 15)
    snaps = [snap(cpu_temp=60.0 + i % 3, gaming=bool(i % 2), fps=120.0, fps_avg=120.0) for i in range(4)]
    t0 = time.perf_counter()
    for i in range(1000):
        r.observe(snaps[i % 4], 1.0 + i, 15)
    media_ms = (time.perf_counter() - t0) * 1000.0 / 1000  # ms por tick
    assert media_ms <= 2.0, f"{media_ms:.3f} ms por tick"
