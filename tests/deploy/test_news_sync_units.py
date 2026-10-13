"""Units do ``magi-news-sync`` e o ``ExecCondition`` da recaída no ``magi-ayanami.service`` (Y3.3)."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UNITS = REPO / "deploy" / "systemd"
COND = '"@REPO@/.venv/bin/python" -m magi.elo.news_sync --precisa-local'


def _unit(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str  # type: ignore[assignment,method-assign]
    cp.read(path, encoding="utf-8")
    return cp


def test_timer_15_min_persistente() -> None:
    t = _unit(UNITS / "magi-news-sync.timer")["Timer"]
    assert t["OnBootSec"] == "2min"
    assert t["OnUnitActiveSec"] == "15min"
    assert t["Persistent"] == "true"
    assert _unit(UNITS / "magi-news-sync.timer")["Install"]["WantedBy"] == "timers.target"


def test_servico_oneshot_chama_o_modulo() -> None:
    s = _unit(UNITS / "magi-news-sync.service")["Service"]
    assert s["Type"] == "oneshot"
    assert s["WorkingDirectory"] == "@REPO@"
    assert s["ExecStart"] == '"@REPO@/.venv/bin/python" -m magi.elo.news_sync'


def test_ayanami_ganha_exec_condition_antes_da_coleta() -> None:
    s = _unit(UNITS / "magi-ayanami.service")["Service"]
    assert s["ExecCondition"] == COND
    assert s["ExecStart"] == '"@REPO@/.venv/bin/magi-ayanami"'


def _env_isolado(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.pop("MAGI_CONFIG", None)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["HOME"] = str(tmp_path)
    return env


def test_exec_condition_sem_ayanami_deixa_a_coleta_rodar(tmp_path: Path) -> None:
    """Sem ``[ayanami]`` (aqui: sem config nenhum) o comando real do ExecCondition sai 0."""
    cfg = tmp_path / "config" / "magi"
    cfg.mkdir(parents=True)
    (cfg / "config.toml").write_text("[user]\nname = 'x'\n")
    r = subprocess.run(
        [sys.executable, "-m", "magi.elo.news_sync", "--precisa-local"],
        cwd=REPO,
        env=_env_isolado(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="sem systemd-analyze")
def test_systemd_analyze_verify(tmp_path: Path) -> None:
    venv = REPO / ".venv" / "bin"
    if not (venv / "python").exists() or not (venv / "magi-ayanami").exists():
        pytest.skip("sem .venv")
    nomes = ("magi-news-sync.service", "magi-news-sync.timer", "magi-ayanami.service", "magi-ayanami.timer")
    for n in nomes:
        (tmp_path / n).write_text((UNITS / n).read_text().replace("@REPO@", str(REPO)))
    r = subprocess.run(
        ["systemd-analyze", "--user", "verify", *(str(tmp_path / n) for n in nomes)],
        capture_output=True,
        text=True,
        env=_env_isolado(tmp_path) | {"XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", "")},
    )
    assert r.returncode == 0, r.stderr
