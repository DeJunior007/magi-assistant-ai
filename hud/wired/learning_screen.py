"""Tela learning "wired" (LM1.5): terceira tela do gamerhud (``view = "learning"``), design §4.

Mesma mecânica do ``MainScreen``/``StandbyScreen``: fundo, painéis e rótulos fixos no cache
(``draw_static``); o resto em grupos com retângulo e chave (``groups``/``group_key``/
``draw_group``). Geometria em ``learning_layout.screen_layout`` (pura), com o retrato do tamanho
exato do painel gamer (``MASCOT_MAIN.size()``, LM-015).

Grupos: ``header`` (relógio, botão END SESSION, linha da sessão), ``mascot`` (o retrato, pintado
pela base como nas outras telas), ``condessa`` (estado da spec §7 e nível), ``system`` (coluna
esquerda: MAGI SYSTEM recolhível, sessão e rede, em ``TEXT_DIM``), ``footer`` (log de uma linha)
e, ainda vazios, ``history``/``input``/``obs``/``topic``/``overlay`` (LM1.6, LM2.2, LM4.3, LM1.9).
``hit_test`` devolve ``"learning"`` no botão END SESSION (a ação é ligada no LM1.7).

Os dados próprios do modo ficam em ``LearningInfo`` (``screen.info``) até o LM1.6 trazer o
``learning_model``; o resto vem do ``Snapshot`` comum (estado da Condessa, MAGI, rede).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPen

from . import kit
from .learning_layout import CHAR_W, LearningLayout, screen_layout, state_label
from .learning_text import Rect
from .main_screen import (
    JP_DAYS,
    MASCOT_MAIN,
    NA,
    PT_DAYS,
    PT_MONTHS,
    Screen,
    Snapshot,
    accent,
    heading,
    label,
    rate,
    text,
    width,
)
from .theme import GPU, HOT, LINE, LINE_STRONG, TEXT, TEXT_DIM, color

W, H = 1920.0, 1080.0  # quadro lógico do HUD em DP-1 (2560×1440 ÷ 1,333)
END_LINE = "#6e5a9e"   # borda do botão END SESSION (protótipo aprovado)
END_TEXT = "#d8c7ff"
CENTER_FILL = "#0c0b11"
C = Qt.AlignmentFlag.AlignHCenter
R = Qt.AlignmentFlag.AlignRight


def qr(r: Rect) -> QRectF:
    return QRectF(r.x, r.y, r.w, r.h)


@dataclass
class LearningInfo:
    """Estado do modo mostrado pela tela (o LM1.6 passa a alimentar pelo ``learning_model``)."""

    session_active: bool = True
    session_no: int = 1
    language: str = "ENGLISH"
    level: str = "B2"
    mode: str = "CONVERSATION"
    action_running: bool = False
    connected: bool = True
    speak_replies: bool = True   # SPEAKING ● ACTIVE/OFF
    muted: bool = False          # LISTENING ● READY/MUTED
    magi_open: bool = True       # MAGI SYSTEM aberto (três unidades) ou recolhido a uma linha
    log: str | None = None       # linha do rodapé


class LearningScreen(Screen):
    """Tela do Learning Mode (aula de inglês)."""

    SCENE_KIND = "main"  # sem cenário animado: ``scene_rects`` é vazio

    def __init__(self, mascot=None, info: LearningInfo | None = None):
        super().__init__(mascot)
        self.info = info or LearningInfo()
        size = MASCOT_MAIN.size()
        self.L: LearningLayout = screen_layout(W, H, (size.width(), size.height()))
        self.MASCOT_RECT = qr(self.L.portrait)

    # ---------------------------------------------------------------- estático

    def draw_static(self, p: QPainter, s: float) -> None:
        L = self.L
        kit.draw_scanlines(p, QRectF(0, 0, W, H))
        # topo
        p.fillRect(QRectF(L.left.left, L.header.bottom - 1, L.right.right - L.left.left, 1), color(LINE))
        text(p, L.left.left, 82, "汎用学習システム", key="mincho", px=46, spacing=0.06)
        label(p, L.left.left, 106, "General purpose learning system — MAGI-01", px=13)
        mid = L.center.left + L.center.w / 2
        text(p, mid, 82, "私は、ここにいる。", key="jp", px=16, spacing=0.2, align=C)
        label(p, mid, 102, "// i am here · learning mode active", px=11, align=C)
        # centro: a conversa
        kit.panel(p, qr(L.center), fill=CENTER_FILL, border=LINE_STRONG)
        p.fillRect(QRectF(L.history.left, L.session.bottom + 4, L.history.w, 1), color(LINE))
        p.fillRect(QRectF(L.history.left, L.input.top - 6, L.history.w, 1), color(LINE))
        # direita: Condessa e observações
        kit.panel(p, qr(L.condessa))
        x0, x1 = L.right.left + 21, L.right.right - 21
        label(p, x0, L.condessa.top + 35, "magi-01 // condessa")
        text(p, x1, L.condessa.top + 35, "人格", key="jp", px=12, color_=TEXT_DIM, align=R)
        if L.obs.h > 0:
            kit.panel(p, qr(L.obs))
            w = heading(p, x0, L.obs.top + 37, "Observations", px=20, color_=TEXT_DIM).width()
            text(p, x0 + w + 10, L.obs.top + 37, "観察", key="jp", px=12, color_=TEXT_DIM)
            btn = QRectF(x0, L.obs.bottom - 21 - 44, x1 - x0, 44)
            if btn.top() > L.obs.top + 50:
                pen = QPen(color(LINE_STRONG), 1, Qt.PenStyle.DashLine)
                p.save()
                p.setPen(pen)
                p.drawRect(btn.adjusted(0.5, 0.5, -0.5, -0.5))
                p.restore()
                label(p, btn.center().x(), btn.top() + 27, "[ view learning profile ]", align=C)
        # rodapé
        y = L.footer.top + 20
        w = heading(p, L.footer.left, y + 1, "MAGI", px=16).width()
        label(p, L.footer.left + w + 12, y, "multi agent guidance interface")
        jw = text(p, L.footer.right, y, "英語勉強", key="jp", px=12, color_=TEXT_DIM, align=R).width()
        label(p, L.footer.right - jw - 6, y, "learning mode //", align=R)

    # ---------------------------------------------------------------- grupos

    def paint_scene(self, p: QPainter, snap: Snapshot, mono: float, s: float) -> None:
        return None

    def scene_rects(self) -> list[QRectF]:
        return []

    def groups(self) -> dict[str, list[QRectF]]:
        L = self.L
        return {
            "header": [qr(L.clock), qr(L.end_btn), qr(L.session)],
            "topic": [qr(L.topic)],
            "mascot": [self.MASCOT_RECT],
            "condessa": [qr(L.state), qr(L.level)],
            "system": [qr(L.left)],
            "history": [qr(L.history)],
            "input": [qr(L.input)],
            "obs": [qr(L.obs)],
            "footer": [self._footer_rect()],
            "overlay": [qr(L.center)],  # menu + balão: por último, por cima
        }

    def _footer_rect(self) -> QRectF:
        f = self.L.footer
        return QRectF(f.left + 360, f.top, f.w - 720, f.h)

    def label_state(self, snap: Snapshot) -> tuple[str, str]:
        i = self.info
        return state_label(snap.magui_state, i.session_active, i.action_running, i.connected)

    def group_key(self, name: str, snap: Snapshot, now: datetime) -> tuple:
        i = self.info
        if name == "header":
            return (now.strftime("%Y%m%d%H%M"), i.session_active, i.session_no, i.language, i.mode)
        if name == "mascot":
            return (accent(snap).rgb(), snap.magui_state)
        if name == "condessa":
            return (self.label_state(snap), i.level, i.mode)
        if name == "system":
            return (i.magi_open, _pct(snap.cpu), _pct(snap.gpu), _pct(snap.ram), snap.cpu_temp is None,
                    i.language, i.level, i.mode, i.speak_replies, i.muted,
                    rate(snap.net_down), rate(snap.net_up))
        if name == "footer":
            return (i.log,)
        return ()  # history/input/obs/topic/overlay: vazios até as próximas tarefas

    def draw_group(self, name: str, p: QPainter, snap: Snapshot, now: datetime, s: float) -> None:
        fn = getattr(self, f"_g_{name}", None)
        if fn is not None:
            fn(p, snap, now, s)

    def _g_header(self, p, snap, now, s):
        L, i = self.L, self.info
        # relógio (direita) e data
        hm = now.strftime("%H:%M")
        tw = text(p, L.clock.right, 100, hm, key="cond", px=56, weight=500, align=R).width()
        dx = L.clock.right - tw - 16
        text(p, dx, 78, JP_DAYS[now.weekday()], key="jp", px=12, color_=TEXT_DIM, align=R)
        label(p, dx, 100, f"{PT_DAYS[now.weekday()]} {now.day:02d} {PT_MONTHS[now.month - 1]}", px=12,
              color_=TEXT, align=R)
        # [ END SESSION // 終了 ]
        b = qr(L.end_btn)
        p.save()
        p.setPen(QPen(color(END_LINE), 1))
        p.drawRect(b.adjusted(0.5, 0.5, -0.5, -0.5))
        p.restore()
        parts = (("[ END SESSION // ", "cond"), ("終了", "jp"), (" ]", "cond"))
        total = sum(width(t, k, 16, None, 0.12 if k == "cond" else 0.0) for t, k in parts)
        x, y = b.center().x() - total / 2, b.top() + 26
        for t, k in parts:
            sp = 0.12 if k == "cond" else 0.0
            text(p, x, y, t, key=k, px=16 if k == "cond" else 14, color_=END_TEXT, spacing=sp)
            x += width(t, k, 16, None, sp)
        # cabeçalho da sessão (centro)
        r = L.session
        y = r.top + 30
        if i.session_active:
            w = heading(p, r.left, y, f"{i.language} session", px=22).width()
            label(p, r.left + w + 12, y, f"// {i.mode} {i.session_no:02d}", px=13)
        else:
            heading(p, r.left, y, "Standby", px=22, color_=TEXT_DIM)

    def _g_condessa(self, p, snap, now, s):
        L, i = self.L, self.info
        txt, col = self.label_state(snap)
        y = L.state.top + 22
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color(col))
        p.drawEllipse(QPointF(L.state.left + 5, y - 6), 4.5, 4.5)
        p.restore()
        latin, _, jp = txt.partition(" ")
        w = text(p, L.state.left + 18, y, latin, key="cond", px=22, weight=600, color_=col,
                 spacing=0.08).width()
        if jp:
            text(p, L.state.left + 18 + w + 10, y, jp, key="jp", px=13, color_=TEXT_DIM)
        y = L.level.top + 44
        w = label(p, L.level.left, y - 4, "level", px=12).width()
        w2 = text(p, L.level.left + w + 12, y, i.level, key="cond", px=44, weight=600).width()
        text(p, L.level.left + w + 12 + w2 + 12, y, f"/ {i.mode}", key="cond", px=20, color_=TEXT_DIM,
             spacing=0.08, max_w=L.level.right - (L.level.left + w + w2 + 24))

    def _g_system(self, p, snap, now, s):
        L, i = self.L, self.info
        x, w = L.left.left, L.left.w
        x0, x1 = x + 21, x + w - 21
        # MAGI SYSTEM (recolhível)
        top = L.left.top
        h = 21 + 30 + 3 * 64 + 21 if i.magi_open else 21 + 30 + 34 + 12
        kit.panel(p, QRectF(x, top, w, h))
        hw = heading(p, x0, top + 40, "MAGI system", px=20, color_=TEXT_DIM).width()
        text(p, x0 + hw + 10, top + 40, "三体合議制御", key="jp", px=11, color_=TEXT_DIM)
        label(p, x1, top + 39, "[ − ]" if i.magi_open else "[ + ]", px=11, align=R)
        units = (("Melchior", "magi·1 // cpu", snap.cpu), ("Balthasar", "magi·2 // gpu", snap.gpu),
                 ("Casper", "magi·3 // memory", snap.ram))
        if i.magi_open:
            y = top + 21 + 30 + 10
            for name, sub, v in units:
                r = QRectF(x0, y, x1 - x0, 56)
                p.save()
                p.setPen(QPen(color(LINE), 1))
                p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
                p.restore()
                text(p, r.left() + 11, r.top() + 24, name.upper(), key="cond", px=18, color_=TEXT_DIM,
                     spacing=0.06)
                label(p, r.left() + 11, r.top() + 44, sub, px=10)
                text(p, r.right() - 11, r.top() + 24, "正常", key="jp", px=13, color_=TEXT_DIM, align=R)
                label(p, r.right() - 11, r.top() + 44, f"load {_pct_txt(v)}", px=10, align=R)
                y += 64
        else:
            label(p, x0, top + 21 + 30 + 22, "melchior · balthasar · casper — 3/3 正常", px=11,
                  max_w=x1 - x0)
        # sessão
        top2 = top + h + 16
        h2 = 200.0
        kit.panel(p, QRectF(x, top2, w, h2))
        y = top2 + 40
        lw = text(p, x0, y, i.language, key="cond", px=18, spacing=0.08, color_=TEXT_DIM).width()
        text(p, x0 + lw + 8, y, f"// {i.level} · {i.mode}", key="cond", px=18, spacing=0.08,
             color_=TEXT_DIM, max_w=x1 - x0 - lw - 8)
        y += 40
        lw = text(p, x0, y, "LEVEL", key="cond", px=16, spacing=0.08, color_=TEXT_DIM).width()
        text(p, x0 + lw + 10, y + 2, i.level, key="cond", px=30, weight=600, color_=TEXT)
        for k, (on, yes, no) in (("SPEAKING", (i.speak_replies, "ACTIVE", "OFF")),
                                 ("LISTENING", (not i.muted, "READY", "MUTED"))):
            y += 34
            lw = text(p, x0, y, k, key="cond", px=16, spacing=0.08, color_=TEXT_DIM).width()
            text(p, x0 + lw + 10, y, f"● {yes if on else no}", key="cond", px=16, spacing=0.08,
                 color_=GPU if on else TEXT_DIM)
        # rede (no pé da coluna)
        h3 = 96.0
        top3 = L.left.bottom - h3
        if top3 > top2 + h2 + 16:
            kit.panel(p, QRectF(x, top3, w, h3))
            heading(p, x0, top3 + 37, "Network", px=18, color_=TEXT_DIM)
            label(p, x0, top3 + 70, f"↓ {rate(snap.net_down)}   ↑ {rate(snap.net_up)}", px=12,
                  upper=False, max_w=x1 - x0)

    def _g_footer(self, p, snap, now, s):
        r = self._footer_rect()
        msg = self.info.log or NA
        if not self.info.connected:
            msg, col = "DISCONNECTED", HOT
        else:
            col = TEXT_DIM
        label(p, r.center().x(), self.L.footer.top + 20, msg, upper=False, align=C, max_w=r.width(),
              color_=col)

    # ---------------------------------------------------------------- cliques

    def hit_rects(self, snap: Snapshot | None = None) -> dict[str, QRectF]:
        return {"learning": qr(self.L.end_btn)}

    @property
    def text_chars(self) -> float:
        """Caracteres do mono 16 por linha do histórico (RNF-06: ≤ ~110)."""
        return self.L.history.w / CHAR_W


def _pct(v: float | None) -> int | None:
    return None if v is None else round(v)


def _pct_txt(v: float | None) -> str:
    return NA if v is None else f"{v:.0f}%"


def logical_size(size: QSize) -> tuple[float, float]:
    """Quadro lógico de ``size`` (largura 1920, como ``Screen.scale``)."""
    s = size.width() / W
    return W, size.height() / s


__all__ = ["LearningInfo", "LearningScreen", "logical_size"]
