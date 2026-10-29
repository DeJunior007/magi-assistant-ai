"""``magi-retrato``: envia a arte da Condessa e o wake word do PC à Ayanami (condessa-celular spec §12).

    magi-retrato enviar [--dir ~/.local/share/magi/condessa] [--modelos ~/.local/share/magi/models/wakeword]
    magi-retrato estado

``enviar`` monta em ``$TMP`` um ``tar`` só com os caminhos permitidos — ``portrait.toml``, ``parts/``,
``eyes/``, ``mouth/``, ``wakeword/{condessa,melspectrogram,embedding_model,silero_vad}.onnx`` (os que
existirem) e ``satellite.toml`` (só ``wake_threshold``, ``wake_patience`` e ``wake_gate_dbfs`` do
``config.toml``) —, comprime com ``zstd -10`` e faz ``PUT /v1/retrato`` com ``X-Sha256``. Links
simbólicos, ``*.token`` e afins nunca entram. ``409`` → "já enviado" (sai 0). O ``$TMP`` é apagado
sempre. ``estado`` → ``GET /v1/retrato/versao``.

Mesmo cliente e credenciais do ``magi-backup``: ``[ayanami] url`` e o token do PC por
``magi.elo.credenciais`` (keyring primeiro, ``ayanami.token`` depois).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import logging
import os
import shutil
import tarfile
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx

from magi.elo.backup import Executor, executor_real, sha256_arquivo
from magi.elo.credenciais import TOKEN_FILE, token_pc, url_ayanami

log = logging.getLogger("magi.elo.retrato")

ROTA = "/v1/retrato"
ROTA_VERSAO = "/v1/retrato/versao"
PASTAS = ("parts", "eyes", "mouth")
MODELOS = ("condessa", "melspectrogram", "embedding_model", "silero_vad")
CHAVES_SATELITE = ("wake_threshold", "wake_patience", "wake_gate_dbfs")
EXCLUIR = ("*.token", "*secret*", "*.key", ".*")
TIMEOUT = httpx.Timeout(60.0, write=600.0)


class RetratoErro(Exception):
    """Falha com frase pronta para o terminal (nunca com segredo)."""


def _xdg_dados() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share").expanduser()


def dir_padrao() -> Path:
    return _xdg_dados() / "magi" / "condessa"


def modelos_padrao() -> Path:
    return _xdg_dados() / "magi" / "models" / "wakeword"


# --- pacote ---------------------------------------------------------------------------------------


def _excluido(nome: str) -> bool:
    return any(fnmatch.fnmatch(nome.lower(), p) for p in EXCLUIR)


def _arquivos(pasta: Path) -> list[Path]:
    """Arquivos regulares de ``pasta`` (sem seguir links, sem links, sem excluídos), em ordem."""
    achados: list[Path] = []
    for raiz, dirs, nomes in os.walk(pasta, followlinks=False):
        r = Path(raiz)
        dirs[:] = sorted(d for d in dirs if not (r / d).is_symlink() and not _excluido(d))
        for n in sorted(nomes):
            p = r / n
            if p.is_symlink() or not p.is_file() or _excluido(n):
                continue
            achados.append(p)
    return achados


def _toml_valor(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return repr(v)
    return json.dumps(str(v), ensure_ascii=False)


def satellite_toml(raw: dict[str, Any]) -> str:
    """Só as chaves de wake do ``[satellite]`` do ``config.toml`` (o resto nunca sai do PC)."""
    sec = raw.get("satellite") or {}
    linhas = ["[satellite]"]
    linhas += [f"{k} = {_toml_valor(sec[k])}" for k in CHAVES_SATELITE if k in sec]
    return "\n".join(linhas) + "\n"


def _limpo(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    ti.mode = 0o644
    return ti


def montar_tar(condessa: Path, modelos: Path, raw: dict[str, Any], destino: Path) -> list[str]:
    """Grava o ``tar`` em ``destino``; devolve os nomes incluídos (relativos, sem ``..``)."""
    if not (condessa / "portrait.toml").is_file() or (condessa / "portrait.toml").is_symlink():
        raise RetratoErro(f"falta {condessa}/portrait.toml")
    if not (condessa / "parts").is_dir() or (condessa / "parts").is_symlink():
        raise RetratoErro(f"falta {condessa}/parts/")
    itens: list[tuple[Path, str]] = [(condessa / "portrait.toml", "portrait.toml")]
    for pasta in PASTAS:
        base = condessa / pasta
        if base.is_dir() and not base.is_symlink():
            itens += [(p, f"{pasta}/{p.relative_to(base).as_posix()}") for p in _arquivos(base)]
    for nome in MODELOS:
        p = modelos / f"{nome}.onnx"
        if p.is_file() and not p.is_symlink():
            itens.append((p, f"wakeword/{nome}.onnx"))
    nomes: list[str] = []
    with tarfile.open(destino, "w") as tar:
        for p, arc in itens:
            tar.add(p, arcname=arc, recursive=False, filter=_limpo)
            nomes.append(arc)
        dados = satellite_toml(raw).encode()
        ti = _limpo(tarfile.TarInfo("satellite.toml"))
        ti.size = len(dados)
        tar.addfile(ti, _Leitor(dados))
        nomes.append("satellite.toml")
    return nomes


class _Leitor:
    def __init__(self, dados: bytes) -> None:
        self._d, self._i = dados, 0

    def read(self, n: int = -1) -> bytes:
        fim = len(self._d) if n < 0 else self._i + n
        pedaco, self._i = self._d[self._i:fim], min(fim, len(self._d))
        return pedaco


def comprimir(executor: Executor, tar: Path) -> Path:
    zst = tar.with_suffix(".tar.zst")
    r = executor(["zstd", "-10", "-q", "-f", "-o", str(zst), str(tar)])
    if r.codigo != 0 or not zst.exists():
        raise RetratoErro(f"zstd falhou ({r.codigo})")
    tar.unlink()
    return zst


# --- comandos -------------------------------------------------------------------------------------


def _frase_http(r: httpx.Response) -> str:
    if r.status_code in (401, 403):
        return f"Ayanami recusou o token do PC (HTTP {r.status_code}); confira {TOKEN_FILE} ou o keyring"
    try:
        corpo = r.json()
        det = corpo.get("erro") or corpo.get("detail") if isinstance(corpo, dict) else None
    except ValueError:
        det = None
    return f"Ayanami respondeu HTTP {r.status_code}" + (f" ({det})" if isinstance(det, str) else "")


def enviar(
    url: str,
    token: str,
    condessa: Path,
    modelos: Path,
    raw: dict[str, Any],
    *,
    cliente: httpx.Client,
    executor: Executor = executor_real,
    tmp_base: Path | None = None,
    saida: Callable[[str], None] = print,
) -> int:
    """Monta, comprime e envia. 0 = aceito ou já enviado; 1 = falhou (com frase)."""
    if tmp_base is not None:
        tmp_base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="magi-retrato-", dir=tmp_base))
    try:
        nomes = montar_tar(condessa, modelos, raw, tmp / "retrato.tar")
        zst = comprimir(executor, tmp / "retrato.tar")
        sha = sha256_arquivo(zst)
        cab = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/zstd",
            "Content-Length": str(zst.stat().st_size),
            "X-Sha256": sha,
        }
        with zst.open("rb") as f:
            r = cliente.put(url.rstrip("/") + ROTA, content=f, headers=cab, timeout=TIMEOUT)
        if r.status_code == 409:
            saida(f"já enviado: a Ayanami já tem esta versão ({sha[:12]})")
            return 0
        if r.status_code in (200, 201, 202):
            corpo = r.json() if r.content else {}
            saida(f"retrato enviado ({len(nomes)} arquivos, {zst.stat().st_size} bytes); "
                  f"versão {str(corpo.get('versao') or sha)[:12]}, job {corpo.get('job', '?')}")
            return 0
        saida(_frase_http(r))
        return 1
    except RetratoErro as e:
        saida(f"magi-retrato: {e}")
        return 1
    except httpx.HTTPError as e:
        saida(f"magi-retrato: Ayanami fora do ar ({type(e).__name__})")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def estado(url: str, token: str, *, cliente: httpx.Client, saida: Callable[[str], None] = print) -> int:
    try:
        r = cliente.get(url.rstrip("/") + ROTA_VERSAO, headers={"Authorization": f"Bearer {token}"},
                        timeout=TIMEOUT)
    except httpx.HTTPError as e:
        saida(f"magi-retrato: Ayanami fora do ar ({type(e).__name__})")
        return 1
    if r.status_code == 404:
        saida("a Ayanami ainda não tem retrato (use magi-retrato enviar)")
        return 0
    if r.status_code != 200:
        saida(_frase_http(r))
        return 1
    v = r.json()
    lados = ", ".join(str(x) for x in v.get("lados") or [])
    saida(f"versão {str(v.get('versao'))[:12]}; lados {lados or '-'}; "
          f"modelos {'sim' if v.get('modelos') else 'não'}; gerando {'sim' if v.get('gerando') else 'não'}")
    return 0


def _ler_config(caminho: Path) -> dict[str, Any]:
    try:
        with caminho.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        log.warning("config.toml indisponível (%s)", type(e).__name__)
        return {}


def main(
    argv: Sequence[str] | None = None,
    *,
    cliente: httpx.Client | None = None,
    executor: Executor = executor_real,
    keyring_get: Callable[[str, str], str | None] | None = None,
    tmp_base: Path | None = None,
    saida: Callable[[str], None] = print,
) -> int:
    ap = argparse.ArgumentParser(
        prog="magi-retrato", description="Envia a arte da Condessa à Ayanami (condessa-celular spec §12).")
    ap.add_argument("--config", help="caminho do config.toml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="comando", required=True)
    pe = sub.add_parser("enviar", help="monta o pacote e faz PUT /v1/retrato")
    pe.add_argument("--dir", type=Path, default=None, help="arte (padrão ~/.local/share/magi/condessa)")
    pe.add_argument("--modelos", type=Path, default=None,
                    help="wake word (padrão ~/.local/share/magi/models/wakeword)")
    sub.add_parser("estado", help="GET /v1/retrato/versao")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if a.config:
        caminho = Path(a.config).expanduser()
    else:
        from magi.common.config import config_path

        caminho = config_path()
    raw = _ler_config(caminho)
    url = url_ayanami(raw)
    if not url:
        saida("magi-retrato: falta [ayanami] url no config.toml")
        return 1
    token = token_pc(caminho.parent, keyring_get=keyring_get)
    if not token:
        saida(f"magi-retrato: sem token do PC (keyring magi/ayanami_pc ou {TOKEN_FILE})")
        return 1
    proprio = cliente is None
    http = cliente or httpx.Client()
    try:
        if a.comando == "estado":
            return estado(url, token, cliente=http, saida=saida)
        condessa = (a.dir or dir_padrao()).expanduser()
        modelos = (a.modelos or modelos_padrao()).expanduser()
        return enviar(url, token, condessa, modelos, raw, cliente=http, executor=executor,
                      tmp_base=tmp_base, saida=saida)
    finally:
        if proprio:
            http.close()


if __name__ == "__main__":
    raise SystemExit(main())
