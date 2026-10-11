"""Mensagem ``think`` da espera viva (spec §1, CA-01)."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from magi.common.contracts import THINK_KINDS, THINK_TOOLS, ThinkMsg
from magi.common.events import HudDecodeError, decode_hud


def _bridge():
    pytest.importorskip("PySide6")
    hud = str(Path(__file__).resolve().parents[2] / "hud")
    if hud not in sys.path:
        sys.path.insert(0, hud)
    return importlib.import_module("hud_bridge")


CASES = [
    (ThinkMsg("wait"), {"t": "think", "v": "wait"}),
    (ThinkMsg("tool", tool="news_query"), {"t": "think", "v": "tool", "tool": "news_query"}),
    (ThinkMsg("lote", n=1), {"t": "think", "v": "lote", "n": 1}),
]


@pytest.mark.parametrize(("msg", "d"), CASES)
def test_ida_e_volta(msg: ThinkMsg, d: dict) -> None:
    assert msg.to_dict() == d
    line = msg.to_json()
    assert decode_hud(line) == msg
    assert _bridge()._decode_min(line) == d


def test_normaliza_campos() -> None:
    assert ThinkMsg("tool", tool="falar_com_gato").tool == "other"
    assert ThinkMsg("tool").tool == "other"
    assert ThinkMsg("wait", tool="search", n=3).to_dict() == {"t": "think", "v": "wait"}
    assert ThinkMsg("tool", tool="search", n=2).to_dict() == {"t": "think", "v": "tool", "tool": "search"}
    assert "other" in THINK_TOOLS and THINK_KINDS == {"wait", "tool", "lote"}


def test_ferramenta_desconhecida_na_ponte_vira_other() -> None:
    line = json.dumps({"t": "think", "v": "tool", "tool": "xyz"})
    assert decode_hud(line) == ThinkMsg("tool", tool="other")
    assert _bridge()._decode_min(line)["tool"] == "other"


@pytest.mark.parametrize(
    "d",
    [
        {"t": "think", "v": "pensando"},
        {"t": "think"},
        {"t": "think", "v": "lote", "n": -1},
        {"t": "think", "v": "lote", "n": "1"},
    ],
)
def test_invalido_recusado(d: dict) -> None:
    line = json.dumps(d)
    with pytest.raises(HudDecodeError):
        decode_hud(line)
    bridge = _bridge()
    with pytest.raises(bridge.DecodeError):
        bridge._decode_min(line)


def test_construtor_recusa() -> None:
    with pytest.raises(ValueError):
        ThinkMsg("x")
    with pytest.raises(ValueError):
        ThinkMsg("lote", n=-2)
