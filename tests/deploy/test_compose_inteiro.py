"""Perfil "node 2 inteiro" (ayanami-plataforma P0.1, spec §1, DSP1–DSP2, design §4.1): CA-P1, CA-P2, CA-P3.

Mescla `compose.yml` + `compose.node2-inteiro.yml` em Python (sem `docker`). Cada tarefa que cria um
serviço novo acrescenta a sua linha em `ORCAMENTO` (e em `LOTE` quando tiver cpuset).
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_AQUI = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("compose_mesclado", _AQUI / "compose_mesclado.py")
assert _SPEC and _SPEC.loader
cm = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("compose_mesclado", cm)
_SPEC.loader.exec_module(cm)

NODE2_ENXUTO = cm.DIR / "compose.node2.yml"
# sha256 do compose.node2.yml no HEAD em que a P0.1 entrou: o perfil enxuto fica intocado (CA-P2).
NODE2_ENXUTO_SHA256 = "6846cf5dbfe4742d4fd7731bdd6cb24b044e898da892fb8cf966e8ec02e656f6"

# Tabela da spec §1: (mem_limit, memswap_limit, cpus, cpu_shares, cpuset). None = não exigido.
ORCAMENTO = {
    "ayanami-pg": ("3g", "3g", 2, 1024, None),
    "ayanami-api": ("1g", "1g", 1, 1024, None),
    "worker-rapido": ("512m", "512m", 1, 1024, None),
    "worker-agendado": ("1g", "1g", 1.5, 512, None),
    "worker-lento": ("3584m", "5632m", 4, 256, "2-7"),
    "ayanami-voz": ("1536m", "2560m", 4, 1024, None),
    "ntfy": ("128m", None, 0.5, 1024, None),
}
INTERATIVOS = {"ayanami-api", "worker-rapido", "ayanami-pg", "ayanami-voz", "ntfy"}
LOTE = {"worker-lento", "sandbox-db", "llm-local", "runner", "migrar"}
# Serviços e imagens que já existiam antes do plataforma: os novos precisam de `@sha256:` (CA-P2).
SERVICOS_ANTIGOS = set(ORCAMENTO) | {"migrar"}
OPCIONAIS = {"llm-local": "noite", "bugsink": "erros", "runner": "runner"}


@pytest.fixture(scope="module")
def doc() -> dict:
    return cm.node2_inteiro()


@pytest.fixture(scope="module")
def todos(doc: dict) -> dict[str, dict]:
    return doc["services"]


def _ops(svc: dict) -> bool:
    return "ops" in (svc.get("profiles") or [])


# --- mesclador -------------------------------------------------------------------------------


def test_mesclador_campo_a_campo_e_listas_substituidas() -> None:
    base = {
        "services": {"a": {"image": "x", "command": ["a", "b"], "environment": {"A": "1", "B": "2"}}},
        "volumes": {"v": {"name": "v"}},
    }
    over = {"services": {"a": {"command": ["c"], "environment": {"B": "3"}, "cpus": 1}, "b": {"image": "y"}}}
    out = cm.mesclar(base, over)
    assert out["services"]["a"] == {
        "image": "x",
        "command": ["c"],
        "environment": {"A": "1", "B": "3"},
        "cpus": 1,
    }
    assert out["services"]["b"] == {"image": "y"}
    assert out["volumes"] == {"v": {"name": "v"}}
    assert base["services"]["a"]["command"] == ["a", "b"]  # não muta a base


def test_mesclador_perfis() -> None:
    doc = {"services": {"a": {}, "b": {"profiles": ["noite"]}, "c": {"profiles": ["ops", "x"]}}}
    assert set(cm.servicos_ativos(doc)) == {"a"}
    assert set(cm.servicos_ativos(doc, ["noite"])) == {"a", "b"}
    assert set(cm.servicos_ativos(doc, ["x"])) == {"a", "c"}
    assert cm.bytes_de("3584m") == 3584 * 1024**2 and cm.bytes_de("3g") == 3 * 1024**3


# --- override ----------------------------------------------------------------------------------


def test_override_so_reajusta_existentes() -> None:
    base = yaml.safe_load(cm.COMPOSE.read_text(encoding="utf-8"))
    over = yaml.safe_load(cm.NODE2_INTEIRO.read_text(encoding="utf-8"))
    assert set(over) == {"services"}  # sem rede, volume nem nome novos (DSP1)
    assert set(over["services"]) == SERVICOS_ANTIGOS
    assert set(over["services"]) <= set(base["services"])
    for nome, svc in over["services"].items():
        assert not {"image", "ports", "volumes", "profiles", "env_file"} & set(svc), nome
    assert set(over["services"]["ntfy"]) == {"cpu_shares"}  # ntfy: só cpu_shares
    assert set(over["services"]["migrar"]) == {"cpuset"}


def test_cabecalho_explica_compose_file() -> None:
    texto = cm.NODE2_INTEIRO.read_text(encoding="utf-8")
    assert "COMPOSE_FILE=compose.yml:compose.node2-inteiro.yml" in texto


def test_pg_shared_buffers(todos: dict) -> None:
    cmd = " ".join(todos["ayanami-pg"]["command"])
    assert "shared_buffers=768MB" in cmd and "max_connections=80" in cmd


def test_orcamento_da_spec(todos: dict) -> None:
    for nome, (mem, swap, cpus, shares, cpuset) in ORCAMENTO.items():
        svc = todos[nome]
        assert cm.bytes_de(svc["mem_limit"]) == cm.bytes_de(mem), nome
        if swap is not None:
            assert cm.bytes_de(svc["memswap_limit"]) == cm.bytes_de(swap), nome
        assert float(svc["cpus"]) == cpus, nome
        assert svc["cpu_shares"] == shares, nome
        assert svc.get("cpuset") == cpuset, nome
    assert todos["migrar"]["cpuset"] == "2-7"


# --- CA-P1 -------------------------------------------------------------------------------------


def test_ca_p1_soma_e_limites(doc: dict) -> None:
    perfis = {p for s in doc["services"].values() for p in (s.get("profiles") or [])} - {"runner", "ops"}
    contados = {n: s for n, s in cm.servicos_ativos(doc, perfis).items() if not _ops(s)}
    for nome, svc in contados.items():
        assert {"mem_limit", "cpus", "cpu_shares"} <= set(svc), nome
    soma = sum(cm.bytes_de(s["mem_limit"]) for s in contados.values())
    assert soma <= 18 * 1024**3, soma / 1024**3


def test_ca_p1_cpuset_lote_e_interativos(todos: dict) -> None:
    lote = {n: s for n, s in todos.items() if n in LOTE}
    assert {"worker-lento", "migrar"} <= set(lote)
    for nome, svc in lote.items():
        assert svc.get("cpuset") == "2-7", nome
    maior_lote = max(s["cpu_shares"] for s in lote.values() if "cpu_shares" in s)
    for nome in INTERATIVOS:
        svc = todos[nome]
        assert "cpuset" not in svc, nome
        assert svc["cpu_shares"] > maior_lote, nome
    # Fora do lote, ninguém fica preso a núcleos (os 0-1 são do interativo).
    for nome, svc in todos.items():
        if nome not in LOTE:
            assert "cpuset" not in svc, nome


# --- CA-P2 -------------------------------------------------------------------------------------


def test_ca_p2_sem_docker_sock_privileged_e_portas_loopback(todos: dict) -> None:
    for nome, svc in todos.items():
        assert not svc.get("privileged"), nome
        vols = [v if isinstance(v, str) else str(v.get("source", "")) for v in svc.get("volumes") or []]
        if nome != "worker-agendado":  # exceção antiga da central (CA-Y29)
            assert not any("docker.sock" in v for v in vols), nome
        for p in svc.get("ports") or []:
            assert str(p).startswith("127.0.0.1:"), (nome, p)
        assert svc.get("env_file") is None or nome in SERVICOS_ANTIGOS, nome  # novos: nunca .env inteiro


def test_ca_p2_imagem_nova_com_digest(todos: dict) -> None:
    for nome, svc in todos.items():
        if nome in SERVICOS_ANTIGOS or str(svc.get("image", "")).startswith("${AYANAMI_IMAGEM"):
            continue
        assert "@sha256:" in str(svc.get("image", "")), nome


def test_ca_p2_node2_enxuto_intocado() -> None:
    assert hashlib.sha256(NODE2_ENXUTO.read_bytes()).hexdigest() == NODE2_ENXUTO_SHA256


# --- CA-P3 -------------------------------------------------------------------------------------


def test_ca_p3_opcionais_so_no_proprio_perfil(doc: dict) -> None:
    padrao = cm.servicos_ativos(doc)
    for nome, perfil in OPCIONAIS.items():
        assert nome not in padrao, nome
        if nome in doc["services"]:
            assert doc["services"][nome]["profiles"] == [perfil], nome
            assert nome in cm.servicos_ativos(doc, [perfil]), nome
