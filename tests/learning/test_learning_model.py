"""LM1.6: ``learning_model`` (puro) e os grupos ``history``/``input`` da ``LearningScreen``
(offscreen): ordem das mensagens, reenvio sem duplicar, sessão nova, todos os ``lm_*``, mensagem
da Condessa revelada pela lógica do ``speech_caption``, rolagem, despachante ``learning_mouse``."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MAGI_PORTRAIT_DIR", "/nonexistent/magi-portrait")
os.environ.setdefault("MAGI_NO_CLAUDE_STATS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from PySide6.QtCore import QPointF, QSize  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from wired.learning_model import (  # noqa: E402
    MAX_MESSAGES,
    SPEECH_WAIT_S,
    LearningModel,
    check_say,
    session_no,
    word_end,
)
from wired.learning_screen import LearningInfo, LearningScreen  # noqa: E402
from wired.main_screen import Snapshot  # noqa: E402

SIZE = QSize(2560, 1440)
NOW = datetime(2026, 10, 7, 17, 42, 10)
REPLY = "Oh, nice. What kind of authentication system did you build?"


def msg(i: int, author: str = "you", text: str | None = None, speaking: bool = False) -> dict:
    return {"t": "lm_msg", "id": i, "author": author, "source": "voice", "text": text or f"message {i}",
            "at": "2026-10-07T17:42:00", "speaking": speaking}


def model() -> LearningModel:
    return LearningModel(clock=lambda: 0.0)


# ------------------------------------------------------------------ mensagens


def test_lm_msg_em_ordem_de_id_sem_duplicar():
    m = model()
    for i in (2, 1, 3):
        assert m.feed(msg(i)) == {"history"}
    assert [x.id for x in m.messages] == [1, 2, 3]
    v = m.msg_version
    m.feed(msg(2, text="corrigida"))  # reenvio (reconexão): substitui
    assert [x.id for x in m.messages] == [1, 2, 3]
    assert m.message(2).text == "corrigida" and m.msg_version > v


def test_historico_limitado_as_ultimas():
    m = model()
    for i in range(MAX_MESSAGES + 15):
        m.feed(msg(i))
    assert len(m.messages) == MAX_MESSAGES and m.messages[0].id == 15


def test_sessao_nova_limpa_o_historico_e_le_numero_nivel_trilha():
    m = model()
    m.feed({"t": "lm_session", "id": "LS-20261007-01", "level": "b2", "track": "conversation",
            "topic": "free", "n_msgs": 0, "obs_count": 2})
    m.feed(msg(1))
    assert (m.session_no, m.level, m.mode, m.obs_count) == (1, "B2", "CONVERSATION", 2)
    m.feed({"t": "lm_session", "id": "LS-20261007-01", "level": "B2", "track": "conversation",
            "topic": "free"})
    assert len(m.messages) == 1  # mesma sessão (lm_mode on reenviado): mantém
    m.feed({"t": "lm_session", "id": "LS-20261007-02", "level": "B2", "track": "conversation",
            "topic": "free"})
    assert m.messages == [] and m.session_no == 2 and m.obs_count == 0


def test_todos_os_lm_do_nucleo():
    m = model()
    m.feed({"t": "lm_mode", "on": True})
    assert m.mode_on and m.session_active
    m.begin_action("A1")
    assert m.action_running
    m.feed({"t": "lm_result", "id": "A1", "kind": "improve", "ok": True, "data": {}, "error": None,
            "cached": False, "ms": 10, "cost_usd": 0.0})
    assert not m.action_running and m.results["A1"]["kind"] == "improve"
    m.feed({"t": "lm_obs", "items": [{"label": "Past tense"}], "count": 1})
    assert m.obs_count == 1 and m.obs_items[0]["label"] == "Past tense"
    m.feed({"t": "lm_topic", "topic": "game", "requested": "game", "label": "THE GAME I'M PLAYING"})
    assert m.topic["topic"] == "game"
    m.feed({"t": "lm_saved", "norm": "authentication", "saved": True, "id": 7})
    assert m.saved["authentication"]["saved"] is True
    m.feed({"t": "lm_mode", "on": False})
    assert not m.mode_on and not m.session_active
    m.feed({"t": "lm_summary", "session_id": "LS-20261007-01", "n": 1}, now=42.0)
    assert m.summary["n"] == 1 and m.summary_at == 42.0
    m.feed({"t": "lm_mode", "on": True})
    assert m.summary is None  # cartão some ao voltar ao modo


def test_tipos_da_ui_desconhecidos_e_quebrados_sao_ignorados():
    m = model()
    assert m.feed({"t": "lm_say", "text": "x"}) == set()
    assert m.feed({"t": "lm_nada"}) == set()
    assert m.feed({"t": "lm_msg", "id": 1}) == set()  # sem author/text
    assert m.messages == []


# ------------------------------------------------------------------ fala sincronizada (LM-003)


def test_mensagem_em_fala_revela_com_a_fala_e_fica_inteira_no_fim():
    m = model()
    m.on_state("speaking", 0.0)
    m.feed(msg(5, "condessa", REPLY, speaking=True), now=0.05)
    m.on_speech(REPLY, 4.0, 0.1)
    c = m.message(5)
    early = m.revealed_end(c, 0.3)
    mid = m.revealed_end(c, 2.0)
    assert early is not None and mid is not None and early < mid < len(REPLY)
    assert REPLY[:mid].split() == REPLY.split()[: len(REPLY[:mid].split())]  # palavras inteiras
    assert m.deadline(2.0) is not None
    m.on_state("sleeping", 4.5)
    assert m.revealed_end(c, 4.5) is None and m.speaking_id is None and m.deadline(4.5) is None


def test_mensagem_em_fala_chegando_no_thinking_espera_a_fala():
    m = model()
    m.on_state("thinking", 0.0)
    m.feed(msg(5, "condessa", REPLY, speaking=True), now=0.1)
    c = m.message(5)
    assert m.revealed_end(c, 0.2) == 0  # oculta até a fala começar
    m.on_state("speaking", 0.5)
    m.on_speech(REPLY, 3.0, 0.5)
    assert 0 < m.revealed_end(c, 1.5) < len(REPLY)


def test_espera_pela_fala_tem_prazo():
    m = model()
    m.on_state("thinking", 0.0)
    m.feed(msg(5, "condessa", REPLY, speaking=True), now=0.0)
    assert m.deadline(0.0) == SPEECH_WAIT_S
    assert m.revealed_end(m.message(5), SPEECH_WAIT_S + 0.01) is None


def test_mensagem_em_fala_depois_da_fala_aparece_inteira():
    m = model()
    m.on_state("speaking", 0.0)
    m.on_state("sleeping", 3.0)
    m.feed(msg(5, "condessa", REPLY, speaking=True), now=3.1)
    assert m.revealed_end(m.message(5), 3.2) is None and m.speaking_id is None


def test_queda_da_conexao_encerra_a_revelacao():
    m = model()
    m.on_state("speaking", 0.0)
    m.feed(msg(5, "condessa", REPLY, speaking=True), now=0.0)
    m.set_connected(False)
    assert not m.connected and m.speaking_id is None


def test_boca_alimenta_a_onda_e_zera_fora_da_fala():
    m = model()
    m.on_state("speaking", 0.0)
    k0 = m.wave_key()
    m.on_mouth(0.9, 0.1)
    assert m.wave_key() != k0 and m.mouth == 0.9
    m.on_state("sleeping", 1.0)
    assert m.wave_key() == k0 and m.mouth == 0.0


def test_auxiliares():
    assert word_end("It was pretty good", 2) == 6 and word_end("abc", 0) == 0
    assert session_no("LS-20261007-03") == 3 and session_no(None) is None
    assert check_say("  hi  ") == "hi" and check_say("   ") is None and check_say("x" * 2001) is None


def test_rolagem_e_mensagem_nova_volta_ao_fim():
    m = model()
    assert m.scroll_by(100, 60) and m.scroll == 60
    assert not m.scroll_by(10, 60)
    m.feed(msg(1))
    assert m.scroll == 0


# ------------------------------------------------------------------ tela (offscreen)

DIALOG = [
    msg(1, "condessa", "How was your day today?"),
    msg(2, "you", "It was pretty good. Yesterday I make a new authentication system for my project."),
    msg(3, "condessa", REPLY),
]


def snap(**kw) -> Snapshot:
    base = dict(cpu=14.0, gpu=3.0, ram=41.0, net_down=1.2e5, net_up=3e3, magui_state="sleeping")
    base.update(kw)
    return Snapshot(**base)


def render(scr: LearningScreen) -> QImage:
    img = QImage(SIZE, QImage.Format.Format_RGB32)
    p = QPainter(img)
    scr.paint(p, SIZE, snap(), now=NOW)
    p.end()
    return img


def test_learning_info_e_o_modelo():
    assert LearningInfo is LearningModel


def test_historico_pinta_e_chave_muda_com_mensagem():
    scr = LearningScreen(info=LearningModel())
    empty = render(scr)
    assert scr.dirty_regions(snap(), now=NOW, size=SIZE) == []
    for d in DIALOG:
        scr.info.feed(d)
    dirty = scr.dirty_regions(snap(), now=NOW, size=SIZE)
    assert dirty and all(r.intersects(scr.group_rects("history", SIZE)[0]) for r in dirty)
    img = render(scr)
    assert img != empty
    boxes = scr.history_boxes()
    assert {b.message_id for b in boxes} == {1, 2, 3}
    h = scr.L.history
    assert all(h.top <= b.rect.top and b.rect.bottom <= h.bottom for b in boxes)


def test_input_muda_com_conexao_e_boca():
    scr = LearningScreen(info=LearningModel())
    render(scr)
    scr.info.set_connected(False)
    assert scr.group_key("input", snap(), NOW) != scr._keys["input"]
    render(scr)
    scr.info.on_state("speaking", 0.0)
    scr.info.on_mouth(0.8, 0.1)
    assert scr.group_key("input", snap(), NOW) != scr._keys["input"]
    e = scr.entry_rect()
    assert scr.L.entry.left < e.left() and e.right() < scr.L.entry.right


def test_roda_rola_o_historico_e_press_no_end_session():
    scr = LearningScreen(info=LearningModel())
    for i in range(1, 60):
        scr.info.feed(msg(i, "you" if i % 2 else "condessa", "word " * 30))
    assert scr.max_scroll() > 0
    h = scr.L.history
    mid = (h.left + h.w / 2, h.top + h.h / 2)
    assert scr.mouse("wheel", mid, 1.0) is None and scr.info.scroll > 0
    assert scr.mouse("wheel", mid, -50.0) is None and scr.info.scroll == 0
    b = scr.L.end_btn
    assert scr.mouse("press", (b.left + 5, b.top + 5)) == "learning"
    assert scr.mouse("double", mid) is None


def test_wired_learning_mouse_e_retrato_sem_push_to_talk():
    from wired.integration import WiredUI

    w = WiredUI()
    scr = w.screen("learning")
    s = scr.scale(SIZE)
    b = scr.L.end_btn
    assert w.learning_mouse("press", QPointF((b.left + 5) * s, (b.top + 5) * s), SIZE) == "learning"
    pr = scr.MASCOT_RECT.center()
    assert w.hit(QPointF(pr.x() * s, pr.y() * s), SIZE, "learning") is None
    assert w.learning_mouse("press", QPointF(pr.x() * s, pr.y() * s), SIZE) is None
