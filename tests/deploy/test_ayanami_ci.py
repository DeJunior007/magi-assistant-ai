"""Teste estático do workflow da Ayanami (Y1.4; R10.4, design §11). Só lê o YAML."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
WORKFLOW = RAIZ / ".github" / "workflows" / "ayanami.yml"

NODE1 = re.compile(r"multivideos|wedding|gold-?crm", re.I)
SEGREDO_LITERAL = re.compile(
    r"ayn_[A-Za-z0-9]|sk-[A-Za-z0-9]|ghp_|github_pat_|BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{8}"
)
SECRETS_PERMITIDOS = {"GITHUB_TOKEN", "AYANAMI_HOST", "AYANAMI_USER", "AYANAMI_SSH_KEY"}


@pytest.fixture(scope="module")
def texto() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wf(texto: str) -> dict:
    return yaml.safe_load(texto)


def _gatilhos(wf: dict) -> dict:
    # PyYAML (YAML 1.1) lê a chave `on` como True.
    return wf.get("on", wf.get(True))


def _passos(wf: dict) -> list[dict]:
    return [p for job in wf["jobs"].values() for p in job.get("steps", [])]


def _runs(wf: dict, job: str) -> str:
    return "\n".join(p.get("run", "") for p in wf["jobs"][job]["steps"])


def test_gatilho_so_push_no_main_com_caminhos(wf: dict) -> None:
    on = _gatilhos(wf)
    assert set(on) == {"push"}
    push = on["push"]
    assert push["branches"] == ["main"]
    caminhos = set(push["paths"])
    assert caminhos - {".github/workflows/ayanami.yml"} == {
        "ayanami/**",
        "magi/elo/**",
        "magi/news/**",
        "deploy/ayanami/**",
        "pyproject.toml",
        "uv.lock",
    }


def test_permissoes_minimas(wf: dict) -> None:
    assert wf["permissions"] == {"contents": "read"}
    for nome, job in wf["jobs"].items():
        perms = job.get("permissions", {})
        if nome == "imagem":
            assert perms == {"contents": "read", "packages": "write"}
        else:
            assert "packages" not in perms


def test_testes_com_pg_descartavel(wf: dict) -> None:
    job = wf["jobs"]["testes"]
    (svc,) = job["services"].values()
    assert svc["image"] == "pgvector/pgvector:pg16"
    assert svc["ports"] == ["54340:5432"]
    assert "pg_isready" in svc["options"]
    dsn = job["env"]["AYANAMI_TEST_DSN"]
    assert dsn.startswith("postgresql://") and "127.0.0.1:54340/" in dsn
    assert ":54329" not in dsn and not dsn.endswith("/magi")
    usuario, senha = svc["env"]["POSTGRES_USER"], svc["env"]["POSTGRES_PASSWORD"]
    assert f"{usuario}:{senha}@" in dsn and dsn.endswith("/" + svc["env"]["POSTGRES_DB"])


def test_testes_uv_ruff_pytest(wf: dict) -> None:
    runs = _runs(wf, "testes")
    assert re.search(r"^uv sync\b", runs, re.M)
    assert "uv run ruff check" in runs
    pytest_linha = next(linha for linha in runs.splitlines() if "pytest" in linha)
    for area in ("tests/elo", "tests/ayanami", "tests/deploy"):
        assert area in pytest_linha
    assert "-q" in pytest_linha


def test_imagem_no_ghcr_depois_dos_testes(wf: dict) -> None:
    job = wf["jobs"]["imagem"]
    assert job["needs"] == "testes"
    usos = {p.get("uses", "").split("@")[0]: p for p in job["steps"]}
    login = usos["docker/login-action"]["with"]
    assert login["registry"] == "ghcr.io"
    assert login["password"] == "${{ secrets.GITHUB_TOKEN }}"
    build = usos["docker/build-push-action"]["with"]
    assert build["file"] == "deploy/ayanami/Dockerfile"
    assert build["push"] is True
    assert "AYANAMI_ML=${{ matrix.ml }}" in build["build-args"]
    assert "${{ github.sha }}${{ matrix.sufixo }}" in build["tags"]
    sufixos = {m["sufixo"] for m in job["strategy"]["matrix"]["include"]}
    assert sufixos == {"", "-ml"}  # mesmas tags que o compose.yml espera
    assert "ghcr.io/" in _runs(wf, "imagem") and ",," in _runs(wf, "imagem")


def test_actions_com_versao_fixa(wf: dict) -> None:
    for passo in _passos(wf):
        if "uses" in passo:
            assert re.search(r"@v\d", passo["uses"]), passo["uses"]


def test_nenhum_segredo_literal(texto: str) -> None:
    assert not SEGREDO_LITERAL.search(texto)
    assert not NODE1.search(texto)
    # Só referências `${{ secrets.X }}` a nomes conhecidos.
    refs = set(re.findall(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)", texto))
    assert refs <= SECRETS_PERMITIDOS, refs
    for linha in texto.splitlines():
        if "secrets." in linha:
            assert re.search(r"\$\{\{\s*secrets\.[A-Z_]+\s*\}\}", linha), linha


def test_if_nunca_le_secrets(wf: dict) -> None:
    """`if:` não lê `secrets`; um gate de deploy, se houver, passa por `env`/output."""
    ifs = [j.get("if", "") for j in wf["jobs"].values()] + [p.get("if", "") for p in _passos(wf)]
    assert not any("secrets" in str(cond) for cond in ifs)


def test_deploy_com_portao_e_comando_forcado(wf: dict) -> None:
    portao = wf["jobs"]["portao"]
    (passo,) = portao["steps"]
    assert passo["env"] == {"AYANAMI_HOST": "${{ secrets.AYANAMI_HOST }}"}
    assert "tem_host" in passo["run"] and "GITHUB_OUTPUT" in passo["run"]
    assert portao["outputs"]["tem_host"] == "${{ steps.ver.outputs.tem_host }}"

    deploy = wf["jobs"]["deploy"]
    assert deploy["needs"] == ["imagem", "portao"]
    assert "refs/heads/main" in deploy["if"]
    assert "needs.portao.outputs.tem_host == 'true'" in deploy["if"]
    assert deploy["concurrency"]["cancel-in-progress"] is False
    for passo in deploy["steps"]:
        assert passo["uses"] == "appleboy/ssh-action@v1.2.0"
        assert passo["with"]["host"] == "${{ secrets.AYANAMI_HOST }}"
        assert passo["with"]["username"] == "${{ secrets.AYANAMI_USER }}"
        assert passo["with"]["key"] == "${{ secrets.AYANAMI_SSH_KEY }}"
    scripts = [p["with"]["script"] for p in deploy["steps"]]
    assert scripts == ["deploy ${{ github.sha }}", "saude"]


def test_comando_forcado_da_chave_de_ci() -> None:
    """A chave da CI só roda deploy.sh com o sha validado e o smoke da /saude (banco == ok)."""
    texto = (RAIZ / "deploy" / "ayanami" / "host" / "ci-deploy.sh").read_text(encoding="utf-8")
    assert "SSH_ORIGINAL_COMMAND" in texto
    assert "^[0-9a-f]{40}$" in texto
    assert 'deploy.sh" --tag "$arg" --sem-git --sem-build' in texto
    assert "http://127.0.0.1:8740/saude" in texto and '"banco") == "ok"' in texto
    assert "restrict," in texto
