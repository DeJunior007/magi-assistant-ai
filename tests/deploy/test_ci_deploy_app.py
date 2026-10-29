"""CA-M36: verbo `app` do comando forçado da CI (`deploy/ayanami/host/ci-deploy.sh`, M1.7).

Roda o bash real do script com `AYANAMI_DIR=tmp_path`, sem rede e sem git: só os caminhos que
publicam o APK ou que recusam antes de tocar em qualquer coisa.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SCRIPT = RAIZ / "deploy" / "ayanami" / "host" / "ci-deploy.sh"
CERT = "ab" * 32  # certificado falso fixo
MAX = 30 * 1024 * 1024


def _rodar(base: Path, pedido: str, stdin: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "AYANAMI_DIR": str(base),
        "SSH_ORIGINAL_COMMAND": pedido,
        "LC_ALL": "C.UTF-8",
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], input=stdin, env=env, capture_output=True, timeout=60, check=False
    )


def _versao(vc: int, apk: bytes, **troca: object) -> dict[str, object]:
    obj: dict[str, object] = {
        "versionCode": vc,
        "versionName": f"0.{vc}",
        "sha256": hashlib.sha256(apk).hexdigest(),
        "bytes": len(apk),
        "minimo": 1,
        "notas": "notas de teste",
        "publicado": "2026-10-28T12:00:00Z",
        "cert_sha256": CERT,
    }
    obj.update(troca)
    return obj


def _b64(obj: object) -> str:
    cru = json.dumps(obj).encode("utf-8")
    return base64.urlsafe_b64encode(cru).decode("ascii").rstrip("=")


def _apk(vc: int) -> bytes:
    return b"PK\x03\x04" + f"apk-falso-{vc}".encode() * 50


def _publicar(base: Path, vc: int, **troca: object) -> subprocess.CompletedProcess[bytes]:
    apk = _apk(vc)
    obj = _versao(vc, apk, **troca)
    return _rodar(base, f"app {vc} {hashlib.sha256(apk).hexdigest()} {_b64(obj)}", apk)


def _app_dir(base: Path) -> Path:
    return base / "dados" / "app"


def _conteudo(base: Path) -> dict[str, bytes]:
    d = _app_dir(base)
    return {p.name: p.read_bytes() for p in sorted(d.iterdir())} if d.exists() else {}


def test_publica_apk_e_versao_json(tmp_path: Path) -> None:
    r = _publicar(tmp_path, 1001)
    assert r.returncode == 0, r.stderr
    d = _app_dir(tmp_path)
    assert sorted(p.name for p in d.iterdir()) == ["condessa-1001.apk", "versao.json"]
    assert (d / "condessa-1001.apk").read_bytes() == _apk(1001)
    assert json.loads((d / "versao.json").read_text()) == _versao(1001, _apk(1001))
    assert (d / "condessa-1001.apk").stat().st_mode & 0o777 == 0o644
    assert b"publicado vc=1001" in r.stdout


def test_mantem_os_3_mais_novos(tmp_path: Path) -> None:
    for vc in (998, 999, 1000, 1001, 1002):
        r = _publicar(tmp_path, vc)
        assert r.returncode == 0, r.stderr
    nomes = sorted(p.name for p in _app_dir(tmp_path).iterdir())
    assert nomes == ["condessa-1000.apk", "condessa-1001.apk", "condessa-1002.apk", "versao.json"]
    assert json.loads((_app_dir(tmp_path) / "versao.json").read_text())["versionCode"] == 1002


def _recusado(r: subprocess.CompletedProcess[bytes]) -> None:
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert b"recusado:" in r.stderr


def test_sha_errado_recusa_sem_resto(tmp_path: Path) -> None:
    apk = _apk(1001)
    obj = _versao(1001, apk)
    r = _rodar(tmp_path, f"app 1001 {'0' * 64} {_b64(obj)}", apk)
    _recusado(r)
    assert _conteudo(tmp_path) == {}


def test_sha_do_json_diferente_recusa(tmp_path: Path) -> None:
    _recusado(_publicar(tmp_path, 1001, sha256="1" * 64))
    assert _conteudo(tmp_path) == {}


def test_vc_nao_maior_que_o_publicado(tmp_path: Path) -> None:
    assert _publicar(tmp_path, 1001).returncode == 0
    antes = _conteudo(tmp_path)
    _recusado(_publicar(tmp_path, 1001))
    _recusado(_publicar(tmp_path, 1000))
    assert _conteudo(tmp_path) == antes


@pytest.mark.parametrize(
    "chave", ["versionCode", "versionName", "sha256", "bytes", "minimo", "notas", "publicado", "cert_sha256"]
)
def test_json_com_chave_faltando(tmp_path: Path, chave: str) -> None:
    apk = _apk(1001)
    obj = _versao(1001, apk)
    del obj[chave]
    _recusado(_rodar(tmp_path, f"app 1001 {hashlib.sha256(apk).hexdigest()} {_b64(obj)}", apk))
    assert _conteudo(tmp_path) == {}


@pytest.mark.parametrize(
    "troca",
    [
        {"versionCode": 1002},
        {"versionCode": "1001"},
        {"bytes": 1},
        {"minimo": 1002},
        {"cert_sha256": "xyz"},
        {"versionName": ""},
    ],
)
def test_json_com_valor_errado(tmp_path: Path, troca: dict[str, object]) -> None:
    _recusado(_publicar(tmp_path, 1001, **troca))
    assert _conteudo(tmp_path) == {}


def test_json_ilegivel(tmp_path: Path) -> None:
    apk = _apk(1001)
    b64 = base64.urlsafe_b64encode(b"nao e json").decode().rstrip("=")
    _recusado(_rodar(tmp_path, f"app 1001 {hashlib.sha256(apk).hexdigest()} {b64}", apk))
    assert _conteudo(tmp_path) == {}


@pytest.mark.parametrize(
    "pedido",
    [
        "app 1001 {sha} {b64} extra",
        "app 1001 {sha}",
        "app 01001 {sha} {b64}",
        "app 1234567890 {sha} {b64}",
        "app 1001 {sha}0 {b64}",
        "app 1001 {sha} {b64}+",
        "app 1001 {sha} " + "A" * 4097,
    ],
)
def test_argumentos_invalidos(tmp_path: Path, pedido: str) -> None:
    apk = _apk(1001)
    sha = hashlib.sha256(apk).hexdigest()
    texto = pedido.format(sha=sha, b64=_b64(_versao(1001, apk)))
    _recusado(_rodar(tmp_path, texto, apk))
    assert _conteudo(tmp_path) == {}


def test_stdin_vazio(tmp_path: Path) -> None:
    sha = hashlib.sha256(b"").hexdigest()
    obj = _versao(1001, b"")
    _recusado(_rodar(tmp_path, f"app 1001 {sha} {_b64(obj)}", b""))
    assert _conteudo(tmp_path) == {}


def test_stdin_maior_que_30_mib(tmp_path: Path) -> None:
    apk = b"\0" * (MAX + 1)
    obj = _versao(1001, apk)
    r = _rodar(tmp_path, f"app 1001 {hashlib.sha256(apk).hexdigest()} {_b64(obj)}", apk)
    _recusado(r)
    assert b"30 MiB" in r.stderr
    assert _conteudo(tmp_path) == {}


@pytest.mark.parametrize(
    "pedido",
    [
        "",
        "deploy",
        "deploy abc",
        "deploy " + "A" * 40,
        "deploy " + "a" * 40 + " extra",
        "saude agora",
        "bash -i",
        "apk 1001",
    ],
)
def test_deploy_e_saude_seguem_recusando(tmp_path: Path, pedido: str) -> None:
    _recusado(_rodar(tmp_path, pedido))
    assert not (tmp_path / "dados").exists()
