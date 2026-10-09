"""Dados novos da interface "wired" (U2, R23.2/R23.3/R23.5).

Roda com o Python do sistema: só PySide6 + stdlib. Nada aqui bloqueia a thread de pintura:
leituras de `/proc` são curtas e o Spotify (MPRIS) e as capas vão para threads.

O PySide6 não consegue desmontar `a{sv}` (`QDBusArgument` sai como `None`/derruba o processo),
então os metadados do MPRIS são lidos com `busctl --json` numa thread; o QtDBus fica com o que
funciona nele: saber se o nome existe e mandar os comandos (Previous/PlayPause/Next).
"""

from __future__ import annotations

import fcntl
import glob
import hashlib
import json
import logging
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

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


# ---------------------------------------------------------------- Claude Code (painel)

AUTOFIX_STATE = Path("~/.local/share/magi/autofix/state.json").expanduser()
CLAUDE_EVENTS = Path("~/.cache/magi/claude-events.jsonl").expanduser()  # hud/tools/claude_hook.py


@dataclass
class ClaudeView:
    """O que o painel "Claude Code" mostra. Campos vazios = sem dado."""
    tokens: int | None = None  # tokens novos do dia (entrada + saída + criação de cache)
    output: int | None = None
    replies: int | None = None
    sessions: list = field(default_factory=list)  # [(projeto, rodando, minutos desde a última)]
    running: int = 0
    autofix: str | None = None  # linha de estado do autoconserto (state.json do núcleo)
    window_end: str | None = None  # fim da janela de 5 h em curso ("01:00"); None = nenhuma aberta
    window_fresh: int = 0  # tokens novos na janela
    window_cache: int = 0  # leitura de cache na janela (pesa bem menos)
    # último evento novo dos hooks (``hud/tools/claude_hook.py``): (epoch, "fail"|"notify"|"stop",
    # projeto); None = nenhum desde que o HUD abriu
    last_event: tuple | None = None


class ClaudeStats:
    """Lê o consumo do Claude Code (``magi.maintenance.claude_usage``) numa thread, a cada
    ``every`` s: a 1ª leitura dos registros leva ~1 s e não pode travar o HUD. ``view`` é o último
    resultado (troca atômica de referência).

    Também lê as linhas **novas** de ``events_file`` (gravadas pelo hook, spec §6 C): a 1ª leitura
    só marca o fim do arquivo (o passado não reage); arquivo menor que a posição = girou, relê do
    começo. ``last_event`` guarda o último evento válido visto."""

    def __init__(self, every: float = 15.0, autofix_state: Path = AUTOFIX_STATE, reader=None,
                 events_file: Path = CLAUDE_EVENTS):
        self.every = every
        self.autofix_state = autofix_state
        self.events_file = events_file
        self.view = ClaudeView()
        self._reader = reader
        self._ev_pos: int | None = None
        self._last_event: tuple | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _make_reader(self):
        root = Path(__file__).resolve().parents[2]  # hud/wired/data.py -> repositório
        if str(root) not in sys.path:
            sys.path.append(str(root))
        from magi.maintenance.claude_usage import UsageReader  # só biblioteca padrão
        return UsageReader()

    def events(self) -> tuple | None:
        """Lê as linhas novas do arquivo de eventos; devolve o último evento visto (ou None)."""
        try:
            size = self.events_file.stat().st_size
        except OSError:
            if self._ev_pos is None:
                self._ev_pos = 0  # ainda não existe: o que vier depois é novo
            return self._last_event
        if self._ev_pos is None:
            self._ev_pos = size
            return self._last_event
        if size < self._ev_pos:
            self._ev_pos = 0  # girou
        if size == self._ev_pos:
            return self._last_event
        try:
            with self.events_file.open("rb") as f:
                f.seek(self._ev_pos)
                bloco = f.read(size - self._ev_pos)
        except OSError:
            return self._last_event
        fim = bloco.rfind(b"\n")
        if fim < 0:
            return self._last_event  # linha ainda pela metade
        self._ev_pos += fim + 1
        for raw in bloco[:fim].splitlines():
            try:
                d = json.loads(raw)
                ev = (float(d["t"]), str(d["ev"]), str(d.get("proj") or ""))
            except (ValueError, TypeError, KeyError):
                continue
            if ev[1] in ("fail", "notify", "stop"):
                self._last_event = ev
        return self._last_event

    def refresh(self, now: datetime | None = None) -> ClaudeView:
        last = self.events()
        if self._reader is None:
            self._reader = self._make_reader()
        try:
            s = self._reader.summary()
        except Exception:
            if self.view.last_event != last:
                self.view = replace(self.view, last_event=last)
            raise
        now = now or datetime.now(UTC)
        sessions = [(x.project, x.running, max(0, int((now - x.last).total_seconds() // 60)))
                    for x in s.active[:4] if x.last is not None]
        end = s.window_end.astimezone().strftime("%H:%M") if s.window_end is not None else None
        self.view = ClaudeView(s.tokens.fresh, s.tokens.output, s.tokens.replies, sessions, s.running,
                               self._autofix(), end, s.window.fresh, s.window.cache_read, last)
        return self.view

    def _autofix(self) -> str | None:
        try:
            data = json.loads(self.autofix_state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return str(data.get("line") or "") or None

    def start(self) -> None:
        if self._thread is not None:
            return

        def loop():
            while not self._stop.is_set():
                try:
                    self.refresh()
                except Exception as e:  # noqa: BLE001 - painel é opcional
                    log.debug("claude: leitura falhou: %s", e)
                self._stop.wait(self.every)

        self._thread = threading.Thread(target=loop, name="claude-stats", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


# ---------------------------------------------------------------- consumo da própria Condessa

# nomes (basename do executável/script) dos processos dela: núcleo (com o Kokoro dentro),
# satélite, rádio, o HUD e o vigia do HUD; os filhos deles entram junto
SELF_NAMES = frozenset(("magi-core", "magi-satellite", "magi-ayanami", "gamerhud.py", "gamerhud-watch.py"))
_VRAM_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}


@dataclass
class SelfView:
    """O que a Condessa gasta da máquina. `cpu`/`gpu` ficam None até a 2ª leitura (precisam de delta)."""
    cpu: float | None = None  # % de um núcleo, somado (passa de 100 com vários núcleos)
    cpu_total: float | None = None  # % do total de CPUs
    ram_mb: float = 0.0  # soma do VmRSS
    gpu: float | None = None  # % do tempo de GPU (soma dos engines, limitado a 100)
    vram_mb: float = 0.0  # soma do drm-memory-vram, clientes DRM sem repetição
    procs: int = 0


def _stat_fields(raw: str) -> list[str]:
    """Campos de `/proc/<pid>/stat` depois do `comm` (que pode ter espaço e parêntese)."""
    return raw[raw.rfind(")") + 2:].split()


def _drm_info(raw: str) -> tuple[tuple[str, str], int, int] | None:
    """fdinfo de um FD de DRM → ((pdev, client-id), ns somados dos engines, bytes de VRAM)."""
    kv = {}
    for line in raw.splitlines():
        k, sep, v = line.partition(":")
        if sep and k.startswith("drm-"):
            kv[k] = v.strip()
    cid = kv.get("drm-client-id")
    if cid is None:
        return None
    ns = 0
    for k, v in kv.items():
        if k.startswith("drm-engine-") and not k.startswith("drm-engine-capacity-"):
            n, _, unit = v.partition(" ")
            if unit.strip() == "ns" and n.isdigit():
                ns += int(n)
    vram = 0
    n, _, unit = (kv.get("drm-memory-vram") or kv.get("drm-resident-vram") or "0").partition(" ")
    if n.isdigit():
        vram = int(n) * _VRAM_UNITS.get(unit.strip() or "B", 1)
    return (kv.get("drm-pdev", ""), cid), ns, vram


class SelfUsage:
    """CPU, RAM, tempo de GPU e VRAM dos processos da Condessa, só lendo `/proc` (chamado no poll
    de 1 Hz do HUD). A árvore de processos e os FDs de DRM são redescobertos a cada `rescan` s;
    entre uma e outra só se leem `stat`/`status` dos membros e o `fdinfo` dos FDs de DRM. Processo
    que some ou nega leitura é ignorado."""

    def __init__(self, proc: str = "/proc", rescan: float = 5.0, uid: int | None = None,
                 names: frozenset[str] = SELF_NAMES, hz: int | None = None, ncpu: int | None = None):
        self.proc = proc
        self.rescan = rescan
        self.uid = os.getuid() if uid is None else uid
        self.names = names
        self.hz = hz or os.sysconf("SC_CLK_TCK")
        self.ncpu = ncpu or os.cpu_count() or 1
        self.view: SelfView | None = None
        self._pids: list[str] = []
        self._drm: dict[str, list[str]] = {}  # pid → FDs de DRM
        self._scan_at: float | None = None
        self._prev: tuple[float, dict[tuple[str, str], int], dict[tuple, int]] | None = None

    def _read(self, *parts: str) -> str | None:
        try:
            with open(os.path.join(self.proc, *parts), encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def _is_self(self, pid: str) -> bool:
        raw = self._read(pid, "cmdline")
        if not raw:
            return False
        args = [os.path.basename(a) for a in raw.split("\0")[:2]]
        if args[0] in self.names:  # executável direto
            return True
        # interpretador + script; "grep magi-core" e afins não contam
        return args[0].startswith("python") and len(args) > 1 and args[1] in self.names

    def _scan(self) -> None:
        """Raízes (cmdline casa) do usuário e seus descendentes; FDs de DRM de cada um."""
        try:
            entries = [e for e in os.listdir(self.proc) if e.isdigit()]
        except OSError:
            entries = []
        parent: dict[str, str] = {}
        roots = []
        for pid in entries:
            try:
                if os.stat(os.path.join(self.proc, pid)).st_uid != self.uid:
                    continue
            except OSError:
                continue
            raw = self._read(pid, "stat")
            if raw is None:
                continue
            parent[pid] = _stat_fields(raw)[1]
            if self._is_self(pid):
                roots.append(pid)
        children: dict[str, list[str]] = {}
        for pid, pp in parent.items():
            children.setdefault(pp, []).append(pid)
        seen: set[str] = set()
        todo = list(roots)
        while todo:
            pid = todo.pop()
            if pid not in seen:
                seen.add(pid)
                todo += children.get(pid, [])
        self._pids = sorted(seen, key=int)
        self._drm = {}
        for pid in self._pids:
            try:
                fds = os.listdir(os.path.join(self.proc, pid, "fdinfo"))
            except OSError:
                continue
            drm = [fd for fd in fds if "drm-client-id" in (self._read(pid, "fdinfo", fd) or "")]
            if drm:
                self._drm[pid] = sorted(drm, key=lambda x: int(x) if x.isdigit() else 0)

    def poll(self, now: float | None = None) -> SelfView | None:
        now = time.monotonic() if now is None else now
        if self._scan_at is None or now - self._scan_at >= self.rescan:
            self._scan()
            self._scan_at = now
        ticks: dict[tuple[str, str], int] = {}  # (pid, starttime) → utime + stime
        ram_kb = 0
        for pid in self._pids:
            raw = self._read(pid, "stat")
            if raw is None:
                continue
            f = _stat_fields(raw)
            try:
                ticks[(pid, f[19])] = int(f[11]) + int(f[12])
            except (IndexError, ValueError):
                continue
            for line in (self._read(pid, "status") or "").splitlines():
                if line.startswith("VmRSS:"):
                    ram_kb += int(line.split()[1])
                    break
        clients: dict[tuple, tuple[int, int]] = {}  # (pdev, client-id) → (ns, vram)
        for pid, fds in self._drm.items():
            for fd in fds:
                info = _drm_info(self._read(pid, "fdinfo", fd) or "")
                if info is not None:
                    clients.setdefault(info[0], info[1:])
        if not ticks:
            self.view, self._prev = None, None
            return None
        gpu_ns = {k: ns for k, (ns, _) in clients.items()}
        view = SelfView(ram_mb=ram_kb / 1024, vram_mb=sum(v for _, v in clients.values()) / 1024 ** 2,
                        procs=len(ticks))
        if self._prev is not None and now > self._prev[0]:
            dt = now - self._prev[0]
            d_ticks = sum(max(0, t - self._prev[1][k]) for k, t in ticks.items() if k in self._prev[1])
            view.cpu = 100.0 * d_ticks / self.hz / dt
            view.cpu_total = view.cpu / self.ncpu
            d_ns = sum(max(0, ns - self._prev[2][k]) for k, ns in gpu_ns.items() if k in self._prev[2])
            view.gpu = min(100.0, 100.0 * d_ns / (dt * 1e9))
        self._prev = (now, ticks, gpu_ns)
        self.view = view
        return view


# ---------------------------------------------------------------- extras do MAGI SYSTEM (clock, swap, disco)


class SysExtra:
    """Clock médio da CPU, swap e ocupação do disco, só lendo `/sys`, `/proc` e `statvfs` (baratos o
    bastante para o poll de 1 Hz). Valor que não dá para ler sai como None, nunca exceção."""

    def __init__(self, cpufreq_glob: str = "/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq",
                 cpuinfo: str = "/proc/cpuinfo", meminfo: str = "/proc/meminfo", disk: str = "/home"):
        self.cpufreq_glob = cpufreq_glob
        self.cpuinfo = cpuinfo
        self.meminfo = meminfo
        self.disk = disk

    @staticmethod
    def _read(path: str) -> str | None:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def cpu_mhz(self) -> float | None:
        khz = []
        for path in glob.glob(self.cpufreq_glob):
            try:
                khz.append(int((self._read(path) or "").strip()))
            except ValueError:
                continue
        if khz:
            return sum(khz) / len(khz) / 1000
        mhz = []  # sem cpufreq (VM, driver ausente): "cpu MHz" de cada núcleo no cpuinfo
        for line in (self._read(self.cpuinfo) or "").splitlines():
            k, sep, v = line.partition(":")
            if sep and k.strip() == "cpu MHz":
                try:
                    mhz.append(float(v))
                except ValueError:
                    continue
        return sum(mhz) / len(mhz) if mhz else None

    def swap_gb(self) -> tuple[float | None, float | None]:
        """(usado, total) em GiB, de SwapTotal - SwapFree."""
        kv = {}
        for line in (self._read(self.meminfo) or "").splitlines():
            k, sep, v = line.partition(":")
            if sep and k in ("SwapTotal", "SwapFree"):
                try:
                    kv[k] = int(v.split()[0])
                except (IndexError, ValueError):
                    continue
        total = kv.get("SwapTotal")
        if total is None:
            return None, None
        free = kv.get("SwapFree")
        used = max(0, total - free) / 1024 ** 2 if free is not None else None
        return used, total / 1024 ** 2

    def disk_pct(self) -> float | None:
        """% ocupado como o `df`: usado / (usado + livre para usuário comum)."""
        try:
            st = os.statvfs(self.disk)
        except OSError:
            return None
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        avail = st.f_bavail * st.f_frsize
        return 100.0 * used / (used + avail) if used + avail > 0 else None

    def poll(self) -> dict:
        used, total = self.swap_gb()
        return {"cpu_mhz": self.cpu_mhz(), "swap_used_gb": used, "swap_total_gb": total,
                "disk_pct": self.disk_pct()}


# ---------------------------------------------------------------- IP / gateway / DNS (card NETWORK)

NET_INFO_TTL = 30.0
DNS_STUB = ("127.0.0.53", "127.0.0.54")  # stubs do systemd-resolved
_net_cache: dict[tuple, tuple[float, dict]] = {}


def _hex_ip(h: str) -> str | None:
    """Endereço de `/proc/net/route` (hex little-endian) → "a.b.c.d"."""
    try:
        return socket.inet_ntoa(struct.pack("<I", int(h, 16)))
    except (ValueError, struct.error):
        return None


def _default_route(route: str) -> tuple[str, str] | None:
    """(interface, gateway) da rota padrão de menor métrica em `/proc/net/route`."""
    try:
        with open(route) as f:
            lines = f.read().splitlines()[1:]
    except OSError:
        return None
    best = None
    for line in lines:
        cols = line.split()
        if len(cols) < 8 or cols[1] != "00000000" or cols[7] != "00000000":
            continue
        try:
            flags, metric = int(cols[3], 16), int(cols[6])
        except ValueError:
            continue
        if not flags & 0x1:  # RTF_UP
            continue
        gw = _hex_ip(cols[2])
        if gw and (best is None or metric < best[0]):
            best = (metric, cols[0], gw)
    return best[1:] if best else None


def _iface_ipv4(iface: str) -> str | None:
    """IPv4 da interface via ioctl SIOCGIFADDR (não manda nada pela rede)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            raw = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", iface[:15].encode()))
        return socket.inet_ntoa(raw[20:24])
    except OSError:
        return None


def _nameserver(path: str) -> str | None:
    try:
        with open(path) as f:
            for line in f:
                cols = line.split()
                if len(cols) >= 2 and cols[0] == "nameserver":
                    return cols[1]
    except OSError:
        pass
    return None


def _resolvectl_dns(timeout: float) -> str | None:
    """Primeiro servidor do `resolvectl dns` (linhas "Link 3 (wlo1): 192.168.0.1 ...")."""
    try:
        out = subprocess.run(["resolvectl", "dns"], capture_output=True, text=True, timeout=timeout,
                             check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        servers = line.partition(":")[2].split()
        if servers:
            return servers[0]
    return None


def net_info(now: float | None = None, *, route: str = "/proc/net/route", resolv: str = "/etc/resolv.conf",
             resolved: str = "/run/systemd/resolve/resolv.conf", ipv4=_iface_ipv4, resolvectl=_resolvectl_dns,
             ttl: float = NET_INFO_TTL) -> dict:
    """{"ip", "gateway", "dns"} da rota padrão (None no que faltar). Fica em cache por `ttl` s
    (por combinação de caminhos), então pode ser chamada no thread de UI à vontade."""
    now = time.monotonic() if now is None else now
    key = (route, resolv, resolved, ipv4, resolvectl)
    hit = _net_cache.get(key)
    if hit is not None and now - hit[0] < ttl:
        return dict(hit[1])
    dr = _default_route(route)
    ip = ipv4(dr[0]) if dr else None
    dns = _nameserver(resolv)
    if dns in DNS_STUB:
        # stub do systemd-resolved: o servidor de verdade está no resolv.conf dele ou no resolvectl
        dns = _nameserver(resolved) or resolvectl(0.5) or dns
    info = {"ip": ip, "gateway": dr[1] if dr else None, "dns": dns}
    _net_cache[key] = (now, info)
    return dict(info)


# ---------------------------------------------------------------- git (barra de status do KONSOLE)


class GitStatus:
    """Branch e +/- de linhas do working tree (staged + não staged) contra o HEAD. O `git` roda no
    máximo a cada `ttl` s, com `timeout` s; repositório inválido (ou git ausente) → valores None.
    ``head`` = hash curto do HEAD da última leitura (None sem commit), fora do dict do ``poll``."""

    def __init__(self, path: str, ttl: float = 30.0, timeout: float = 2.0):
        self.path = path
        self.ttl = ttl
        self.timeout = timeout
        self._at: float | None = None
        self._last: dict = {"branch": None, "added": None, "removed": None}
        self.head: str | None = None

    def _git(self, *args: str) -> str | None:
        try:
            out = subprocess.run(["git", "-C", self.path, *args], capture_output=True, text=True,
                                 timeout=self.timeout, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout if out.returncode == 0 else None

    def _read(self) -> dict:
        res: dict = {"branch": None, "added": None, "removed": None}
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if branch is None:
            self.head = None
            return res
        res["branch"] = branch.strip() or None
        head = self._git("rev-parse", "--short", "HEAD")
        self.head = (head.strip() or None) if head is not None else None
        diff = self._git("diff", "--numstat", "HEAD")  # sem commit ainda: HEAD falha → +/- None
        if diff is None:
            return res
        added = removed = 0
        for line in diff.splitlines():
            cols = line.split("\t")
            if len(cols) >= 2 and cols[0].isdigit() and cols[1].isdigit():  # binário vem "-"
                added += int(cols[0])
                removed += int(cols[1])
        res["added"], res["removed"] = added, removed
        return res

    def poll(self, now: float | None = None) -> dict:
        now = time.monotonic() if now is None else now
        if self._at is None or now - self._at >= self.ttl:
            self._at = now
            self._last = self._read()
        return dict(self._last)
