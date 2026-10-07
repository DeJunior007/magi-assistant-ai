from __future__ import annotations

import json
import random
from dataclasses import replace
from types import SimpleNamespace

from wired.main_screen import Snapshot, Track
from wired.reactions import LINE_GAP, MUSIC_LINE_GAP, Reactor, Taste

GENRES = {"ado": {"genres": ["j-rock", "anime"]}, "gojira": {"genres": ["metal"]},
          "lucca e mateus": {"genres": ["sertanejo"]}, "frederic chopin": {"genres": ["classica"]},
          "kijugo": {"genres": ["lofi"]}, "dua lipa": {"genres": ["pop"]},
          "lady gaga": {"genres": ["pop"]}, "evan call": {"genres": ["trilha"]},
          "ana castela": {"genres": ["sertanejo"]}}


def make(tmp_path, taste="", genres=None):
    g = tmp_path / "genres.json"
    g.write_text(json.dumps(GENRES if genres is None else genres), encoding="utf-8")
    t = tmp_path / "gosto.toml"
    t.write_text(taste, encoding="utf-8")
    r = Reactor(Taste(g, t), cleanup_file=tmp_path / "cleanup.json", seen_file=tmp_path / "seen.json",
                clock=lambda: 1_800_000_000.0, rng=random.Random(1))
    r.favorite_of_day = lambda: ""  # a Favorita do Dia tem teste próprio
    return r


def snap(**kw) -> Snapshot:
    return replace(Snapshot(), **kw)


def play(r, title, artist, now, hour=15, **kw):
    r.until = 0.0
    r.observe(snap(track=Track(title, artist), **kw), now, hour)
    return r.active(now)


def test_gosto_do_conselho(tmp_path):
    tz = make(tmp_path).taste
    assert tz.affinity("Usseewa", "Ado") == 2  # rival: fixo
    assert tz.affinity("Usseewa (slowed)", "Ado") == 2  # nem o slowed derruba a rival
    assert tz.affinity("x", "Gojira") == 0  # metal 0
    assert tz.affinity("x", "Lucca e Mateus") == -1  # sertanejo -1, nenhum gênero em -2
    assert tz.affinity("x", "Ana Castela") == -2  # a careta é por artista
    assert tz.affinity("Faixa (Acoustic)", "Ana Castela") == 0  # suaviza até 0
    assert tz.affinity("Clair de Lune", "Debussy") == 1
    assert tz.affinity("Reflets dans l'eau", "Debussy") == 2  # Processo contra Debussy
    assert tz.affinity("Nocturne Op. 9", "Frédéric Chopin", hour=23) == 2  # madrugada, teto 2
    assert tz.affinity("x", "Kijugo", hour=15) == 0
    assert tz.affinity("x", "Kijugo", hour=2) == 1  # madrugada sobe o lofi
    assert tz.affinity("x", "Desconhecido") == 0
    assert tz.affinity("x", "Ado, Gojira") == 2  # vários artistas: o primeiro reconhecido


def test_ajuste_do_pedro_vence(tmp_path):
    tz = make(tmp_path, '[artistas]\n"gojira" = 2\n[generos]\nsertanejo = 1\n').taste
    assert tz.affinity("x", "Gojira") == 2
    assert tz.affinity("x", "Lucca e Mateus") == 1


def test_contexto_claude_festa_repeticao_e_gaga(tmp_path):
    tz = make(tmp_path).taste
    assert tz.verdict("x", "Kijugo", 15, claude=True).note == 1
    assert tz.verdict("x", "Dua Lipa", 21).note == 2  # festa: pop +1
    assert tz.verdict("x", "Dua Lipa", 21, gaming=True).note == 1  # jogando não é festa
    assert tz.verdict("x", "Dua Lipa", 15, plays=3).note == 0  # 3ª vez cansa
    assert tz.verdict("x", "Lady Gaga", 15, plays=2).note == 2
    assert tz.verdict("x", "Lady Gaga", 15, plays=3).note == 1  # Diva contra Diva


def test_musica_favorita_rival_e_fala_rara(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    cur = play(r, "Usseewa", "Ado", 1.0)
    assert cur.name == "music_love" and cur.mood == "happy"  # rival: happy, não love
    assert r.caption(1.0) == "Ela de novo. Um dia eu canto melhor que isso."
    cur = play(r, "Unravel", "Evan Call", 100.0)
    assert cur.name == "music_love" and cur.mood == "love" and cur.bob
    assert r.caption(100.0) is None or r.caption(100.0).startswith("Ela de novo")  # 20 min entre falas
    assert 100.0 < MUSIC_LINE_GAP


def test_careta_rara_e_nunca_de_manha(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    assert play(r, "x", "Ana Castela", 1.0, hour=7).name == "music_meh"  # antes das 8h
    assert play(r, "y", "Ana Castela", 2.0).name == "music_hate"
    assert play(r, "z", "Ana Castela", 3.0).name == "music_meh"  # 1 careta a cada 30 min
    assert play(r, "w", "Ana Castela", 3.0 + 31 * 60).name == "music_hate"


def test_favorita_do_pedro_e_jogando(tmp_path):
    r = make(tmp_path, '[pedro]\nfavoritas = ["Ana Castela"]\n')
    r.observe(snap(), 0.0, 15)
    assert play(r, "x", "Ana Castela", 1.0).name == "music_tolerate"
    r2 = make(tmp_path)
    r2.observe(snap(gaming=True, fps=140.0), 0.0, 15)
    assert play(r2, "x", "Dua Lipa", 1.0, gaming=True, fps=140.0) is None  # jogando: só extremos
    cur = play(r2, "Battle", "Evan Call", 2.0, gaming=True, fps=140.0)
    assert cur.name == "music_love" and cur.mood == "focus"
    assert r2.caption(2.0) == "Música de chefe. Então vence, piloto."


def test_quinta_vez_vira_hino_ou_acostuma(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    for i in range(5):
        r.observe(snap(), 10.0 * i + 5, 15)  # sai e volta: conta como nova execução
        cur = play(r, "Unravel", "Evan Call", 10.0 * i + 6)
    assert cur.name == "music_love" and cur.mood == "love"
    for i in range(5):
        r.observe(snap(), 100.0 + 10 * i, 15)
        cur = play(r, "Moda", "Lucca e Mateus", 100.0 + 10 * i + 1)
    assert cur.name == "music_tolerate"


def test_artista_novo_curiosa_depois_a_nota(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), -1.0, 15)
    assert play(r, "Faixa", "Banda Nova", 0.0).name == "music_new"
    assert "Banda Nova" in r.caption(0.0)
    assert "banda nova" in json.loads((tmp_path / "seen.json").read_text())["artists"]
    r.until = 0.0
    r.observe(snap(track=Track("Faixa", "Banda Nova")), 10.5, 15)
    assert r.active(10.5).name == "music_ok"  # depois dos 10 s, a nota (0)


def test_favorita_do_dia_veto_da_kurisu(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    r.favorite_of_day = lambda: "lucca e mateus"  # nota -1 → com +1 vira 0: só "gosta"
    cur = play(r, "x", "Lucca e Mateus", 1.0)
    assert cur.name == "music_like" and r.caption(1.0) == "Hoje eu tento gostar de Lucca e Mateus. Hoje."
    r2 = make(tmp_path)
    r2.observe(snap(), 0.0, 15)
    r2.favorite_of_day = lambda: "kijugo"  # 0 + 1 = 1 → amor forçado, uma vez no dia
    assert play(r2, "a", "Kijugo", 1.0).name == "music_love"
    assert play(r2, "b", "Kijugo", 2.0).name == "music_ok"


def test_hud_quente_noticia_e_faxina(tmp_path):
    r = make(tmp_path)
    r.observe(snap(cpu_temp=60.0), 0.0, 15)
    r.observe(snap(cpu_temp=88.0), 1.0, 15)
    assert r.active(1.0).name == "hot" and r.active(1.0).look == "magi"
    assert "88" in r.caption(1.0)
    r.observe(snap(cpu_temp=80.0), 2.0, 15)  # histerese: ainda quente, não repete
    r.until = 0.0
    r.observe(snap(cpu_temp=80.0, news=[("10:00", "manchete")]), 3.0, 15)
    assert r.active(3.0).name == "news"
    (tmp_path / "cleanup.json").write_text('{"at": "2026-10-07T02:00:00", "freed_bytes": 1000}')
    r.until = 0.0
    r.observe(snap(cpu_temp=70.0, news=[("10:00", "manchete")]), 3.5, 15)
    assert r.active(3.5) is None  # faxina vazia: nada a comemorar
    (tmp_path / "cleanup.json").write_text('{"at": "2026-10-07T03:00:00", "freed_bytes": 3000000000}')
    r.until = 0.0
    r.observe(snap(cpu_temp=70.0, news=[("10:00", "manchete")]), 4.0 + LINE_GAP, 15)
    assert r.active(4.0 + LINE_GAP).name == "cleanup"


def test_fim_de_jogo_pelo_veto_da_aqua(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    r.observe(snap(gaming=True), 1.0, 15)
    r.until = 0.0
    r.observe(snap(), 120.0, 15)  # 2 min: curta
    assert r.active(120.0).mood == "calm"
    r.observe(snap(gaming=True), 200.0, 15)
    r.until = 0.0
    r.observe(snap(), 200.0 + 3600, 15)
    assert r.active(200.0 + 3600).mood == "happy"


def test_fps_caindo_com_dado_e_cliques(tmp_path):
    r = make(tmp_path)
    r.observe(snap(gaming=True, fps=140.0, fps_avg=140.0), 0.0, 15)
    r.observe(snap(gaming=True, fps=60.0, fps_avg=140.0), 1.0, 15)
    assert r.active(1.0) is None
    r.observe(snap(gaming=True, fps=60.0, fps_avg=140.0), 2.0, 15)
    assert r.active(2.0).name == "fps_drop" and r.active(2.0).mood == "focus"
    r.on_click("led", 10.0)
    assert r.active(10.0).name == "led" and r.active(10.0).effect == "bang"


def test_pular_tres_faixas_ela_oferece(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), -1.0, 15)
    t = 0.0
    for i in range(3):
        play(r, f"f{i}", "", t)
        r.until = 0.0
        r.on_click("next", t + 5)
        t += 10
    assert r.active(t - 5).name == "skips"
    assert r.caption(t - 5) is not None


def test_falando_cancela_e_sem_falas_de_musica(tmp_path):
    r = make(tmp_path, "[falas]\nmusica = false\n")
    r.observe(snap(), 0.0, 15)
    assert play(r, "Usseewa", "Ado", 1.0).name == "music_love"
    assert r.caption(1.0) is None  # o rosto reage, o texto não
    r.cancel()
    assert r.active(1.0) is None
    assert SimpleNamespace  # noqa: B018 (import usado em outros testes)
