"""Steam local: horas e conquistas lidas do disco, sem rede, sem chave e sem IA.

- **Horas:** ``Playtime`` (minutos) e ``LastPlayed`` do ``userdata/<id>/config/localconfig.vdf``
  da conta em uso (o modificado por último; mesmo leitor das notícias, ``magi.news.progress``).
- **Conquistas:** o cliente da Steam guarda em ``appcache/stats`` dois KeyValues binários por jogo:
  ``UserGameStatsSchema_<appid>.bin`` (nomes e descrições em todos os idiomas, inclusive
  ``brazilian``) e ``UserGameStats_<conta>_<appid>.bin`` (bits desbloqueados e a hora de cada um).
  Só existe para jogos que a Steam já abriu nesta máquina; sem eles, ``None``.

Uso no núcleo: a linha do jogo no prompt (horas, conquistas, a última), o gancho
``achievements_idle`` da ajuda em degraus (4.5) e a ferramenta ``steam_game`` do agente.
"""

from __future__ import annotations

import logging
import struct
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from magi.core.catalog import default_steam_root, parse_vdf, scan_games

log = logging.getLogger(__name__)

__all__ = ["Achievement", "GameStats", "SteamLocal", "parse_binary_vdf"]

LANGS = ("brazilian", "portuguese", "english")


def parse_binary_vdf(data: bytes) -> dict[str, Any]:
    """KeyValues binário da Steam (tipos 0 objeto, 1 texto, 2 int32, 3 float, 7 uint64, 8 fim)."""

    def node(i: int) -> tuple[dict[str, Any], int]:
        out: dict[str, Any] = {}
        while i < len(data):
            kind = data[i]
            i += 1
            if kind in (0x08, 0x0B):
                return out, i
            end = data.index(b"\0", i)
            key = data[i:end].decode("utf-8", "replace")
            i = end + 1
            if kind == 0x00:
                out[key], i = node(i)
            elif kind == 0x01:
                end = data.index(b"\0", i)
                out[key] = data[i:end].decode("utf-8", "replace")
                i = end + 1
            elif kind in (0x02, 0x04, 0x06):
                out[key] = struct.unpack_from("<i", data, i)[0]
                i += 4
            elif kind == 0x03:
                out[key] = struct.unpack_from("<f", data, i)[0]
                i += 4
            elif kind in (0x07, 0x0A):
                out[key] = struct.unpack_from("<Q", data, i)[0]
                i += 8
            else:
                raise ValueError(f"tipo {kind:#x} desconhecido na posição {i - 1}")
        return out, i

    return node(0)[0]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if c.isalnum() or c == " ").strip()


def _text(display: Any) -> str:
    if isinstance(display, str):
        return display
    if isinstance(display, dict):
        for lang in LANGS:
            if display.get(lang):
                return str(display[lang])
    return ""


@dataclass(frozen=True)
class Achievement:
    api: str
    name: str
    desc: str
    hidden: bool = False
    got: bool = False  # desbloqueada
    unlocked_at: float | None = None  # epoch do desbloqueio (None = bloqueada ou sem data)


@dataclass
class GameStats:
    appid: int
    name: str = ""
    minutes: int | None = None  # tempo total jogado
    last_played: float | None = None
    achievements: list[Achievement] = field(default_factory=list)

    @property
    def unlocked(self) -> list[Achievement]:
        return sorted((a for a in self.achievements if a.got), key=lambda a: -(a.unlocked_at or 0))

    @property
    def locked(self) -> list[Achievement]:
        return [a for a in self.achievements if not a.got]

    @property
    def last_unlock(self) -> Achievement | None:
        got = self.unlocked
        return got[0] if got else None

    def summary(self, now: float | None = None) -> str:
        """Uma linha para o prompt: "92 h no total; conquistas 31/44, a última há 3 dias (O Louco)"."""
        now = time.time() if now is None else now
        parts = []
        if self.minutes is not None:
            hours = f"{self.minutes / 60:.0f} h" if self.minutes >= 60 else f"{self.minutes} min"
            parts.append(f"{hours} no total")
        if self.achievements:
            s = f"conquistas {len(self.unlocked)}/{len(self.achievements)}"
            last = self.last_unlock
            if last is not None and last.unlocked_at:
                s += f", a última {ago(now - last.unlocked_at)} ({last.name})"
            parts.append(s)
        return "; ".join(parts)


def ago(seconds: float) -> str:
    m = max(0, int(seconds // 60))
    if m < 60:
        return "agora há pouco" if m < 2 else f"há {m} min"
    h = m // 60
    if h < 48:
        return f"há {h} h"
    return f"há {h // 24} dias"


class SteamLocal:
    """Leitor do disco da Steam. Lê sob demanda e guarda por mtime (arquivos pequenos)."""

    def __init__(self, steam_root: Path | None = None) -> None:
        self.root = steam_root or default_steam_root()
        self._cache: dict[Path, tuple[float, Any]] = {}

    # -- arquivos -------------------------------------------------------------------------------

    def _load(self, path: Path, binary: bool) -> Any:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        hit = self._cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            data = parse_binary_vdf(path.read_bytes()) if binary else parse_vdf(
                path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError, struct.error) as exc:
            log.warning("steam: não li %s (%s)", path, exc)
            data = None
        self._cache[path] = (mtime, data)
        return data

    def localconfig(self) -> Path | None:
        try:
            found = [(p.stat().st_mtime, p)
                     for p in (self.root / "userdata").glob("*/config/localconfig.vdf")]
        except OSError:
            return None
        return max(found)[1] if found else None

    def account(self) -> str | None:
        cfg = self.localconfig()
        return cfg.parent.parent.name if cfg else None

    # -- horas ----------------------------------------------------------------------------------

    def playtime(self, appid: int) -> tuple[int | None, float | None]:
        """(minutos, último dia jogado em epoch) do ``localconfig.vdf``; (None, None) sem registro."""
        cfg = self.localconfig()
        data = self._load(cfg, binary=False) if cfg else None
        apps = _ci(data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps") or {}
        entry = apps.get(str(appid)) if isinstance(apps, dict) else None
        if not isinstance(entry, dict):
            return None, None
        minutes, last = _ci(entry, "Playtime"), _ci(entry, "LastPlayed")
        return (int(minutes) if str(minutes or "").isdigit() else None,
                float(last) if str(last or "").isdigit() else None)

    # -- conquistas -----------------------------------------------------------------------------

    def achievements(self, appid: int) -> list[Achievement]:
        stats = self.root / "appcache" / "stats"
        schema = self._load(stats / f"UserGameStatsSchema_{appid}.bin", binary=True) or {}
        account = self.account()
        user = self._load(stats / f"UserGameStats_{account}_{appid}.bin", binary=True) if account else None
        cache = (user or {}).get("cache", {}) if isinstance(user, dict) else {}
        game = schema.get(str(appid), {}) if isinstance(schema, dict) else {}
        out: list[Achievement] = []
        for stat_id, stat in (game.get("stats") or {}).items():
            bits = stat.get("bits") if isinstance(stat, dict) else None
            if not isinstance(bits, dict):
                continue
            mine = cache.get(stat_id, {}) if isinstance(cache, dict) else {}
            mask = int(mine.get("data", 0)) & 0xFFFFFFFF if isinstance(mine, dict) else 0
            times = mine.get("AchievementTimes", {}) if isinstance(mine, dict) else {}
            for bit, ach in bits.items():
                if not isinstance(ach, dict) or not str(bit).isdigit():
                    continue
                display = ach.get("display") or {}
                got = bool(mask >> int(bit) & 1)
                when = times.get(str(bit)) if isinstance(times, dict) else None
                out.append(Achievement(
                    api=str(ach.get("name", "")),
                    name=_text(display.get("name")) or str(ach.get("name", "")),
                    desc=_text(display.get("desc")),
                    hidden=bool(int(ach.get("hidden", 0) or 0)),
                    got=got,
                    unlocked_at=float(when) if got and when else None,
                ))
        return out

    # -- tudo junto -----------------------------------------------------------------------------

    def stats(self, appid: int, name: str = "") -> GameStats:
        minutes, last = self.playtime(appid)
        return GameStats(appid, name, minutes, last, self.achievements(appid))

    def find(self, name: str) -> tuple[int, str] | None:
        """(appid, nome) do jogo instalado cujo nome mais combina com ``name``."""
        want = _norm(name)
        if not want:
            return None
        best: tuple[int, int, str] | None = None
        for g in scan_games(self.root):
            have = _norm(g.name)
            if have == want:
                return g.appid, g.name
            if want in have or have in want:
                score = -abs(len(have) - len(want))
                if best is None or score > best[0]:
                    best = (score, g.appid, g.name)
        return (best[1], best[2]) if best else None

    def idle_minutes(self, appid: int, now: float | None = None) -> float | None:
        """Minutos desde a última conquista (``None`` se o jogo não tem conquistas no disco)."""
        ach = self.achievements(appid)
        if not ach:
            return None
        last = max((a.unlocked_at or 0.0 for a in ach), default=0.0)
        if not last:
            return None
        return ((time.time() if now is None else now) - last) / 60


def _ci(d: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(d, dict):
            return None
        low = key.lower()
        d = next((v for k, v in d.items() if k.lower() == low), None)
    return d
