"""U5: o papel de parede sempre volta. Plasma, KWin e appletsrc falsos; nada toca na sessão real."""

import importlib.util
import json
import os
import re
import signal
from pathlib import Path

import gamerhud
import pytest

HUD_DIR = Path(__file__).resolve().parents[2] / "hud"
WE = gamerhud.WE_PLUGIN


class FakePlasma:
    """Interpreta os poucos scripts que o gamerhud manda pro evaluateScript."""

    def __init__(self, stills, alive=True):
        self.stills = str(stills)
        self.alive = alive
        self.calls = 0
        # id: plugin, cena, imagem, PauseMode, filtro, geometria
        self.desk = {
            "1": {"plugin": WE, "scene": "111", "image": "", "pause": 1, "flt": True,
                  "geo": (0, 0, 2560, 1440)},
            "2": {"plugin": WE, "scene": "222", "image": "", "pause": 1, "flt": True,
                  "geo": (2560, 0, 1920, 1080)},
        }

    def stick(self):
        """Estado do bug: telas presas em fotos do cache, sem wallpaper_state.json."""
        for d in self.desk.values():
            d["plugin"], d["image"] = "org.kde.image", f"file://{self.stills}/{d['scene']}_x.jpg"

    def __call__(self, script):
        self.calls += 1
        if not self.alive:
            return None
        if "WallpaperWorkShopId" in script:
            return ";".join(",".join([k, d["plugin"], d["scene"], *map(str, d["geo"])])
                            for k, d in self.desk.items())
        if "indexOf(st)" in script:
            st = json.loads(re.search(r"var st=(\".*?\"),n=0", script).group(1))
            n = 0
            for d in self.desk.values():
                if d["plugin"] == "org.kde.image" and st in d["image"]:
                    d["plugin"], n = WE, n + 1
            return f"ok {n}"
        if "writeConfig('Image'" in script:
            for did, path in self._obj(script).items():
                self.desk[did].update(plugin="org.kde.image", image="file://" + path)
            return ""
        if "readConfig('PauseMode')" in script:
            return ";".join(f"{k}={d['pause']},{'true' if d['flt'] else 'false'}"
                            for k, d in self.desk.items() if d["plugin"] == WE)
        if "writeConfig('PauseMode'" in script:
            for did, (mode, flt) in self._obj(script).items():
                if self.desk[did]["plugin"] == WE:
                    self.desk[did].update(pause=mode, flt=flt)
            return "ok"
        raise AssertionError(script)

    @staticmethod
    def _obj(script):
        return json.loads(re.search(r"var s=(\{.*?\});desktops", script).group(1))

    def plugins(self):
        return [d["plugin"] for d in self.desk.values()]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(gamerhud, "CACHE", str(cache))
    monkeypatch.setattr(gamerhud, "WP_STATE", str(cache / "wallpaper_state.json"))
    plasma = FakePlasma(cache / "stills")
    monkeypatch.setattr(gamerhud, "plasma_eval", plasma)
    monkeypatch.setattr(gamerhud, "kwin_script", lambda js, name: True)
    monkeypatch.setattr(gamerhud, "load_settings", lambda: {"wallpaper": "still"})
    monkeypatch.setattr(gamerhud, "wallpaper_disabled", lambda: False)
    (cache / "stills").mkdir(parents=True)
    for scene, w, h in (("111", 2560, 1440), ("222", 1920, 1080)):   # prints em cache: sem spectacle
        (cache / "stills" / f"{scene}_{w}x{h}.jpg").write_bytes(b"jpg")
    return plasma


def state():
    try:
        return json.loads(Path(gamerhud.WP_STATE).read_text())
    except OSError:
        return None


def test_restaura_plugin_sem_arquivo_de_estado(fake):
    fake.stick()
    assert state() is None
    assert gamerhud.restore_wallpapers() is True
    assert fake.plugins() == [WE, WE]


def test_still_e_volta(fake):
    gamerhud.prepare_wallpapers()
    assert fake.plugins() == ["org.kde.image"] * 2
    assert state()["mode"] == "still"
    gamerhud.restore_wallpapers()
    assert fake.plugins() == [WE, WE]
    assert state() is None


def test_abrir_duas_vezes_nao_sobrescreve_o_estado(fake):
    gamerhud.prepare_wallpapers()
    first = Path(gamerhud.WP_STATE).read_text()
    gamerhud.prepare_wallpapers()
    assert Path(gamerhud.WP_STATE).read_text() == first
    assert gamerhud._write_state({"mode": "pause", "desktops": {}}) is False
    assert Path(gamerhud.WP_STATE).read_text() == first


def test_abrir_com_prints_presos_nao_grava_a_foto_como_original(fake, monkeypatch):
    monkeypatch.setattr(gamerhud, "load_settings", lambda: {"wallpaper": "pause"})
    fake.stick()   # sobra de uma sessão que perdeu o estado
    gamerhud.prepare_wallpapers()
    assert fake.plugins() == [WE, WE]                 # os prints saíram antes de gravar
    assert state() == {"mode": "pause", "desktops": {"1": [1, True], "2": [1, True]}}
    assert [d["pause"] for d in fake.desk.values()] == [5, 5]
    gamerhud.restore_wallpapers()
    assert [(d["pause"], d["flt"]) for d in fake.desk.values()] == [(1, True), (1, True)]
    assert state() is None


def test_plasma_fora_do_ar_nao_apaga_o_estado(fake):
    gamerhud.prepare_wallpapers()
    fake.alive = False
    assert gamerhud.restore_wallpapers() is False
    assert state()["mode"] == "still"                 # fica pra rede de segurança
    fake.alive = True
    assert gamerhud.restore_wallpapers() is True
    assert fake.plugins() == [WE, WE] and state() is None


def test_offscreen_nao_chama_plasma_nem_kwin(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("D-Bus real tocado")
    monkeypatch.setattr(gamerhud, "QDBusInterface", boom)
    monkeypatch.setenv("GAMERHUD_NO_WALLPAPER", "1")
    assert gamerhud.wallpaper_disabled()
    assert gamerhud.plasma_eval("print(1)") is None
    assert gamerhud.kwin_script("1", "x") is False
    gamerhud.prepare_wallpapers()
    monkeypatch.delenv("GAMERHUD_NO_WALLPAPER")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert gamerhud.wallpaper_disabled()


def test_ferramenta_offscreen_desliga_o_wallpaper(monkeypatch):
    for name in ("load_settings", "save_settings", "settings_mtime", "prepare_wallpapers",
                 "still_wallpapers", "pause_wallpapers", "restore_wallpapers"):
        monkeypatch.setattr(gamerhud, name, getattr(gamerhud, name))   # desfaz o que a ferramenta trocar
    calls = []
    monkeypatch.setattr(gamerhud, "plasma_eval", lambda s: calls.append(s))
    monkeypatch.setattr(gamerhud, "kwin_script", lambda *a: calls.append(a))

    class DummyHUD:
        def __init__(self, *a, **k):
            gamerhud.prepare_wallpapers()

        def resize(self, *a):
            pass

        def show(self):
            pass

    monkeypatch.setattr(gamerhud, "HUD", DummyHUD)
    spec = importlib.util.spec_from_file_location("wired_hud_u5", HUD_DIR / "tools" / "wired_hud.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    assert os.environ["GAMERHUD_NO_WALLPAPER"] == "1"
    tool.make_hud()
    gamerhud.restore_wallpapers()
    gamerhud.still_wallpapers()
    assert calls == []


# ---------------------------------------------------------------- vigia
@pytest.fixture
def watch(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("gamerhud_watch_u5", HUD_DIR / "gamerhud-watch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stills = tmp_path / "cache" / "stills"
    monkeypatch.setattr(mod, "STILLS", str(stills))
    monkeypatch.setattr(mod, "APPLETSRC", str(tmp_path / "appletsrc"))
    runs = []
    monkeypatch.setattr(mod.subprocess, "run", lambda args, **k: runs.append(args))
    mod.runs = runs
    return mod


def appletsrc(path, plugin, image):
    path.write_text(
        "[Containments][1]\nactivityId=x\nformfactor=0\nplugin=org.kde.plasma.folder\n"
        f"wallpaperplugin={plugin}\n\n"
        f"[Containments][1][Wallpaper][org.kde.image][General]\nFillMode=2\nImage={image}\n\n"
        f"[Containments][1][Wallpaper][{WE}][General]\nWallpaperWorkShopId=111\n\n"
        "[Containments][2]\nwallpaperplugin=org.kde.image\n\n"
        "[Containments][2][Wallpaper][org.kde.image][General]\nImage=file:///home/x/foto.jpg\n")


def test_vigia_restaura_quando_o_hud_nao_esta_rodando(watch, monkeypatch):
    appletsrc(Path(watch.APPLETSRC), "org.kde.image", f"file://{watch.STILLS}/111_2560x1440.jpg")
    assert watch.stuck_stills() == ["1"]               # a foto pessoal da tela 2 não conta
    monkeypatch.setattr(watch, "hud_pid", lambda: None)
    assert watch.rescue_wallpaper() is True
    assert watch.runs == [["python3", watch.HUD, "--restore"]]


def test_vigia_nao_mexe_com_hud_aberto_ou_sem_prints(watch, monkeypatch):
    appletsrc(Path(watch.APPLETSRC), "org.kde.image", f"file://{watch.STILLS}/111_2560x1440.jpg")
    monkeypatch.setattr(watch, "hud_pid", lambda: 4242)
    assert watch.rescue_wallpaper() is False
    monkeypatch.setattr(watch, "hud_pid", lambda: None)
    appletsrc(Path(watch.APPLETSRC), WE, f"file://{watch.STILLS}/111_2560x1440.jpg")
    assert watch.rescue_wallpaper() is False
    Path(watch.APPLETSRC).unlink()
    assert watch.rescue_wallpaper() is False
    assert watch.runs == []


# ---------------------------------------------------------------- sinais
@pytest.fixture
def guard_env(monkeypatch):
    restored = []
    monkeypatch.setattr(gamerhud, "restore_wallpapers", lambda: restored.append(1))
    monkeypatch.setattr("atexit.register", lambda f: None)
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    yield restored
    for s, h in saved.items():
        signal.signal(s, h)


def test_sigterm_restaura_antes_do_loop(guard_env):
    g = gamerhud.WallpaperGuard()
    g.install()
    with pytest.raises(SystemExit):
        os.kill(os.getpid(), signal.SIGTERM)
        for _ in range(1000):   # o handler roda no próximo bytecode da thread principal
            pass
    assert guard_env == [1]
    g.finish()                  # aboutToQuit/closeEvent/atexit depois: não restaura de novo
    assert guard_env == [1]


def test_sigterm_no_loop_esconde_restaura_e_sai(guard_env):
    events = []

    class App:
        def quit(self):
            events.append("quit")

        def processEvents(self):
            events.append("events")

    class Win:
        def hide(self):
            events.append("hide")

    g = gamerhud.WallpaperGuard(window=Win())
    g.app, g.in_loop = App(), True
    signal.signal(signal.SIGTERM, g.on_signal)
    os.kill(os.getpid(), signal.SIGTERM)
    for _ in range(1000):
        pass
    assert guard_env == [1]
    assert events == ["hide", "events", "quit"]

