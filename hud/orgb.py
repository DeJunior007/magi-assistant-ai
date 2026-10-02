"""Cliente mínimo do SDK do OpenRGB: leitura das cores atuais e escrita de cor/brilho.

Só stdlib (o HUD roda com o Python do sistema). Escrita: UPDATEMODE (1101) troca o modo ativo
e seus campos (cores do modo, brilho); UPDATELEDS (1050) pinta todos os LEDs do controlador.
O servidor não responde a esses pacotes; um REQUEST_CONTROLLER_COUNT no fim serve de barreira.
"""
import socket
import struct

REQ_COUNT, REQ_DATA, REQ_PROTO, SET_NAME = 0, 1, 40, 50
UPDATE_LEDS, UPDATE_MODE = 1050, 1101
MODE_HAS_BRIGHTNESS, MODE_HAS_PER_LED, MODE_HAS_MODE_COLOR = 1 << 4, 1 << 5, 1 << 6
COLOR_MODE_PER_LED, COLOR_MODE_SPECIFIC = 1, 2
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
        m["smin"], m["smax"] = rd.u32(), rd.u32()
        if proto >= 3:
            m["bmin"], m["bmax"] = rd.u32(), rd.u32()
        m["cmin"], m["cmax"] = rd.u32(), rd.u32()
        m["speed"] = rd.u32()
        if proto >= 3:
            m["brightness"] = rd.u32()
        m["direction"] = rd.u32()
        m["color_mode"] = rd.u32()
        m["colors"] = rd.colors()
        modes.append(m)
    for _ in range(rd.u16()):      # zonas
        rd.string()                # nome
        rd.i += 16                 # tipo, leds min/max/count
        mlen = rd.u16()
        rd.i += mlen
    for _ in range(rd.u16()):      # leds
        rd.string()
        rd.u32()                   # valor do led
    dev["colors"] = rd.colors()
    dev["mode"] = modes[active] if 0 <= active < len(modes) else None
    dev["modes"], dev["active"] = modes, active
    return dev


def pack_mode(mode, proto):
    """Serializa um modo no formato do SDK (mesma ordem de ``parse_controller``)."""
    name = mode["name"].encode() + b"\0"
    out = struct.pack("<H", len(name)) + name
    out += struct.pack("<iIII", mode["value"], mode["flags"], mode.get("smin", 0), mode.get("smax", 0))
    if proto >= 3:
        out += struct.pack("<II", mode.get("bmin", 0), mode.get("bmax", 0))
    out += struct.pack("<III", mode.get("cmin", 0), mode.get("cmax", 0), mode.get("speed", 0))
    if proto >= 3:
        out += struct.pack("<I", mode.get("brightness", 0))
    out += struct.pack("<II", mode.get("direction", 0), mode["color_mode"])
    return out + pack_colors(mode.get("colors", []))


def pack_colors(colors):
    return struct.pack("<H", len(colors)) + b"".join(bytes((r, g, b, 0)) for r, g, b in colors)


class OpenRGB:
    def __init__(self, host="127.0.0.1", port=6742, timeout=0.5, name="GamerHUD"):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self._send(0, SET_NAME, name.encode() + b"\0")
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

    # --- escrita -------------------------------------------------------------------------
    def update_leds(self, dev, colors):
        """UPDATELEDS: uma cor por LED do controlador ``dev`` (índice)."""
        body = pack_colors(colors)
        self._send(dev, UPDATE_LEDS, struct.pack("<I", 4 + len(body)) + body)

    def update_mode(self, dev, index, mode):
        """UPDATEMODE: torna ``index`` o modo ativo com os campos de ``mode``."""
        body = struct.pack("<i", index) + pack_mode(mode, self.proto)
        self._send(dev, UPDATE_MODE, struct.pack("<I", 4 + len(body)) + body)

    def sync(self):
        """Barreira: o servidor trata os pacotes em ordem, então a resposta vem depois deles."""
        self._send(0, REQ_COUNT)
        self._recv(REQ_COUNT)

    def apply_color(self, idx, dev, rgb):
        """Pinta o controlador ``idx`` com ``rgb``. Devolve False se nenhum modo aceita cor."""
        modes, active = dev["modes"], dev["active"]
        order = [active] if 0 <= active < len(modes) else []
        prefs = ("direct", "static", "custom")
        order += sorted((i for i in range(len(modes)) if i != active),
                        key=lambda i: prefs.index(modes[i]["name"].lower())
                        if modes[i]["name"].lower() in prefs else len(prefs))
        for i in order:
            m = dict(modes[i])
            static = i == active or m["name"].lower() in prefs
            if not static:
                continue
            if m["flags"] & MODE_HAS_PER_LED:
                if i != active or m["color_mode"] != COLOR_MODE_PER_LED:
                    m["color_mode"] = COLOR_MODE_PER_LED
                    self.update_mode(idx, i, m)
                self.update_leds(idx, [rgb] * len(dev["colors"]))
                return True
            if m["flags"] & MODE_HAS_MODE_COLOR and m.get("cmax", 0) >= 1:
                m["color_mode"] = COLOR_MODE_SPECIFIC
                m["colors"] = [rgb] * max(len(m.get("colors", [])), m.get("cmin", 0), 1)
                self.update_mode(idx, i, m)
                return True
        return False

    def apply_brightness(self, idx, dev, frac):
        """Brilho ``frac`` (0..1): pelo modo, se ele tiver brilho; senão escala as cores."""
        m = dict(dev["mode"] or {})
        if m and m["flags"] & MODE_HAS_BRIGHTNESS and m.get("bmax", 0) > m.get("bmin", 0):
            m["brightness"] = round(m["bmin"] + frac * (m["bmax"] - m["bmin"]))
            self.update_mode(idx, dev["active"], m)
            return True
        base = _base_color(dev)
        if base is None:
            return False
        return self.apply_color(idx, dev, tuple(round(c * frac) for c in base))


def _base_color(dev):
    """Cor dominante do dispositivo normalizada para o canal máximo 255, ou None."""
    mode = dev["mode"] or {}
    cols = [c for c in dev["colors"] if any(c)] or [c for c in mode.get("colors", []) if any(c)]
    if not cols:
        return None
    c = max(cols, key=lambda c: max(c) - min(c) + max(c) / 4)
    k = 255 / max(c)
    return tuple(min(255, round(x * k)) for x in c)


def _write(fn, board_only, host, port, timeout, name):
    cli = OpenRGB(host, port, timeout, name)
    try:
        devs = cli.devices()
        done = 0
        for idx, dev in enumerate(devs):
            if board_only and dev["type"] != TYPE_MOTHERBOARD:
                continue
            done += bool(fn(cli, idx, dev))
        cli.sync()
        return done
    finally:
        cli.close()


def set_color(rgb, board_only=False, host="127.0.0.1", port=6742, timeout=1.0, name="GamerHUD"):
    """Aplica ``rgb`` (r, g, b) em todos os dispositivos (ou só na placa-mãe).

    Devolve quantos controladores aceitaram. Levanta ``OSError``/``ConnectionError`` se o
    OpenRGB não responder.
    """
    rgb = tuple(int(c) & 0xFF for c in rgb)
    return _write(lambda cli, i, d: cli.apply_color(i, d, rgb), board_only, host, port, timeout, name)


def set_brightness(pct, board_only=False, host="127.0.0.1", port=6742, timeout=1.0, name="GamerHUD"):
    """Brilho 0..100 em todos os dispositivos (ou só na placa-mãe). Igual a ``set_color``."""
    frac = max(0, min(100, pct)) / 100
    return _write(lambda cli, i, d: cli.apply_brightness(i, d, frac), board_only, host, port, timeout, name)


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
        print(d["type"], d["name"], "| modo:", m.get("name"),
              "brilho:", m.get("brightness"), "/", m.get("bmax"),
              "| cores únicas:", sorted(set(d["colors"]))[:6], "| cores do modo:", m.get("colors"))
    print("tema:", board_color())
