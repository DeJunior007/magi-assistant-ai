"""Dados novos da interface "wired" (U2, R23.2/R23.3/R23.5).

Roda com o Python do sistema: só PySide6 + stdlib. Nada aqui bloqueia a thread de pintura:
leituras de `/proc` são curtas e o Spotify (MPRIS) e as capas vão para threads.

O PySide6 não consegue desmontar `a{sv}` (`QDBusArgument` sai como `None`/derruba o processo),
então os metadados do MPRIS são lidos com `busctl --json` numa thread; o QtDBus fica com o que
funciona nele: saber se o nome existe e mandar os comandos (Previous/PlayPause/Next).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass

BUS_NAME = "org.mpris.MediaPlayer2.spotify"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"

COVER_DIR = os.path.expanduser("~/.cache/gamerhud/covers")
COVER_LIMIT = 50

VIRTUAL_PREFIXES = ("lo", "veth", "docker", "br-", "virbr", "vnet", "tun", "tap", "wg", "zt",
                    "tailscale", "vmnet", "vboxnet", "lxc", "lxdbr", "podman", "cni", "flannel")


def fmt_rate(bps: float | None) -> str:
    """Bytes/s → texto curto ("– –" sem dado)."""
    if bps is None:
        return "– –"
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1000 or unit == "GB/s":
            return f"{bps:.0f} {unit}" if unit == "B/s" else f"{bps:.1f} {unit}"
        bps /= 1000
    return "– –"  # inalcançável


# ---------------------------------------------------------------- rede


class NetRate:
    """↓/↑ em bytes/s somando as interfaces físicas de `/proc/net/dev`."""

    def __init__(self, path: str = "/proc/net/dev", sys_net: str | None = "/sys/class/net",
                 maxlen: int = 60):
        self.path = path
        self.sys_net = sys_net
        self.down: float | None = None
        self.up: float | None = None
        self.down_series: deque[float] = deque(maxlen=maxlen)
        self.up_series: deque[float] = deque(maxlen=maxlen)
        self._prev: tuple[float, int, int] | None = None

    def physical(self, name: str) -> bool:
        if name.startswith(VIRTUAL_PREFIXES):
            return False
        if self.sys_net:
            node = os.path.join(self.sys_net, name)
            if os.path.isdir(node) and not os.path.exists(os.path.join(node, "device")):
                return False
        return True

    def _read(self) -> tuple[int, int] | None:
        try:
            with open(self.path) as f:
                lines = f.read().splitlines()[2:]
        except OSError:
            return None
        rx = tx = 0
        for line in lines:
            name, _, rest = line.partition(":")
            name = name.strip()
            cols = rest.split()
            if len(cols) < 9 or not self.physical(name):
                continue
            try:
                rx += int(cols[0])
                tx += int(cols[8])
            except ValueError:
                continue
        return rx, tx

    def poll(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        cur = self._read()
        if cur is None:
            self.down = self.up = None
            self._prev = None
            return
        prev, self._prev = self._prev, (now, *cur)
        if prev is None or now <= prev[0]:
            return
        dt = now - prev[0]
        # contador zerado (interface reiniciada) → 0 em vez de taxa negativa
        self.down = max(0, cur[0] - prev[1]) / dt
        self.up = max(0, cur[1] - prev[2]) / dt
        self.down_series.append(self.down)
        self.up_series.append(self.up)


# ---------------------------------------------------------------- histórico de carga


class LoadHistory:
    """CPU/GPU/RAM dos últimos 60 min: um ponto a cada 30 s (média das leituras do intervalo)."""

    INTERVAL = 30.0
    SIZE = 120

    def __init__(self, interval: float = INTERVAL, size: int = SIZE):
        self.interval = interval
        self.points: deque[tuple[float, float | None, float | None, float | None]] = deque(maxlen=size)
        self._acc: list[list[float]] = [[], [], []]
        self._last: float | None = None

    def push(self, cpu: float | None, gpu: float | None, ram: float | None, now: float) -> bool:
        """Acumula uma leitura (`now` = time.time()); devolve True quando gravou um ponto."""
        for acc, v in zip(self._acc, (cpu, gpu, ram), strict=True):
            if v is not None:
                acc.append(float(v))
        if self._last is not None and now - self._last < self.interval:
            return False
        avg = [sum(a) / len(a) if a else None for a in self._acc]
        self.points.append((now, avg[0], avg[1], avg[2]))
        self._acc = [[], [], []]
        self._last = now
        return True

    def series(self, key: str) -> list[float | None]:
        idx = {"cpu": 1, "gpu": 2, "ram": 3}[key]
        return [p[idx] for p in self.points]

    def times(self) -> list[float]:
        return [p[0] for p in self.points]

    def axis(self, n: int = 5) -> list[tuple[float, str]]:
        """Rótulos do eixo X: (posição 0..1 na janela de 60 min, "HH:MM"); a direita é o ponto mais novo."""
        if not self.points:
            return []
        end = self.points[-1][0]
        span = self.interval * (self.points.maxlen - 1)
        out = []
        for i in range(n):
            frac = i / (n - 1) if n > 1 else 1.0
            out.append((frac, time.strftime("%H:%M", time.localtime(end - span * (1 - frac)))))
        return out


# ---------------------------------------------------------------- FPS


@dataclass(frozen=True)
class FpsSnapshot:
    current: float
    min: float
    avg: float
    max: float
    series: list[float]


class FpsStats:
    """Janela deslizante de FPS; `push(None, now)` (sem jogo) zera."""

    def __init__(self, window: float = 60.0):
        self.window = window
        self._data: deque[tuple[float, float]] = deque()

    def push(self, fps: float | None, now: float) -> None:
        if fps is None:
            self._data.clear()
            return
        self._data.append((now, float(fps)))
        while self._data and now - self._data[0][0] > self.window:
            self._data.popleft()

    def snapshot(self) -> FpsSnapshot | None:
        if not self._data:
            return None
        vals = [v for _, v in self._data]
        return FpsSnapshot(vals[-1], min(vals), sum(vals) / len(vals), max(vals), vals)


# ---------------------------------------------------------------- log do rodapé


class EventLog:
    def __init__(self, maxlen: int = 100):
        self.entries: deque[tuple[float, str]] = deque(maxlen=maxlen)

    def add(self, text: str, now: float | None = None) -> None:
        self.entries.append((time.time() if now is None else now, text))

    def ticker(self, n: int = 3) -> list[str]:
        """Últimas `n` linhas, da mais velha para a mais nova, como "[HH:MM:SS] texto"."""
        items = list(self.entries)[-n:] if n > 0 else []
        return [f"[{time.strftime('%H:%M:%S', time.localtime(t))}] {s}" for t, s in items]


# ---------------------------------------------------------------- capas


def normalize_art_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("https://open.spotify.com/image/"):  # Spotify antigo
        return "https://i.scdn.co/image/" + url.rsplit("/", 1)[-1]
    if url.startswith(("https://", "http://", "file://")):
        return url
    return None


class CoverCache:
    """Baixa capas numa thread para `dir` (nome = sha1 da URL), mantendo no máximo `limit` arquivos."""

    RETRY = 60.0

    def __init__(self, folder: str = COVER_DIR, limit: int = COVER_LIMIT, fetch=None,
                 threaded: bool = True):
        self.dir = folder
        self.limit = limit
        self.fetch = fetch or self._fetch
        self.threaded = threaded
        self._busy: set[str] = set()
        self._failed: dict[str, float] = {}
        self._touched: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def _fetch(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "gamerhud"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read(4 << 20)

    def file_for(self, url: str) -> str:
        return os.path.join(self.dir, hashlib.sha1(url.encode()).hexdigest() + ".img")

    def path_for(self, url: str | None) -> str | None:
        """Caminho local da capa se já estiver em cache; senão agenda o download e devolve None."""
        url = normalize_art_url(url)
        if not url:
            return None
        if url.startswith("file://"):
            p = url[7:]
            return p if os.path.isfile(p) else None
        path = self.file_for(url)
        if os.path.exists(path):
            if path not in self._touched:  # LRU barato: renova o mtime uma vez por sessão
                self._touched.add(path)
                try:
                    os.utime(path)
                except OSError:
                    pass
            return path
        with self._lock:
            if url in self._busy or time.monotonic() - self._failed.get(url, -1e9) < self.RETRY:
                return None
            self._busy.add(url)
        if self.threaded:
            threading.Thread(target=self._download, args=(url, path), daemon=True).start()
        else:
            self._download(url, path)
        return path if os.path.exists(path) else None

    def _download(self, url: str, path: str) -> None:
        try:
            data = self.fetch(url)
            if not data:
                raise OSError("capa vazia")
            os.makedirs(self.dir, exist_ok=True)
            tmp = f"{path}.{threading.get_ident()}.part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            self._touched.add(path)
            self._prune()
        except Exception:  # rede fora, 404, disco cheio: tenta de novo mais tarde
            with self._lock:
                self._failed[url] = time.monotonic()
        finally:
            with self._lock:
                self._busy.discard(url)

    def _prune(self) -> None:
        try:
            files = [e for e in os.scandir(self.dir) if e.name.endswith(".img")]
        except OSError:
            return
        if len(files) <= self.limit:
            return
        files.sort(key=lambda e: e.stat().st_mtime)
        for e in files[: len(files) - self.limit]:
            try:
                os.remove(e.path)
            except OSError:
                pass


# ---------------------------------------------------------------- Spotify (MPRIS)


class MprisBackend:
    """Acesso real ao MPRIS. `fetch()` bloqueia (chamar fora da thread de pintura); `call()` não."""

    def __init__(self, bus_name: str = BUS_NAME, timeout: float = 2.0):
        self.bus_name = bus_name
        self.timeout = timeout

    def _bus(self):
        from PySide6.QtDBus import QDBusConnection
        return QDBusConnection.sessionBus()

    def available(self) -> bool:
        try:
            bus = self._bus()
            return bool(bus.isConnected() and bus.interface().isServiceRegistered(self.bus_name).value())
        except Exception:
            return False

    def fetch(self) -> dict | None:
        """{"Metadata": {...}, "PlaybackStatus": str, "Position": int µs} ou None (player fechado)."""
        if not self.available():
            return None
        names = ("Metadata", "PlaybackStatus", "Position")
        try:
            out = subprocess.run(
                ["busctl", "--user", "--json=short", "get-property", self.bus_name, OBJECT_PATH,
                 PLAYER_IFACE, *names],
                capture_output=True, text=True, timeout=self.timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        res: dict = {}
        for name, line in zip(names, out.stdout.splitlines(), strict=False):
            try:
                res[name] = _plain(json.loads(line))
            except ValueError:
                return None
        return res

    def call(self, method: str) -> None:
        try:
            from PySide6.QtDBus import QDBusMessage
            msg = QDBusMessage.createMethodCall(self.bus_name, OBJECT_PATH, PLAYER_IFACE, method)
            self._bus().send(msg)  # sem esperar resposta
        except Exception:
            pass


def _plain(node):
    """JSON do busctl ({"type", "data"} aninhado) → valores Python simples."""
    if isinstance(node, dict) and set(node) == {"type", "data"}:
        node = node["data"]
    if isinstance(node, dict):
        return {k: _plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain(v) for v in node]
    return node


class NowPlaying:
    """Faixa atual do Spotify. Chame `tick()` ~1×/s na thread da GUI; a leitura real é a cada `poll` s
    numa thread, e a posição é interpolada localmente entre as leituras."""

    def __init__(self, backend=None, covers: CoverCache | None = None, poll: float = 3.0,
                 threaded: bool = True, clock=time.monotonic):
        self.backend = backend or MprisBackend()
        self.covers = covers or CoverCache()
        self.poll = poll
        self.threaded = threaded
        self.clock = clock
        self._lock = threading.Lock()
        self._pending: tuple[float, dict | None] | None = None
        self._busy = False
        self._next_req = -1e18
        self._pix_path: str | None = None
        self._pix = None
        self._img = None  # (caminho, QImage) decodificada na thread
        self._clear()

    def _clear(self) -> None:
        self.title = self.artist = self.album = self.year = self.art_url = None
        self.length: float | None = None  # segundos
        self.status: str | None = None  # "Playing" | "Paused" | "Stopped" | None (fechado)
        self._pos = 0.0
        self._pos_t = 0.0

    # -- leitura

    @property
    def active(self) -> bool:
        return self.status is not None and bool(self.title)

    def tick(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is not None:
            self._apply(*pending)
        if not self._busy and now >= self._next_req:
            self._busy = True
            self._next_req = now + self.poll
            if self.threaded:
                threading.Thread(target=self._worker, daemon=True).start()
            else:
                self._worker()
                self.tick(now)

    def _worker(self) -> None:
        try:
            res = self.backend.fetch()
        except Exception:
            res = None
        with self._lock:
            self._pending = (self.clock(), res)
            self._busy = False

    def _apply(self, t: float, res: dict | None) -> None:
        if not res:
            self._clear()
            return
        md = res.get("Metadata") or {}
        status = res.get("PlaybackStatus")
        self.status = status if status in ("Playing", "Paused", "Stopped") else "Stopped"
        self.title = md.get("xesam:title") or None
        artist = md.get("xesam:artist")
        self.artist = ", ".join(artist) if isinstance(artist, list) else (artist or None)
        self.album = md.get("xesam:album") or None
        created = str(md.get("xesam:contentCreated") or "")
        self.year = created[:4] if created[:4].isdigit() else None
        self.art_url = normalize_art_url(md.get("mpris:artUrl"))
        length = md.get("mpris:length")
        self.length = length / 1e6 if isinstance(length, int | float) and length > 0 else None
        pos = res.get("Position")
        self._pos = pos / 1e6 if isinstance(pos, int | float) and pos >= 0 else 0.0
        self._pos_t = t

    def position(self, now: float | None = None) -> float | None:
        """Posição em segundos, interpolada desde a última leitura enquanto toca."""
        if not self.active:
            return None
        now = self.clock() if now is None else now
        pos = self._pos + (max(0.0, now - self._pos_t) if self.status == "Playing" else 0.0)
        return min(pos, self.length) if self.length else pos

    # -- capa

    @property
    def cover_path(self) -> str | None:
        return self.covers.path_for(self.art_url) if self.active else None

    def cover_pixmap(self):
        """QPixmap da capa (memorizado por arquivo) ou None enquanto não houver.

        O JPEG é decodificado em QImage numa thread (custava ~15 ms na primeira vez); aqui só
        sai o `QPixmap.fromImage`, barato para 300×300."""
        path = self.cover_path
        if path != self._pix_path:
            self._pix_path, self._pix = path, None
            if path:
                if self.threaded:
                    threading.Thread(target=self._decode, args=(path,), daemon=True).start()
                else:
                    self._decode(path)
        if self._pix is None and path:
            with self._lock:
                ready = self._img if self._img and self._img[0] == path else None
            if ready:
                from PySide6.QtGui import QPixmap
                self._pix = QPixmap.fromImage(ready[1])
        return self._pix

    def _decode(self, path: str) -> None:
        from PySide6.QtGui import QImage
        img = QImage(path)
        with self._lock:
            self._img = None if img.isNull() else (path, img)

    # -- controles

    def _control(self, method: str) -> None:
        self.backend.call(method)
        self._next_req = min(self._next_req, self.clock() + 0.3)  # relê logo depois

    def previous(self) -> None:
        self._control("Previous")

    def next(self) -> None:
        self._control("Next")

    def play_pause(self) -> None:
        if self.active:  # resposta imediata na tela; a próxima leitura confirma
            now = self.clock()
            self._pos = self.position(now) or 0.0
            self._pos_t = now
            self.status = "Paused" if self.status == "Playing" else "Playing"
        self._control("PlayPause")
