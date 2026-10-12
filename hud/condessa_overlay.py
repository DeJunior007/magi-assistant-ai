#!/usr/bin/env python3
"""Condessa overlay: o retrato dela na área de trabalho (specs/condessa-overlay, spec §3, §5).

Processo próprio (D1), mais um cliente do socket do HUD. Estilo ``card`` (O4.1, padrão): o retrato
com fundo num cartão com moldura na cor do humor, cantos marcados e uma placa ``CONDESSA`` + estado;
a máscara é o retângulo todo e o botão esquerdo arrasta. Estilo ``solto``: só o rosto, sem fundo,
máscara recortada. Sempre acima, sem foco; o clique no rosto só faz reação (nunca liga a escuta). A cada 5 s
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
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QMenu, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parent))  # wired/ e hud_bridge ao lado

from wired import fonts, kit, overlay, theme  # noqa: E402
from wired.overlay import (  # noqa: E402
    Config,
    Gestos,
    Lugar,
    canto_para_posicao,
    decidir_lugar,
    fundo_efetivo,
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
POS_SALVAR_MS = 600  # sem release depois do startSystemMove: grava quando a janela parar

# -- card (O4.1) ------------------------------------------------------------------------------
CARD_PAD = 7.0  # da borda do card ao retrato
CARD_GAP = 3.0  # entre o retrato e a placa
PLACA_H = 22.0
CARD_CHANFRO = 12.0  # cantos cima-direita/baixo-esquerda chanfrados (kit.panel_path)
RETRATO_RAIO = 6.0  # cantos arredondados do retrato
CANTO_L, CANTO_E = 16, 2  # cantos marcados: comprimento e espessura (px)
COR_HUMOR = theme.CPU  # recaída da borda: o acento #b392f0 (estado.COR_FAIXA das faixas calmas)
ESTADO_CURTO = {"sleeping": "dormindo", "listening": "ouvindo", "thinking": "pensando",
                "speaking": "falando"}


def estado_curto(s: str) -> str:
    """Texto da placa; reações (happy/confused/alert) contam como acordada."""
    return ESTADO_CURTO.get(s, "acordada")


def card_retangulos(w: float, h: float) -> tuple[QRectF, QRectF]:
    """(retrato, placa) dentro de um card ``w``×``h``."""
    placa = QRectF(CARD_PAD, h - CARD_PAD - PLACA_H, w - 2 * CARD_PAD, PLACA_H)
    retrato = QRectF(CARD_PAD, CARD_PAD, w - 2 * CARD_PAD, placa.top() - CARD_GAP - CARD_PAD)
    return retrato, placa


def _pixmap(w: int, h: int, dpr: float) -> QPixmap:
    pm = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


def card_fundo(w: int, h: int, cor: str, estado: str, dpr: float = 1.0) -> QPixmap:
    """Camada de baixo do card: painel chanfrado, scanlines e a placa (nome + estado)."""
    pm = _pixmap(w, h, dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    contorno = kit.panel_path(QRectF(0, 0, w, h), CARD_CHANFRO)
    p.fillPath(contorno, theme.alpha(theme.PANEL, 240))
    kit.draw_scanlines(p, QRectF(0, 0, w, h), contorno)
    _, placa = card_retangulos(w, h)
    p.fillRect(placa, theme.alpha(cor, 26))
    p.fillRect(QRectF(placa.left(), placa.top(), placa.width(), 1), theme.alpha(cor, 110))
    texto = placa.adjusted(7, 0, -7, 0)
    p.setFont(fonts.font("cond", 13, 600, 0.22))
    p.setPen(theme.color(theme.TEXT))
    p.drawText(texto, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "CONDESSA")
    p.setFont(fonts.font("mono", 9.5, 400, 0.04))
    acordada = estado != "dormindo"
    p.setPen(theme.color(theme.TEXT if acordada else theme.TEXT_DIM))
    larg = p.fontMetrics().horizontalAdvance(estado)
    p.drawText(texto, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, estado)
    led = QRectF(texto.right() - larg - 10, placa.center().y() - 2.5, 5, 5)  # LED do estado
    p.fillRect(led, theme.color(cor) if acordada else theme.alpha(cor, 90))
    p.end()
    return pm


def card_moldura(w: int, h: int, cor: str, dpr: float = 1.0) -> QPixmap:
    """Camada de cima do card: borda fina na cor do humor, contorno do retrato e cantos marcados."""
    pm = _pixmap(w, h, dpr)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(theme.alpha(cor, 170))
    p.drawPath(kit.panel_path(QRectF(0.5, 0.5, w - 1, h - 1), CARD_CHANFRO))
    retrato, _ = card_retangulos(w, h)
    p.setPen(theme.color(theme.LINE_STRONG))
    p.drawRoundedRect(retrato.adjusted(-0.5, -0.5, 0.5, 0.5), RETRATO_RAIO, RETRATO_RAIO)
    c = min(CARD_CHANFRO, w / 2, h / 2)  # chanfros: traço grosso na diagonal
    pen = p.pen()
    pen.setColor(theme.color(cor))
    pen.setWidthF(CANTO_E)
    p.setPen(pen)
    p.drawLine(QPoint(round(w - c), 1), QPoint(w - 1, round(c)))
    p.drawLine(QPoint(1, round(h - c)), QPoint(round(c), h - 1))
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    q = theme.color(cor)
    L, E = CANTO_L, CANTO_E  # noqa: N806
    p.fillRect(0, 0, L * 2, E, q)  # topo-esquerdo: traço longo (o acento do kit) e a perna
    p.fillRect(0, 0, E, L, q)
    p.fillRect(w - L, h - E, L, E, q)  # baixo-direito
    p.fillRect(w - E, h - L, E, L, q)
    p.end()
    return pm


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
        self.card = cfg.estilo == "card"
        portrait.fundo = fundo_efetivo(cfg)

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
        self.cor_humor = COR_HUMOR
        self._card_cache: tuple[tuple, QPixmap, QPixmap] | None = None
        self._movendo = False  # arraste pelo usuário em curso (grava a posição ao soltar)
        self._arrasto: QPoint | None = None  # arraste manual (sem startSystemMove): deslocamento
        self._press_global = QPoint()

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

        self.gestos = Gestos(reactor.on_click, self._hover)

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
        self._t_pos = self._timer(True, self._fim_movimento, POS_SALVAR_MS)

    def _timer(self, unico: bool, alvo: Callable[[], None], ms: int = 0) -> QTimer:
        t = QTimer(self)
        t.setSingleShot(unico)
        t.setInterval(ms)
        t.timeout.connect(alvo)
        return t

    # -- ciclo -----------------------------------------------------------------------------

    def iniciar(self, pos: tuple[int, int, str | None] | None = None) -> None:
        """Posição inicial, ponte, laços; mostra conforme o ``decidir_lugar``.

        ``pos`` = ``overlay.ler_posicao()`` (O4.1): vale antes do canto D6 se cair numa tela.
        """
        if self.xcb and self.cfg.x is not None and self.cfg.y is not None:
            self.move(self.cfg.x, self.cfg.y)  # recaída D4: o app escolhe a posição
        elif pos is not None and self._pos_valida(pos):
            self._ir_para(pos[2], QPoint(pos[0], pos[1]))
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

    def _pos_valida(self, pos: tuple[int, int, str | None]) -> bool:
        tela = self._tela(pos[2])
        return tela is not None and tela.geometry().contains(QPoint(pos[0], pos[1]))

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
        cor = self._cor_do_humor(now)
        if cor != self.cor_humor:
            self.cor_humor = cor
            if self.card:
                self.update()

    def _cor_do_humor(self, now: float) -> str:
        """Cor do medidor (``estado.COR_FAIXA``) pelo ``Reactor.medidor``; sem ela → o acento."""
        medidor = getattr(self.reactor, "medidor", None)
        try:
            cor = medidor(now)[1] if medidor is not None else None
        except Exception:  # noqa: BLE001 — o humor é enfeite: nunca derruba o laço
            log.debug("medidor do humor falhou", exc_info=True)
            cor = None
        return cor if isinstance(cor, str) and QColor.isValidColorName(cor) else COR_HUMOR

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
        mudou = estado_curto(s) != estado_curto(self.magui)
        self.magui = s
        self.portrait.set_expression(s)
        if self.card and mudou:
            self.update()  # placa

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
        if self.card:
            self.pintar_card(p)
        else:
            self.portrait.paint(p, QRectF(self.rect()), ACCENT, self.clock())
        p.end()

    def camadas_card(self) -> tuple[QPixmap, QPixmap]:
        """Fundo e moldura do card em cache; refeitas só quando tamanho/humor/estado mudam."""
        dpr = self.devicePixelRatioF()
        chave = (self.width(), self.height(), self.cor_humor, estado_curto(self.magui), dpr)
        if self._card_cache is None or self._card_cache[0] != chave:
            w, h = self.width(), self.height()
            self._card_cache = (chave, card_fundo(w, h, self.cor_humor, chave[3], dpr),
                                card_moldura(w, h, self.cor_humor, dpr))
        return self._card_cache[1], self._card_cache[2]

    def pintar_card(self, p: QPainter) -> None:
        fundo, moldura = self.camadas_card()
        p.drawPixmap(0, 0, fundo)
        retrato, _ = card_retangulos(self.width(), self.height())
        recorte = QPainterPath()
        recorte.addRoundedRect(retrato, RETRATO_RAIO, RETRATO_RAIO)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setClipPath(recorte)
        self.portrait.paint(p, retrato, ACCENT, self.clock())
        p.restore()
        p.drawPixmap(0, 0, moldura)

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
        """``setMask`` com a ``regiao_entrada`` (≤ 1×/s fora de show/resize); vazia → quadro todo.

        No ``card`` a máscara é o retângulo inteiro (O4.1: dá para pegar em qualquer ponto).
        """
        if self.card:
            reg = QRegion(self.rect())
            if self.mask() != reg:
                self.setMask(reg)
            return reg
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
        self._press_global = ev.globalPosition().toPoint()
        if b == Qt.MouseButton.LeftButton:
            alto = self.card or pos.y() < self.height() * ROSTO_Y  # card: arrasta de qualquer ponto
            self.gestos.press(pos.x(), pos.y(), alto, self.clock())
        elif b == Qt.MouseButton.MiddleButton:
            self.arrastar()  # dentro do press: o Wayland exige o serial do clique
        elif b == Qt.MouseButton.RightButton:
            self.menu().popup(ev.globalPosition().toPoint())

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._arrasto is not None:  # recaída: o compositor não aceitou o startSystemMove
            self.move(ev.globalPosition().toPoint() - self._arrasto)
            return
        pos = ev.position()
        self.gestos.move(pos.x(), pos.y(), True, self.clock())  # arrasto → _hover → arrastar()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        b = ev.button()
        if b == Qt.MouseButton.LeftButton:
            self.gestos.release(self.clock())
            self._t_gesto.start()  # vence a espera do duplo
        if b in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton) and self._movendo:
            self._fim_movimento()

    def _hover(self, ev: str, agora: float) -> None:
        """Hover do ``Gestos``; no card o ``arrasto`` move a janela em vez de virar reação."""
        if ev == "arrasto" and self.card:
            self.arrastar()
            return
        self.reactor.on_hover(ev, agora)

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self.gestos.move(None, None, False, self.clock())
        super().leaveEvent(ev)

    def wheelEvent(self, ev) -> None:  # noqa: N802
        ev.ignore()

    def mover(self) -> bool:
        """Movimento interativo pelo compositor (R4); a regra do KWin lembra a posição."""
        h = self.windowHandle()
        if h is None:
            return False
        return bool(h.startSystemMove())

    def arrastar(self) -> None:
        """Começa um arraste do usuário (chamado dentro do press/move do mouse)."""
        self._movendo = True
        if not self.mover():  # compositor recusou: move na mão com o mouse (X11/XWayland)
            log.info("startSystemMove recusado; arraste manual")
            self._arrasto = self._press_global - self.pos()

    def moveEvent(self, ev) -> None:  # noqa: N802
        super().moveEvent(ev)
        if self._movendo:  # o compositor pode engolir o release do arraste: grava quando parar
            self._t_pos.start()

    def _fim_movimento(self) -> None:
        self._t_pos.stop()
        self._arrasto = None
        if self._movendo:
            self._movendo = False
            self.salvar_posicao()

    def salvar_posicao(self) -> None:
        """Grava ``x, y, tela`` no ``overlay-pos.json`` (O4.1) e, na recaída XCB, no toml (D4).

        No Wayland nativo o app não sabe onde está (``pos()`` não é a posição real): não grava;
        quem lembra é a regra do KWin.
        """
        if self.xcb:
            self.lembrar_posicao()
        if QGuiApplication.platformName() != "wayland":
            overlay.gravar_posicao(self.x(), self.y(), self._nome_tela())

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
                  self._t_gesto, self._t_pos):
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
    win.iniciar(overlay.ler_posicao())  # O4.1: a posição do último arraste, antes do canto D6
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
