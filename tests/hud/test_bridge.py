"""Ponte do HUD (1.15) contra um servidor falso de socket Unix em diretório temporário."""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable
from pathlib import Path

import hud_bridge
import pytest
from PySide6.QtGui import QGuiApplication

from magi.common.contracts import (
    CardLevel,
    CardMsg,
    DetailMsg,
    DetailTarget,
    Expression,
    MoodMsg,
    MouthMsg,
    SpeechMsg,
    StateMsg,
    SubtitleMsg,
    Verdict,
    VoteMsg,
)
from magi.common.events import decode_hud, encode_hud_line


@pytest.fixture(scope="module", autouse=True)
def app():
    # QGuiApplication (não QCoreApplication): os testes do rosto, no mesmo processo, desenham.
    yield QGuiApplication.instance() or QGuiApplication([])


def pump(pred: Callable[[], bool], timeout: float = 3.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QGuiApplication.processEvents()
        if pred():
            return True
        time.sleep(0.005)
    QGuiApplication.processEvents()
    return pred()


class FakeCore:
    """Servidor do núcleo: escuta no socket, aceita um cliente por vez sem bloquear o Qt."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(str(path))
        self.srv.listen(4)
        self.srv.setblocking(False)
        self.conn: socket.socket | None = None

    def accept(self, timeout: float = 3.0) -> socket.socket:
        def ready() -> bool:
            try:
                self.conn, _ = self.srv.accept()
            except BlockingIOError:
                return False
            return True

        assert pump(ready, timeout), "a ponte não conectou"
        assert self.conn is not None
        return self.conn

    def send(self, data: bytes) -> None:
        assert self.conn is not None
        self.conn.sendall(data)

    def recv_line(self, timeout: float = 3.0) -> bytes:
        assert self.conn is not None
        self.conn.setblocking(False)
        buf = bytearray()

        def got() -> bool:
            try:
                buf.extend(self.conn.recv(4096))
            except BlockingIOError:
                pass
            return b"\n" in buf

        assert pump(got, timeout)
        return bytes(buf)

    def drop_client(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def close(self) -> None:
        self.drop_client()
        self.srv.close()
        self.path.unlink(missing_ok=True)


class Recorder:
    def __init__(self, bridge: hud_bridge.HudBridge) -> None:
        self.events: list[tuple] = []
        for name in ("message", "stateChanged", "subtitle", "speech", "mouth", "mood", "vote", "card",
                     "detail", "connectedChanged"):
            getattr(bridge, name).connect(lambda *a, n=name: self.events.append((n, *a)))

    def of(self, name: str) -> list[tuple]:
        return [e[1:] for e in self.events if e[0] == name]


@pytest.fixture
def sock_path(tmp_path: Path) -> Path:
    return tmp_path / "hud.sock"


@pytest.fixture
def bridge(sock_path: Path):
    b = hud_bridge.HudBridge(sock_path, backoff_start=0.02, backoff_max=0.05)
    yield b
    b.stop()


def test_uses_contract_decoder_in_venv():
    assert hud_bridge.HAS_MAGI
    assert hud_bridge.decode_line is hud_bridge._decode_magi
    assert hud_bridge.hud_socket_path({"XDG_RUNTIME_DIR": "/x"}) == Path("/x/magi/hud.sock")


def test_delivers_every_message_type(bridge, sock_path):
    core = FakeCore(sock_path)
    rec = Recorder(bridge)
    bridge.start()
    core.accept()
    assert pump(lambda: bridge.is_connected)

    msgs = [
        StateMsg(Expression.LISTENING),
        SubtitleMsg("Oi", full="Oi, tudo bem?"),
        SubtitleMsg("Só curta"),
        SpeechMsg("Oi, tudo bem?", dur=1.5, i=0),
        SpeechMsg("Sem duração.", i=1),
        MouthMsg(0.42),
        MoodMsg(3),
        VoteMsg(Verdict.PENDING, label="Fechar Elden Ring"),
        VoteMsg(Verdict.APPROVED),
        CardMsg(CardLevel.ALTA, "Título", url="https://x", source="Fonte"),
        DetailMsg(DetailTarget.GPU),
    ]
    # Tudo num envio só, com a última linha partida em dois pedaços.
    data = b"".join(encode_hud_line(m) for m in msgs)
    core.send(data[:-7])
    pump(lambda: False, 0.05)
    core.send(data[-7:])
    assert pump(lambda: len(rec.of("message")) == len(msgs))

    assert rec.of("message") == [(m.to_dict(),) for m in msgs]
    assert rec.of("stateChanged") == [("listening",)]
    assert rec.of("subtitle") == [("Oi", "Oi, tudo bem?"), ("Só curta", "")]
    assert rec.of("speech") == [("Oi, tudo bem?", 1.5, 0), ("Sem duração.", -1.0, 1)]
    assert rec.of("mouth") == [(pytest.approx(0.42),)]
    assert rec.of("mood") == [(3,)]
    assert rec.of("vote") == [("pending", "Fechar Elden Ring"), ("approved", "")]
    assert rec.of("card") == [({"level": "alta", "title": "Título", "url": "https://x", "source": "Fonte"},)]
    assert rec.of("detail") == [("gpu",)]
    assert rec.of("connectedChanged") == [(True,)]
    core.close()


def test_invalid_lines_are_ignored(bridge, sock_path):
    core = FakeCore(sock_path)
    rec = Recorder(bridge)
    bridge.start()
    core.accept()
    bad = [
        b"isso nao e json\n",
        b"[1,2]\n",
        b'{"v":"listening"}\n',
        b'{"t":"desconhecido"}\n',
        b'{"t":"state","v":"bravo"}\n',
        b'{"t":"mood","v":9}\n',
        b'{"t":"mouth"}\n',
        b"\n",
        b"\xff\xfe\n",
    ]
    core.send(b"".join(bad) + encode_hud_line(MoodMsg(1)))
    assert pump(lambda: rec.of("mood") == [(1,)])
    assert len(rec.of("message")) == 1
    assert bridge.is_connected
    core.close()


def test_oversized_line_is_dropped(bridge, sock_path):
    core = FakeCore(sock_path)
    rec = Recorder(bridge)
    bridge.start()
    core.accept()
    core.send(b"x" * (hud_bridge.MAX_LINE + 10))
    pump(lambda: False, 0.1)
    core.send(b'"}\n' + encode_hud_line(DetailMsg(DetailTarget.CPU)))
    assert pump(lambda: rec.of("detail") == [("cpu",)])
    assert len(rec.of("message")) == 1
    core.close()


def test_reconnects_when_core_comes_up_later_and_after_drop(bridge, sock_path):
    rec = Recorder(bridge)
    bridge.start()  # núcleo fora do ar: não pode travar nem levantar exceção
    pump(lambda: False, 0.15)
    assert not bridge.is_connected

    core = FakeCore(sock_path)
    core.accept()
    assert pump(lambda: bridge.is_connected)

    core.drop_client()  # núcleo derruba a conexão
    assert pump(lambda: not bridge.is_connected)
    core.accept()  # a ponte volta sozinha
    assert pump(lambda: bridge.is_connected)
    core.send(encode_hud_line(StateMsg(Expression.HAPPY)))
    assert pump(lambda: rec.of("stateChanged") == [("happy",)])

    core.close()  # núcleo some de vez, depois volta
    assert pump(lambda: not bridge.is_connected)
    core = FakeCore(sock_path)
    core.accept()
    assert pump(lambda: bridge.is_connected)
    assert rec.of("connectedChanged") == [(True,), (False,), (True,), (False,), (True,)]
    core.close()


def test_stop_stops_reconnecting(bridge, sock_path):
    bridge.start()
    pump(lambda: False, 0.05)
    bridge.stop()
    core = FakeCore(sock_path)
    pump(lambda: False, 0.2)
    with pytest.raises(BlockingIOError):
        core.srv.accept()
    core.close()


def test_send_cmd(bridge, sock_path):
    assert not bridge.send_cmd("push_to_talk")  # desconectado
    core = FakeCore(sock_path)
    bridge.start()
    core.accept()
    assert pump(lambda: bridge.is_connected)
    assert bridge.send_cmd("push_to_talk")
    line = core.recv_line()
    assert json.loads(line) == {"t": "cmd", "name": "push_to_talk"}
    assert decode_hud(line).name == "push_to_talk"
    assert bridge.send_cmd("x", {"a": 1})
    assert json.loads(core.recv_line()) == {"t": "cmd", "name": "x", "args": {"a": 1}}
    core.close()


# -- decodificador mínimo (Python do sistema, sem magi.common) -----------------------------------

VALID = [
    '{"t":"state","v":"listening"}',
    '{"t":"subtitle","text":"oi","full":"oi, tudo?"}',
    '{"t":"subtitle","text":"oi","full":null}',
    '{"t":"speech","text":"oi.","dur":1.23456,"i":2}',
    '{"t":"speech","text":"oi.","dur":2}',
    '{"t":"speech","text":"oi.","dur":null,"i":0}',
    '{"t":"mouth","v":0.4242}',
    '{"t":"mouth","v":3}',
    '{"t":"mouth","v":-1}',
    '{"t":"mood","v":0}',
    '{"t":"vote","verdict":"denied","label":"x"}',
    '{"t":"vote","verdict":"pending"}',
    '{"t":"card","level":"bomba","title":"T"}',
    '{"t":"card","level":"link","title":"T","url":"u","source":"s"}',
    '{"t":"cmd","name":"push_to_talk"}',
    '{"t":"cmd","name":"x","args":{"k":[1]}}',
    '{"t":"cmd","name":"x","args":{}}',
    '{"t":"detail","v":"none"}',
    '{"t":"detail","v":"memory","extra":1}\n',
]

INVALID = [
    "", "nada", "[]", '"state"', '{"t":1}', '{"t":"x"}',
    '{"t":"state"}', '{"t":"state","v":"bravo"}', '{"t":"state","v":1}',
    '{"t":"subtitle"}', '{"t":"subtitle","text":1}',
    '{"t":"speech"}', '{"t":"speech","text":"a","dur":-1}', '{"t":"speech","text":"a","i":true}',
    '{"t":"mouth","v":"0.4"}', '{"t":"mouth","v":true}',
    '{"t":"mood","v":5}', '{"t":"mood","v":-1}', '{"t":"mood","v":2.0}', '{"t":"mood","v":true}',
    '{"t":"vote","verdict":"talvez"}', '{"t":"vote"}',
    '{"t":"card","level":"alta"}', '{"t":"card","level":"x","title":"T"}',
    '{"t":"cmd"}', '{"t":"cmd","name":"x","args":[1]}',
    '{"t":"detail","v":"disk"}',
]


@pytest.mark.parametrize("line", VALID)
def test_min_decoder_matches_contract(line):
    assert hud_bridge._decode_min(line) == decode_hud(line).to_dict()
    assert hud_bridge._decode_min(line.encode()) == hud_bridge._decode_magi(line)


@pytest.mark.parametrize("line", INVALID)
def test_min_decoder_rejects_like_contract(line):
    with pytest.raises(hud_bridge.DecodeError):
        hud_bridge._decode_min(line)
    with pytest.raises(hud_bridge.DecodeError):
        hud_bridge._decode_magi(line)


def test_min_encoder_matches_contract():
    for name, args in [("push_to_talk", None), ("x", {"a": "ç"}), ("y", {})]:
        assert hud_bridge._encode_min(name, args) == hud_bridge._encode_magi(name, args)


def test_bridge_works_with_min_decoder(monkeypatch, bridge):
    monkeypatch.setattr(hud_bridge, "decode_line", hud_bridge._decode_min)
    rec = Recorder(bridge)
    bridge.feed_line(b'{"t":"mouth","v":0.5}')
    bridge.feed_line(b'{"t":"mood","v":7}')
    assert rec.of("mouth") == [(0.5,)]
    assert rec.of("mood") == []


def test_import_without_magi_falls_back(monkeypatch):
    import importlib.util
    import sys

    monkeypatch.setitem(sys.modules, "magi.common.events", None)  # import passa a falhar
    spec = importlib.util.spec_from_file_location("hud_bridge_sem_magi", hud_bridge.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert not mod.HAS_MAGI
    assert mod.decode_line is mod._decode_min
    assert mod.encode_cmd is mod._encode_min
    assert mod.hud_socket_path({"XDG_RUNTIME_DIR": "/r"}) == Path("/r/magi/hud.sock")
