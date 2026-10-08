"""Pintura do Konsole (KONSOLE // CLAUDE CODE): células do ``KonsoleSession`` em QPainter.

Dois modos, em px lógicos da grade 1920×1080 (o painter já vem escalado por ``scale``):

- ``paint_compact(p, rect, scale)``: miolo do card (sem moldura — a moldura é do card do painel):
  as últimas linhas da tela que cabem, JetBrains Mono pequena.
- ``paint_expanded(p, rect, scale)``: a janela grande na caixa do cam 01 (o painel troca: a câmera
  vai para o lugar do card), com a moldura do mockup (barra de título, aba SESSION 01, terminal,
  barra de status em 2 linhas). A Condessa, o LOAD HISTORY e o UNIT SPEC nunca são cobertos.

Cores ANSI/256/truecolor viram a paleta do mockup (``docs/design/nova-ui/painel.dc.html``,
bloco KONSOLE). Cursor em bloco fixo: nada pisca com o terminal ocioso.
O estado (sessão atual, erro, status do git) fica em ``VIEW``; o gamerhud liga a sessão nele.
"""

from __future__ import annotations

import colorsys
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen

from . import fonts

try:   # o HUD importa ``wired`` com ``hud/`` no sys.path
    import konsole_term as kt
except ImportError:   # pragma: no cover - só se alguém importar fora do HUD
    kt = None

F = 1920 / 1672   # mockup → base 1920 (docs/design/nova-ui/README.md)

# paleta do mockup
BG = "#07060c"
BAR = "#0f0d16"
TAB_BAR = "#0d0b13"
BORDER = "#3a3550"
SEP = "#2b2738"
TEXT = "#e2deee"
TEXT_HI = "#f1eef8"
DIM = "#a39eb8"
FAINT = "#6d6884"
LILAC = "#b49af0"
GREEN = "#6fd49a"
DOT = "#5fd38d"
RED = "#e88f8f"
SCROLL_TRACK = "#14121b"
SCROLL_THUMB = "#3d3752"
CURSOR = LILAC

# ANSI 0–15 → paleta (preto vira um cinza lilás legível no fundo escuro)
ANSI = {
    "black": "#6d6884", "red": RED, "green": GREEN, "brown": "#e6c07b", "blue": "#8fa6ee",
    "magenta": LILAC, "cyan": "#7fcfd6", "white": "#ddd8ea",
    "brightblack": "#8f89a6", "brightred": "#f2a7a7", "brightgreen": "#8fe2b0",
    "brightbrown": "#f0d398", "brightblue": "#adbdf4", "brightmagenta": "#c9b4f6",
    "brightcyan": "#a2e0e5", "brightwhite": TEXT_HI,
}
# aliases que o pyte também usa
ANSI["yellow"] = ANSI["brown"]
ANSI["brightyellow"] = ANSI["brightbrown"]
# alvos para cores arbitrárias (256/truecolor): a mais próxima em matiz entre estas
HUES = [RED, "#f2a06a", "#e6c07b", GREEN, "#7fcfd6", "#8fa6ee", LILAC, "#e39ad0"]
GREYS = [FAINT, "#8f89a6", DIM, "#c9c2e6", TEXT, TEXT_HI]

# ---------------------------------------------------------------- geometria (base 1920)

EXPANDED_RECT = QRectF(553.5, 143.5, 584.5, 491.5)   # caixa do CAM 01 (main_screen.CAM)
CARD_RECT = QRectF(1539.0, 604.0, 355.5, 382.5)      # card KONSOLE (main_screen.KONSOLE): a câmera
                                                     # fica aqui enquanto o Konsole está expandido
TITLE_H = 34 * F
TAB_H = 24 * F
STATUS_H = 36 * F
PAD_X, PAD_TOP, PAD_BOTTOM = 10 * F, 8 * F, 6 * F
SCROLL_W = 4 * F
BTN_W = 16 * F

EXP_PX = 12 * F       # fonte do terminal expandido
COMPACT_PX = 11 * F   # fonte do miolo do card (mockup: 11 px)
COMPACT_MIN_PX = 7 * F   # o card encolhe a fonte até aqui para caber a largura da sessão
LINE_K = 1.38         # altura de linha / px

BOX = {   # caracteres de moldura desenhados à mão: (esq, dir, cima, baixo); sem buracos entre linhas
    "─": "lr", "━": "lr", "│": "ud", "┃": "ud", "┌": "rd", "┐": "ld", "└": "ru", "┘": "lu",
    "├": "udr", "┤": "udl", "┬": "lrd", "┴": "lru", "┼": "lrud",
    "╭": "rd~", "╮": "ld~", "╰": "ru~", "╯": "lu~",
}


@lru_cache(maxsize=512)
def _q(hex_: str) -> QColor:
    return QColor(hex_)


def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round((x + (y - x) * t) * 255):02x}" for x, y in zip(ra, rb, strict=True))


@lru_cache(maxsize=1024)
def _nearest(hex6: str) -> str:
    """Cor arbitrária → a da paleta mais parecida (cinzas pela luminância, cores pela matiz)."""
    r, g, b = _rgb(hex6)
    h, lum, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.18 or lum < 0.08 or lum > 0.94:
        return GREYS[min(len(GREYS) - 1, int(lum * len(GREYS)))]
    best, dist = HUES[0], 9.0
    for c in HUES:
        hc = colorsys.rgb_to_hls(*_rgb(c))[0]
        d = min(abs(hc - h), 1 - abs(hc - h))
        if d < dist:
            best, dist = c, d
    return best


@lru_cache(maxsize=1024)
def fg_hex(name: str) -> str:
    """Cor do texto: "default", nome ANSI do pyte ou "rrggbb" (256/truecolor) → paleta."""
    if not name or name == "default":
        return TEXT
    if name in ANSI:
        return ANSI[name]
    if len(name) == 6:
        try:
            return _nearest(name)
        except ValueError:
            return TEXT
    return TEXT


@lru_cache(maxsize=1024)
def bg_hex(name: str) -> str | None:
    """Cor de fundo (None = o fundo do terminal). Esmaecida no fundo: realce sem berrar."""
    if not name or name == "default":
        return None
    if name in ANSI:
        return _mix(BG, ANSI[name], 0.38)
    if len(name) == 6:
        try:
            r, g, b = _rgb(name)
        except ValueError:
            return None
        lum = colorsys.rgb_to_hls(r, g, b)[1]
        return _mix(BG, _nearest(name), max(0.14, min(0.55, lum * 0.9)))
    return None


def cell_colors(cell) -> tuple[str, str | None]:
    """(texto, fundo) da célula com o ``reverse`` aplicado."""
    fg, bg = fg_hex(cell.fg), bg_hex(cell.bg)
    if cell.reverse:
        return (bg or BG), fg
    return fg, bg


# ---------------------------------------------------------------- métricas

def _font(px: float, bold: bool = False):
    return fonts.font("mono", px, 700 if bold else 400)


@lru_cache(maxsize=256)
def _metrics(px: float, scale: float) -> tuple[float, float, float]:
    """(largura da célula, altura da linha, ascent) em px lógicos; a linha cai em px inteiros do
    dispositivo."""
    fm = QFontMetricsF(_font(px))
    cw = fm.horizontalAdvance("M")
    lh = max(1.0, round(px * LINE_K * scale)) / max(scale, 1e-6)
    asc = fm.ascent() + (lh - fm.height()) / 2
    return cw, lh, asc


def term_rect(rect: QRectF = EXPANDED_RECT) -> QRectF:
    """Área das células dentro da moldura do expandido."""
    top = rect.top() + TITLE_H + TAB_H + PAD_TOP
    bottom = rect.bottom() - STATUS_H - PAD_BOTTOM
    right = rect.right() - SCROLL_W - 8 * F
    return QRectF(rect.left() + PAD_X, top, right - rect.left() - PAD_X, bottom - top)


def compact_px(width: float, cols: int, scale: float = 1.0) -> float:
    """Fonte do card: a do mockup, ou menor (até ``COMPACT_MIN_PX``) para as ``cols`` colunas da
    sessão (do tamanho do expandido) caberem em ``width`` sem cortar a direita."""
    sc = round(scale, 4)
    cw = _metrics(COMPACT_PX, sc)[0]
    if cols * cw <= width:
        return COMPACT_PX
    px = round(COMPACT_PX * width / (cols * cw), 2)
    while px > COMPACT_MIN_PX and cols * _metrics(px, sc)[0] > width:   # o avanço não é linear
        px = round(px - 0.05, 2)
    return max(COMPACT_MIN_PX, px)


def cells_for(rect: QRectF = EXPANDED_RECT, scale: float = 1.0, expanded: bool = True,
              px: float | None = None) -> tuple[int, int]:
    """(colunas, linhas) que cabem: no expandido descontando a moldura; no compacto, o ``rect``
    (na fonte ``px``, padrão a do mockup)."""
    area = term_rect(rect) if expanded else rect
    cw, lh, _ = _metrics(px or (EXP_PX if expanded else COMPACT_PX), round(scale, 4))
    return max(2, int(area.width() // cw)), max(2, int(area.height() // lh))


# ---------------------------------------------------------------- estado

class KonsoleView:
    """O que a pintura precisa: a sessão (ou None), um erro para mostrar e o status do git."""

    def __init__(self):
        self.session = None
        self.error: str | None = None
        self.status: dict = {}
        self.tokens: int | None = None   # contexto do claude (konsole_term.TokenMeter)

    # -- textos de estado
    def placeholder(self) -> str | None:
        if kt is None or not kt.HAVE_PYTE:
            return "instale python3-pyte"
        if self.error:
            return self.error
        if self.session is None:
            return "clique para abrir o Claude Code"
        if not self.session.alive:
            return "[sessão encerrada · clique para abrir outra]"
        return None

    # -- células
    def _draw_rows(self, p: QPainter, origin: QPointF, rows, px: float, scale: float, ncols: int,
                   cursor: tuple[int, int] | None) -> None:
        cw, lh, asc = _metrics(px, round(scale, 4))
        fonts_ = {False: _font(px), True: _font(px, True)}
        x0, y0 = origin.x(), origin.y()
        clip = p.clipBoundingRect() if p.hasClipping() else None
        for ry, row in enumerate(rows):
            top = y0 + ry * lh
            if clip is not None and (top > clip.bottom() or top + lh < clip.top()):
                continue   # linha fora da região repintada
            base = top + asc
            row = row[:ncols]
            # fundos
            x = 0
            while x < len(row):
                _, bg = cell_colors(row[x])
                if bg is None:
                    x += 1
                    continue
                x1 = x
                while x1 < len(row) and cell_colors(row[x1])[1] == bg:
                    x1 += 1
                p.fillRect(QRectF(x0 + x * cw, top, (x1 - x) * cw, lh), _q(bg))
                x = x1
            # texto: corridas ASCII com o mesmo atributo; o resto célula a célula na sua coluna
            x = 0
            while x < len(row):
                c = row[x]
                ch = c.char
                if ch in ("", " "):
                    x += 1
                    continue
                fg, _ = cell_colors(c)
                if ch in BOX:
                    _box(p, QRectF(x0 + x * cw, top, cw, lh), BOX[ch], fg, scale)
                    x += 1
                    continue
                if ch.isascii():
                    key = (c.fg, c.bg, c.bold, c.reverse, c.underscore)
                    x1 = x + 1
                    while x1 < len(row):
                        d = row[x1]
                        if not d.char.isascii() or not d.char or d.char in BOX \
                                or (d.fg, d.bg, d.bold, d.reverse, d.underscore) != key:
                            break
                        x1 += 1
                    s = "".join(cc.char for cc in row[x:x1]).rstrip()
                else:
                    x1, s = x + 1, ch
                if s:
                    p.setFont(fonts_[bool(c.bold)])
                    p.setPen(_q(fg))
                    p.drawText(QPointF(x0 + x * cw, base), s)
                    if c.underscore:
                        p.fillRect(QRectF(x0 + x * cw, base + 1.5, (x1 - x) * cw, 1 / scale), _q(fg))
                x = x1
            if cursor is not None and cursor[1] == ry and 0 <= cursor[0] < ncols:
                cx = cursor[0]
                r = QRectF(x0 + cx * cw, top + 1 / scale, cw, lh - 2 / scale)
                p.fillRect(r, _q(CURSOR))
                if cx < len(row) and row[cx].char not in ("", " "):
                    p.setFont(fonts_[bool(row[cx].bold)])
                    p.setPen(_q(BG))
                    p.drawText(QPointF(r.left(), base), row[cx].char)

    def _cursor(self, sess):
        if sess is None or not sess.alive or sess.scroll:
            return None
        x, y, vis = sess.cursor()
        return (x, y) if vis else None

    # -- modos
    def paint_compact(self, p: QPainter, rect: QRectF, scale: float) -> None:
        """Miolo do card: fundo do terminal e as últimas linhas da tela que cabem."""
        p.save()
        p.setClipRect(rect)
        p.fillRect(rect, _q(BG))
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        msg = self.placeholder()
        inner = rect.adjusted(2, 2, -2, -2)
        sess = self.session
        live = sess is not None and kt is not None and kt.HAVE_PYTE and not self.error
        px = compact_px(inner.width(), sess.cols, scale) if live else COMPACT_PX
        ncols, nrows = cells_for(inner, scale, expanded=False, px=px)
        if live:
            rows = sess.rows_view()
            last = len(rows) - 1 if sess.scroll else sess.last_used_row()
            if msg:
                nrows -= 2   # espaço para o aviso de sessão encerrada embaixo
            first = max(0, last - nrows + 1)
            cur = self._cursor(sess)
            if cur is not None:
                cur = (cur[0], cur[1] - first)
            self._draw_rows(p, inner.topLeft(), rows[first:last + 1], px, scale, ncols, cur)
        if msg:
            _, lh, _ = _metrics(COMPACT_PX, round(scale, 4))
            y = inner.bottom() - lh if sess is not None else inner.center().y() - lh / 2
            p.setFont(_font(COMPACT_PX))
            p.setPen(_q(DIM))
            p.drawText(QRectF(inner.left(), y, inner.width(), lh),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, msg)
        p.restore()

    def paint_expanded(self, p: QPainter, rect: QRectF = EXPANDED_RECT, scale: float = 1.0) -> None:
        """Janela grande: moldura do mockup + terminal + status."""
        p.save()
        p.setClipRect(rect)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(rect, _q(BG))
        self._title(p, rect, scale)
        self._tabs(p, rect, scale)
        self.paint_term(p, rect, scale)
        self._status(p, rect, scale)
        hair = 1 / scale
        b = _q(BORDER)
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), hair), b)
        p.fillRect(QRectF(rect.left(), rect.bottom() - hair, rect.width(), hair), b)
        p.fillRect(QRectF(rect.left(), rect.top(), hair, rect.height()), b)
        p.fillRect(QRectF(rect.right() - hair, rect.top(), hair, rect.height()), b)
        p.restore()

    def paint_term(self, p: QPainter, rect: QRectF = EXPANDED_RECT, scale: float = 1.0) -> None:
        """Só a área do terminal (+ barra de rolagem) do expandido: o que muda com a saída."""
        area = term_rect(rect)
        body = QRectF(rect.left() + 1 / scale, area.top() - PAD_TOP, rect.width() - 2 / scale,
                      area.height() + PAD_TOP + PAD_BOTTOM)
        p.save()
        p.setClipRect(body)
        p.fillRect(body, _q(BG))
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        msg = self.placeholder()
        sess = self.session
        ncols, nrows = cells_for(rect, scale)
        if sess is not None and kt is not None and kt.HAVE_PYTE and not self.error:
            self._draw_rows(p, area.topLeft(), sess.rows_view()[:nrows], EXP_PX, scale, ncols,
                            self._cursor(sess))
        if msg:
            _, lh, _ = _metrics(EXP_PX, round(scale, 4))
            p.setFont(_font(EXP_PX))
            p.setPen(_q(DIM))
            y = area.bottom() - lh if sess is not None else area.center().y() - lh / 2
            p.drawText(QRectF(area.left(), y, area.width(), lh),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, msg)
        # barra de rolagem: posição no histórico
        track = QRectF(rect.right() - 4 * F - SCROLL_W, area.top(), SCROLL_W, area.height())
        p.fillRect(track, _q(SCROLL_TRACK))
        hist = sess.history_len() if sess is not None and kt is not None and kt.HAVE_PYTE else 0
        total = hist + nrows
        frac = nrows / total if total else 1.0
        pos = (hist - (sess.scroll if sess else 0)) / total if total else 0.0
        p.fillRect(QRectF(track.left(), track.top() + pos * track.height(), track.width(),
                          max(8.0, frac * track.height())), _q(SCROLL_THUMB))
        p.restore()

    def row_rects(self, rows, rect: QRectF = EXPANDED_RECT, scale: float = 1.0) -> list[QRectF]:
        """Retângulos (base 1920) das linhas ``rows`` do expandido, para repintar só elas."""
        area = term_rect(rect)
        _, lh, _ = _metrics(EXP_PX, round(scale, 4))
        out = []
        for r in sorted(rows):
            out.append(QRectF(rect.left(), area.top() + r * lh - 1, rect.width() - SCROLL_W - 4 * F,
                              lh + 2))
        return out

    # -- moldura
    def _title(self, p: QPainter, rect: QRectF, scale: float) -> None:
        bar = QRectF(rect.left(), rect.top(), rect.width(), TITLE_H)
        p.fillRect(bar, _q(BAR))
        p.fillRect(QRectF(bar.left(), bar.bottom() - 1 / scale, bar.width(), 1 / scale), _q(SEP))
        cy = bar.center().y()
        # ícone: janela com prompt
        ic = QRectF(bar.left() + 10 * F, cy - 7.5 * F, 15 * F, 15 * F)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(_q("#c9c3dc"), 1.6 * F * 15 / 24)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        k = ic.width() / 24
        p.drawRect(QRectF(ic.left() + 3 * k, ic.top() + 4 * k, 18 * k, 16 * k))
        path = QPainterPath(QPointF(ic.left() + 7 * k, ic.top() + 9 * k))
        path.lineTo(ic.left() + 10 * k, ic.top() + 12 * k)
        path.lineTo(ic.left() + 7 * k, ic.top() + 15 * k)
        path.moveTo(ic.left() + 12 * k, ic.top() + 15 * k)
        path.lineTo(ic.left() + 17 * k, ic.top() + 15 * k)
        p.drawPath(path)
        p.restore()
        p.setFont(fonts.font("cond", 16 * F, 600, 0.05))
        p.setPen(_q(TEXT))
        p.drawText(QRectF(ic.right() + 8 * F, bar.top(), 400, bar.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "KONSOLE // CLAUDE CODE")
        # botões – □ ×
        x = bar.right() - 8 * F - 3 * BTN_W
        p.setPen(_q(DIM))
        for i, (g, px) in enumerate((("–", 11), ("□", 10), ("×", 12))):
            p.setFont(fonts.font("mono", px * F))
            p.drawText(QRectF(x + i * BTN_W, bar.top(), BTN_W, bar.height()), Qt.AlignmentFlag.AlignCenter, g)
        # NODE 01 ●
        alive = self.session is not None and self.session.alive
        nf = fonts.font("mono", 9 * F, 400, 0.08)
        nw = QFontMetricsF(nf).horizontalAdvance("NODE 01")
        dot_x = x - 8 * F - 6 * F
        p.setFont(nf)
        p.drawText(QRectF(dot_x - 5 * F - nw - 4, bar.top(), nw + 4, bar.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "NODE 01")
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_q(DOT if alive else FAINT))
        p.drawEllipse(QRectF(dot_x, cy - 3 * F, 6 * F, 6 * F))
        p.restore()

    def button_rects(self, rect: QRectF = EXPANDED_RECT) -> dict[str, QRectF]:
        """Botões da barra de título (base 1920): "min", "max", "close"."""
        x = rect.right() - 8 * F - 3 * BTN_W
        return {n: QRectF(x + i * BTN_W, rect.top(), BTN_W, TITLE_H)
                for i, n in enumerate(("min", "max", "close"))}

    def _tabs(self, p: QPainter, rect: QRectF, scale: float) -> None:
        bar = QRectF(rect.left(), rect.top() + TITLE_H, rect.width(), TAB_H)
        hair = 1 / scale
        p.fillRect(bar, _q(TAB_BAR))
        p.fillRect(QRectF(bar.left(), bar.bottom() - hair, bar.width(), hair), _q(SEP))
        f = fonts.font("mono", 9 * F, 400, 0.1)
        fm = QFontMetricsF(f)
        label = "SESSION 01"
        tw = 9 * F + fm.horizontalAdvance(label) + 10 * F + fm.horizontalAdvance("×") + 9 * F
        tab = QRectF(bar.left() + hair, bar.top(), tw, bar.height())
        p.fillRect(tab, _q(BG))
        p.fillRect(QRectF(tab.left(), tab.top(), tab.width(), hair), _q(LILAC))
        p.fillRect(QRectF(tab.right(), tab.top(), hair, tab.height()), _q(SEP))
        p.setFont(f)
        p.setPen(_q(TEXT))
        p.drawText(QRectF(tab.left() + 9 * F, tab.top(), tw, tab.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        p.setPen(_q(FAINT))
        p.drawText(QRectF(tab.right() - 9 * F - fm.horizontalAdvance("×"), tab.top(), 20, tab.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "×")
        plus = QRectF(tab.right(), tab.top(), 26 * F, tab.height())
        p.fillRect(QRectF(plus.right(), plus.top(), hair, plus.height()), _q(SEP))
        p.setFont(fonts.font("mono", 12 * F))
        p.setPen(_q(DIM))
        p.drawText(plus, Qt.AlignmentFlag.AlignCenter, "+")

    def _status(self, p: QPainter, rect: QRectF, scale: float) -> None:
        bar = QRectF(rect.left(), rect.bottom() - STATUS_H, rect.width(), STATUS_H)
        p.fillRect(bar, _q(BAR))
        p.fillRect(QRectF(bar.left(), bar.top(), bar.width(), 1 / scale), _q(SEP))
        f = fonts.font("mono", 9.5 * F)
        fm = QFontMetricsF(f)
        p.setFont(f)
        st = self.status or {}
        sess = self.session
        alive = sess is not None and sess.alive
        line_h = (STATUS_H - 10 * F - 2 * F) / 2
        y1 = bar.top() + 5 * F
        y2 = y1 + line_h + 2 * F
        x0 = bar.left() + 10 * F

        def parts(y, items):
            x = x0
            for txt, col in items:
                p.setPen(_q(col or DIM))
                p.drawText(QRectF(x, y, 2000, line_h), Qt.AlignmentFlag.AlignVCenter, txt)
                x += fm.horizontalAdvance(txt)

        proj = st.get("project") or (sess.cwd if sess is not None else "")
        row1 = [(proj, DIM)]
        if st.get("branch"):
            row1 += [("  |  ", SCROLL_THUMB), (st["branch"], DIM)]
        if st.get("added") or st.get("removed"):
            row1 += [("  |  ", SCROLL_THUMB), (f"+{st.get('added', 0)}", GREEN), (" ", DIM),
                     (f"-{st.get('removed', 0)}", RED)]
        parts(y1, row1)
        row2 = [("CLAUDE CODE", DIM)]
        if sess is not None:
            tok = kt.format_tokens(self.tokens) if self.tokens is not None and kt is not None else "—"
            row2 += [("  |  ", SCROLL_THUMB), (f"TOKENS {tok}", DIM)]
            if sess.scroll:
                row2 += [("  |  ", SCROLL_THUMB), (f"↑ {sess.scroll}", LILAC)]
        parts(y2, row2)
        state = "ONLINE" if alive else ("ENCERRADA" if sess is not None else "OFFLINE")
        col = GREEN if alive else DIM
        sw = fm.horizontalAdvance(state)
        sx = bar.right() - 10 * F - sw
        p.setPen(_q(col))
        p.drawText(QRectF(sx, y2, sw + 4, line_h), Qt.AlignmentFlag.AlignVCenter, state)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_q(DOT if alive else FAINT))
        p.drawEllipse(QRectF(sx - 11 * F, y2 + line_h / 2 - 3 * F, 6 * F, 6 * F))
        p.restore()

    # -- cliques
    def hit_expanded(self, pt: QPointF, rect: QRectF = EXPANDED_RECT,
                     cam: QRectF = CARD_RECT) -> str | None:
        """Clique (base 1920) no expandido: "collapse" (– □ ×), "term" (dentro), "cam" (a câmera
        pequena no lugar do card: recolhe) ou None (fora: recolhe também)."""
        if cam.contains(pt):
            return "cam"
        if not rect.contains(pt):
            return None
        for r in self.button_rects(rect).values():
            if r.contains(pt):
                return "collapse"
        return "term"


def _box(p: QPainter, r: QRectF, arms: str, fg: str, scale: float) -> None:
    """Moldura (─│╭╮…) vetorial ocupando a célula inteira: as linhas emendam sem frestas."""
    cx, cy = r.center().x(), r.center().y()
    w = max(1.0 / scale, 1.0)
    col = _q(fg)
    if "~" in arms:   # canto arredondado
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(QPen(col, w))
        p.setBrush(Qt.BrushStyle.NoBrush)
        hx = r.right() if "r" in arms else r.left()
        vy = r.bottom() if "d" in arms else r.top()
        path = QPainterPath(QPointF(hx, cy))
        path.quadTo(QPointF(cx, cy), QPointF(cx, vy))
        p.drawPath(path)
        p.restore()
        return
    o = 0.5 / scale   # meio pixel além da célula: com largura fracionária o arredondamento abria fresta
    if "l" in arms:
        p.fillRect(QRectF(r.left() - o, cy - w / 2, cx - r.left() + w / 2 + o, w), col)
    if "r" in arms:
        p.fillRect(QRectF(cx - w / 2, cy - w / 2, r.right() - cx + w / 2 + o, w), col)
    if "u" in arms:
        p.fillRect(QRectF(cx - w / 2, r.top() - o, w, cy - r.top() + w / 2 + o), col)
    if "d" in arms:
        p.fillRect(QRectF(cx - w / 2, cy - w / 2, w, r.bottom() - cy + w / 2 + o), col)


VIEW = KonsoleView()


def paint_compact(p: QPainter, rect: QRectF, scale: float) -> None:
    """Miolo do card KONSOLE (``rect`` em base 1920, painter escalado por ``scale``)."""
    VIEW.paint_compact(p, rect, scale)


def paint_expanded(p: QPainter, rect: QRectF = EXPANDED_RECT, scale: float = 1.0) -> None:
    """Konsole grande com a moldura do mockup."""
    VIEW.paint_expanded(p, rect, scale)
