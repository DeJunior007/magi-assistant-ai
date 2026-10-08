"""LM1.6: ``hud_bridge`` com servidor falso — todo ``lm_*`` chega ao ``learning_model`` na ordem
certa, a reconexão recebe o ``lm_mode on`` reenviado pelo núcleo (sem ``lm_hello``) e não duplica
o histórico; ``send_lm`` só manda o que o contrato aceita. No ``gamerhud`` (offscreen): campo de
texto só na view learning, troca de ``WindowDoesNotAcceptFocus``, Enter → ``lm_say`` e o
despachante de mouse (retrato não vira push-to-talk, duplo clique não fecha)."""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GAMERHUD_NO_WALLPAPER"] = "1"  # nunca toca no papel de parede real
os.environ.setdefault("MAGI_PORTRAIT_DIR", "/nonexistent/magi-portrait")
os.environ.setdefault("MAGI_NO_CLAUDE_STATS", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from PySide6.QtCore import QPointF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

import hud_bridge  # noqa: E402
from wired.learning_model import LearningModel  # noqa: E402

from magi.common.events import decode_hud  # noqa: E402


def pump(pred: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if pred():
            return True
        time.sleep(0.005)
    QApplication.processEvents()
    return pred()


class FakeCore:
    """Núcleo falso: socket Unix que aceita um cliente por vez sem bloquear o Qt."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(str(path))
        self.srv.listen(4)
        self.srv.setblocking(False)
        self.conn: socket.socket | None = None

    def accept(self) -> None:
        def ready() -> bool:
            try:
                self.conn, _ = self.srv.accept()
            except BlockingIOError:
                return False
            return True

        assert pump(ready), "a ponte não conectou"

    def send(self, *msgs: dict) -> None:
        assert self.conn is not None
        self.conn.sendall(b"".join(json.dumps(m).encode() + b"\n" for m in msgs))

    def recv_lines(self) -> list[bytes]:
        assert self.conn is not None
        self.conn.setblocking(False)
        buf = bytearray()

        def got() -> bool:
            try:
                buf.extend(self.conn.recv(65536))
            except BlockingIOError:
                pass
            return buf.endswith(b"\n")

        assert pump(got)
        return [ln + b"\n" for ln in bytes(buf).split(b"\n") if ln]

    def drop(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def close(self) -> None:
        self.drop()
        self.srv.close()
        self.path.unlink(missing_ok=True)


AT = "2026-10-07T17:42:00+00:00"


def lm_msg(i: int, author: str = "you", speaking: bool = False) -> dict:
    return {"t": "lm_msg", "id": i, "author": author, "source": "text", "text": f"message {i}",
            "at": AT, "speaking": speaking}


SESSION = {"t": "lm_session", "id": "LS-20261007-01", "started_at": AT, "level": "B2",
           "track": "conversation", "topic": "free", "n_msgs": 0, "obs_count": 0}


@pytest.fixture(params=["contrato", "minimo"])
def setup(request, tmp_path, monkeypatch):
    if request.param == "minimo":
        monkeypatch.setattr(hud_bridge, "decode_line", hud_bridge._decode_min)
        monkeypatch.setattr(hud_bridge, "_decode_hud", None)
    path = tmp_path / "hud.sock"
    core = FakeCore(path)
    model = LearningModel(connected=False)
    b = hud_bridge.HudBridge(path, backoff_start=0.02, backoff_max=0.05, learning_model=model)
    got: list[dict] = []
    b.learning.connect(got.append)
    b.start()
    core.accept()
    assert pump(lambda: b.is_connected)
    yield core, b, model, got
    b.stop()
    core.close()


def test_lm_chegam_ao_modelo_em_ordem(setup):
    core, b, model, got = setup
    assert model.connected
    core.send({"t": "lm_mode", "on": True}, SESSION, lm_msg(2), lm_msg(1), lm_msg(3, "condessa"),
              {"t": "lm_obs", "items": [], "count": 0},
              {"t": "lm_topic", "topic": "free", "requested": "free", "label": "FREE TALK"})
    assert pump(lambda: len(got) == 7)
    assert [m["t"] for m in got][:3] == ["lm_mode", "lm_session", "lm_msg"]
    assert model.mode_on and model.session_no == 1
    assert [m.id for m in model.messages] == [1, 2, 3]
    assert model.messages[-1].author == "condessa" and model.topic["label"] == "FREE TALK"


def test_reconexao_recebe_lm_mode_on_sem_duplicar(setup):
    core, b, model, got = setup
    core.send({"t": "lm_mode", "on": True}, SESSION, lm_msg(1), lm_msg(2))
    assert pump(lambda: len(model.messages) == 2)
    core.drop()
    assert pump(lambda: not b.is_connected)
    assert not model.connected
    core.accept()  # a ponte reconecta sozinha; sem lm_hello: o núcleo reenvia o estado
    assert pump(lambda: b.is_connected) and model.connected
    n = len(got)
    core.send({"t": "lm_mode", "on": True}, SESSION, lm_msg(1), lm_msg(2), lm_msg(3))
    assert pump(lambda: len(got) == n + 5)
    assert model.mode_on and [m.id for m in model.messages] == [1, 2, 3]


def test_send_lm_validado(setup):
    core, b, model, got = setup
    assert b.send_lm("lm_say", {"text": "  Yesterday I make a new system  "})
    assert b.send_lm("lm_mode", {"on": False})
    assert b.send_lm("lm_cfg", {"speak_replies": False})
    assert b.send_lm("lm_action", {"id": "A1", "kind": "improve", "message_id": 2, "start": 0,
                                   "end": 6})
    assert b.send_lm("lm_topic", {"topic": "game"})
    assert b.send_lm("lm_save", {"action_id": "A1", "on": True})
    lines = []
    assert pump(lambda: len(lines.extend(core.recv_lines()) or lines) >= 6)
    decoded = [decode_hud(ln).to_dict() for ln in lines]
    assert [d["t"] for d in decoded] == ["lm_say", "lm_mode", "lm_cfg", "lm_action", "lm_topic",
                                          "lm_save"]
    assert decoded[0]["text"] == "Yesterday I make a new system"
    # inválidas: tipo do núcleo, vazio, longo demais, campo faltando
    assert not b.send_lm("lm_msg", {"id": 1})
    assert not b.send_lm("lm_say", {"text": "   "})
    assert not b.send_lm("lm_say", {"text": "x" * 2001})
    assert not b.send_lm("lm_save", {"action_id": "A1"})


def test_send_lm_desconectado(tmp_path):
    b = hud_bridge.HudBridge(tmp_path / "ninguem.sock")
    assert not b.send_lm("lm_say", {"text": "hi"})


def test_lm_estranho_nao_derruba_a_conexao(setup):
    core, b, model, got = setup
    core.send({"t": "lm_msg", "id": "x"}, {"t": "lm_nada"}, lm_msg(1))
    assert pump(lambda: len(model.messages) == 1)
    assert b.is_connected


# ------------------------------------------------------------------ gamerhud (offscreen)


@pytest.fixture
def hud(tmp_path, monkeypatch):
    import gamerhud
    from wired import reactions

    for name in ("GENRES_FILE", "CLEANUP_FILE", "TASTE_FILE", "SEEN_FILE", "FAVORITES_FILE", "SPEECH_FILE"):
        monkeypatch.setattr(reactions, name, tmp_path / "reacoes" / name.lower())
    monkeypatch.setattr(gamerhud, "load_settings",
                        lambda: {"view": "full", "transition": False, "ui": "wired", "rgb_sync": False})
    monkeypatch.setattr(gamerhud, "save_settings", lambda d: None)
    monkeypatch.setattr(gamerhud.orgb, "board_color", lambda: None)
    bridge = hud_bridge.HudBridge(tmp_path / "hud.sock")
    w = gamerhud.HUD({"seg": "Hack"}, bridge=bridge)
    w.resize(2560, 1440)
    yield w
    for name in ("face_timer", "anim_timer", "data_timer", "rgb_timer", "wired_timer", "caption_timer"):
        t = getattr(w, name, None)
        if t is not None:
            t.stop()
    bridge.stop()
    w.hide()
    w.deleteLater()


def click(w, kind, pos: QPointF, double=False):
    t = {"press": QMouseEvent.Type.MouseButtonPress, "release": QMouseEvent.Type.MouseButtonRelease,
         "double": QMouseEvent.Type.MouseButtonDblClick}[kind]
    ev = QMouseEvent(t, pos, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    {"press": w.mousePressEvent, "release": w.mouseReleaseEvent,
     "double": w.mouseDoubleClickEvent}[kind](ev)


def test_campo_so_na_view_learning_com_troca_de_flag(hud):
    hud.show()
    assert pump(lambda: hud.windowHandle() is not None)
    win = hud.windowHandle()
    assert not hud.lm_entry.isVisible()
    assert win.flags() & Qt.WindowType.WindowDoesNotAcceptFocus
    hud.view = "learning"
    e = hud.lm_entry
    assert e.isVisible()
    assert not (win.flags() & Qt.WindowType.WindowDoesNotAcceptFocus)
    scr = hud.wired.learning
    s = scr.scale(QSize(2560, 1440))
    r = scr.entry_rect()
    assert abs(e.geometry().x() - r.x() * s) <= 1 and abs(e.geometry().width() - r.width() * s) <= 1
    assert e.font().pixelSize() == round(18 * s)
    hud.view = "idle"
    assert not e.isVisible() and win.flags() & Qt.WindowType.WindowDoesNotAcceptFocus


def test_enter_manda_lm_say(hud, monkeypatch):
    sent = []
    monkeypatch.setattr(hud.bridge, "send_lm", lambda t, f=None: sent.append((t, f)) or True)
    hud.view = "learning"
    hud.lm_entry.setText("  Yesterday I make a new system ")
    hud.lm_entry.returnPressed.emit()
    assert sent == [("lm_say", {"text": "Yesterday I make a new system"})]
    assert hud.lm_entry.text() == ""
    hud.lm_entry.setText("   ")
    hud.lm_entry.returnPressed.emit()
    assert len(sent) == 1


def test_mouse_na_view_learning_vai_ao_despachante(hud, monkeypatch):
    cmds, calls = [], []
    monkeypatch.setattr(hud.bridge, "send_cmd", lambda n, a=None: cmds.append(n) or True)
    real = hud.wired.learning_mouse
    monkeypatch.setattr(hud.wired, "learning_mouse",
                        lambda kind, pos, size, delta=0.0: calls.append(kind) or real(kind, pos, size, delta))
    monkeypatch.setattr(hud, "close", lambda: pytest.fail("duplo clique fechou o HUD"))
    hud.view = "learning"
    scr = hud.wired.learning
    s = scr.scale(hud.size())
    c = scr.MASCOT_RECT.center()
    pos = QPointF(c.x() * s, c.y() * s)
    click(hud, "press", pos)
    click(hud, "release", pos)
    click(hud, "double", pos)
    assert calls == ["press", "release", "double"]
    assert cmds == []  # o retrato não é push-to-talk na tela learning
    hud.view = "full"
    calls.clear()
    click(hud, "double", pos)
    assert calls == []
