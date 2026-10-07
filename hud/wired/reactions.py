"""Reações da Condessa ao HUD, à música e aos cliques do Pedro — só no rosto (e, raramente, uma
linha de texto na legenda). Nada aqui chama IA nem fala em voz alta.

``Reactor.observe(snap, ...)`` (1 Hz, com o Snapshot novo) e ``Reactor.on_click(alvo)`` geram uma
``Reaction``: olhos/boca da checklist (B*/C*), para onde olhar (nome de painel), humor do fundo,
efeito desenhado em código e por quanto tempo. O retrato só a usa parado (dormindo de dia ou
ouvindo); falando/pensando, a reação é descartada.

Gosto musical: ``docs/design/CONDESSA-PERSONA.md``. Gêneros por artista vêm do cache do núcleo
(``~/.local/share/magi/artist-genres.json``); ajustes em ``~/.config/magi/condessa-gosto.toml``::

    [artistas]          # afinidade -2..2 por artista (nome como no player)
    "Ado" = 2
    [generos]           # sobrescreve a tabela padrão
    funk = -1
    [falas]
    musica = false      # sem comentários de música (o rosto continua)
    geral = true
"""

from __future__ import annotations

import json
import time
import tomllib
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

GENRES_FILE = Path.home() / ".local/share/magi/artist-genres.json"
CLEANUP_FILE = Path.home() / ".local/share/magi/cleanup_state.json"
TASTE_FILE = Path.home() / ".config/magi/condessa-gosto.toml"
SEEN_FILE = Path.home() / ".local/state/magi/condessa-artistas.json"

# afinidade por gênero (vocabulário do artist-genres.json)
GENRE_AFFINITY = {
    "trilha": 2, "anime": 2, "vocaloid": 1, "j-rock": 1, "j-pop": 1, "lofi": 1, "indie": 1,
    "rnb": 1, "mpb": 1, "jazz": 1, "classica": 1, "folk": 1,
    "pop": 0, "hip-hop": 0, "rock": 0, "eletronica": 0, "funk": 0, "kpop": 0, "latina": 0,
    "punk": 0, "comedia": 0,
    "metal": -1, "sertanejo": -1,
}
CALM = {"lofi", "classica", "jazz", "folk", "trilha", "mpb"}
LOVED_WORDS = ("ost", "soundtrack", "opening", "original sound", "city pop", "persona", "nier",
               "final fantasy", "shoegaze")
SOFTEN_WORDS = ("instrumental", "orchestra", "orquestra", "piano", "acoustic", "jazz")
HATED_WORDS = ("sped up", "speed up", "nightcore", "spedup")

HOT_C, COOL_C = 85.0, 78.0  # temperatura: entra em "quente" e só sai abaixo de COOL_C
FPS_DROP = 0.6  # FPS abaixo de 60% da média por 2 leituras seguidas
LONG_SESSION = 2 * 3600.0
SKIP_WINDOW = 40.0  # "próxima" até 40 s depois da faixa começar conta como pular
LINE_GAP = 4 * 60.0  # entre duas falas de texto quaisquer
MUSIC_LINE_GAP = 20 * 60.0  # entre comentários de música
LINE_SECS = 7.0


@dataclass(frozen=True)
class Reaction:
    name: str
    eyes: str | None = None  # B*/F* da checklist; None = os do estado
    mouth: str | None = None  # C*
    look: str | None = None  # painel: magi, fps, player, radio, claude, led, net, history
    mood: str = "calm"  # fundo: calm, happy, stress, sad, focus, surprise, sleepy, love
    effect: str | None = None  # sweat, notes, question, bang, blush
    dur: float = 4.0
    bob: bool = False  # balança a cabeça no ritmo
    prio: int = 1
    line: str | None = None  # texto curto na legenda (sem voz)


R = Reaction
REACTIONS: dict[str, Reaction] = {
    "music_love": R("music_love", "B5", "C13", "player", "love", "notes", 9.0, True, 2),
    "music_like": R("music_like", "B2", "C5", "player", "happy", None, 6.0, True, 1),
    "music_ok": R("music_ok", None, None, "player", "calm", None, 2.5, False, 1),
    "music_meh": R("music_meh", "F1", "C11", "player", "sad", None, 4.0, False, 1),
    "music_hate": R("music_hate", "B7", "C12", "player", "stress", "sweat", 4.5, False, 2),
    "music_new": R("music_new", "B9", "C7", "player", "surprise", "question", 4.0, False, 2),
    "music_tolerate": R("music_tolerate", "B4", "C14", "player", "calm", None, 4.0, False, 1),
    "news": R("news", None, "C7", "radio", "focus", None, 3.5, False, 1),
    "hot": R("hot", None, "C8", "magi", "stress", "sweat", 6.0, False, 3),
    "fps_drop": R("fps_drop", None, "C11", "fps", "stress", None, 3.5, False, 2),
    "game_on": R("game_on", "B4", "C6", "fps", "happy", None, 4.0, False, 2),
    "game_off": R("game_off", "B4", "C5", "fps", "calm", None, 3.0, False, 1),
    "long_session": R("long_session", "B14", "C1", None, "sleepy", None, 8.0, False, 1),
    "cleanup": R("cleanup", "B4", "C10", None, "happy", "blush", 6.0, False, 2),
    "led": R("led", "B9", "C7", "led", "surprise", "bang", 2.5, False, 2),
    "player": R("player", None, None, "player", "calm", None, 1.8, False, 1),
    "card": R("card", None, None, "magi", "focus", None, 2.0, False, 1),
    "claude": R("claude", "B13", "C1", "claude", "focus", None, 5.0, False, 1),
    "skips": R("skips", "B13", "C10", "player", "calm", "question", 5.0, False, 2),
}
MOOD_OF_STATE = {"happy": "happy", "alert": "stress", "confused": "sad", "thinking": "focus"}

# para onde fica cada painel, visto do retrato (nome do olhar do portrait.toml)
LOOK_DIRS = {
    "main": {"magi": "left", "led": "left", "fps": "down_left", "net": "down_left",
             "history": "down_left", "player": "up_right", "radio": "right", "claude": "down_right"},
    "idle": {"magi": "left", "led": "up_right", "fps": "left", "net": "left", "history": "left",
             "player": "down", "radio": "left", "claude": "left"},
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Taste:
    """Afinidade −2..2 de uma faixa: gêneros do artista + palavras do título + ajustes do Pedro."""

    def __init__(self, genres_file: Path | None = None, taste_file: Path | None = None):
        self.genres_file = genres_file or GENRES_FILE
        self.taste_file = taste_file or TASTE_FILE
        self._mtimes: tuple = ()
        self.genres: dict[str, list[str]] = {}
        self.artists: dict[str, int] = {}
        self.table = dict(GENRE_AFFINITY)
        self.lines = {"musica": True, "geral": True}

    def _reload(self) -> None:
        mt = tuple(p.stat().st_mtime if p.exists() else 0 for p in (self.genres_file, self.taste_file))
        if mt == self._mtimes:
            return
        self._mtimes = mt
        raw = _load_json(self.genres_file)
        self.genres = {norm(k): list(v.get("genres") or ()) for k, v in raw.items() if isinstance(v, dict)}
        cfg: dict = {}
        if self.taste_file.exists():
            try:
                cfg = tomllib.loads(self.taste_file.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                cfg = {}
        self.artists = {norm(k): int(v) for k, v in dict(cfg.get("artistas", {})).items()}
        self.table = dict(GENRE_AFFINITY) | {str(k): int(v) for k, v in dict(cfg.get("generos", {})).items()}
        falas = {str(k): bool(v) for k, v in dict(cfg.get("falas", {})).items()}
        self.lines = {"musica": True, "geral": True} | falas

    def known(self, artist: str) -> bool:
        self._reload()
        return norm(artist) in self.genres or norm(artist) in self.artists

    def affinity(self, title: str, artist: str, hour: int = 12) -> int:
        self._reload()
        a, t = norm(artist or ""), norm(title or "")
        if any(w in t for w in HATED_WORDS):
            return -2
        if a in self.artists:
            return max(-2, min(2, self.artists[a]))
        genres = self.genres.get(a, [])
        vals = [self.table.get(g, 0) for g in genres]
        v = max(vals) if vals else 0
        if any(w in t for w in LOVED_WORDS):
            v = 2
        elif v < 0 and any(w in t for w in SOFTEN_WORDS):
            v = 1  # metal instrumental/orquestrado sobe
        if hour >= 23 or hour < 6:  # tarde da noite: prefere coisa calma
            if set(genres) & CALM:
                v += 1
            elif set(genres) & {"metal", "eletronica", "punk", "funk"}:
                v -= 1
        return max(-2, min(2, v))


class Reactor:
    def __init__(self, taste: Taste | None = None, cleanup_file: Path | None = None,
                 seen_file: Path | None = None, clock=time.time):
        self.taste = taste or Taste()
        self.cleanup_file = cleanup_file or CLEANUP_FILE
        self.seen_file = seen_file or SEEN_FILE
        self.clock = clock
        self.current: Reaction | None = None
        self.until = 0.0
        self.line: str | None = None
        self.line_until = 0.0
        self._last_line = -1e9
        self._last_music_line = -1e9
        self._cooldown: dict[str, float] = {}
        self._prev = None
        self._track: tuple | None = None
        self._track_at = 0.0
        self._plays: dict[tuple, int] = {}
        self._plays_day = ""
        self._skips = 0
        self._hot = False
        self._low_fps = 0
        self._game_since: float | None = None
        self._long_done = False
        self._cleanup_at = self._cleanup_stamp()
        self._claude_running = 0
        self._seen: set[str] = set(_load_json(seen_file).get("artists", [])) if seen_file else set()

    # ------------------------------------------------------------ saída

    def active(self, now: float) -> Reaction | None:
        if self.current is not None and now >= self.until:
            self.current = None
        return self.current

    def caption(self, now: float) -> str | None:
        if self.line is not None and now >= self.line_until:
            self.line = None
        return self.line

    def cancel(self) -> None:
        """Ela começou a falar/pensar: a reação parada some (a fala dela manda)."""
        self.current = None

    # ------------------------------------------------------------ disparo

    def fire(self, key: str, now: float, line: str | None = None, cooldown: float = 0.0,
             music: bool = False) -> Reaction | None:
        r = REACTIONS[key]
        if now < self._cooldown.get(key, -1e9):
            return None
        cur = self.active(now)
        if cur is not None and cur.prio > r.prio:
            return None
        self._cooldown[key] = now + cooldown
        self.current, self.until = r, now + r.dur
        if line and self.taste.lines.get("musica" if music else "geral", True):
            gap_ok = now - self._last_line >= LINE_GAP
            if gap_ok and (not music or now - self._last_music_line >= MUSIC_LINE_GAP):
                self.line, self.line_until, self._last_line = line, now + LINE_SECS, now
                if music:
                    self._last_music_line = now
                self.current = replace(r, line=line)
        return self.current

    # ------------------------------------------------------------ entradas

    def on_click(self, target: str, now: float) -> None:
        if target == "led":
            self.fire("led", now, cooldown=3.0)
        elif target == "next":
            if self._track is not None and now - self._track_at <= SKIP_WINDOW:
                self._skips += 1
            if self._skips >= 3:
                self._skips = 0
                self.fire("skips", now, "Tá difícil, hein? Diz \"coloca uma boa\" que eu escolho.",
                          cooldown=600.0)
                return
            self.fire("player", now)
        elif target in ("prev", "playpause"):
            self.fire("player", now)
        elif target.startswith("card:"):
            self.fire("card", now)

    def observe(self, snap, now: float, hour: int | None = None) -> None:
        """Compara o Snapshot com o anterior e dispara o que mudou (chamado a 1 Hz)."""
        hour = time.localtime(self.clock()).tm_hour if hour is None else hour
        prev, self._prev = self._prev, snap
        self._music(snap, now, hour, first=prev is None)
        if prev is None:  # ao abrir o HUD só registra (não reage ao que já estava rolando)
            self._hot = self._is_hot(snap)
            self._game_since = now if snap.gaming else None
            return
        if snap.news and (not prev.news or snap.news[0] != prev.news[0]):
            self.fire("news", now, cooldown=20.0)
        hot = self._is_hot(snap, self._hot)
        if hot and not self._hot:
            t = max(x for x in (snap.cpu_temp, snap.gpu_temp) if x is not None)
            self.fire("hot", now, f"Tá esquentando aqui: {t:.0f} °C.", cooldown=300.0)
        self._hot = hot
        if snap.gaming and not prev.gaming:
            self._game_since, self._long_done = now, False
            self.fire("game_on", now, cooldown=30.0)
        elif prev.gaming and not snap.gaming:
            self._game_since = None
            self.fire("game_off", now, cooldown=30.0)
        if snap.fps is not None and snap.fps_avg and snap.fps < FPS_DROP * snap.fps_avg:
            self._low_fps += 1
            if self._low_fps == 2:
                self.fire("fps_drop", now, cooldown=90.0)
        else:
            self._low_fps = 0
        if self._game_since is not None and not self._long_done and now - self._game_since >= LONG_SESSION:
            self._long_done = True
            self.fire("long_session", now, "Duas horas direto… bebe uma água, vai.")
        stamp = self._cleanup_stamp()
        if stamp != self._cleanup_at:
            self._cleanup_at = stamp
            self.fire("cleanup", now, "Fiz a faxina do SSD.", cooldown=60.0)
        running = getattr(snap.claude, "running", 0) or 0
        if running > self._claude_running:
            self.fire("claude", now, cooldown=120.0)
        self._claude_running = running

    # ------------------------------------------------------------ detalhes

    @staticmethod
    def _is_hot(snap, was: bool = False) -> bool:
        temps = [x for x in (snap.cpu_temp, snap.gpu_temp) if x is not None]
        return bool(temps) and max(temps) >= (COOL_C if was else HOT_C)

    def _cleanup_stamp(self) -> str | None:
        return _load_json(self.cleanup_file).get("at") if self.cleanup_file else None

    def _music(self, snap, now: float, hour: int, first: bool = False) -> None:
        tr = snap.track
        key = (tr.title, tr.artist) if tr is not None and getattr(tr, "title", None) else None
        if key == self._track:
            return
        self._track, self._track_at = key, now
        if key is None or first or snap.gaming and snap.fps is not None:  # jogando: quase não reage
            return
        title, artist = key[0] or "", key[1] or ""
        day = time.strftime("%Y%m%d", time.localtime(self.clock()))
        if day != self._plays_day:
            self._plays, self._plays_day = {}, day
        self._plays[key] = n = self._plays.get(key, 0) + 1
        a = self.taste.affinity(title, artist, hour)
        if n >= 3 and a < 2:
            a -= 1  # a mesma faixa de novo e de novo
        new = bool(artist) and norm(artist) not in self._seen
        if new:
            self._remember(artist)
        if new and a >= 0 and not self.taste.known(artist):
            self.fire("music_new", now, f"Quem é {artist}? Não conhecia.", music=True)
        elif a >= 2:
            self.fire("music_love", now, "Agora sim.", music=True)
        elif a == 1:
            self.fire("music_like", now)
        elif a == 0:
            self.fire("music_ok", now)
        elif a == -1:
            self.fire("music_meh", now)
        else:
            line = "Sped up? Respeita a música, Pedro." if any(
                w in norm(title) for w in HATED_WORDS) else "Hm… não é minha praia."
            self.fire("music_hate", now, line, music=True)

    def _remember(self, artist: str) -> None:
        self._seen.add(norm(artist))
        if self.seen_file is None:
            return
        try:
            self.seen_file.parent.mkdir(parents=True, exist_ok=True)
            self.seen_file.write_text(json.dumps({"artists": sorted(self._seen)}, ensure_ascii=False),
                                      encoding="utf-8")
        except OSError:
            pass
