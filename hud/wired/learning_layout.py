"""Geometria pura da tela learning (sem Qt).

LM1.5 — ``screen_layout(w, h, portrait)``: topo, três colunas (sistema | conversa | Condessa),
rodapé e o retângulo da entrada, em coordenadas lógicas (largura 1920 = escala do HUD; em DP-1
2560×1440 o quadro lógico é 1920×1080). A coluna central fica limitada a ~``MAX_CHARS``
caracteres (RNF-06) e a sobra vai para as laterais; a coluna direita tem largura mínima =
retrato + margens (LM-015): se faltar espaço, o centro cede, o retrato nunca encolhe. O tamanho do
retrato vem de fora (``MASCOT_MAIN.size()`` de ``main_screen``, lido pela ``LearningScreen``),
porque este módulo não pode importar PySide6. ``state_label`` é a tabela de spec §7 (UI-001).

LM2.1 — menu e balão:

- ``menu_size(label_w, n_items)``: largura saída da medida do rótulo ``selected: "…"``, com
  mínimo de ``MENU_MIN_W`` lógicos (nota do LM0.3: 220 fixo cortava o rótulo).
- ``menu_rect``: ancorado no fim da seleção (esquerda da última palavra, base + 4); vira para a
  esquerda/para cima quando passaria da coluna; nunca cobre a seleção nem sai da tela (SEL-002).
- ``bubble_rect``: ao lado do menu; pode sobrepor a borda entre a conversa e a coluna direita,
  mas não sai da tela nem cobre a seleção ou o menu (design §4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .learning_text import Rect

MENU_MIN_W = 260.0
MENU_PAD = 12.0      # margem interna horizontal
MENU_HEAD_H = 30.0   # linha do rótulo selected: "…"
MENU_ITEM_H = 28.0
MENU_GAP = 4.0       # distância entre a seleção e o menu (LM0.3)
BUBBLE_GAP = 8.0


def menu_size(label_w: float, n_items: int = 4) -> tuple[float, float]:
    """(largura, altura) do menu a partir da largura medida do rótulo."""
    w = max(MENU_MIN_W, label_w + 2 * MENU_PAD)
    h = MENU_HEAD_H + n_items * MENU_ITEM_H + MENU_PAD / 2
    return w, h


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if hi < lo else min(max(v, lo), hi)


def _bounds(column: Rect, screen: Rect) -> Rect:
    left, top = max(column.left, screen.left), max(column.top, screen.top)
    right, bottom = min(column.right, screen.right), min(column.bottom, screen.bottom)
    return Rect(left, top, max(0.0, right - left), max(0.0, bottom - top))


def _free(r: Rect, avoid: Sequence[Rect]) -> bool:
    return not any(r.intersects(a) for a in avoid)


def menu_rect(selection: Sequence[Rect], column: Rect, screen: Rect, label_w: float,
              n_items: int = 4) -> Rect:
    """Retângulo do menu para a seleção ``selection`` (caixas das palavras, em ordem).

    Preferência: abaixo da última palavra, alinhado à esquerda dela; se passa da direita da
    coluna, alinha pela direita; se passa de baixo, vai para cima da seleção. Sempre dentro de
    ``column ∩ screen`` (largura cortada se a coluna for mais estreita).
    """
    if not selection:
        raise ValueError("menu_rect sem seleção")
    area = _bounds(column, screen)
    w, h = menu_size(label_w, n_items)
    w = min(w, area.w)
    h = min(h, area.h)
    last = selection[-1]
    top_sel = min(r.top for r in selection)
    bottom_sel = max(r.bottom for r in selection)
    xs = (last.left, last.right - w)
    ys = (last.bottom + MENU_GAP, top_sel - MENU_GAP - h)
    candidates = []
    for y in ys:
        for x in xs:
            cx = _clamp(x, area.left, area.right - w)
            candidates.append(Rect(cx, y, w, h))
    for r in candidates:
        if area.contains_rect(r) and _free(r, selection):
            return r
    # Seleção maior que a coluna: o lado com mais espaço, encostado nela.
    below = area.bottom - bottom_sel
    above = top_sel - area.top
    x = _clamp(last.left, area.left, area.right - w)
    y = bottom_sel + MENU_GAP if below >= above else top_sel - MENU_GAP - h
    return Rect(x, _clamp(y, area.top, area.bottom - h), w, h)


def bubble_rect(menu: Rect, selection: Sequence[Rect], screen: Rect, size: tuple[float, float],
                column: Rect | None = None) -> Rect:
    """Retângulo do balão de resultado (``size`` = largura, altura desejadas).

    Ordem: à direita do menu (pode passar da coluna para a coluna direita), à esquerda do
    menu, abaixo do menu, acima do menu. Sem cobrir a seleção nem o menu; dentro da tela.
    ``column`` (opcional) só desempata: o lado que fica mais dentro dela vence.
    """
    w = min(size[0], screen.w)
    h = min(size[1], screen.h)
    avoid = [*selection, menu]
    top = _clamp(menu.top, screen.top, screen.bottom - h)
    side = [Rect(menu.right + BUBBLE_GAP, top, w, h), Rect(menu.left - BUBBLE_GAP - w, top, w, h)]
    if column is not None:
        side.sort(key=lambda r: -_overlap_w(r, column))
    xc = _clamp(menu.left, screen.left, screen.right - w)
    candidates = [*side, Rect(xc, menu.bottom + BUBBLE_GAP, w, h),
                  Rect(xc, menu.top - BUBBLE_GAP - h, w, h)]
    for r in candidates:
        if screen.contains_rect(r) and _free(r, avoid):
            return r
    # Sem lugar livre: o primeiro candidato empurrado para dentro da tela.
    r = candidates[0]
    return Rect(_clamp(r.x, screen.left, screen.right - w), _clamp(r.y, screen.top,
                screen.bottom - h), w, h)


def _overlap_w(r: Rect, c: Rect) -> float:
    return max(0.0, min(r.right, c.right) - max(r.left, c.left))


# ====================================================================== LM1.5: colunas

PORTRAIT_SIZE = (340.1666666666667, 302.0)  # MASCOT_MAIN.size() na base 1920 (só o padrão dos testes)
MARGIN_X = 28.0      # como o painel gamer (X1)
GAP = 20.0           # entre colunas
HEADER_H = 124.0     # linha do topo em y = 123
TOP = 144.0          # topo das colunas (Y2 do painel)
FOOTER_H = 76.0      # da base das colunas até o fim da tela (Y3 − 20 do painel)
PANEL_PAD = 21.0     # margem interna dos painéis (a do lado do mascote no painel)
CENTER_PAD = 24.0    # margem interna da coluna da conversa
MAX_CHARS = 110      # RNF-06: linha da conversa ≤ ~110 caracteres
CHAR_W = 9.6         # avanço do mono 16 px (texto da conversa)
SIDE_RATIO = (1.0, 3.0, 1.0)  # protótipo aprovado: esquerda | centro | direita
PORTRAIT_TOP = 23.0 + 15.8 + 14.0  # rótulo "magi-01 // condessa" + gap, igual ao painel gamer
STATE_H = 30.0
LEVEL_H = 64.0
INPUT_H = 128.0      # onda de áudio + campo de texto
ENTRY_H = 44.0       # campo de texto (QLineEdit do LM1.6) na base do bloco de entrada
SESSION_H = 44.0     # "ENGLISH SESSION // CONVERSATION 01" + tema
TOPIC_W = 300.0
END_W, END_H = 250.0, 40.0
CLOCK_W = 300.0
PROFILE_H = 44.0


@dataclass(frozen=True, slots=True)
class LearningLayout:
    """Retângulos lógicos da tela learning (todos dentro de ``screen``)."""

    screen: Rect
    header: Rect      # faixa do topo (título, frase, botão, relógio)
    clock: Rect
    end_btn: Rect     # [ END SESSION // 終了 ]
    left: Rect        # coluna MAGI SYSTEM + sessão + rede
    center: Rect      # coluna da conversa
    right: Rect       # coluna da Condessa
    session: Rect     # linha do cabeçalho da sessão (centro, topo)
    topic: Rect       # chip do tema, à direita da linha da sessão
    history: Rect     # mensagens
    input: Rect       # onda de áudio + status + campo
    entry: Rect       # o campo de texto em si
    condessa: Rect    # painel do retrato (direita, em cima)
    portrait: Rect    # retrato: exatamente o tamanho de MASCOT_MAIN (LM-015)
    state: Rect       # rótulo de estado (spec §7)
    level: Rect       # B2 / CONVERSATION
    obs: Rect         # OBSERVATIONS + botão Learning Profile (direita, embaixo)
    footer: Rect      # linha do log

    @property
    def text_chars(self) -> float:
        """Caracteres do mono 16 que cabem numa linha do histórico."""
        return self.history.w / CHAR_W


def column_widths(w: float, portrait_w: float, *, max_chars: int = MAX_CHARS,
                  char_w: float = CHAR_W) -> tuple[float, float, float]:
    """(esquerda, centro, direita) para a largura lógica ``w``."""
    avail = max(0.0, w - 2 * MARGIN_X - 2 * GAP)
    unit = avail / sum(SIDE_RATIO)
    left, center, right = (unit * r for r in SIDE_RATIO)
    right_min = portrait_w + 2 * PANEL_PAD
    if right < right_min:          # o retrato nunca encolhe: o centro cede
        center -= right_min - right
        right = right_min
    cap = max_chars * char_w + 2 * CENTER_PAD
    if center > cap:               # ultrawide: a sobra vai para as laterais, não para o texto
        extra = center - cap
        center = cap
        left += extra / 2
        right += extra / 2
    return left, max(0.0, center), right


def screen_layout(w: float = 1920.0, h: float = 1080.0,
                  portrait: tuple[float, float] = PORTRAIT_SIZE, *, max_chars: int = MAX_CHARS,
                  char_w: float = CHAR_W) -> LearningLayout:
    """Layout da tela learning para o quadro lógico ``w``×``h`` e o retrato ``portrait``
    (largura, altura) — passe ``MASCOT_MAIN.size()``."""
    pw, ph = portrait
    lw, cw, rw = column_widths(w, pw, max_chars=max_chars, char_w=char_w)
    bottom = max(TOP, h - FOOTER_H)
    col_h = bottom - TOP
    x_left = MARGIN_X
    x_center = x_left + lw + GAP
    x_right = x_center + cw + GAP
    left = Rect(x_left, TOP, lw, col_h)
    center = Rect(x_center, TOP, cw, col_h)
    right = Rect(x_right, TOP, rw, col_h)

    header = Rect(0.0, 0.0, w, HEADER_H)
    clock = Rect(w - MARGIN_X - CLOCK_W, 30.0, CLOCK_W, 86.0)
    end_btn = Rect(clock.left - 24 - END_W, 62.0, END_W, END_H)

    inner_w = max(0.0, cw - 2 * CENTER_PAD)
    session = Rect(x_center + CENTER_PAD, TOP + 16, inner_w, SESSION_H)
    topic_w = min(TOPIC_W, inner_w / 2)
    topic = Rect(session.right - topic_w, session.top, topic_w, SESSION_H)
    inp = Rect(x_center + CENTER_PAD, max(session.bottom, bottom - CENTER_PAD - INPUT_H), inner_w,
               min(INPUT_H, max(0.0, bottom - CENTER_PAD - session.bottom)))
    entry = Rect(inp.left, inp.bottom - min(ENTRY_H, inp.h), inp.w, min(ENTRY_H, inp.h))
    hist_top = session.bottom + 12
    history = Rect(x_center + CENTER_PAD, hist_top, inner_w, max(0.0, inp.top - 12 - hist_top))

    portrait_r = Rect(x_right + (rw - pw) / 2, TOP + PORTRAIT_TOP, pw, ph)
    state = Rect(x_right + PANEL_PAD, portrait_r.bottom + 14, rw - 2 * PANEL_PAD, STATE_H)
    level = Rect(state.left, state.bottom + 10, state.w, LEVEL_H)
    condessa = Rect(x_right, TOP, rw, level.bottom + PANEL_PAD - TOP)
    obs_top = condessa.bottom + GAP
    obs = Rect(x_right, obs_top, rw, max(0.0, bottom - obs_top))
    footer = Rect(MARGIN_X, h - 56.0, max(0.0, w - 2 * MARGIN_X), 28.0)
    return LearningLayout(screen=Rect(0.0, 0.0, w, h), header=header, clock=clock, end_btn=end_btn,
                          left=left, center=center, right=right, session=session, topic=topic,
                          history=history, input=inp, entry=entry, condessa=condessa,
                          portrait=portrait_r, state=state, level=level, obs=obs, footer=footer)


# ====================================================================== LM1.5: estado (spec §7)

COLOR_GPU = "#5fd38d"       # = theme.GPU (sem importar o tema: ele usa Qt)
COLOR_FOCUS = "#5fd0e0"     # = theme.FOCUS
COLOR_CPU = "#b392f0"       # = theme.CPU
COLOR_TEXT_DIM = "#8f89a6"  # = theme.TEXT_DIM
COLOR_HOT = "#e5695b"       # = theme.HOT

_ACTIVE = {
    "listening": ("LISTENING 聴取中", COLOR_FOCUS),
    "thinking": ("THINKING 思考中", COLOR_FOCUS),
    "speaking": ("SPEAKING 発話中", COLOR_CPU),
}


def state_label(core_state: str | None, session_active: bool, action_running: bool = False,
                connected: bool = True) -> tuple[str, str]:
    """(rótulo, cor) da Condessa na tela learning — tabela de spec §7 (UI-001).

    Ordem: sem conexão → ``OFFLINE``; sem sessão → ``STANDBY``; ouvindo/pensando/falando seguem o
    núcleo (com ou sem ação); ocioso (``sleeping``/``followup`` ou outra expressão) com ação →
    ``ANALYZING`` discreto; ocioso → ``TEACHING`` (o repouso do Learning Mode).
    """
    if not connected:
        return "OFFLINE", COLOR_HOT
    if not session_active:
        return "STANDBY", COLOR_TEXT_DIM
    if core_state in _ACTIVE:
        return _ACTIVE[core_state]
    if action_running:
        return "ANALYZING 分析中", COLOR_TEXT_DIM
    return "TEACHING 教育中", COLOR_GPU
