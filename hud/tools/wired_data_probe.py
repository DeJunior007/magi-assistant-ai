#!/usr/bin/env python3
"""Imprime por ~N s os dados reais da U2 (rede, CPU/RAM no histórico, Spotify, capa). Só leitura.

    python3 hud/tools/wired_data_probe.py [segundos] [--bus org.mpris.MediaPlayer2.spotify]
"""

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PySide6.QtGui import QGuiApplication  # noqa: E402
from wired.data import (  # noqa: E402
    BUS_NAME,
    EventLog,
    LoadHistory,
    MprisBackend,
    NetRate,
    NowPlaying,
    fmt_rate,
)


def cpu_ram(prev):
    vals = list(map(int, open("/proc/stat").readline().split()[1:]))
    idle, total = vals[3] + vals[4], sum(vals)
    cpu = 100 * (1 - (idle - prev[0]) / (total - prev[1])) if prev and total > prev[1] else None
    mem = {k: int(v.split()[0]) for k, v in (ln.split(":", 1) for ln in open("/proc/meminfo"))}
    return cpu, 100 * (1 - mem["MemAvailable"] / mem["MemTotal"]), (idle, total)


def main():
    args = sys.argv[1:]
    bus = BUS_NAME
    if "--bus" in args:
        i = args.index("--bus")
        bus = args[i + 1]
        del args[i:i + 2]
    secs = float(args[0]) if args else 20.0
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 (QPixmap precisa)
    net, hist, log = NetRate(), LoadHistory(interval=5), EventLog()
    player = NowPlaying(MprisBackend(bus))
    prev, last_title = None, object()
    end = time.monotonic() + secs
    while time.monotonic() < end:
        t0 = time.perf_counter()
        net.poll()
        player.tick()
        cpu, ram, prev = cpu_ram(prev)
        hist.push(cpu, None, ram, time.time())
        if player.title != last_title:
            last_title = player.title
            log.add(f"spotify: {player.title or 'nada tocando'}")
        pos = player.position()
        pix = player.cover_pixmap()
        size = f"{pix.width()}x{pix.height()}" if pix else ""
        tick_ms = (time.perf_counter() - t0) * 1000
        print(f"net ↓{fmt_rate(net.down)} ↑{fmt_rate(net.up)} | hist {len(hist.points)} pts | "
              f"spotify {player.status or '– –'} {player.artist or ''} — {player.title or ''} "
              f"[{player.album or ''} · {player.year or ''}] "
              f"{'' if pos is None else f'{pos:5.1f}/{player.length or 0:.0f}s'} | "
              f"capa {player.cover_path or '– –'} {size} | "
              f"tick {tick_ms:.2f} ms", flush=True)
        time.sleep(1)
    print("ticker:", log.ticker(3))
    print("eixo:", hist.axis(3))


if __name__ == "__main__":
    main()
