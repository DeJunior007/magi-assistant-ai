"""``/v1/app/*``: versão e APK do app Android da Condessa (dono: M1.1; condessa-celular spec §9.2).

O diretório ``[app] dir`` (padrão ``/dados/app``) tem ``versao.json`` (gravado por último pelo verbo
``app`` do ``ci-deploy.sh``) e ``condessa-<versionCode>.apk``. A Ayanami só lê e serve.

- ``GET /v1/app/versao``: o ``versao.json`` validado (:func:`ler_versao`): ``404 sem_versao`` sem
  arquivo; ``500 versao_invalida`` se faltam chaves, tipo errado, ``sha256`` não é 64 hex ou o APK
  não existe com ``bytes`` certo.
- ``GET /v1/app/apk``: ``200``/``206`` com ``ETag: "<sha256>"``, ``Range: bytes=a-``/``a-b``/``-n``;
  ``If-Range`` diferente do ETag → ``200`` inteiro; faixa inválida → ``416``. Não conta no 60/min;
  conta no limite de downloads (6/h, :meth:`ayanami.api.limites.Limites.por_download`).

Auditoria ``tipo="app"`` com os bytes servidos (sem IP).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ayanami.api import auditoria
from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota

log = logging.getLogger("ayanami.api.app_android")
router = APIRouter()

VERSAO_JSON = "versao.json"
MIME_APK = "application/vnd.android.package-archive"
BLOCO = 256 * 1024
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CAMPOS: dict[str, type] = {
    "versionCode": int, "versionName": str, "sha256": str, "bytes": int, "minimo": int,
    "notas": str, "publicado": str, "cert_sha256": str,
}


class VersaoInvalida(ValueError):
    """``versao.json`` existe mas não valida (o motivo vai só para o log)."""


def nome_apk(version_code: int) -> str:
    return f"condessa-{version_code}.apk"


def dir_app(ctx: Any) -> Path:
    return Path(ctx.cfg.app.dir)


def ler_versao(pasta: Path) -> dict | None:
    """``versao.json`` validado; ``None`` sem arquivo; :class:`VersaoInvalida` se não valida."""
    try:
        bruto = (pasta / VERSAO_JSON).read_bytes()
    except FileNotFoundError:
        return None
    try:
        dados = json.loads(bruto)
    except ValueError as e:
        raise VersaoInvalida("json ilegível") from e
    if not isinstance(dados, dict):
        raise VersaoInvalida("não é objeto")
    for chave, tipo in _CAMPOS.items():
        v = dados.get(chave)
        if not isinstance(v, tipo) or isinstance(v, bool):
            raise VersaoInvalida(f"{chave}: tipo errado ou ausente")
    if dados["versionCode"] < 1 or dados["minimo"] < 0 or dados["bytes"] < 1:
        raise VersaoInvalida("versionCode/minimo/bytes fora da faixa")
    if not _SHA_RE.match(dados["sha256"]):
        raise VersaoInvalida("sha256 não é 64 hex")
    apk = pasta / nome_apk(dados["versionCode"])
    try:
        tamanho = apk.stat().st_size
    except FileNotFoundError as e:
        raise VersaoInvalida("apk ausente") from e
    if tamanho != dados["bytes"]:
        raise VersaoInvalida("bytes diferente do apk")
    return dados


def version_code_publicado(pasta: Path) -> int | None:
    """Para o ``/saude``: o ``versionCode`` publicado, ou ``None`` (sem arquivo ou inválido)."""
    try:
        v = ler_versao(pasta)
    except (VersaoInvalida, OSError):
        return None
    return None if v is None else v["versionCode"]


def _versao_ou_erro(ctx: Any) -> dict:
    try:
        v = ler_versao(dir_app(ctx))
    except VersaoInvalida as e:
        log.warning("app: versao.json inválido (%s)", e)
        raise ErroApi(500, "versao_invalida", "versao.json publicado não valida") from None
    if v is None:
        raise ErroApi(404, "sem_versao", "nenhuma versão do app publicada")
    return v


def faixa(cabecalho: str | None, tamanho: int) -> tuple[int, int] | None:
    """``(inicio, fim)`` inclusivos de ``Range``; ``None`` = sem faixa; :class:`ValueError` = 416."""
    if cabecalho is None:
        return None
    m = _RANGE_RE.match(cabecalho.strip())
    if not m or (not m[1] and not m[2]):
        raise ValueError("faixa inválida")
    if not m[1]:  # sufixo: os últimos n bytes
        n = int(m[2])
        if n == 0 or tamanho == 0:
            raise ValueError("faixa vazia")
        return max(0, tamanho - n), tamanho - 1
    inicio = int(m[1])
    fim = int(m[2]) if m[2] else tamanho - 1
    if inicio >= tamanho or fim < inicio:
        raise ValueError("faixa fora do arquivo")
    return inicio, min(fim, tamanho - 1)


def _ler(caminho: Path, inicio: int, n: int) -> Iterator[bytes]:
    with caminho.open("rb") as f:
        f.seek(inicio)
        while n > 0:
            bloco = f.read(min(BLOCO, n))
            if not bloco:
                return
            n -= len(bloco)
            yield bloco


def servir_arquivo(request: Request, caminho: Path, etag: str, mime: str,
                   extras: dict[str, str] | None = None) -> Response:
    """``200``/``206``/``416`` de ``caminho`` com ``ETag``/``Range``/``If-Range`` (também para o
    retrato da M1.3). ``etag`` já entre aspas."""
    tamanho = caminho.stat().st_size
    cab = {"ETag": etag, "Accept-Ranges": "bytes", **(extras or {})}
    pedido = request.headers.get("range")
    if_range = request.headers.get("if-range")
    if if_range is not None and if_range != etag:
        pedido = None
    try:
        f = faixa(pedido, tamanho)
    except ValueError:
        return JSONResponse({"erro": "faixa_invalida", "msg": "Range fora do arquivo"}, status_code=416,
                            headers={"Content-Range": f"bytes */{tamanho}", **cab})
    if f is None:
        return StreamingResponse(_ler(caminho, 0, tamanho), media_type=mime,
                                 headers={"Content-Length": str(tamanho), **cab})
    inicio, fim = f
    n = fim - inicio + 1
    return StreamingResponse(_ler(caminho, inicio, n), status_code=206, media_type=mime,
                             headers={"Content-Length": str(n),
                                      "Content-Range": f"bytes {inicio}-{fim}/{tamanho}", **cab})


@router.get("/v1/app/versao")
def versao(
    request: Request,
    disp: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/app/versao"))],
) -> JSONResponse:
    v = _versao_ou_erro(request.app.state.ctx)
    return JSONResponse(v, headers={"Cache-Control": "no-cache"})


@router.get("/v1/app/apk")
def apk(
    request: Request,
    disp: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/app/apk"))],
) -> Response:
    ctx = request.app.state.ctx
    v = _versao_ou_erro(ctx)
    etag = f'"{v["sha256"]}"'
    ctx.limites.por_download(request, disp, etag)
    nome = nome_apk(v["versionCode"])
    resp = servir_arquivo(request, dir_app(ctx) / nome, etag, MIME_APK,
                          {"Content-Disposition": f'attachment; filename="{nome}"'})
    if resp.status_code in (200, 206):
        auditoria.registrar(ctx.db, tipo="app", resumo=f"apk baixado: {resp.headers['content-length']} bytes",
                            ok=True, dispositivo=disp.id, alvo=f"v{v['versionCode']}")
    return resp
