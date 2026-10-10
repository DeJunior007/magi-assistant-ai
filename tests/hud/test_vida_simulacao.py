"""V0.9 · CA-V6: o dia real (2026-10-09) reproduzido como acontecimentos passa nas 7 metas do
acordo §8.

A fixture ``fixtures/dia-2026-10-09.json`` saiu do ``reacoes.jsonl`` do Pedro: cada disparo antigo
virou o acontecimento que o causou (segundos do dia): música tocando (das passivas de música, com
buracos ≤ 15 min), a faixa amada (``music_love``), jogo aberto/fechado, PC quente até o alívio,
quedas de FPS, rodadas do Claude (do "parou depois de N s"), hook notify/fail, commits, ausências
(do "quieta há 10 min"/fim do jogo até a volta) e as voltas do Pedro. As passivas antigas ficam de
fora: o sistema novo sorteia as dele. O ``Reactor`` real roda com os detectores de tempo, música,
sistema e Claude, relógio e ``rng`` injetados (passo de 2 s).
"""

from __future__ import annotations

import json
import random
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from wired.main_screen import Snapshot, Track
from wired.reacoes import det_claude, det_musica, det_sistema, det_tempo
from wired.reacoes.atividade import Atividade
from wired.reacoes.vida import Faixa as FaixaHumor
from wired.reactions import Reactor, Taste

DIA = json.loads((Path(__file__).parent / "fixtures" / "dia-2026-10-09.json").read_text("utf-8"))
PASSO = 2.0
FAIXA_S = 210  # uma faixa nova a cada 3,5 min enquanto toca música
ARTISTAS = {"lume": "pop", "vento": "lofi", "norte": "rock"}  # notas 1, 0, 1 no gosto do conselho
EXPRESSAO = ("cena", "ativa", "gesto")
CORPO = frozenset({"recoloca_fone", "musica_parou"})  # troca de fone = passo de corpo (P11, Tipo.CORPO)
# acordo §4: suspiro, franja, beicinho de birra (+ as caretas com culpado do diretor/episódio); o
# "encarando" da escada do Tédio é o degrau do próprio Tédio (acordo §3), não careta com culpado
NEGATIVAS = frozenset({"suspiro", "beicinho", "soprando_franja", "impaciente", "indiferente",
                       "desconfiada", "eu_avisei"})
SEM_PISO = frozenset({"conversa", "jogando"})
HOOKS = sorted([(x, "notify") for x in DIA["espera"]] + [(x, "fail") for x in DIA["erro"]])
POSITIVAS = frozenset({"sorriso_canto", "rindo_sozinha", "piscada_gato", "corando", "cantarolando",
                       "cantando_junto", "refrao", "piscadinha", "brilho_presilha", "music_love",
                       "music_like", "pedro_voltou", "bom_dia", "ideia", "commit", "musica_comecou",
                       "cabeca_ritmo", "claude_terminou", "game_on", "truque", "duelo_ado"})
ALIVIO = frozenset({("fps_drop", "recuperou"), ("hot", "alivio")})  # acontecimento +0,10 (acordo §1)


def _em(t: float, faixas) -> bool:
    return any(a <= t < b for a, b in faixas)


def _ultimo(t: float, ts):
    antes = [x for x in ts if x[0] <= t]
    return antes[-1] if antes else None


def _snap(t: float, meia_noite: float) -> Snapshot:
    kw: dict = {"gaming": _em(t, DIA["jogo"]), "cpu_temp": 85.0 if _em(t, DIA["quente"]) else 60.0}
    if _em(t, DIA["musica"]):
        if any(a <= t < a + 240 for a in DIA["ado"]):
            kw["track"] = Track("Usseewa", "Ado", playing=True)
        else:
            i = int(t // FAIXA_S)
            kw["track"] = Track(f"Faixa {i}", list(ARTISTAS)[i % 3], playing=True)
    if kw["gaming"]:
        kw.update(fps_avg=100.0, fps=30.0 if any(f - 4 <= t < f + 2 for f in DIA["fps"]) else 100.0)
    ev = _ultimo(t, HOOKS)
    kw["claude"] = SimpleNamespace(running=int(_em(t, DIA["claude"])),
                                   last_event=(meia_noite + ev[0], ev[1], "proj") if ev else None)
    return replace(Snapshot(), **kw)


def simular(tmp_path: Path, semente: int = 1, gosto_pedro: str = "") -> dict:
    meia_noite = time.mktime(time.strptime(DIA["dia"], "%Y-%m-%d"))
    t = float(DIA["inicio"])
    relogio = [meia_noite + t]
    g = tmp_path / "genres.json"
    generos = {"ado": {"genres": ["j-rock"]}} | {a: {"genres": [x]} for a, x in ARTISTAS.items()}
    g.write_text(json.dumps(generos), encoding="utf-8")
    gosto = tmp_path / "gosto.toml"
    gosto.write_text(gosto_pedro, encoding="utf-8")  # vazio: só o conselho (persona) + VIDA_PADRAO
    r = Reactor(Taste(g, gosto), cleanup_file=tmp_path / "c.json", seen_file=tmp_path / "s.json",
                clock=lambda: relogio[0], rng=random.Random(semente),
                detectores=(det_tempo.detectar, det_musica.detectar, det_sistema.detectar,
                            det_claude.detectar),
                registro_file=tmp_path / "r.jsonl", estado_file=tmp_path / "e.json", boot_id="replay",
                atividade=Atividade(tmp_path / "atividade.json"))
    r.favorite_of_day = lambda: ""
    log: list[dict] = []

    def _log(tipo, chave, motivo, now, d=None, disp=None, causa=None):  # noqa: ARG001
        log.append({"t": relogio[0] - meia_noite, "tipo": tipo, "chave": chave, "rel": r._rel(now),  # noqa: SLF001
                    "causas": dict(r.diretor.causas), "momento": str(r.ctx.get("momento") or ""),
                    "var": disp.variante if disp is not None else None})

    r._log = _log  # noqa: SLF001
    faixas: Counter = Counter()
    animo: list[tuple[float, float]] = []
    ticks: list[tuple[float, bool, str]] = []  # (t, Pedro ausente, momento)
    presente_s = Counter()  # hora → segundos com o Pedro presente
    ping = -1e9
    while t <= DIA["fim"]:
        relogio[0] = meia_noite + t
        ausente = _em(t, DIA["ausente"])
        if not ausente and t - ping >= 60 and not any(b <= t < b + 10 for _, b in DIA["ausente"]):
            r.atividade.evento(relogio[0], "entrada")  # teclado/mouse do Pedro (1/min presente)
            ping = t
        r.ctx["git_head"] = f"h{sum(1 for x in DIA['commit'] if x <= t)}"
        r.observe(_snap(t, meia_noite), t - DIA["inicio"], int(t // 3600) % 24)
        animo.append((t, round(r.humor.animo, 3)))
        faixas[r.humor.faixa(r._rel(t - DIA["inicio"]))] += PASSO  # noqa: SLF001
        if not ausente:
            presente_s[int(t // 3600)] += PASSO
        ticks.append((t, ausente, str(r.momento)))
        t += PASSO
    return {"log": log, "faixas": faixas, "presente_s": presente_s, "animo": animo, "ticks": ticks}


@pytest.fixture(scope="module")
def dia(tmp_path_factory) -> dict:
    return simular(tmp_path_factory.mktemp("replay"))


def _expressoes(dia: dict) -> list[dict]:
    return [x for x in dia["log"] if x["tipo"] in EXPRESSAO and x["chave"] not in CORPO]


def metas(dia: dict) -> dict:
    exp = _expressoes(dia)
    horas = (DIA["fim"] - DIA["inicio"]) / 3600
    ts = [x["t"] for x in exp if x["momento"] != "conversa"]
    rajadas = sum(1 for i in range(len(ts) - 2) if ts[i + 2] - ts[i] <= 30)
    vivas = {x["t"] for x in dia["log"] if x["tipo"] in (*EXPRESSAO, "atencao") and x["chave"] not in CORPO}
    maior, ult = 0.0, DIA["inicio"]
    for t, ausente, momento in dia["ticks"]:  # Pedro presente, sem expressão nem atenção dirigida
        if ausente or momento in SEM_PISO or t in vivas:  # spec §9: o piso não vale em
            ult = t  # Conversa e Jogando (lá a média das passivas é 8 min, acordo §4)
        maior = max(maior, t - ult)
    negs = [x for x in exp if x["chave"] in NEGATIVAS]
    sem_causa = [x for x in negs if not any(0 <= x["rel"] - c <= 120 for c in x["causas"].values())]
    total = sum(dia["faixas"].values())
    pos_h = Counter(int(x["t"] // 3600) for x in exp
                    if x["chave"] in POSITIVAS or (x["chave"], x["var"]) in ALIVIO)
    horas_sem_pos = [h for h, s in dia["presente_s"].items() if s >= 1800 and not pos_h[h]]
    cenas = [x for x in dia["log"] if x["tipo"] == "cena"]
    voltas_sem_cena = [v for v in DIA["volta"] if not any(
        abs(c["t"] - v) <= 15 and c["chave"].startswith(("pedro_voltou", "sentiu_falta", "sobressalto"))
        for c in cenas)]
    return {
        "1_exp_h": len(exp) / horas,
        "2_rajadas": rajadas,
        "3_maior_buraco_min": maior / 60,
        "4_neg_sem_causa": len(sem_causa),
        "5_faixas": {str(k): round(v / total, 3) for k, v in dia["faixas"].items()},
        "6_horas_sem_positiva": horas_sem_pos,
        "7_voltas_sem_cena": voltas_sem_cena,
    }


def test_replay_do_dia_real_bate_as_7_metas(dia):
    m = metas(dia)
    print(m)  # o número medido de cada meta (pytest -s)
    assert 12 <= m["1_exp_h"] <= 20
    assert m["2_rajadas"] == 0
    assert m["3_maior_buraco_min"] <= 6
    assert m["4_neg_sem_causa"] == 0
    fx = dia["faixas"]
    total = sum(fx.values())
    assert len([f for f, s in fx.items() if s > 0]) >= 3
    assert fx[FaixaHumor.EMBURRADA] / total < 0.15
    assert fx[FaixaHumor.RADIANTE] > 0
    assert m["6_horas_sem_positiva"] == []
    assert m["7_voltas_sem_cena"] == []


def test_escada_encarando_aos_15_min_sem_musica(tmp_path):
    """A V0.8b achou o encarando só ~30 min sem música; o acordo §3 põe o degrau nos 15 min sem
    música (a própria entrada no Tédio) e o "ei, tô aqui" nos 30."""
    agora = [0.0]
    g = tmp_path / "g.json"
    g.write_text("{}", encoding="utf-8")
    (tmp_path / "t.toml").write_text("", encoding="utf-8")
    r = Reactor(Taste(g, tmp_path / "t.toml"), cleanup_file=tmp_path / "c.json",
                seen_file=tmp_path / "s.json",
                clock=lambda: 1_800_000_000.0 + agora[0], rng=random.Random(7), detectores=(),
                registro_file=tmp_path / "r.jsonl", estado_file=tmp_path / "e.json", boot_id="b",
                atividade=SimpleNamespace(parado_s=lambda _agora: 0.0))
    r.favorite_of_day = lambda: ""
    vistos: dict[str, float] = {}
    r._log = lambda tipo, chave, *a, **k: vistos.setdefault(chave, agora[0]) if tipo != "repouso" else None  # noqa: SLF001
    while agora[0] <= 7200:
        faixa = Track("Faixa", "vento", playing=True) if agora[0] < 60 else None  # a música para no 1º min
        r.observe(replace(Snapshot(), track=faixa), agora[0], 15)
        agora[0] += 5.0
    assert 60 + 15 * 60 <= vistos["encarando"] < 60 + 20 * 60  # antes: ≥ 30 min de silêncio
    assert vistos["ei_to_aqui"] >= 60 + 30 * 60  # o "ei" só depois dos 30 min (quando sai é sorteio)
