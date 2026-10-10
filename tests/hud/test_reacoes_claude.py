"""R1.5: detector do Claude Code (spec §5, acordo §1 52–56, 75, 82, 90) e ``GitStatus.head``."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from hud.wired import data
from hud.wired.main_screen import Snapshot, Track
from hud.wired.reacoes import catalogo, det_claude, diretor


def claude(n: int) -> SimpleNamespace:
    return SimpleNamespace(running=n)


class Sim:
    def __init__(self, **base):
        self.ctx: dict = {"agora": 0.0}
        self.base = {"cpu": 10.0, "claude": claude(0)} | base
        self.ant = None

    def tick(self, t: float, **campos) -> list[tuple[str, str | None]]:
        snap = Snapshot(**(self.base | campos))
        self.ctx["agora"] = t
        out = det_claude.detectar(self.ant, snap, self.ctx)
        self.ant = snap
        for d in out:
            k = (d.chave, d.variante) if d.variante else d.chave
            assert k in catalogo.ATIVAS or d.chave in diretor.ROTEIROS, k
        return [(d.chave, d.variante) for d in out]

    def rodar(self, t0: float, t1: float, passo: float = 10.0, **campos) -> list:
        out, t = [], t0
        while t <= t1:
            out += self.tick(t, **campos)
            t += passo
        return out


def test_52_claude_base_nao_sai_daqui():
    s = Sim()
    s.tick(0.0)
    assert ("claude", None) not in s.tick(1.0, claude=claude(1))  # fica no fire antigo


def test_53_terminou_depois_de_2_min():
    s = Sim()
    s.rodar(0.0, 130.0, claude=claude(1))
    out = det_claude.detectar(s.ant, Snapshot(**s.base), s.ctx | {"agora": 131.0})
    assert [(d.chave, d.variante) for d in out] == [("claude_terminou", None)]
    assert out[0].fmt["dur_s"] == 131.0  # V0.8b: a duração vai no fmt (sem regex no motivo)


def test_53_rodada_curta_nao_conta():
    s = Sim()
    s.rodar(0.0, 100.0, claude=claude(1))
    assert s.tick(101.0) == []


def test_56_demorando_15_min_uma_vez():
    s = Sim()
    out = s.rodar(0.0, 3600.0, claude=claude(2))
    assert out == [("claude", "demorando")]


def test_90_pesado_com_cpu_alta_no_lugar_do_56():
    s = Sim()
    out = s.rodar(0.0, 3600.0, claude=claude(1), cpu=85.0)
    assert out == [("claude", "pesado")]


def test_90_cpu_sobe_depois_do_56():
    s = Sim()
    out = s.rodar(0.0, 1000.0, claude=claude(1))
    out += s.rodar(1010.0, 1100.0, claude=claude(1), cpu=75.0)
    assert out == [("claude", "demorando"), ("claude", "pesado")]


def test_90_cpu_alta_curta_nao_conta():
    s = Sim()
    s.rodar(0.0, 900.0, claude=claude(1))  # 56 sai aqui
    out = s.tick(910.0, claude=claude(1), cpu=90.0) + s.tick(920.0, claude=claude(1))
    assert ("claude", "pesado") not in out


def test_82_claude_com_musica():
    s = Sim()
    s.tick(0.0, claude=claude(1))
    assert s.tick(1.0, claude=claude(1), track=Track("A", "x", playing=True)) == [("claude", "com_musica")]
    assert s.tick(2.0, claude=claude(1), track=Track("A", "x", playing=True)) == []
    s.tick(3.0, claude=claude(1), track=Track("A", "x", playing=False))
    assert s.tick(4.0, claude=claude(1), track=Track("A", "x", playing=True)) == []  # 1× por rodada


def test_82_ja_estava_junto_no_primeiro_tick_tambem_sai():
    s = Sim()
    assert s.tick(0.0, claude=claude(1), track=Track("A", "x", playing=True)) == [("claude", "com_musica")]


def test_82_musica_pausada_nao_conta():
    s = Sim()
    assert s.tick(0.0, claude=claude(1), track=Track("A", "x", playing=False)) == []


def test_75_head_mudou_ideia():
    s = Sim()
    s.ctx["git_head"] = "abc1234"
    assert s.tick(0.0) == []  # o 1º só registra
    assert s.tick(1.0) == []
    s.ctx["git_head"] = "def5678"
    assert s.tick(2.0) == [("ideia", None)]
    assert s.tick(3.0) == []


def test_75_head_pelo_snapshot():
    s = Sim()
    snap1 = SimpleNamespace(claude=claude(0), cpu=0.0, track=None, git_head="aaa")
    snap2 = SimpleNamespace(claude=claude(0), cpu=0.0, track=None, git_head="bbb")
    det_claude.detectar(None, snap1, s.ctx)
    out = det_claude.detectar(snap1, snap2, s.ctx)
    assert [(d.chave, d.variante) for d in out] == [("ideia", None)]


def test_sem_dado_do_claude_nao_quebra():
    s = Sim(claude=None)
    assert s.rodar(0.0, 2000.0) == []


def test_git_status_head_com_git_falso(monkeypatch):
    chamadas = []

    def run(cmd, **kw):
        chamadas.append(cmd[3:])
        saida = {("rev-parse", "--abbrev-ref", "HEAD"): "main\n",
                 ("rev-parse", "--short", "HEAD"): "a1b2c3d\n",
                 ("diff", "--numstat", "HEAD"): "1\t2\tx.py\n"}
        return subprocess.CompletedProcess(cmd, 0, saida[tuple(cmd[3:])], "")

    monkeypatch.setattr(data.subprocess, "run", run)
    g = data.GitStatus("/repo/falso")
    assert g.head is None
    assert g.poll(0.0) == {"branch": "main", "added": 1, "removed": 2}  # dict do poll não muda
    assert g.head == "a1b2c3d"


def test_git_status_head_sem_repo(monkeypatch):
    monkeypatch.setattr(data.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 128, "", "fatal"))
    g = data.GitStatus("/repo/falso")
    g.head = "velho"
    g.poll(0.0)
    assert g.head is None
