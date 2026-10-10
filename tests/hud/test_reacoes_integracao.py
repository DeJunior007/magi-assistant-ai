"""R1.6: integração da onda 1 — ``Reactor`` real (detectores e catálogo reais) + ``Snapshot`` sintético."""

from __future__ import annotations

import json
import random
import time
from dataclasses import replace

from wired import integration
from wired.main_screen import Snapshot, Track
from wired.reacoes import DETECTORES
from wired.reacoes.atividade import Atividade
from wired.reacoes.catalogo import ATIVAS
from wired.reactions import Reactor, Taste

RELOGIO = 1_800_000_000.0  # relógio de parede fixo (a hora vai explícita no observe)


class Gravador:
    """Embrulha os detectores reais e guarda o que cada tick devolveu (o governador decide depois)."""

    def __init__(self):
        self.disparos = []

    def embrulha(self, det):
        def f(anterior, snap, ctx):
            out = det(anterior, snap, ctx)
            self.disparos.extend(out or ())
            return out
        return f

    def chaves(self):
        return {(d.chave, d.variante) for d in self.disparos}


def make(tmp_path, gosto: str = "") -> tuple[Reactor, Gravador]:
    g = tmp_path / "genres.json"
    g.write_text(json.dumps({"ado": {"genres": ["j-rock"]}}), encoding="utf-8")
    t = tmp_path / "gosto.toml"
    t.write_text(gosto, encoding="utf-8")
    grav = Gravador()
    r = Reactor(Taste(g, t), cleanup_file=tmp_path / "cleanup.json", seen_file=tmp_path / "seen.json",
                clock=lambda: RELOGIO, rng=random.Random(1),
                detectores=[grav.embrulha(d) for d in DETECTORES], sortear=lambda ctx, agora, rng: None,
                registro_file=tmp_path / "reacoes.jsonl", atividade=Atividade(tmp_path / "ativ.json"))
    return r, grav


def aquece(r: Reactor, base: Snapshot | None = None) -> None:
    """1º tick só registra; o 2º dá o 1º tick dos detectores (``hud_acordou``, que o diretor toca
    depois dos 3 s de coalescência e acaba)."""
    for t in range(6):
        r.observe(base or Snapshot(), float(t), hour=12)


def snap(**kw) -> Snapshot:
    return replace(Snapshot(), **kw)


def faixa(title: str, artist: str, playing: bool = True) -> Track:
    return Track(title, artist, "", "", 0.0, 200.0, playing, None)


def tocadas(tmp_path) -> set[str]:
    p = tmp_path / "reacoes.jsonl"
    if not p.exists():
        return set()
    return {json.loads(x).get("chave") for x in p.read_text(encoding="utf-8").splitlines() if x.strip()}


def test_28_terceira_vez_no_dia_pelos_plays_do_reactor(tmp_path):
    r, grav = make(tmp_path)
    a, b = faixa("Unravel", "TK"), faixa("Outra", "TK")
    t = 0.0
    r.observe(snap(), t, hour=12)
    for i in range(3):
        for tr in (a, b):
            t += 60.0
            r.observe(snap(track=tr), t, hour=12)
            if tr is a:
                assert r.ctx["plays"] == i + 1  # o ctx tem os plays do dia do Reactor
    assert ("musica_repetida", None) in grav.chaves()
    assert sum(d.chave == "musica_repetida" for d in grav.disparos) == 2  # 1× por faixa (a e b)


def test_28_conta_do_reactor_vence_a_local(tmp_path):
    """Plays do dia vêm do ``Reactor`` (persistentes entre aberturas do detector), não da sessão."""
    r, grav = make(tmp_path)
    aquece(r)
    r._plays[("Unravel", "TK")] = 2  # já tocou 2× hoje, antes desta sessão do detector
    r._day = time.strftime("%Y%m%d", time.localtime(RELOGIO))
    r.observe(snap(track=faixa("Unravel", "TK")), 60.0, hour=12)
    assert r.ctx["plays"] == 3
    assert ("musica_repetida", None) in grav.chaves()


def test_33_artista_novo_pelo_seen_do_reactor(tmp_path):
    r, grav = make(tmp_path, '[artistas]\n"radwimps" = 2\n')
    aquece(r)
    r.observe(snap(track=faixa("Sparkle", "RADWIMPS")), 60.0, hour=12)
    assert r.ctx["artista_novo"] is True
    assert ("music_new", "amou") in grav.chaves()
    # artista já no _seen persistido (outra abertura do HUD): não é novo
    (tmp_path / "b").mkdir()
    r2, grav2 = make(tmp_path / "b", '[artistas]\n"radwimps" = 2\n')
    r2._seen.add("radwimps")
    aquece(r2)
    r2.observe(snap(track=faixa("Sparkle", "RADWIMPS")), 60.0, hour=12)
    assert r2.ctx["artista_novo"] is False
    assert ("music_new", "amou") not in grav2.chaves()


def test_64_terceiro_clique_no_led_e_66_com_musica(tmp_path):
    r, grav = make(tmp_path)
    r.atividade.evento(RELOGIO, "teste")  # o bom-dia de hoje já saiu
    aquece(r)
    for t in (30.0, 31.0, 32.0):
        r.on_click("led", t)
    assert [c for c, _ in r.ctx["cliques"]] == [30.0, 31.0, 32.0]
    for t in (32.5, 33.5, 34.5, 35.5):  # o diretor junta os disparos por 3 s
        r.observe(snap(), t, hour=12)
    assert ("led", None) in grav.chaves()
    assert "led" in tocadas(tmp_path)  # o governador aprovou e a sequência tocou

    (tmp_path / "m").mkdir()
    r, grav = make(tmp_path / "m")
    musica = snap(track=faixa("Sparkle", "RADWIMPS"))
    aquece(r, musica)
    r.on_click("led", 100.0)
    r.observe(musica, 100.5, hour=12)
    assert ("led", "fone") in grav.chaves()


def test_cliques_velhos_saem_do_ctx(tmp_path):
    r, _ = make(tmp_path)
    r.on_click("next", 0.0)
    r.on_click("led", 40.0)
    assert r.ctx["cliques"] == ((40.0, "led"),)


def test_clique_e_evento_real_e_vira_bom_dia(tmp_path):
    r, grav = make(tmp_path)
    r.observe(snap(), 0.0, hour=12)
    r.on_click("next", 5.0)
    assert r.atividade.parado_s(RELOGIO) == 0.0  # o clique ficou registrado
    r.observe(snap(), 6.0, hour=12)
    assert ("bom_dia", None) in grav.chaves()
    assert "volta_clique" not in r.ctx  # consumido pelo det_tempo


def test_75_head_novo_pelo_snapshot(tmp_path):
    r, grav = make(tmp_path)
    aquece(r, snap(git_head="abc1234"))
    r.observe(snap(git_head="abc1234"), 30.0, hour=12)
    assert ("ideia", None) not in grav.chaves()
    for t in (31.0, 32.0, 33.0, 34.0):  # o diretor junta os disparos por 3 s
        r.observe(snap(git_head="def5678"), t, hour=12)
    assert ("ideia", None) in grav.chaves()
    assert "ideia" in tocadas(tmp_path)


class _GitFalso:
    """``GitStatus`` falso: nunca roda ``git`` de verdade."""

    head: str | None = "abc1234"

    def poll(self, mono=None):
        return {"branch": "main", "added": 0, "removed": 0}


class _SemPlayer:
    active = False


class _RedeFalsa:
    down = up = 0.0
    down_series = ()

    def poll(self, now=None):
        pass


def test_integration_build_passa_o_head_do_gitstatus():
    git = _GitFalso()
    ui = integration.WiredUI(now_playing=_SemPlayer(), net=_RedeFalsa(), git=git)
    assert ui.build({}).git_head == "abc1234"
    git.head = None  # repositório sem commit
    assert ui.build({}).git_head is None


def test_marco_onda_1_ativas():
    assert len(ATIVAS) >= 87
