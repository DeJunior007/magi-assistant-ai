"""Units ``magi-backup.{service,timer}`` (Y4.1, spec §7.1). Nada aqui toca o systemd real."""

from __future__ import annotations

import configparser
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UNITS = REPO / "deploy" / "systemd"


def _unit(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str  # mantém a caixa das chaves
    cp.read(path, encoding="utf-8")
    return cp


def test_timer_0330_persistente_e_10min_apos_subir() -> None:
    t = _unit(UNITS / "magi-backup.timer")["Timer"]
    assert t["OnCalendar"] == "*-*-* 03:30:00"
    assert t["Persistent"] == "true"
    assert t["OnStartupSec"] == "10min"
    assert t["Unit"] == "magi-backup.service"
    assert _unit(UNITS / "magi-backup.timer")["Install"]["WantedBy"] == "timers.target"


def test_servico_oneshot_chama_magi_backup() -> None:
    s = _unit(UNITS / "magi-backup.service")["Service"]
    assert s["Type"] == "oneshot"
    assert s["ExecStart"] == '"@REPO@/.venv/bin/magi-backup"'
    assert s["WorkingDirectory"] == "@REPO@"
    assert "Restart" not in s


def test_entrada_magi_backup_no_pyproject() -> None:
    assert 'magi-backup = "magi.elo.backup:main"' in (REPO / "pyproject.toml").read_text()


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="sem systemd-analyze")
def test_systemd_analyze_verify(tmp_path: Path) -> None:
    if not (REPO / ".venv" / "bin" / "magi-backup").exists():
        pytest.skip("sem .venv com o executável (rode uv sync)")
    for nome in ("magi-backup.service", "magi-backup.timer"):
        (tmp_path / nome).write_text((UNITS / nome).read_text().replace("@REPO@", str(REPO)))
    r = subprocess.run(
        ["systemd-analyze", "--user", "verify", *sorted(map(str, tmp_path.iterdir()))],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
