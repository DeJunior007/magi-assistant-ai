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


# ------------------------------------------------------------ V1.7: placar, sem sentido, torcida


def _pontos(tmp_path) -> list[dict]:
    return [x for x in linhas(tmp_path) if x.get("tipo") == "placar"]


def test_partida_limpa_vira_ponto_dele_com_ref_e_vai_ao_estado(tmp_path):
    r = make(tmp_path, detectores=DETECTORES)
    r.observe(snap(), 0.0, 15)
    jogo = snap(gaming=True)
    for t in range(1, 16 * 60 + 2, 5):
        r.observe(jogo, float(t), 15)
    r.observe(snap(), 16 * 60 + 5.0, 15)
    ps = _pontos(tmp_path)
    assert [p["causa"] for p in ps] == ["placar:ele_partida_limpa"]
    assert ps[0]["placar"]["lado"] == "ele" and ps[0]["placar"]["ref"].endswith("#game_off")
    assert r.placar_resumo()["texto"].startswith("Condessa 0 × 1 Pedro")
    r._salvo_em = -1e18
    r.observe(snap(), 16 * 60 + 6.0, 15)
    dados = json.loads((tmp_path / "estado.json").read_text())
    assert set(dados) >= {"placar", "sem_sentido", "torcida"}
    assert make(tmp_path).placar.hoje(r._rel(16 * 60 + 6.0)) == (0, 1)


def test_partida_curta_e_limpa_nao_conta(tmp_path):
    r = make(tmp_path, detectores=DETECTORES)
    r.observe(snap(), 0.0, 15)
    for t in range(1, 120, 5):
        r.observe(snap(gaming=True), float(t), 15)
    r.observe(snap(), 125.0, 15)
    assert _pontos(tmp_path) == []


def test_truque_ignorado_vira_ponto_dele(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    r.diretor.truque_em = r._rel(0.0)
    for t in range(1, 20):
        r.observe(snap(), float(t), 15)
    ps = _pontos(tmp_path)
    assert [p["causa"] for p in ps] == ["placar:ele_truque_ignorado"]
    assert ps[0]["placar"]["ref"].endswith("#truque:ignorado")


def test_faixa_nota2_ate_o_fim_e_pulo(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    r.ctx["_musica_fim"] = {"faixa": ("A", "B"), "nota": 2, "ate_fim": True, "pulo": False,
                            "especial": True}
    r.observe(snap(), 1.0, 15)
    r.ctx["_musica_fim"] = {"faixa": ("C", "D"), "nota": 2, "ate_fim": False, "pulo": True}
    r.observe(snap(), 2.0, 15)
    assert [p["causa"] for p in _pontos(tmp_path)] == [
        "placar:ele_faixa_nota2", "placar:ela_favorita_ado", "placar:ela_pulo_nota2"]


def test_marca_sem_sentido_vira_fator_no_sorteio(tmp_path):
    vistos: list = []

    def sortear(ctx, agora, rng, fatores=None):
        vistos.append(fatores)

    r = make(tmp_path, sortear=sortear)
    r.observe(snap(), 0.0, 15)
    r.observe(snap(), 1.0, 15)
    alvo = {"t": 1.0, "chave": "sorriso_canto", "variante": None, "tipo": "gesto",
            "momento": str(r.momento)}
    linha = r.marcar_sem_sentido(alvo, "hover", 2.0)
    assert linha["alvo"]["chave"] == "sorriso_canto" and r.ajustes() == 1
    assert r.active(2.0) is not None  # o "hm… anotado"
    assert (tmp_path / "reacoes" / "sem-sentido.jsonl").exists()  # o conftest isola
    for t in range(3, 30):
        r.observe(snap(), float(t), 15)
    assert {"sorriso_canto": 0.7} in vistos


def test_atalho_marca_a_ultima_expressao_e_desfaz(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    assert r.marcar_sem_sentido(gesto="atalho")["alvo"] == "nenhum"
    r._log("gesto", "sorriso_canto", "x", 1.0)
    alvo = r.ultimas_expressoes()[-1]
    assert alvo["chave"] == "sorriso_canto" and alvo["tipo"] == "gesto"
    (tmp_path / "b").mkdir()
    r2 = make(tmp_path / "b")
    r2._expressoes = [alvo]
    assert r2.marcar_sem_sentido(None, "atalho")["alvo"]["chave"] == "sorriso_canto"
    assert "desfeito" in r2.marcar_sem_sentido(None, "atalho")  # o mesmo alvo em ≤ 5 s desfaz


def test_piso_da_torcida_dispara_em_jogando(tmp_path):
    r = make(tmp_path)
    r.observe(snap(), 0.0, 15)
    jogo = snap(gaming=True)
    r.torcida._acum = 46 * 60.0
    for t in range(1, 180):
        r.observe(jogo, float(t), 15)
    assert r.momento == Momento.JOGANDO
    ts = [x for x in linhas(tmp_path) if x["chave"] == "torcida"]
    assert ts and ts[0]["causa"].startswith("jogando_sem_positiva:")
    assert r.torcida.minutos(r._rel(179.0)) < 5  # zerou


def test_volta_aplica_delta_pelo_degrau():
    d = Disparo("sentiu_falta", "voltou depois de 0.30 h", None, {"fora_s": 1080.0})
    a = Reactor._adaptar(d)
    assert a.chave == "pedro_voltou" and a.fmt["fora_s"] == 1080.0
    assert Reactor._evento(a) is None  # o Δ sai na cena, pelo degrau
