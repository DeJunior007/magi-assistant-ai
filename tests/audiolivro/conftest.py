"""Isola os testes do audiolivro: ``HOME`` e ``XDG_*`` em ``tmp_path`` (nada em ``~/.local``,
``~/.config``, ``~/.cache`` nem ``~/Livros`` reais)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isola_casa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    casa = tmp_path / "casa"
    casa.mkdir()
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("XDG_STATE_HOME", str(casa / ".local/state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(casa / ".cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(casa / ".config"))
    monkeypatch.delenv("MAGI_CONFIG", raising=False)
    return casa
