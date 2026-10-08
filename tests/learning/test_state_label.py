"""CA-17 (UI-001): tabela de spec §7 — estado do núcleo → rótulo e cor da Condessa."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

from wired.learning_layout import state_label  # noqa: E402

GPU, FOCUS, CPU, DIM, HOT = "#5fd38d", "#5fd0e0", "#b392f0", "#8f89a6", "#e5695b"


@pytest.mark.parametrize("core,session,action,connected,expected", [
    ("sleeping", True, False, True, ("TEACHING 教育中", GPU)),
    ("followup", True, False, True, ("TEACHING 教育中", GPU)),
    ("listening", True, False, True, ("LISTENING 聴取中", FOCUS)),
    ("listening", True, True, True, ("LISTENING 聴取中", FOCUS)),
    ("thinking", True, False, True, ("THINKING 思考中", FOCUS)),
    ("thinking", True, True, True, ("THINKING 思考中", FOCUS)),
    ("speaking", True, False, True, ("SPEAKING 発話中", CPU)),
    ("speaking", True, True, True, ("SPEAKING 発話中", CPU)),
    ("sleeping", True, True, True, ("ANALYZING 分析中", DIM)),
    ("followup", True, True, True, ("ANALYZING 分析中", DIM)),
    ("happy", True, True, True, ("ANALYZING 分析中", DIM)),
    ("happy", True, False, True, ("TEACHING 教育中", GPU)),
    ("sleeping", False, False, True, ("STANDBY", DIM)),
    ("speaking", False, True, True, ("STANDBY", DIM)),
    ("listening", True, False, False, ("OFFLINE", HOT)),
    ("sleeping", False, False, False, ("OFFLINE", HOT)),
    (None, True, False, True, ("TEACHING 教育中", GPU)),
])
def test_tabela_spec_7(core, session, action, connected, expected):
    assert state_label(core, session, action, connected) == expected


def test_cores_iguais_ao_tema():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from wired import theme

    assert (GPU, FOCUS, CPU, DIM, HOT) == (theme.GPU, theme.FOCUS, theme.CPU, theme.TEXT_DIM, theme.HOT)
