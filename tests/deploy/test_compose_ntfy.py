"""ntfy no Compose da Ayanami (condessa-celular M1.6, spec §10, DSC6, CA-M35). Só leitura estática."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DIR = REPO / "deploy" / "ayanami"
COMPOSE = DIR / "compose.yml"
NODE2 = DIR / "compose.node2.yml"
SERVER = DIR / "ntfy" / "server.yml"
TAILSCALE = DIR / "host" / "tailscale.sh"
ENV_EXEMPLO = DIR / "env.example"
RUNBOOK = REPO / "docs" / "ayanami" / "runbook.md"

ARQUIVOS = (COMPOSE, NODE2, SERVER, TAILSCALE, ENV_EXEMPLO, RUNBOOK)
TS_NET = re.compile(r"[\w.-]+\.ts\.net")
IPV4 = re.compile(r"\b(?!127\.0\.0\.1\b)(?:\d{1,3}\.){3}\d{1,3}\b")


def _bytes(v: str | int) -> int:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmg]?)b?", str(v).strip().lower())
    assert m, f"mem_limit ilegível: {v!r}"
    return int(float(m.group(1)) * {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[m.group(2)])


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ntfy(compose: dict) -> dict:
    return compose["services"]["ntfy"]


@pytest.fixture(scope="module")
def server() -> dict:
    return yaml.safe_load(SERVER.read_text(encoding="utf-8"))


def test_ca_m35_porta_so_loopback_8742(ntfy: dict) -> None:
    assert ntfy["ports"] == ["127.0.0.1:8742:80"]
    assert "network_mode" not in ntfy
    assert ntfy["networks"] == ["ayanami"]


def test_ca_m35_restart_limites_healthcheck(ntfy: dict) -> None:
    assert ntfy["restart"] == "unless-stopped"
    assert float(ntfy["cpus"]) == 0.5
    assert _bytes(ntfy["mem_limit"]) == _bytes("128m")
    hc = ntfy["healthcheck"]
    assert hc["test"] == ["CMD", "wget", "-qO-", "http://localhost/v1/health"]
    assert (hc["interval"], hc["timeout"], hc["retries"]) == ("30s", "5s", 3)
    assert ntfy["logging"]["options"] == {"max-size": "10m", "max-file": "3"}


def test_ca_m35_sem_env_nem_docker_sock(ntfy: dict) -> None:
    assert "env_file" not in ntfy
    vols = [
        v if isinstance(v, str) else f"{v.get('source', '')}:{v.get('target', '')}" for v in ntfy["volumes"]
    ]
    assert not any("docker.sock" in v for v in vols)
    assert not any(re.search(r"(^|/)\.env(\.|$)", v.split(":", 1)[0]) for v in vols)
    assert vols == ["./ntfy:/etc/ntfy:ro", "ntfy-cache:/var/cache/ntfy", "ntfy-auth:/var/lib/ntfy"]
    # Só variáveis não secretas; nada de POSTGRES_*/tokens herdados.
    assert set(ntfy["environment"]) == {"TZ", "NTFY_BASE_URL"}
    assert ntfy["environment"]["TZ"] == "America/Sao_Paulo"


def test_imagem_fixa_e_comando(ntfy: dict, compose: dict) -> None:
    assert re.fullmatch(r"binwiederhier/ntfy:v\d+\.\d+\.\d+", ntfy["image"])
    assert ntfy["command"] == ["serve"]
    assert {"ntfy-cache", "ntfy-auth"} <= set(compose["volumes"])


def test_base_url_vem_do_env_com_placeholder(ntfy: dict) -> None:
    assert ntfy["environment"]["NTFY_BASE_URL"] == "${NTFY_BASE_URL:-https://ayanami.exemplo.ts.net:8443}"
    env = ENV_EXEMPLO.read_text(encoding="utf-8")
    assert re.search(r"^NTFY_BASE_URL=https://ayanami\.exemplo\.ts\.net:8443$", env, re.M)


def test_ca_m35_server_yml(server: dict) -> None:
    assert server["auth-default-access"] == "deny-all"
    assert server["enable-signup"] is False
    assert server["enable-login"] is False
    assert server["web-root"] == "disable"
    assert server["listen-http"] == ":80"
    assert server["behind-proxy"] is True
    assert server["cache-file"] == "/var/cache/ntfy/cache.db"
    assert server["cache-duration"] == "12h"
    assert server["auth-file"] == "/var/lib/ntfy/user.db"
    assert server["visitor-request-limit-burst"] == 60
    assert server["base-url"] == "https://ayanami.exemplo.ts.net:8443"


def test_ca_m35_nenhum_host_real() -> None:
    for arq in ARQUIVOS:
        texto = arq.read_text(encoding="utf-8")
        for host in TS_NET.findall(texto):
            assert "exemplo" in host, f"{arq.name}: host real {host!r}"
        if arq in (COMPOSE, NODE2, SERVER, ENV_EXEMPLO):
            assert not IPV4.search(texto.replace("0.0.0.0", "")), arq.name
        assert not re.search(r"ayn_[A-Za-z0-9]|tk_[A-Za-z0-9]{8}", texto), arq.name


def test_tailscale_serve_8443(ntfy: dict) -> None:
    texto = TAILSCALE.read_text(encoding="utf-8")
    assert 'ALVO_NTFY="http://127.0.0.1:8742"' in texto
    assert 'tailscale serve --bg --https=8443 "$ALVO_NTFY"' in texto
    assert "tailscale funnel --" not in texto and "--https=8443 --funnel" not in texto  # nunca Funnel


def test_perfil_node2_enxuto(compose: dict) -> None:
    """Com COMPOSE_FILE=compose.yml:compose.node2.yml o ntfy fica nos núcleos 6-7, pequeno e sem swap."""
    over = yaml.safe_load(NODE2.read_text(encoding="utf-8"))["services"]["ntfy"]
    svc = {**compose["services"]["ntfy"], **over}
    assert svc["cpuset"] == "6,7"
    assert float(svc["cpus"]) <= 0.5
    assert _bytes(svc["mem_limit"]) <= _bytes("128m")
    assert _bytes(svc["memswap_limit"]) == _bytes(svc["mem_limit"])
    assert set(over) <= {"cpuset", "cpus", "mem_limit", "memswap_limit"}


def test_runbook_secao_ntfy_no_fim() -> None:
    texto = RUNBOOK.read_text(encoding="utf-8")
    titulos = re.findall(r"^## .*$", texto, re.M)
    assert "ntfy" in titulos[-1]
    secao = texto[texto.rindex(titulos[-1]) :]
    for trecho in (
        "ntfy access everyone 'up*' write-only",
        "ntfy user add celular",
        "ntfy access celular 'up*' read-only",
        "NTFY_BASE_URL",
        "8443",
        "bateria",
    ):
        assert trecho in secao, trecho
