"""Espera viva no HUD (E1.2): ``ThinkMsg`` da ponte muda o chip e o retrato."""

from __future__ import annotations

from turn_phase import MIN_DWELL_S
from wired.main_screen import chip_label

from .test_wired_integration import make_hud  # noqa: F401 - fixture do HUD real


def test_think_da_ponte_muda_chip_e_retrato(make_hud, monkeypatch):  # noqa: F811 - fixture
    import gamerhud

    clock = [100.0]
    monkeypatch.setattr(gamerhud.time, "monotonic", lambda: clock[0])
    w = make_hud()
    pedidos = []
    w.wired.mascot.set_think = lambda kind, tool, now, n=0: pedidos.append((kind, tool, now, n))
    w.on_face_state("thinking")
    clock[0] += MIN_DWELL_S + 0.1
    w.bridge.think.emit("tool", "news_query", 0)
    assert pedidos == [("tool", "news_query", clock[0], 0)]
    clock[0] += MIN_DWELL_S + 0.1
    w.caption_tick()
    snap = w.wired.snap
    assert snap.chip == "thinking" and snap.chip_tool == "news_query"
    assert chip_label(snap)[0].startswith("Searching")
    w.bridge.think.emit("lote", "", 1)
    assert pedidos[-1] == ("lote", None, clock[0], 1)
    antes = (w.wired.snap.chip, w.wired.snap.chip_tool)
    w.bridge.think.emit("wait", "", 0)  # só a pose: o chip não muda
    assert pedidos[-1][0] == "wait" and (w.wired.snap.chip, w.wired.snap.chip_tool) == antes
    w.on_bridge_connected(False)
    assert w.wired.snap.chip_tool is None  # núcleo caiu: rótulo da ferramenta some


def test_wired_set_think_sem_pose_ignora():
    from wired.integration import WiredUI

    ui = WiredUI()
    assert not hasattr(ui.mascot, "set_think")  # mascote vetorial (sem a arte)
    ui.set_think("tool", "rgb", 1.0)  # não quebra
