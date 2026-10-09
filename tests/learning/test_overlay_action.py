"""LM3.4: balão com resultados reais — lm_action pelo bridge, correlação por id, retry e timeout
de UI de 12 s (lógica pura, sem PySide6)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from wired.learning_overlay import (  # noqa: E402
    ERROR,
    LOADING,
    MOCK_IMPROVE,
    OK,
    UI_TIMEOUT_S,
    BridgeProvider,
    Overlay,
    error_text,
)
from wired.learning_text import ActionKind, Selection  # noqa: E402


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class Bridge:
    def __init__(self, up: bool = True) -> None:
        self.up = up
        self.sent: list[tuple[str, dict]] = []

    def send_lm(self, t: str, fields: dict) -> bool:
        if not self.up:
            return False
        self.sent.append((t, dict(fields)))
        return True


TEXT = "I make an authentication system"


def _overlay(up: bool = True) -> tuple[Overlay, Bridge, Clock]:
    br, clk = Bridge(up), Clock()
    o = Overlay(provider=BridgeProvider(br.send_lm), clock=clk)
    o.open(Selection(message_id=7, start=0, end=6, text="I make"), "you", TEXT)
    return o, br, clk


def _ok(aid: str) -> dict:
    return {"id": aid, "kind": "improve", "ok": True, "data": dict(MOCK_IMPROVE), "error": None,
            "cached": False, "ms": 900, "cost_usd": 0.0002}


def test_envia_lm_action_e_espera():
    o, br, _ = _overlay()
    act = o.choose(ActionKind.IMPROVE)
    assert o.phase == LOADING
    assert br.sent == [("lm_action", {"id": act["id"], "kind": "improve", "message_id": 7,
                                      "start": 0, "end": 6})]
    assert o.deadline() == 100.0 + UI_TIMEOUT_S


def test_correlacao_por_id():
    o, br, _ = _overlay()
    first = o.choose(ActionKind.IMPROVE)["id"]
    o.choose(ActionKind.EXPLAIN)                 # nova ação: a anterior não vale mais
    assert not o.on_result(_ok(first))
    assert o.phase == LOADING
    assert o.poll({first: _ok(first)}) is False  # resultado de outra ação no dicionário
    assert o.on_result({**_ok(o.action_id), "kind": "explain",
                        "data": {"explanation": "x", "examples": [], "pt": "y"}})
    assert o.phase == OK


def test_poll_pega_resultado_do_modelo():
    o, _, _ = _overlay()
    aid = o.choose(ActionKind.IMPROVE)["id"]
    assert not o.poll({})
    v = o.version
    assert o.poll({aid: _ok(aid)})
    assert o.phase == OK and o.result["data"] == MOCK_IMPROVE and o.version > v
    assert o.deadline() is None


def test_poll_usa_results_do_provedor():
    o, _, _ = _overlay()
    aid = o.choose(ActionKind.IMPROVE)["id"]
    o.provider.results = {aid: _ok(aid)}  # o ModelProvider da tela expõe info.results
    assert o.poll()
    assert o.phase == OK


def test_timeout_de_12s_e_retry():
    o, br, clk = _overlay()
    first = o.choose(ActionKind.IMPROVE)["id"]
    clk.t += UI_TIMEOUT_S - 0.1
    assert not o.poll({})
    clk.t += 0.1
    assert o.poll({})
    assert o.phase == ERROR and o.result["error"] == "timeout"
    assert error_text(o.result["error"]).endswith("took too long")
    assert not o.on_result(_ok(first))           # resposta atrasada é ignorada
    assert o.phase == ERROR
    assert o.target("retry")                     # retry manda nova ação com outro id
    assert o.phase == LOADING and o.action_id != first
    assert len(br.sent) == 2 and br.sent[1][1]["id"] == o.action_id
    assert o.deadline() == clk.t + UI_TIMEOUT_S
    assert o.on_result(_ok(o.action_id))
    assert o.phase == OK


def test_erro_do_nucleo_tem_retry():
    o, br, _ = _overlay()
    aid = o.choose(ActionKind.IMPROVE)["id"]
    assert o.on_result({"id": aid, "kind": "improve", "ok": False, "data": None, "error": "model"})
    assert o.phase == ERROR
    assert o.key("enter") and o.phase == LOADING and len(br.sent) == 2


def test_desconectado_vira_erro_offline():
    o, br, _ = _overlay(up=False)
    o.choose(ActionKind.IMPROVE)
    assert o.phase == ERROR and o.result["error"] == "offline"
    assert br.sent == []
    br.up = True
    assert o.retry() is not None and o.phase == LOADING and len(br.sent) == 1


def test_fechar_descarta_resultado():
    o, _, _ = _overlay()
    aid = o.choose(ActionKind.IMPROVE)["id"]
    o.close()
    assert not o.on_result(_ok(aid)) and not o.poll({aid: _ok(aid)})
    assert o.deadline() is None
