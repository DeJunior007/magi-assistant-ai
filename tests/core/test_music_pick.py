"""Testes do "coloca uma boa" (2.5): API falsa, gosto em memória, relógio falso."""

from __future__ import annotations

import asyncio
import random
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from magi.common.contracts import (
    ActionRequest,
    Intent,
    IntentId,
    MusicSignal,
    MusicSignalValue,
    Slot,
    TasteEntry,
    TurnContext,
    WakeSource,
)
from magi.core.actions.spotify_api import SpotifyApiError
from magi.core.music import pick
from magi.core.music.pick import ArtistInfo, GameInfo, GenreCache, MusicPicker, wish_for

ARTISTS = ["Calmo", "Agitado", "Anime", "Rapper", "Indie"]
INFO = {
    "Calmo": ArtistInfo(("lofi", "jazz"), 1.0),
    "Agitado": ArtistInfo(("rock", "metal"), 5.0),
    "Anime": ArtistInfo(("anime", "j-rock"), 4.0),
    "Rapper": ArtistInfo(("hip-hop",), 3.0),
    "Indie": ArtistInfo(("indie",), 2.5),
}


def tr(artist: str, n: int) -> dict[str, Any]:
    return {
        "uri": f"spotify:track:{artist}{n}",
        "name": f"{artist} {n}",
        "artists": [{"name": artist, "id": f"id-{artist}"}],
    }


class FakeApi:
    market = "BR"

    def __init__(self, *, top_tracks_status: int | None = None, delay: float = 0.0) -> None:
        self.calls: list[str] = []
        self.top_tracks_status = top_tracks_status
        self.delay = delay

    async def get(self, path: str, params: Any = None) -> dict[str, Any]:
        self.calls.append(path)
        if self.delay:
            await asyncio.sleep(self.delay)
        if path == "/me/top/tracks":
            return {"items": [tr(a, i) for a in ARTISTS for i in (1, 2)]}
        if path.endswith("/top-tracks"):
            if self.top_tracks_status:
                raise SpotifyApiError(self.top_tracks_status, "nope")
            a = path.split("/")[2].removeprefix("id-")
            return {"tracks": [tr(a, i) for i in range(1, 6)]}
        raise AssertionError(path)

    async def search(self, query: str, types: Any = (), limit: int = 5) -> dict[str, Any]:
        self.calls.append(f"search:{query}:{','.join(types)}")
        a = query.split('"')[1]
        if tuple(types) == ("artist",):
            return {"artists": {"items": [{"name": a, "id": f"id-{a}"}]}}
        return {"tracks": {"items": [tr(a, i) for i in (7, 8)]}}


class FakeTaste:
    def __init__(self, weights: dict[str, float]) -> None:
        self.weights = weights

    async def top(self, limit: int = 50, genre: str | None = None) -> list[TasteEntry]:
        es = [TasteEntry(a, "", w) for a, w in self.weights.items()]
        return sorted(es, key=lambda e: -e.weight)[:limit]


class FakeRepo:
    def __init__(self) -> None:
        self.rows: list[MusicSignal] = []

    async def recent(self, limit: int = 100) -> list[MusicSignal]:
        return self.rows[:limit]


class FakeSignals:
    def __init__(self, banned: set[str] | None = None) -> None:
        self._banned = banned or set()
        self.repo = FakeRepo()
        self.picked: list[tuple[str, str]] = []

    async def banned(self) -> set[str]:
        return set(self._banned)

    def mark_picked(self, uri: str, request: str = "") -> None:
        self.picked.append((uri, request))


class FakePlayer:
    def __init__(self) -> None:
        self.opened: list[str] = []

    async def open_uri(self, uri: str) -> None:
        self.opened.append(uri)


class Clock:
    def __init__(self, hour: int) -> None:
        self.t = datetime(2026, 10, 3, hour, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t


def make(
    hour: int = 15,
    weights: dict[str, float] | None = None,
    seed: int = 0,
    banned: set[str] | None = None,
    game: GameInfo | None = None,
    api: FakeApi | None = None,
) -> tuple[MusicPicker, FakeSignals, FakePlayer, Clock]:
    genres = GenreCache()
    genres.put(INFO)
    sig, player, clock = FakeSignals(banned), FakePlayer(), Clock(hour)
    p = MusicPicker(
        player,
        api or FakeApi(),
        sig,
        FakeTaste(weights or dict.fromkeys(ARTISTS, 0.5)),
        genres,
        game=lambda: game,
        now=clock,
        rng=random.Random(seed),
    )
    return p, sig, player, clock


def req(text: str = "coloca uma boa", query: str | None = None) -> ActionRequest:
    slots = (Slot("query", query),) if query else ()
    ctx = TurnContext("pc", WakeSource.PTT, datetime.now(UTC))
    return ActionRequest(Intent(IntentId.MUSIC_PICK.value, slots), ctx, text)


async def artists_over_seeds(n: int = 60, text: str = "", **kw: Any) -> Counter[str]:
    c: Counter[str] = Counter()
    for seed in range(n):
        p, *_ = make(seed=seed, **kw)
        ch = await p.choose(text)
        assert ch is not None
        c[ch.track.artist] += 1
    return c


async def test_nunca_escolhe_faixa_banida() -> None:
    banned = {f"spotify:track:{a}{i}" for a in ARTISTS for i in (1, 2)}
    banned |= {f"spotify:track:{a}{i}" for a in ("Calmo", "Agitado") for i in range(1, 9)}
    ok = 0
    for seed in range(40):
        p, sig, player, _ = make(seed=seed, banned=banned)
        for _ in range(4):
            res = await p.pick(req())
            if res.ok:
                ok += 1
                assert player.opened[-1] not in banned
    assert ok > 100


async def test_artista_com_peso_negativo_fica_de_fora() -> None:
    c = await artists_over_seeds(weights={"Calmo": -0.4, "Agitado": 0.5, "Indie": 0.5})
    assert "Calmo" not in c


async def test_horario_noite_prefere_calmo() -> None:
    w = {"Calmo": 0.5, "Agitado": 0.5}
    night = await artists_over_seeds(hour=23, weights=w)
    day = await artists_over_seeds(hour=15, weights=w)
    assert night["Calmo"] > night["Agitado"]
    assert night["Calmo"] > day["Calmo"]


async def test_pedido_muda_a_escolha() -> None:
    w = {"Calmo": 0.5, "Agitado": 0.5, "Anime": 0.3, "Rapper": 0.6}
    animado = await artists_over_seeds(text="algo animado", weights=w)
    focar = await artists_over_seeds(text="coloca uma boa pra focar", weights=w)
    anime = await artists_over_seeds(text="um anime opening", weights=w)
    assert animado["Agitado"] > animado["Calmo"]
    assert focar["Calmo"] > focar["Agitado"]
    assert set(anime) == {"Anime"}  # gênero pedido filtra


async def test_jogo_aberto_muda_a_escolha() -> None:
    w = {"Calmo": 0.5, "Agitado": 0.5}
    fps = await artists_over_seeds(weights=w, game=GameInfo("Doom", ("FPS", "Action")))
    cozy = await artists_over_seeds(weights=w, game=GameInfo("Stardew Valley", ("Farming Sim", "Relaxing")))
    assert fps["Agitado"] > fps["Calmo"]
    assert cozy["Calmo"] > cozy["Agitado"]


def test_wish_prioridade() -> None:
    game = GameInfo("Doom", ("FPS",))
    assert wish_for("pra focar", 15, game).why == "pra focar"
    assert wish_for("", 15, game).why == "combinando com Doom"
    assert wish_for("", 23).energy == 2.0
    assert wish_for("", 15).energy is None


async def test_variedade_nao_repete_artista_recente() -> None:
    p, sig, player, clock = make(seed=3)
    seen: list[str] = []
    for _ in range(8):
        res = await p.pick(req())
        assert res.ok
        seen.append(player.opened[-1].removeprefix("spotify:track:")[:-1])
        clock.t += timedelta(minutes=4)
    for i in range(1, len(seen)):
        assert seen[i] not in seen[max(0, i - pick.RECENT_ARTISTS) : i]
    assert len(set(player.opened)) == len(player.opened)


async def test_evita_o_que_tocou_nas_ultimas_horas() -> None:
    p, sig, player, clock = make(weights={"Calmo": 1.0})
    for i in (1, 2):
        sig.repo.rows.append(
            MusicSignal(
                f"spotify:track:Calmo{i}", "Calmo", MusicSignalValue.FINISHED, clock.t - timedelta(hours=1)
            )
        )
    ch = await p.choose()
    assert ch is not None and ch.track.uri not in {"spotify:track:Calmo1", "spotify:track:Calmo2"}


async def test_toca_marca_e_responde_curto() -> None:
    p, sig, player, _ = make(weights={"Calmo": 1.0}, hour=23)
    res = await p.pick(req())
    assert res.ok and player.opened and sig.picked == [(player.opened[0], "coloca uma boa")]
    assert res.speech.startswith("Coloquei Calmo") and "essa hora" in res.speech


async def test_handler_usa_slot_query() -> None:
    p, sig, player, _ = make()
    h = pick.handlers(p)[0]
    res = await h.run(req("toca uma boa", query="anime opening"))
    assert res.ok and "Anime" in player.opened[0]
    assert sig.picked[0][1] == "anime opening"


async def test_top_tracks_do_artista_negado_usa_busca() -> None:
    api = FakeApi(top_tracks_status=403)
    banned = {f"spotify:track:Calmo{i}" for i in (1, 2)}
    p, *_ = make(weights={"Calmo": 1.0}, api=api, banned=banned)
    ch = await p.choose()
    assert ch is not None and ch.track.uri in {"spotify:track:Calmo7", "spotify:track:Calmo8"}
    await p.choose()
    assert sum(c.endswith("/top-tracks") for c in api.calls) == 1  # não insiste no 403


async def test_latencia_sem_llm() -> None:
    p, *_ = make()
    p.genres = GenreCache()  # sem gêneros classificados: escolhe só pelo peso, sem chamar modelo
    t0 = time.perf_counter()
    res = await p.pick(req("coloca uma boa pra focar"))
    assert res.ok and time.perf_counter() - t0 < 0.5


async def test_api_lenta_responde_no_prazo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pick, "PICK_TIMEOUT_S", 0.05)
    p, *_ = make(api=FakeApi(delay=1.0))
    t0 = time.perf_counter()
    res = await p.pick(req())
    assert not res.ok and time.perf_counter() - t0 < 0.5


class FakeChat:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def chat(self, messages: Any, *, json_mode: bool = False, personal: bool) -> Any:
        import json

        assert personal is False and json_mode
        asked = json.loads(messages[-1].content)
        self.calls.append(asked)
        body = {a: {"genres": ["rock", "inventado"], "energy": 9} for a in asked if a != "Rapper"}

        class R:
            text = "```json\n" + json.dumps(body) + "\n```"

        return R()


async def test_cache_de_generos(tmp_path: Any) -> None:
    path = tmp_path / pick.GENRE_FILE
    cache = GenreCache(path)
    cache.put({"Calmo": ArtistInfo(("lofi",), 1.0)})
    chat = FakeChat()
    taste = FakeTaste({"Calmo": 0.9, "Agitado": 0.5, "Rapper": 0.4, "Ruim": -0.5})
    n = await pick.fill_genres(taste, cache, chat, batch=1)
    assert n == 2 and sorted(sum(chat.calls, [])) == ["Agitado", "Rapper"]
    again = GenreCache(path)  # persistido
    assert again.get("agitado") == ArtistInfo(("rock",), 5.0)  # gênero fora do vocabulário some
    assert again.get("Rapper") == ArtistInfo()  # ignorado pelo modelo: não pergunta de novo
    assert again.get("Calmo") == ArtistInfo(("lofi",), 1.0)
    assert await pick.fill_genres(taste, again, chat) == 0 and len(chat.calls) == 2
