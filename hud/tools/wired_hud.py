#!/usr/bin/env python3
"""HUD real (gamerhud.HUD, tema wired) montado offscreen: PNGs das telas e medição de CPU (R23.8).

    QT_QPA_PLATFORM=offscreen uv run python hud/tools/wired_hud.py shots [pasta]
    QT_QPA_PLATFORM=offscreen uv run python hud/tools/wired_hud.py bench [segundos] [awake]

Não toca na sessão ao vivo: settings em memória (nada é gravado no settings.json do HUD), ponte
com a Magui num socket que ninguém escuta e OpenRGB só lido. `shots` grava
`hud-{full,idle}-{standby,gaming}.png` (2560×1440); o modo "gaming" injeta um jogo e uma faixa
falsos só para a foto. `bench` deixa o HUD rodando com os timers reais e mede a CPU do processo
(`/proc/self/stat`, utime+stime) em cada tela.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HUD_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HUD_DIR))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SETTINGS: dict = {"view": "full", "transition": False, "ui": "wired", "rgb_sync": True}


def make_hud():
    import gamerhud
    import hud_bridge

    gamerhud.load_settings = lambda: dict(SETTINGS)
    gamerhud.save_settings = lambda data: SETTINGS.update(data)
    gamerhud.settings_mtime = lambda: 1.0
    sock = Path(tempfile.mkdtemp()) / "hud.sock"
    w = gamerhud.HUD({"seg": "Hack"}, bridge=hud_bridge.HudBridge(sock))
    w.resize(2560, 1440)
    w.show()
    return gamerhud, w


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class FakeNowPlaying:
    """Faixa fixa para a foto do modo "gaming" (o Spotify real pode estar fechado)."""
    title, artist, album, year = "Duvet", "bôa", "Twilight", "2001"
    length, status, active = 203.0, "Playing", True

    def position(self, now=None):
        return 74.0

    def cover_pixmap(self):
        pm = QPixmap(300, 300)
        pm.fill(QColor("#3a4a6a"))
        return pm

    def tick(self, now=None):
        pass


def cpu_seconds() -> float:
    f = open("/proc/self/stat").read().rsplit(")", 1)[1].split()
    return (int(f[11]) + int(f[12])) / os.sysconf("SC_CLK_TCK")


def shots(out: Path) -> None:
    gh, w = make_hud()
    out.mkdir(parents=True, exist_ok=True)
    pump(1500)
    for mode in ("standby", "gaming"):
        if mode == "gaming":
            w.wired.now_playing = FakeNowPlaying()
            fps = iter([118, 121, 97, 124, 120, 119, 122] * 50)

            def fake_poll(fps=fps):
                w.fpsrc.name, w.fpsrc.fps = "ELDEN RING", float(next(fps))
            w.fpsrc.poll = fake_poll
            for _ in range(7):
                fake_poll()
                w.wired.fps.push(w.fpsrc.fps, time.monotonic())
            w.wired.set_mood(3)
            w.wired.set_state("speaking")
            w.wired.set_mouth(0.6)
            w.wired.set_caption("Boss na fase 2: espera o golpe de área e rola pra dentro.")
        for view in ("full", "idle"):
            w.view = view
            w.wired_refresh()
            w.update()
            pump(300)
            path = out / f"hud-{view}-{mode}.png"
            w.grab().save(str(path))
            print(path)
    w.close()


def bench(seconds: float, awake: bool = False) -> None:
    """`awake`: Magui falando (mascote a 30 fps, pior caso) em vez de dormindo."""
    gh, w = make_hud()
    if awake:  # boca seguindo um "áudio" a 20 Hz, como o magi-mouth
        import random
        w.on_face_state("speaking")
        mouth = QTimer(w, timeout=lambda: w.on_face_mouth(random.random()))
        mouth.start(50)
    pump(2000)
    for view in ("full", "idle"):
        w.view = view
        w.update()
        pump(1500)
        c0, t0 = cpu_seconds(), time.monotonic()
        pump(int(seconds * 1000))
        pct = 100.0 * (cpu_seconds() - c0) / (time.monotonic() - t0)
        print(f"{view}{' (falando)' if awake else ''}: {pct:.2f}% de um núcleo em {seconds:.0f} s")
    w.close()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    cmd = sys.argv[1] if len(sys.argv) > 1 else "shots"
    if cmd == "bench":
        bench(float(sys.argv[2]) if len(sys.argv) > 2 else 60.0, awake="awake" in sys.argv[3:])
    else:
        shots(Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / ".cache/gamerhud/wired-demo")


if __name__ == "__main__":
    main()
