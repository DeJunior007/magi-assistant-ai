"""Catálogo de jogos instalados da Steam (R4.4, R5.1, R5.2, §4.2, tarefa 1.7).

Lê os ``appmanifest_*.acf`` de todas as bibliotecas (``steamapps/libraryfolders.vdf``), ignora
ferramentas (Proton, Steam Linux Runtime, redistribuíveis), junta os apelidos aprendidos e faz
busca aproximada com ``rapidfuzz`` pensada para nomes falados em PT-BR: números por extenso
("três" → 3), romanos ("III" → 3) e grafias fonéticas ("dedi cels" → Dead Cells).

Só lê arquivos da Steam; a única escrita é a do repositório de apelidos.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from rapidfuzz import fuzz

from magi.common.contracts import Game, VocabRepo, VocabTerm

log = logging.getLogger(__name__)

__all__ = [
    "AliasStore",
    "JsonAliasStore",
    "MemoryAliasStore",
    "SteamCatalog",
    "default_steam_root",
    "is_tool",
    "library_dirs",
    "normalize",
    "parse_vdf",
    "read_manifest",
    "scan_games",
]

# ---------------------------------------------------------------------------
# VDF/ACF


def parse_vdf(text: str) -> dict[str, Any]:
    """Parser mínimo de KeyValues da Valve (texto): strings entre aspas e blocos ``{}``.

    Chaves repetidas: vale a última. Texto malformado devolve o que deu para ler.
    """
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root: dict[str, Any] = {}
    stack: list[dict[str, Any]] = [root]
    key: str | None = None
    for quoted, brace in tokens:
        if brace == "{":
            child: dict[str, Any] = {}
            if key is not None:
                stack[-1][key] = child
                key = None
            stack.append(child)
        elif brace == "}":
            key = None
            if len(stack) > 1:
                stack.pop()
        else:
            value = re.sub(r"\\(.)", r"\1", quoted)
            if key is None:
                key = value
            else:
                stack[-1][key] = value
                key = None
    return root


def _ci_get(d: Mapping[str, Any], key: str) -> Any:
    """Busca sem diferenciar maiúsculas (o VDF real mistura ``AppState``/``appstate``)."""
    if key in d:
        return d[key]
    low = key.lower()
    for k, v in d.items():
        if k.lower() == low:
            return v
    return None


def default_steam_root() -> Path:
    return Path(os.path.expanduser("~/.local/share/Steam"))


def library_dirs(steam_root: Path) -> list[Path]:
    """Diretórios ``steamapps`` de todas as bibliotecas, sem repetição (raiz primeiro)."""
    dirs = [steam_root / "steamapps"]
    vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
    try:
        data = parse_vdf(vdf_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        data = {}
    folders = _ci_get(data, "libraryfolders")
    if isinstance(folders, dict):
        for entry in folders.values():
            path = _ci_get(entry, "path") if isinstance(entry, dict) else None
            if isinstance(path, str) and path:
                dirs.append(Path(path) / "steamapps")
    out: list[Path] = []
    seen: set[Path] = set()
    for d in dirs:
        try:
            real = d.resolve()
        except OSError:
            real = d
        if real not in seen:
            seen.add(real)
            out.append(d)
    return out


def read_manifest(path: Path) -> Game | None:
    """Lê um ``appmanifest_*.acf``; ``None`` se ilegível ou sem ``appid``/``name``."""
    try:
        data = parse_vdf(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    state = _ci_get(data, "AppState")
    if not isinstance(state, dict):
        return None
    appid, name = _ci_get(state, "appid"), _ci_get(state, "name")
    if not isinstance(appid, str) or not appid.isdigit() or not isinstance(name, str) or not name.strip():
        return None
    install_dir = _ci_get(state, "installdir")
    install_dir = install_dir if isinstance(install_dir, str) else ""
    return Game(appid=int(appid), name=name.strip(), install_dir=install_dir)


# Ferramentas que a Steam instala como "apps": nunca são jogos.
_TOOL_APPIDS = frozenset(
    {
        228980,  # Steamworks Common Redistributables
        1070560,  # Steam Linux Runtime 1.0 (scout)
        1391110,  # Steam Linux Runtime 2.0 (soldier)
        1628350,  # Steam Linux Runtime 3.0 (sniper)
        1493710,  # Proton Experimental
        2180100,  # Proton Hotfix
        1826330,  # Proton EasyAntiCheat Runtime
        1161040,  # Proton BattlEye Runtime
    }
)
_TOOL_NAME = re.compile(
    r"^(proton\b|steam linux runtime|steamworks common redistributables|steamvr\b|"
    r"steam runtime|steam audio|.*\bdedicated server$|.*\bsdk$)",
    re.IGNORECASE,
)


def is_tool(game: Game) -> bool:
    """Proton, runtimes, redistribuíveis, servidores dedicados e SDKs."""
    return game.appid in _TOOL_APPIDS or bool(_TOOL_NAME.match(game.name.strip()))


def scan_games(steam_root: Path) -> list[Game]:
    """Todos os jogos (sem ferramentas) das bibliotecas, sem appid repetido, por nome."""
    games: dict[int, Game] = {}
    for lib in library_dirs(steam_root):
        try:
            manifests = sorted(lib.glob("appmanifest_*.acf"))
        except OSError:
            continue
        for path in manifests:
            game = read_manifest(path)
            if game is None or is_tool(game) or game.appid in games:
                continue
            games[game.appid] = game
    return sorted(games.values(), key=lambda g: g.name.casefold())


# ---------------------------------------------------------------------------
# Normalização e busca

_NUMBER_WORDS = {
    # PT-BR
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13,
    "catorze": 14, "quatorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18,
    "dezenove": 19, "vinte": 20,
    # EN (nome original falado)
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}  # fmt: skip
# "i" fica de fora: é palavra comum em inglês.
_ROMAN = {
    "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
    "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15, "xvi": 16,
}  # fmt: skip


def normalize(text: str) -> str:
    """Minúsculas, sem acento nem pontuação; números por extenso e romanos viram dígitos."""
    text = re.sub(r"[™®©℠]", " ", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("&", " and ").replace("'", "").replace("’", "")
    words = re.findall(r"[a-z0-9]+", text)
    out = []
    for w in words:
        n = _NUMBER_WORDS.get(w, _ROMAN.get(w))
        out.append(str(n) if n is not None else w)
    return " ".join(out)


# Grafia "como se fala": aproxima o que o STT escreve em PT-BR de nomes em inglês.
_PHONETIC = [
    (r"^kn", "n"),
    (r"igh", "ai"),
    (r"ph", "f"),
    (r"ck", "k"),
    (r"qu", "k"),
    (r"q", "k"),
    (r"c(?=[eiy])", "s"),
    (r"c", "k"),
    (r"sh", "x"),
    (r"ch", "x"),
    (r"th", "t"),
    (r"ow", "ou"),
    (r"w", "u"),
    (r"y", "i"),
    (r"z", "s"),
    (r"h", ""),
    (r"ee|ie", "i"),
    (r"ea", "e"),
    (r"oo|ou", "u"),
    (r"(.)\1+", r"\1"),
    # vogal de apoio no fim, comum na fala em PT ("dedi" ~ "dead", "naite" ~ "night")
    (r"(?<=[^aeiou])[ei]$", ""),
    # encontros de vogais são instáveis na transcrição: fica a primeira
    (r"(?<=[a-z])([aeiou])[aeiou]+(?=[a-z])", r"\1"),
]


def _phonetic_word(word: str) -> str:
    if word.isdigit():
        return word
    for pattern, repl in _PHONETIC:
        word = re.sub(pattern, repl, word)
    return word


def _phonetic(norm: str) -> str:
    """Grafia "como se fala", palavra a palavra (espaços mantidos)."""
    return " ".join(w for w in map(_phonetic_word, norm.split()) if w)


class _Key:
    """Formas pré-calculadas de um nome (ou apelido) para a busca."""

    __slots__ = ("norm", "short", "compact", "phon", "exact")

    def __init__(self, text: str, exact: bool = False) -> None:
        self.norm = normalize(text)
        # sem subtítulo: "The Witcher 3: Wild Hunt" → "the witcher 3"
        head = re.split(r"\s*[:\-–—]\s+|\s*:\s*", text, maxsplit=1)[0]
        self.short = normalize(head) or self.norm
        self.compact = self.norm.replace(" ", "")
        self.phon = _phonetic(self.norm)
        self.exact = exact


_NUMBER_MISMATCH_CAP = 80.0


def _score(query: str, key: _Key) -> tuple[float, float]:
    """(nota 0..100, desempate). Junta várias medidas e fica com a melhor."""
    q_norm = query
    if not q_norm or not key.norm:
        return 0.0, 0.0
    q_compact = q_norm.replace(" ", "")
    if q_norm in (key.norm, key.short) or q_compact == key.compact:
        return 100.0, 100.0
    full = fuzz.ratio(q_norm, key.norm)
    short = fuzz.ratio(q_norm, key.short)
    compact = fuzz.ratio(q_compact, key.compact)
    # subconjunto de palavras ("witcher 3" ⊂ "the witcher 3 wild hunt"); vale menos que o exato
    subset = fuzz.token_set_ratio(q_norm, key.norm) * 0.95
    q_phon = _phonetic(q_norm)
    phon = max(
        fuzz.ratio(q_phon.replace(" ", ""), key.phon.replace(" ", "")) * 0.97,
        fuzz.token_set_ratio(q_phon, key.phon) * 0.93,
    )
    best = max(full, short, compact, subset, phon)
    # número falado que o nome não tem ("portal 2" com só "Portal" instalado): no máximo "dúvida"
    if set(re.findall(r"\d+", q_norm)) - set(re.findall(r"\d+", key.norm)):
        best = min(best, _NUMBER_MISMATCH_CAP)
    return round(best, 1), max(full, short, compact)


# ---------------------------------------------------------------------------
# Apelidos


@runtime_checkable
class AliasStore(Protocol):
    """Repositório de apelidos aprendidos (appid → apelidos). Implementação injetável."""

    def load(self) -> dict[int, list[str]]: ...

    async def add(self, appid: int, alias: str) -> None: ...


class MemoryAliasStore:
    """Apelidos só em memória (testes, ou sem persistência)."""

    def __init__(self, initial: Mapping[int, Iterable[str]] | None = None) -> None:
        self._data = {int(k): list(v) for k, v in (initial or {}).items()}

    def load(self) -> dict[int, list[str]]:
        return {k: list(v) for k, v in self._data.items()}

    async def add(self, appid: int, alias: str) -> None:
        items = self._data.setdefault(appid, [])
        if alias not in items:
            items.append(alias)


def _default_alias_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "magi" / "game_aliases.json"


class JsonAliasStore:
    """Apelidos num JSON local ``{"<appid>": ["apelido", ...]}`` (escrita atômica)."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _default_alias_path()
        self._lock = threading.Lock()

    def load(self) -> dict[int, list[str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            log.warning("apelidos ilegíveis em %s: %s", self.path, exc)
            return {}
        out: dict[int, list[str]] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if str(k).isdigit() and isinstance(v, list):
                    out[int(k)] = [str(a) for a in v if isinstance(a, str) and a.strip()]
        return out

    async def add(self, appid: int, alias: str) -> None:
        with self._lock:
            data = self.load()
            items = data.setdefault(appid, [])
            if alias in items:
                return
            items.append(alias)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            payload = {str(k): v for k, v in sorted(data.items())}
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)


# ---------------------------------------------------------------------------
# Catálogo


class SteamCatalog:
    """Implementa ``contracts.GameCatalog``.

    ``steam_root``: raiz da Steam (padrão ``~/.local/share/Steam``). ``aliases``: repositório de
    apelidos (padrão: JSON em ``$XDG_DATA_HOME/magi/game_aliases.json``). ``vocab``: se dado, cada
    apelido novo também vira ``VocabTerm(kind="nickname")`` para a dica do STT.
    A varredura é preguiçosa (no primeiro uso) e refeita com :meth:`refresh`.
    """

    def __init__(
        self,
        steam_root: Path | str | None = None,
        aliases: AliasStore | None = None,
        vocab: VocabRepo | None = None,
    ) -> None:
        self.steam_root = Path(steam_root) if steam_root is not None else default_steam_root()
        self._aliases: AliasStore = aliases if aliases is not None else JsonAliasStore()
        self._vocab = vocab
        self._games: dict[int, Game] | None = None
        self._keys: dict[int, list[_Key]] = {}

    # -- carga ------------------------------------------------------------

    def refresh(self) -> None:
        """Relê manifests e apelidos."""
        learned = self._aliases.load()
        games: dict[int, Game] = {}
        for game in scan_games(self.steam_root):
            aliases = tuple(dict.fromkeys(a.strip() for a in learned.get(game.appid, []) if a.strip()))
            games[game.appid] = replace(game, aliases=aliases)
        self._games = games
        self._keys = {appid: self._build_keys(g) for appid, g in games.items()}
        log.info("catálogo: %d jogos em %s", len(games), self.steam_root)

    @staticmethod
    def _build_keys(game: Game) -> list[_Key]:
        return [_Key(game.name), *(_Key(a, exact=True) for a in game.aliases)]

    def _ensure(self) -> dict[int, Game]:
        if self._games is None:
            self.refresh()
        assert self._games is not None
        return self._games

    # -- GameCatalog ------------------------------------------------------

    def all(self) -> list[Game]:
        return sorted(self._ensure().values(), key=lambda g: g.name.casefold())

    def get(self, appid: int) -> Game | None:
        return self._ensure().get(int(appid))

    def find(self, name: str, limit: int = 3) -> list[tuple[Game, float]]:
        """Candidatos por nota 0..100, maior primeiro. Apelido idêntico dá 100."""
        games = self._ensure()
        query = normalize(name)
        if not query or limit <= 0:
            return []
        ranked: list[tuple[float, float, str, Game]] = []
        for appid, game in games.items():
            best, tie = 0.0, 0.0
            for key in self._keys.get(appid, ()):
                s, t = _score(query, key)
                if key.exact and s == 100.0:
                    t = 101.0  # apelido aprendido vence empate com nome parecido
                if (s, t) > (best, tie):
                    best, tie = s, t
            if best > 0:
                ranked.append((best, tie, game.name.casefold(), game))
        ranked.sort(key=lambda r: (-r[0], -r[1], r[2]))
        return [(g, s) for s, _, _, g in ranked[:limit]]

    async def add_alias(self, appid: int, alias: str) -> None:
        """Aprende um apelido (ex.: "mãe do witcher" → 292030). Ignora appid desconhecido."""
        alias = " ".join(alias.split())
        games = self._ensure()
        game = games.get(int(appid))
        if game is None or not alias:
            log.warning("apelido %r ignorado: appid %s não está no catálogo", alias, appid)
            return
        if normalize(alias) in {normalize(a) for a in (game.name, *game.aliases)}:
            return
        await self._aliases.add(game.appid, alias)
        game = replace(game, aliases=(*game.aliases, alias))
        games[game.appid] = game
        self._keys[game.appid] = self._build_keys(game)
        if self._vocab is not None:
            await self._vocab.upsert(VocabTerm(term=alias, kind="nickname"))
