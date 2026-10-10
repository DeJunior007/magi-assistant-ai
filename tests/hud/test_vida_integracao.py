"""V0.8: a vida ligada no Reactor — estado → momento → diretor → passivas → repouso (CA-V9)."""

from __future__ import annotations

import json
import random
import time
from dataclasses import replace

from wired.main_screen import Snapshot, Track
from wired.reacoes import DETECTORES
from wired.reacoes.contratos import Disparo
from wired.reacoes.vida import Fone, Momento
from wired.reactions import Reactor, Taste

RELOGIO = 1_800_000_000.0


def make(tmp_path, detectores=(), sortear=None, boot="boot-1", relogio=None):
    g = tmp_path / "genres.json"
    g.write_text(json.dumps({"ado": {"genres": ["j-rock"]}}), encoding="utf-8")
    t = tmp_path / "gosto.toml"
    t.write_text("", encoding="utf-8")
    r = Reactor(Taste(g, t), cleanup_file=tmp_path / "cleanup.json", seen_file=tmp_path / "seen.json",
                clock=relogio or (lambda: RELOGIO), rng=random.Random(3), detectores=detectores,
                sortear=sortear or (lambda ctx, agora, rng: None), registro_file=tmp_path / "r.jsonl",
                estado_file=tmp_path / "estado.json", boot_id=boot)
    r.favorite_of_day = lambda: ""
    return r


def snap(**kw) -> Snapshot:
    return replace(Snapshot(), **kw)


def linhas(tmp_path) -> list[dict]:
    p = tmp_path / "r.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_ponta_a_ponta_musica_amada(tmp_path):
    """Música amada → 1 cena (com o fone posto pelo P11), sorriso de repouso pela faixa e o medidor
    subindo com a causa."""
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    antes = r.medidor(0.0)[0]
    ado = snap(track=Track("Usseewa", "Ado"))
    for t in range(1, 15):
        r.observe(ado, float(t), 15)
    cenas = [x for x in linhas(tmp_path) if x["tipo"] == "cena"]
    assert [(x["chave"], x["causa"]) for x in cenas] == [("music_love", "faixa:Usseewa|Ado")]
    assert all(x["momento"] and x["faixa"] for x in cenas)
    assert r.vida_estado.postura.fone == Fone.CABECA  # a cena pôs o fone (P11 E2)
    valor, cor, momento, causas = r.medidor(14.0)
    assert valor > antes and causas[-1][0] == "Ado" and causas[-1][1] > 0 and causas[-1][2] >= 0
    assert momento == str(r.momento) and cor.startswith("#")
    rep = r.repouso
    assert rep.mouth in ("C10", "C5") and rep.fone == Fone.CABECA  # sorriso da faixa, com fone
    assert rep.eyes == "B4"  # nota 2 com fone na cabeça


def test_sem_musica_sem_fone_e_estado_persistido(tmp_path):
    r = make(tmp_path)
    for t in range(0, 5):
        r.observe(snap(), float(t), 15)
    assert r.repouso.fone == Fone.PESCOCO  # CA-V5: sem música nunca E2
    r.vida_estado.postura.fone = Fone.CABECA
    r.diretor.gov.hist.append((RELOGIO - 4, "cena", "x", "musica", False, False))
    r._salvo_em = -1e18
    r.observe(snap(), 5.0, 15)
    dados = json.loads((tmp_path / "estado.json").read_text())
    assert dados["governador"]["boot"] == "boot-1" and dados["governador"]["hist"]
    assert dados["postura"]["fone"] == "cabeca"
    r2 = make(tmp_path)
    assert r2.vida_estado.postura.fone == Fone.CABECA
    assert any(h[2] == "x" for h in r2.diretor.gov.hist)  # contadores do governador voltam


def test_hud_acordou_uma_vez_por_boot(tmp_path):
    def acordou(r) -> bool:
        for t in range(0, 6):
            r.observe(snap(), float(t), 15)
        return any(x["chave"] == "hud_acordou" for x in linhas(tmp_path))

    r = make(tmp_path, detectores=DETECTORES)
    assert acordou(r)
    r._salvo_em = -1e18
    r.observe(snap(), 6.0, 15)
    (tmp_path / "r.jsonl").unlink()
    assert not acordou(make(tmp_path, detectores=DETECTORES))  # HUD reiniciado, mesmo boot
    assert acordou(make(tmp_path, detectores=DETECTORES, boot="boot-2"))  # PC reiniciado


def test_piso_de_vida_vira_atencao_dirigida(tmp_path):
    r = make(tmp_path, sortear=lambda ctx, agora, rng: Disparo("atencao", "piso"))
    r.observe(snap(track=Track("x", "Desconhecido")), 0.0, 15)
    r.observe(snap(track=Track("x", "Desconhecido")), 1.0, 15)
    at = [x for x in linhas(tmp_path) if x["tipo"] == "atencao"]
    assert at and at[0]["motivo"] == "piso" and at[0]["chave"].startswith("atencao:")
    assert r.active(1.0).name == "atencao" and r.active(1.0).look


def test_sistema_cala_a_antiga_do_episodio(tmp_path):
    def cala(anterior, s, ctx):
        ctx["_sistema_cala"] = {"hot"}
        return []

    r = make(tmp_path, detectores=[cala])
    r.observe(snap(cpu_temp=60.0), 0.0, 15)
    for t in range(1, 6):
        r.observe(snap(cpu_temp=90.0), float(t), 15)
    assert not any(x["chave"] == "hot" for x in linhas(tmp_path))


def test_ctx_ganha_os_sinais_da_vida(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    r.observe(snap(), 1.0, 15)
    assert set(r.ctx) >= {"momento", "faixa_humor", "fone", "energia", "animo", "causas", "filtros",
                          "ultima_expressao_em", "pedro_inativo_s", "sem_musica_ha_s", "magui_ativa"}
    assert isinstance(r.ctx["momento"], Momento) and r.ctx["musica_nota"] == 0  # 0 p/ os detectores


def test_ca_v9_tick_ate_2ms(tmp_path):
    from wired.reacoes import passivas

    r = make(tmp_path, detectores=DETECTORES, sortear=passivas.sortear)
    faixas = [Track("Usseewa", "Ado"), Track("x", "Desconhecido"), None]
    r.observe(snap(), 0.0, 15)
    total = 0.0
    for i in range(1, 1001):
        s = snap(track=faixas[(i // 120) % 3], cpu=40.0 + i % 50, cpu_temp=60.0 + i % 30,
                 gaming=(i // 300) % 2 == 1, fps=60.0 + i % 80, fps_avg=120.0)
        t0 = time.perf_counter()
        r.observe(s, float(i), 15)
        total += time.perf_counter() - t0
    assert total / 1000 <= 0.002  # CA-V9: média de 1000 ticks com tudo ligado
