"""Faxina do Docker (magi-clean) sem Docker de verdade: comandos e saídas falsos."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

from magi.maintenance.cleanup import CleanupConfig, clean, load, parse_reclaimed, plan, save

GB = 10**9


def test_parse_reclaimed():
    assert parse_reclaimed("Deleted build cache objects:\nabc\nTotal:  12.5GB\n") == 12_500_000_000
    assert parse_reclaimed("Deleted Images:\n...\nTotal reclaimed space: 512MB") == 512_000_000
    assert parse_reclaimed("Total reclaimed space: 0B") == 0
    assert parse_reclaimed("nada") == 0


def test_plano_nunca_mexe_em_volumes():
    cfg = CleanupConfig()
    mode, cmds = plan(70.0, cfg)
    assert mode == "routine" and cmds[0] == ["docker", "builder", "prune", "-f", "--filter", "until=168h"]
    mode, cmds = plan(93.0, cfg)
    assert mode == "aggressive" and cmds[0] == ["docker", "builder", "prune", "-f"]
    for cmd in (*plan(70.0, cfg)[1], *cmds):
        assert "volume" not in cmd and "-a" not in cmd and "--all" not in cmd and "system" not in cmd


def test_faxina_soma_e_grava(tmp_path):
    calls = []

    def runner(cmd):
        calls.append(list(cmd))
        out = "Total:  10GB" if cmd[1] == "builder" else "Total reclaimed space: 1.5GB"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    disks = iter([(92.0, 50 * GB), (90.5, 61 * GB)])
    res = clean(CleanupConfig(), runner=runner, usage=lambda p: next(disks),
                now=lambda: datetime(2026, 10, 6, 7, 30, tzinfo=UTC))
    assert res.mode == "aggressive" and res.freed_bytes == 11_500_000_000 and res.free_bytes_after == 61 * GB
    assert len(calls) == 2
    save(res, tmp_path / "cleanup_state.json")
    data = load(tmp_path / "cleanup_state.json")
    assert data is not None and data["freed_bytes"] == 11_500_000_000 and data["announced"] is False


def test_docker_com_erro_nao_quebra():
    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 1, "", "Cannot connect to the Docker daemon")

    res = clean(CleanupConfig(), runner=runner, usage=lambda p: (50.0, 400 * GB))
    assert res.freed_bytes == 0 and "Cannot connect" in res.note
