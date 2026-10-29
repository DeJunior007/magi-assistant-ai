"""Compose e Dockerfile da Ayanami (Y1.1, spec §9.3, CA-Y29, RNF-A6). Só leitura estática: nada sobe."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DIR = REPO / "deploy" / "ayanami"
COMPOSE = DIR / "compose.yml"
DOCKERFILE = DIR / "Dockerfile"
DOCKERIGNORE = REPO / ".dockerignore"

SERVICOS = {
    "ayanami-pg",
    "migrar",
    "ayanami-api",
    "worker-rapido",
    "worker-agendado",
    "worker-lento",
    "ayanami-voz",
    "ntfy",  # condessa-celular M1.6 (detalhes em test_compose_ntfy.py)
}
# Imagens de terceiros: sem .env, sem ./dados nem ayanami.toml.
TERCEIROS = {"ayanami-pg", "ntfy"}
# Limites da spec §9.3 / §4.1 / design §4.4.
LIMITES = {
    "ayanami-pg": (2, "2g"),
    "ayanami-api": (1, "1g"),
    "worker-rapido": (1, "512m"),
    "worker-agendado": (1.5, "1g"),
    "worker-lento": (4, "6g"),
    "ayanami-voz": (2, "1536m"),
    "ntfy": (0.5, "128m"),
}
# Nada do node 1 (MultiVideos, wedding, gold-crm) aparece na infra da Ayanami.
NODE1 = re.compile(r"multivideos|wedding|gold-?crm", re.I)


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def servicos(compose: dict) -> dict:
    return compose["services"]


def _bytes(v: str | int) -> int:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmg]?)b?", str(v).strip().lower())
    assert m, f"mem_limit ilegível: {v!r}"
    mult = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[m.group(2)]
    return int(float(m.group(1)) * mult)


def _ops(svc: dict) -> bool:
    return "ops" in (svc.get("profiles") or [])


def _volumes(svc: dict) -> list[str]:
    out = []
    for v in svc.get("volumes") or []:
        out.append(v if isinstance(v, str) else f"{v.get('source', '')}:{v.get('target', '')}")
    return out


def test_nome_e_servicos(compose: dict, servicos: dict) -> None:
    assert compose["name"] == "ayanami"
    assert set(servicos) == SERVICOS
    assert servicos["migrar"]["profiles"] == ["ops"]
    assert [s for s, d in servicos.items() if _ops(d)] == ["migrar"]


def test_ca_y29_portas_so_em_loopback(servicos: dict) -> None:
    publicadas = {}
    for nome, svc in servicos.items():
        for p in svc.get("ports") or []:
            assert isinstance(p, str), f"{nome}: use a forma curta com IP ('127.0.0.1:h:c')"
            assert p.startswith("127.0.0.1:"), f"{nome}: porta {p} fora de 127.0.0.1"
            publicadas[nome] = p
    assert publicadas == {
        "ayanami-pg": "127.0.0.1:54339:5432",
        "ayanami-api": "127.0.0.1:8740:8740",
        "ntfy": "127.0.0.1:8742:80",
    }
    assert "ports" not in servicos["ayanami-voz"]
    assert "network_mode" not in str(servicos)  # nada de rede do host


def test_ca_y29_restart_limites_healthcheck(servicos: dict) -> None:
    for nome, svc in servicos.items():
        if _ops(svc):
            assert "healthcheck" not in svc
            continue
        assert svc["restart"] == "unless-stopped", nome
        cpus, mem = LIMITES[nome]
        assert float(svc["cpus"]) == cpus, nome
        assert _bytes(svc["mem_limit"]) == _bytes(mem), nome
        hc = svc["healthcheck"]
        assert hc["test"] and hc["test"][0] in ("CMD", "CMD-SHELL"), nome
        assert (hc["interval"], hc["timeout"], hc["retries"]) == ("30s", "5s", 3), nome


def test_healthchecks_da_spec(servicos: dict) -> None:
    def cmd(s: str) -> str:
        return " ".join(servicos[s]["healthcheck"]["test"][1:])

    assert cmd("ayanami-pg") == "pg_isready -U ayanami"
    assert cmd("ayanami-api") == "curl -fsS localhost:8740/saude"
    assert cmd("ayanami-voz") == "curl -fsS localhost:8741/saude"
    for svc, fila in (
        ("worker-rapido", "rapida"),
        ("worker-agendado", "agendada"),
        ("worker-lento", "lenta"),
    ):
        assert cmd(svc) == f"ayanami batimento {fila} --max 90"
        assert servicos[svc]["command"] == ["ayanami", "worker", fila]


def test_comandos_e_dependencias(servicos: dict) -> None:
    assert servicos["ayanami-pg"]["image"] == "pgvector/pgvector:pg16"
    assert "shared_buffers=512MB" in servicos["ayanami-pg"]["command"]
    assert "max_connections=40" in servicos["ayanami-pg"]["command"]
    api = " ".join(servicos["ayanami-api"]["command"])
    assert api == "uvicorn ayanami.api.app:app_de_producao --factory --host 0.0.0.0 --port 8740 --workers 1"
    assert servicos["ayanami-voz"]["command"] == ["ayanami", "voz", "--port", "8741"]
    migrar = " ".join(servicos["migrar"]["command"])
    assert migrar.startswith("sh -c ayanami migrar &&")
    assert "procrastinate --app=ayanami.fila.app schema --apply" in migrar
    assert "to_regclass" in migrar and "procrastinate_jobs" in migrar  # idempotente
    for nome in ("migrar", "ayanami-api", "worker-rapido", "worker-agendado", "worker-lento"):
        assert servicos[nome]["depends_on"]["ayanami-pg"]["condition"] == "service_healthy", nome
    assert "depends_on" not in servicos["ayanami-voz"]
    assert servicos["worker-lento"]["cpu_shares"] == 512


def test_rnf_a6_orcamento(servicos: dict) -> None:
    ativos = [s for s in servicos.values() if not _ops(s)]
    assert sum(_bytes(s["mem_limit"]) for s in ativos) <= 13 * 1024**3
    assert float(servicos["worker-lento"]["cpus"]) + float(servicos["ayanami-voz"]["cpus"]) <= 6


def test_ca_y29_docker_sock_so_no_agendado(servicos: dict) -> None:
    com_sock = [n for n, s in servicos.items() if any("docker.sock" in v for v in _volumes(s))]
    assert com_sock == ["worker-agendado"]


def test_ca_y29_env_nunca_montado(servicos: dict) -> None:
    for nome, svc in servicos.items():
        for v in _volumes(svc):
            origem = v.split(":", 1)[0]
            assert not re.search(r"(^|/)\.env(\.|$)", origem), f"{nome} monta {v}"
        if nome == "ntfy":
            assert "env_file" not in svc
        elif not _ops(svc):
            assert svc["env_file"] == ".env", nome


def test_volumes_rede_e_logs(compose: dict, servicos: dict) -> None:
    assert set(compose["volumes"]) == {"ayanami-pgdata", "ayanami-modelos", "ntfy-cache", "ntfy-auth"}
    assert "ayanami-pgdata:/var/lib/postgresql/data" in _volumes(servicos["ayanami-pg"])
    com_modelos = {
        n for n, s in servicos.items() if any(v.startswith("ayanami-modelos:") for v in _volumes(s))
    }
    assert com_modelos == {"worker-lento", "ayanami-voz"}
    for nome, svc in servicos.items():
        assert svc["networks"] == ["ayanami"], nome
        assert svc["logging"]["driver"] == "json-file", nome
        assert svc["logging"]["options"] == {"max-size": "10m", "max-file": "3"}, nome
        if nome not in TERCEIROS:
            vols = _volumes(svc)
            assert "./dados:/dados" in vols, nome
            assert "./ayanami.toml:/etc/ayanami/ayanami.toml:ro" in vols, nome
            assert svc["environment"]["TZ"] == "America/Sao_Paulo", nome
    agendado = _volumes(servicos["worker-agendado"])
    assert "./compose.yml:/opt-config/compose.yml:ro" in agendado
    assert "./ayanami.toml:/opt-config/ayanami.toml:ro" in agendado


def test_variante_ml_so_no_lento_e_voz(servicos: dict) -> None:
    ml = {n for n, s in servicos.items() if (s.get("build") or {}).get("args", {}).get("AYANAMI_ML") == "1"}
    assert ml == {"worker-lento", "ayanami-voz"}
    for nome in ml:
        assert servicos[nome]["image"].endswith("-ml")


def test_nada_do_node1_nem_segredo_literal() -> None:
    for arq in (COMPOSE, DOCKERFILE, DOCKERIGNORE):
        texto = arq.read_text(encoding="utf-8")
        assert not NODE1.search(texto), arq
        assert not re.search(r"ayn_[A-Za-z0-9]|sk-[A-Za-z0-9]{8}", texto), arq
    assert "POSTGRES_PASSWORD:" not in COMPOSE.read_text(encoding="utf-8")  # vem só do .env


def test_dockerfile() -> None:
    texto = DOCKERFILE.read_text(encoding="utf-8")
    assert len(re.findall(r"^FROM ", texto, re.M)) >= 2  # multi-stage
    assert "astral-sh/uv" in texto and "uv sync --frozen" in texto
    assert "--extra ayanami-ml" in texto and "ARG AYANAMI_ML=0" in texto
    assert "TZ=America/Sao_Paulo" in texto
    assert re.search(r"groupadd .*ayanami", texto) and re.search(r"useradd .*ayanami", texto)
    usuarios = re.findall(r"^USER (\S+)", texto, re.M)
    assert usuarios and usuarios[-1] == "ayanami"  # a imagem final não roda como root
    assert "curl" in texto  # healthchecks da API e da voz


def test_dockerignore_fecha_segredos() -> None:
    linhas = [ln.strip() for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()]
    regras = [ln for ln in linhas if ln and not ln.startswith("#")]
    assert regras[0] == "*"  # tudo fora por padrão
    assert "**/.env" in regras and "**/.env.*" in regras
    liberados = {r[1:] for r in regras if r.startswith("!")}
    assert liberados >= {"pyproject.toml", "uv.lock", "README.md", "magi/", "ayanami/"}
    assert not any(".env" in r or ".git/" == r or "scratch" in r for r in liberados)


# --- Y1.0b: perfil enxuto do node 2 compartilhado com outro serviço (compose.node2.yml) ---

NODE2 = DIR / "compose.node2.yml"
# (cpus, mem_limit, memswap_limit) decididos pelo Pedro para os núcleos 6-7.
LIMITES_NODE2 = {
    "ayanami-pg": (1, "1g", "1g"),
    "ayanami-api": (0.5, "512m", "512m"),
    "worker-rapido": (0.5, "384m", "384m"),
    "worker-agendado": (0.5, "512m", "512m"),
    "worker-lento": (2, "3g", "5g"),
    "ayanami-voz": (1.5, "1g", "2g"),
    "ntfy": (0.25, "64m", "64m"),
}


@pytest.fixture(scope="module")
def node2() -> dict:
    return yaml.safe_load(NODE2.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mesclado(servicos: dict, node2: dict) -> dict:
    """Como o `docker compose -f compose.yml -f compose.node2.yml` mescla: chave a chave por serviço."""
    return {nome: {**svc, **(node2["services"].get(nome) or {})} for nome, svc in servicos.items()}


def test_node2_so_sobrepoe_servicos_existentes(servicos: dict, node2: dict) -> None:
    assert set(node2) == {"services"}  # sem rede, volume ou nome novos
    assert set(node2["services"]) <= set(servicos)
    for nome, svc in node2["services"].items():
        assert "ports" not in svc and "volumes" not in svc and "image" not in svc, nome


def test_node2_limites_e_soma(mesclado: dict) -> None:
    ativos = {n: s for n, s in mesclado.items() if not _ops(s)}
    assert set(ativos) == set(LIMITES_NODE2)
    for nome, (cpus, mem, swap) in LIMITES_NODE2.items():
        svc = ativos[nome]
        assert float(svc["cpus"]) == cpus, nome
        assert _bytes(svc["mem_limit"]) == _bytes(mem), nome
        assert _bytes(svc["memswap_limit"]) == _bytes(swap), nome
        assert float(svc["cpus"]) <= 2, nome  # nunca mais que os 2 núcleos do cpuset
    assert sum(_bytes(s["mem_limit"]) for s in ativos.values()) <= 6.5 * 1024**3


def test_node2_swap_so_no_lento_e_voz(mesclado: dict) -> None:
    extra = {
        n: _bytes(s["memswap_limit"]) - _bytes(s["mem_limit"]) for n, s in mesclado.items() if not _ops(s)
    }
    assert extra == {
        "ayanami-pg": 0,
        "ayanami-api": 0,
        "worker-rapido": 0,
        "worker-agendado": 0,
        "worker-lento": 2 * 1024**3,
        "ayanami-voz": 1 * 1024**3,
        "ntfy": 0,
    }


def test_node2_cpuset_em_todos(mesclado: dict) -> None:
    for nome, svc in mesclado.items():
        assert svc.get("cpuset") == "6,7", nome


def test_node2_workers_parada_graciosa(mesclado: dict) -> None:
    for nome in ("worker-rapido", "worker-agendado", "worker-lento"):
        m = re.fullmatch(r"(\d+)s", str(mesclado[nome]["stop_grace_period"]))
        assert m and int(m.group(1)) >= 35, nome


def test_node2_pg_cabe_no_limite(mesclado: dict) -> None:
    cmd = mesclado["ayanami-pg"]["command"]
    sb = next(c.split("=", 1)[1] for c in cmd if c.startswith("shared_buffers="))
    assert _bytes(sb.removesuffix("B")) <= _bytes(mesclado["ayanami-pg"]["mem_limit"]) // 2
    assert "max_connections=40" in cmd


def test_node2_portas_so_em_loopback_e_nome_neutro(mesclado: dict) -> None:
    for nome, svc in mesclado.items():
        for p in svc.get("ports") or []:
            assert str(p).startswith("127.0.0.1:"), f"{nome}: {p}"
    texto = NODE2.read_text(encoding="utf-8")
    assert not re.search(r"minecraft", texto, re.I)
    assert not NODE1.search(texto)


def test_node2_concorrencia_lenta_um_por_vez() -> None:
    toml = (DIR / "ayanami.example.toml").read_text(encoding="utf-8")
    assert re.search(r"^lenta_concorrencia\s*=\s*1\b", toml, re.M)
