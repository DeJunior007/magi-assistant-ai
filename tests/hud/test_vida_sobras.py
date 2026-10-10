"""V0.8b: sobras da ligação — sinais do ``ctx`` (Claude esperando, LM, dançante, água, contadores),
a escada do Tédio de ponta a ponta no ``Reactor`` e a tabela ``[vida.momentos]`` no gosto."""

from __future__ import annotations

import random
import tomllib
from pathlib import Path
from types import SimpleNamespace

from wired.data import ClaudeView
from wired.main_screen import Snapshot, Track
from wired.reacoes import det_claude, momento, passivas
from wired.reacoes.contratos import Disparo
from wired.reacoes.vida import VIDA_PADRAO, Momento

from .test_vida_integracao import RELOGIO, linhas, make, snap

GOSTO = Path(__file__).resolve().parents[2] / "persona" / "condessa-gosto.toml"


class Presente:
    """Atividade de teste: o Pedro está aí (parado há ``s`` segundos)."""

    def __init__(self, s: float = 0.0) -> None:
        self.s = s

    def parado_s(self, agora: float) -> float:
        return self.s

    def evento(self, agora: float, tipo: str) -> bool:
        return False


# ------------------------------------------------------------ det_claude


def _claude(running: int, ev=None) -> Snapshot:
    return Snapshot(cpu=10.0, claude=SimpleNamespace(running=running, last_event=ev))


def test_claude_terminou_leva_dur_s_no_fmt():
    ctx: dict = {"agora": 0.0}
    det_claude.detectar(None, _claude(1), ctx)
    out = det_claude.detectar(_claude(1), _claude(0), ctx | {"agora": 400.0})
    assert [(d.chave, d.fmt["dur_s"]) for d in out] == [("claude_terminou", 400.0)]


def test_claude_esperando_do_notify_ate_o_proximo_evento():
    ctx: dict = {"agora": 0.0, "relogio": 1000.0}
    det_claude.detectar(None, _claude(1), ctx)
    assert ctx["claude_esperando"] is False
    det_claude.detectar(None, _claude(1, (1000.0, "notify", "p")), ctx)
    assert ctx["claude_esperando"] is True
    ctx["relogio"] = 1010.0
    det_claude.detectar(None, _claude(1, (1000.0, "notify", "p")), ctx)  # mesmo evento: segue
    assert ctx["claude_esperando"] is True
    det_claude.detectar(None, _claude(1, (1005.0, "stop", "p")), ctx)
    assert ctx["claude_esperando"] is False


def test_claude_esperando_vence_depois_de_meia_hora():
    ctx: dict = {"agora": 0.0, "relogio": 1000.0}
    det_claude.detectar(None, _claude(1, (1000.0, "notify", "p")), ctx)
    ctx["relogio"] = 1000.0 + det_claude.ESPERA_MAX_S + 1
    det_claude.detectar(None, _claude(1, (1000.0, "notify", "p")), ctx)
    assert ctx["claude_esperando"] is False


def test_reactor_esperando_vira_momento_e_causa_e_franja_uma_por_espera(tmp_path):
    def sortear(ctx, agora, rng):
        if ctx.get("momento") == Momento.ESPERANDO and not ctx.get("franja_na_espera"):
            return Disparo("soprando_franja", "teste")
        return None

    r = make(tmp_path, detectores=[det_claude.detectar], sortear=sortear)
    r.atividade = Presente()
    ev = ClaudeView(running=1, last_event=(RELOGIO, "notify", "p"))
    r.observe(snap(claude=ClaudeView(running=1)), 0.0, 15)
    for t in range(1, 120):
        r.observe(snap(claude=ev), float(t), 15)
    assert r.momento == Momento.ESPERANDO
    assert r.ctx["claude_esperando"] and "claude_esperando" in r.diretor.causas
    gestos = [x["chave"] for x in linhas(tmp_path) if x["tipo"] == "gesto"]
    assert gestos.count("soprando_franja") == 1 and r.ctx["franja_na_espera"] is True


# ------------------------------------------------------------ LM, dançante, água, cantando


def test_lm_on_vem_do_snapshot_e_da_estudando(tmp_path):
    r = make(tmp_path)
    r.atividade = Presente()
    r.observe(snap(lm_on=True), 0.0, 15)
    r.observe(snap(lm_on=True), 1.0, 15)
    assert r.ctx["lm_on"] is True and r.momento == Momento.ESTUDANDO
    r.observe(snap(), 2.0, 15)
    assert r.ctx["lm_on"] is False


def test_dancante_e_faixa_agua_no_ctx(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    chuva = snap(track=Track("Rain Dance", "Ado"))  # Ado: j-rock no genres.json do teste
    r.observe(chuva, 1.0, 15)
    assert r.ctx["dancante"] is True and r.ctx["faixa_agua"] == "Rain Dance"
    r.observe(snap(track=Track("Quiet", "Desconhecido")), 2.0, 15)
    assert r.ctx["dancante"] is False and r.ctx["faixa_agua"] is None
    r.observe(snap(), 3.0, 15)
    assert r.ctx["dancante"] is False and r.ctx["faixa_agua"] is None


def test_cantando_e_franja_por_faixa_zeram_na_troca(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    a = snap(track=Track("A", "Ado"))
    r.observe(a, 1.0, 15)
    r._marcar("cantando_junto", r.ctx, 1.0, 1.0)  # noqa: SLF001
    r._marcar("soprando_franja", r.ctx, 1.0, 1.0)  # noqa: SLF001
    r.observe(a, 2.0, 15)
    assert r.ctx["cantando_na_faixa"] is True and r.ctx["franja_na_faixa"] is True
    r.observe(snap(track=Track("B", "Ado")), 3.0, 15)
    assert r.ctx["cantando_na_faixa"] is False and r.ctx["franja_na_faixa"] is False


# ------------------------------------------------------------ escada do Tédio


def _tedio(tmp_path, ate_s: float, passo: float = 5.0, clique_no_ei: bool = False):
    r = make(tmp_path, sortear=passivas.sortear)
    r.rng = random.Random(7)
    r.atividade = Presente()
    t = 0.0
    while t <= ate_s:
        r.observe(snap(), t, 15)
        if clique_no_ei and r._marcas.get("ei_pendente") is not None:  # noqa: SLF001
            r.on_click("portrait", t + 1.0)
        t += passo
    return r, [x for x in linhas(tmp_path) if x["tipo"] == "gesto"]


def test_escada_do_tedio_de_ponta_a_ponta(tmp_path):
    """Tédio: encarando (1×, ≥ 15 min) → ei_to_aqui (≥ 30 min) → beicinho só com o ei ignorado."""
    r, gestos = _tedio(tmp_path, 3 * 3600.0)
    assert r.momento == Momento.TEDIO
    chaves = [g["chave"] for g in gestos]
    t_de = {c: [i for i, k in enumerate(chaves) if k == c] for c in ("encarando", "ei_to_aqui", "beicinho")}
    assert len(t_de["encarando"]) == 1
    assert t_de["ei_to_aqui"] and t_de["encarando"][0] < t_de["ei_to_aqui"][0]
    assert t_de["beicinho"] and t_de["beicinho"][0] > t_de["ei_to_aqui"][0]
    assert all(g["momento"] == "tedio" for g in gestos if g["chave"] in t_de)
    assert "ignorada" in r.diretor.causas  # a causa da negativa
    assert chaves  # e a vida seguiu com as outras do grupo


def test_escada_sem_beicinho_quando_o_pedro_responde(tmp_path):
    r, gestos = _tedio(tmp_path, 3 * 3600.0, clique_no_ei=True)
    chaves = [g["chave"] for g in gestos]
    assert "ei_to_aqui" in chaves and "beicinho" not in chaves
    assert "ignorada" not in r.diretor.causas


# ------------------------------------------------------------ [vida.momentos]


def test_vida_momentos_no_gosto_e_no_padrao():
    gosto = tomllib.loads(GOSTO.read_text(encoding="utf-8"))["vida"]["momentos"]
    assert gosto == VIDA_PADRAO["momentos"] == momento.LIMIARES_PADRAO


def test_momento_le_o_limiar_do_taste_vida(tmp_path):
    r = make(tmp_path)
    r.taste.taste_file.write_text("[vida.momentos]\ntedio_sem_musica_s = 60\n", encoding="utf-8")
    vida = r.taste.vida()
    assert momento.limiar({"vida": vida}, "tedio_sem_musica_s") == 60
    assert momento.limiar({"vida": vida}, "pedro_sumiu_s") == 600  # o resto vem do padrão
