"""Ações de volume e RGB (1.11). Regra 8: pulsectl e servidor OpenRGB falsos, nada real."""

import socket
import struct
import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    Intent,
    IntentId,
    Slot,
    SlotName,
    TurnContext,
    WakeSource,
)
from magi.core.actions import Registry
from magi.core.actions.system import (
    SAY_RGB_DOWN,
    SAY_SOUND_DOWN,
    RgbActions,
    VolumeActions,
    handlers,
    load_orgb,
    parse_color,
)

orgb = load_orgb()
CTX = TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime.now(UTC))


def _req(iid, *slots):
    return ActionRequest(intent=Intent(id=iid, slots=tuple(Slot(n, v) for n, v in slots)), ctx=CTX)


# ---------------------------------------------------------------------------------------------
# pulsectl falso
# ---------------------------------------------------------------------------------------------


class FakePulse:
    def __init__(self, vol=0.5, mute=False, fail=False):
        self.sink = SimpleNamespace(name="fake_sink", mute=int(mute), volume=SimpleNamespace(value_flat=vol))
        self.fail = fail
        self.calls = []

    def __call__(self):
        return self

    def __enter__(self):
        if self.fail:
            raise OSError("sem pulse")
        return self

    def __exit__(self, *a):
        return False

    def server_info(self):
        return SimpleNamespace(default_sink_name="fake_sink")

    def get_sink_by_name(self, name):
        assert name == "fake_sink"
        return self.sink

    def volume_set_all_chans(self, sink, v):
        self.calls.append(("vol", round(v, 2)))
        sink.volume.value_flat = v

    def mute(self, sink, m):
        self.calls.append(("mute", m))
        sink.mute = int(m)


@pytest.mark.parametrize(
    ("value", "start", "want"),
    [("30", 0.5, 30), ("+10", 0.5, 60), ("-10", 0.5, 40),
     ("+", 0.95, 100), ("-", 0.05, 0), ("150", 0.5, 100)],
)
async def test_volume_set(value, start, want):
    p = FakePulse(vol=start)
    res = await VolumeActions(p).run(_req(IntentId.VOLUME_SET, (SlotName.VOLUME, value)))
    assert res.ok and res.speech == f"Volume em {want}."
    assert p.calls == [("vol", want / 100)]


async def test_volume_set_unmutes_when_raising():
    p = FakePulse(vol=0.2, mute=True)
    await VolumeActions(p).run(_req(IntentId.VOLUME_SET, (SlotName.VOLUME, "30")))
    assert p.calls == [("vol", 0.3), ("mute", False)]


async def test_volume_bad_or_missing_slot():
    p = FakePulse()
    assert not (await VolumeActions(p).run(_req(IntentId.VOLUME_SET))).ok
    assert not (await VolumeActions(p).run(_req(IntentId.VOLUME_SET, (SlotName.VOLUME, "alto")))).ok
    assert p.calls == []


async def test_mute_unmute():
    p = FakePulse()
    act = VolumeActions(p)
    assert (await act.run(_req(IntentId.VOLUME_MUTE))).speech == "Mutado."
    assert (await act.run(_req(IntentId.VOLUME_MUTE))).speech == "Já está no mudo."
    assert (await act.run(_req(IntentId.VOLUME_UNMUTE))).speech == "Som de volta."
    assert p.calls == [("mute", True), ("mute", False)]


async def test_volume_pulse_down():
    res = await VolumeActions(FakePulse(fail=True)).run(_req(IntentId.VOLUME_MUTE))
    assert not res.ok and res.speech == SAY_SOUND_DOWN


# ---------------------------------------------------------------------------------------------
# OpenRGB falso: servidor TCP que entende SET_NAME, PROTO, COUNT, DATA, UPDATELEDS e UPDATEMODE
# ---------------------------------------------------------------------------------------------


def _s(text):
    b = text.encode() + b"\0"
    return struct.pack("<H", len(b)) + b


def _mode(name, flags, color_mode, colors=(), cmin=0, cmax=0, bmax=0, brightness=0):
    return {"name": name, "value": 0, "flags": flags, "smin": 0, "smax": 0, "bmin": 0, "bmax": bmax,
            "cmin": cmin, "cmax": cmax, "speed": 0, "brightness": brightness, "direction": 0,
            "color_mode": color_mode, "colors": list(colors)}


PER_LED, MODE_COLOR, BRIGHT = orgb.MODE_HAS_PER_LED, orgb.MODE_HAS_MODE_COLOR, orgb.MODE_HAS_BRIGHTNESS


def _board(active=0):
    modes = [_mode("Direct", PER_LED | BRIGHT, 1, bmax=255, brightness=255),
             _mode("Static", MODE_COLOR | BRIGHT, 2, [(9, 9, 9)], 1, 1, 255, 255),
             _mode("Color Cycle", BRIGHT, 0, bmax=255, brightness=255)]
    return {"type": orgb.TYPE_MOTHERBOARD, "name": "Placa", "modes": modes, "active": active,
            "colors": [(0, 0, 40)] * 4}


def _ram(active=0):
    modes = [_mode("Direct", PER_LED, 1), _mode("Off", 0, 0), _mode("Rainbow", 1, 0)]
    return {"type": 1, "name": "RAM", "modes": modes, "active": active, "colors": [(0, 0, 0)] * 3}


def _ser(dev, proto):
    body = struct.pack("<i", dev["type"]) + _s(dev["name"]) + _s("v") + b"".join(_s("x") for _ in range(4))
    body += struct.pack("<Hi", len(dev["modes"]), dev["active"])
    body += b"".join(orgb.pack_mode(m, proto) for m in dev["modes"])
    n = len(dev["colors"])
    body += struct.pack("<H", 1) + _s("z") + struct.pack("<iIIIH", 0, n, n, n, 0)
    body += struct.pack("<H", n) + b"".join(_s(f"L{i}") + struct.pack("<I", i) for i in range(n))
    body += orgb.pack_colors(dev["colors"])
    return struct.pack("<I", 4 + len(body)) + body


def _parse_mode(data, proto):
    rd = orgb.Reader(data)
    m = {"name": rd.string(), "value": rd.i32(), "flags": rd.u32(), "smin": rd.u32(), "smax": rd.u32()}
    if proto >= 3:
        m["bmin"], m["bmax"] = rd.u32(), rd.u32()
    m["cmin"], m["cmax"], m["speed"] = rd.u32(), rd.u32(), rd.u32()
    if proto >= 3:
        m["brightness"] = rd.u32()
    m["direction"], m["color_mode"], m["colors"] = rd.u32(), rd.u32(), rd.colors()
    return m


class FakeOpenRGB:
    def __init__(self, devices, proto=3):
        self.devices, self.proto, self.log = devices, proto, []
        self.srv = socket.create_server(("127.0.0.1", 0))
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self):
        self.srv.close()

    def _serve(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            with conn:
                self._client(conn)

    def _client(self, conn):
        f = conn.makefile("rb")
        proto = self.proto
        while (hdr := f.read(16)) and len(hdr) == 16:
            assert hdr[:4] == b"ORGB"
            dev, pkt, size = struct.unpack("<III", hdr[4:])
            data = f.read(size)

            def reply(payload, dev=dev, pkt=pkt):
                conn.sendall(b"ORGB" + struct.pack("<III", dev, pkt, len(payload)) + payload)

            if pkt == orgb.REQ_PROTO:
                proto = min(proto, struct.unpack("<I", data)[0])
                reply(struct.pack("<I", self.proto))
            elif pkt == orgb.REQ_COUNT:
                self.log.append("count")
                reply(struct.pack("<I", len(self.devices)))
            elif pkt == orgb.REQ_DATA:
                reply(_ser(self.devices[dev], proto))
            elif pkt == orgb.UPDATE_LEDS:
                assert struct.unpack_from("<I", data)[0] == size
                cols = orgb.Reader(data[4:]).colors()
                assert len(cols) == len(self.devices[dev]["colors"])
                self.devices[dev]["colors"] = cols
                self.log.append(("leds", dev, cols[0]))
            elif pkt == orgb.UPDATE_MODE:
                assert struct.unpack_from("<I", data)[0] == size
                idx = struct.unpack_from("<i", data, 4)[0]
                m = _parse_mode(data[8:], proto)
                self.devices[dev]["modes"][idx] = m
                self.devices[dev]["active"] = idx
                self.log.append(("mode", dev, m["name"], m["color_mode"], m["colors"], m.get("brightness")))


@pytest.fixture
def fake_rgb():
    servers = []

    def make(devices, proto=3):
        s = FakeOpenRGB(devices, proto)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def _rgb(srv, board_only=False):
    return RgbActions(port=srv.port, board_only=board_only, orgb=orgb)


async def test_rgb_color_all_devices_per_led(fake_rgb):
    srv = fake_rgb([_board(), _ram()])
    res = await _rgb(srv).run(_req(IntentId.RGB_COLOR, (SlotName.COLOR, "azul")))
    assert res.ok and res.speech == "RGB azul."
    assert srv.log == ["count", ("leds", 0, (0, 0, 255)), ("leds", 1, (0, 0, 255)), "count"]
    assert srv.devices[0]["colors"] == [(0, 0, 255)] * 4


async def test_rgb_color_hex_board_only_mode_specific(fake_rgb):
    srv = fake_rgb([_ram(), _board(active=1)])
    res = await _rgb(srv, board_only=True).run(_req(IntentId.RGB_COLOR, (SlotName.COLOR, "#FF0000")))
    assert res.ok and res.speech == "RGB vermelho."
    assert ("mode", 1, "Static", 2, [(255, 0, 0)], 255) in srv.log
    assert not any(e[0] == "leds" for e in srv.log if isinstance(e, tuple))


async def test_rgb_color_switches_from_effect_and_off(fake_rgb):
    srv = fake_rgb([_board(active=2), _ram(active=1)])
    res = await _rgb(srv).run(_req(IntentId.RGB_COLOR, (SlotName.COLOR, "Roxo")))
    assert res.ok
    assert srv.devices[0]["active"] == 0 and srv.devices[1]["active"] == 0
    assert ("leds", 1, orgb_color("roxo")) in srv.log
    # a leitura do HUD continua funcionando e vê a cor nova
    cli = orgb.OpenRGB(port=srv.port)
    assert cli.devices()[1]["colors"][0] == orgb_color("roxo")
    cli.close()


def orgb_color(name):
    return parse_color(name)[0]


async def test_rgb_brightness_mode_and_scaled(fake_rgb):
    ram = _ram()
    ram["colors"] = [(0, 0, 200)] * 3
    srv = fake_rgb([_board(), ram])
    res = await _rgb(srv).run(_req(IntentId.RGB_BRIGHTNESS, (SlotName.BRIGHTNESS, "50")))
    assert res.ok and res.speech == "Brilho em 50%."
    assert ("mode", 0, "Direct", 1, [], 128) in srv.log  # placa: brilho do modo
    assert ("leds", 1, (0, 0, 128)) in srv.log  # RAM sem brilho: cor escalada


async def test_rgb_brightness_proto2_without_color(fake_rgb):
    srv = fake_rgb([_ram()], proto=2)
    res = await _rgb(srv).run(_req(IntentId.RGB_BRIGHTNESS, (SlotName.BRIGHTNESS, "80")))
    assert not res.ok and srv.log == ["count", "count"]


async def test_rgb_unknown_color(fake_rgb):
    srv = fake_rgb([_board()])
    res = await _rgb(srv).run(_req(IntentId.RGB_COLOR, (SlotName.COLOR, "marrom")))
    assert not res.ok and srv.log == []


async def test_rgb_offline():
    s = socket.create_server(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    res = await RgbActions(port=port, orgb=orgb).run(_req(IntentId.RGB_COLOR, (SlotName.COLOR, "verde")))
    assert not res.ok and res.speech == SAY_RGB_DOWN


def test_parse_color():
    assert parse_color("ciano") == ((0, 255, 255), "ciano")
    assert parse_color("cor amarela")[1] == "amarelo"
    assert parse_color("#00ff00") == ((0, 255, 0), "verde")
    assert parse_color("#123456") == ((0x12, 0x34, 0x56), "")
    assert parse_color("xyz") is None


def test_handlers_register():
    hs = handlers(pulse_factory=FakePulse())
    assert all(isinstance(h, ActionHandler) for h in hs)
    reg = Registry(hs)
    for iid in (IntentId.VOLUME_SET, IntentId.VOLUME_MUTE, IntentId.VOLUME_UNMUTE,
                IntentId.RGB_COLOR, IntentId.RGB_BRIGHTNESS):
        assert reg.handles(iid)
