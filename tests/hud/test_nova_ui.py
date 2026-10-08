"""Nova UI do painel (docs/design/nova-ui): geometria do mockup, textos que cabem com as fontes
reais e a fala digitada 1 caractere por vez no terminal do card da Condessa."""

from datetime import datetime
from itertools import combinations

import pytest
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QImage, QPainter
from wired import main_screen as ms
from wired.data import ClaudeView
from wired.main_screen import MainScreen, Snapshot
from wired.typewriter import MIN_CPS, Typewriter

SIZE = QSize(2560, 1440)
NOW = datetime(2026, 10, 7, 11, 37, 5)

# tabela do README (base 1920, ≈)
TABLE = {
    "magi": (26.4, 143.5, 505.3, 405.4),
    "activity": (26.4, 566.1, 505.3, 250.3),
    "network": (26.4, 834.8, 505.3, 151.6),
    "cam": (553.5, 143.5, 584.5, 491.5),
    "history": (553.5, 656.8, 584.5, 329.6),
    "condessa": (1162.1, 143.5, 356.0, 491.5),
    "spec": (1162.1, 656.8, 356.0, 329.6),
    "player": (1538.8, 143.5, 356.0, 275.6),
    "radio": (1538.8, 437.5, 356.0, 147.0),
    "konsole": (1538.8, 604.0, 356.0, 382.4),
}


def render(sc, snap, now=NOW):
    img = QImage(SIZE, QImage.Format.Format_RGB32)
    p = QPainter(img)
    sc.paint(p, SIZE, snap, now, mono=0.0)
    p.end()
    return img


# ------------------------------------------------------------------ geometria


@pytest.mark.parametrize("name", list(TABLE))
def test_cards_nas_caixas_da_tabela(name):
    r = ms.CARDS[name]
    x, y, w, h = TABLE[name]
    assert (r.x(), r.y(), r.width(), r.height()) == pytest.approx((x, y, w, h), abs=0.6)


def test_cards_nao_se_sobrepoem_e_ficam_entre_topo_e_rodape():
    for (a, ra), (b, rb) in combinations(ms.CARDS.items(), 2):
        assert not ra.intersects(rb), (a, b)
    top, foot = ms.TOP_RULE_Y * ms.F, ms.FOOT_RULE_Y * ms.F
    for name, r in ms.CARDS.items():
        assert r.top() > top and r.bottom() < foot, name
        assert r.left() >= 0 and r.right() <= ms.W
    assert ms.LEARN_BTN.bottom() < top and ms.HEADER_CLOCK.bottom() < top
    assert not ms.LEARN_BTN.intersects(ms.HEADER_CLOCK)


def test_pecas_dentro_dos_cards():
    card = ms.CARDS
    assert all(card["magi"].contains(u) for u in ms.UNITS)
    assert card["magi"].contains(ms.LED_BTN)
    assert not any(ms.LED_BTN.intersects(u) for u in ms.UNITS)
    for a, b in combinations(ms.UNITS, 2):
        assert not a.intersects(b)
    cond = card["condessa"]
    for r in (ms.MASCOT_MAIN, ms.MOOD_MAIN, ms.CHIP_RECT, ms.TALK, ms.CAPTION_RECT):
        assert cond.contains(r), r
    assert ms.MASCOT_MAIN.width() == ms.MASCOT_MAIN.height() == pytest.approx(272 * ms.F, abs=0.6)
    assert ms.MASCOT_MAIN.bottom() <= ms.CHIP_RECT.top() and ms.CHIP_RECT.bottom() <= ms.TALK.top()
    assert ms.TALK.contains(ms.CAPTION_RECT)
    assert all(card["player"].contains(b) for b in ms.BTNS.values())
    assert card["player"].contains(ms.COVER)
    kon = card["konsole"]
    assert kon.contains(ms.KONSOLE_VIEW) and kon.contains(ms.KONSOLE_STATUS)
    assert ms.KONSOLE_VIEW.bottom() <= ms.KONSOLE_STATUS.top()


def test_grupos_dentro_da_tela_e_dos_seus_cards():
    sc = MainScreen()
    g = sc.groups()
    inside = {"magi": "magi", "activity": "activity", "history": "history", "spec": "spec",
              "player": "player", "radio": "radio", "konsole": "konsole", "konsole_status": "konsole",
              "mood": "condessa", "mascot": "condessa", "talk": "condessa"}
    for name, card in inside.items():
        for r in g[name]:
            assert ms.CARDS[card].adjusted(-1, -1, 1, 1).contains(r), (name, r)


# ------------------------------------------------------------------ textos com as fontes reais


def test_textos_fixos_cabem():
    # MAGI SYSTEM: nome em 96, rótulo em 58, valor em 54, botão LED com o texto mais largo
    for name, sub in ms.UNIT_NAMES:
        assert ms.tw(name, "cond", 20, 600, 0.02) <= 96 and ms.tw(sub, "mono", 10, None, 0.08) <= 96
    for k in ("負荷 load", "温度 temp", "周波 clock", "映像 vram", "主記 ram", "交換 swap", "記憶 disk"):
        assert ms.tw(k, "jp", 10) <= 58, k
    for v in ("11.4/32G", "15.9/16G", "4.2GHz", "100°C", "0.2/8G"):
        assert ms.tw(v, "mono", 11) <= 54, v
    led = 2 + 28 + 8 + 8 + ms.tw("消灯", "jp", 11) + 8 + ms.tw("LED OFF", "mono", 10, None, 0.1)
    assert led <= ms.LED_W + 0.5
    # títulos dos cards na largura do conteúdo
    assert ms.tw("SYSTEM ACTIVITY", "cond", 20, 600) + 10 + ms.tw("システム動作状況", "jp", 10) <= 406
    self_hdr = ms.tw("MAGI ", "cond", 13) + ms.tw("自己", "jp", 10) + ms.tw(" · USO PRÓPRIO", "mono", 11)
    assert self_hdr <= 446 - ms.ACT_SELF_X
    assert ms.tw("NO SIGNAL", "cond", 15, None, 0.04) + 12 + ms.tw("ゲーム未検出", "jp", 11) <= 220
    assert ms.tw("SIGNAL OK", "cond", 15, None, 0.04) + 12 + ms.tw("ゲーム検出", "jp", 11) <= 220
    assert ms.tw("↓  999.9 KB/s", "mono", 11) * 2 + 20 <= 220 + 14
    # rádio: título + LIVE na mesma linha
    radio = ms.tw("RÁDIO AYANAMI", "cond", 20, 600, 0.02) + 8 + ms.tw("//", "mono", 12) + 8 + \
        ms.tw("放送", "jp", 11)
    assert radio + 8 + ms.tw("LIVE 00:00", "mono", 10, None, 0.1) <= 276
    # chip: o rótulo mais largo cabe na largura da caixa da fala
    for st in ("listening", "thinking", "speaking", "sleeping"):
        en, jp, _, _ = ms.main_chip(Snapshot(magui_state=st))
        assert 20 + ms.tw(en, "cond", 14, None, 0.04) + ms.tw(" ", "cond", 14) + ms.tw(jp, "jp", 14) <= 284
    # rodapé: esquerda + direita deixam espaço para o log
    left = ms.tw("MAGI", "mono", 13, 700, 0.1) + \
        ms.tw("  MULTI AGENT GUIDANCE INTERFACE", "mono", 11, None, 0.1)
    right = ms.tw("META+M · PAINEL COMPLETO", "mono", 11, None, 0.1)
    assert left + right + 600 <= 1627


def test_valores_longos_sao_cortados_na_caixa():
    long = "X" * 80
    for px, box in ((10.5, 232), (11, 54), (10, 72)):
        assert ms.tw(ms.elide(long, box, "mono", px), "mono", px) <= box + 0.01


def test_pinta_com_dados_extremos_sem_quebrar():
    snap = Snapshot(cpu=100.0, cpu_temp=99.0, cpu_mhz=9999.0, ram=100.0, ram_txt="127.9/128G",
                    swap_used_gb=64.0,
                    swap_total_gb=64.0, disk_pct=100.0, net_ip="255.255.255.255",
                    net_gateway="255.255.255.255",
                    net_dns="2001:4860:4860::8888",
                    project="/home/x/" + "pasta/" * 20, git_branch="feature/" * 8,
                    git_added=123456, git_removed=99999, claude=ClaudeView(tokens=12_345_678_901),
                    specs=[("CPU", "Y" * 90)] * 6, events=["[00:00:00] " + "e" * 300], konsole_online=True,
                    caption="palavra " * 200, magui_state="speaking", chip="speaking", fps=999.0,
                    fps_series=[1.0, 999.0])
    img = render(MainScreen(), snap)
    assert not img.isNull()


def test_status_do_konsole():
    snap = Snapshot(project="/x/magi", git_branch="main", git_added=3, git_removed=1,
                    claude=ClaudeView(tokens=2_400_000), konsole_online=True)
    assert ms.short_num(2_400_000) == "2.4M" and ms.short_num(12_300) == "12.3K"
    assert ms.short_num(950) == "950"
    assert ms.short_num(None) == ms.NA
    sc = MainScreen()
    render(sc, snap)
    assert sc.dirty_regions(snap, NOW, SIZE) == []
    off = Snapshot(**{**snap.__dict__, "konsole_online": False})
    assert sc.dirty_regions(off, NOW, SIZE) == sc.group_rects("konsole_status", SIZE)


# ------------------------------------------------------------------ fala digitada


def test_typewriter_um_caractere_por_vez_acompanhando():
    tw = Typewriter()
    assert tw.feed("Uma", 0.0) is False and tw.shown == ""
    shown = []
    t = 0.0
    target = ""
    words = "Uma aranha tem oito patas.".split()
    for i in range(1, 400):  # a legenda cresce palavra a palavra (~15 caracteres/s), a 30 Hz
        t = i / 30
        target = " ".join(words[:min(len(words), 1 + int(t * 15 / 5))])
        tw.feed(target, t)
        shown.append(tw.shown)
    assert tw.shown == target == "Uma aranha tem oito patas."
    for a, b in zip(shown, shown[1:], strict=False):  # só cresce, como prefixo, sem saltar palavra inteira
        assert b.startswith(a)
        assert len(b) - len(a) <= 2
    assert tw.deadline(t) is None  # tudo digitado: parado, nada a redesenhar


def test_typewriter_texto_novo_recomeca_e_alcanca():
    tw = Typewriter()
    tw.feed("abc def", 0.0)
    tw.feed("abc def", 5.0)
    assert tw.shown == "abc def"
    tw.feed("outra fala", 5.0)  # outra fala: recomeça
    assert tw.shown == ""
    assert tw.deadline(5.0) == pytest.approx(5.0 + 1 / 30)
    tw.feed("outra fala", 5.0 + len("outra fala") / MIN_CPS + 0.01)
    assert tw.shown == "outra fala"
    tw.feed("outra fala, longa", 6.0)  # continuação: mantém o que já foi digitado
    assert tw.shown == "outra fala"


def test_card_digita_a_fala_e_cursor_so_falando():
    sc = MainScreen()
    clock = [100.0]
    sc.clock = lambda: clock[0]
    frase = "Sinal estável. Melchior e Balthasar dentro do normal."
    falando = Snapshot(magui_state="speaking", chip="speaking", caption=frase)
    render(sc, falando)
    assert sc.tw.shown == ""
    k0 = sc.group_key("talk", falando, NOW)
    clock[0] = 100.5
    assert sc.caption_feed(frase) and 0 < len(sc.tw.shown) < len(frase)
    assert sc.group_key("talk", falando, NOW) != k0
    assert sc.caption_deadline() is not None
    clock[0] = 110.0
    sc.caption_feed(frase)
    assert sc.tw.shown == frase and sc.caption_deadline() is None
    # cursor lilás e barra lilás só falando; parada não há prazo (nada pisca)
    lilac = ms.color(ms.M_LILAC)

    def lilac_px(img):
        r = ms.dev_rect(ms.TALK, SIZE.width() / ms.W)
        n = 0
        for y in range(r.top(), r.bottom(), 2):
            for x in range(r.left(), r.right(), 2):
                c = img.pixelColor(x, y)
                n += abs(c.red() - lilac.red()) < 12 and abs(c.green() - lilac.green()) < 12 and \
                    abs(c.blue() - lilac.blue()) < 12
        return n

    parada = Snapshot(magui_state="sleeping", caption=frase)
    a, b = lilac_px(render(sc, falando)), lilac_px(render(sc, parada))
    assert a > b + 20
    assert sc.caption_deadline() is None


def test_chip_falando_em_lilas():
    en, jp, fg, lit = ms.main_chip(Snapshot(magui_state="happy", chip="speaking"))
    assert (en, jp, fg, lit) == ("SPEAKING ·", "発話中", ms.M_LILAC, True)
    en, jp, fg, lit = ms.main_chip(Snapshot())
    assert (en, jp, lit) == ("STANDBY ·", "待機中", False)


def test_terminal_rola_com_fala_longa():
    sc = MainScreen()
    sc.clock = lambda: 0.0
    longa = "palavra " * 60
    for i in range(0, 1201):  # digitação a 20 Hz: a janela acompanha a última linha
        sc.caption_feed(longa, i / 20)
    assert sc.tw.shown == longa and sc.cap.max_off > 0 and sc.cap.follow
    assert len(sc.caption_lines(sc.tw.shown)) > ms.CAPTION_VISIBLE
    for ln in sc.caption_lines(sc.tw.shown):
        assert ms.tw(ln, "mono", ms.TALK_PX) <= ms.TALK_TEXT[2] + 0.01


def test_rei_carrega():
    pm = ms.rei_pixmap()
    assert pm is not None and not pm.isNull()
    assert QRectF(*ms.B_REI).width() == 146
