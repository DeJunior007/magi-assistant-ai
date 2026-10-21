"""Scripts do host do node 2 e runbook (Y1.2, design §10–§11, spec §9.3).

Nada roda de verdade: `bash -n`, leitura estática e execução com comandos FALSOS num PATH em tmp
(docker, ufw, tailscale, git, curl, systemctl… só registram a chamada num log).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOST = REPO / "deploy" / "ayanami" / "host"
RUNBOOK = REPO / "docs" / "ayanami" / "runbook.md"
SCRIPTS = ["preparar.sh", "ufw.sh", "tailscale.sh", "deploy.sh", "limpar-multivideos.sh"]
BASH = shutil.which("bash") or "/bin/bash"

# Tudo que um script poderia chamar com efeito no sistema: sempre falso no teste.
FALSOS = [
    "id",
    "hostname",
    "ip",
    "docker",
    "ufw",
    "tailscale",
    "systemctl",
    "curl",
    "git",
    "apt-get",
    "useradd",
    "usermod",
    "getent",
    "sshd",
    "wg-quick",
    "sleep",
    "chown",
    "sudo",
    "ssh",
    "scp",
]

FAKE = r"""#!/bin/bash
nome="$(basename "$0")"
echo "$nome $*" >> "$FAKE_LOG"
case "$nome $*" in
  "id -u") echo "${FAKE_UID:-0}" ;;
  "hostname -I") echo "${FAKE_IPS:-}" ;;
  "hostname "|"hostname") echo "${FAKE_HOSTNAME:-}" ;;
  "ip link show wg0") exit "${FAKE_IP_WG_RC:-1}" ;;
  "docker compose pull --help") echo "  --ignore-buildable  Ignore images that can be built" ;;
  "docker ps --format"*) printf '%b' "${FAKE_DOCKER_PS:-}" ;;
  "docker ps -a -q"*) : ;;
  "docker ps -a"*) printf '%b' "${FAKE_DOCKER_PS_A:-}" ;;
  "docker volume ls"*) printf '%b' "${FAKE_VOLUMES:-}" ;;
  "docker inspect"*) echo false ;;
  "ufw status numbered") printf '%b' "${FAKE_UFW_NUMBERED:-}" ;;
  "ufw status"*) printf '%b' "${FAKE_UFW_STATUS:-}" ;;
  "tailscale status --json") printf '%s' "${FAKE_TS_JSON:-}" ;;
  "tailscale serve status") printf '%b' "${FAKE_TS_SERVE:-}" ;;
  "tailscale funnel status") printf '%b' "${FAKE_TS_FUNNEL:-}" ;;
  "curl -fsSL"*) : ;;
  "curl "*) echo '{"ok":true}'; exit "${FAKE_CURL_RC:-0}" ;;
  "getent group docker") echo "docker:x:991:" ;;
  "getent passwd"*) exit "${FAKE_GETENT_RC:-0}" ;;
esac
exit 0
"""


@pytest.fixture
def ambiente(tmp_path: Path):
    """PATH com os falsos na frente; devolve (rodar, log)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "_fake"
    fake.write_text(FAKE)
    fake.chmod(0o755)
    for nome in FALSOS:
        (bindir / nome).symlink_to(fake)
    log = tmp_path / "chamadas.log"
    log.write_text("")

    def rodar(script: str, *args: str, entrada: str = "", **env: str) -> subprocess.CompletedProcess:
        e = {
            "PATH": f"{bindir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "LANG": "C.UTF-8",
            "FAKE_LOG": str(log),
            **env,
        }
        return subprocess.run(
            [BASH, str(HOST / script), *args],
            input=entrada,
            capture_output=True,
            text=True,
            env=e,
            cwd=tmp_path,
            timeout=30,
        )

    return rodar, log


def chamadas(log: Path) -> list[str]:
    return [linha for linha in log.read_text().splitlines() if linha]


# --- estático -------------------------------------------------------------------------------------


@pytest.mark.parametrize("nome", SCRIPTS)
def test_sintaxe_e_modo_estrito(nome: str) -> None:
    caminho = HOST / nome
    subprocess.run([BASH, "-n", str(caminho)], check=True)
    texto = caminho.read_text()
    assert texto.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in texto
    assert os.access(caminho, os.X_OK)


@pytest.mark.parametrize("nome", SCRIPTS)
def test_nada_proibido(nome: str) -> None:
    texto = (HOST / nome).read_text()
    assert not re.search(r"compose\s+down", texto)
    assert not re.search(r"\bDROP\b|\bTRUNCATE\b|--clean", texto)
    # Só o limpar remove volume, e só os de modelos (ollama/whisper), nunca ayanami/magi.
    if nome == "limpar-multivideos.sh":
        assert len(re.findall(r"volume\s+rm", texto)) == 1
        assert "grep -viE 'ayanami|magi'" in texto
    else:
        assert not re.search(r"volume\s+(rm|remove|prune)", texto)


@pytest.mark.parametrize("arquivo", [*(HOST / s for s in SCRIPTS), RUNBOOK])
def test_sem_host_real_nem_segredo(arquivo: Path) -> None:
    texto = arquivo.read_text()
    ips = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", texto))
    assert ips <= {"127.0.0.1", "0.0.0.0"}, ips
    assert not re.search(r"ayn_[a-z]+_[A-Za-z0-9]{8,}", texto)
    assert not re.search(r"tskey-[A-Za-z0-9-]{8,}", texto)
    assert not re.search(r"\bvmi\d+\b|contaboserver\.net", texto)
    assert not re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY", texto)
    assert not re.search(r"\b\w+\.ts\.net\b", texto.replace("ayanami.<tailnet>.ts.net", ""))


def test_ufw_so_22_e_41641_e_22_antes_de_ligar() -> None:
    texto = (HOST / "ufw.sh").read_text()
    allows = re.findall(r"^ufw allow (\S+)", texto, re.M)
    assert allows == ["22/tcp", "41641/udp"]
    assert "ufw default deny incoming" in texto
    assert texto.index("ufw allow 22/tcp") < texto.index("ufw --force enable")


def test_tailscale_hostname_e_serve() -> None:
    texto = (HOST / "tailscale.sh").read_text()
    assert 'HOSTNAME_TS="ayanami"' in texto
    assert 'tailscale serve --bg --https=443 "$ALVO"' in texto
    assert 'ALVO="http://127.0.0.1:8740"' in texto
    assert "--advertise-exit-node" not in texto and "--advertise-routes" not in texto


def test_runbook_cobre_y15_e_y16_na_ordem() -> None:
    texto = RUNBOOK.read_text()
    passos = [
        "Painel da Contabo",
        "limpar-multivideos.sh --host-esperado",
        "--sim",
        "Conta do Tailscale",
        "preparar.sh --repo",
        "ufw.sh",
        "tailscale.sh",
        "nmap",
        "/opt/ayanami/.env",
        "ayanami.toml",
        "host/deploy.sh",
        "dispositivo criar pc --tipo pc",
        "ayanami-vigia.timer",
        "ts.net/saude",
        "claude mcp add",
        "mcp-remote",
        "AYANAMI_SSH_KEY",
    ]
    # cada passo aparece depois do anterior (busca sequencial)
    pos = 0
    for passo in passos:
        achado = texto.find(passo, pos)
        assert achado >= 0, f"{passo!r} fora de ordem ou ausente"
        pos = achado + len(passo)
    for secao in ("Rollback por tag", "Ver filas", "Girar token", "Restore manual", "Alertas do vigia"):
        assert secao in texto
    assert "/mcp/" in texto
    for alerta in (
        "/saude",
        "Disco > 85%",
        "batimento",
        "Snapshot `pc`",
        "Snapshot `ayanami`",
        "Restore de teste",
    ):
        assert alerta in texto


# --- limpar-multivideos ---------------------------------------------------------------------------

MV_NO_NODE2 = {
    "FAKE_HOSTNAME": "node-dois",
    "FAKE_IPS": "192.0.2.10 100.64.0.5",
    "FAKE_DOCKER_PS": "",
    "FAKE_DOCKER_PS_A": "multivideos-ollama-1\\nmultivideos-whisper-1\\n",
    "FAKE_VOLUMES": "multivideos_ollama_models\\nmultivideos_whisper\\nayanami-modelos\\nayanami-pgdata\\n",
    "FAKE_IP_WG_RC": "0",
    "FAKE_UFW_NUMBERED": (
        "Status: active\\n\\n     To                         Action      From\\n"
        "[ 1] 22/tcp                     ALLOW IN    Anywhere\\n"
        "[ 2] 8080/tcp                   ALLOW IN    Anywhere\\n"
        "[ 3] 51820/udp                  ALLOW IN    Anywhere\\n"
        "[ 4] 22/tcp (v6)                ALLOW IN    Anywhere (v6)\\n"
    ),
}
ARGS = ("--host-esperado", "node-dois", "--ip-esperado", "192.0.2.10")
DESTRUTIVOS = re.compile(r"^(docker (container rm|volume rm)|ufw --force delete|wg-quick|systemctl disable)")


def _raiz(tmp_path: Path) -> Path:
    raiz = tmp_path / "raiz"
    (raiz / "opt" / "multivideos").mkdir(parents=True)
    (raiz / "opt" / "multivideos" / "docker-compose.node2.yml").write_text("x")
    (raiz / "root").mkdir()
    (raiz / "root" / "docker-compose.node2.yml").write_text("x")
    (raiz / "etc" / "wireguard").mkdir(parents=True)
    (raiz / "etc" / "wireguard" / "wg0.conf").write_text("[Interface]\n")
    return raiz


def test_limpar_dry_run_lista_e_nao_apaga(ambiente, tmp_path: Path) -> None:
    rodar, log = ambiente
    raiz = _raiz(tmp_path)
    r = rodar("limpar-multivideos.sh", *ARGS, FAKE_UID="1000", LIMPAR_RAIZ=str(raiz), **MV_NO_NODE2)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert f"diretório: {raiz}/opt/multivideos" in out
    assert f"arquivo: {raiz}/root/docker-compose.node2.yml" in out
    assert "contêiner parado: multivideos-ollama-1" in out
    assert "volume: multivideos_ollama_models" in out and "volume: multivideos_whisper" in out
    assert "ayanami-modelos" not in out and "ayanami-pgdata" not in out
    assert "wireguard: wg0" in out
    assert "regra ufw [3]: 51820/udp" in out and "regra ufw [2]: 8080/tcp" in out
    assert "[1]" not in out and "[4]" not in out
    assert "dry-run" in out
    assert not [c for c in chamadas(log) if DESTRUTIVOS.match(c)]
    assert (raiz / "opt" / "multivideos").is_dir() and (raiz / "etc" / "wireguard" / "wg0.conf").exists()


@pytest.mark.parametrize(
    "muda",
    [
        {"FAKE_HOSTNAME": "outro"},
        {"FAKE_IPS": "198.51.100.7"},
        {"FAKE_DOCKER_PS": "wedding-app-1 wedding:latest\\n"},
        {"FAKE_DOCKER_PS": "gold-crm-api-1 gold-crm:1\\n"},
    ],
)
def test_limpar_aborta_fora_do_node2(ambiente, tmp_path: Path, muda: dict) -> None:
    rodar, log = ambiente
    raiz = _raiz(tmp_path)
    r = rodar(
        "limpar-multivideos.sh",
        *ARGS,
        "--sim",
        entrada="s\n" * 20,
        LIMPAR_RAIZ=str(raiz),
        **{**MV_NO_NODE2, **muda},
    )
    assert r.returncode == 3
    assert "ABORTADO" in r.stderr
    feitas = chamadas(log)
    assert not [c for c in feitas if DESTRUTIVOS.match(c)]
    assert not any(c.startswith(("docker volume", "ufw")) for c in feitas)
    assert (raiz / "opt" / "multivideos").is_dir()


def test_limpar_exige_host_e_ip(ambiente) -> None:
    rodar, log = ambiente
    r = rodar("limpar-multivideos.sh", "--sim", **MV_NO_NODE2)
    assert r.returncode == 2
    assert chamadas(log) == []


def test_limpar_sim_confirma_item_a_item(ambiente, tmp_path: Path) -> None:
    rodar, log = ambiente
    raiz = _raiz(tmp_path)
    # ordem: dir, arquivo, 2 contêineres, 2 volumes, wg0, regras 3 e 2
    respostas = "s\nn\ns\nn\ns\nn\ns\ns\nn\n"
    r = rodar(
        "limpar-multivideos.sh", *ARGS, "--sim", entrada=respostas, LIMPAR_RAIZ=str(raiz), **MV_NO_NODE2
    )
    assert r.returncode == 0, r.stderr
    feitas = [c for c in chamadas(log) if DESTRUTIVOS.match(c)]
    assert "docker container rm multivideos-ollama-1" in feitas
    assert "docker container rm multivideos-whisper-1" not in feitas
    assert "docker volume rm multivideos_ollama_models" in feitas
    assert not any("ayanami" in c for c in feitas)
    assert "ufw --force delete 3" in feitas and "ufw --force delete 2" not in feitas
    assert not (raiz / "opt" / "multivideos").exists()
    assert (raiz / "root" / "docker-compose.node2.yml").exists()
    assert not (raiz / "etc" / "wireguard" / "wg0.conf").exists()
    assert list((raiz / "var" / "backups").glob("limpar-multivideos-*/wg0.conf"))


def test_limpar_sim_sem_root_recusa(ambiente, tmp_path: Path) -> None:
    rodar, log = ambiente
    r = rodar(
        "limpar-multivideos.sh",
        *ARGS,
        "--sim",
        FAKE_UID="1000",
        LIMPAR_RAIZ=str(_raiz(tmp_path)),
        **MV_NO_NODE2,
    )
    assert r.returncode == 1
    assert not [c for c in chamadas(log) if DESTRUTIVOS.match(c)]


# --- deploy ---------------------------------------------------------------------------------------


def _opt(tmp_path: Path, env: str = "POSTGRES_PASSWORD=x\n") -> Path:
    opt = tmp_path / "opt-ayanami"
    (opt / ".git").mkdir(parents=True)
    (opt / "deploy" / "ayanami").mkdir(parents=True)
    (opt / "deploy" / "ayanami" / "compose.yml").write_text("name: ayanami\n")
    (opt / ".env").write_text(env)
    return opt


def test_deploy_sequencia_da_spec(ambiente, tmp_path: Path) -> None:
    rodar, log = ambiente
    opt = _opt(tmp_path)
    r = rodar("deploy.sh", AYANAMI_DIR=str(opt), AYANAMI_SAUDE_ESPERA="0")
    assert r.returncode == 0, r.stderr
    assert chamadas(log) == [
        f"git -C {opt} pull --ff-only",
        "docker compose pull --ignore-buildable",
        "docker compose build",
        "docker compose --profile ops run --rm migrar",
        "docker compose up -d",
        "curl -fsS http://127.0.0.1:8740/saude",
    ]


def test_deploy_rollback_por_tag_sem_git_e_com_ghcr(ambiente, tmp_path: Path) -> None:
    rodar, log = ambiente
    opt = _opt(tmp_path, "POSTGRES_PASSWORD=x\nAYANAMI_IMAGEM=ghcr.io/dono/ayanami\nAYANAMI_TAG=novo\n")
    r = rodar("deploy.sh", "--sem-git", "--tag", "abc123", AYANAMI_DIR=str(opt), AYANAMI_SAUDE_ESPERA="0")
    assert r.returncode == 0, r.stderr
    feitas = chamadas(log)
    assert not any(c.startswith("git") for c in feitas)
    assert "docker compose build" not in feitas
    assert "docker compose pull --quiet" in feitas  # com ghcr baixa também os serviços com `build:`
    env = (opt / ".env").read_text()
    assert "AYANAMI_TAG=abc123" in env and "AYANAMI_TAG=novo" not in env


def test_deploy_tag_invalida_e_saude_falhando(ambiente, tmp_path: Path) -> None:
    rodar, log = ambiente
    opt = _opt(tmp_path)
    r = rodar("deploy.sh", "--tag", "x;rm", AYANAMI_DIR=str(opt))
    assert r.returncode == 2
    r = rodar(
        "deploy.sh",
        "--sem-git",
        AYANAMI_DIR=str(opt),
        AYANAMI_SAUDE_ESPERA="0",
        AYANAMI_SAUDE_TENTATIVAS="3",
        FAKE_CURL_RC="22",
    )
    assert r.returncode == 1
    assert sum(c.startswith("curl") for c in chamadas(log)) == 3


# --- ufw / tailscale / preparar ---------------------------------------------------------------------


def test_ufw_roda_na_ordem_e_avisa_extras(ambiente) -> None:
    rodar, log = ambiente
    r = rodar(
        "ufw.sh",
        FAKE_UFW_STATUS=(
            "22/tcp                     ALLOW       Anywhere\\n"
            "8080/tcp                   ALLOW       Anywhere\\n"
        ),
        FAKE_DOCKER_PS="velho 0.0.0.0:8080->8080/tcp\\nayanami-api 127.0.0.1:8740->8740/tcp\\n",
    )
    assert r.returncode == 0, r.stderr
    feitas = chamadas(log)
    assert feitas.index("ufw allow 22/tcp") < feitas.index("ufw --force enable")
    assert "ufw allow 41641/udp" in feitas and "ufw default deny incoming" in feitas
    assert "8080/tcp" in r.stdout and "velho 0.0.0.0" in r.stdout
    assert "ayanami-api" not in r.stdout
    assert not any(c.startswith("ufw delete") or "--force delete" in c for c in feitas)


def test_tailscale_up_e_serve_e_idempotente(ambiente) -> None:
    rodar, log = ambiente
    r = rodar("tailscale.sh", FAKE_TS_JSON='{"BackendState":"NeedsLogin"}')
    assert r.returncode == 0, r.stderr
    feitas = chamadas(log)
    assert "tailscale up --hostname=ayanami --advertise-tags=tag:ayanami --ssh" in feitas
    assert "tailscale serve --bg --https=443 http://127.0.0.1:8740" in feitas

    log.write_text("")
    r = rodar(
        "tailscale.sh",
        FAKE_TS_JSON='{"BackendState":"Running","Self":{"HostName":"ayanami"}}',
        FAKE_TS_SERVE="https://ayanami.x (tailnet only)\\n|-- / proxy http://127.0.0.1:8740\\n",
    )
    assert r.returncode == 0, r.stderr
    feitas = chamadas(log)
    assert not any(c.startswith(("tailscale up", "tailscale serve --bg")) for c in feitas)


def test_tailscale_recusa_funnel(ambiente) -> None:
    rodar, _ = ambiente
    r = rodar(
        "tailscale.sh",
        FAKE_TS_JSON='{"BackendState":"Running","Self":{"HostName":"ayanami"}}',
        FAKE_TS_FUNNEL="Funnel on\\n",
    )
    assert r.returncode == 1


def test_preparar_grava_docker_gid_links_e_e_idempotente(ambiente, tmp_path: Path) -> None:
    rodar, log = ambiente
    raiz = tmp_path / "raiz"
    (raiz / "etc").mkdir(parents=True)
    (raiz / "etc" / "os-release").write_text("ID=ubuntu\n")
    opt = raiz / "opt" / "ayanami"
    (opt / ".git" / "info").mkdir(parents=True)
    (opt / "deploy" / "ayanami").mkdir(parents=True)
    for _ in range(2):
        r = rodar("preparar.sh", PREPARAR_RAIZ=str(raiz))
        assert r.returncode == 0, r.stderr
    env = opt / ".env"
    assert env.read_text() == "DOCKER_GID=991\n"
    assert env.stat().st_mode & 0o777 == 0o600
    for nome in (".env", "ayanami.toml", "dados"):
        assert os.readlink(opt / "deploy" / "ayanami" / nome) == str(opt / nome)
    exclude = (opt / ".git" / "info" / "exclude").read_text().splitlines()
    assert exclude.count("/.env") == 1
    assert (opt / "dados" / "restic-cache").is_dir()
    # sem chave autorizada: não desliga senha do SSH
    assert not (raiz / "etc" / "ssh" / "sshd_config.d" / "50-ayanami.conf").exists()
    assert "usermod -aG docker ayanami" in chamadas(log)


def test_preparar_com_chave_desliga_senha(ambiente, tmp_path: Path) -> None:
    rodar, log = ambiente
    raiz = tmp_path / "raiz"
    (raiz / "etc").mkdir(parents=True)
    (raiz / "etc" / "os-release").write_text("ID=debian\n")
    (raiz / "root" / ".ssh").mkdir(parents=True)
    (raiz / "root" / ".ssh" / "authorized_keys").write_text("ssh-ed25519 AAAA teste\n")
    opt = raiz / "opt" / "ayanami"
    (opt / ".git" / "info").mkdir(parents=True)
    (opt / "deploy" / "ayanami").mkdir(parents=True)
    r = rodar("preparar.sh", PREPARAR_RAIZ=str(raiz))
    assert r.returncode == 0, r.stderr
    conf = (raiz / "etc" / "ssh" / "sshd_config.d" / "50-ayanami.conf").read_text()
    assert "PasswordAuthentication no" in conf
    assert "sshd -t" in chamadas(log)


def test_preparar_recusa_sem_root_e_distro_estranha(ambiente, tmp_path: Path) -> None:
    rodar, log = ambiente
    raiz = tmp_path / "raiz"
    (raiz / "etc").mkdir(parents=True)
    (raiz / "etc" / "os-release").write_text("ID=fedora\n")
    assert rodar("preparar.sh", PREPARAR_RAIZ=str(raiz), FAKE_UID="1000").returncode == 1
    assert rodar("preparar.sh", PREPARAR_RAIZ=str(raiz)).returncode == 1
    assert not any(c.startswith("apt-get") for c in chamadas(log))
