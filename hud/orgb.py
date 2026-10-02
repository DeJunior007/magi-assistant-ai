"""Cliente mínimo do SDK do OpenRGB (só leitura das cores atuais)."""
import socket
import struct

REQ_COUNT, REQ_DATA, REQ_PROTO, SET_NAME = 0, 1, 40, 50
CLIENT_PROTO = 3   # v3 traz o brilho dos modos; sem segmentos (v4+)
TYPE_MOTHERBOARD = 0


class Reader:
    def __init__(self, data):
        self.d, self.i = data, 0

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.i)[0]
        self.i += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.i)[0]
        self.i += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.i)[0]
        self.i += 4
        return v

    def string(self):
        n = self.u16()
        s = self.d[self.i:self.i + n].rstrip(b"\0").decode(errors="ignore")
        self.i += n
        return s

    def colors(self):
        out = []
        for _ in range(self.u16()):
            r, g, b, _x = self.d[self.i:self.i + 4]
            out.append((r, g, b))
            self.i += 4
        return out


def parse_controller(data, proto):
    rd = Reader(data)
    rd.u32()                       # data_size
    dev = {"type": rd.i32(), "name": rd.string()}
    if proto >= 1:
        dev["vendor"] = rd.string()
    for _ in range(4):             # description, version, serial, location
        rd.string()
    n_modes = rd.u16()
    active = rd.i32()
    modes = []
    for _ in range(n_modes):
        m = {"name": rd.string(), "value": rd.i32(), "flags": rd.u32()}
        rd.u32(); rd.u32()         # speed min/max
        if proto >= 3:
            m["bmin"], m["bmax"] = rd.u32(), rd.u32()
        rd.u32(); rd.u32()         # colors min/max
        rd.u32()                   # speed
        if proto >= 3:
            m["brightness"] = rd.u32()
        rd.u32()                   # direction
        m["color_mode"] = rd.u32()
        m["colors"] = rd.colors()
        modes.append(m)
    for _ in range(rd.u16()):      # zonas
        rd.string(); rd.i32(); rd.u32(); rd.u32(); rd.u32()
        mlen = rd.u16()
        rd.i += mlen
    for _ in range(rd.u16()):      # leds
        rd.string(); rd.u32()
    dev["colors"] = rd.colors()
    dev["mode"] = modes[active] if 0 <= active < len(modes) else None
    return dev


class OpenRGB:
    def __init__(self, host="127.0.0.1", port=6742, timeout=0.5):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self._send(0, SET_NAME, b"GamerHUD\0")
        self._send(0, REQ_PROTO, struct.pack("<I", CLIENT_PROTO))
        self.proto = min(CLIENT_PROTO, struct.unpack("<I", self._recv(REQ_PROTO))[0])

    def close(self):
        self.sock.close()

    def _send(self, dev, pkt, payload=b""):
        self.sock.sendall(b"ORGB" + struct.pack("<III", dev, pkt, len(payload)) + payload)

    def _exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("OpenRGB fechou a conexão")
            buf += chunk
        return buf

    def _recv(self, want):
        while True:
            hdr = self._exact(16)
            if hdr[:4] != b"ORGB":
                raise ConnectionError("cabeçalho inválido")
            _dev, pkt, size = struct.unpack("<III", hdr[4:])
            body = self._exact(size)
            if pkt == want:
                return body

    def devices(self):
        self._send(0, REQ_COUNT)
        count = struct.unpack("<I", self._recv(REQ_COUNT))[0]
        out = []
        for i in range(count):
            self._send(i, REQ_DATA, struct.pack("<I", self.proto))
            out.append(parse_controller(self._recv(REQ_DATA), self.proto))
        return out


def board_color():
    """(r, g, b, nível 0..1) da placa-mãe, ou None se o OpenRGB não responder."""
    try:
        cli = OpenRGB()
        devs = cli.devices()
        cli.close()
    except (OSError, ConnectionError, struct.error, IndexError):
        return None
    devs.sort(key=lambda d: d["type"] != TYPE_MOTHERBOARD)
    for dev in devs:
        mode = dev["mode"] or {}
        if mode.get("name", "").lower() == "off":
            return (0, 0, 0, 0.0)
        cols = [c for c in dev["colors"] if any(c)] or [c for c in mode.get("colors", []) if any(c)]
        if not cols:
            if dev["type"] == TYPE_MOTHERBOARD:
                return (0, 0, 0, 0.0)
            continue
        r, g, b = max(cols, key=lambda c: max(c) - min(c) + max(c) / 4)
        level = max(r, g, b) / 255
        if mode.get("bmax"):
            span = mode["bmax"] - mode.get("bmin", 0)
            if span > 0:
                level *= (mode.get("brightness", mode["bmax"]) - mode.get("bmin", 0)) / span
        return (r, g, b, level)
    return None


if __name__ == "__main__":
    cli = OpenRGB()
    print("protocolo", cli.proto)
    for d in cli.devices():
        m = d["mode"] or {}
        print(d["type"], d["name"], "| modo:", m.get("name"), "brilho:", m.get("brightness"), "/", m.get("bmax"),
              "| cores únicas:", sorted(set(d["colors"]))[:6], "| cores do modo:", m.get("colors"))
    print("tema:", board_color())
