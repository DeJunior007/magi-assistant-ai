#!/usr/bin/env python3
"""GamerHUD: cobre o monitor secundário com um painel estilo NERV/MAGI.

- Desenhado na CPU (QPainter/raster): fundo e textos ficam em cache e só a
  rolagem do gráfico e as barras são redesenhadas por frame. GPU ~ zero.
- FPS vem dos logs em tempo real do MangoHud (~/.config/MangoHud/MangoHud.conf).
- A cor do tema segue a cor da placa-mãe no OpenRGB (servidor SDK :6742).
- Enquanto aberto, pausa as cenas do Wallpaper Engine (plugin KDE) em todos
  os monitores e restaura a configuração ao fechar.
Fica abaixo das outras janelas (regra do KWin), então dá pra usar o monitor
normalmente por cima dele. Duplo clique fecha.
`gamerhud.py --restore` só restaura o wallpaper (mesmo sem wallpaper_state.json); `--install-icons` gera os ícones.
"""
import datetime
import glob
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from collections import deque

from PySide6.QtCore import QCoreApplication, QPointF, QRectF, QSocketNotifier, Qt, QTimer
from PySide6.QtDBus import QDBusConnection, QDBusInterface
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication, QIcon, QImage,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF, QRegion)
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import orgb  # noqa: E402
import hud_bridge  # noqa: E402
import konsole_term  # noqa: E402
from face import Face  # noqa: E402
from speech_caption import SpeechCaption  # noqa: E402
from turn_phase import TurnPhase  # noqa: E402
from wired import fonts as wfonts  # noqa: E402
from wired import konsole_view as kview  # noqa: E402
from wired import theme as wtheme  # noqa: E402
from wired.data import ClaudeStats  # noqa: E402
from wired.integration import CARD_DETAIL, WiredUI, learning_toggle, rgb_hex  # noqa: E402
from wired.learning_model import LearningModel, check_say  # noqa: E402

TARGET_SCREEN = os.environ.get("GAMERHUD_SCREEN", "DP-1")
CACHE = os.path.expanduser("~/.cache/gamerhud")
FPS_DIR = os.path.join(CACHE, "fps")
WP_STATE = os.path.join(CACHE, "wallpaper_state.json")
RGB_STATE = os.path.join(CACHE, "last_rgb.json")
SETTINGS = os.path.expanduser("~/.config/gamerhud/settings.json")


def load_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w") as f:
        json.dump(data, f)


def settings_mtime():
    try:
        return os.path.getmtime(SETTINGS)
    except OSError:
        return 0.0
WE_PLUGIN = "com.github.catsout.wallpaperEngineKde"
SAMPLE_MS = 500        # coleta de dados (igual ao log_interval do MangoHud)
ANIM_MS = 33           # ~30 fps só nas regiões animadas
RGB_MS = 300          # consulta ao OpenRGB (~0,5 ms cada)
HISTORY = 240          # 2 min de histórico
IDLE_AVG_S = 300       # tela de ociosidade: média de FPS atualizada a cada 5 min
TRANSITION_S = 0.55    # cortina ao trocar de tela (Meta+M)
UI_DEFAULT = "wired"   # settings.json "ui": "wired" (R23) | "eva" (tema antigo, R23.9)
DEFAULT_RGB = (255, 140, 26, 1.0)   # laranja NERV quando o OpenRGB não responde

DIAS = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]
DIAS_JP = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN",
         "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def hwmon(name):
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(f"{d}/name") == name:
            return d
    return None


def alpha(c, a):
    c = QColor(c)
    c.setAlpha(a)
    return c


# ---------------------------------------------------------------- tema / RGB

def luminance(c):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c.red()) + 0.7152 * lin(c.green()) + 0.0722 * lin(c.blue())


class Theme:
    """Paleta derivada da cor da placa-mãe; `level` escurece tudo junto."""

    def __init__(self, r, g, b, level):
        self.off = level < 0.04
        if self.off:
            base, bright = QColor(150, 155, 165), 0.5
        else:
            c = QColor(int(r), int(g), int(b))
            h, s = c.hsvHueF(), c.hsvSaturationF()
            if s < 0.18 or h < 0:
                base = QColor.fromHsvF(max(h, 0.0), s * 0.5, 0.95)
            else:
                base = QColor.fromHsvF(h, max(s, 0.75), 1.0)
            # azul/roxo puros quase somem no fundo escuro: clareia até ficar legível
            while luminance(base) < 0.2:
                base = QColor(base.red() + (255 - base.red()) // 10 + 1,
                              base.green() + (255 - base.green()) // 10 + 1, base.blue())
            bright = 0.5 + 0.5 * min(1.0, level)
        self.level = bright
        self.raw = QColor(int(r), int(g), int(b))

        def k(c, a=255):
            return QColor(int(c.red() * bright), int(c.green() * bright), int(c.blue() * bright), a)

        hue = max(base.hsvHueF(), 0.0)
        sat = base.hsvSaturationF()
        self.accent = k(base)
        self.dim = k(base.lighter(130), 120)
        self.white = k(QColor("#f4ede4"))
        self.green = k(QColor("#3dff7a"))
        self.amber = k(QColor("#ffb300"))
        self.red = k(QColor("#ff2a2a"))
        self.purple = k(QColor("#a46bff"))
        self.bg_top = QColor.fromHsvF(hue, 0.6 * sat, 0.045)
        self.bg_bot = QColor.fromHsvF(hue, 0.5 * sat, 0.015)
        self.plot_bg = QColor.fromHsvF(hue, 0.5 * sat, 0.03)
        self.ink = QColor.fromHsvF(hue, 0.6 * sat, 0.04)


T = Theme(*DEFAULT_RGB)


def status(value, warn, danger):
    """Selo de status estilo MAGI: (kanji, inglês, cor)."""
    if value is None:
        return "不明", "N/A", T.dim
    if value >= danger:
        return "危険", "DANGER", T.red
    if value >= warn:
        return "注意", "CAUTION", T.amber
    return "正常", "NORMAL", T.green


def resolve_rgb(res):
    """No boot o perfil de inicialização do OpenRGB não define cor e ele reporta
    tudo preto mesmo com os LEDs acesos. Preto só conta como "apagado" se já
    vimos outra coisa neste boot; senão usa a última cor conhecida."""
    if res is None:
        return None
    boot = read("/proc/sys/kernel/random/boot_id", "")
    try:
        with open(RGB_STATE) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = None
    if res[3] < 0.04 and saved and saved.get("boot") != boot:
        return tuple(saved["rgb"])
    if not saved or saved.get("boot") != boot or list(saved["rgb"]) != list(res):
        os.makedirs(CACHE, exist_ok=True)
        with open(RGB_STATE, "w") as f:
            json.dump({"boot": boot, "rgb": list(res)}, f)
    return res


# --------------------------------------------------------------------- ícone

ICON_SIZES = (16, 22, 24, 32, 48, 64, 128, 256)


def make_icon(size, accent):
    """Hexágono MAGI estilo NERV, na cor do tema."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    c, r = size / 2, size * 0.48
    hexa = QPolygonF([QPointF(c + r * dx, c + r * dy) for dx, dy in
                      ((0, -1), (0.866, -0.5), (0.866, 0.5), (0, 1), (-0.866, 0.5), (-0.866, -0.5))])
    g = QLinearGradient(0, 0, 0, size)
    g.setColorAt(0, QColor(30, 16, 10))
    g.setColorAt(1, QColor(6, 3, 4))
    p.setBrush(g)
    p.setPen(QPen(accent, max(1.0, size * 0.055)))
    p.drawPolygon(hexa)
    font = QFont("Noto Serif")
    font.setWeight(QFont.Black)
    font.setStretch(QFont.ExtraCondensed)
    if size < 32:
        font.setPixelSize(int(size * 0.62))
        p.setFont(font)
        p.setPen(accent)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, "M")
    else:
        font.setPixelSize(int(size * 0.34))
        p.setFont(font)
        p.setPen(QColor("#f4ede4"))
        p.drawText(QRectF(0, size * 0.22, size, size * 0.38), Qt.AlignCenter, "MAGI")
        bar = QRectF(size * 0.24, size * 0.64, size * 0.52, size * 0.1)
        p.save()
        p.setClipRect(bar)
        p.fillRect(bar, QColor(0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        w = bar.height()
        x = bar.left() - w
        while x < bar.right():
            p.drawPolygon(QPolygonF([QPointF(x, bar.bottom()), QPointF(x + w, bar.top()),
                                     QPointF(x + 2 * w, bar.top()), QPointF(x + w, bar.bottom())]))
            x += 2.4 * w
        p.restore()
        font.setPixelSize(int(size * 0.11))
        p.setFont(font)
        p.setPen(accent)
        p.drawText(QRectF(0, size * 0.76, size, size * 0.12), Qt.AlignCenter, "01")
    p.end()
    return pm


def install_icons():
    base = os.path.expanduser("~/.local/share/icons/hicolor")
    for size in ICON_SIZES:
        d = os.path.join(base, f"{size}x{size}", "apps")
        os.makedirs(d, exist_ok=True)
        make_icon(size, QColor(*DEFAULT_RGB[:3])).save(os.path.join(d, "gamerhud.png"))


# ------------------------------------------- wallpaper engine (print / pausa)
# Modo "still" (padrão): troca cada cena por um print dela mesma, o plugin do
# Wallpaper Engine é descarregado e solta a VRAM; ao fechar, volta pra cena.
# Modo "pause" (reserva, ou settings.json "wallpaper": "pause"): só pausa as cenas.
# A volta não depende do wallpaper_state.json: toda tela em `org.kde.image` com
# imagem em ~/.cache/gamerhud/stills/ volta pro plugin do WE (as configs dele
# ficam intactas no appletsrc). O estado só é apagado se o Plasma confirmar.

def wallpaper_disabled():
    """Testes e ferramentas offscreen nunca tocam no papel de parede real."""
    return (os.environ.get("GAMERHUD_NO_WALLPAPER", "") not in ("", "0")
            or os.environ.get("QT_QPA_PLATFORM", "") == "offscreen")


def plasma_eval(script):
    if wallpaper_disabled():
        return None
    iface = QDBusInterface("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell",
                           QDBusConnection.sessionBus())
    if not iface.isValid():
        return None
    args = iface.call("evaluateScript", script).arguments()
    return args[0] if args else None


def kwin_script(js, name):
    """Roda um script curto no KWin (carrega, executa, descarrega)."""
    if wallpaper_disabled():
        return False
    bus = QDBusConnection.sessionBus()
    scripting = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", bus)
    if not scripting.isValid():
        return False
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{name}.js")
    with open(path, "w") as f:
        f.write(js)
    scripting.call("unloadScript", name)
    args = scripting.call("loadScript", path, name).arguments()
    if not args:
        return False
    QDBusInterface("org.kde.KWin", f"/Scripting/Script{args[0]}", "org.kde.kwin.Script", bus).call("run")
    time.sleep(0.1)
    scripting.call("unloadScript", name)
    return True


# opacidade/1000 deixa a janela invisível e guarda o valor original nela mesma
HIDE_JS = ("workspace.windowList().forEach(function(w){"
           "if(!w.desktopWindow&&w.opacity>0.002)w.opacity=w.opacity/1000;});")
SHOW_JS = ("workspace.windowList().forEach(function(w){"
           "if(!w.desktopWindow&&w.opacity>0&&w.opacity<=0.0011)w.opacity=w.opacity*1000;});")


def stills_dir():
    return os.path.join(CACHE, "stills")


def _read_state():
    try:
        with open(WP_STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    if "mode" not in state:   # formato antigo: {id: [PauseMode, filtro]}
        state = {"mode": "pause", "desktops": state}
    return state


def _write_state(state):
    """Atômico (tmp + rename) e nunca por cima de um estado existente: o original é o 1º."""
    if _read_state() is not None:
        return False
    os.makedirs(CACHE, exist_ok=True)
    tmp = f"{WP_STATE}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, WP_STATE)
    return True


def _desktops():
    """{id: (plugin, cena, x, y, w, h)} de cada área de trabalho do Plasma."""
    out = plasma_eval(
        f"var o=[];desktops().forEach(function(d){{var g=screenGeometry(d.screen);"
        f"d.currentConfigGroup=['Wallpaper','{WE_PLUGIN}','General'];"
        f"o.push([d.id,d.wallpaperPlugin,d.readConfig('WallpaperWorkShopId')||'',g.x,g.y,g.width,g.height].join(','));}});"
        f"print(o.join(';'));")
    res = {}
    for item in filter(None, (out or "").split(";")):
        did, plugin, scene, *geo = item.split(",")
        res[did] = (plugin, scene, *(int(float(v)) for v in geo))
    return res


def _apply_wp(values):
    """values: {desktop_id: (PauseMode, PauseFilterByScreen)}. True se o Plasma confirmou."""
    js = json.dumps({str(k): [int(m), bool(f)] for k, (m, f) in values.items()})
    out = plasma_eval(
        f"var s={js};desktops().forEach(function(d){{var v=s[String(d.id)];"
        f"if(!v||d.wallpaperPlugin!='{WE_PLUGIN}')return;"
        f"d.currentConfigGroup=['Wallpaper','{WE_PLUGIN}','General'];"
        f"d.writeConfig('PauseMode',v[0]);d.writeConfig('PauseFilterByScreen',v[1]);}});"
        f"print('ok');")
    return bool(out) and "ok" in str(out)


def _unstill():
    """Toda tela em org.kde.image com foto do cache volta pro WE. None se o Plasma não respondeu."""
    out = plasma_eval(
        f"var st={json.dumps(stills_dir())},n=0;desktops().forEach(function(d){{"
        f"if(d.wallpaperPlugin!='org.kde.image')return;"
        f"d.currentConfigGroup=['Wallpaper','org.kde.image','General'];"
        f"if(String(d.readConfig('Image')||'').indexOf(st)<0)return;"
        f"d.wallpaperPlugin='{WE_PLUGIN}';n++;}});print('ok '+n);")
    m = re.search(r"ok (\d+)", str(out or ""))
    return int(m.group(1)) if m else None


def still_wallpapers():
    """Troca as cenas por um print do wallpaper (sem janelas) e descarrega o plugin.
    O print fica em cache por cena: só captura de novo se a cena mudar."""
    state = _read_state()
    if state and state["mode"] == "still":
        return True            # sobrou de uma sessão que caiu: os prints já estão aplicados
    # sobras (estado de pausa, ou prints presos sem estado) voltam antes: senão o "original" vira a foto
    if not restore_wallpapers():
        return False
    desks = _desktops()
    we = {k: v[1:] for k, v in desks.items() if v[0] == WE_PLUGIN}
    if not we:
        return False
    os.makedirs(stills_dir(), exist_ok=True)
    paths = {did: os.path.join(stills_dir(), f"{scene or did}_{w}x{h}.jpg")
             for did, (scene, x, y, w, h) in we.items()}
    if not all(os.path.exists(p) for p in paths.values()):
        full = os.path.join(CACHE, "capture.png")
        try:
            if not kwin_script(HIDE_JS, "gamerhud_hide"):
                return False
            time.sleep(0.15)
            subprocess.run(["spectacle", "-b", "-n", "-f", "-o", full], timeout=15, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            return False
        finally:
            kwin_script(SHOW_JS, "gamerhud_show")
        img = QImage(full)
        if img.isNull():
            return False
        ox = min(v[2] for v in desks.values())
        oy = min(v[3] for v in desks.values())
        k = img.width() / (max(v[2] + v[4] for v in desks.values()) - ox)   # escala do print
        for did, (scene, x, y, w, h) in we.items():
            img.copy(round((x - ox) * k), round((y - oy) * k), round(w * k), round(h * k)) \
               .save(paths[did], "JPG", 95)
        os.remove(full)
    _write_state({"mode": "still", "desktops": list(paths)})
    plasma_eval(
        f"var s={json.dumps(paths)};desktops().forEach(function(d){{var p=s[String(d.id)];if(!p)return;"
        f"d.wallpaperPlugin='org.kde.image';d.currentConfigGroup=['Wallpaper','org.kde.image','General'];"
        f"d.writeConfig('Image','file://'+p);d.writeConfig('FillMode',2);}});")
    return True


def pause_wallpapers():
    """PauseMode=FullScreen sem filtro de tela: a tela cheia do HUD pausa todos."""
    state = _read_state()
    if not state:
        restore_wallpapers()   # prints presos sem estado voltam pro WE antes de ler o "original"
        out = plasma_eval(
            f"var o=[];desktops().forEach(function(d){{if(d.wallpaperPlugin!='{WE_PLUGIN}')return;"
            f"d.currentConfigGroup=['Wallpaper','{WE_PLUGIN}','General'];"
            f"o.push(d.id+'='+d.readConfig('PauseMode')+','+d.readConfig('PauseFilterByScreen'));}});"
            f"print(o.join(';'));")
        saved = {}
        for item in filter(None, (out or "").split(";")):
            did, vals = item.split("=", 1)
            mode, flt = vals.split(",", 1)
            saved[did] = [int(mode or 0), flt.strip().lower() == "true"]
        if not saved:
            return
        _write_state({"mode": "pause", "desktops": saved})
        state = _read_state()
    if state and state["mode"] == "pause":
        _apply_wp({k: (5, False) for k in state["desktops"]})


def prepare_wallpapers():
    if wallpaper_disabled():
        return
    mode = load_settings().get("wallpaper", "still")
    if mode == "off":
        return
    if mode == "still" and still_wallpapers():
        return
    pause_wallpapers()


def restore_wallpapers():
    """Sempre tira os prints do cache (com ou sem estado) e, no modo pausa, devolve
    PauseMode/filtro originais. True se ficou tudo restaurado (estado apagado)."""
    kwin_script(SHOW_JS, "gamerhud_show")   # garantia: nenhuma janela fica invisível
    state = _read_state()
    ok = _unstill() is not None
    if state and state["mode"] == "pause":
        ok = _apply_wp({k: tuple(v) for k, v in state["desktops"].items()}) and ok
    if not ok:
        return state is None   # Plasma fora do ar (logout, offscreen): o estado fica pra próxima
    try:
        os.remove(WP_STATE)
    except OSError:
        pass
    return True


class WallpaperGuard:
    """Restauração única e garantida: SIGTERM/SIGINT/SIGHUP, aboutToQuit, closeEvent e atexit."""

    def __init__(self, app=None, window=None):
        self.app, self.window, self.done, self.in_loop = app, window, False, False

    def finish(self):
        if self.done:
            return
        self.done = True
        try:
            if self.window is not None:
                self.window.hide()   # some da tela na hora; a restauração vem depois
                if self.app is not None:
                    self.app.processEvents()
        except RuntimeError:         # janela já destruída (atexit): restaura assim mesmo
            pass
        restore_wallpapers()

    def on_signal(self, *_):
        self.finish()
        if self.in_loop:
            self.app.quit()
        else:
            raise SystemExit(0)   # sinal antes do app.exec() (ex.: no meio do prepare): sai já

    def install(self):
        import atexit
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, self.on_signal)
        if self.app is not None:
            self.app.aboutToQuit.connect(self.finish)
            QTimer.singleShot(0, self._loop_started)
        atexit.register(self.finish)

    def _loop_started(self):
        self.in_loop = True


def single_instance():
    """Trava do HUD: dois HUDs não disputam o mesmo estado do wallpaper. None = já tem um."""
    import fcntl
    os.makedirs(CACHE, exist_ok=True)
    lock = open(os.path.join(CACHE, "hud.lock"), "w")
    for _ in range(20):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock
        except OSError:
            time.sleep(0.05)
    lock.close()
    return None


# ------------------------------------------------------------ sistema / dados

def system_info(gpu_dev):
    cpu_model, cores, threads = "", 0, 0
    for line in read("/proc/cpuinfo", "").splitlines():
        key, _, val = line.partition(":")
        key = key.strip()
        if key == "model name" and not cpu_model:
            cpu_model = val
        elif key == "cpu cores" and not cores:
            cores = int(val)
        elif key == "siblings" and not threads:
            threads = int(val)
    cpu = re.sub(r"\((R|TM)\)|\d+(st|nd|rd|th) Gen|CPU|Processor|@.*$|\d+-Core", "", cpu_model)
    info = [("CPU", f"{' '.join(cpu.split())} · {cores}C/{threads}T")]

    gpu = "--"
    if gpu_dev:
        out = sh(["lspci", "-s", os.path.basename(os.path.realpath(gpu_dev))])
        names = re.findall(r"\[([^\]]+)\]", out)
        vendor = ("AMD" if re.search(r"AMD|ATI", out) else "NVIDIA" if "NVIDIA" in out
                  else "INTEL" if "Intel" in out else "")
        vram = int(read(f"{gpu_dev}/mem_info_vram_total", "0")) / 2**30
        gpu = f"{vendor} {names[-1] if names else 'GPU'}" + (f" · {vram:.0f} GB" if vram else "")
    info.append(("GPU", gpu))

    vendor = (read("/sys/class/dmi/id/board_vendor", "") or "").split(" ")[0]
    info.append(("M/B", f"{vendor} {read('/sys/class/dmi/id/board_name', '')}".strip()))
    mem = int(read("/proc/meminfo", "MemTotal: 0").split()[1]) / 2**20
    info.append(("RAM", f"{math.ceil(mem)} GB"))
    pretty = "Linux"
    for line in read("/etc/os-release", "").splitlines():
        if line.startswith("PRETTY_NAME="):
            pretty = re.sub(r"\s*\(.*\)", "", line.split("=", 1)[1].strip('"'))
    info.append(("OS", f"{pretty} · {os.uname().release.split('-')[0]}"))
    mesa = sh(["rpm", "-q", "--qf", "%{VERSION}\n", "mesa-dri-drivers"]).split("\n")[0]
    if mesa and " " not in mesa:
        info.append(("MESA", mesa))
    return [(k, v.upper()) for k, v in info]


def controllers():
    """Controles físicos (evdev com handler jsN), com bateria quando disponível."""
    batteries = {}
    for d in glob.glob("/sys/class/power_supply/*"):
        if read(f"{d}/scope") == "Device":
            batteries[os.path.basename(d).lower()] = (read(f"{d}/capacity"), read(f"{d}/status"))
    out, seen = [], set()
    for block in read("/proc/bus/input/devices", "").split("\n\n"):
        name = re.search(r'N: Name="(.*)"', block)
        handlers = re.search(r"H: Handlers=(.*)", block)
        sysfs = re.search(r"S: Sysfs=(.*)", block)
        uniq = re.search(r"U: Uniq=(.*)", block)
        bus = re.search(r"I: Bus=(\w+)", block)
        if not (name and handlers and re.search(r"\bjs\d+", handlers.group(1))):
            continue
        if sysfs and sysfs.group(1).startswith("/devices/virtual/input"):
            continue   # pads virtuais do uinput (Steam Input etc.); Bluetooth fica em .../misc/uhid
        raw = name.group(1)
        if re.search(r"Motion Sensors|Touchpad|IMU", raw):
            continue
        mac = (uniq.group(1) if uniq else "").lower()
        if (raw, mac) in seen:
            continue
        seen.add((raw, mac))
        low = raw.lower()
        if "dualsense" in low:
            label = "DUALSENSE EDGE" if "edge" in low else "DUALSENSE"
        elif "sony" in low or "dualshock" in low:
            label = "DUALSHOCK 4"
        elif "xbox" in low or "x-box" in low:
            label = "XBOX CONTROLLER"
        elif "pro controller" in low:
            label = "SWITCH PRO"
        else:
            label = raw.upper()
        bat, charging = None, False
        if mac:
            for key, (cap, st) in batteries.items():
                if mac in key:
                    bat, charging = cap, st in ("Charging", "Full")
        conn = {"0005": "BT", "0003": "USB"}.get(bus.group(1) if bus else "", "")
        out.append((label, bat, conn, charging))
    return out


def readb(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


STEAM_ROOT = os.path.expanduser("~/.local/share/Steam")
_steam_names = {}


def steam_game_name(appid):
    if appid in _steam_names:
        return _steam_names[appid]
    libs = [os.path.join(STEAM_ROOT, "steamapps")]
    vdf = read(os.path.join(STEAM_ROOT, "steamapps", "libraryfolders.vdf"), "")
    libs += [os.path.join(p, "steamapps") for p in re.findall(r'"path"\s+"([^"]+)"', vdf)]
    name = None
    for lib in libs:
        m = re.search(r'"name"\s+"([^"]+)"', read(os.path.join(lib, f"appmanifest_{appid}.acf"), ""))
        if m:
            name = m.group(1).upper()
            break
    _steam_names[appid] = name or f"APP {appid}"
    return _steam_names[appid]


def steam_game():
    """Nome do jogo da Steam em execução (processo `reaper SteamLaunch AppId=N`), ou None."""
    for e in os.scandir("/proc"):
        if not e.name.isdigit():
            continue
        raw = readb(f"/proc/{e.name}/cmdline")
        if not raw or b"SteamLaunch" not in raw:
            continue
        args = raw.split(b"\0")
        if b"SteamLaunch" not in args:
            continue
        for a in args:
            m = re.fullmatch(rb"AppId=(\d+)", a)
            if m and m.group(1) != b"228980":
                return steam_game_name(m.group(1).decode())
    return None


class Sensors:
    def __init__(self):
        self.cpu_hw = hwmon("coretemp") or hwmon("k10temp")
        self.gpu_hw = hwmon("amdgpu")
        paths = glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")
        self.gpu_dev = os.path.dirname(paths[0]) if paths else None
        self.prev_cpu = None
        self.data = {}

    def _cpu_usage(self):
        vals = list(map(int, read("/proc/stat").splitlines()[0].split()[1:]))
        idle, total = vals[3] + vals[4], sum(vals)
        usage = 0.0
        if self.prev_cpu:
            di, dt = idle - self.prev_cpu[0], total - self.prev_cpu[1]
            usage = 100.0 * (1 - di / dt) if dt else 0.0
        self.prev_cpu = (idle, total)
        return max(0.0, min(100.0, usage))

    def _hw(self, base, f, div):
        v = read(f"{base}/{f}") if base else None
        return int(v) / div if v else None

    def poll(self):
        d = {"cpu": self._cpu_usage(),
             "cpu_temp": self._hw(self.cpu_hw, "temp1_input", 1000),
             "gpu_temp": self._hw(self.gpu_hw, "temp2_input", 1000),
             "gpu_w": self._hw(self.gpu_hw, "power1_average", 1e6)}
        if self.gpu_dev:
            d["gpu"] = float(read(f"{self.gpu_dev}/gpu_busy_percent", "0"))
            used = int(read(f"{self.gpu_dev}/mem_info_vram_used", "0"))
            total = int(read(f"{self.gpu_dev}/mem_info_vram_total", "1"))
            d["vram"] = 100.0 * used / total
            d["vram_txt"] = f"{used / 2**30:.1f}/{total / 2**30:.0f}G"
        else:
            d["gpu"], d["vram"], d["vram_txt"] = 0.0, 0.0, "--"
        mem = {}
        for line in read("/proc/meminfo").splitlines():
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0])
        used = mem["MemTotal"] - mem["MemAvailable"]
        d["ram"] = 100.0 * used / mem["MemTotal"]
        d["ram_txt"] = f"{used / 2**20:.1f}/{math.ceil(mem['MemTotal'] / 2**20)}G"
        self.data = d


class FpsSource:
    """Lê a última linha do CSV mais recente que o MangoHud está escrevendo."""

    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.file = None
        self.fps = self.frametime = self.name = None
        self.recent = deque(maxlen=120)  # últimos 60 s
        self.last_cleanup = 0.0

    def _newest(self):
        best = None
        try:
            for e in os.scandir(self.folder):
                if e.name.endswith(".csv"):
                    m = e.stat().st_mtime
                    if best is None or m > best[1]:
                        best = (e.path, m)
        except OSError:
            pass
        return best

    def _last_row(self, path):
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 1024))
                lines = f.read().decode(errors="ignore").splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            cols = line.split(",")
            try:
                return float(cols[0]), float(cols[1])
            except (ValueError, IndexError):
                continue
        return None

    def _cleanup(self):
        now = time.time()
        if now - self.last_cleanup < 60:
            return
        self.last_cleanup = now
        for p in glob.glob(os.path.join(self.folder, "*.csv")):
            try:
                if now - os.path.getmtime(p) > 3600:
                    os.remove(p)
            except OSError:
                pass

    def poll(self):
        self._cleanup()
        newest = self._newest()
        row = None
        if newest and time.time() - newest[1] < 3:
            row = self._last_row(newest[0])
        if not row:
            self.file = self.fps = self.frametime = self.name = None
            self.recent.clear()
            return
        if newest[0] != self.file:
            self.file = newest[0]
            self.recent.clear()
            base = os.path.basename(self.file)
            base = re.sub(r"_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.csv$", "", base)
            base = re.sub(r"\.(exe|x86_64|x86|bin)$", "", base, flags=re.I)
            self.name = re.sub(r"[_\-]+", " ", base).strip().upper() or "UNKNOWN"
        self.fps, self.frametime = row
        self.recent.append(self.fps)


WINE_SYS = {"services.exe", "winedevice.exe", "plugplay.exe", "svchost.exe", "explorer.exe",
            "rpcss.exe", "tabtip.exe", "conhost.exe", "start.exe", "wineboot.exe",
            "winemenubuilder.exe", "rundll32.exe", "wineserver", "wine64-preloader",
            "wine-preloader", "wine", "wine64"}
INTERPRETERS = ("python", "bash", "sh", "node", "perl", "ruby", "java")


class ProcStats:
    """Consumo por aplicativo. Só roda com o painel de detalhes aberto."""

    def __init__(self):
        self.own = os.getpid()
        self.ncpu = os.cpu_count() or 1
        self.page_kb = os.sysconf("SC_PAGE_SIZE") // 1024
        self.names = {}
        self.reset()

    def reset(self):
        self.prev_cpu, self.prev_total = {}, None
        self.prev_gpu, self.prev_t = {}, None

    def app_name(self, pid, comm):
        if pid == self.own:
            return "MAGI GAMER"
        raw = readb(f"/proc/{pid}/cmdline")
        if not raw:
            return "KERNEL"
        args = [a.decode(errors="ignore") for a in raw.split(b"\0") if a]
        if any(a.endswith("gamerhud.py") for a in args[:2]):
            return "MAGI GAMER"
        base = re.split(r"[\\/]", args[0])[-1] or comm
        low = base.lower()
        if low.startswith(INTERPRETERS):
            script = next((a for a in args[1:] if not a.startswith("-")), None)
            if script:
                base = re.split(r"[\\/]", script)[-1]
                low = base.lower()
        if "steam" in low or low.startswith(("srt-", "pv-", "pressure-vessel")) \
                or low in ("reaper", "fossilize_replay", "gameoverlayui"):
            return "STEAM"
        if low in WINE_SYS:
            return "PROTON / WINE"
        if low.startswith("kwin"):
            return "KWIN · DESKTOP"
        if low == "plasmashell":
            return "PLASMA SHELL"
        base = re.sub(r"\.exe$", "", base, flags=re.I)
        return base.upper()[:40]

    @staticmethod
    def _kib(val):
        num, _, unit = val.strip().partition(" ")
        mult = {"KiB": 1, "MiB": 1024, "GiB": 1024 ** 2}.get(unit.strip(), 1 / 1024)
        return float(num) * mult

    def poll(self, kind):
        """Top 8 de (nome, valor principal, texto extra) para 'cpu', 'gpu' ou 'mem'."""
        total = sum(map(int, read("/proc/stat").splitlines()[0].split()[1:]))
        now = time.monotonic_ns()
        acc, extra = {}, {}
        cpu_now, gpu_now, seen_clients = {}, {}, set()
        alive = set()
        for e in os.scandir("/proc"):
            if not e.name.isdigit():
                continue
            pid = int(e.name)
            raw = readb(f"/proc/{pid}/stat")
            if not raw:
                continue
            alive.add(pid)
            r = raw.rfind(b")")
            comm = raw[raw.find(b"(") + 1:r].decode(errors="ignore")
            name = self.names.get(pid)
            if name is None:
                name = self.names[pid] = self.app_name(pid, comm)
            if kind == "cpu":
                f = raw[r + 2:].split()
                jiff = int(f[11]) + int(f[12])
                cpu_now[pid] = jiff
                if pid in self.prev_cpu:
                    acc[name] = acc.get(name, 0) + jiff - self.prev_cpu[pid]
            elif kind == "mem":
                kb = None
                roll = readb(f"/proc/{pid}/smaps_rollup")
                if roll:
                    m = re.search(rb"^Pss:\s+(\d+)", roll, re.M)
                    kb = int(m.group(1)) if m else None
                if kb is None:
                    statm = readb(f"/proc/{pid}/statm")
                    kb = int(statm.split()[1]) * self.page_kb if statm else 0
                acc[name] = acc.get(name, 0) + kb
            if kind in ("gpu", "mem"):
                try:
                    fds = os.listdir(f"/proc/{pid}/fd")
                except OSError:
                    continue
                for fd in fds:
                    try:
                        if not os.readlink(f"/proc/{pid}/fd/{fd}").startswith("/dev/dri/"):
                            continue
                    except OSError:
                        continue
                    info = readb(f"/proc/{pid}/fdinfo/{fd}")
                    if not info:
                        continue
                    fields = dict(line.split(":", 1) for line in info.decode(errors="ignore").splitlines()
                                  if line.startswith("drm-") and ":" in line)
                    cid = fields.get("drm-client-id", "").strip()
                    if not cid or cid in seen_clients:
                        continue
                    seen_clients.add(cid)
                    vram = fields.get("drm-memory-vram") or fields.get("drm-resident-vram")
                    if vram:
                        extra[name] = extra.get(name, 0) + self._kib(vram)
                    if kind == "gpu":
                        ns = sum(int(fields[k].split()[0]) for k in ("drm-engine-gfx", "drm-engine-compute")
                                 if k in fields)
                        gpu_now[cid] = (ns, name)
                        if cid in self.prev_gpu:
                            acc[name] = acc.get(name, 0) + ns - self.prev_gpu[cid][0]
        self.names = {p: n for p, n in self.names.items() if p in alive}

        rows = []
        if kind == "cpu":
            ready = self.prev_total is not None and total > self.prev_total
            if ready:
                dt = total - self.prev_total
                for n, v in acc.items():
                    pct = 100.0 * v / dt
                    rows.append((n, pct, f"{pct * self.ncpu:.0f}% DE 1 NÚCLEO"))
            self.prev_cpu, self.prev_total = cpu_now, total
            if not ready:
                return None
        elif kind == "gpu":
            ready = self.prev_t is not None
            if ready:
                dt = max(1, now - self.prev_t)
                for n in set(acc) | set(extra):
                    pct = min(100.0, 100.0 * acc.get(n, 0) / dt)
                    rows.append((n, pct, f"VRAM {extra.get(n, 0) / 1024:.0f} MB"))
            self.prev_gpu, self.prev_t = gpu_now, now
            if not ready:
                return None
        else:
            for n, kb in acc.items():
                vr = extra.get(n, 0)
                rows.append((n, kb / 2**20, f"VRAM {vr / 1024:.0f} MB" if vr >= 1024 else ""))
        rows.sort(key=lambda x: x[1], reverse=True)
        return rows[:8]


KANJI_DIGITS = "零壱弐参四伍六七八九"
EN_ONES = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN",
           "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN",
           "EIGHTEEN", "NINETEEN"]
EN_TENS = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY"]
EN_DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
EN_MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
             "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]


def kanji_num(n):
    """19 -> 拾九, 37 -> 参拾七 (numerais formais, como nos títulos do Evangelion)."""
    if n == 0:
        return "零"
    tens, ones = divmod(n, 10)
    return ((KANJI_DIGITS[tens] if tens > 1 else "") + ("拾" if tens else "")
            + (KANJI_DIGITS[ones] if ones else ""))


def en_num(n):
    if n < 20:
        return EN_ONES[n]
    tens, ones = divmod(n, 10)
    return EN_TENS[tens] + (f"-{EN_ONES[ones]}" if ones else "")


def en_time(h, m):
    return f"{en_num(h)} {'HUNDRED' if m == 0 else ('OH-' + EN_ONES[m]) if m < 10 else en_num(m)}"


# ---------------------------------------------------------------------- HUD

class HUD(QWidget):
    # view: 'full' | 'idle' (Meta+M) | 'learning'. Propriedade: toda troca (direta, cortina,
    # settings.json) mostra/esconde o campo de texto da tela learning e troca a flag de foco (LM1.6).
    @property
    def view(self):
        return self._view

    @view.setter
    def view(self, v):
        self._view = v
        if getattr(self, "kon_open", False) and v != "full":
            self.konsole_collapse()   # o Konsole expandido só existe no painel completo
        if getattr(self, "lm_entry", None) is not None:
            self.learning_entry_sync()

    def __init__(self, fonts, bridge=None):
        super().__init__()
        self.fonts = fonts
        self.sensors = Sensors()
        self.fpsrc = FpsSource(FPS_DIR)
        self.spec = system_info(self.sensors.gpu_dev)
        self.pads = controllers()
        self.steam_game = steam_game()
        self.hist = {k: deque([0.0] * HISTORY, maxlen=HISTORY) for k in ("fps", "gpu", "cpu")}
        self.bars = {}        # valor mostrado (animado) de cada barra
        self.fps_scale = 60.0
        self.last_sample = time.monotonic()
        self.sample_count = 0
        self.rgb_cur = list(DEFAULT_RGB)
        self.rgb_tgt = list(DEFAULT_RGB)
        self.rgb_online = False
        self.rgb_sync = True
        self.settings_mtime = -1.0
        cfg = load_settings()
        self.view = cfg.get("view", "full")   # 'full' | 'idle' (Meta+M) | 'learning' (LM1.5, só wired)
        self.lm_return = None   # view guardada ao entrar no Learning Mode (LM1.7); Meta+M muda só ela
        self.ui = "eva" if cfg.get("ui", UI_DEFAULT) == "eva" else "wired"
        self.wired = WiredUI() if self.ui == "wired" else None   # tema wired (U4)
        self.claude_stats = None
        self.attach_claude()
        # tela de ociosidade: média de FPS que só muda a cada IDLE_AVG_S, e tempo de sessão
        self.idle_avg = None
        self.idle_acc = []
        self.idle_avg_t = 0.0
        self.game_since = None
        self.idle_key = None
        self.trans = None     # cortina em andamento: {'old', 'new', 't0'}
        self.procs = ProcStats()
        self.detail = None            # 'cpu' | 'gpu' | 'mem' com o painel de detalhes aberto
        self.detail_rows = None
        self.detail_until = 0.0
        self.theme_frame = 0
        self.bg = self.frame = self.plot_pm = None
        # Konsole // Claude Code: sessão sob demanda (1º clique no card), expandido trocado com o cam 01
        self.kon = None
        self.kon_open = False
        self.kon_notifier = None
        self.kon_full = False     # repintar o expandido inteiro (e não só as linhas sujas)
        self.kon_last = 0.0
        self.kon_timer = QTimer(self, timeout=self.konsole_flush)
        self.kon_timer.setSingleShot(True)
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.konsole_stop)
        self.setWindowTitle("MAGI Gamer")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.data_timer = QTimer(self, timeout=self.sample)
        self.anim_timer = QTimer(self, timeout=self.animate)
        self.anim_timer.setTimerType(Qt.PreciseTimer)
        # wired: um batimento por segundo de relógio (dados + regiões sujas), sem quadros de animação
        self.wired_timer = QTimer(self, timeout=self.wired_beat)
        self.wired_timer.setSingleShot(True)
        self.wired_timer.setTimerType(Qt.PreciseTimer)
        self.poll_rgb(instant=True)
        self.sample()
        self.start_timers()
        self.rgb_timer = QTimer(self, timeout=self.poll_rgb)
        self.rgb_timer.start(RGB_MS)
        self.init_magui(bridge)

    # ---------- tema: wired (R23) ou eva (R23.9) ----------
    def start_timers(self):
        if self.wired:
            self.data_timer.stop()
            self.anim_timer.stop()
            self.wired_beat(sample=False)
        else:
            self.wired_timer.stop()
            self.data_timer.start(SAMPLE_MS)
            self.anim_timer.start(ANIM_MS)

    def apply_ui(self, ui):
        """Troca de tema em execução (settings.json "ui")."""
        ui = "eva" if ui == "eva" else "wired"
        if ui == self.ui:
            return
        self.ui = ui
        self.trans = None
        if ui == "wired":
            self.wired = self.wired_keep if getattr(self, "wired_keep", None) else WiredUI()
            self.attach_claude()
            self.frame = None
            self.wired.set_state(self.face.state if self.face.state in self.FACE_STATES else "sleeping")
            self.wired.set_mood(self.magui_mood)
            self.wired.learning.info = self.learning_model
        else:
            self.wired_keep, self.wired = self.wired, None
            self.bg = None
            self.render_caches()
        self.start_timers()
        self.learning_entry_sync()
        self.update()
        self.face_tick()

    FACE_STATES = ("sleeping", "listening", "thinking", "speaking", "happy", "confused", "alert")

    def wired_beat(self, sample=True):
        """1 Hz alinhado ao segundo do relógio: coleta, dados novos e redesenho só do que mudou."""
        if sample:
            self.sample()
        if self.wired:
            self.wired_timer.start(1000 - int(time.time() * 1000) % 1000 + 3)

    def attach_claude(self):
        """Painel "Claude Code": coleta numa thread (MAGI_NO_CLAUDE_STATS=1 desliga, nos testes)."""
        if self.wired is None or os.environ.get("MAGI_NO_CLAUDE_STATS") == "1":
            return
        if self.claude_stats is None:
            self.claude_stats = ClaudeStats()
            self.claude_stats.start()
        self.wired.claude = self.claude_stats

    def wired_poll(self):
        d = self.sensors.data
        self.wired.poll(d, self.fpsrc.fps, self.steam_game or self.fpsrc.name)
        self.wired_refresh()

    def wired_refresh(self, detail=False):
        """Remonta o Snapshot e invalida só as regiões que mudaram (dirty_regions)."""
        w = self.wired
        if not w:
            return
        snap = w.build(self.sensors.data, spec=self.spec, pads=self.pads,
                       gaming=(self.steam_game or self.fpsrc.name) is not None)
        if getattr(self, "turn_phase", None) is not None:   # chip pela fase do turno (estável)
            snap.chip = self.turn_phase.chip(time.monotonic())
        if not (self.isVisible() and self.width() > 1) or self.trans:
            return
        for r in w.screen(self.view).dirty_regions(snap, size=self.size()):
            self.update(r)
        if detail and self.detail and self.view not in ("idle", "learning"):
            self.update(w.detail_rect(self.size()))

    def paint_wired(self, p, region):
        w, size = self.wired, self.size()
        scr = w.screen(self.view)
        kon = self.konsole_dev(kview.EXPANDED_RECT) if self.konsole_shown() else None
        if w.konsole_swap(kon is not None):   # transição etc.: câmera de volta / no slot do card
            self.konsole_swap_update()
        for r in region:   # retângulos separados: relógio + rodapé não viram a tela inteira
            if kon is None or not kon.contains(r):   # dentro do Konsole opaco: só ele
                scr.paint(p, size, w.snap, region=r)
                if self.detail and self.view not in ("idle", "learning"):
                    w.paint_detail(p, size, r, self.detail, self.detail_rows)
            if kon is not None and kon.intersects(r):
                s = self.konsole_scale()
                p.save()
                p.setClipRect(r)
                p.scale(s, s)
                kview.paint_expanded(p, kview.EXPANDED_RECT, s)
                p.restore()

    # ---------- Magui: rosto e ponte com o núcleo (tarefa 1.16) ----------
    # O rosto não entra no cache (frame): o paintEvent o desenha por cima, e só a região dele
    # é invalidada, no ritmo que Face.tick pede (até 30 fps acordada, 1 quadro a cada 4 s
    # dormindo). Timer de disparo único reprogramado pelo prazo do tick: dormindo, o HUD não
    # acorda à toa. O HUD só existe no monitor secundário, então o rosto nunca vai pro do jogo.
    DETAIL_FROM_BRIDGE = {"cpu": "cpu", "gpu": "gpu", "memory": "mem"}

    def init_magui(self, bridge):
        self.face = Face("sleeping")
        self.magui_mood = None        # termômetro de humor (4.4): desenhado pelo tema wired
        self.magui_vote = None        # TODO: votação dos MAGI (veredito, rótulo) no painel
        self.magui_cards = deque(maxlen=8)   # TODO: cards de notícia/links no HUD
        self.detail_return = None     # view a restaurar quando o detalhe pedido pela voz fechar
        self.face_timer = QTimer(self, timeout=self.face_tick)
        self.face_timer.setSingleShot(True)
        self.face_timer.setTimerType(Qt.PreciseTimer)
        # legenda que se escreve conforme ela fala: timer próprio, só enquanto revela
        self.speech_caption = SpeechCaption()
        self.turn_phase = TurnPhase()   # fase do turno: chip estável e "falando" da legenda
        self.caption_timer = QTimer(self, timeout=self.caption_tick)
        self.caption_timer.setSingleShot(True)
        self.bridge = bridge if bridge is not None else hud_bridge.HudBridge(parent=self)
        b = self.bridge
        # Learning Mode (LM1.6): estado da tela alimentado por todo lm_* (o bridge entrega)
        self.learning_model = LearningModel(connected=False)
        if self.wired:
            self.wired.learning.info = self.learning_model
        b.learning_model = self.learning_model
        b.learning.connect(self.on_bridge_learning)
        self.lm_entry = None
        self.make_learning_entry()
        b.stateChanged.connect(self.on_face_state)
        b.mouth.connect(self.on_face_mouth)
        b.subtitle.connect(self.on_face_subtitle)
        b.speech.connect(self.on_face_speech)
        b.detail.connect(self.on_bridge_detail)
        b.mood.connect(self.on_bridge_mood)
        b.vote.connect(self.on_bridge_vote)
        b.card.connect(self.on_bridge_card)
        b.connectedChanged.connect(self.on_bridge_connected)
        b.start()
        self.face_tick()

    def r_face(self):
        if self.view == "idle":
            return self.R(1400, 380, 1000, 680)   # metade direita, com legenda embaixo
        return self.R(1560, 62, 190, 116)         # cabeçalho: entre o título e o relógio

    def face_tick(self):
        now = time.monotonic()
        if self.wired:
            screen = self.wired.screen(self.view)
            rect, deadline = screen.mascot_tick(now, self.size())
            rects, scene_deadline = screen.scene_tick(now, self.size())  # cenário animado
            if self.detail and self.view not in ("idle", "learning"):
                rects = []  # o painel de detalhes cobre o "cam 01": não redesenha por baixo
            if not self.trans and self.isVisible():
                for r in ([rect] if rect is not None else []) + rects:
                    self.update(r)
            deadline = min(deadline, scene_deadline)
            self.face_timer.start(max(1, math.ceil((deadline - now) * 1000)))
            return
        redraw, deadline = self.face.tick(now)
        if redraw and self.frame is not None and not self.trans:
            self.update(self.r_face().toAlignedRect())
        self.face_timer.start(max(1, math.ceil((deadline - now) * 1000)))

    def on_face_state(self, expr):
        try:
            self.face.set_state(expr)
        except ValueError:
            return
        now = time.monotonic()
        self.turn_phase.on_state(expr, now)
        # happy/confused/alert durante a resposta também são fala (o núcleo manda a expressão)
        self.speech_caption.on_state("speaking" if self.turn_phase.speaking else expr, now)
        self.learning_model.on_state(expr, now, speaking=self.turn_phase.speaking)
        self.caption_tick()
        if self.wired:
            self.wired.set_state(expr)
            self.wired_refresh()
        self.face_tick()

    def on_face_mouth(self, level):
        self.face.set_mouth_level(level)
        self.turn_phase.on_mouth(level, time.monotonic())
        lm_input = self.learning_model.on_mouth(level, time.monotonic())
        if self.speech_caption.on_mouth(time.monotonic()):   # o áudio começou: a estimativa parte daqui
            self.caption_tick()
        elif lm_input and self.view == "learning":
            self.learning_refresh()   # onda de áudio do grupo input
        if self.wired:
            self.wired.set_mouth(level)
        self.face_tick()

    def on_face_subtitle(self, text, full=""):
        # fora da fala fica pendente: se a fala vem logo, a legenda nasce vazia (sem o "pisca")
        self.speech_caption.on_subtitle(text, time.monotonic())
        self.learning_model.on_subtitle(text, time.monotonic())
        self.caption_tick()
        if self.wired:
            self.wired_refresh()
        self.face_tick()

    def on_face_speech(self, text, dur=-1.0, index=0):
        """Frase começando a tocar no satélite: a legenda passa a revelá-la no tempo do áudio."""
        self.turn_phase.on_speech(time.monotonic())
        self.speech_caption.on_speech(text, dur if dur and dur > 0 else None, time.monotonic())
        self.learning_model.on_speech(text, dur if dur and dur > 0 else None, time.monotonic())
        self.caption_tick()

    def caption_tick(self):
        """Legenda que se escreve conforme ela fala: troca só o texto e redesenha só o grupo da
        fala (wired) ou o rosto, no ritmo das palavras (até 30 Hz); parada, o timer para."""
        now = time.monotonic()
        sc = self.speech_caption
        txt = sc.text(now)
        deadlines = [sc.deadline(now), self.turn_phase.deadline(now)]
        if self.wired:
            rects = self.wired.caption_rects(txt, self.view, self.size())
            main = self.wired.main
            chip = self.turn_phase.chip(now)
            if chip != self.wired.snap.chip:   # chip mudou (fase do turno / tempo mínimo)
                self.wired.snap.chip = chip
                rects = rects or self.wired.screen(self.view).group_rects("talk", self.size())
            if main.caption_feed(self.wired.snap.caption, now) and self.view not in ("idle", "learning"):
                rects = rects or main.group_rects("talk", self.size())   # rolagem suave da legenda
            deadlines.append(main.caption_deadline(now))
            if self.view == "learning":   # mensagem da Condessa revelada em sincronia (LM-003)
                deadlines.append(self.learning_model.deadline(now))
                rects = list(rects or []) + self.learning_dirty()
            if rects and not self.trans and self.isVisible() and self.width() > 1:
                for r in rects:
                    self.update(r)
        if txt != self.face.subtitle:
            self.face.set_subtitle(txt)
            if not self.wired:
                self.face_tick()
        deadline = min((d for d in deadlines if d is not None), default=None)
        if deadline is None:
            self.caption_timer.stop()
        else:
            self.caption_timer.start(max(1, math.ceil((deadline - now) * 1000)))

    def on_bridge_connected(self, up):
        self.learning_refresh()   # STATUS // CONNECTED/DISCONNECTED (o bridge já avisou o modelo)
        if up and self.wired:   # voltou: some a interferência do retrato
            self.wired.on_connected(True)
        if not up:   # núcleo fora do ar: a Magui dorme e a legenda some
            self.face.set_state("sleeping")
            self.face.set_subtitle("")
            self.speech_caption = SpeechCaption()
            self.turn_phase = TurnPhase()
            if self.wired:
                self.wired.snap.chip = None
            self.caption_timer.stop()
            if self.wired:
                self.wired.on_connected(False)
                self.wired_refresh()
            self.face_tick()

    def on_bridge_mood(self, v):
        self.magui_mood = v
        if self.wired:
            self.wired.set_mood(v)
            self.wired_refresh()

    def on_bridge_card(self, card):
        self.magui_cards.append(card)
        if self.wired:
            self.wired.on_card(card)
            self.wired_refresh()

    def on_bridge_vote(self, verdict, label):
        self.magui_vote = (verdict, label)

    def on_bridge_detail(self, target):
        """Painel de detalhes pedido pelo núcleo: cpu, gpu, memory; `none` fecha."""
        kind = self.DETAIL_FROM_BRIDGE.get(target)
        if kind is None:
            if self.detail:
                self.open_detail(self.detail)   # mesmo tipo de novo = fecha
            return
        if self.detail == kind:
            self.detail_until = time.monotonic() + 45
        else:
            self.open_detail(kind)
        if self.view == "idle":   # o painel só existe na view completa: vai e volta depois
            self.detail_return = "idle"
            self.switch_view("full")

    def switch_view(self, new_view):
        if new_view == self.view:
            return
        if self.isVisible() and load_settings().get("transition", True):
            self.start_transition(new_view)
        else:
            self.view = new_view
            self.idle_key = None
            self.render_caches()
            self.update()

    def detail_closed(self):
        if self.detail is None and self.detail_return:
            back, self.detail_return = self.detail_return, None
            self.switch_view(back)

    # ---------- dados / animação ----------
    def poll_rgb(self, instant=False):
        global T
        mtime = settings_mtime()
        if mtime != self.settings_mtime:
            self.settings_mtime = mtime
            cfg = load_settings()
            self.rgb_sync = cfg.get("rgb_sync", True)
            if not instant:
                self.apply_ui(cfg.get("ui", UI_DEFAULT))
            new_view = cfg.get("view", "full")
            self.detail_return = None   # Meta+M manda mais que o detalhe pedido pela voz
            # durante o Learning Mode o Meta+M só muda a view de retorno (LM1.7)
            new_view, self.lm_return = learning_toggle(self.view, self.lm_return,
                                                       {"t": "view", "view": new_view})
            if not instant and new_view != self.view and cfg.get("transition", True) and self.isVisible():
                self.start_transition(new_view)
            else:
                self.view = new_view
                if not instant:
                    self.idle_key = None
                    self.render_caches()
                    self.update()
        res = resolve_rgb(orgb.board_color()) if self.rgb_sync else None
        self.rgb_online = res is not None
        self.rgb_tgt = list(res if res else DEFAULT_RGB)
        if self.wired:   # LED ligado sem OpenRGB → visual off + aviso no rodapé (R23.6)
            self.wired.set_led(self.rgb_sync, rgb_hex(res) if res else None)
            if self.wired.snap.led_rgb != self.wired.led_rgb or self.wired.snap.led_on != self.wired.led_on:
                self.wired_refresh()
        if not instant and self.rgb_tgt != self.rgb_cur:
            self.theme_frame = 1   # começa a transição no próximo frame
        if instant:
            self.rgb_cur = list(self.rgb_tgt)
            T = Theme(*self.rgb_cur)
            self.update_icon()

    def toggle_rgb_sync(self):
        settings = load_settings()
        settings["rgb_sync"] = self.rgb_sync = not self.rgb_sync   # vale já, sem esperar o mtime
        save_settings(settings)
        self.poll_rgb()
        if self.wired:
            self.wired_refresh()

    def update_icon(self):
        icon = QIcon()
        for size in ICON_SIZES:
            icon.addPixmap(make_icon(size, T.accent))
        self.setWindowIcon(icon)

    def sample(self):
        self.sensors.poll()
        prev_file = self.fpsrc.file
        self.fpsrc.poll()
        if self.fpsrc.file and self.fpsrc.file != prev_file:
            # jogo novo: histórico e escala de FPS próprios
            self.hist["fps"] = deque([0.0] * HISTORY, maxlen=HISTORY)
            self.fps_scale = 60.0
        self.sample_count += 1
        if self.sample_count % 4 == 0:
            self.pads = controllers()
            self.steam_game = steam_game()
        if self.detail:
            if time.monotonic() > self.detail_until:
                self.detail = None    # fecha sozinho e volta pro FPS
                if self.detail_return:
                    self.detail_closed()
                    return
            elif self.wired or self.sample_count % 2 == 0:
                self.detail_rows = self.procs.poll(self.detail) or self.detail_rows
        d = self.sensors.data
        self.hist["fps"].append(self.fpsrc.fps or 0.0)
        self.hist["gpu"].append(d["gpu"])
        self.hist["cpu"].append(d["cpu"])
        self.last_sample = time.monotonic()
        self.targets = {
            "cpu": d["cpu"], "cpu_t": self._temp_pct(d["cpu_temp"]),
            "gpu": d["gpu"], "gpu_t": self._temp_pct(d["gpu_temp"]),
            "vram": d["vram"], "ram": d["ram"],
        }
        for k, v in self.targets.items():
            self.bars.setdefault(k, v)
        peak = max(max(self.hist["fps"]), 1.0)
        self.fps_scale += (max(60.0, peak * 1.15) - self.fps_scale) * 0.5
        self.track_session()
        if self.wired:
            self.wired_poll()
            if self.detail:
                self.wired_refresh(detail=True)
            return
        if not (self.isVisible() and self.width() > 1):
            return
        if self.view == "idle":
            # só redesenha quando algo visível muda (minuto, jogo, média, sessão)
            now = datetime.datetime.now()
            key = (now.hour, now.minute, self.steam_game or self.fpsrc.name, self.idle_avg,
                   self.session_minutes(), T.accent.name(), self.size().width())
            if key == self.idle_key:
                return
            self.idle_key = key
        self.render_caches()
        self.update()

    def track_session(self):
        playing = (self.steam_game or self.fpsrc.name) is not None
        now = time.monotonic()
        if not playing:
            self.game_since, self.idle_avg, self.idle_acc = None, None, []
            return
        if self.game_since is None:
            self.game_since, self.idle_avg_t = now, now
        if self.fpsrc.fps is not None:
            self.idle_acc.append(self.fpsrc.fps)
        first = self.idle_avg is None and len(self.idle_acc) >= 60          # ~30 s de jogo
        if self.idle_acc and (first or now - self.idle_avg_t >= IDLE_AVG_S):
            self.idle_avg = sum(self.idle_acc) / len(self.idle_acc)
            self.idle_acc, self.idle_avg_t = [], now

    def session_minutes(self):
        return None if self.game_since is None else int((time.monotonic() - self.game_since) // 60)

    @staticmethod
    def _temp_pct(t):
        return 0.0 if t is None else max(0.0, min(100.0, (t - 30) / 70 * 100))

    def start_transition(self, new_view):
        self.trans = None
        old = self.grab()                 # o que está na tela agora (com gráfico e barras)
        self.view = new_view
        self.idle_key = None
        self.render_caches()
        new = self.grab()
        self.trans = {"old": old, "new": new, "t0": time.monotonic()}
        self.anim_timer.start(16)   # 60 fps só durante a cortina
        self.update()

    def animate(self):
        global T
        if self.frame is None and not self.trans:
            return
        if self.trans:
            if time.monotonic() - self.trans["t0"] >= TRANSITION_S:
                self.trans = None
                if self.wired:
                    self.anim_timer.stop()   # wired não tem quadros de animação fora da cortina
                    self.face_tick()
                else:
                    self.anim_timer.setInterval(ANIM_MS)
            self.update()
            return
        if self.wired:
            self.anim_timer.stop()
            return
        # transição de cor do tema (~0,4 s), re-renderizando o cache a 15 fps
        if self.rgb_cur != self.rgb_tgt:
            self.theme_frame += 1
            if self.theme_frame % 2 == 0:
                done = True
                for i, t in enumerate(self.rgb_tgt):
                    c = self.rgb_cur[i]
                    eps = 0.02 if i == 3 else 3.0
                    if abs(t - c) > eps:
                        self.rgb_cur[i] = c + (t - c) * 0.45
                        done = False
                if done:
                    self.rgb_cur = list(self.rgb_tgt)
                T = Theme(*self.rgb_cur)
                if done:
                    self.update_icon()
                self.bg = None
                self.render_caches()
                self.update()
                return
        if self.view == "idle":
            return
        for k, t in self.targets.items():
            v = self.bars[k]
            if abs(t - v) > 0.05:
                self.bars[k] = v + (t - v) * 0.2
                for spec in self.bar_specs():
                    if spec[1] == k:
                        self.update(spec[0].toAlignedRect().adjusted(-2, -2, 2, 2))
            else:
                self.bars[k] = t
        self.update(self.r_plot().toAlignedRect().adjusted(-2, -2, 2, 2))

    DETAIL_KINDS = ("cpu", "gpu", "mem")

    def open_detail(self, kind):
        if self.detail == kind:
            self.detail = None
        else:
            self.detail = kind
            self.procs.reset()
            self.detail_rows = self.procs.poll(kind)   # cpu/gpu precisam de 2 leituras
        self.detail_until = time.monotonic() + 45
        if self.detail is None and self.detail_return:
            self.detail_closed()
            return
        if self.wired:
            self.update(self.wired.detail_rect(self.size()))
            return
        self.render_caches()
        self.update()

    def clickable(self, pos):
        """Clique simples tem ação aqui (rosto, botão de sync, linhas do MAGI, painel aberto)."""
        if self.wired:
            return self.wired.hit(pos, self.size(), self.view, self.detail)
        if self.r_face().contains(pos):
            return "face"
        if self.view == "idle":
            return None
        if self.r_sync().contains(pos):
            return "sync"
        for i, kind in enumerate(self.DETAIL_KINDS):
            if self.r_magi_row(i).contains(pos):
                return kind
        if self.detail and self.r_hero().contains(pos):
            return "close"
        return None

    # ---------- Konsole // Claude Code (docs/design/nova-ui/KONSOLE.md) ----------
    # O `claude` roda num pty (konsole_term.KonsoleSession); o QSocketNotifier no fd chama
    # pump(), e a repintura (card ou expandido) sai no máximo a ~30 fps. Só no expandido o HUD
    # aceita foco e teclado (mesma troca de WindowDoesNotAcceptFocus do Learning, LM0.3).
    KON_FRAME_S = 0.033

    def konsole_scale(self):
        return self.width() / 1920.0

    def konsole_dev(self, r):
        """Retângulo base 1920 → dispositivo (com 1 px de folga para o antialias)."""
        s = self.konsole_scale()
        return QRectF(r.x() * s, r.y() * s, r.width() * s, r.height() * s).toAlignedRect().adjusted(-1, -1, 1, 1)

    def konsole_shown(self):
        return self.kon_open and self.wired is not None and self.view == "full" and not self.trans

    def konsole_start(self):
        """Sobe a sessão se não houver uma viva (comando e pasta: settings.json konsole_cmd/konsole_cwd)."""
        if self.kon is not None and self.kon.alive:
            return
        self.konsole_stop()
        kview.VIEW.error = None
        cfg = load_settings()
        cols, rows = kview.cells_for(kview.EXPANDED_RECT, self.konsole_scale())
        try:
            self.kon = konsole_term.KonsoleSession(cfg.get("konsole_cmd"), cfg.get("konsole_cwd"), cols, rows)
        except RuntimeError:   # sem pyte no Python do sistema
            self.kon = None
            kview.VIEW.error = konsole_term.MISSING_PYTE
        except OSError as ex:   # claude fora do PATH, pasta inexistente…
            self.kon = None
            kview.VIEW.error = f"[falha ao abrir: {ex.strerror or ex}]"
            print(f"konsole: {ex}", file=sys.stderr)
        kview.VIEW.session = self.kon
        if self.kon is None:
            return
        n = QSocketNotifier(self.kon.fileno(), QSocketNotifier.Type.Read, self)
        n.activated.connect(self.konsole_read)
        self.kon_notifier = n

    def konsole_stop(self):
        """Encerra a sessão (SIGTERM/SIGKILL ao grupo, sem zumbi). A view mostra "encerrada"."""
        if self.kon_notifier is not None:
            self.kon_notifier.setEnabled(False)
            self.kon_notifier.deleteLater()
            self.kon_notifier = None
        if self.kon is not None and self.kon.fd is not None:
            self.kon.close()

    def konsole_read(self, *_):
        k = self.kon
        if k is None:
            return
        changed = k.pump()
        if not k.alive:   # saiu: o fd fica legível para sempre (EIO), desliga o notifier
            self.konsole_stop()
            self.kon_full = True
            changed = True
        if changed:
            self.konsole_schedule()

    def konsole_schedule(self):
        if not self.kon_timer.isActive():
            wait = self.kon_last + self.KON_FRAME_S - time.monotonic()
            self.kon_timer.start(max(0, int(wait * 1000)))

    def konsole_flush(self):
        """Repinta o que mudou: as linhas sujas do expandido ou o card (o painel pinta o miolo)."""
        self.kon_last = time.monotonic()
        k = self.kon
        rows = k.take_dirty() if k is not None else set()
        if not (self.wired and self.view == "full" and self.isVisible()) or self.trans:
            return
        if not self.kon_open:
            self.update(self.konsole_dev(kview.CARD_RECT))
            return
        s = self.konsole_scale()
        if self.kon_full or k is None:
            self.kon_full = False
            self.update(self.konsole_dev(kview.EXPANDED_RECT))
            return
        area = kview.term_rect(kview.EXPANDED_RECT)
        track = QRectF(area.right(), area.top(), kview.EXPANDED_RECT.right() - area.right(), area.height())
        for r in kview.VIEW.row_rects(rows, kview.EXPANDED_RECT, s) + [track]:
            self.update(self.konsole_dev(r))

    def konsole_expand(self):
        """Clique no card: abre o Konsole grande (sobe a sessão se preciso) com foco e teclado."""
        if not self.wired or self.view != "full":
            return
        self.konsole_start()
        self.kon_open = True
        if self.kon is not None:
            self.kon.resize(*kview.cells_for(kview.EXPANDED_RECT, self.konsole_scale()))
            kview.VIEW.status = konsole_term.git_status(self.kon.cwd)
        self.konsole_focus(True)
        self.kon_full = False
        self.wired.konsole_swap(True)   # a câmera vai para o lugar do card
        self.konsole_swap_update()

    def konsole_collapse(self):
        """Recolhe (a sessão continua viva): devolve a flag de foco e destroca câmera e card."""
        if not self.kon_open:
            return
        self.kon_open = False
        self.konsole_focus(False)
        if self.wired:
            self.wired.konsole_swap(False)
        self.konsole_swap_update()

    def konsole_swap_update(self):
        """Troca Konsole ⇄ cam 01: só as duas caixas (a do cam 01 e a do card KONSOLE)."""
        self.update(self.konsole_dev(kview.EXPANDED_RECT))
        self.update(self.konsole_dev(kview.CARD_RECT))

    def konsole_focus(self, on):
        win = self.windowHandle()
        if win is not None:
            learning = self.wired is not None and self.view == "learning"
            win.setFlag(Qt.WindowDoesNotAcceptFocus, not (on or learning))
        if on:
            self.setFocusPolicy(Qt.StrongFocus)
            self.activateWindow()
            self.setFocus(Qt.MouseFocusReason)
        else:
            self.clearFocus()
            self.setFocusPolicy(Qt.NoFocus)

    def konsole_mouse(self, e):
        s = self.konsole_scale()
        hit = kview.VIEW.hit_expanded(QPointF(e.position().x() / s, e.position().y() / s))
        if hit == "term":
            if self.kon is None or not self.kon.alive:
                if e.button() == Qt.LeftButton:
                    self.konsole_expand()   # sessão encerrada: clique abre outra
                    self.kon_full = True
                    self.konsole_schedule()
            else:
                self.konsole_focus(True)
            return
        self.konsole_collapse()   # botão – □ ×, câmera pequena ("cam") ou clique fora

    def focusNextPrevChild(self, nxt):
        if self.konsole_shown():
            return False   # Tab/Shift+Tab vão para o terminal (keyPressEvent)
        return super().focusNextPrevChild(nxt)

    def keyPressEvent(self, e):
        """Teclado do Konsole expandido → pty (Esc também: o Claude usa para interromper).
        Ctrl+Shift+V cola; Shift+PgUp/PgDn rolam o histórico."""
        if not self.konsole_shown():
            super().keyPressEvent(e)
            return
        e.accept()
        k, key, mods = self.kon, e.key(), e.modifiers()
        if k is None or not k.alive:
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self.konsole_expand()
                self.kon_full = True
                self.konsole_schedule()
            return
        if key == Qt.Key_V and mods & Qt.ControlModifier and mods & Qt.ShiftModifier:
            k.paste(QGuiApplication.clipboard().text())
            return
        if key in (Qt.Key_PageUp, Qt.Key_PageDown) and mods & Qt.ShiftModifier:
            step = max(1, k.rows // 2)
            if k.scroll_by(step if key == Qt.Key_PageUp else -step):
                self.kon_full = True
                self.konsole_schedule()
            return
        data = konsole_term.qt_key_to_bytes(key, e.text(), mods, k.app_cursor)
        if data:
            if k.scroll:   # digitou: volta a acompanhar o fim
                k.scroll_by(-k.scroll)
                self.kon_full = True
                self.konsole_schedule()
            k.write(data)

    # ---------- Learning Mode (LM1.6): campo de texto, despachante de mouse, lm_* ----------
    def make_learning_entry(self):
        """QLineEdit filho (design §4.3, caminho 1 do LM0.3): oculto fora da view learning, sem
        moldura (a moldura é pintada no grupo input), Enter → lm_say, Esc limpa."""
        e = QLineEdit(self)
        e.setFrame(False)
        e.setMaxLength(hud_bridge.LM_SAY_MAX)
        e.setPlaceholderText("type a message…")
        e.setAttribute(Qt.WA_MacShowFocusRect, False)
        e.returnPressed.connect(self.learning_submit)
        e.hide()
        e.installEventFilter(self)
        self.lm_entry = e
        self.learning_entry_sync()

    def eventFilter(self, obj, ev):
        if obj is self.lm_entry and ev.type() == ev.Type.KeyPress:
            # menu de seleção aberto (LM2.2): ↑↓/Enter/Esc vão primeiro para ele; com texto no
            # campo o Enter continua mandando lm_say
            name = {Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Return: "enter",
                    Qt.Key_Enter: "enter", Qt.Key_Escape: "esc"}.get(ev.key())
            if name and self.wired and self.view == "learning" \
                    and self.wired.learning.key(name, typing=bool(obj.text())):
                self.learning_refresh()
                return True
            if ev.key() == Qt.Key_Escape:
                obj.clear()
                return True
        return super().eventFilter(obj, ev)

    def learning_entry_sync(self):
        """Mostra o campo só na view learning (wired), posicionado no retângulo do campo ×
        escala, com a fonte × escala. Troca WindowDoesNotAcceptFocus pela QWindow (sem recriar
        a superfície, LM0.3): sem a flag só na view learning; painel e espera continuam sem foco."""
        e = self.lm_entry
        if e is None:
            return
        on = self.wired is not None and self.view == "learning"
        win = self.windowHandle()
        if win is not None:
            win.setFlag(Qt.WindowDoesNotAcceptFocus, not (on or getattr(self, "kon_open", False)))
        if not on:
            if e.isVisible():
                e.clearFocus()
                e.hide()
            return
        scr = self.wired.learning
        s = scr.scale(self.size())
        r = scr.entry_rect()
        e.setGeometry(round(r.x() * s), round(r.y() * s), round(r.width() * s), round(r.height() * s))
        e.setFont(wfonts.font("mono", 18 * s))   # o filho não passa pelo p.scale(): fonte × escala
        e.setStyleSheet(f"QLineEdit {{ background: transparent; border: none; color: {wtheme.TEXT};"
                        f" selection-background-color: {wtheme.CPU}; }}")
        if not e.isVisible():
            e.show()
            e.setFocus(Qt.OtherFocusReason)

    def learning_submit(self):
        """Enter no campo: lm_say. Fica o texto se o núcleo estiver fora (rodapé DISCONNECTED)."""
        txt = check_say(self.lm_entry.text())
        if txt is None:
            return
        if self.bridge.send_lm("lm_say", {"text": txt}):
            self.lm_entry.clear()

    def learning_dirty(self):
        """Retângulos da tela learning cujos grupos mudaram (vazio fora da view)."""
        if not (self.wired and self.view == "learning") or self.trans:
            return []
        if not (self.isVisible() and self.width() > 1):
            return []
        return self.wired.learning.dirty_regions(self.wired.snap, size=self.size())

    def learning_refresh(self):
        for r in self.learning_dirty():
            self.update(r)

    def on_bridge_learning(self, msg):
        """lm_* (o bridge já entregou ao learning_model): repinta os grupos e agenda a revelação."""
        if msg.get("t") == "lm_mode":
            self.learning_switch(msg)
        if msg.get("t") == "lm_msg":
            self.caption_tick()   # prazo da revelação da fala + repintura do histórico
        else:
            self.learning_refresh()

    def learning_switch(self, msg):
        """``lm_mode`` confirmado pelo núcleo (botão ou voz, LM1.7): entra na view learning
        guardando a atual (full/idle) ou volta para ela, com a cortina (``switch_view``)."""
        if not self.wired:   # a tela learning só existe no tema wired
            return
        view = self.view
        if msg.get("on") and view != "learning" and self.detail_return:
            # painel aberto pela voz a partir da espera: o retorno é a espera, e o detalhe não
            # pode tirar o HUD da tela learning ao fechar
            view, self.detail_return = self.detail_return, None
        new, self.lm_return = learning_toggle(view, self.lm_return, msg)
        if new != self.view:
            self.switch_view(new)

    def learning_mouse(self, kind, e, delta=0.0):
        """Despachante único: com view learning, todo evento de mouse vai ao WiredUI."""
        target = self.wired.learning_mouse(kind, e.position(), self.size(), delta)
        if kind == "press" and self.lm_entry is not None and self.lm_entry.isVisible():
            self.lm_entry.setFocus(Qt.MouseFocusReason)   # clicou no HUD: o teclado vai ao campo
        if target:
            self.wired_click(target)
        self.learning_refresh()

    def mousePressEvent(self, e):
        if self.konsole_shown():   # expandido: dentro é dele, fora (qualquer botão) recolhe
            self.konsole_mouse(e)
            return
        if e.button() != Qt.LeftButton:
            return
        if self.wired and self.view == "learning":
            self.learning_mouse("press", e)
            return
        target = self.clickable(e.position())
        if self.wired and target:
            self.wired_click(target)
            return
        if target == "face":
            self.bridge.send_cmd("push_to_talk")   # falso se o núcleo não estiver no ar
        elif target == "sync":
            self.toggle_rgb_sync()
        elif target == "close":
            self.open_detail(self.detail)
        elif target:
            self.open_detail(target)

    def mouseMoveEvent(self, e):
        if self.wired and self.view == "learning" and e.buttons() & Qt.LeftButton:
            self.learning_mouse("move", e)

    def mouseReleaseEvent(self, e):
        if self.wired and self.view == "learning" and e.button() == Qt.LeftButton:
            self.learning_mouse("release", e)

    def wired_click(self, target):
        """Cliques do tema wired: LED → RGB Sync, player → MPRIS, cards → detalhes por processo,
        LEARNING/END SESSION → pede ``lm_mode`` ao núcleo (a tela só troca na confirmação, LM1.7;
        com o núcleo fora o envio falha e nada muda: o rodapé já mostra DISCONNECTED).
        A Condessa olha para onde o Pedro clicou (wired.reactions)."""
        self.wired.on_click(target)
        self.face_tick()
        if target == "learning":
            self.bridge.send_lm("lm_mode", {"on": self.view != "learning"})
        elif target == "face":
            self.bridge.send_cmd("push_to_talk")
        elif target == "led":
            self.toggle_rgb_sync()
        elif target == "konsole":
            self.konsole_expand()
        elif target == "cam":   # câmera pequena no slot do card: recolhe o Konsole
            self.konsole_collapse()
        elif target == "detail":
            self.open_detail(self.detail)   # mesmo tipo de novo = fecha
        elif target in CARD_DETAIL:
            self.open_detail(CARD_DETAIL[target])
        elif self.wired.player(target):
            self.wired_refresh()

    on_close = None   # main() liga a restauração do wallpaper aqui

    def closeEvent(self, e):
        self.konsole_stop()
        if self.on_close:
            self.on_close()
        super().closeEvent(e)

    def wheelEvent(self, e):
        """Roda do mouse sobre a legenda da Condessa: volta para ler a última fala (pausa o
        acompanhamento; volta a acompanhar no fim do texto ou com fala nova)."""
        if self.konsole_shown():   # Konsole expandido: a roda rola o histórico do terminal
            steps = e.angleDelta().y() / 120 or e.pixelDelta().y() / 27
            if self.kon is not None and self.kon.scroll_by(round(steps * 3)):
                self.kon_full = True
                self.konsole_schedule()
            e.accept()
            return
        if self.wired and self.view == "learning":   # rolagem do histórico (LM1.6)
            steps = e.angleDelta().y() / 120 or e.pixelDelta().y() / 27
            self.learning_mouse("wheel", e, steps)
            e.accept()
            return
        main = self.wired.main if self.wired else None
        if main is None or self.view in ("idle", "learning") or not main.caption_hit(e.position(), self.size()):
            e.ignore()
            return
        steps = e.angleDelta().y() / 120 or e.pixelDelta().y() / 27
        if steps and main.caption_wheel(steps):
            for r in main.group_rects("talk", self.size()):
                self.update(r)
            self.caption_tick()   # agenda os quadros da rolagem
        e.accept()

    def mouseDoubleClickEvent(self, e):
        # Duplo clique não fecha mais o HUD: dois cliques rápidos em notícias/rede derrubavam tudo.
        # Para fechar: pkill -f gamerhud/gamerhud.py (o HUD sobe sozinho no login).
        # Na view learning ele só seleciona a frase (LM2.2), nunca fecha nada.
        if self.wired and self.view == "learning" and e.button() == Qt.LeftButton:
            self.learning_mouse("double", e)
        return

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.learning_entry_sync()
        if self.kon_open and self.kon is not None:
            self.kon.resize(*kview.cells_for(kview.EXPANDED_RECT, self.konsole_scale()))
        if self.wired:
            return   # as telas wired guardam a camada estática por tamanho sozinhas
        self.bg = None
        self.render_caches()

    # ---------- layout (unidades de projeto em 2560x1440) ----------
    def R(self, x, y, w, h):
        sx, sy = self.width() / 2560, self.height() / 1440
        return QRectF(x * sx, y * sy, w * sx, h * sy)

    def r_header_clock(self): return self.R(1800, 40, 690, 160)
    def r_hero(self): return self.R(70, 260, 1390, 650)
    def r_magi(self): return self.R(1510, 260, 980, 650)
    def r_graph(self): return self.R(70, 960, 1470, 410)
    def r_spec(self): return self.R(1580, 960, 910, 410)
    def r_sync(self): return self.R(2130, 976, 330, 52)
    def r_magi_row(self, i): return self.R(1530, 338 + i * 186, 940, 178)

    def r_plot(self):
        g, s = self.r_graph(), self.height() / 1440
        return QRectF(g.left() + 44 * s, g.top() + 80 * s, g.width() - 88 * s, g.height() - 110 * s)

    def bar_specs(self):
        """(retângulo, chave, cor, escala de calor) de cada barra segmentada."""
        r, s = self.r_magi(), self.height() / 1440
        rows = (("cpu", "cpu_t", T.purple), ("gpu", "gpu_t", T.green), ("vram", "ram", T.accent))
        out = []
        for i, (k1, k2, col) in enumerate(rows):
            top = r.top() + (84 + i * 186) * s
            for j, k in enumerate((k1, k2)):
                y = top + (14 + j * 82) * s
                out.append((QRectF(r.left() + 396 * s, y + 8 * s, 340 * s, 50 * s), k, col, k.endswith("_t")))
        return out

    # ---------- fontes ----------
    def f(self, kind, px):
        s = self.height() / 1440
        fam, weight, st = {
            "title": ("Noto Serif", QFont.Black, QFont.ExtraCondensed),
            "jp": ("Noto Serif CJK JP", QFont.Black, 85),
            "seg": (self.fonts["seg"], QFont.Bold, 100),
        }[kind]
        font = QFont(fam)
        font.setPixelSize(max(1, int(px * s)))
        font.setWeight(weight)
        font.setStretch(st)
        return font

    def text(self, p, rect, flags, txt, font, color):
        p.setFont(font)
        p.setPen(color)
        p.drawText(rect, flags, txt)

    def elided(self, p, rect, flags, txt, font, color):
        p.setFont(font)
        txt = p.fontMetrics().elidedText(txt, Qt.ElideRight, int(rect.width()))
        self.text(p, rect, flags, txt, font, color)

    # ---------- desenho ----------
    def render_caches(self):
        if self.wired:
            self.frame = None   # o tema wired pinta direto (camadas em cache dentro das telas)
            return
        if self.view == "idle":
            self.frame = self.build_idle()
            return
        if self.bg is None or self.bg.size() != self.size():
            self.bg = self.build_background()
        self.frame = QPixmap(self.size())
        p = QPainter(self.frame)
        p.drawPixmap(0, 0, self.bg)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        for rect, fn in ((self.r_header_clock(), self.draw_clock),
                         (self.r_hero(), self.draw_detail if self.detail else self.draw_hero),
                         (self.r_magi(), self.draw_magi),
                         (self.r_graph(), self.draw_graph),
                         (self.r_spec(), self.draw_spec)):
            p.save()
            fn(p, rect)
            p.restore()
        p.end()
        self.plot_pm = self.render_plot()

    def paintEvent(self, ev):
        if self.wired:
            p = QPainter(self)
            if self.trans:
                self.paint_transition(p)
            else:
                self.paint_wired(p, ev.region())
            p.end()
            return
        if self.frame is None or self.frame.size() != self.size():
            self.render_caches()
        p = QPainter(self)
        if self.trans:
            self.paint_transition(p)
            p.end()
            return
        region = ev.region()
        if self.view == "idle":
            p.drawPixmap(0, 0, self.frame)
            self.paint_face(p, region)
            p.end()
            return
        s = self.height() / 1440
        plot = self.r_plot()
        plot_i = plot.toAlignedRect()
        rest = region.subtracted(QRegion(plot_i))
        if not rest.isEmpty():
            p.setClipRegion(rest)
            p.drawPixmap(0, 0, self.frame)
            p.setClipping(False)
        if region.intersects(plot_i):
            step = plot.width() / (HISTORY - 2)
            phase = min(1.0, (time.monotonic() - self.last_sample) * 1000 / SAMPLE_MS)
            x0 = round(plot.right() + (1 - phase) * step - (HISTORY - 1) * step)
            p.setClipRect(plot_i)
            p.drawPixmap(x0, plot_i.top(), self.plot_pm)
            p.setClipping(False)
            p.setPen(QPen(alpha(T.accent, 80), 1.5 * s))
            p.drawRect(plot)
        p.setRenderHint(QPainter.Antialiasing)
        for rect, key, col, heat in self.bar_specs():
            if region.intersects(rect.toAlignedRect()):
                self.seg_bar(p, rect, self.bars[key], col, heat)
        self.paint_face(p, region)
        p.end()

    def paint_face(self, p, region):
        r = self.r_face()
        if region.intersects(r.toAlignedRect()):
            self.face.paint(p, r, T.accent)

    def paint_transition(self, p):
        """Cortina diagonal estilo NERV: a tela nova entra pela esquerda atrás de uma faixa preta."""
        W, H = self.width(), self.height()
        s = H / 1440
        t = min(1.0, (time.monotonic() - self.trans["t0"]) / TRANSITION_S)
        e = t * t * (3 - 2 * t)                   # suaviza início e fim
        band, skew = 520 * s, 360 * s
        x = -band - skew + e * (W + 2 * band + 2 * skew)   # borda esquerda da faixa

        def poly(x0, x1):
            return QPolygonF([QPointF(x0 + skew, 0), QPointF(x1 + skew, 0),
                              QPointF(x1, H), QPointF(x0, H)])

        def clip_draw(region, pm):
            path = QPainterPath()
            path.addPolygon(region)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(0, 0, pm)
            p.restore()

        clip_draw(poly(-W - skew, x), self.trans["new"])
        clip_draw(poly(x + band, W + skew), self.trans["old"])
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0))
        p.drawPolygon(poly(x, x + band))
        # listras de alerta dentro da faixa
        path = QPainterPath()
        path.addPolygon(poly(x, x + band))
        p.save()
        p.setClipPath(path)
        p.setBrush(alpha(T.accent, 45))
        step = 70 * s
        k = x - H
        while k < x + band + skew:
            p.drawPolygon(QPolygonF([QPointF(k, H), QPointF(k + H * 0.6, 0),
                                     QPointF(k + H * 0.6 + step / 2, 0), QPointF(k + step / 2, H)]))
            k += step
        p.restore()
        # bordas na cor do tema + texto vertical
        for edge, wpx in ((x, 10 * s), (x + band - 4 * s, 4 * s)):
            p.setBrush(T.accent)
            p.drawPolygon(poly(edge, edge + wpx))
        big = QFont("Noto Serif CJK JP")
        big.setWeight(QFont.Black)
        big.setPixelSize(int(120 * s))
        p.save()
        p.translate(x + band / 2 + skew / 2, H / 2)
        p.rotate(90)
        self.text(p, QRectF(-H, -80 * s, 2 * H, 160 * s), Qt.AlignCenter, "移行中  ·  MAGI", big,
                  QColor(244, 240, 232))
        p.restore()

    def build_idle(self):
        """Tela de ociosidade estilo title card do Evangelion: preto, mincho gigante, nada se mexe."""
        W, H = self.width(), self.height()
        s = H / 1440
        pm = QPixmap(self.size())
        pm.fill(QColor(0, 0, 0))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        now = datetime.datetime.now()
        game = self.steam_game or self.fpsrc.name
        white = QColor(244, 240, 232)

        x0, y0 = 320 * s, 250 * s
        p.fillRect(QRectF(x0 - 70 * s, y0 + 10 * s, 12 * s, 900 * s), T.accent)   # fio de cor do tema

        label = game or "MAGI SYSTEM"
        self.elided(p, QRectF(x0, y0, 1500 * s, 80 * s), Qt.AlignLeft | Qt.AlignVCenter,
                    label, self.f("title", 72), white)
        lw = min(p.fontMetrics().horizontalAdvance(label), 1500 * s)
        self.text(p, QRectF(x0 + lw + 30 * s, y0 + 6 * s, 400 * s, 80 * s), Qt.AlignLeft | Qt.AlignVCenter,
                  "稼働中" if game else "待機中", self.f("jp", 44), T.accent)

        big = QFont("Noto Serif CJK JP")
        big.setWeight(QFont.Black)
        big.setStretch(72)
        big.setPixelSize(int(310 * s))
        for i, line in enumerate((f"{kanji_num(now.hour)}時", f"{kanji_num(now.minute)}分")):
            self.text(p, QRectF(x0 - 14 * s, y0 + (110 + i * 300) * s, 2200 * s, 330 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, line, big, white)

        self.text(p, QRectF(x0, y0 + 760 * s, 2000 * s, 90 * s), Qt.AlignLeft | Qt.AlignVCenter,
                  en_time(now.hour, now.minute), self.f("title", 84), white)
        self.text(p, QRectF(x0, y0 + 850 * s, 2000 * s, 60 * s), Qt.AlignLeft | Qt.AlignVCenter,
                  f"{EN_DAYS[now.weekday()]}, {EN_MONTHS[now.month - 1]} {now.day}  ·  {DIAS_JP[now.weekday()]}",
                  self.f("title", 40), alpha(white, 120))

        if game:   # canto discreto: média de FPS (muda a cada 5 min) e tempo de sessão
            right = W - 160 * s
            mins = self.session_minutes() or 0
            self.text(p, QRectF(right - 900 * s, H - 330 * s, 900 * s, 40 * s), Qt.AlignRight | Qt.AlignVCenter,
                      f"平均  ·  MÉDIA {IDLE_AVG_S // 60} MIN", self.f("title", 26), alpha(white, 90))
            avg = f"{self.idle_avg:.0f}" if self.idle_avg is not None else "--"
            r = QRectF(right - 760 * s, H - 290 * s, 560 * s, 140 * s)
            self.text(p, r, Qt.AlignRight | Qt.AlignVCenter, avg, self.f("seg", 96), alpha(white, 150))
            self.text(p, QRectF(r.right() + 20 * s, r.top(), 180 * s, r.height()),
                      Qt.AlignLeft | Qt.AlignBottom, "FPS", self.f("title", 48), alpha(T.accent, 190))
            self.text(p, QRectF(right - 900 * s, H - 140 * s, 900 * s, 44 * s), Qt.AlignRight | Qt.AlignVCenter,
                      f"稼働時間  ·  SESSÃO {mins // 60:02d}:{mins % 60:02d}", self.f("title", 30), alpha(white, 110))
        self.text(p, QRectF(x0 - 70 * s, H - 110 * s, 1000 * s, 40 * s), Qt.AlignLeft | Qt.AlignVCenter,
                  "META+M  ·  PAINEL COMPLETO", self.f("title", 22), alpha(white, 45))
        p.end()
        return pm

    def render_plot(self):
        """Linhas do gráfico numa imagem opaca; a rolagem é só um deslocamento."""
        s = self.height() / 1440
        plot = self.r_plot()
        step = plot.width() / (HISTORY - 2)
        pm = QPixmap(int((HISTORY - 1) * step) + 8, plot.toAlignedRect().height() + 1)
        pm.fill(T.plot_bg)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        h = plot.height()
        p.setPen(QPen(alpha(T.green, 22), 1))
        for k in range(1, 4):
            p.drawLine(QPointF(0, h * k / 4), QPointF(pm.width(), h * k / 4))
        for i in range(HISTORY):
            if (self.sample_count - (HISTORY - 1 - i)) % 20 == 0:
                p.drawLine(QPointF(i * step, 0), QPointF(i * step, h))
        series = [("cpu", T.purple, 100.0), ("gpu", T.green, 100.0)]
        if self.graph_live():
            series.append(("fps", T.accent, self.fps_scale))
        for key, col, scale in series:
            pts = [QPointF(i * step, h - h * min(1.0, v / scale)) for i, v in enumerate(self.hist[key])]
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            if key == "fps":
                fill = QPainterPath(path)
                fill.lineTo(pts[-1].x(), h)
                fill.lineTo(0, h)
                fill.closeSubpath()
                g = QLinearGradient(0, 0, 0, h)
                g.setColorAt(0, alpha(col, 70))
                g.setColorAt(1, alpha(col, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawPath(fill)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col, (3.5 if key == "fps" else 2.2) * s))
            p.drawPath(path)
        p.end()
        return pm

    def graph_live(self):
        return self.fpsrc.fps is not None or max(self.hist["fps"]) > 0

    def cut_panel(self, r, c):
        return QPolygonF([QPointF(r.left() + c, r.top()), QPointF(r.right(), r.top()),
                          QPointF(r.right(), r.bottom() - c), QPointF(r.right() - c, r.bottom()),
                          QPointF(r.left(), r.bottom()), QPointF(r.left(), r.top() + c)])

    def panel(self, p, r):
        s = self.height() / 1440
        p.setPen(QPen(alpha(T.accent, 170), 2 * s))
        p.setBrush(alpha(T.accent, 10))
        p.drawPolygon(self.cut_panel(r, 34 * s))
        p.setPen(Qt.NoPen)
        p.setBrush(T.accent)
        p.drawRect(QRectF(r.left() + 40 * s, r.top() - 4 * s, 120 * s, 8 * s))

    def hazard(self, p, r):
        p.save()
        p.setClipRect(r)
        p.fillRect(r, QColor(0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(alpha(T.accent, 210))
        w = r.height()
        x = r.left() - w
        while x < r.right():
            p.drawPolygon(QPolygonF([QPointF(x, r.bottom()), QPointF(x + w, r.top()),
                                     QPointF(x + 2 * w, r.top()), QPointF(x + w, r.bottom())]))
            x += 2.4 * w
        p.restore()

    def build_background(self):
        W, H = self.width(), self.height()
        s = H / 1440
        pm = QPixmap(self.size())
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        g = QLinearGradient(0, 0, 0, H)
        g.setColorAt(0, T.bg_top)
        g.setColorAt(1, T.bg_bot)
        p.fillRect(pm.rect(), g)

        # grade hexagonal
        rr = 46 * s
        hw, hh = rr * 1.732, rr * 1.5
        p.setPen(QPen(alpha(T.accent, 14), 1))
        p.setBrush(Qt.NoBrush)
        hexa = [QPointF(rr * 0.866 * dx, rr * dy) for dx, dy in
                ((0, -1), (1, -0.5), (1, 0.5), (0, 1), (-1, 0.5), (-1, -0.5))]
        row, y = 0, 0.0
        while y < H + rr:
            x = (hw / 2) if row % 2 else 0.0
            while x < W + hw:
                p.drawPolygon(QPolygonF([QPointF(x + q.x(), y + q.y()) for q in hexa]))
                x += hw
            y += hh
            row += 1

        # cabeçalho
        self.text(p, self.R(70, 40, 1600, 100), Qt.AlignLeft | Qt.AlignVCenter,
                  "汎用監視システム", self.f("jp", 84), T.white)
        self.text(p, self.R(74, 140, 1600, 50), Qt.AlignLeft | Qt.AlignVCenter,
                  "GENERAL PURPOSE MONITORING SYSTEM  —  MAGI-01", self.f("title", 40), T.accent)
        self.hazard(p, self.R(70, 212, 2420, 18))

        for r in (self.r_hero(), self.r_magi(), self.r_graph(), self.r_spec()):
            self.panel(p, r)
        p.fillRect(self.r_plot(), T.plot_bg)

        # rótulos fixos
        h = self.r_hero()
        self.text(p, QRectF(h.left() + 44 * s, h.top() + 26 * s, 900 * s, 70 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "FRAME RATE", self.f("title", 66), T.white)
        self.text(p, QRectF(h.left() + 46 * s, h.top() + 92 * s, 900 * s, 40 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "毎秒フレーム数", self.f("jp", 30), T.accent)
        p.setPen(QPen(alpha(T.accent, 90), 2 * s))
        p.drawLine(QPointF(h.left() + 40 * s, h.top() + 528 * s),
                   QPointF(h.right() - 40 * s, h.top() + 528 * s))

        m = self.r_magi()
        self.text(p, QRectF(m.left() + 44 * s, m.top() + 18 * s, 600 * s, 56 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "MAGI SYSTEM", self.f("title", 52), T.white)
        self.text(p, QRectF(m.left(), m.top() + 22 * s, m.width() - 44 * s, 50 * s),
                  Qt.AlignRight | Qt.AlignVCenter, "三系統合議制", self.f("jp", 28), T.accent)

        sp = self.r_spec()
        self.text(p, QRectF(sp.left() + 44 * s, sp.top() + 14 * s, 400 * s, 50 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "UNIT SPEC", self.f("title", 44), T.white)
        self.text(p, QRectF(sp.left() + 230 * s, sp.top() + 18 * s, 300 * s, 44 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "機体情報", self.f("jp", 26), T.accent)
        p.setPen(QPen(alpha(T.accent, 70), 2 * s))
        p.drawLine(QPointF(sp.left() + 548 * s, sp.top() + 84 * s),
                   QPointF(sp.left() + 548 * s, sp.bottom() - 30 * s))
        p.end()
        return pm

    def draw_clock(self, p, r):
        s = self.height() / 1440
        now = datetime.datetime.now()
        top = QRectF(r.left(), r.top(), r.width(), 110 * s)
        self.text(p, top, Qt.AlignRight | Qt.AlignVCenter, "88:88", self.f("seg", 92), alpha(T.accent, 22))
        self.text(p, top, Qt.AlignRight | Qt.AlignVCenter, now.strftime("%H:%M"), self.f("seg", 92), T.accent)
        date = f"{DIAS[now.weekday()]} {now.day:02d} {MESES[now.month - 1]} {now.year}"
        bottom = QRectF(r.left(), r.top() + 112 * s, r.width(), 48 * s)
        self.text(p, bottom, Qt.AlignRight | Qt.AlignVCenter, date, self.f("title", 40), T.white)
        fm_w = p.fontMetrics().horizontalAdvance(date)
        self.text(p, bottom.adjusted(0, 0, -fm_w - 20 * s, 0), Qt.AlignRight | Qt.AlignVCenter,
                  DIAS_JP[now.weekday()], self.f("jp", 30), T.accent)

    def draw_hero(self, p, r):
        s = self.height() / 1440
        src = self.fpsrc
        live = src.fps is not None
        game = self.steam_game or src.name   # nome da biblioteca da Steam quando houver
        running = game is not None

        # selo de estado
        col = T.green if running else T.accent
        tag = QRectF(r.right() - 360 * s, r.top() + 34 * s, 320 * s, 76 * s)
        p.setPen(QPen(col, 2 * s))
        p.setBrush(alpha(col, 40))
        p.drawPolygon(self.cut_panel(tag, 14 * s))
        self.text(p, tag.adjusted(18 * s, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter,
                  "稼働中" if running else "待機中", self.f("jp", 36), col)
        self.text(p, tag.adjusted(0, 0, -18 * s, 0), Qt.AlignRight | Qt.AlignVCenter,
                  "ACTIVE" if running else "STANDBY", self.f("title", 40), T.white)

        # número grande em 7 segmentos
        num_rect = QRectF(r.left() + 40 * s, r.top() + 130 * s, r.width() - 330 * s, 390 * s)
        fps_txt = f"{src.fps:.0f}" if live else "---"
        ghost = "8" * max(3, len(fps_txt))
        fcol = T.accent
        if live and src.fps < 30:
            fcol = T.red
        elif live and src.fps < 50:
            fcol = T.amber
        self.text(p, num_rect, Qt.AlignRight | Qt.AlignVCenter, ghost, self.f("seg", 330), alpha(T.accent, 18))
        self.text(p, num_rect, Qt.AlignRight | Qt.AlignVCenter, fps_txt, self.f("seg", 330), fcol)
        self.text(p, QRectF(r.right() - 280 * s, r.top() + 350 * s, 240 * s, 140 * s),
                  Qt.AlignLeft | Qt.AlignBottom, "FPS", self.f("title", 110), alpha(T.white, 220))

        # rodapé: nome do jogo + estatísticas
        foot = QRectF(r.left() + 44 * s, r.top() + 545 * s, 760 * s, 80 * s)
        if live:
            self.elided(p, foot, Qt.AlignLeft | Qt.AlignVCenter, game, self.f("title", 58), T.white)
        elif running:
            # jogo aberto mas sem log do MangoHud (ex.: Steam aberta antes do wrapper)
            self.elided(p, QRectF(foot.left(), foot.top() - 6 * s, foot.width(), 56 * s),
                        Qt.AlignLeft | Qt.AlignVCenter, game, self.f("title", 50), T.white)
            self.text(p, QRectF(foot.left(), foot.top() + 46 * s, 1200 * s, 34 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, "SEM DADOS DE FPS  ·  MANGOHUD NÃO CARREGOU NESTE JOGO",
                      self.f("title", 24), T.amber)
            return
        else:
            self.text(p, foot, Qt.AlignLeft | Qt.AlignVCenter, "NO SIGNAL", self.f("title", 58), alpha(T.white, 120))
            self.text(p, foot.adjusted(250 * s, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter,
                      "ゲーム未検出", self.f("jp", 32), alpha(T.accent, 150))
        rec = src.recent
        stats = [("平均", "AVG", f"{sum(rec) / len(rec):.0f}" if rec else "--"),
                 ("最低", "MIN", f"{min(rec):.0f}" if rec else "--"),
                 ("時間", "MS", f"{src.frametime:.1f}" if live else "--")]
        x = r.right() - 560 * s
        for jp, en, val in stats:
            col_r = QRectF(x, r.top() + 545 * s, 170 * s, 80 * s)
            self.text(p, QRectF(col_r.left(), col_r.top(), col_r.width(), 30 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, f"{jp} {en}", self.f("jp", 20), T.dim)
            self.text(p, QRectF(col_r.left(), col_r.top() + 28 * s, col_r.width(), 56 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, val, self.f("seg", 40), T.accent)
            x += 180 * s

    def seg_bar(self, p, r, pct, col, heat=False, n=16):
        s = self.height() / 1440
        gap = 5 * s
        w = (r.width() - gap * (n - 1)) / n
        filled = pct / 100 * n
        p.setPen(Qt.NoPen)
        k = 4 * s
        for i in range(n):
            x = r.left() + i * (w + gap)
            seg_col = col
            if heat:
                seg_col = T.green if i < n * 0.6 else T.amber if i < n * 0.8 else T.red
            if i + 1 <= filled:
                a = 230
            elif i < filled:
                a = int(40 + 190 * (filled - i))
            else:
                a = 28
            p.setBrush(alpha(seg_col, a))
            p.drawPolygon(QPolygonF([QPointF(x + k, r.top()), QPointF(x + w, r.top()),
                                     QPointF(x + w - k, r.bottom()), QPointF(x, r.bottom())]))

    def draw_magi(self, p, r):
        s = self.height() / 1440
        d = self.sensors.data
        rows = [
            ("MELCHIOR", "1", "CPU", T.purple, status(d["cpu_temp"], 75, 88),
             [("負荷", "LOAD", f"{d['cpu']:.0f}%"),
              ("温度", "TEMP", f"{d['cpu_temp']:.0f}°" if d["cpu_temp"] else "--")]),
            ("BALTHASAR", "2", f"GPU · {d['gpu_w']:.0f}W" if d["gpu_w"] is not None else "GPU",
             T.green, status(d["gpu_temp"], 85, 100),
             [("負荷", "LOAD", f"{d['gpu']:.0f}%"),
              ("温度", "HOT", f"{d['gpu_temp']:.0f}°" if d["gpu_temp"] else "--")]),
            ("CASPER", "3", "MEMORY", T.accent, status(max(d["vram"], d["ram"]), 85, 95),
             [("映像", "VRAM", d["vram_txt"]),
              ("主記", "RAM", d["ram_txt"])]),
        ]
        self.text(p, QRectF(r.left() + 290 * s, r.top() + 26 * s, 400 * s, 44 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "CLIQUE PARA DETALHES", self.f("title", 22), T.dim)
        for i, (name, num, sub, col, (st_jp, st_en, st_col), bars) in enumerate(rows):
            top = r.top() + (84 + i * 186) * s
            tag = QRectF(r.left() + 34 * s, top, 250 * s, 166 * s)
            selected = self.detail == self.DETAIL_KINDS[i]
            p.setPen(QPen(alpha(col, 255 if selected else 200), (4 if selected else 2) * s))
            p.setBrush(alpha(col, 80 if selected else 22))
            p.drawPolygon(self.cut_panel(tag, 22 * s))
            if selected:   # seta apontando pro painel de detalhes
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                cy = tag.center().y()
                p.drawPolygon(QPolygonF([QPointF(tag.left() - 8 * s, cy - 18 * s),
                                         QPointF(tag.left() - 8 * s, cy + 18 * s),
                                         QPointF(tag.left() - 26 * s, cy)]))
            self.text(p, QRectF(tag.left() + 20 * s, tag.top() + 14 * s, tag.width(), 60 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, name, self.f("title", 50), T.white)
            self.text(p, QRectF(tag.left() + 20 * s, tag.top() + 68 * s, tag.width(), 40 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, f"MAGI·{num}", self.f("title", 30), col)
            self.text(p, QRectF(tag.left() + 20 * s, tag.top() + 108 * s, tag.width(), 40 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, sub, self.f("title", 30), alpha(T.white, 190))

            for j, (jp, en, val) in enumerate(bars):
                y = top + (14 + j * 82) * s
                self.text(p, QRectF(r.left() + 304 * s, y, 90 * s, 34 * s),
                          Qt.AlignLeft | Qt.AlignVCenter, jp, self.f("jp", 24), col)
                self.text(p, QRectF(r.left() + 304 * s, y + 32 * s, 90 * s, 30 * s),
                          Qt.AlignLeft | Qt.AlignVCenter, en, self.f("title", 22), T.dim)
                self.text(p, QRectF(r.left() + 740 * s, y, 104 * s, 66 * s),
                          Qt.AlignRight | Qt.AlignVCenter, val,
                          self.f("title", 30 if "/" in val else 44), T.white)

            badge = QRectF(r.right() - 130 * s, top + 22 * s, 100 * s, 122 * s)
            p.setPen(Qt.NoPen)
            p.setBrush(st_col)
            p.drawPolygon(self.cut_panel(badge, 14 * s))
            self.text(p, badge.adjusted(0, 10 * s, 0, -40 * s), Qt.AlignCenter,
                      st_jp, self.f("jp", 34), T.ink)
            self.text(p, badge.adjusted(0, 70 * s, 0, -8 * s), Qt.AlignCenter,
                      st_en, self.f("title", 20), T.ink)

    def draw_detail(self, p, r):
        s = self.height() / 1440
        kind = self.detail
        name, num, col, sub = {
            "cpu": ("MELCHIOR", "1", T.purple, "CPU · CONSUMO POR APLICATIVO (% DA CPU TOTAL)"),
            "gpu": ("BALTHASAR", "2", T.green, "GPU · USO DO PROCESSADOR GRÁFICO POR APLICATIVO"),
            "mem": ("CASPER", "3", T.accent, "MEMÓRIA · RAM (PSS) E VRAM POR APLICATIVO"),
        }[kind]
        p.setPen(QPen(col, 3 * s))
        p.setBrush(T.bg_top)
        p.drawPolygon(self.cut_panel(r, 34 * s))
        p.setBrush(alpha(col, 16))
        p.drawPolygon(self.cut_panel(r, 34 * s))

        title = f"{name}·{num}"
        self.text(p, QRectF(r.left() + 44 * s, r.top() + 22 * s, 700 * s, 70 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, title, self.f("title", 64), T.white)
        tw = p.fontMetrics().horizontalAdvance(title)
        self.text(p, QRectF(r.left() + 66 * s + tw, r.top() + 30 * s, 400 * s, 60 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "詳細解析", self.f("jp", 34), col)
        self.text(p, QRectF(r.left() + 46 * s, r.top() + 92 * s, 1000 * s, 36 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, sub, self.f("title", 28), T.dim)
        tag = QRectF(r.right() - 300 * s, r.top() + 34 * s, 260 * s, 60 * s)
        p.setPen(QPen(alpha(col, 160), 2 * s))
        p.setBrush(alpha(col, 24))
        p.drawPolygon(self.cut_panel(tag, 12 * s))
        self.text(p, tag.adjusted(16 * s, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, "閉じる", self.f("jp", 26), col)
        self.text(p, tag.adjusted(0, 0, -16 * s, 0), Qt.AlignRight | Qt.AlignVCenter,
                  "✕ FECHAR", self.f("title", 30), T.white)

        rows = self.detail_rows
        if not rows:
            self.text(p, QRectF(r.left(), r.top() + 150 * s, r.width(), 440 * s), Qt.AlignCenter,
                      "解析中  ·  ANALISANDO", self.f("title", 48), alpha(col, 200))
            return
        if kind == "mem":
            scale = max(rows[0][1], 2.0)
        else:
            scale = max(rows[0][1], 10.0)
        for i, (app, val, extra_txt) in enumerate(rows):
            y = r.top() + (150 + i * 58) * s
            row_r = QRectF(r.left() + 40 * s, y, r.width() - 80 * s, 50 * s)
            if i % 2 == 0:
                p.setPen(Qt.NoPen)
                p.setBrush(alpha(col, 10))
                p.drawRect(row_r)
            self.text(p, QRectF(r.left() + 52 * s, y, 60 * s, 50 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, f"{i + 1:02d}", self.f("seg", 24), col)
            self.elided(p, QRectF(r.left() + 120 * s, y, 430 * s, 50 * s),
                        Qt.AlignLeft | Qt.AlignVCenter, app, self.f("title", 38), T.white)
            self.seg_bar(p, QRectF(r.left() + 570 * s, y + 12 * s, 400 * s, 26 * s),
                         min(100.0, 100.0 * val / scale), col, n=20)
            self.text(p, QRectF(r.left() + 980 * s, y, 200 * s, 50 * s),
                      Qt.AlignRight | Qt.AlignVCenter, extra_txt, self.f("title", 24), T.dim)
            main = f"{val:.1f} GB" if kind == "mem" else f"{val:.1f}%"
            self.text(p, QRectF(r.left() + 1190 * s, y, 156 * s, 50 * s),
                      Qt.AlignRight | Qt.AlignVCenter, main, self.f("title", 40), T.white)

    def draw_graph(self, p, r):
        s = self.height() / 1440
        live = self.graph_live()
        title = "FRAME RATE HISTORY" if live else "LOAD HISTORY"
        self.text(p, QRectF(r.left() + 44 * s, r.top() + 14 * s, 900 * s, 50 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, title, self.f("title", 44), T.white)
        tw = p.fontMetrics().horizontalAdvance(title)
        self.text(p, QRectF(r.left() + 64 * s + tw, r.top() + 18 * s, 400 * s, 44 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "推移記録", self.f("jp", 26), T.accent)

        series = [("CPU", T.purple), ("GPU", T.green)] + ([("FPS", T.accent)] if live else [])
        lx = r.right() - 44 * s
        for label, col in reversed(series):
            lx -= 110 * s
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRect(QRectF(lx, r.top() + 32 * s, 22 * s, 14 * s))
            self.text(p, QRectF(lx + 30 * s, r.top() + 16 * s, 80 * s, 46 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, label, self.f("title", 30), T.white)
        if live:
            self.text(p, QRectF(lx - 230 * s, r.top() + 16 * s, 210 * s, 46 * s),
                      Qt.AlignRight | Qt.AlignVCenter, f"ESCALA {self.fps_scale:.0f}",
                      self.f("title", 26), T.dim)

    def draw_spec(self, p, r):
        s = self.height() / 1440
        # botão de sincronia com o RGB da placa-mãe (clique alterna)
        btn = self.r_sync()
        p.setPen(QPen(alpha(T.accent, 150 if self.rgb_sync else 70), 1.5 * s))
        p.setBrush(alpha(T.accent, 26 if self.rgb_sync else 6))
        p.drawPolygon(self.cut_panel(btn, 12 * s))
        sync = btn.adjusted(14 * s, 5 * s, -14 * s, -5 * s)
        if not self.rgb_sync:
            label, sw = "RGB SYNC OFF", None
        elif not self.rgb_online:
            label, sw = "RGB OFFLINE", None
        elif T.off:
            label, sw = "LED 消灯 OFF", None
        else:
            label, sw = "RGB SYNC", T.raw
        self.text(p, sync.adjusted(0, 0, -60 * s, 0), Qt.AlignRight | Qt.AlignVCenter,
                  label, self.f("title", 26), T.dim)
        p.setPen(QPen(T.dim, 2 * s))
        p.setBrush(sw if sw is not None else Qt.NoBrush)
        p.drawRect(QRectF(sync.right() - 44 * s, sync.top() + 10 * s, 44 * s, 22 * s))

        # especificações
        y = r.top() + 88 * s
        for key, val in self.spec[:6]:
            self.text(p, QRectF(r.left() + 44 * s, y, 90 * s, 44 * s),
                      Qt.AlignLeft | Qt.AlignVCenter, key, self.f("title", 26), T.accent)
            self.elided(p, QRectF(r.left() + 130 * s, y, 400 * s, 44 * s),
                        Qt.AlignLeft | Qt.AlignVCenter, val, self.f("title", 30), T.white)
            y += 47 * s

        # controles = pilotos
        x0 = r.left() + 574 * s
        w = r.right() - 40 * s - x0
        self.text(p, QRectF(x0, r.top() + 84 * s, 200 * s, 44 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "PILOTS", self.f("title", 32), T.white)
        self.text(p, QRectF(x0 + 104 * s, r.top() + 88 * s, 200 * s, 40 * s),
                  Qt.AlignLeft | Qt.AlignVCenter, "操縦者", self.f("jp", 22), T.accent)
        for i in range(4):
            slot = QRectF(x0, r.top() + (138 + i * 58) * s, w, 50 * s)
            pad = self.pads[i] if i < len(self.pads) else None
            col = T.accent if pad else alpha(T.dim, 60)
            p.setPen(QPen(alpha(col, 160), 1.5 * s))
            p.setBrush(alpha(col, 24 if pad else 6))
            p.drawPolygon(self.cut_panel(slot, 12 * s))
            self.text(p, QRectF(slot.left() + 12 * s, slot.top(), 50 * s, slot.height()),
                      Qt.AlignLeft | Qt.AlignVCenter, f"{i + 1:02d}", self.f("seg", 20), col)
            name_r = QRectF(slot.left() + 62 * s, slot.top(), w - 140 * s, slot.height())
            if pad is None:
                self.text(p, name_r, Qt.AlignLeft | Qt.AlignVCenter, "未接続  —  EMPTY",
                          self.f("jp", 18), alpha(T.dim, 90))
                continue
            label, bat, conn, charging = pad
            p.setFont(self.f("title", 28))
            label_w = min(p.fontMetrics().horizontalAdvance(label), name_r.width() - 50 * s)
            self.elided(p, name_r, Qt.AlignLeft | Qt.AlignVCenter, label, self.f("title", 28), T.white)
            if conn:
                self.text(p, QRectF(name_r.left() + label_w + 10 * s, slot.top(), 60 * s, slot.height()),
                          Qt.AlignLeft | Qt.AlignVCenter, conn, self.f("title", 20), T.dim)
            if bat:
                b = int(bat)
                bcol = T.red if b <= 15 else T.amber if b <= 35 else T.green
                self.text(p, QRectF(slot.right() - 110 * s, slot.top(), 96 * s, slot.height()),
                          Qt.AlignRight | Qt.AlignVCenter, f"{'⚡' if charging else ''}{b}%",
                          self.f("title", 28), bcol)


def main():
    if "--restore" in sys.argv:
        app = QCoreApplication(sys.argv)
        restore_wallpapers()
        return
    if "--toggle-rgb" in sys.argv:
        settings = load_settings()
        settings["rgb_sync"] = not settings.get("rgb_sync", True)
        save_settings(settings)
        print("RGB Sync", "ligado" if settings["rgb_sync"] else "desligado")
        return
    if "--install-icons" in sys.argv:
        app = QGuiApplication(sys.argv)
        install_icons()
        return

    QGuiApplication.setDesktopFileName("gamerhud")
    app = QApplication(sys.argv)
    app.setApplicationName("gamerhud")
    fonts = {"seg": "Hack"}
    fid = QFontDatabase.addApplicationFont(os.path.join(HERE, "DSEG7Classic-Bold.ttf"))
    if fid >= 0:
        fonts["seg"] = QFontDatabase.applicationFontFamilies(fid)[0]

    lock = single_instance()
    if lock is None:
        print("gamerhud: já tem um HUD aberto", file=sys.stderr)
        return
    # sinais, aboutToQuit, closeEvent e atexit: todos restauram o wallpaper (uma vez só)
    guard = WallpaperGuard(app)
    guard.install()
    wake = QTimer(timeout=lambda: None)
    wake.start(250)   # deixa o Python processar sinais durante o loop do Qt

    screens = app.screens()
    screen = next((sc for sc in screens if sc.name() == TARGET_SCREEN), None)
    if screen is None:
        screen = next((sc for sc in screens if sc != app.primaryScreen()), app.primaryScreen())

    w = HUD(fonts)
    guard.window = w
    w.on_close = guard.finish
    prepare_wallpapers()   # antes de mostrar o HUD, pro print pegar o wallpaper limpo
    w.setScreen(screen)
    w.setGeometry(screen.geometry())
    w.showFullScreen()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
