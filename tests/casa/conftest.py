"""Isola os caminhos da casa em ``tmp_path`` (nada em ~/.config ou ~/.local reais) e dá um relógio
falso. Sem TV real, sem multicast, sem rede."""

from __future__ import annotations

import io
import json
import logging

import pytest

from magi.casa import log
from magi.casa.falso import RelogioFalso


@pytest.fixture(autouse=True)
def casa_isolada(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    return home


@pytest.fixture
def relogio() -> RelogioFalso:
    return RelogioFalso(1000.0)


class LogCapturado:
    def __init__(self) -> None:
        self.buf = io.StringIO()

    @property
    def texto(self) -> str:
        return self.buf.getvalue()

    def linhas(self) -> list[dict]:
        return [json.loads(x) for x in self.texto.splitlines() if x.strip()]


@pytest.fixture
def log_casa():
    cap = LogCapturado()
    h = log.configurar("DEBUG", stream=cap.buf)
    yield cap
    log.logger().removeHandler(h)
    log.logger().setLevel(logging.NOTSET)
