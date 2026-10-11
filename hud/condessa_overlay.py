#!/usr/bin/env python3
"""Condessa overlay: o retrato dela solto na área de trabalho (specs/condessa-overlay, spec §3, §5).

Processo próprio (D1), mais um cliente do socket do HUD. Sem fundo (``fundo = false``), sempre
acima, sem foco; o clique no rosto só faz reação (nunca liga a escuta). A cada 5 s
``decidir_lugar`` diz onde ficar (D2: HUD aberto → some; D3: em jogo → monitor oposto, um monitor
só → some) e a janela só aplica, guardando a posição antes de sair para voltar a ela.

Nada de D-Bus aqui: a posição/regras no Wayland ficam com a regra do KWin (spec §4).
"""

from __future__ import annotations

import fcntl
import logging
import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QMenu, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parent))  # wired/ e hud_bridge ao lado

from wired import overlay  # noqa: E402
from wired.overlay import (  # noqa: E402
    Config,
    Gestos,
    Lugar,
    canto_para_posicao,
    decidir_lugar,
    tamanho_quadro,
)

log = logging.getLogger("condessa-overlay")

ACCENT = "#b4a0e6"
IDLE_STATES = ("sleeping",)  # parada: as reações aparecem no rosto (como no HUD)
LUGAR_MS = 5000  # D2/D3: hud_aberto/jogo_aberto a cada 5 s
LACO_MS = 1000  # snapshot leve → Reactor a 1 Hz
PAUSA_MS = 3600 * 1000  # menu "Esconder 1 h"
GLITCH_MS = 2000  # núcleo caiu: interferência por 2 s
ROSTO_Y = 0.32  # centro do rosto (fração da altura do quadro): acima = "alto" (arrasto)
TAMANHO_PASSO = 20
TAMANHO_MIN, TAMANHO_MAX = 120, 480


def travar(caminho: Path) -> IO[str] | None:
    """Trava de instância única (flock não bloqueante). None = já tem um overlay rodando."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    f = open(caminho, "w")  # noqa: SIM115 — fica aberto enquanto o processo vive
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


class OverlayWindow(QWidget):
    """A janela do overlay (spec §5). Dependências injetadas para os testes (offscreen)."""

    fechada = Signal()

    def __init__(
        self,
        cfg: Config,
        portrait: Any,
        bridge: Any,
        reactor: Any,
        now_playing: Any,
        *,
        trava: IO[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        jogo: Callable[[], bool] = overlay.jogo_aberto,
        hud: Callable[[], bool] = overlay.hud_aberto,
        xcb: bool = False,
    ) -> None:
        super().__init__(None)
        self.cfg = cfg
        self.portrait = portrait
        self.bridge = bridge
        self.reactor = reactor
        self.now_playing = now_playing
        self.trava = trava
        self.clock = clock
        self.jogo = jogo
        self.hud = hud
        self.xcb = xcb
        portrait.fundo = cfg.fundo

        self.magui = "sleeping"
        self.mouth_level = 0.0
        self.mood: int | None = None
        self.turn_tag: str | None = None
        self.gaming = False
        self._lugar: Lugar | None = None
        self._volta: tuple[str | None, QPoint] | None = None  # (monitor, posição) antes de sair
        self._pausa = False
        self._reacao: Any = None
        self._mascara_t = -1e18

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setWindowTitle("Condessa")
        self.resize(*tamanho_quadro(cfg))

        self.gestos = Gestos(reactor.on_click, reactor.on_hover)

        bridge.stateChanged.connect(self.on_state)
        bridge.mouth.connect(self.on_mouth)
        bridge.mood.connect(self.on_mood)
        bridge.turnTag.connect(self.on_turn_tag)
        bridge.connectedChanged.connect(self.on_connected)

        self._t_quadro = self._timer(True, self.quadro)
        self._t_laco = self._timer(False, self.passo, LACO_MS)
        self._t_lugar = self._timer(False, self.checar_lugar, LUGAR_MS)
        self._t_pausa = self._timer(True, self._fim_pausa, PAUSA_MS)
        self._t_glitch = self._timer(True, self._fim_glitch, GLITCH_MS)
        self._t_gesto = self._timer(True, lambda: self.gestos.tick(self.clock()), Gestos.DBL_MS + 10)

    def _timer(self, unico: bool, alvo: Callable[[], None], ms: int = 0) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(unico)
        t.setInterval(ms)
        t.timeout.connect(alvo)
        return t

    # -- ciclo -----------------------------------------------------------------------------

    def iniciar(self) -> None:
        """Posição inicial, ponte, laços; mostra conforme o ``decidir_lugar``."""
        if self.xcb and self.cfg.x is not None and self.cfg.y is not None:
            self.move(self.cfg.x, self.cfg.y)  # recaída D4: o app escolhe a posição
        else:
            tela = self._tela(self.cfg.tela)
            if tela is not None:
                self.move(canto_para_posicao(self.cfg, tela.geometry()))
        self.bridge.start()
        self.checar_lugar()
        self.passo()
        self._t_laco.start()
        self._t_lugar.start()
        self.quadro()

    def quadro(self) -> None:
        """Redesenho no ritmo do ``portrait.tick`` (60/40/6 fps), timer de disparo único."""
        now = self.clock()
        mudou, prazo = self.portrait.tick(now)
        if mudou and self.isVisible():
            self.update()
        self._t_quadro.start(max(5, min(1000, round((prazo - now) * 1000))))

    def passo(self) -> None:
        """Laço de 1 Hz: snapshot leve → ``Reactor`` → rosto (design §3, passo 3)."""
        now = self.clock()
        track = None
        np_ = self.now_playing
        if np_ is not None:
            np_.tick(now)
            if np_.active:
                from wired.main_screen import Track

                track = Track(np_.title, np_.artist, np_.album, np_.year, np_.position(now),
                              np_.length, np_.status == "Playing", np_.cover_pixmap())
        snap = overlay.snapshot_leve(self.magui, self.mouth_level, self.mood, self.turn_tag, track,
                                     self.gaming)
        r = self.reactor
        r.observe(snap, now)
        if self.magui not in IDLE_STATES:
            r.cancel()
        ativa = r.active(now)
        self.portrait.react(ativa, r.until)
        repouso = getattr(r, "repouso", None)
        if repouso is not None and hasattr(self.portrait, "set_rest"):
            self.portrait.set_rest(repouso)
        if ativa is not self._reacao:  # início/fim de reação: a silhueta pode mudar (braço)
            self._reacao = ativa
            self.remascarar(now)

    # -- lugar (D2/D3) ----------------------------------------------------------------------

    def _tela(self, nome: str | None):
        for s in QGuiApplication.screens():
            if s.name() == nome:
                return s
        return QGuiApplication.primaryScreen()

    def checar_lugar(self) -> Lugar:
        """A cada 5 s: ``decidir_lugar(cfg, telas, principal, jogo_aberto(), hud_aberto())``."""
        self.gaming = bool(self.jogo())
        telas = [s.name() for s in QGuiApplication.screens()]
        prim = QGuiApplication.primaryScreen()
        lugar = decidir_lugar(self.cfg, telas, prim.name() if prim else None, self.gaming,
                              bool(self.hud()))
        self.aplicar(lugar)
        return lugar

    def aplicar(self, lugar: Lugar, forcar: bool = False) -> None:
        """Só aplica o ``Lugar``: esconde, troca de monitor (canto/margem) ou volta onde estava."""
        ant, self._lugar = self._lugar, lugar
        if ant == lugar and not forcar:
            return
        if (ant is not None and ant.motivo == "normal" and lugar.motivo != "normal"
                and self._volta is None):
            self._volta = (self._nome_tela(), QPoint(self.pos()))  # guarda antes de sair
        if self._pausa or not lugar.visivel:
            self.hide()
            return
        if lugar.motivo == "jogo_oposto":
            self._ir_para(lugar.tela, None)
        elif self._volta is not None:
            nome, pos = self._volta
            self._volta = None
            self._ir_para(nome, pos)
        elif ant is not None and ant.tela != lugar.tela:
            self._ir_para(lugar.tela, None)
        self.show()

    def _nome_tela(self) -> str | None:
        s = self.screen()
        return s.name() if s is not None else None

    def _ir_para(self, nome: str | None, pos: QPoint | None) -> None:
        tela = self._tela(nome)
        if tela is None:
            return
        if tela is not self.screen():
            self.setScreen(tela)  # no Wayland pode não valer (Sobras O0.1): O3.1 mede
        self.move(pos if pos is not None else canto_para_posicao(self.cfg, tela.geometry()))

    # -- ponte ------------------------------------------------------------------------------

    def on_state(self, s: str) -> None:
        self.magui = s
        self.portrait.set_expression(s)

    def on_mouth(self, v: float) -> None:
        self.mouth_level = v
        self.portrait.set_level(v)

    def on_mood(self, v: int) -> None:
        self.mood = v

    def on_turn_tag(self, v: str) -> None:
        self.turn_tag = v

    def on_connected(self, ok: bool) -> None:
        if ok:
            return
        self.on_state("sleeping")  # núcleo fora: dormindo, com interferência por 2 s
        self.portrait.glitch = 0.4
        self._t_glitch.start()

    def _fim_glitch(self) -> None:
        self.portrait.glitch = 0.0

    # -- pintura e máscara --------------------------------------------------------------------

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        self.portrait.paint(p, QRectF(self.rect()), ACCENT, self.clock())
        p.end()

    def imagem(self, now: float | None = None) -> QImage:
        """Um quadro do retrato num ``QImage`` fora da tela (base da região de entrada)."""
        img = QImage(self.width(), self.height(), QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(0, 0, 0, 0))
        p = QPainter(img)
        self.portrait.paint(p, QRectF(0, 0, self.width(), self.height()), ACCENT,
                            self.clock() if now is None else now)
        p.end()
        return img

    def remascarar(self, now: float | None = None, forcar: bool = False) -> QRegion:
        """``setMask`` com a ``regiao_entrada`` (≤ 1×/s fora de show/resize); vazia → quadro todo."""
        now = self.clock() if now is None else now
        if not forcar and now - self._mascara_t < 1.0:
            return self.mask()
        self._mascara_t = now
        reg = QRegion()
        for r in overlay.regiao_entrada(self.imagem(now)):
            reg = reg.united(r)
        if reg.isEmpty():
            reg = QRegion(self.rect())  # nunca "inclicável"
        self.setMask(reg)
        return reg

    def showEvent(self, ev) -> None:  # noqa: N802
        super().showEvent(ev)
        self.remascarar(forcar=True)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self.remascarar(forcar=True)

    # -- mouse --------------------------------------------------------------------------------

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        b = ev.button()
        pos = ev.position()
        if b == Qt.MouseButton.LeftButton:
            self.gestos.press(pos.x(), pos.y(), pos.y() < self.height() * ROSTO_Y, self.clock())
        elif b == Qt.MouseButton.MiddleButton:
            self.mover()
        elif b == Qt.MouseButton.RightButton:
            self.menu().popup(ev.globalPosition().toPoint())

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        pos = ev.position()
        self.gestos.move(pos.x(), pos.y(), True, self.clock())

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        b = ev.button()
        if b == Qt.MouseButton.LeftButton:
            self.gestos.release(self.clock())
            self._t_gesto.start()  # vence a espera do duplo
        elif b == Qt.MouseButton.MiddleButton and self.xcb:
            self.lembrar_posicao()

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self.gestos.move(None, None, False, self.clock())
        super().leaveEvent(ev)

    def wheelEvent(self, ev) -> None:  # noqa: N802
        ev.ignore()

    def mover(self) -> None:
        """Movimento interativo pelo compositor (R4); a regra do KWin lembra a posição."""
        h = self.windowHandle()
        if h is not None:
            h.startSystemMove()

    def lembrar_posicao(self) -> None:
        """Recaída XWayland (D4 = b): grava ``x``/``y`` no ``overlay.toml``."""
        self.cfg.x, self.cfg.y = self.x(), self.y()
        self.cfg.gravar()

    def menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("Mover", self.mover)
        m.addAction("Tamanho +", lambda: self.mudar_tamanho(+TAMANHO_PASSO))
        m.addAction("Tamanho −", lambda: self.mudar_tamanho(-TAMANHO_PASSO))
        m.addAction("Esconder 1 h", self.esconder_1h)
        m.addAction("Sair", self.close)
        return m

    def mudar_tamanho(self, delta: int) -> None:
        self.cfg.tamanho = max(TAMANHO_MIN, min(TAMANHO_MAX, self.cfg.tamanho + delta))
        self.cfg.gravar()
        self.resize(*tamanho_quadro(self.cfg))

    def esconder_1h(self) -> None:
        self._pausa = True
        self.hide()
        self._t_pausa.start()

    def _fim_pausa(self) -> None:
        self._pausa = False
        if self._lugar is not None:
            self.aplicar(self._lugar, forcar=True)
        else:
            self.checar_lugar()

    # -- fim ----------------------------------------------------------------------------------

    def closeEvent(self, ev) -> None:  # noqa: N802
        for t in (self._t_quadro, self._t_laco, self._t_lugar, self._t_pausa, self._t_glitch,
                  self._t_gesto):
            t.stop()
        self.bridge.stop()
        if self.trava is not None:
            self.trava.close()  # solta a trava
            self.trava = None
        super().closeEvent(ev)
        self.fechada.emit()


def main(argv: list[str] | None = None) -> int:
    """Sobe o overlay. Sai com 0 se desligado, sem arte em partes (R1.2) ou já rodando."""
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    argv = sys.argv if argv is None else argv
    cfg = Config.ler()
    if not cfg.ligado:
        log.info("desligado no overlay.toml (ligado = false)")
        return 0
    xcb = os.environ.get("MAGI_OVERLAY_XCB") == "1"
    if xcb:
        os.environ["QT_QPA_PLATFORM"] = "xcb"  # recaída D4 = b (antes do QApplication)
    trava = travar(overlay.LOCK_FILE)
    if trava is None:
        log.info("já tem um overlay rodando")
        return 0
    from wired.portrait import PartsAssets, PartsPortrait, is_parts, portrait_dir

    pasta = portrait_dir()
    if not is_parts(pasta):
        log.warning("sem a arte em partes em %s; o overlay não mostra o mascote vetorial", pasta)
        trava.close()
        return 0

    QGuiApplication.setDesktopFileName("condessa-overlay")  # app_id que a regra do KWin casa
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("condessa-overlay")

    from hud_bridge import HudBridge
    from wired.data import NowPlaying
    from wired.reacoes.atividade import Atividade
    from wired.reactions import Reactor

    assets = PartsAssets(pasta)
    assets.renderer = cfg.renderer  # o overlay sobrepõe o portrait.toml (cpu por padrão)
    portrait = PartsPortrait(assets, "sleeping")
    reactor = Reactor(detectores=overlay.DETECTORES_OVERLAY, registro_file=overlay.REGISTRO_FILE,
                      atividade=Atividade(overlay.ATIVIDADE_FILE))
    win = OverlayWindow(cfg, portrait, HudBridge(), reactor, NowPlaying(poll=3.0), trava=trava,
                        xcb=xcb)
    win.fechada.connect(app.quit)
    app.aboutToQuit.connect(win.close)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: win.close())
    pulso = QTimer()  # deixa o Python atender os sinais com o laço do Qt rodando
    pulso.timeout.connect(lambda: None)
    pulso.start(500)
    win.iniciar()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
