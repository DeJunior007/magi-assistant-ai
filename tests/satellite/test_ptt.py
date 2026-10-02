"""Apertar pra falar com D-Bus e evdev falsos (nada toca o KGlobalAccel/KWin de verdade)."""

import asyncio
from types import SimpleNamespace

import pytest
from dbus_next import Message, MessageType
from evdev import ecodes

from magi.common.contracts import CHUNK_SAMPLES, AudioEndReason, WakeEvent, WakeSource
from magi.satellite.__main__ import wake_loop
from magi.satellite.ptt import (
    ACTION,
    ACTION_ID,
    COMP_IFACE,
    COMPONENT,
    DualSensePtt,
    KeyboardPtt,
    PttSettings,
    PttSource,
    PushToTalk,
    find_dualsense,
    parse_key,
    qkeyseq,
)
from magi.satellite.wake import WakeSpotter


def test_qkeyseq_sempre_quatro_inteiros():
    for key in ("Pause", "Meta+Ctrl+Alt+F12", "ScrollLock", "F35"):
        seq = qkeyseq(parse_key(key))
        assert len(seq) == 1 and len(seq[0]) == 4 and seq[0][1:] == [0, 0, 0]
    assert parse_key("Pause") == 0x01000008
    with pytest.raises(ValueError):
        parse_key("Hyper+X")


def test_settings():
    assert PttSettings.from_raw({}) == PttSettings(True, "Pause", True)
    s = PttSettings.from_raw({"satellite": {"ptt_keyboard": False, "ptt_dualsense": False, "ptt_key": "F13"}})
    assert (s.keyboard, s.dualsense, s.key) == (False, False, "F13")
    with pytest.raises(ValueError):
        PttSettings.from_raw({"satellite": {"ptt_key": "Nada"}})


def test_maquina_unica_duas_fontes():
    ptt = PushToTalk()
    ptt.set(PttSource.KEYBOARD, True)
    ptt.set(PttSource.DUALSENSE, True)
    ptt.set(PttSource.KEYBOARD, False)
    assert ptt.pressed  # o controle ainda segura
    ptt.set(PttSource.DUALSENSE, False)
    assert not ptt.pressed


class FakeBus:
    """D-Bus falso: grava as chamadas e responde vazio."""

    def __init__(self, applied=([[0x01000008, 0, 0, 0]],)):
        self.calls: list[Message] = []
        self.handlers = []
        self.applied = applied

    def add_message_handler(self, h):
        self.handlers.append(h)

    async def call(self, msg):
        self.calls.append(msg)
        body = [list(self.applied)] if msg.member == "setShortcutKeys" else []
        return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=body, error_name=None)

    def emit(self, member, action=ACTION):
        msg = SimpleNamespace(message_type=MessageType.SIGNAL, interface=COMP_IFACE, member=member,
                              body=[COMPONENT, action, 123])
        for h in self.handlers:
            h(msg)


async def test_teclado_registra_com_4_inteiros_e_segue_sinais():
    bus, ptt = FakeBus(), PushToTalk()
    kb = KeyboardPtt(ptt, "Pause", bus=bus)
    task = asyncio.create_task(kb.run())
    await asyncio.sleep(0.01)
    kga = [m for m in bus.calls if m.destination == "org.kde.kglobalaccel"]
    assert [m.member for m in kga] == ["doRegister", "setShortcutKeys"]
    setk = kga[1]
    assert setk.signature == "asa(ai)u"
    assert setk.body == [ACTION_ID, [[[0x01000008, 0, 0, 0]]], 6]
    # a(ai) = lista de structs; cada struct (ai) = [lista de 4 ints]. O dbus-next valida ao serializar.
    Message(destination="org.kde.kglobalaccel", path="/kglobalaccel", interface="org.kde.KGlobalAccel",
            member="setShortcutKeys",
            signature="asa(ai)u", body=setk.body)._marshall(False)
    assert all(len(struct[0]) == 4 for struct in setk.body[1])
    assert ACTION_ID[:2] == ["magi-satellite", "push_to_talk"]

    bus.emit("globalShortcutPressed")
    assert ptt.pressed
    bus.emit("globalShortcutRepeated")
    bus.emit("globalShortcutReleased", action="outra")
    assert ptt.pressed
    bus.emit("globalShortcutReleased")
    assert not ptt.pressed

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    last = bus.calls[-1]
    assert (last.member, last.signature, last.body) == ("setInactive", "as", [ACTION_ID])
    assert not any(m.member in ("unregister", "globalShortcutsByKey") for m in bus.calls)


async def test_teclado_sem_kglobalaccel_nao_derruba():
    class Broken(FakeBus):
        async def call(self, msg):
            if msg.member == "doRegister":
                return SimpleNamespace(message_type=MessageType.ERROR, body=["x"], error_name="Err")
            return await super().call(msg)

    await asyncio.wait_for(KeyboardPtt(PushToTalk(), bus=Broken()).run(), 1)


def ev(code, value, type_=ecodes.EV_KEY):
    return SimpleNamespace(type=type_, code=code, value=value)


class FakePad:
    def __init__(self, events, fail=True):
        self.events, self.fail, self.closed, self.grabbed = events, fail, False, False

    async def async_read_loop(self):
        for e in self.events:
            yield e
            await asyncio.sleep(0)
        if self.fail:
            raise OSError(19, "No such device")

    def grab(self):
        self.grabbed = True

    def close(self):
        self.closed = True


def test_dualsense_ps_mais_share():
    ptt = PushToTalk()
    ds = DualSensePtt(ptt, find=lambda: None)
    ds.handle(ev(ecodes.BTN_MODE, 1))
    assert not ptt.pressed  # só PS
    ds.handle(ev(ecodes.BTN_SELECT, 1))
    assert ptt.pressed
    ds.handle(ev(ecodes.BTN_SELECT, 2))  # repetição
    ds.handle(ev(ecodes.BTN_SOUTH, 0))
    ds.handle(ev(ecodes.BTN_MODE, 0, type_=ecodes.EV_ABS))
    assert ptt.pressed
    ds.handle(ev(ecodes.BTN_MODE, 0))  # soltar qualquer um
    assert not ptt.pressed


async def test_dualsense_reconecta_em_outro_no():
    ptt = PushToTalk()
    nodes = iter([None, "/dev/input/event29", None, "/dev/input/event33"])
    pads = {}
    seen = []

    def open_device(path):
        pads[path] = FakePad([ev(ecodes.BTN_MODE, 1), ev(ecodes.BTN_SELECT, 1)])
        return pads[path]

    ds = DualSensePtt(ptt, find=lambda: next(nodes), open_device=open_device, retry_s=0)
    orig = ds.handle
    ds.handle = lambda e: (orig(e), seen.append(ptt.pressed))
    for _ in range(4):
        await ds.read_once()
        assert not ptt.pressed  # desconectou segurando → solto
    assert list(pads) == ["/dev/input/event29", "/dev/input/event33"]
    assert all(p.closed and not p.grabbed for p in pads.values())
    assert seen == [False, True, False, True]


async def test_dualsense_sem_permissao_nao_trava():
    def deny(path):
        raise PermissionError(13, "denied")

    await DualSensePtt(PushToTalk(), find=lambda: "/dev/input/event5", open_device=deny).read_once()


def test_find_dualsense(tmp_path):
    def node(n, vendor, product, name):
        d = tmp_path / f"event{n}" / "device"
        (d / "id").mkdir(parents=True)
        (d / "id" / "vendor").write_text(vendor)
        (d / "id" / "product").write_text(product)
        (d / "name").write_text(name + "\n")

    node(3, "046d", "c52b", "Logitech")
    node(30, "054c", "0ce6", "DualSense Wireless Controller Motion Sensors")
    node(29, "054c", "0ce6", "DualSense Wireless Controller")
    assert find_dualsense(tmp_path) == "/dev/input/event29"
    assert find_dualsense(tmp_path / "nada") is None


class FakeClient:
    def __init__(self):
        self.msgs, self.events = [], []

    async def send(self, msg):
        self.msgs.append(msg)
        return True

    async def send_event(self, event):
        self.events.append(event)
        return True


class ScriptSource:
    """Blocos de silêncio; aperta/solta o atalho nos índices dados."""

    def __init__(self, ptt, n, script):
        self.ptt, self.n, self.script = ptt, n, script

    async def blocks(self):
        for i in range(self.n):
            if i in self.script:
                self.ptt.set(PttSource.KEYBOARD, self.script[i])
            yield bytes(CHUNK_SAMPLES * 2)


class Silent:
    name = "fake"

    def process(self, block):
        return 0.0

    def reset(self):
        pass


async def test_grava_enquanto_pressionado():
    from magi.common.events import from_event

    ptt, client = PushToTalk(), FakeClient()
    src = ScriptSource(ptt, 30, {5: True, 15: False})
    await wake_loop(src, WakeSpotter(Silent(), gate_dbfs=None), client, "pc", vad=Silent(), ptt=ptt)
    assert client.msgs == [WakeEvent(source=WakeSource.PTT, satellite="pc")]
    types = [e.type for e in client.events]
    assert types[0] == "audio-start" and types[-1] == "audio-stop"
    assert types.count("audio-stop") == 1
    # silêncio não encerra o PTT (VAD só mede o tom); fim por soltar o atalho
    assert from_event(client.events[-1]).reason == AudioEndReason.PTT_RELEASE
    assert types.count("audio-chunk") >= 10
