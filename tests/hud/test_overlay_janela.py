"""O1.3: janela e processo do overlay (CA-O6), offscreen, sem núcleo/MPRIS/KWin de verdade."""

import fcntl
import random

import condessa_overlay as co
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QGuiApplication, QImage
from wired import overlay
from wired.overlay import Config, Lugar, canto_para_posicao


def _arte(pasta):
    for rel in ("parts/head.png", "parts/body.png", "parts/back.png", "eyes/B1.png", "eyes/B2.png",
                "eyes/B3.png", "eyes/B4.png", "eyes/B14.png", "eyes/F1.png", "mouth/C1.png",
                "mouth/C2.png", "mouth/C3.png", "mouth/C6.png"):
        (pasta / rel).parent.mkdir(parents=True, exist_ok=True)
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        img.fill(QColor(200, 100, 100))
        assert img.save(str(pasta / rel))
    (pasta / "portrait.toml").write_text(
        'mode = "parts"\nrenderer = "gl"\n[states]\n'
        'listening = { eyes = "B1", mouth = "C1", blink = ["B2", "B3"] }\n'
        'sleeping = { eyes = "B14", mouth = "C1", blink = ["B15", "B15"] }\n'
        '[speech]\nmouths = ["C1", "C2", "C3"]\n', encoding="utf-8")
    return pasta


class _Vazio:
    def fetch(self):
        return None


@pytest.fixture
def janela(tmp_path, monkeypatch):
    from hud_bridge import HudBridge
    from wired.data import CoverCache, NowPlaying
    from wired.portrait import PartsAssets, PartsPortrait
    from wired.reacoes.atividade import Atividade
    from wired.reactions import Reactor, Taste

    monkeypatch.delenv("MAGI_PORTRAIT_RENDERER", raising=False)
    assets = PartsAssets(_arte(tmp_path / "arte"))
    assets.renderer = "cpu"
    relogio = [100.0]
    portrait = PartsPortrait(assets, "sleeping", now=relogio[0])
    portrait.hour = lambda: 12
    (tmp_path / "g.json").write_text("{}", encoding="utf-8")
    (tmp_path / "gosto.toml").write_text("", encoding="utf-8")
    reactor = Reactor(Taste(tmp_path / "g.json", tmp_path / "gosto.toml"),
                      cleanup_file=tmp_path / "c.json", seen_file=tmp_path / "s.json",
                      clock=lambda: 1_800_000_000.0, rng=random.Random(1),
                      detectores=overlay.DETECTORES_OVERLAY, sortear=lambda ctx, agora, rng: None,
                      registro_file=overlay.REGISTRO_FILE,
                      atividade=Atividade(overlay.ATIVIDADE_FILE), estado_file=tmp_path / "e.json",
                      sem_sentido_file=tmp_path / "ss.jsonl", boot_id="b")
    np_ = NowPlaying(backend=_Vazio(), covers=CoverCache(str(tmp_path / "capas"), threaded=False),
                     threaded=False, clock=lambda: relogio[0])
    bridge = HudBridge(tmp_path / "hud.sock", backoff_start=60.0, backoff_max=60.0)
    trava = co.travar(overlay.LOCK_FILE)
    estado = {"hud": False, "jogo": False}
    w = co.OverlayWindow(Config(), portrait, bridge, reactor, np_, trava=trava,
                         clock=lambda: relogio[0], jogo=lambda: estado["jogo"],
                         hud=lambda: estado["hud"])
    w.relogio, w.estado = relogio, estado
    yield w
    w.close()


def test_abre_pinta_mascara_e_fecha_soltando_a_trava(janela):
    w = janela
    w.iniciar()
    assert w.isVisible() and w.portrait.fundo is False
    assert (w.width(), w.height()) == overlay.tamanho_quadro(w.cfg)
    for i in range(10):  # 10 quadros
        w.relogio[0] = 100.0 + i / 30
        w.quadro()
        assert not w.grab().isNull()
    reg = w.remascarar(forcar=True)
    assert not reg.isEmpty() and w.mask() == reg
    with open(overlay.LOCK_FILE, "w") as f:  # ocupada enquanto a janela vive
        with pytest.raises(BlockingIOError):
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    w.close()
    assert w.trava is None
    with open(overlay.LOCK_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)  # solta


def test_falando_muda_a_boca(janela):
    w = janela
    p = w.portrait
    assert p.mouth_id(50.0) == "C1"
    w.bridge.stateChanged.emit("speaking")
    w.bridge.mouth.emit(0.8)
    assert w.magui == "speaking" and w.mouth_level == 0.8
    assert p.mouth_id(60.0) != "C1"


def test_nucleo_fora_glitch_e_dorme(janela):
    w = janela
    w.bridge.stateChanged.emit("speaking")
    w.bridge.connectedChanged.emit(False)
    assert w.magui == "sleeping" and w.portrait.glitch == pytest.approx(0.4)
    assert w._t_glitch.isActive() and w._t_glitch.interval() == co.GLITCH_MS
    w._t_glitch.timeout.emit()
    assert w.portrait.glitch == 0.0


def test_hud_aberto_esconde_e_volta_na_posicao_guardada(janela):
    w = janela
    w.iniciar()
    w.move(300, 200)
    guardada = QPoint(w.pos())
    w.estado["hud"] = True
    assert w.checar_lugar() == Lugar(False, motivo="hud")
    assert not w.isVisible()
    w.move(0, 0)  # alguém mexeu enquanto escondida: volta à guardada
    w.estado["hud"] = False
    assert w.checar_lugar().visivel
    assert w.isVisible() and w.pos() == guardada


def test_jogo_com_um_monitor_some_e_volta(janela):
    w = janela
    w.iniciar()
    assert len(QGuiApplication.screens()) == 1  # offscreen: um monitor só
    w.move(250, 150)
    w.estado["jogo"] = True
    assert w.checar_lugar() == Lugar(False, motivo="jogo") and not w.isVisible()
    assert w.gaming is True
    w.estado["jogo"] = False
    w.checar_lugar()
    assert w.isVisible() and w.pos() == QPoint(250, 150)


def test_jogo_oposto_vai_ao_canto_do_monitor(janela):
    w = janela
    w.iniciar()
    w.move(10, 10)
    tela = QGuiApplication.primaryScreen()
    w.aplicar(Lugar(True, tela.name(), "jogo_oposto"))
    assert w.isVisible() and w.pos() == canto_para_posicao(w.cfg, tela.geometry())
    w.aplicar(Lugar(True, tela.name(), "normal"))
    assert w.pos() == QPoint(10, 10)


def test_esconder_1h_e_tamanho(janela):
    w = janela
    w.iniciar()
    w.esconder_1h()
    assert not w.isVisible() and w._t_pausa.interval() == 3600 * 1000
    w.checar_lugar()
    assert not w.isVisible()  # a pausa ganha do laço de 5 s
    w._t_pausa.timeout.emit()
    assert w.isVisible()
    w.mudar_tamanho(+20)
    assert w.cfg.tamanho == 240 and Config.ler().tamanho == 240
    assert w.width() == 240
    nomes = [a.text() for a in w.menu().actions()]
    assert nomes == ["Mover", "Tamanho +", "Tamanho −", "Esconder 1 h", "Sair"]


def test_laco_alimenta_o_reactor(janela, monkeypatch):
    w = janela
    vistos = []
    monkeypatch.setattr(w.reactor, "observe", lambda snap, now, hour=None: vistos.append(snap))
    w.gaming = True
    w.on_mood(3)
    w.passo()
    s = vistos[-1]
    assert (s.magui_state, s.mood, s.gaming, s.track) == ("sleeping", 3, True, None)


def test_segunda_instancia_sai_com_zero(tmp_path, monkeypatch):
    primeira = co.travar(overlay.LOCK_FILE)
    assert primeira is not None
    monkeypatch.setattr(co, "OverlayWindow", lambda *a, **k: pytest.fail("abriu janela"))
    try:
        assert co.main(["x"]) == 0
    finally:
        primeira.close()


def test_sem_arte_em_partes_sai_com_zero(monkeypatch):
    monkeypatch.setattr(co, "OverlayWindow", lambda *a, **k: pytest.fail("abriu janela"))
    assert co.main(["x"]) == 0  # MAGI_PORTRAIT_DIR inexistente (conftest)


def test_desligado_sai_com_zero(monkeypatch):
    Config(ligado=False).gravar()
    monkeypatch.setattr(co, "travar", lambda p: pytest.fail("travou"))
    assert co.main(["x"]) == 0
