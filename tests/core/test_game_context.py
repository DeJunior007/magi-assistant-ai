"""Contexto de jogo (1.21): /proc falso, catálogo falso e Store via MockTransport."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from magi.common.contracts import ChatReply, Game, ProviderTask, TurnContext, WakeSource
from magi.core.actions import Registry
from magi.core.assemble import default_agent
from magi.core.game_context import GameWatcher, scan
from magi.core.music.pick import GameInfo, wish_for
from magi.core.steam_tags import SteamTags

BTIME = 1_000_000
TICK = os.sysconf("SC_CLK_TCK")
NOW = BTIME + 3600.0


class FakeCatalog:
    def __init__(self, *games: Game) -> None:
        self.games = {g.appid: g for g in games}

    def get(self, appid: int) -> Game | None:
        return self.games.get(appid)


class FakeProc:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir()
        (root / "stat").write_text(f"cpu  1 2 3\nbtime {BTIME}\n")
        (root / "self").mkdir()  # entradas não numéricas são ignoradas

    def add(self, pid: int, comm: str, env: dict[str, str] | None = None, start_s: float = 0.0) -> None:
        d = self.root / str(pid)
        d.mkdir()
        (d / "comm").write_text(comm + "\n")
        (d / "environ").write_bytes(b"\0".join(f"{k}={v}".encode() for k, v in (env or {}).items()) + b"\0")
        fields = ["S", "1", *["0"] * 17, str(int(start_s * TICK))]
        (d / "stat").write_text(f"{pid} ({comm}) {' '.join(fields)}\n")

    def kill(self, pid: int) -> None:
        d = self.root / str(pid)
        for f in d.iterdir():
            f.unlink()
        d.rmdir()


def store_payload(appid: int) -> dict:
    return {
        str(appid): {
            "success": True,
            "data": {
                "name": "Dead Cells",
                "genres": [{"id": "1", "description": "Action"}, {"id": "23", "description": "Indie"}],
                "categories": [{"id": 2, "description": "Single-player"}],
            },
        }
    }


class Store:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.host)
        if self.fail:
            return httpx.Response(503)
        if request.url.host == "store.steampowered.com":
            assert request.url.params["l"] == "english"
            return httpx.Response(200, json=store_payload(int(request.url.params["appids"])))
        tags = {"Roguelite": 900, "Metroidvania": 1200, "Pixel Graphics": 50}
        return httpx.Response(200, json={"tags": tags})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


def make_tags(tmp_path: Path, store: Store, now: float = NOW) -> SteamTags:
    return SteamTags(tmp_path / "cache" / "steam-tags.json", client=store.client, clock=lambda: now)


@pytest.fixture
def proc(tmp_path: Path) -> FakeProc:
    p = FakeProc(tmp_path / "proc")
    p.add(1, "systemd", {"PATH": "/bin"})
    p.add(100, "steam", {"SteamAppId": "588650", "HOME": "/home/x"})
    p.add(101, "steamwebhelper", {"SteamAppId": "588650"})
    p.add(102, "kwin_wayland", {"XSteamAppId": "5"})
    return p


def watcher(proc: FakeProc, tags: SteamTags | None = None, **kw) -> GameWatcher:
    cat = FakeCatalog(Game(appid=588650, name="Dead Cells", install_dir="Dead Cells"))
    return GameWatcher(cat, tags, proc_root=proc.root, clock=lambda: NOW, **kw)


async def test_no_game_ignores_steam_itself(proc: FakeProc) -> None:
    w = watcher(proc)
    assert await w.poll() is None
    assert w.current() is None and w.game_context() is None


async def test_detects_closes_and_emits_events(proc: FakeProc, tmp_path: Path) -> None:
    store = Store()
    w = watcher(proc, make_tags(tmp_path, store))
    events = []
    w.subscribe(events.append)

    async def async_listener(e) -> None:
        events.append(("async", e.kind))

    w.subscribe(async_listener)
    proc.add(200, "reaper", {"SteamAppId": "588650", "SteamGameId": "588650"}, start_s=600)
    proc.add(201, "deadcells", {"SteamAppId": "588650"}, start_s=605)
    game = await w.poll()
    assert game is not None and game.appid == 588650 and game.name == "Dead Cells"
    assert game.pid == 200 and game.since == BTIME + 600
    assert game.genres == ("Action", "Indie") and game.tags[0] == "Metroidvania"
    assert [e.kind for e in events if not isinstance(e, tuple)] == ["opened"]
    assert ("async", "opened") in events

    # segunda varredura: mesmo jogo, sem evento nem rede
    n_calls = len(store.calls)
    assert await w.poll() is game
    assert len(store.calls) == n_calls and len(events) == 2

    proc.kill(200)
    proc.kill(201)
    assert await w.poll() is None
    assert events[-2].kind == "closed" and events[-2].game.appid == 588650
    assert w.current() is None


async def test_adapters(proc: FakeProc, tmp_path: Path) -> None:
    w = watcher(proc, make_tags(tmp_path, Store()))
    proc.add(300, "deadcells", {"SteamAppId": "588650"}, start_s=NOW - BTIME - 25 * 60)
    await w.poll()
    info = w.current()
    assert isinstance(info, GameInfo) and info.name == "Dead Cells"
    assert "Action" in info.tags and "Metroidvania" in info.tags
    assert "combinando com Dead Cells" in wish_for("coloca uma boa", 15, info).why
    ctx = w.game_context()
    assert ctx is not None and ctx.name == "Dead Cells" and ctx.session_minutes == 25
    assert ctx.genre == "Action, Indie"


async def test_unknown_appid_named_by_store_and_offline(proc: FakeProc, tmp_path: Path) -> None:
    proc.add(400, "game.exe", {"SteamAppId": "999"})
    w = watcher(proc, make_tags(tmp_path, Store(fail=True)))
    game = await w.poll()
    assert game is not None and game.name == "App 999" and game.tags == ()  # sem rede: segue sem tags
    w2 = watcher(proc, make_tags(tmp_path / "b", Store()))
    assert (await w2.poll()).name == "Dead Cells"  # nome vindo da Store (payload fixo)


async def test_non_steam_known_process(proc: FakeProc) -> None:
    proc.add(500, "Minecraft", {"PATH": "/bin"})
    w = watcher(proc, known_processes={"minecraft": "Minecraft"})
    game = await w.poll()
    assert game is not None and game.appid is None and game.name == "Minecraft"
    assert scan(proc.root, {"minecraft": "Minecraft"}) == ["Minecraft"]


async def test_tags_cache_persists_and_expires(tmp_path: Path) -> None:
    store = Store()
    tags = make_tags(tmp_path, store)
    info = await tags.fetch(588650)
    assert info is not None and info.tags == ("Metroidvania", "Roguelite", "Pixel Graphics")
    assert info.categories == ("Single-player",)
    raw = json.loads((tmp_path / "cache" / "steam-tags.json").read_text())
    assert raw["588650"]["genres"] == ["Action", "Indie"]

    store2 = Store()
    again = make_tags(tmp_path, store2, now=NOW + 86400)
    assert (await again.fetch(588650)).tags == info.tags and store2.calls == []  # do disco
    stale = make_tags(tmp_path, store2, now=NOW + 40 * 86400)
    await stale.fetch(588650)
    assert store2.calls  # venceu: busca de novo


async def test_failure_not_cached_and_backoff(tmp_path: Path) -> None:
    store = Store(fail=True)
    tags = make_tags(tmp_path, store)
    assert await tags.fetch(10) is None
    n = len(store.calls)
    assert await tags.fetch(10) is None and len(store.calls) == n  # espera ``retry_s``
    assert not (tmp_path / "cache" / "steam-tags.json").exists()


class _Chat:
    def __init__(self) -> None:
        self.calls: list = []

    async def chat(self, messages, *, tools=(), json_mode=False, personal):
        self.calls.append(list(messages))
        return ChatReply(text="Beleza.")


class _Providers:
    def __init__(self) -> None:
        self.c = _Chat()

    def chat(self, task: ProviderTask = ProviderTask.AGENT) -> _Chat:
        return self.c


async def test_agent_receives_game_context(proc: FakeProc, tmp_path: Path) -> None:
    w = watcher(proc, make_tags(tmp_path, Store()))
    proc.add(600, "deadcells", {"SteamAppId": "588650"})
    await w.poll()
    providers = _Providers()
    agent = default_agent(providers, Registry([]), game=w.game_context)
    ctx = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC), mood=2)
    await agent.answer("que jogo é esse?", ctx)
    system = " ".join(m.content for m in providers.c.calls[-1] if m.role == "system")
    assert "Jogando: Dead Cells (Action, Indie)" in system
