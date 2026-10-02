"""Testes de 1.9 (R5.1–R5.5). Regra 8: launcher, kill e árvore de processos são falsos."""

from __future__ import annotations

import signal
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import pytest

from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    Intent,
    IntentId,
    Slot,
    SlotName,
    TurnContext,
    WakeSource,
)
from magi.core.actions import Registry
from magi.core.actions.games import ProcFs, ProcInfo, game_tree, handlers, running_appids
from magi.core.catalog import MemoryAliasStore, SteamCatalog

GAMES = {588650: "Dead Cells", 1145360: "Hades", 1145350: "Hades II", 367520: "Hollow Knight"}


@pytest.fixture
def catalog(tmp_path: Path) -> SteamCatalog:
    apps = tmp_path / "Steam" / "steamapps"
    apps.mkdir(parents=True)
    for appid, name in GAMES.items():
        (apps / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n'
            f'\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"{name}"\n}}\n'
        )
    return SteamCatalog(tmp_path / "Steam", aliases=MemoryAliasStore())


class FakeTable:
    """Árvore de processos falsa. ``kill`` só marca; ``stubborn`` ignora SIGTERM."""

    def __init__(self, procs: list[ProcInfo], env: Mapping[int, Mapping[str, str]] | None = None):
        self.procs = {p.pid: p for p in procs}
        self.env = dict(env or {})
        self.stubborn: set[int] = set()
        self.signals: list[tuple[int, int]] = []

    def list(self) -> list[ProcInfo]:
        return list(self.procs.values())

    def environ(self, pid: int) -> Mapping[str, str]:
        return self.env.get(pid, {})

    def alive(self, pid: int) -> bool:
        return pid in self.procs

    def kill(self, pid: int, sig: int) -> None:
        self.signals.append((pid, sig))
        if pid not in self.procs:
            raise ProcessLookupError(pid)
        if sig == signal.SIGKILL or pid not in self.stubborn:
            del self.procs[pid]


def _native_game() -> FakeTable:
    return FakeTable(
        [
            ProcInfo(1, 0, ("/usr/lib/systemd/systemd",)),
            ProcInfo(100, 1, ("steam",)),
            ProcInfo(200, 100, ("reaper", "SteamLaunch", "AppId=588650", "--", "deadcells")),
            ProcInfo(201, 200, ("deadcells",)),
            ProcInfo(202, 201, ("deadcells-helper",)),
            ProcInfo(300, 1, ("bash", "-c", "grep SteamLaunch AppId=1145360")),
            ProcInfo(400, 100, ("reaper", "SteamLaunch", "AppId=228980", "--", "redist")),
        ]
    )


def _proton_game() -> FakeTable:
    return FakeTable(
        [
            ProcInfo(100, 1, ("steam",)),
            ProcInfo(200, 100, ("reaper", "SteamLaunch", "AppId=1145360", "--", "proton")),
            ProcInfo(210, 200, ("python3", "proton", "waitforexitandrun")),
            ProcInfo(500, 1, ("/x/files/bin/wine64-preloader", "Hades.exe")),  # reparentado
            ProcInfo(501, 500, ("Z:\\Hades\\Hades.exe",), exe="/x/files/bin/wine64-preloader"),
            ProcInfo(600, 1, ("/x/files/bin/wine64-preloader", "outro.exe")),
        ],
        env={500: {"SteamAppId": "1145360"}, 501: {"SteamAppId": "1145360"}, 600: {"SteamAppId": "999"}},
    )


class Recorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: Sequence[str]) -> None:
        self.calls.append(list(argv))


async def _no_sleep(_s: float) -> None:
    return None


def _ctx() -> TurnContext:
    return TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime(2026, 1, 1))


def _req(intent_id: IntentId, *slots: Slot, text: str = "") -> ActionRequest:
    return ActionRequest(intent=Intent(intent_id.value, slots=tuple(slots)), ctx=_ctx(), text=text)


def _registry(catalog: SteamCatalog, table: FakeTable, tmp_path: Path, launcher: Recorder) -> Registry:
    wrapper = tmp_path / "steam-mangohud.sh"
    wrapper.write_text("#!/bin/sh\n")
    hs: list[ActionHandler] = handlers(
        catalog, launcher=launcher, wrapper=wrapper, table=table, killer=table.kill, sleep=_no_sleep
    )
    assert all(isinstance(h, ActionHandler) for h in hs)
    return Registry(hs)


# -- detecção -----------------------------------------------------------------------------------


def test_running_appids_ignores_text_and_redist() -> None:
    assert running_appids(_native_game().list()) == {588650: 200}


def test_game_tree_native_and_proton() -> None:
    assert sorted(game_tree(588650, _native_game())) == [200, 201, 202]
    assert sorted(game_tree(1145360, _proton_game())) == [200, 210, 500, 501]


def test_procfs_reads_real_proc_read_only() -> None:
    import os

    fs = ProcFs()
    me = next(p for p in fs.list() if p.pid == os.getpid())
    assert me.args and fs.alive(me.pid)
    assert "PATH" in fs.environ(me.pid)


# -- abrir --------------------------------------------------------------------------------------


async def test_open_by_appid_slot(catalog: SteamCatalog, tmp_path: Path) -> None:
    launcher = Recorder()
    reg = _registry(catalog, FakeTable([]), tmp_path, launcher)
    res = await reg.run(_req(IntentId.GAME_OPEN, Slot(SlotName.GAME, "588650", raw="dedi cels")))
    assert res.ok and res.speech == "Abrindo Dead Cells"
    assert launcher.calls == [[str(tmp_path / "steam-mangohud.sh"), "steam://rungameid/588650"]]


async def test_open_dedi_cels_by_fuzzy_raw(catalog: SteamCatalog, tmp_path: Path) -> None:
    launcher = Recorder()
    reg = _registry(catalog, FakeTable([]), tmp_path, launcher)
    res = await reg.run(_req(IntentId.GAME_OPEN, Slot(SlotName.GAME, "", raw="dedi cels")))
    assert res.ok and res.speech == "Abrindo Dead Cells"
    assert launcher.calls[0][-1] == "steam://rungameid/588650"


async def test_open_uses_intent_reply(catalog: SteamCatalog, tmp_path: Path) -> None:
    launcher = Recorder()
    reg = _registry(catalog, FakeTable([]), tmp_path, launcher)
    req = ActionRequest(
        intent=Intent("game.open", (Slot("game", "1145360"),), reply="Bora de {game}!"), ctx=_ctx()
    )
    assert (await reg.run(req)).speech == "Bora de Hades!"


async def test_open_not_found_suggests_up_to_three(catalog: SteamCatalog, tmp_path: Path) -> None:
    launcher = Recorder()
    reg = _registry(catalog, FakeTable([]), tmp_path, launcher)
    res = await reg.run(_req(IntentId.GAME_OPEN, Slot(SlotName.GAME, "", raw="hadis tres")))
    assert not res.ok and launcher.calls == []
    assert res.speech.startswith("Não achei hadis tres.")
    assert "Hades" in res.speech and res.speech.count(",") <= 2


async def test_open_launch_failure(catalog: SteamCatalog, tmp_path: Path) -> None:
    def boom(_argv: Sequence[str]) -> None:
        raise FileNotFoundError("steam")

    hs = handlers(catalog, launcher=boom, wrapper=tmp_path / "nao-existe.sh", table=FakeTable([]))
    res = await Registry(hs).run(_req(IntentId.GAME_OPEN, Slot(SlotName.GAME, "588650")))
    assert not res.ok and "Dead Cells" in res.speech


# -- fechar -------------------------------------------------------------------------------------


async def test_close_requires_confirmation(catalog: SteamCatalog, tmp_path: Path) -> None:
    table = _native_game()
    reg = _registry(catalog, table, tmp_path, Recorder())
    res = await reg.run(_req(IntentId.GAME_CLOSE, text="fecha o jogo"))
    assert res.needs_confirmation and res.dangerous and "confirma" in res.speech
    assert table.signals == []
    assert res.on_confirm is not None and res.on_confirm.confirmed
    assert res.on_confirm.intent.slot("game").value == "588650"
    assert not res.on_confirm.args.get("force")

    done = await reg.run(res.on_confirm)
    assert done.ok and not done.needs_confirmation
    assert sorted(table.signals) == [(200, signal.SIGTERM), (201, signal.SIGTERM), (202, signal.SIGTERM)]
    assert 100 in table.procs and 300 in table.procs  # Steam e o terminal intactos


async def test_close_stubborn_asks_again_for_sigkill(catalog: SteamCatalog, tmp_path: Path) -> None:
    table = _proton_game()
    table.stubborn = {501}
    reg = _registry(catalog, table, tmp_path, Recorder())
    first = await reg.run(_req(IntentId.GAME_CLOSE))
    assert first.on_confirm is not None
    second = await reg.run(first.on_confirm)
    assert second.needs_confirmation and second.dangerous
    assert all(sig == signal.SIGTERM for _, sig in table.signals)
    assert 501 in table.procs and 600 in table.procs
    assert second.on_confirm is not None and second.on_confirm.args["force"] is True

    table.signals.clear()
    third = await reg.run(second.on_confirm)
    assert third.ok and table.signals == [(501, signal.SIGKILL)]
    assert 501 not in table.procs and 600 in table.procs


async def test_close_nothing_running(catalog: SteamCatalog, tmp_path: Path) -> None:
    reg = _registry(catalog, FakeTable([ProcInfo(100, 1, ("steam",))]), tmp_path, Recorder())
    res = await reg.run(_req(IntentId.GAME_CLOSE))
    assert not res.ok and not res.needs_confirmation


async def test_close_named_game_not_running(catalog: SteamCatalog, tmp_path: Path) -> None:
    table = _native_game()
    reg = _registry(catalog, table, tmp_path, Recorder())
    res = await reg.run(_req(IntentId.GAME_CLOSE, Slot(SlotName.GAME, "367520")))
    assert not res.ok and res.speech == "Hollow Knight não está aberto."
    assert table.signals == []
