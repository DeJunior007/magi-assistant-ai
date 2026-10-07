"""Units systemd --user e hud/install.sh (tarefa 1.17, RNF-11). Nada aqui toca o systemd real."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UNITS = REPO / "deploy" / "systemd"
INSTALL = REPO / "hud" / "install.sh"
SERVICES = ("magi-satellite", "magi-core")


def _unit(path: Path) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    cp.optionxform = str  # mantém a caixa das chaves
    cp.read(path, encoding="utf-8")
    return cp


def _render(tmp_path: Path) -> Path:
    out = tmp_path / "units"
    subprocess.run(["bash", str(INSTALL), "--render-units", str(out)], check=True)
    return out


@pytest.mark.parametrize("name", SERVICES)
def test_servico_reinicia_sempre_em_2s(name: str) -> None:
    u = _unit(UNITS / f"{name}.service")
    assert u["Service"]["Restart"] == "always"
    assert u["Service"]["RestartSec"] == "2"
    # Sem limite de partidas: o núcleo reinicia enquanto o Postgres não sobe.
    assert u["Unit"]["StartLimitIntervalSec"] == "0"
    assert u["Service"]["ExecStart"] == f'"@REPO@/.venv/bin/{name}"'
    assert u["Service"]["WorkingDirectory"] == "@REPO@"
    assert "%h/projetos" not in (UNITS / f"{name}.service").read_text()


def test_satelite_na_sessao_grafica() -> None:
    u = _unit(UNITS / "magi-satellite.service")
    assert u["Unit"]["PartOf"] == "graphical-session.target"
    assert "pipewire.service" in u["Unit"]["After"].split()
    assert u["Install"]["WantedBy"] == "graphical-session.target"
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=%t/bus" in u["Service"]["Environment"]


def test_nucleo_nao_depende_da_unit_do_docker() -> None:
    text = (UNITS / "magi-core.service").read_text()
    assert "docker" not in "".join(
        ln for ln in text.splitlines() if not ln.startswith("#")
    )


def test_install_sh_sintaxe() -> None:
    subprocess.run(["bash", "-n", str(INSTALL)], check=True)


def test_render_usa_caminho_real_do_repo(tmp_path: Path) -> None:
    out = _render(tmp_path)
    names = sorted(p.name for p in out.iterdir())
    assert names == [
        "magi-ayanami.service",
        "magi-ayanami.timer",
        "magi-clean.service",
        "magi-clean.timer",
        "magi-core.service",
        "magi-satellite.service",
    ]
    for name in (*SERVICES, "magi-ayanami", "magi-clean"):
        u = _unit(out / f"{name}.service")
        assert u["Service"]["ExecStart"] == f'"{REPO}/.venv/bin/{name}"'
        assert u["Service"]["WorkingDirectory"] == str(REPO)
    assert not any("@REPO@" in p.read_text() for p in out.iterdir())


@pytest.mark.skipif(not shutil.which("systemd-analyze"), reason="sem systemd-analyze")
def test_systemd_analyze_verify(tmp_path: Path) -> None:
    out = _render(tmp_path)
    for name in (*SERVICES, "magi-ayanami", "magi-clean"):
        if not (REPO / ".venv" / "bin" / name).exists():
            pytest.skip("sem .venv com os executáveis (rode uv sync)")
    r = subprocess.run(
        ["systemd-analyze", "--user", "verify", *sorted(map(str, out.iterdir()))],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def _dry_run(tmp_path: Path, *args: str) -> str:
    env = {**os.environ, "HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "cfg")}
    r = subprocess.run(
        ["bash", str(INSTALL), "--dry-run", *args],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout


def test_dry_run_mostra_e_nao_escreve(tmp_path: Path) -> None:
    out = _dry_run(tmp_path)
    assert "sync --frozen --project" in out
    assert "+ systemctl --user daemon-reload" in out
    assert "+ systemctl --user enable magi-satellite.service magi-core.service" in out
    assert "--now" not in out
    assert "restart" not in out  # sem --start não inicia nada
    assert "HUD: pulado" in out
    assert f"cp {REPO}/config.example.toml" in out
    for proibido in (" down", " rm ", "docker rm", "DROP"):
        assert proibido not in out
    assert list(tmp_path.iterdir()) == []  # nada foi criado


def test_dry_run_start_inicia(tmp_path: Path) -> None:
    out = _dry_run(tmp_path, "--start", "--no-hud")
    assert "+ systemctl --user restart magi-satellite.service magi-core.service" in out
    assert "+ systemctl --user start magi-ayanami.timer magi-clean.timer" in out
    assert "HUD" not in out


def test_dry_run_mantem_config_existente(tmp_path: Path) -> None:
    conf = tmp_path / "cfg" / "magi" / "config.toml"
    conf.parent.mkdir(parents=True)
    conf.write_text("# meu\n")
    out = _dry_run(tmp_path, "--no-hud")
    assert "já existe; mantida" in out
    assert "config.example.toml" not in out
