"""O1.1 — Gestos (CA-O2), snapshot leve + reações (CA-O5), hud_aberto (D2) e jogo_aberto (D3)."""

import fcntl
import json
import random
import types

import pytest
from wired import overlay
from wired.overlay import Gestos


class Rec:
    def __init__(self):
        self.eventos: list[tuple[str, str, float]] = []
        self.g = Gestos(lambda alvo, t: self.eventos.append(("click", alvo, t)),
                        lambda ev, t: self.eventos.append(("hover", ev, t)))

    def nomes(self) -> list[str]:
        return [f"{k}:{v}" for k, v, _ in self.eventos]


# --- CA-O2 ---------------------------------------------------------------------------------------


def test_simples_sai_so_quando_vence_a_espera():
    r = Rec()
    r.g.press(10, 10, False, 1.0)
    r.g.release(1.1)
    r.g.tick(1.2)
    assert r.eventos == []  # ainda na espera do duplo
    r.g.tick(1.1 + 0.25)
    assert r.eventos == [("click", "face", 1.35)]
    r.g.tick(2.0)
    assert r.nomes() == ["click:face"]  # uma vez só


def test_duplo_nao_da_clique():
    r = Rec()
    r.g.press(10, 10, False, 1.0)
    r.g.release(1.05)
    r.g.press(10, 10, False, 1.2)
    r.g.release(1.25)
    r.g.tick(5.0)
    assert r.nomes() == ["hover:dbl"]


def test_press_depois_da_espera_sem_tick_e_dois_simples():
    r = Rec()
    r.g.press(10, 10, False, 1.0)
    r.g.release(1.05)
    r.g.press(10, 10, False, 2.0)  # tick atrasou: o 1º simples sai aqui, não vira duplo
    r.g.release(2.05)
    r.g.tick(3.0)
    assert r.nomes() == ["click:face", "click:face"]


def test_longo():
    r = Rec()
    r.g.press(10, 10, True, 1.0)
    r.g.release(1.0 + Gestos.LONG_S)
    r.g.tick(5.0)
    assert r.nomes() == ["hover:long"]


def test_arrasto_no_alto_uma_vez_e_sem_clique():
    r = Rec()
    r.g.press(10, 10, True, 1.0)
    r.g.move(20, 10, True, 1.1)  # 10 px: ainda não
    r.g.move(10, 28, True, 1.2)  # 18 px
    r.g.move(60, 60, True, 1.3)
    r.g.release(1.4)
    r.g.tick(5.0)
    assert r.nomes().count("hover:arrasto") == 1
    assert "click:face" not in r.nomes()


def test_arrasto_embaixo_nao_conta():
    r = Rec()
    r.g.press(10, 10, False, 1.0)
    r.g.move(80, 80, True, 1.1)
    r.g.release(1.2)
    r.g.tick(5.0)
    assert "hover:arrasto" not in r.nomes()
    assert r.nomes()[-1] == "click:face"


def test_hover_in_move_out():
    r = Rec()
    r.g.move(5, 5, True, 1.0)
    r.g.move(6, 5, True, 1.1)
    r.g.move(50, 50, False, 1.2)
    r.g.move(6, 5, True, 1.3)
    r.g.move(None, None, False, 1.4)
    assert r.nomes() == ["hover:in", "hover:move", "hover:out", "hover:in", "hover:out"]


def test_nunca_emite_escuta():
    r = Rec()
    rng = random.Random(7)
    t = 0.0
    for _ in range(400):
        t += rng.random() * 0.4
        op = rng.choice(("press", "move", "release", "tick"))
        if op == "press":
            r.g.press(rng.random() * 100, rng.random() * 100, rng.random() < 0.5, t)
        elif op == "move":
            r.g.move(rng.random() * 100, rng.random() * 100, rng.random() < 0.8, t)
        elif op == "release":
            r.g.release(t)
        else:
            r.g.tick(t)
    permitidos = {"click:face", "hover:dbl", "hover:long", "hover:arrasto",
                  "hover:in", "hover:move", "hover:out"}
    assert set(r.nomes()) <= permitidos


# --- CA-O5 ---------------------------------------------------------------------------------------


def test_snapshot_leve_so_preenche_o_combinado():
    from wired.main_screen import Snapshot, Track

    tr = Track(title="X", artist="Y")
    s = overlay.snapshot_leve("speaking", 0.7, 3, ("piada", 1.0), tr, True)
    assert (s.magui_state, s.mouth_level, s.mood, s.turn_tag, s.track, s.gaming) == (
        "speaking", 0.7, 3, ("piada", 1.0), tr, True)
    padrao = Snapshot()
    assert (s.cpu, s.fps, s.events, s.caption, s.led_on) == (
        padrao.cpu, padrao.fps, padrao.events, padrao.caption, padrao.led_on)


def test_detectores_do_overlay():
    from wired.reacoes import det_conversa, det_entrada, det_musica, det_tempo

    assert overlay.DETECTORES_OVERLAY == (
        det_tempo.detectar, det_musica.detectar, det_entrada.detectar, det_conversa.detectar)


def test_reactor_do_overlay_reage_aos_cliques_e_registra(tmp_path):
    from wired.reacoes.atividade import Atividade
    from wired.reactions import Reactor, Taste

    g = tmp_path / "genres.json"
    g.write_text("{}", encoding="utf-8")
    gosto = tmp_path / "gosto.toml"
    gosto.write_text("", encoding="utf-8")
    relogio = [1_800_000_000.0]
    r = Reactor(Taste(g, gosto), cleanup_file=tmp_path / "cleanup.json",
                seen_file=tmp_path / "seen.json", clock=lambda: relogio[0], rng=random.Random(3),
                detectores=overlay.DETECTORES_OVERLAY, sortear=lambda ctx, agora, rng: None,
                registro_file=overlay.REGISTRO_FILE, atividade=Atividade(overlay.ATIVIDADE_FILE),
                estado_file=tmp_path / "estado.json", sem_sentido_file=tmp_path / "ss.jsonl",
                boot_id="boot-1")
    r.favorite_of_day = lambda: ""
    r.atividade.evento(relogio[0], "teste")  # o bom-dia de hoje já saiu
    snap = overlay.snapshot_leve("sleeping", 0.0, 2, None, None, False)
    for t in range(6):  # aquece: 1º tick só registra; o hud_acordou toca e acaba
        r.observe(snap, float(t), 12)
    cliques: list = []
    gestos = Gestos(lambda alvo, t: (cliques.append(alvo), r.on_click(alvo, t)), r.on_hover)
    for t in (30.0, 31.0, 32.0):  # três cutucadas no rosto em 5 s = rajada (64)
        gestos.press(50, 50, False, t)
        gestos.release(t + 0.05)
        gestos.tick(t + 0.4)
    assert cliques == ["face", "face", "face"]
    for t in (32.5, 33.5, 34.5, 35.5):  # o diretor junta os disparos por 3 s
        r.observe(snap, t, 12)
    linhas = [json.loads(x) for x in overlay.REGISTRO_FILE.read_text().splitlines() if x.strip()]
    assert "led" in {x.get("chave") for x in linhas}, linhas


# --- hud_aberto (D2) -----------------------------------------------------------------------------


def test_hud_aberto_sem_arquivo_e_falso_e_nao_cria(tmp_path):
    lock = tmp_path / "hud.lock"
    assert overlay.hud_aberto(lock) is False
    assert not lock.exists()


def test_hud_aberto_trava_real_ocupada_e_livre(tmp_path):
    lock = tmp_path / "hud.lock"
    lock.touch()
    assert overlay.hud_aberto(lock) is False
    with open(lock, "w") as f:  # o "HUD" segura a trava (outra descrição de arquivo)
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert overlay.hud_aberto(lock) is True
        assert overlay.hud_aberto(lock) is True  # não ficou com nada preso
    assert overlay.hud_aberto(lock) is False
    with open(lock, "w") as f:  # depois de testar, a trava está livre na hora
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_hud_aberto_padrao_le_hud_lock_na_hora(monkeypatch, tmp_path):
    lock = tmp_path / "outro.lock"
    lock.touch()
    monkeypatch.setattr(overlay, "HUD_LOCK", lock)
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert overlay.hud_aberto() is True


# --- jogo_aberto (D3) ----------------------------------------------------------------------------


def _vigia(steam=None, mango=None, erro=None):
    def falha():
        raise erro

    return types.SimpleNamespace(steam_game=falha if erro else (lambda: steam), mango_game=lambda: mango)


@pytest.mark.parametrize(("steam", "mango", "esperado"), [
    (None, None, False), ("steam:570", None, True), (None, "mango:jogo", True),
])
def test_jogo_aberto_com_vigia_falso(monkeypatch, steam, mango, esperado):
    monkeypatch.setattr(overlay, "_carregar_watch", lambda: _vigia(steam, mango))
    assert overlay.jogo_aberto() is esperado


def test_jogo_aberto_erro_e_falso(monkeypatch):
    monkeypatch.setattr(overlay, "_carregar_watch", lambda: _vigia(erro=OSError("proc")))
    assert overlay.jogo_aberto() is False

    def sem_arquivo():
        raise FileNotFoundError("gamerhud-watch.py")

    monkeypatch.setattr(overlay, "_carregar_watch", sem_arquivo)
    assert overlay.jogo_aberto() is False


def test_vigia_real_carrega_sem_rodar_main(monkeypatch):
    monkeypatch.setattr(overlay, "_WATCH", None)
    w = overlay._carregar_watch()  # noqa: SLF001
    assert callable(w.steam_game) and callable(w.mango_game)
    assert w.__name__ != "__main__"
    assert overlay._carregar_watch() is w  # noqa: SLF001 — carregado uma vez
