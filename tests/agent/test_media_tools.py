"""Ferramentas de mídia (3.5) chamadas pelo modelo falso: ação do registro, confirmação, ficha."""

from __future__ import annotations

import signal
from pathlib import Path

import pytest

from magi.agent.graph import GraphAgent
from magi.agent.self_model import SelfModel
from magi.agent.tools.media import map_spotify_play, media_tools
from magi.agent.tools.system import system_tools
from magi.common.contracts import ChatReply, IntentId, SlotName
from magi.core.actions import Registry
from magi.core.actions.games import CloseGame, ProcInfo
from magi.core.actions.spotify_api import Match, SpotifyPlayer
from magi.core.actions.spotify_mpris import SpotifyHandler
from magi.core.catalog import MemoryAliasStore, SteamCatalog
from tests.agent.test_graph import CTX, FakeChat, FakeProviders, Recorder, call
from tests.core.test_games import FakeTable

MUSIC = [IntentId.MUSIC_OPEN, IntentId.MUSIC_PLAY, IntentId.MUSIC_PAUSE, IntentId.MUSIC_NEXT,
         IntentId.MUSIC_PREVIOUS, IntentId.MUSIC_VOLUME, IntentId.MUSIC_LIKE, IntentId.MUSIC_NEVER]


def agent_for(reg: Registry, script):
    chat = FakeChat(script)
    tools = [*system_tools(reg), *media_tools(reg)]
    return GraphAgent(FakeProviders(chat), tools, persona="Você é a Magi."), chat


async def run_tool(reg: Registry, name: str, **args):
    agent, chat = agent_for(reg, [ChatReply(text="", tool_calls=(call(name, **args),)), ChatReply(text="")])
    return await agent.answer("pedido", CTX), chat


# -- close_game --------------------------------------------------------------------------------


@pytest.fixture
def close_setup(tmp_path: Path):
    apps = tmp_path / "Steam" / "steamapps"
    apps.mkdir(parents=True)
    (apps / "appmanifest_1145360.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"1145360"\n\t"name"\t\t"Hades"\n'
        '\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"Hades"\n}\n'
    )
    catalog = SteamCatalog(tmp_path / "Steam", aliases=MemoryAliasStore())
    table = FakeTable([
        ProcInfo(1, 0, ("systemd",)),
        ProcInfo(200, 1, ("reaper", "SteamLaunch", "AppId=1145360", "--", "hades")),
        ProcInfo(201, 200, ("hades",)),
    ])

    async def sleep(_s: float) -> None:
        return None

    closer = CloseGame(catalog, table, table.kill, sleep, grace_s=0.1, poll_s=0.05)
    return Registry([closer]), table


async def test_close_game_pede_confirmacao_com_a_frase_do_handler(close_setup) -> None:
    reg, table = close_setup
    res, chat = await run_tool(reg, "close_game")
    assert res.needs_confirmation and res.dangerous
    assert res.speech == "Fechar Hades? Diz confirma."
    assert table.signals == [] and len(chat.calls) == 1  # nada executado, modelo não rodou de novo
    assert res.on_confirm is not None and res.on_confirm.confirmed
    assert res.on_confirm.intent.id == IntentId.GAME_CLOSE and res.on_confirm.intent.danger
    done = await reg.run(res.on_confirm)  # o núcleo roda on_confirm depois do "confirma"
    assert done.ok and done.speech == "Hades fechado."
    assert {sig for _, sig in table.signals} == {signal.SIGTERM}


async def test_close_game_force_e_jogo_fechado(close_setup) -> None:
    reg, table = close_setup
    res, _ = await run_tool(reg, "close_game", game="1145360", force=True)
    assert res.needs_confirmation and res.speech == "Forçar o fechamento de Hades? Diz confirma."
    assert res.on_confirm.args["force"] is True and table.signals == []
    table.procs.clear()
    res, chat = await run_tool(reg, "close_game")
    assert not res.needs_confirmation and len(chat.calls) == 2
    assert "Não tem jogo aberto." in chat.calls[1][0][-1].content


# -- rgb ---------------------------------------------------------------------------------------


async def test_rgb_cor_hex_e_brilho() -> None:
    rgb = Recorder([IntentId.RGB_COLOR, IntentId.RGB_BRIGHTNESS])
    reg = Registry([rgb])
    await run_tool(reg, "rgb", color="azul")
    await run_tool(reg, "rgb", color="FF8800", brightness=40)
    got = [(r.intent.id, r.intent.slots[0].name, r.intent.slots[0].value) for r in rgb.reqs]
    assert got == [
        (IntentId.RGB_COLOR, SlotName.COLOR, "azul"),
        (IntentId.RGB_COLOR, SlotName.COLOR, "#ff8800"),
        (IntentId.RGB_BRIGHTNESS, SlotName.BRIGHTNESS, "40"),
    ]
    res, chat = await run_tool(reg, "rgb", brightness=150)
    assert len(rgb.reqs) == 3 and "0 a 100" in chat.calls[1][0][-1].content


# -- spotify -----------------------------------------------------------------------------------


class FakeApi:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def find(self, query: str) -> Match:
        self.queries.append(query)
        return Match(kind="album", uri="spotify:album:meteora", name="Meteora", artist="Linkin Park")


class FakeMpris:
    def __init__(self) -> None:
        self.opened: list[str] = []

    async def open_uri(self, uri: str) -> None:
        self.opened.append(uri)


async def test_spotify_play_usa_play_query_e_marca_escolha() -> None:
    api, mpris, picked = FakeApi(), FakeMpris(), []
    player = SpotifyPlayer(mpris, api, on_play=lambda uri, req: picked.append((uri, req)))  # mark_picked
    reg = Registry([SpotifyHandler(mpris, player.play_query)])
    res, _ = await run_tool(reg, "spotify_play", query="Meteora", kind="album", artist="Linkin Park")
    assert api.queries == ["o album Meteora de Linkin Park"]
    assert mpris.opened == ["spotify:album:meteora"]
    assert picked == [("spotify:album:meteora", "o album Meteora de Linkin Park")]
    assert res.ok


def test_map_spotify_play_tipos() -> None:
    def q(**a):
        return map_spotify_play(a).slots[0].value

    assert q(query="Numb") == "Numb"
    assert q(query="Numb", kind="track", artist="Linkin Park") == "a musica Numb de Linkin Park"
    assert q(query="Linkin Park", kind="artist", artist="Linkin Park") == "o artista Linkin Park"
    assert q(query="Daily Mix 1", kind="playlist") == "a playlist Daily Mix 1"


@pytest.mark.parametrize(
    ("args", "intent", "volume"),
    [
        ({"action": "play"}, IntentId.MUSIC_PLAY, None),
        ({"action": "pause"}, IntentId.MUSIC_PAUSE, None),
        ({"action": "next"}, IntentId.MUSIC_NEXT, None),
        ({"action": "previous"}, IntentId.MUSIC_PREVIOUS, None),
        ({"action": "open"}, IntentId.MUSIC_OPEN, None),
        ({"action": "like"}, IntentId.MUSIC_LIKE, None),
        ({"action": "never"}, IntentId.MUSIC_NEVER, None),
        ({"action": "volume", "level": 30}, IntentId.MUSIC_VOLUME, "30"),
        ({"action": "volume", "delta": -10}, IntentId.MUSIC_VOLUME, "-10"),
    ],
)
async def test_spotify_control(args, intent, volume) -> None:
    music = Recorder(MUSIC)
    await run_tool(Registry([music]), "spotify_control", **args)
    (req,) = music.reqs
    assert req.intent.id == intent
    slot = req.intent.slot(SlotName.VOLUME)
    assert (slot.value if slot else None) == volume
    assert req.intent.slot(SlotName.QUERY) is None  # play sem query = retomar


async def test_spotify_pick_so_com_picker() -> None:
    assert "spotify_pick" not in [t.name for t in media_tools(Registry([Recorder(MUSIC)]))]
    pick = Recorder([IntentId.MUSIC_PICK], "Deixa comigo.")
    reg = Registry([pick])
    assert "spotify_pick" in [t.name for t in media_tools(reg)]
    res, _ = await run_tool(reg, "spotify_pick")
    assert [r.intent.id for r in pick.reqs] == [IntentId.MUSIC_PICK] and res.speech == "Deixa comigo."


# -- ficha (3.9) -------------------------------------------------------------------------------


def test_ficha_lista_ferramentas_de_midia() -> None:
    def ficha(reg: Registry) -> SelfModel:
        m = SelfModel(raw={}, spotify=lambda: True)
        m.registry = reg
        m.tools = tuple(t.spec for t in [*system_tools(reg), *media_tools(reg)])
        return m

    m = ficha(Registry([Recorder(MUSIC)]))
    names = m.tool_names()
    for n in ("close_game", "rgb", "spotify_play", "spotify_control"):
        assert n in names and n in m.about_section()
    assert "spotify_pick" not in names
    assert "escolher música pelo seu gosto" in m.gaps()
    m = ficha(Registry([Recorder([IntentId.MUSIC_PICK])]))
    assert "spotify_pick" in m.tool_names() and "escolher música pelo seu gosto" not in m.gaps()

