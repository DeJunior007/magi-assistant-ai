#!/usr/bin/env python3
"""Vigia do MAGI Gamer: abre o HUD sozinho quando um jogo começa e fecha quando
ele termina (só se foi o vigia que abriu; se você fechar no meio do jogo, ele
não reabre até o próximo jogo).

Detecta jogos da Steam pelo processo `reaper SteamLaunch AppId=N` e qualquer
outro jogo Vulkan pelo log em tempo real do MangoHud.
Config em ~/.config/gamerhud/settings.json: "auto_open" e "auto_close" (true/false).
"""
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HUD = os.path.join(HERE, "gamerhud.py")
CACHE = os.path.expanduser("~/.cache/gamerhud")
FPS_DIR = os.path.join(CACHE, "fps")
SETTINGS = os.path.expanduser("~/.config/gamerhud/settings.json")
PLUGIN_QML = os.path.expanduser(
    "~/.local/share/plasma/wallpapers/com.github.catsout.wallpaperEngineKde/contents/ui/main.qml")
IGNORE_APPIDS = {"228980"}   # Steamworks Common Redistributables (roda na instalação)
POLL_S = 2
GRACE_S = 15                 # espera depois do jogo fechar (cobre launchers que reiniciam)


def settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def cmdlines():
    for e in os.scandir("/proc"):
        if e.name.isdigit():
            try:
                with open(f"/proc/{e.name}/cmdline", "rb") as f:
                    yield int(e.name), f.read()
            except OSError:
                continue


def hud_pid():
    for pid, raw in cmdlines():
        args = raw.split(b"\0")
        if len(args) >= 2 and args[1].endswith(b"gamerhud.py") and b"--" not in raw:
            return pid
    return None


def steam_game():
    """`reaper SteamLaunch AppId=N -- jogo`: argumentos separados, não texto solto
    (um terminal com `grep SteamLaunch` não conta como jogo)."""
    for _pid, raw in cmdlines():
        if b"SteamLaunch" not in raw:
            continue
        args = raw.split(b"\0")
        if b"SteamLaunch" not in args:
            continue
        for a in args:
            m = re.fullmatch(rb"AppId=(\d+)", a)
            if m and m.group(1).decode() not in IGNORE_APPIDS:
                return f"steam:{m.group(1).decode()}"
    return None


def mango_game():
    try:
        newest = max((e for e in os.scandir(FPS_DIR) if e.name.endswith(".csv")),
                     key=lambda e: e.stat().st_mtime, default=None)
    except OSError:
        return None
    if newest and time.time() - newest.stat().st_mtime < 5:
        return "mango:" + re.sub(r"_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.csv$", "", newest.name)
    return None


def ensure_plugin_patch():
    """O plugin do Wallpaper Engine pausa 5 s toda vez que carrega uma cena; deixa em 0,5 s.
    Reaplica se uma atualização do plugin desfizer (vale a partir do próximo login)."""
    try:
        with open(PLUGIN_QML) as f:
            src = f.read()
    except OSError:
        return
    new, n = re.subn(r"(id: playTimer\s*\n\s*running: false\s*\n\s*repeat: false\s*\n\s*interval: )5000",
                     r"\g<1>500", src)
    if n:
        with open(PLUGIN_QML, "w") as f:
            f.write(new)


def main():
    os.makedirs(CACHE, exist_ok=True)
    lock = open(os.path.join(CACHE, "watch.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)   # já tem um vigia rodando
    ensure_plugin_patch()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    current = None        # jogo em andamento
    gone_since = None
    child = None          # HUD que o vigia abriu
    while True:
        if child and child.poll() is not None:
            child = None  # HUD fechou (pelo usuário ou por nós)
        cfg = settings()
        game = steam_game() or mango_game()
        if game:
            gone_since = None
            if game != current:
                current = game
                if cfg.get("auto_open", True) and hud_pid() is None:
                    child = subprocess.Popen(["python3", HUD], start_new_session=True,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif current:
            gone_since = gone_since or time.monotonic()
            if time.monotonic() - gone_since >= GRACE_S:
                current = gone_since = None
                if child and cfg.get("auto_close", True):
                    child.terminate()   # SIGTERM: o HUD restaura o wallpaper ao sair
                    try:
                        child.wait(10)
                    except subprocess.TimeoutExpired:
                        pass
                    child = None
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
