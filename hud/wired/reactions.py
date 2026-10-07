"""Reações da Condessa ao HUD, à música e aos cliques do Pedro — só no rosto (e, raramente, uma
linha de texto na legenda). Nada aqui chama IA nem fala em voz alta.

``Reactor.observe(snap, ...)`` (1 Hz, com o Snapshot novo) e ``Reactor.on_click(alvo)`` geram uma
``Reaction``: olhos/boca da checklist (B*/C*), para onde olhar (nome de painel), humor do fundo,
efeito desenhado em código e por quanto tempo. O retrato só a usa parado (dormindo de dia);
ouvindo/falando/pensando, a reação é descartada.

Gosto, regras e falas: ``persona/condessa-gosto.toml``, decidido pelo Conselho da Condessa
(``persona/conselho/``). Gêneros por artista vêm do cache do núcleo
(``~/.local/share/magi/artist-genres.json``). O Pedro sobrepõe o que quiser em
``~/.config/magi/condessa-gosto.toml`` (mesmo formato; ``[falas] musica = false`` desliga os
comentários de música; ``[pedro] favoritas = ["artista", ...]`` nunca levam careta). As
favoritas do Spotify chegam sozinhas pelo núcleo (``~/.local/share/magi/pedro-favoritas.json``).
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
import tomllib
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

COUNCIL_FILE = Path(__file__).resolve().parents[2] / "persona" / "condessa-gosto.toml"
GENRES_FILE = Path.home() / ".local/share/magi/artist-genres.json"
CLEANUP_FILE = Path.home() / ".local/share/magi/cleanup_state.json"
TASTE_FILE = Path.home() / ".config/magi/condessa-gosto.toml"
SEEN_FILE = Path.home() / ".local/state/magi/condessa-artistas.json"
FAVORITES_FILE = Path.home() / ".local/share/magi/pedro-favoritas.json"  # do Spotify, pelo núcleo
SPEECH_FILE = Path.home() / ".config/magi/config.toml"  # [speech] language = "en-gb": falas em inglês

HOT_C, COOL_C = 85.0, 78.0  # temperatura: entra em "quente" e só sai abaixo de COOL_C
FPS_DROP = 0.6  # FPS abaixo de 60% da média por 2 leituras seguidas
LONG_SESSION = 2 * 3600.0
SKIP_WINDOW = 40.0  # "próxima" até 40 s depois da faixa começar conta como pular
LINE_GAP = 4 * 60.0  # entre duas falas de texto quaisquer
MUSIC_LINE_GAP = 20 * 60.0  # entre comentários de música
LINE_SECS = 7.0
CLEANUP_MIN_BYTES = 1_000_000_000  # faxina menor que isso não é comemorada (= cleanup_announce_gb)
CLICK_TALK = 0.25  # chance de comentar um clique comum (player, card)
_SPLIT = re.compile(r"\s*(?:,|&|/|;| feat\.? | ft\.? | x | e )\s*")


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
    "music_meh": R("music_meh", "F1", "C11", "player", "calm", None, 4.0, False, 1),
    "music_hate": R("music_hate", "B7", "C12", "player", "stress", "sweat", 4.5, False, 2),
    "music_new": R("music_new", "B9", "C7", "player", "surprise", "question", 10.0, False, 2),
    "music_tolerate": R("music_tolerate", "B4", "C14", "player", "calm", None, 4.0, False, 1),
    "news": R("news", None, "C7", "radio", "focus", None, 3.5, False, 1),
    "hot": R("hot", None, "C8", "magi", "stress", "sweat", 6.0, False, 3),
    "fps_drop": R("fps_drop", None, "C11", "fps", "focus", None, 3.5, False, 2),
    "game_on": R("game_on", "B4", "C6", "fps", "happy", None, 4.0, False, 2),
    "game_off": R("game_off", "B4", "C5", "fps", "happy", None, 3.0, False, 1),
    "long_session": R("long_session", "B14", "C1", None, "sad", None, 8.0, False, 1),
    "cleanup": R("cleanup", "B4", "C10", None, "happy", "blush", 6.0, False, 2),
    "led": R("led", "B9", "C7", "led", "surprise", "bang", 2.5, False, 2),
    "player": R("player", None, None, "player", "calm", None, 1.8, False, 1),
    "card": R("card", None, None, "magi", "focus", None, 2.0, False, 1),
    "claude": R("claude", "B13", "C1", "claude", "focus", None, 5.0, False, 1),
    "skips": R("skips", "B13", "C10", "player", "stress", "question", 5.0, False, 2),
}
MUSIC_BY_NOTE = {2: "music_love", 1: "music_like", 0: "music_ok", -1: "music_meh", -2: "music_hate"}
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


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _has(text: str, words) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(norm(w))}(?!\w)", text) for w in words)


def _in_hours(hour: int, span) -> bool:
    a, b = int(span[0]), int(span[1])
    return a <= hour < b if a < b else (hour >= a or hour < b)


@dataclass(frozen=True)
class Verdict:
    """Nota final de uma faixa e o porquê (para a reação e a fala certas)."""
    note: int
    artist: str = ""  # chave normalizada do artista reconhecido ("" = nenhum)
    genres: tuple[str, ...] = ()
    rival: bool = False
    slowed: bool = False
    known: bool = False


class Taste:
    """Gosto da Condessa: acordo do conselho + ajustes do Pedro, relidos quando os arquivos mudam."""

    def __init__(self, genres_file: Path | None = None, taste_file: Path | None = None,
                 council_file: Path | None = None, favorites_file: Path | None = None,
                 speech_file: Path | None = None):
        self.genres_file = genres_file or GENRES_FILE
        self.taste_file = taste_file or TASTE_FILE
        self.council_file = council_file or COUNCIL_FILE
        self.favorites_file = favorites_file or FAVORITES_FILE
        self.speech_file = speech_file or SPEECH_FILE
        self.english = False  # a Condessa fala inglês (config do núcleo): falas de [falas_en]
        self.pedro_tracks: set[tuple[str, str]] = set()
        self._mtimes: tuple = ()
        self.genres: dict[str, list[str]] = {}
        self.cfg: dict = {}
        self.table: dict[str, int] = {}
        self.artists: dict[str, int] = {}
        self.lines = {"musica": True, "geral": True}
        self.pedro: set[str] = set()

    # ------------------------------------------------------------ carga

    def _reload(self) -> None:
        files = (self.genres_file, self.taste_file, self.council_file, self.favorites_file, self.speech_file)
        mt = tuple(p.stat().st_mtime if p.exists() else 0 for p in files)
        if mt == self._mtimes:
            return
        self._mtimes = mt
        raw = _load_json(self.genres_file)
        self.genres = {norm(k): list(v.get("genres") or ()) for k, v in raw.items() if isinstance(v, dict)}
        council, mine = _load_toml(self.council_file), _load_toml(self.taste_file)
        cfg = {k: dict(v) if isinstance(v, dict) else v for k, v in council.items()}
        for k, v in mine.items():  # o Pedro sobrepõe tabela a tabela
            cfg[k] = (cfg.get(k, {}) | v) if isinstance(v, dict) and isinstance(cfg.get(k), dict) else v
        self.cfg = cfg
        speech = _load_toml(self.speech_file).get("speech", {})
        lang = speech.get("language", "") if isinstance(speech, dict) else ""
        self.english = str(lang).strip().lower().startswith("en")
        self.table = {str(k): int(v) for k, v in dict(cfg.get("generos", {})).items()}
        self.artists = {norm(k): int(v) for k, v in dict(cfg.get("artistas", {})).items()}
        falas = dict(cfg.get("falas", {}))
        self.lines = {"musica": True, "geral": True} | {k: v for k, v in falas.items() if isinstance(v, bool)}
        fav = _load_json(self.favorites_file)
        mine_fav = dict(cfg.get("pedro", {})).get("favoritas", [])
        self.pedro = {norm(a) for a in [*mine_fav, *fav.get("artists", [])]}
        self.pedro_tracks = {(norm(t[0]), norm(t[1])) for t in fav.get("tracks", []) if len(t) >= 2}

    def section(self, name: str) -> dict:
        self._reload()
        return dict(self.cfg.get(name, {}))

    def ctx(self, key: str, default):
        return self.section("contexto").get(key, default)

    def lines_for(self, key: str) -> dict[str, list[str]]:
        self._reload()
        table = dict(self.cfg.get("falas", {})).get(key, {})
        if self.english:  # em inglês, se a fala foi traduzida (senão a de sempre)
            table = dict(self.cfg.get("falas_en", {})).get(key) or table
        return {k: list(v) for k, v in dict(table).items()} if isinstance(table, dict) else {}

    def mood(self, key: str, default: str) -> str:
        return str(self.section("humor").get(key, default))

    # ------------------------------------------------------------ artista

    def artist_key(self, artist: str) -> str:
        """Primeiro nome reconhecido em "A, B feat. C" (a string inteira primeiro)."""
        self._reload()
        whole = norm(artist or "")
        for cand in [whole, *_SPLIT.split(whole)]:
            if cand and (cand in self.artists or cand in self.genres):
                return cand
        return ""

    def pedro_favorite(self, title: str, artist: str) -> bool:
        """Faixa ou artista entre os favoritos do Pedro (Spotify ou ajuste dele)."""
        key = self.artist_key(artist) or norm(artist or "")
        first = _SPLIT.split(norm(artist or ""))[0] if artist else ""
        return key in self.pedro or (norm(title or ""), first) in self.pedro_tracks

    def known(self, artist: str) -> bool:
        return bool(self.artist_key(artist))

    def base(self, key: str) -> int:
        """Nota do artista sem título nem contexto (gênero → ajuste por artista)."""
        self._reload()
        if key in self.artists:
            return max(-2, min(2, self.artists[key]))
        vals = [self.table.get(g, 0) for g in self.genres.get(key, [])]
        return max(vals) if vals else 0

    def candidates(self, floor: int) -> list[str]:
        self._reload()
        return sorted(k for k in set(self.artists) | set(self.genres) if self.base(k) >= floor)

    # ------------------------------------------------------------ nota

    def verdict(self, title: str, artist: str, hour: int = 12, plays: int = 1, gaming: bool = False,
                claude: bool = False) -> Verdict:
        """gênero → artista → título (±1) → contexto (±1) → limite -2..2."""
        key = self.artist_key(artist)
        genres = tuple(self.genres.get(key, ()))
        note = self.base(key) if key else 0
        rival = key in {norm(a) for a in self.section("rivais").get("artistas", [])}
        t = norm(title or "")
        tw = self.section("titulo")
        slowed = _has(t, tw.get("desce", []))
        if rival:
            return Verdict(2, key, genres, True, slowed, True)
        up = _has(t, tw.get("sobe", [])) or _has(t, tw.get("agua", []))
        down = slowed or (note == 2 and _has(t, [tw.get("remix_rival", "remix")]))
        note += max(-1, min(1, int(up) - int(down)))
        if note < 0 and _has(t, tw.get("suaviza", [])):
            note = 0
        bonus = 0
        g = set(genres)
        if _in_hours(hour, self.ctx("madrugada", [22, 4])) and g & set(self.ctx("madrugada_generos", [])):
            bonus = 1
        party = g & set(self.ctx("festa_generos", []))
        if not gaming and party and _in_hours(hour, self.ctx("festa", [20, 0])):
            bonus = 1
        if claude and g & set(self.ctx("claude_generos", [])):
            bonus = 1
        if plays >= int(self.ctx("repeticao_cai", 3)) and note <= 1:
            bonus -= 1
        note = max(-2, min(2, note + max(-1, min(1, bonus))))
        drop = self.section("cai_apos").get(key)
        if isinstance(drop, dict) and plays >= int(drop.get("plays", 99)):
            note = min(note, int(drop.get("nota", note)))
        return Verdict(note, key, genres, False, slowed, bool(key))

    def affinity(self, title: str, artist: str, hour: int = 12) -> int:
        return self.verdict(title, artist, hour).note


class Reactor:
    def __init__(self, taste: Taste | None = None, cleanup_file: Path | None = None,
                 seen_file: Path | None = None, clock=time.time, rng: random.Random | None = None):
        self.taste = taste or Taste()
        self.cleanup_file = cleanup_file or CLEANUP_FILE
        self.seen_file = seen_file or SEEN_FILE
        self.clock = clock
        self.rng = rng or random.Random()
        self.current: Reaction | None = None
        self.until = 0.0
        self.line: str | None = None
        self.line_until = 0.0
        self._last_line = -1e9
        self._last_line_prio = 0
        self._last_music_line = -1e9
        self._last_hate = -1e9
        self._cooldown: dict[str, float] = {}
        self._prev = None
        self._track: tuple | None = None
        self._track_at = 0.0
        self._pending: tuple | None = None  # (quando, track, chave, variante, humor): depois do "?"
        self._plays: dict[tuple, int] = {}
        self._day = ""
        self._fav_used = False
        self._skips = 0
        self._hot = False
        self._low_fps = 0
        self._game_since: float | None = None
        self._long_done = False
        self._cleanup_at = self._cleanup_stamp()
        self._claude_running = 0
        self._seen: set[str] = set(_load_json(self.seen_file).get("artists", []))

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

    def pick(self, key: str, variant: str | None = None, **fmt) -> str | None:
        table = self.taste.lines_for(key)
        opts = (table.get(variant) if variant else None) or table.get("padrao") or []
        if not opts:
            return None
        try:
            return self.rng.choice(opts).format(**fmt)
        except (KeyError, IndexError, ValueError):
            return None

    def fire(self, key: str, now: float, line: str | None = None, cooldown: float = 0.0,
             music: bool = False, mood: str | None = None, talk: bool = True) -> Reaction | None:
        base = REACTIONS[key]
        r = replace(base, mood=mood or self.taste.mood(key, base.mood))
        if now < self._cooldown.get(key, -1e9):
            return None
        cur = self.active(now)
        if cur is not None and cur.prio > r.prio:
            return None
        self._cooldown[key] = now + cooldown
        self.current, self.until = r, now + r.dur
        if talk and line and self.taste.lines.get("musica" if music else "geral", True):
            gap_ok = now - self._last_line >= LINE_GAP or r.prio > self._last_line_prio
            if gap_ok and (not music or now - self._last_music_line >= MUSIC_LINE_GAP):
                self.line, self.line_until, self._last_line = line, now + LINE_SECS, now
                self._last_line_prio = r.prio
                if music:
                    self._last_music_line = now
                self.current = replace(r, line=line)
        return self.current

    def say(self, key: str, now: float, variant: str | None = None, cooldown: float = 0.0,
            mood: str | None = None, **fmt) -> Reaction | None:
        return self.fire(key, now, self.pick(key, variant, **fmt), cooldown, mood=mood)

    # ------------------------------------------------------------ entradas

    def on_click(self, target: str, now: float) -> None:
        if target == "led":
            self.say("led", now, cooldown=3.0)
        elif target == "next":
            if self._track is not None and now - self._track_at <= SKIP_WINDOW:
                self._skips += 1
            if self._skips >= 3:
                self._skips = 0
                self.say("skips", now, cooldown=600.0)
                return
            self._click("player", now)
        elif target in ("prev", "playpause"):
            self._click("player", now)
        elif target.startswith("card:"):
            self._click("card", now)

    def _click(self, key: str, now: float) -> None:
        """Clique comum: ela sempre olha; comenta só de vez em quando (1 em 4)."""
        line = self.pick(key) if self.rng.random() < CLICK_TALK else None
        self.fire(key, now, line)

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
            self.say("news", now, cooldown=20.0)
        hot = self._is_hot(snap, self._hot)
        if hot and not self._hot:
            t = max(x for x in (snap.cpu_temp, snap.gpu_temp) if x is not None)
            self.say("hot", now, cooldown=300.0, temp=f"{t:.0f}")
        self._hot = hot
        night = _in_hours(hour, self.taste.ctx("madrugada", [22, 4]))
        if snap.gaming and not prev.gaming:
            self._game_since, self._long_done = now, False
            self.say("game_on", now, cooldown=30.0)
        elif prev.gaming and not snap.gaming:
            took = now - (self._game_since if self._game_since is not None else now)
            if took < 60 * float(self.taste.ctx("jogo_curto_min", 10)):
                self.say("game_off", now, "curto", 30.0, self.taste.mood("game_off_curto", "calm"))
            elif night and self._long_done:
                self.say("game_off", now, "madrugada", 30.0, self.taste.mood("game_off_madrugada", "sad"))
            else:
                self.say("game_off", now, cooldown=30.0)
            self._game_since = None
        if snap.fps is not None and snap.fps_avg and snap.fps < FPS_DROP * snap.fps_avg:
            self._low_fps += 1
            if self._low_fps == 2:
                self.say("fps_drop", now, cooldown=90.0, fps=f"{snap.fps:.0f}")
        else:
            self._low_fps = 0
        if self._game_since is not None and not self._long_done and now - self._game_since >= LONG_SESSION:
            self._long_done = True
            self.say("long_session", now, "madrugada" if night else None)
        stamp = self._cleanup_stamp()
        if stamp != self._cleanup_at:
            self._cleanup_at = stamp
            self.say("cleanup", now, cooldown=60.0)
        running = getattr(snap.claude, "running", 0) or 0
        if running > self._claude_running:
            self.say("claude", now, cooldown=120.0)
        self._claude_running = running

    # ------------------------------------------------------------ detalhes

    @staticmethod
    def _is_hot(snap, was: bool = False) -> bool:
        temps = [x for x in (snap.cpu_temp, snap.gpu_temp) if x is not None]
        return bool(temps) and max(temps) >= (COOL_C if was else HOT_C)

    def _cleanup_stamp(self) -> str | None:
        """Marca da última faxina que valeu a pena (a mesma régua da fala do núcleo: ≥ 1 GB)."""
        data = _load_json(self.cleanup_file) if self.cleanup_file else {}
        try:
            worth = int(data.get("freed_bytes", 0)) >= CLEANUP_MIN_BYTES
        except (TypeError, ValueError):
            worth = False
        return data.get("at") if worth else None

    def favorite_of_day(self) -> str:
        """Favorita do Dia: sorteada pela data entre artistas com nota ≥ o piso do acordo."""
        pool = self.taste.candidates(int(self.taste.ctx("favorita_dia_piso", -1)))
        if not pool:
            return ""
        h = int(hashlib.sha1(self._day.encode()).hexdigest(), 16)
        return pool[h % len(pool)]

    def _music(self, snap, now: float, hour: int, first: bool = False) -> None:
        tr = snap.track
        key = (tr.title, tr.artist) if tr is not None and getattr(tr, "title", None) else None
        if key != self._track:
            self._track, self._track_at, self._pending = key, now, None
            if key is not None and not first:
                self._new_track(key, snap, now, hour)
        if self._pending and now >= self._pending[0] and self._pending[1] == self._track:
            _, _, rkey, variant, mood, fmt = self._pending
            self._pending = None
            self.fire(rkey, now, self.pick(rkey, variant, **fmt), music=True, mood=mood)

    def _new_track(self, key: tuple, snap, now: float, hour: int) -> None:
        title, artist = key[0] or "", key[1] or ""
        day = time.strftime("%Y%m%d", time.localtime(self.clock()))
        if day != self._day:
            self._plays, self._day, self._fav_used = {}, day, False
        self._plays[key] = plays = self._plays.get(key, 0) + 1
        gaming = bool(snap.gaming)
        claude = bool(getattr(snap.claude, "running", 0))
        v = self.taste.verdict(title, artist, hour, plays, gaming, claude)
        pedro = self.taste.pedro_favorite(title, artist)
        rkey, variant, mood = self._decide(v, plays, gaming, hour, now, pedro)
        if rkey is None:
            return
        fmt = {"artist": artist}
        new = bool(artist) and norm(artist) not in self._seen
        if new:
            self._remember(artist)
        if new and v.note >= 0 and not v.known and not gaming:
            self.fire("music_new", now, self.pick("music_new", artist=artist), music=True)
            self._pending = (now + float(self.taste.ctx("novo_segundos", 10)), key, rkey, variant, mood, fmt)
            return
        line = self.pick(rkey, variant, **fmt)
        talk = not gaming or variant == "batalha"  # jogando, só a fala de chefe passa
        self.fire(rkey, now, line, music=True, mood=mood, talk=talk)

    def _decide(self, v: Verdict, plays: int, gaming: bool, hour: int, now: float,
                pedro: bool = False) -> tuple[str | None, str | None, str | None]:
        """Reação (chave, variante da fala, humor) para o veredito, pelas regras do acordo."""
        note, night = v.note, _in_hours(hour, self.taste.ctx("madrugada", [22, 4]))
        if gaming and note not in (2, -2):
            return None, None, None  # jogando: o rosto só reage aos extremos
        if note <= -1 and pedro:
            return "music_tolerate", None, None
        if v.artist and v.artist == self.favorite_of_day() and not self._fav_used:
            self._fav_used = True
            boosted = min(2, note + 1)
            if boosted >= int(self.taste.ctx("favorita_dia_amor_min", 1)):
                return "music_love", "favorita", None
            return "music_like", "favorita", None
        if plays >= int(self.taste.ctx("repeticao_acostuma", 5)):
            if note == 2:
                return "music_love", "quinta", "love"
            if note <= 0:
                return "music_tolerate", None, None
        if note == 2:
            if v.rival:
                return "music_love", "rival", self.taste.section("rivais").get("humor", "happy")
            if gaming and "trilha" in v.genres:
                return "music_love", "batalha", self.taste.mood("music_love_batalha", "focus")
            return "music_love", "madrugada" if night else None, None
        if note == -2:
            early = hour < int(self.taste.ctx("sem_careta_ate", 8))
            recent = now - self._last_hate < 60 * float(self.taste.ctx("careta_intervalo_min", 30))
            if early or recent:
                return "music_meh", None, "sleepy" if early else None
            self._last_hate = now
            return "music_hate", "slowed" if v.slowed else None, None
        return MUSIC_BY_NOTE[note], None, None

    def _remember(self, artist: str) -> None:
        self._seen.add(norm(artist))
        try:
            self.seen_file.parent.mkdir(parents=True, exist_ok=True)
            self.seen_file.write_text(json.dumps({"artists": sorted(self._seen)}, ensure_ascii=False),
                                      encoding="utf-8")
        except OSError:
            pass
