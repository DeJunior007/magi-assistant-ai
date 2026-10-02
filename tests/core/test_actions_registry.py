import pytest

from magi.common.contracts import ActionRegistry, ActionRequest, ActionResult, Intent
from magi.core.actions import SAY_FAILED, SAY_NO_HANDLER, DuplicateIntent, Registry


class _Handler:
    def __init__(self, intents, result=None, boom=False):
        self.intents = frozenset(intents)
        self.result = result or ActionResult(ok=True, speech="feito")
        self.boom = boom
        self.calls = []

    async def run(self, req):
        self.calls.append(req)
        if self.boom:
            raise RuntimeError("falhou")
        return self.result


def _req(intent_id):
    return ActionRequest(intent=Intent(id=intent_id), ctx=None)  # ctx não importa para o registro


def test_is_action_registry():
    assert isinstance(Registry(), ActionRegistry)


async def test_dispatch_by_intent():
    a, b = _Handler({"x.a"}), _Handler({"x.b", "x.c"})
    reg = Registry([a, b])
    assert reg.handles("x.c") and not reg.handles("x.z")
    res = await reg.run(_req("x.c"))
    assert res.ok and b.calls and not a.calls


async def test_unknown_intent():
    res = await Registry().run(_req("nada"))
    assert not res.ok and res.speech == SAY_NO_HANDLER


async def test_handler_exception_becomes_failure():
    res = await Registry([_Handler({"x.a"}, boom=True)]).run(_req("x.a"))
    assert not res.ok and res.speech == SAY_FAILED


def test_duplicate_intent_rejected():
    reg = Registry([_Handler({"x.a"})])
    with pytest.raises(DuplicateIntent):
        reg.register(_Handler({"x.b", "x.a"}))
    assert not reg.handles("x.b")
