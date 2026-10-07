from __future__ import annotations

import json
from dataclasses import replace

from wired.main_screen import Snapshot, Track
from wired.reactions import LINE_GAP, Reactor, Taste


def make(tmp_path, genres=None, taste=""):
    g = tmp_path / "genres.json"
    g.write_text(json.dumps(genres or {}), encoding="utf-8")
    t = tmp_path / "gosto.toml"
    t.write_text(taste, encoding="utf-8")
    return Reactor(Taste(g, t), cleanup_file=tmp_path / "cleanup.json", seen_file=tmp_path / "seen.json",
                   clock=lambda: 1_800_000_000.0)


def snap(**kw) -> Snapshot:
    return replace(Snapshot(), **kw)


def test_gosto_cinza(tmp_path):
    tz = make(tmp_path, {"ado": {"genres": ["j-rock", "anime"]}, "gojira": {"genres": ["metal"]},
                         "bbno$": {"genres": ["hip-hop", "pop"]}}, '[artistas]\n"bbno$" = -1\n').taste
    assert tz.affinity("Usseewa", "Ado") == 2
    assert tz.affinity("Silvera", "Gojira") == -1
    assert tz.affinity("Silvera (Orchestra)", "Gojira") == 1  # metal orquestrado sobe
    assert tz.affinity("Usseewa (sped up)", "Ado") == -2
    assert tz.affinity("Lalala", "bbno$") == -1  # ajuste do Pedro manda
    assert tz.affinity("x", "desconhecido") == 0


def test_musica_reage_no_rosto_e_fala_rara(tmp_path):
    r = make(tmp_path, {"ado": {"genres": ["anime"]}})
    r.observe(snap(), 0.0)
    r.observe(snap(track=Track("Usseewa", "Ado")), 1.0)
    cur = r.active(1.0)
    assert cur.name == "music_love" and cur.bob and cur.look == "player"
    assert r.caption(1.0) == "Agora sim."
    r.observe(snap(track=Track("Show", "Ado")), 100.0)
    assert r.active(100.0).name == "music_love"
    assert r.caption(100.0) is None  # comentário de música no máximo a cada 20 min


def test_artista_novo_curiosa(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), -1.0)
    r.observe(snap(track=Track("Faixa", "Banda Nova")), 0.0)
    assert r.active(0.0).name == "music_new"
    assert "Banda Nova" in r.caption(0.0)
    assert "banda nova" in json.loads((tmp_path / "seen.json").read_text())["artists"]


def test_hud_quente_noticia_e_faxina(tmp_path):
    r = make(tmp_path)
    r.observe(snap(cpu_temp=60.0), 0.0)
    r.observe(snap(cpu_temp=88.0), 1.0)
    assert r.active(1.0).name == "hot" and r.active(1.0).look == "magi"
    assert "88" in r.caption(1.0)
    r.observe(snap(cpu_temp=80.0), 2.0)  # histerese: ainda quente, não repete
    r.until = 0.0
    r.observe(snap(cpu_temp=80.0, news=[("10:00", "manchete")]), 3.0)
    assert r.active(3.0).name == "news"
    (tmp_path / "cleanup.json").write_text('{"at": "2026-10-07T03:00:00"}')
    r.until = 0.0
    r.observe(snap(cpu_temp=70.0, news=[("10:00", "manchete")]), 4.0 + LINE_GAP)
    assert r.active(4.0 + LINE_GAP).name == "cleanup"


def test_fps_caindo_e_cliques(tmp_path):
    r = make(tmp_path)
    r.observe(snap(gaming=True, fps=140.0, fps_avg=140.0), 0.0)
    r.observe(snap(gaming=True, fps=60.0, fps_avg=140.0), 1.0)
    assert r.active(1.0) is None
    r.observe(snap(gaming=True, fps=60.0, fps_avg=140.0), 2.0)
    assert r.active(2.0).name == "fps_drop"
    r.on_click("led", 10.0)
    assert r.active(10.0).name == "led" and r.active(10.0).effect == "bang"


def test_pular_tres_faixas_ela_oferece(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), -1.0)
    t = 0.0
    for i in range(3):
        r.observe(snap(track=Track(f"f{i}", "")), t)
        r.until = 0.0
        r.on_click("next", t + 5)
        t += 10
    assert r.active(t - 5).name == "skips"
    assert "coloca uma boa" in r.caption(t - 5)


def test_falando_cancela(tmp_path):
    r = make(tmp_path)
    r.on_click("led", 0.0)
    r.cancel()
    assert r.active(0.0) is None
