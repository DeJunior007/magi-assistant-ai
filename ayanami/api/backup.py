"""``PUT /v1/backup/pc`` (dono: Y4.2; spec §2.2, §2.3, §7.2, design §9).

Corpo binário ``.tar.zst`` em **fluxo** para ``<dados>/entrada/pc/<data>/`` (``ctx.extras["dados"]``,
padrão ``/dados``): grava num ``.parcial-*`` calculando o sha256; no fim confere com ``X-Sha256`` —
diferente → ``400`` e o parcial é apagado; corte no meio (cliente caiu ou ``413`` do
:class:`~ayanami.api.limites.LimiteCorpo`, > 2 GiB) → parcial apagado. Íntegro → vira
``magi-<data>.tar.zst`` + ``manifesto.json`` (de ``X-Manifesto``, base64 JSON), linha em
``backups`` (``origem='pc'``), ``auditoria`` e defere ``backup.restic`` (``ctx.extras["fila"]`` ou
o app de produção). Mesma data já recebida e com o arquivo do tamanho certo → ``409``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from ayanami import fila
from ayanami.api import auditoria
from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota
from ayanami.api.limites import GIB
from ayanami.deps import DADOS_PADRAO
from ayanami.workers.backup import MANIFESTO, arquivo_pc, data_valida, pasta_pc

log = logging.getLogger("ayanami.api.backup")

router = APIRouter()

MAX_BYTES = 2 * GIB
MAX_MANIFESTO = 64 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _cabecalhos(request: Request) -> tuple[str, str, dict[str, Any]]:
    sha = (request.headers.get("x-sha256") or "").strip().lower()
    if not _SHA.match(sha):
        raise ErroApi(400, "cabecalho_invalido", "X-Sha256: 64 dígitos hexadecimais")
    data = (request.headers.get("x-data") or "").strip()
    try:
        data_valida(data)
    except ValueError as e:
        raise ErroApi(400, "cabecalho_invalido", "X-Data: AAAA-MM-DD") from e
    bruto = (request.headers.get("x-manifesto") or "").strip()
    try:
        if len(bruto) > MAX_MANIFESTO:
            raise ValueError("grande")
        manifesto = json.loads(base64.b64decode(bruto, validate=True))
    except (ValueError, binascii.Error) as e:
        raise ErroApi(400, "cabecalho_invalido", "X-Manifesto: base64 de um JSON") from e
    if not isinstance(manifesto, dict):
        raise ErroApi(400, "cabecalho_invalido", "X-Manifesto: objeto JSON")
    return sha, data, manifesto


def _ja_recebido(conn: Any, dados: Path, data: str) -> bool:
    r = conn.execute(
        "SELECT bytes FROM backups WHERE origem = 'pc' AND data = %s", (data_valida(data),)
    ).fetchone()
    if r is None:
        return False
    arq = arquivo_pc(dados, data)
    return arq.exists() and arq.stat().st_size == int(r[0])


def _apagar(caminho: Path | None) -> None:
    if caminho is not None:
        caminho.unlink(missing_ok=True)
        try:
            caminho.parent.rmdir()  # só se ficou vazio
        except OSError:
            pass


async def _receber(request: Request, pasta: Path) -> tuple[Path, str, int]:
    """Corpo para ``pasta/.parcial-<uuid>`` em fluxo; devolve (parcial, sha256, bytes)."""
    pasta.mkdir(parents=True, exist_ok=True)
    parcial = pasta / f".parcial-{uuid4().hex}"
    h = hashlib.sha256()
    n = 0
    fh = await asyncio.to_thread(open, parcial, "xb")
    try:
        async for pedaco in request.stream():
            if not pedaco:
                continue
            n += len(pedaco)
            if n > MAX_BYTES:
                raise ErroApi(413, "corpo_grande", "corpo maior que 2 GiB")
            h.update(pedaco)
            await asyncio.to_thread(fh.write, pedaco)
    except BaseException:
        await asyncio.to_thread(fh.close)
        await asyncio.to_thread(_apagar, parcial)
        raise
    await asyncio.to_thread(fh.close)
    return parcial, h.hexdigest(), n


async def _deferir(request: Request, data: str) -> None:
    try:
        app = await fila.app_aberto(request.app.state.ctx.extras.get("fila"))
        await app.configure_task("backup.restic", **fila.defer_opcoes("backup.restic")).defer_async(data=data)
    except Exception as e:  # noqa: BLE001 — o backup.enviar diário reenvia o que ficou sem snapshot
        log.warning("backup.restic não deferido (%s)", type(e).__name__)


@router.put("/v1/backup/pc", status_code=201)
async def receber_pc(
    request: Request,
    disp: Annotated[Dispositivo, Depends(exigir_rota("PUT", "/v1/backup/pc"))],
) -> Any:
    ctx = request.app.state.ctx
    sha, data, manifesto = _cabecalhos(request)
    dados = Path(ctx.extras.get("dados") or DADOS_PADRAO)

    def ja() -> bool:
        with ctx.db.connection() as conn:
            return _ja_recebido(conn, dados, data)

    if await asyncio.to_thread(ja):
        await asyncio.to_thread(
            auditoria.registrar,
            ctx.db,
            tipo="backup",
            resumo=f"pc {data}: já recebido",
            ok=False,
            dispositivo=disp.id,
            alvo="pc",
        )
        raise ErroApi(409, "ja_recebido", "backup desta data já recebido e íntegro")
    try:
        parcial, calculado, n = await _receber(request, pasta_pc(dados, data))
    except ClientDisconnect:
        return JSONResponse({"erro": "corpo_cortado", "msg": "corpo incompleto"}, status_code=400)
    if calculado != sha:
        await asyncio.to_thread(_apagar, parcial)
        await asyncio.to_thread(
            auditoria.registrar,
            ctx.db,
            tipo="backup",
            resumo=f"pc {data}: sha256 não confere ({n} bytes)",
            ok=False,
            dispositivo=disp.id,
            alvo="pc",
        )
        raise ErroApi(400, "sha256_diferente", "sha256 não confere; arquivo apagado")

    def guardar() -> None:
        destino = arquivo_pc(dados, data)
        parcial.replace(destino)
        (destino.parent / MANIFESTO).write_text(json.dumps(manifesto, ensure_ascii=False), encoding="utf-8")
        with ctx.db.connection() as conn:
            conn.execute(
                "INSERT INTO backups (origem, data, bytes, sha256, manifesto, recebido)"
                " VALUES ('pc', %s, %s, %s, %s, %s) ON CONFLICT (origem, data) DO UPDATE SET"
                " bytes = EXCLUDED.bytes, sha256 = EXCLUDED.sha256, manifesto = EXCLUDED.manifesto,"
                " recebido = EXCLUDED.recebido, snapshot = NULL, enviado = NULL",
                (data_valida(data), n, sha, json.dumps(manifesto), ctx.relogio.agora()),
            )
            auditoria.registrar(
                conn, tipo="backup", resumo=f"pc {data}: {n} bytes", ok=True, dispositivo=disp.id, alvo="pc"
            )

    try:
        await asyncio.to_thread(guardar)
    except BaseException:
        await asyncio.to_thread(_apagar, parcial)
        raise
    await _deferir(request, data)
    return {"recebido": n}
