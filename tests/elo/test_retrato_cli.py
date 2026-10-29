"""CA-M38: ``magi-retrato`` (condessa-celular spec §12) com servidor falso e arte sintética."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tarfile
from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest

from magi.elo import retrato as rt
from magi.elo.backup import Resultado

TOKEN = "ayn_falso_0000"
URL = "https://ayanami.exemplo.ts.net"


def zstd_falso(cmd: Sequence[str], saida: Path | None = None) -> Resultado:
    """Faz de conta que comprime: copia o tar (o teste abre o 'zst' como tar)."""
    assert list(cmd[:2]) == ["zstd", "-10"]
    shutil.copyfile(cmd[-1], cmd[cmd.index("-o") + 1])
    return Resultado(0)


class Ayanami:
    def __init__(self, status: int = 202, corpo: dict | None = None) -> None:
        self.status, self.corpo = status, corpo
        self.pedidos: list[tuple[httpx.Request, bytes]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        dados = req.read()
        self.pedidos.append((req, dados))
        if self.corpo is not None:
            return httpx.Response(self.status, json=self.corpo)
        if self.status == 202:
            return httpx.Response(202, json={"versao": hashlib.sha256(dados).hexdigest(), "job": 7})
        return httpx.Response(self.status, json={"erro": "x"})

    def cliente(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def casa(tmp_path: Path) -> dict[str, Path]:
    share = tmp_path / "share" / "magi"
    cond = share / "condessa"
    for d in ("parts/cabelo", "eyes", "mouth"):
        (cond / d).mkdir(parents=True)
    (cond / "portrait.toml").write_text("[retrato]\nlado = 64\n")
    (cond / "parts" / "rosto.png").write_bytes(b"\x89PNG falso")
    (cond / "parts" / "cabelo" / "franja.png").write_bytes(b"\x89PNG falso 2")
    (cond / "eyes" / "aberto.png").write_bytes(b"olho")
    (cond / "mouth" / "a.png").write_bytes(b"boca")
    (cond / "parts" / "x.token").write_text("segredo")
    (cond / "parts" / ".oculto").write_text("x")
    (cond / "notas.txt").write_text("fora da lista")
    fora = tmp_path / "fora.png"
    fora.write_bytes(b"fora")
    os.symlink(fora, cond / "parts" / "link.png")
    os.symlink(tmp_path, cond / "mouth" / "pasta_link")
    mods = share / "models" / "wakeword"
    mods.mkdir(parents=True)
    (mods / "condessa.onnx").write_bytes(b"onnx falso")
    (mods / "melspectrogram.onnx").write_bytes(b"mel falso")
    (mods / "outro.onnx").write_bytes(b"nao vai")
    conf = tmp_path / "config" / "magi"
    conf.mkdir(parents=True)
    (conf / "config.toml").write_text(
        f'[ayanami]\nurl = "{URL}"\n\n[satellite]\nwake_model = "condessa"\nwake_threshold = 0.6\n'
        'wake_patience = 2\nwake_gate_dbfs = "off"\n\n[llm]\napi_key = "nao-sai"\n')
    (conf / "ayanami.token").write_text(TOKEN)
    os.chmod(conf / "ayanami.token", 0o600)
    return {"cond": cond, "mods": mods, "conf": conf / "config.toml", "tmp": tmp_path / "tmp"}


def _roda(casa: dict[str, Path], ay: Ayanami, *args: str) -> tuple[int, list[str]]:
    falas: list[str] = []
    with ay.cliente() as c:
        rc = rt.main(["--config", str(casa["conf"]), *args], cliente=c, executor=zstd_falso,
                     keyring_get=lambda s, n: None, tmp_base=casa["tmp"], saida=falas.append)
    return rc, falas


def _enviar(casa: dict[str, Path], ay: Ayanami) -> tuple[int, list[str]]:
    return _roda(casa, ay, "enviar", "--dir", str(casa["cond"]), "--modelos", str(casa["mods"]))


def test_tar_so_caminhos_permitidos_e_sha_confere(casa: dict[str, Path]) -> None:
    ay = Ayanami()
    rc, falas = _enviar(casa, ay)
    assert rc == 0, falas
    req, corpo = ay.pedidos[0]
    assert req.method == "PUT" and req.url == httpx.URL(URL + "/v1/retrato")
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert req.headers["X-Sha256"] == hashlib.sha256(corpo).hexdigest()
    with tarfile.open(fileobj=io.BytesIO(corpo)) as tar:
        membros = tar.getmembers()
        nomes = sorted(m.name for m in membros)
        assert all(m.isfile() for m in membros)
        sat = tar.extractfile("satellite.toml").read().decode()  # type: ignore[union-attr]
    assert nomes == sorted([
        "portrait.toml", "parts/rosto.png", "parts/cabelo/franja.png", "eyes/aberto.png",
        "mouth/a.png", "wakeword/condessa.onnx", "wakeword/melspectrogram.onnx", "satellite.toml",
    ])
    assert "wake_threshold = 0.6" in sat and "wake_patience = 2" in sat and 'wake_gate_dbfs = "off"' in sat
    assert "api_key" not in sat and "ayanami" not in sat and "wake_model" not in sat
    assert list(casa["tmp"].iterdir()) == []
    assert "enviado" in falas[-1]


def test_409_ja_enviado_sai_0(casa: dict[str, Path]) -> None:
    rc, falas = _enviar(casa, Ayanami(409))
    assert rc == 0 and "já enviado" in falas[-1]
    assert list(casa["tmp"].iterdir()) == []


def test_401_sai_1_com_frase(casa: dict[str, Path]) -> None:
    rc, falas = _enviar(casa, Ayanami(401))
    assert rc == 1 and "recusou o token" in falas[-1] and TOKEN not in falas[-1]
    assert list(casa["tmp"].iterdir()) == []


def test_sem_portrait_nao_envia_e_apaga_tmp(casa: dict[str, Path]) -> None:
    (casa["cond"] / "portrait.toml").unlink()
    ay = Ayanami()
    rc, falas = _enviar(casa, ay)
    assert rc == 1 and "portrait.toml" in falas[-1] and ay.pedidos == []
    assert list(casa["tmp"].iterdir()) == []


def test_rede_fora_sai_1_e_apaga_tmp(casa: dict[str, Path]) -> None:
    def cai(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("falso", request=req)

    falas: list[str] = []
    with httpx.Client(transport=httpx.MockTransport(cai)) as c:
        rc = rt.main(["--config", str(casa["conf"]), "enviar", "--dir", str(casa["cond"]),
                      "--modelos", str(casa["mods"])], cliente=c, executor=zstd_falso,
                     keyring_get=lambda s, n: None, tmp_base=casa["tmp"], saida=falas.append)
    assert rc == 1 and "fora do ar" in falas[-1]
    assert list(casa["tmp"].iterdir()) == []


def test_estado(casa: dict[str, Path]) -> None:
    v = {"versao": "ab" * 32, "lados": [512, 768], "pacotes": {}, "modelos": None, "gerando": False}
    ay = Ayanami(200, v)
    rc, falas = _roda(casa, ay, "estado")
    assert rc == 0 and "abababababab" in falas[-1] and "512, 768" in falas[-1]
    assert ay.pedidos[0][0].url == httpx.URL(URL + "/v1/retrato/versao")
    rc, falas = _roda(casa, Ayanami(404, {"erro": "sem_retrato"}), "estado")
    assert rc == 0 and "ainda não tem retrato" in falas[-1]


def test_sem_token_sai_1(casa: dict[str, Path]) -> None:
    (casa["conf"].parent / "ayanami.token").unlink()
    ay = Ayanami()
    rc, falas = _enviar(casa, ay)
    assert rc == 1 and "sem token" in falas[-1] and ay.pedidos == []


def test_help() -> None:
    with pytest.raises(SystemExit) as e:
        rt.main(["--help"])
    assert e.value.code == 0
