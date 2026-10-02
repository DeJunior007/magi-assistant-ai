"""Ações do HUD (1.10). Nada de HUD real: runner falso e settings em diretório temporário."""

import json

import pytest

from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    DetailMsg,
    DetailTarget,
    HudSink,
    Intent,
    IntentId,
    Slot,
    SlotName,
)
from magi.core.actions import Registry
from magi.core.actions import hud as hud_actions


class FakeRunner:
    def __init__(self, running=False, cmd_code=0):
        self.running = running
        self.cmd_code = cmd_code
        self.calls = []

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if argv[0] == "pgrep":
            assert argv[-1] == hud_actions.HUD_PROCESS_PATTERN
            return 0 if self.running else 1
        if self.cmd_code == 0:
            self.running = not self.running
        return self.cmd_code

    @property
    def toggles(self):
        return [c for c in self.calls if c[0] != "pgrep"]


class FakeSink:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


@pytest.fixture
def env(tmp_path):
    runner, sink = FakeRunner(), FakeSink()
    settings = tmp_path / "gamerhud" / "settings.json"
    (handler,) = hud_actions.handlers(
        sink, settings_path=settings, gamerhud_cmd=tmp_path / "gamerhud-bin", runner=runner
    )
    return handler, runner, sink, settings


def _req(intent_id, *slots, **args):
    return ActionRequest(intent=Intent(id=intent_id, slots=tuple(slots)), ctx=None, args=args)


def test_contract_and_registry(env):
    handler, *_ = env
    assert isinstance(handler, ActionHandler)
    assert isinstance(FakeSink(), HudSink)
    reg = Registry([handler])
    for iid in ("hud.open", "hud.close", "hud.idle_toggle", "hud.detail", "hud.rgb_sync"):
        assert reg.handles(iid)


async def test_open_when_closed_runs_toggle(env, tmp_path):
    handler, runner, *_ = env
    res = await handler.run(_req(IntentId.HUD_OPEN))
    assert res.ok and res.speech == hud_actions.SAY_OPENED
    assert runner.toggles == [[str(tmp_path / "gamerhud-bin")]]


async def test_open_when_open_does_nothing(env):
    handler, runner, *_ = env
    runner.running = True
    res = await handler.run(_req(IntentId.HUD_OPEN))
    assert res.ok and res.speech == hud_actions.SAY_ALREADY_OPEN
    assert runner.toggles == []


async def test_close_only_when_open(env):
    handler, runner, *_ = env
    res = await handler.run(_req(IntentId.HUD_CLOSE))
    assert res.speech == hud_actions.SAY_ALREADY_CLOSED and runner.toggles == []
    runner.running = True
    res = await handler.run(_req(IntentId.HUD_CLOSE))
    assert res.ok and res.speech == hud_actions.SAY_CLOSED
    assert len(runner.toggles) == 1 and not runner.running


async def test_toggle_failure(env):
    handler, runner, *_ = env
    runner.cmd_code = 2
    res = await handler.run(_req(IntentId.HUD_OPEN))
    assert not res.ok and res.speech == hud_actions.SAY_HUD_FAILED


async def test_idle_toggle_preserves_other_keys(env):
    handler, _, _, settings = env
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"rgb_sync": False, "transition": True}))
    res = await handler.run(_req(IntentId.HUD_IDLE_TOGGLE))
    assert res.speech == hud_actions.SAY_IDLE
    assert json.loads(settings.read_text()) == {
        "rgb_sync": False,
        "transition": True,
        "view": "idle",
    }
    res = await handler.run(_req(IntentId.HUD_IDLE_TOGGLE))
    assert res.speech == hud_actions.SAY_FULL
    assert json.loads(settings.read_text())["view"] == "full"
    assert [p.name for p in settings.parent.iterdir()] == ["settings.json"]  # sem temporários


async def test_idle_set_explicit(env):
    handler, _, _, settings = env
    on = Slot(name=SlotName.ON_OFF, value="on")
    await handler.run(_req(IntentId.HUD_IDLE_TOGGLE, on))
    await handler.run(_req(IntentId.HUD_IDLE_TOGGLE, on))
    assert json.loads(settings.read_text())["view"] == "idle"
    res = await handler.run(_req(IntentId.HUD_IDLE_TOGGLE, view="full"))
    assert res.speech == hud_actions.SAY_FULL
    assert json.loads(settings.read_text())["view"] == "full"


async def test_corrupt_settings_treated_as_empty(env):
    handler, _, _, settings = env
    settings.parent.mkdir(parents=True)
    settings.write_text("{nope")
    res = await handler.run(_req(IntentId.HUD_RGB_SYNC))
    assert res.speech == hud_actions.SAY_RGB_OFF  # padrão do HUD é ligado
    assert json.loads(settings.read_text()) == {"rgb_sync": False}


async def test_rgb_sync_on_off_and_toggle(env):
    handler, _, _, settings = env
    off = Slot(name=SlotName.ON_OFF, value="off")
    res = await handler.run(_req(IntentId.HUD_RGB_SYNC, off))
    assert res.speech == hud_actions.SAY_RGB_OFF
    res = await handler.run(_req(IntentId.HUD_RGB_SYNC, off))
    assert res.speech == hud_actions.SAY_RGB_OFF
    res = await handler.run(_req(IntentId.HUD_RGB_SYNC))
    assert res.speech == hud_actions.SAY_RGB_ON
    assert json.loads(settings.read_text()) == {"rgb_sync": True}
    res = await handler.run(_req(IntentId.HUD_RGB_SYNC, Slot(name=SlotName.ON_OFF, value="on")))
    assert res.speech == hud_actions.SAY_RGB_ON


async def test_settings_write_failure(env, tmp_path):
    handler, runner, sink, _ = env
    blocker = tmp_path / "arquivo"
    blocker.write_text("x")
    (bad,) = hud_actions.handlers(sink, settings_path=blocker / "s.json", runner=runner)
    res = await bad.run(_req(IntentId.HUD_RGB_SYNC))
    assert not res.ok and res.speech == hud_actions.SAY_SETTINGS_FAILED


@pytest.mark.parametrize("target", list(DetailTarget))
async def test_detail_sends_msg(env, target):
    handler, runner, sink, _ = env
    runner.running = True
    res = await handler.run(_req(IntentId.HUD_DETAIL, Slot(name=SlotName.DETAIL, value=target)))
    assert res.ok and res.speech == hud_actions.SAY_DETAIL[target]
    assert sink.sent == [DetailMsg(v=target)]


async def test_detail_invalid_or_hud_closed(env):
    handler, runner, sink, _ = env
    res = await handler.run(_req(IntentId.HUD_DETAIL))
    assert not res.ok and res.speech == hud_actions.SAY_DETAIL_WHICH
    res = await handler.run(_req(IntentId.HUD_DETAIL, Slot(name=SlotName.DETAIL, value="disco")))
    assert not res.ok
    res = await handler.run(_req(IntentId.HUD_DETAIL, Slot(name=SlotName.DETAIL, value="cpu")))
    assert not res.ok and res.speech == hud_actions.SAY_HUD_NOT_OPEN
    assert sink.sent == [] and runner.toggles == []
