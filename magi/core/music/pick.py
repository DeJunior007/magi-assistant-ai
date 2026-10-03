""" "Coloca uma boa": escolha de faixa por gosto + contexto (tarefa 2.5, R8.1, R15.5).

Caminho do pedido (sem LLM, alvo ≤ 3 s):

1. Artistas do gosto com peso efetivo (``TasteRepo.top``, view ``taste_effective``); artista com peso
   ≤ 0 (muitos pulos ou "nunca mais") fica de fora.
2. Desejo do contexto (:func:`wish_for`): pedido livre ("pra focar", "algo animado", "um anime
   opening") > tags da Steam do jogo aberto (R15.5) > horário (madrugada/noite → mais calmo). Vira
   gêneros preferidos e uma energia alvo (1 calmo … 5 agitado).
3. Nota de cada artista = peso + afinidade de gênero + proximidade de energia (do cache de gêneros);
   artistas tocados nas últimas escolhas ou nas últimas horas perdem nota (variedade). Sorteio
   ponderado entre os melhores (``TOP_K``), para não tocar sempre o mesmo.
4. Faixas candidatas: top tracks do usuário daquele artista + top-tracks do artista na Web API (se
   o app em modo dev der 403/404, busca ``artist:"nome"``). Nunca faixa em ``banned()`` ("nunca
   mais", R8.5) nem tocada nas últimas ``RECENT_TRACK_H`` horas.
5. Toca pelo MPRIS (``open_uri``), chama ``MusicSignals.mark_picked`` (sinais da 2.4) e responde em
   uma frase o que escolheu e por quê.

Gêneros: apps novos do Spotify não recebem ``genres``. :func:`genre_loop` roda em segundo plano
(depois da importação do gosto) e classifica os artistas sem cache com o modelo da tarefa ``news``
(cota gratuita, ``personal=False``: só nomes de artistas, sem nada do usuário), em lotes, guardando
em ``artist-genres.json`` no diretório de dados (:class:`GenreCache`). O pedido só lê o cache.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import re
import time
import unicodedata
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx

from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    ActionResult,
    ChatMessage,
    Expression,
    IntentId,
    SlotName,
    TasteEntry,
)
from magi.core.actions.spotify_api import SAY_LOGIN, SpotifyApiError, SpotifyAuthError
from magi.core.actions.spotify_mpris import SAY_DBUS_FAILED, SAY_NOT_STARTED, MprisError, SpotifyNotRunning

log = logging.getLogger(__name__)

GENRE_FILE = "artist-genres.json"
#: Vocabulário fechado de gêneros (o classificador só pode usar estes).
GENRES = (
    "rock", "metal", "punk", "pop", "indie", "hip-hop", "rnb", "eletronica", "lofi", "jazz",
    "classica", "trilha", "anime", "j-pop", "j-rock", "vocaloid", "kpop", "mpb", "funk",
    "sertanejo", "latina", "reggae", "folk", "comedia",
)  # fmt: skip
TASTE_LIMIT = 400
TOP_K = 6
RECENT_ARTISTS = 3  # não repetir os últimos 3 artistas escolhidos
RECENT_TRACK_H = 6.0  # nem faixa (nem artista, com penalidade) tocada nessas horas
TOP_TRACKS_TTL_S = 6 * 3600.0
PICK_TIMEOUT_S = 2.5
SEARCH_LIMIT = 5
W_GENRE = 0.8
W_ENERGY = 0.5
RECENT_ARTIST_PENALTY = 0.6
NIGHT_HOURS = frozenset({22, 23, 0, 1, 2, 3, 4, 5})

SAY_EMPTY = "Ainda não conheço seu gosto; me deixa importar do Spotify primeiro."
SAY_NO_TRACK = "Não achei nada bom pra tocar agora."
SAY_API_FAILED = "Não consegui falar com o Spotify."


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


# --- desejo do contexto ---------------------------------------------------------------------


@dataclass(frozen=True)
class Wish:
    """O que o contexto pede. ``strict``: o pedido citou gênero; filtra se houver quem combine."""

    genres: frozenset[str] = frozenset()
    energy: float | None = None
    why: str = "uma que você curte"
    strict: bool = False


@dataclass(frozen=True)
class GameInfo:
    """Jogo aberto e suas tags da Steam (R15.5)."""

    name: str
    tags: tuple[str, ...] = ()


# (regex no texto normalizado, gêneros, energia, motivo, estrito)
_REQUEST_RULES: tuple[tuple[str, tuple[str, ...], float | None, str, bool], ...] = (
    (r"\b(anime|opening|abertura|animes)\b", ("anime", "j-pop", "j-rock"), None, "pro clima de anime", True),
    (
        r"\b(foc\w*|estud\w*|concentr\w*|trabalh\w*)\b",
        ("lofi", "trilha", "classica", "jazz"),
        2.0,
        "pra focar",
        False,
    ),
    (
        r"\b(animad\w*|agitad\w*|pesad\w*|treino|energia|empolg\w*|pilha)\b",
        ("rock", "metal", "eletronica"),
        4.5,
        "pra animar",
        False,
    ),
    (
        r"\b(calm\w*|relax\w*|tranquil\w*|dormir|suave|leve)\b",
        ("lofi", "indie", "jazz", "rnb"),
        1.5,
        "pra relaxar",
        False,
    ),
    (r"\b(rap|hip hop|hiphop|trap)\b", ("hip-hop",), None, "no rap", True),
    (r"\b(rock)\b", ("rock", "j-rock"), None, "no rock", True),
    (r"\b(metal)\b", ("metal",), None, "no metal", True),
    (r"\b(pop)\b", ("pop", "j-pop", "kpop"), None, "no pop", True),
    (r"\b(eletronic\w*|edm)\b", ("eletronica",), None, "na eletrônica", True),
    (r"\b(lofi|lo fi)\b", ("lofi",), 2.0, "no lofi", True),
    (r"\b(jazz)\b", ("jazz",), None, "no jazz", True),
    (r"\b(classic\w*)\b", ("classica",), 2.0, "no clássico", True),
    (r"\b(trilha|soundtrack|ost)\b", ("trilha",), None, "de trilha", True),
    (r"\b(kpop|k pop)\b", ("kpop",), None, "no k-pop", True),
    (r"\b(mpb|brasileir\w*)\b", ("mpb",), None, "na MPB", True),
    (r"\b(vocaloid)\b", ("vocaloid",), None, "no vocaloid", True),
)

# (tags da Steam em minúsculas, gêneros, energia)
_GAME_RULES: tuple[tuple[frozenset[str], tuple[str, ...], float], ...] = (
    (
        frozenset(
            {
                "fps",
                "shooter",
                "racing",
                "fighting",
                "hack and slash",
                "sports",
                "action",
                "competitive",
                "bullet hell",
                "roguelike",
                "arcade",
            }
        ),
        ("rock", "metal", "eletronica"),
        4.5,
    ),
    (
        frozenset({"rpg", "jrpg", "open world", "exploration", "adventure", "story rich", "fantasy"}),
        ("trilha", "anime", "j-rock"),
        3.0,
    ),
    (
        frozenset(
            {
                "puzzle",
                "casual",
                "relaxing",
                "cozy",
                "farming sim",
                "life sim",
                "building",
                "city builder",
                "strategy",
                "simulation",
            }
        ),
        ("lofi", "indie", "jazz"),
        2.0,
    ),
    (frozenset({"horror", "psychological horror"}), ("trilha", "eletronica"), 2.0),
)


def wish_for(text: str, hour: int, game: GameInfo | None = None) -> Wish:
    """Pedido livre > tags do jogo > horário."""
    t = norm(text)
    for rx, genres, energy, why, strict in _REQUEST_RULES:
        if re.search(rx, t):
            if energy is None and hour in NIGHT_HOURS:
                energy = 2.5
            return Wish(frozenset(genres), energy, why, strict)
    if game is not None:
        tags = {norm(x) for x in game.tags}
        extra = {"anime"} if "anime" in tags else set()
        for keys, genres, energy in _GAME_RULES:
            if tags & keys:
                return Wish(frozenset(genres) | extra, energy, f"combinando com {game.name}")
        if extra:
            return Wish(frozenset(extra), None, f"combinando com {game.name}")
    if hour in NIGHT_HOURS:
        return Wish(frozenset(), 2.0, "mais calminha pra essa hora")
    return Wish()


# --- cache de gêneros -----------------------------------------------------------------------


@dataclass(frozen=True)
class ArtistInfo:
    genres: tuple[str, ...] = ()
    energy: float = 3.0


class GenreCache:
    """Gêneros e energia por artista (chave normalizada). ``path=None``: só em memória."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._d: dict[str, ArtistInfo] = {}
        if path is not None and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    self._d[k] = ArtistInfo(tuple(v.get("genres") or ()), float(v.get("energy", 3)))
            except (OSError, ValueError, AttributeError):
                log.warning("cache de gêneros ilegível: %s", path)

    def get(self, artist: str) -> ArtistInfo | None:
        return self._d.get(norm(artist))

    def missing(self, artists: Iterable[str]) -> list[str]:
        return [a for a in artists if norm(a) not in self._d]

    def put(self, items: Mapping[str, ArtistInfo]) -> None:
        for a, info in items.items():
            self._d[norm(a)] = info
        self.save()

    def __len__(self) -> int:
        return len(self._d)

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: {"genres": list(v.genres), "energy": v.energy} for k, v in self._d.items()}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(self.path)


class ChatLike(Protocol):
    async def chat(
        self, messages: Sequence[ChatMessage], *, json_mode: bool = False, personal: bool
    ) -> Any: ...


GENRE_PROMPT = (
    "Classifique cada artista musical. Responda só JSON: um objeto com o nome exato de cada artista "
    'como chave e valor {"genres": [1 a 3 gêneros], "energy": 1-5}. Gêneros permitidos: '
    + ", ".join(GENRES)
    + ". energy: 1 = muito calmo, 3 = médio, 5 = muito agitado. Artistas japoneses de aberturas de "
    "anime levam 'anime'. Se não conhecer, chute pelo nome."
)


def parse_genres(text: str, asked: Sequence[str]) -> dict[str, ArtistInfo]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        raw = json.loads(m.group(0))
    except ValueError:
        return {}
    by_norm = {norm(a): a for a in asked}
    out: dict[str, ArtistInfo] = {}
    for k, v in raw.items() if isinstance(raw, dict) else ():
        a = by_norm.get(norm(str(k)))
        if a is None or not isinstance(v, dict):
            continue
        genres = tuple(g for g in (norm(str(x)) for x in v.get("genres") or ()) if g in GENRES)[:3]
        try:
            energy = min(5.0, max(1.0, float(v.get("energy", 3))))
        except (TypeError, ValueError):
            energy = 3.0
        out[a] = ArtistInfo(genres, energy)
    return out


async def classify_genres(chat: ChatLike, artists: Sequence[str]) -> dict[str, ArtistInfo]:
    msgs = [
        ChatMessage("system", GENRE_PROMPT),
        ChatMessage("user", json.dumps(list(artists), ensure_ascii=False)),
    ]
    reply = await chat.chat(msgs, json_mode=True, personal=False)
    return parse_genres(getattr(reply, "text", ""), artists)


async def fill_genres(taste: Any, cache: GenreCache, chat: ChatLike, *, batch: int = 40) -> int:
    """Classifica os artistas do gosto ainda sem cache. Devolve quantos entraram."""
    entries = await taste.top(TASTE_LIMIT)
    todo = cache.missing(dict.fromkeys(e.artist for e in entries if e.weight > 0 and e.artist))
    added = 0
    for i in range(0, len(todo), batch):
        part = todo[i : i + batch]
        got = await classify_genres(chat, part)
        # quem o modelo ignorou entra como desconhecido para não repetir a chamada sempre
        cache.put({a: got.get(a, ArtistInfo()) for a in part})
        added += len(part)
    return added


async def genre_loop(
    taste: Any, cache: GenreCache, chat: ChatLike, *, check_s: float = 3600.0, first_delay_s: float = 120.0
) -> None:
    """Tarefa de fundo: depois da importação, classifica os artistas novos de hora em hora."""
    await asyncio.sleep(first_delay_s)
    while True:
        try:
            n = await fill_genres(taste, cache, chat)
            if n:
                log.info("gêneros: %d artistas classificados (cache com %d)", n, len(cache))
        except Exception:
            log.exception("gêneros: classificação falhou")
        await asyncio.sleep(check_s)


# --- escolha ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Track:
    uri: str
    name: str
    artist: str
    artist_id: str = ""


def _track(item: Mapping[str, Any]) -> Track | None:
    uri = item.get("uri") or ""
    artists = item.get("artists") or []
    if not uri.startswith("spotify:track:") or not artists:
        return None
    return Track(uri, item.get("name") or "", artists[0].get("name") or "", artists[0].get("id") or "")


class Api(Protocol):
    market: str

    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]: ...

    async def search(self, query: str, types: Iterable[str] = ..., limit: int = ...) -> dict[str, Any]: ...


class Player(Protocol):
    async def open_uri(self, uri: str) -> None: ...


@dataclass
class Choice:
    track: Track
    why: str

    @property
    def speech(self) -> str:
        return f"Coloquei {self.track.name}, de {self.track.artist}, {self.why}."


@dataclass
class _Recent:
    picks: deque[tuple[str, str, datetime]] = field(default_factory=lambda: deque(maxlen=20))


class MusicPicker:
    """Escolhe e toca. ``taste``: ``TasteRepo`` (``None`` = só top tracks do usuário); ``signals``:
    ``MusicSignals`` (``banned``, ``repo.recent``, ``mark_picked``); ``game``: jogo aberto com tags
    (R15.5); ``now``/``rng``/``clock`` injetáveis para testes."""

    def __init__(
        self,
        player: Player,
        api: Api,
        signals: Any = None,
        taste: Any = None,
        genres: GenreCache | None = None,
        *,
        game: Callable[[], GameInfo | None] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.player = player
        self.api = api
        self.signals = signals
        self.taste = taste
        self.genres = genres or GenreCache()
        self.game = game
        self._now = now
        self._clock = clock
        self._rng = rng or random.Random()
        self._recent = _Recent()
        self._top: list[Track] = []
        self._top_at: float | None = None
        self._artist_ids: dict[str, str] = {}
        self._top_tracks_ok = True  # a Web API de apps dev pode negar /artists/{id}/top-tracks

    # -- dados ----------------------------------------------------------------------------------

    async def user_top_tracks(self) -> list[Track]:
        now = self._clock()
        if self._top_at is not None and now - self._top_at < TOP_TRACKS_TTL_S:
            return self._top
        out: list[Track] = []
        for rng in ("short_term", "medium_term"):
            try:
                d = await self.api.get("/me/top/tracks", {"time_range": rng, "limit": 50})
            except SpotifyApiError as e:
                log.warning("pick: top tracks %s indisponível (%s)", rng, e)
                continue
            out += [t for t in (_track(x) for x in d.get("items") or [] if x) if t]
        self._top, self._top_at = list({t.uri: t for t in out}.values()), now
        for t in self._top:
            if t.artist_id:
                self._artist_ids.setdefault(norm(t.artist), t.artist_id)
        return self._top

    async def artist_tracks(self, artist: str) -> list[Track]:
        aid = self._artist_ids.get(norm(artist))
        if aid is None:
            d = await self.api.search(f'artist:"{artist}"', ("artist",), 1)
            items = (d.get("artists") or {}).get("items") or []
            if items and norm(items[0].get("name") or "") == norm(artist):
                aid = self._artist_ids[norm(artist)] = items[0].get("id") or ""
        if aid and self._top_tracks_ok:
            try:
                d = await self.api.get(f"/artists/{aid}/top-tracks", {"market": self.api.market})
                return [t for t in (_track(x) for x in d.get("tracks") or [] if x) if t]
            except SpotifyApiError as e:
                if getattr(e, "status", 0) in (403, 404):
                    self._top_tracks_ok = False
                log.info("pick: top-tracks do artista indisponível (%s); usando a busca", e)
        d = await self.api.search(f'artist:"{artist}"', ("track",), SEARCH_LIMIT)
        tracks = [t for t in (_track(x) for x in (d.get("tracks") or {}).get("items") or [] if x) if t]
        return [t for t in tracks if norm(t.artist) == norm(artist)]

    async def _recently_played(self) -> tuple[set[str], set[str], list[str]]:
        """(faixas das últimas horas, artistas das últimas horas, últimos artistas escolhidos)."""
        now = self._now()
        cut = now - timedelta(hours=RECENT_TRACK_H)
        uris = {u for u, _, at in self._recent.picks if at >= cut}
        artists = {norm(a) for _, a, at in self._recent.picks if at >= cut}
        last = [norm(a) for _, a, _ in list(self._recent.picks)[-RECENT_ARTISTS:]]
        repo = getattr(self.signals, "repo", None)
        if repo is not None:
            with contextlib.suppress(Exception):
                for s in await repo.recent(100):
                    at = s.at if s.at.tzinfo else s.at.replace(tzinfo=UTC)
                    if at >= cut:
                        uris.add(s.track_uri)
                        if s.artist:
                            artists.add(norm(s.artist))
        return uris, artists, last

    async def _banned(self) -> set[str]:
        if self.signals is None:
            return set()
        return set(await self.signals.banned())

    # -- nota ----------------------------------------------------------------------------------

    def score(self, e: TasteEntry, wish: Wish, recent_artists: set[str]) -> float:
        info = self.genres.get(e.artist)
        s = e.weight
        if info is not None:
            if wish.genres and set(info.genres) & wish.genres:
                s += W_GENRE
            if wish.energy is not None:
                s += W_ENERGY * (1 - abs(info.energy - wish.energy) / 4)
        if norm(e.artist) in recent_artists:
            s -= RECENT_ARTIST_PENALTY
        return s

    def rank(
        self, entries: Sequence[TasteEntry], wish: Wish, recent: set[str], last: Sequence[str]
    ) -> list[str]:
        """Artistas na ordem de tentativa: sorteio ponderado entre os ``TOP_K`` melhores."""
        best: dict[str, TasteEntry] = {}
        for e in entries:
            if e.artist and e.weight > 0 and norm(e.artist) not in last:
                if e.artist not in best or e.weight > best[e.artist].weight:
                    best[e.artist] = e
        pool = list(best.values())
        if wish.strict:
            match = [e for e in pool if (i := self.genres.get(e.artist)) and set(i.genres) & wish.genres]
            pool = match or pool
        scored = sorted(((self.score(e, wish, recent), e.artist) for e in pool), reverse=True)[:TOP_K]
        order: list[str] = []
        while scored:
            w = [max(s, 0.01) for s, _ in scored]
            i = self._rng.choices(range(len(scored)), weights=w)[0]
            order.append(scored.pop(i)[1])
        return order

    # -- pedido ----------------------------------------------------------------------------------

    async def choose(self, text: str = "") -> Choice | None:
        now = self._now()
        game = self.game() if self.game is not None else None
        wish = wish_for(text, now.hour, game)
        banned = await self._banned()
        played, recent_artists, last = await self._recently_played()
        bad = banned | played
        entries: list[TasteEntry] = list(await self.taste.top(TASTE_LIMIT)) if self.taste is not None else []
        top = await self.user_top_tracks()
        if not entries:  # sem perfil: artistas das top tracks
            entries = [TasteEntry(t.artist, "", 1.0 / (1 + i)) for i, t in enumerate(top)]
        for artist in self.rank(entries, wish, recent_artists, last)[:3]:
            mine = [t for t in top if norm(t.artist) == norm(artist) and t.uri not in bad]
            if mine:
                return Choice(self._rng.choice(mine), wish.why)
            more = [t for t in await self.artist_tracks(artist) if t.uri not in bad]
            if more:
                return Choice(self._rng.choice(more[:5]), wish.why)
        rest = [t for t in top if t.uri not in bad and norm(t.artist) not in last]
        return Choice(self._rng.choice(rest), "uma das suas mais ouvidas") if rest else None

    async def pick(self, req: ActionRequest | None = None, text: str = "") -> ActionResult:
        confused = Expression.CONFUSED
        try:
            choice = await asyncio.wait_for(self.choose(text), PICK_TIMEOUT_S)
        except SpotifyAuthError:
            return ActionResult(ok=False, speech=SAY_LOGIN, expression=confused)
        except (TimeoutError, SpotifyApiError, httpx.HTTPError) as e:
            log.warning("pick: escolha falhou: %r", e)
            return ActionResult(ok=False, speech=SAY_API_FAILED, expression=confused)
        if choice is None:
            return ActionResult(ok=False, speech=SAY_NO_TRACK, expression=confused)
        try:
            await self.player.open_uri(choice.track.uri)
        except SpotifyNotRunning:
            return ActionResult(ok=False, speech=SAY_NOT_STARTED, expression=confused)
        except (MprisError, OSError) as e:
            log.warning("pick: OpenUri falhou: %r", e)
            return ActionResult(ok=False, speech=SAY_DBUS_FAILED, expression=confused)
        self._recent.picks.append((choice.track.uri, choice.track.artist, self._now()))
        if self.signals is not None:
            self.signals.mark_picked(choice.track.uri, request=text or "coloca uma boa")
        return ActionResult(ok=True, speech=choice.speech, expression=Expression.HAPPY)


class MusicPickHandler:
    """``ActionHandler`` de ``music.pick`` (R8.1). Pedido livre: slot ``query`` ou o texto do turno."""

    intents = frozenset({IntentId.MUSIC_PICK})

    def __init__(self, picker: MusicPicker) -> None:
        self.picker = picker

    async def run(self, req: ActionRequest) -> ActionResult:
        slot = req.intent.slot(SlotName.QUERY.value)
        return await self.picker.pick(req, slot.value if slot else req.text)


def handlers(picker: MusicPicker) -> list[ActionHandler]:
    return [MusicPickHandler(picker)]
