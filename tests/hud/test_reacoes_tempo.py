"""R1.4: atividade do Pedro e detector de tempo (spec §5, acordo §1 17–20/57–62, §2 I1/I2/I16/I17/I19)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from wired.main_screen import Snapshot, Track
from wired.reacoes import atividade, catalogo, det_tempo, governador
from wired.reacoes.atividade import Atividade
from wired.reacoes.contratos import Disparo

MIN = 60.0
H = 3600.0


def epoch(h: int, m: int = 0, dia: tuple[int, int, int] = (2026, 3, 10)) -> float:
    """Relógio de parede local (independe do fuso da máquina)."""
    return time.mktime((*dia, h, m, 0, 0, 0, -1))


def faixa(title: str = "A", playing: bool = True) -> Track:
    return Track(title=title, artist="X", playing=playing)


def claude(n: int) -> SimpleNamespace:
    return SimpleNamespace(running=n)


class Sim:
    """Roda o detector com o mesmo ``ctx``; ``t`` em segundos desde ``epoch(h0)``."""

    def __init__(self, tmp_path, h0: int = 10, m0: int = 0, dia=(2026, 3, 10), **ctx):
        self.t0 = epoch(h0, m0, dia)
        self.ativ = Atividade(tmp_path / "ativ.json")
        self.ctx: dict = {"atividade": self.ativ, "musica_nota": 0, "git": lambda: "2025-01-02"} | ctx
        self.ant = None
        self.campos: dict = {}

    def tick(self, t: float, **campos) -> list[tuple[str, str | None]]:
        self.campos |= campos
        snap = Snapshot(**self.campos)
        rel = self.t0 + t
        self.ctx.update(agora=t, relogio=rel, hora=time.localtime(rel).tm_hour, jogo=snap.gaming)
        out = det_tempo.detectar(self.ant, snap, self.ctx)
        self.ant = snap
        for d in out:  # toda chave emitida existe no catálogo e está ativa
            k = (d.chave, d.variante) if d.variante else d.chave
            assert k in catalogo.ATIVAS
        return [d.chave for d in out]

    def rodar(self, t0: float, t1: float, passo: float = 60.0, **campos) -> list[str]:
        out, t = [], t0
        while t <= t1:
            out += self.tick(t, **campos)
            t += passo
        return out


# --- atividade.py ---------------------------------------------------------------------------


def test_atividade_persiste_e_primeiro_do_dia(tmp_path):
    p = tmp_path / "a.json"
    a = Atividade(p)
    assert a.parado_s(epoch(9)) is None
    assert a.evento(epoch(4), "faixa") is False  # antes das 05h não é o bom-dia
    assert a.evento(epoch(9), "faixa") is True
    assert a.evento(epoch(9, 5), "claude") is False
    assert a.parado_s(epoch(9, 15)) == pytest.approx(600)
    b = Atividade(p)  # relê do arquivo
    assert b.parado_s(epoch(9, 15)) == pytest.approx(600)
    assert b.evento(epoch(10), "jogo") is False
    assert b.evento(epoch(9, dia=(2026, 3, 11)), "jogo") is True


def test_atividade_le_estado_file_na_hora(tmp_path, monkeypatch):
    a = Atividade()
    monkeypatch.setattr(atividade, "ESTADO_FILE", tmp_path / "x" / "estado.json")
    a.evento(epoch(9), "faixa")
    assert (tmp_path / "x" / "estado.json").exists()


def test_atividade_arquivo_ruim_vira_vazio(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("{nada")
    assert Atividade(p).parado_s(epoch(9)) is None


def test_eventos_deduzidos_do_snapshot():
    a = Snapshot()
    assert det_tempo.eventos(None, Snapshot(gaming=True)) == []
    assert det_tempo.eventos(a, Snapshot(track=faixa())) == ["faixa"]
    assert det_tempo.eventos(Snapshot(track=faixa()), Snapshot(track=faixa())) == []
    assert det_tempo.eventos(a, Snapshot(claude=claude(1))) == ["claude"]
    assert det_tempo.eventos(a, Snapshot(magui_state="listening")) == ["magui"]
    assert det_tempo.eventos(a, Snapshot(gaming=True)) == ["jogo"]


# --- CA-04: uma por linha ---------------------------------------------------------------------


def test_17_bocejo_quieta_10_min(tmp_path):
    s = Sim(tmp_path)
    assert "bocejo" not in s.rodar(0, 9 * MIN)
    assert s.rodar(10 * MIN, 12 * MIN).count("bocejo") == 1


def test_18_cochilo_quieta_25_min(tmp_path):
    s = Sim(tmp_path)
    out = s.rodar(0, 30 * MIN)
    assert out.count("cochilo") == 1


@pytest.mark.parametrize("campos, nota", [
    ({"gaming": True}, 0),
    ({"claude": claude(1)}, 0),
    ({}, 1),
])
def test_18_nunca_com_jogo_claude_ou_musica_boa(tmp_path, campos, nota):
    s = Sim(tmp_path, h0=2, musica_nota=nota)
    s.tick(0)
    out = s.rodar(MIN, 4 * H, **campos)
    assert not {"bocejo", "cochilo", "cabeca_pesada"} & set(out)
    # e o governador também barra o 18 se algum detector pedir
    ctx = {"defs": catalogo.DEFS, "jogo": bool(campos.get("gaming")), "claude": "claude" in campos,
           "musica_nota": nota, "hora": 2}
    assert governador.escolher([Disparo("cochilo", "t")], 0.0, ctx) is None


def test_19_cabeca_pesada_sessao_longa_de_madrugada(tmp_path):
    s = Sim(tmp_path, h0=0)
    s.tick(0)
    out = []
    for i in range(1, 7):  # Pedro mexendo (Magui ouvindo) a cada 25 min, nada tocando
        out += s.tick(i * 25 * MIN, magui_state="listening")
        out += s.tick(i * 25 * MIN + 30, magui_state="sleeping")
    out += s.rodar(151 * MIN, 155 * MIN)
    assert out.count("cabeca_pesada") == 1


def test_20_sobressalto_evento_depois_do_cochilo(tmp_path):
    s = Sim(tmp_path)
    s.tick(0)
    s.ativ.evento(s.t0, "clique")  # já houve o bom-dia
    assert "cochilo" in s.rodar(MIN, 26 * MIN)
    assert s.tick(27 * MIN, track=faixa()) == ["sobressalto"]


def test_57_bom_dia_primeiro_evento_depois_das_5h(tmp_path):
    s = Sim(tmp_path, h0=4, m0=50)
    s.tick(0)
    assert "bom_dia" not in s.tick(MIN, track=faixa("a"))  # 04h51: ainda não
    assert "bom_dia" in s.tick(15 * MIN, track=faixa("b"))  # 05h05
    assert "bom_dia" not in s.tick(20 * MIN, track=faixa("c"))


def test_58_almoco(tmp_path):
    s = Sim(tmp_path, h0=11, m0=58)
    s.tick(0, claude=claude(1))
    assert "almoco" not in s.tick(MIN)
    out = s.rodar(3 * MIN, 30 * MIN)
    assert out.count("almoco") == 1


def test_59_meia_noite(tmp_path):
    s = Sim(tmp_path, h0=23, m0=58, claude=None)
    s.tick(0, track=faixa())
    assert s.rodar(MIN, 4 * MIN).count("meia_noite") == 1


def test_60_madrugada_pesada(tmp_path):
    s = Sim(tmp_path, h0=2, m0=58)
    s.tick(0, claude=claude(1))
    assert s.rodar(MIN, 20 * MIN).count("madrugada") == 1


def test_61_pausa_sessao_de_2h(tmp_path):
    s = Sim(tmp_path, h0=14)
    out = s.rodar(0, 2 * H + 5 * MIN, claude=claude(1))
    assert out.count("long_session") == 1
    assert "long_session" not in s.rodar(2 * H + 6 * MIN, 2 * H + 20 * MIN)  # 1×/sessão
    s.rodar(2 * H + 21 * MIN, 2 * H + 55 * MIN, claude=claude(0))  # pausa de 34 min
    out = s.rodar(2 * H + 56 * MIN, 5 * H, claude=claude(1))
    assert out.count("long_session") == 1  # sessão nova


def test_61_nao_sai_com_jogo(tmp_path):
    s = Sim(tmp_path, h0=14)
    assert "long_session" not in s.rodar(0, 3 * H, gaming=True)


def test_62_sentiu_falta_depois_de_2h(tmp_path):
    s = Sim(tmp_path, h0=9)
    s.tick(0)
    assert s.tick(MIN, track=faixa("a")) == ["bom_dia"]
    s.tick(2 * MIN, track=None)
    s.rodar(3 * MIN, 2 * H + 5 * MIN, passo=5 * MIN, magui_state="speaking")  # nenhum evento
    assert "sentiu_falta" in s.tick(2 * H + 10 * MIN, track=faixa("b"), magui_state="sleeping")


def test_I1_fim_de_expediente(tmp_path):
    s = Sim(tmp_path, h0=16)
    s.rodar(0, 2 * H + 30 * MIN, passo=5 * MIN, claude=claude(1))  # até 18h30
    assert "fim_expediente" in s.tick(2 * H + 31 * MIN, claude=claude(0))


def test_I1_nao_antes_das_18h(tmp_path):
    s = Sim(tmp_path, h0=9)
    s.rodar(0, 2 * H + 30 * MIN, passo=5 * MIN, claude=claude(1))
    assert "fim_expediente" not in s.tick(2 * H + 31 * MIN, claude=claude(0))


def test_I2_boa_noite(tmp_path):
    s = Sim(tmp_path, h0=0, m0=30)
    s.tick(0, track=faixa())
    s.tick(MIN, track=faixa(playing=False))
    assert s.rodar(2 * MIN, 15 * MIN).count("boa_noite") == 1


def test_I16_silencio_longo(tmp_path):
    s = Sim(tmp_path, h0=1)
    out = s.rodar(0, 45 * MIN)
    assert out.count("silencio_longo") == 1


def test_I17_ei_to_aqui(tmp_path):
    s = Sim(tmp_path, h0=10)
    out = s.rodar(0, 3 * H, passo=5 * MIN)
    assert out.count("ei_to_aqui") == 2  # 40 min e +2 h


def test_I19_aniversario_dela(tmp_path):
    chamadas = []

    def git():
        chamadas.append(1)
        return "2025-03-10"

    s = Sim(tmp_path, h0=9, git=git)
    out = s.rodar(0, 30 * MIN, claude=claude(1))
    assert out.count("aniversario_dela") == 1
    assert len(chamadas) == 1  # data lida uma vez


def test_I19_outro_dia_nao(tmp_path):
    s = Sim(tmp_path, h0=9, git=lambda: "2025-07-01")
    assert "aniversario_dela" not in s.rodar(0, 10 * MIN, claude=claude(1))


def test_git_primeiro_commit_falso(monkeypatch):
    def run(*a, **k):
        return SimpleNamespace(returncode=0, stdout="2025-01-02\n2025-01-03\n")

    monkeypatch.setattr(det_tempo.subprocess, "run", run)
    assert det_tempo.git_primeiro_commit() == "2025-01-02"


# --- volta fura a cota (governador real) ------------------------------------------------------


@pytest.mark.parametrize("chave", ["sobressalto", "bom_dia", "sentiu_falta"])
def test_volta_toca_com_cota_cheia(chave):
    est = governador.Estado()
    est.ativas = [100.0 + i for i in range(governador.ATIVAS_POR_HORA)]
    ctx = {"defs": catalogo.DEFS, "estado": est, "hora": 10, "parada": True}
    assert governador.escolher([Disparo("almoco", "x")], 200.0, ctx) is None  # cota cheia
    d = governador.escolher([Disparo(chave, "volta")], 200.0, ctx)
    assert d is not None and d.chave == chave
