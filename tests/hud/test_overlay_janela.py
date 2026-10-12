"""O1.3: janela e processo do overlay (CA-O6), offscreen, sem núcleo/MPRIS/KWin de verdade."""

import fcntl
import random

import condessa_overlay as co
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QGuiApplication, QImage, QRegion
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
def fabrica(tmp_path, monkeypatch):
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
    feitas = []

    def fazer(cfg):
        trava = co.travar(overlay.LOCK_FILE)
        estado = {"hud": False, "jogo": False}
        w = co.OverlayWindow(cfg, portrait, bridge, reactor, np_, trava=trava,
                             clock=lambda: relogio[0], jogo=lambda: estado["jogo"],
                             hud=lambda: estado["hud"])
        w.relogio, w.estado = relogio, estado
        feitas.append(w)
        return w

    yield fazer
    for w in feitas:
        w.close()


@pytest.fixture
def janela(fabrica):
    return fabrica(Config(estilo="solto"))  # O4.1: o comportamento antigo (rosto solto)


@pytest.fixture
def card(fabrica):
    return fabrica(Config())  # padrão: card


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


# -- O4.1: card com moldura e arraste pelo botão esquerdo ---------------------------------------

def _mouse(w, tipo, botao, pos):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    t = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
         "release": QEvent.Type.MouseButtonRelease}[tipo]
    local = QPointF(*pos)
    glob = QPointF(w.mapToGlobal(local.toPoint()))
    botoes = Qt.MouseButton.NoButton if tipo == "release" else botao
    b = botao if tipo != "move" else Qt.MouseButton.NoButton
    ev = QMouseEvent(t, local, glob, b, botoes, Qt.KeyboardModifier.NoModifier)
    {"press": w.mousePressEvent, "move": w.mouseMoveEvent,
     "release": w.mouseReleaseEvent}[tipo](ev)


def test_config_estilo(tmp_path):
    f = tmp_path / "o.toml"
    assert Config().estilo == "card" and overlay.fundo_efetivo(Config()) is True
    f.write_text('[overlay]\nestilo = "solto"\nfundo = false\n', encoding="utf-8")
    cfg = Config.ler(f)
    assert cfg.estilo == "solto" and overlay.fundo_efetivo(cfg) is False
    f.write_text('[overlay]\nestilo = "balao"\nfundo = false\n', encoding="utf-8")
    cfg = Config.ler(f)
    assert cfg.estilo == "card" and overlay.fundo_efetivo(cfg) is True  # inválido → padrão


def test_card_pinta_moldura_e_placa(card):
    w = card
    w.iniciar()
    assert w.portrait.fundo is True  # forçado no card
    assert (w.width(), w.height()) == overlay.tamanho_quadro(w.cfg)
    img = w.grab().toImage()
    cor = QColor(co.COR_HUMOR)
    for x, y in ((1, 1), (w.width() - 2, w.height() - 2)):  # cantos marcados
        assert img.pixelColor(x, y).rgb() == cor.rgb()
    assert img.pixelColor(w.width() - 1, 0).alpha() == 0  # chanfro: canto recortado
    _, placa = co.card_retangulos(w.width(), w.height())
    claros = sum(img.pixelColor(x, y).lightness() > 150
                 for x in range(int(placa.left()) + 8, int(placa.left()) + 70)
                 for y in range(int(placa.top()) + 3, int(placa.bottom()) - 3))
    assert claros > 20  # texto "CONDESSA" na placa
    fundo, _ = w.camadas_card()
    w.bridge.stateChanged.emit("speaking")  # estado novo → placa refeita
    assert w.camadas_card()[0] is not fundo and co.estado_curto(w.magui) == "falando"


def test_card_borda_na_cor_do_humor(card, monkeypatch):
    w = card
    w.iniciar()
    monkeypatch.setattr(w.reactor, "medidor", lambda now: (0.9, "#f2a7c3", None, ()))
    w.passo()
    assert w.cor_humor == "#f2a7c3"
    assert w.grab().toImage().pixelColor(1, 1).rgb() == QColor("#f2a7c3").rgb()
    monkeypatch.setattr(w.reactor, "medidor", lambda now: 1 / 0)
    w.passo()
    assert w.cor_humor == co.COR_HUMOR  # recaída: o acento


def test_card_mascara_e_o_retangulo(card):
    w = card
    w.iniciar()
    assert w.remascarar(forcar=True) == QRegion(w.rect()) and w.mask() == QRegion(w.rect())


class _Handle:
    def __init__(self, aceita):
        self.aceita, self.chamadas = aceita, 0

    def startSystemMove(self):  # noqa: N802
        self.chamadas += 1
        return self.aceita


def test_card_arraste_esquerdo_chama_startsystemmove_e_grava(card, monkeypatch):
    from PySide6.QtCore import Qt

    w = card
    w.iniciar()
    h = _Handle(True)
    monkeypatch.setattr(w, "windowHandle", lambda: h)
    reacoes = []
    monkeypatch.setattr(w.reactor, "on_hover", lambda ev, t: reacoes.append(ev))
    esq = Qt.MouseButton.LeftButton
    _mouse(w, "press", esq, (60, 200))  # metade de baixo: no card arrasta igual
    _mouse(w, "move", esq, (60 + overlay.Gestos.DRAG_PX + 2, 200))
    assert h.chamadas == 1 and "arrasto" not in reacoes  # move, não vira reação
    w.move(321, 123)
    _mouse(w, "release", esq, (80, 200))
    assert overlay.ler_posicao() == (321, 123, w._nome_tela())
    cliques = []
    monkeypatch.setattr(w.reactor, "on_click", lambda alvo, t: cliques.append(alvo))
    w.gestos.enviar_click = w.reactor.on_click
    w.relogio[0] = 200.0
    _mouse(w, "press", esq, (60, 200))  # clique simples continua reação
    _mouse(w, "release", esq, (60, 200))
    w.gestos.tick(201.0)
    assert cliques == ["face"] and h.chamadas == 1


def test_meio_move_e_recaida_manual(card, monkeypatch):
    from PySide6.QtCore import Qt

    w = card
    w.iniciar()
    w.move(100, 100)
    h = _Handle(False)  # compositor recusa: arraste manual pelo mouse
    monkeypatch.setattr(w, "windowHandle", lambda: h)
    meio = Qt.MouseButton.MiddleButton
    _mouse(w, "press", meio, (10, 10))
    assert h.chamadas == 1 and w._arrasto is not None
    _mouse(w, "move", meio, (60, 30))
    assert w.pos() == QPoint(150, 120)
    _mouse(w, "release", meio, (60, 30))
    assert w._arrasto is None and overlay.ler_posicao()[:2] == (150, 120)


def test_solto_esquerdo_nao_move(janela, monkeypatch):
    from PySide6.QtCore import Qt

    w = janela
    w.iniciar()
    h = _Handle(True)
    monkeypatch.setattr(w, "windowHandle", lambda: h)
    reacoes = []
    monkeypatch.setattr(w.reactor, "on_hover", lambda ev, t: reacoes.append(ev))
    _mouse(w, "press", Qt.MouseButton.LeftButton, (60, 10))
    _mouse(w, "move", Qt.MouseButton.LeftButton, (90, 10))
    assert "arrasto" in reacoes and h.chamadas == 0


def test_posicao_restaurada_antes_do_canto(card, tmp_path):
    tela = QGuiApplication.primaryScreen()
    overlay.gravar_posicao(40, 50, tela.name())
    card.iniciar(overlay.ler_posicao())
    assert card.pos() == QPoint(40, 50)


def test_posicao_fora_da_tela_vai_ao_canto(card):
    tela = QGuiApplication.primaryScreen()
    card.iniciar((99999, 99999, tela.name()))
    assert card.pos() == canto_para_posicao(card.cfg, tela.geometry())


def test_ler_posicao_ilegivel():
    assert overlay.ler_posicao() is None
    overlay.POS_FILE.parent.mkdir(parents=True, exist_ok=True)
    overlay.POS_FILE.write_text("{x", encoding="utf-8")
    assert overlay.ler_posicao() is None
