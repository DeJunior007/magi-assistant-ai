"""Turno do celular (dono: Y6.4; spec §2.2 linhas ``/v1/turno*``, §6.1, §6.2).

- ``POST /v1/turno``: JSON ``{"texto": "…"}`` ou ``multipart`` com o campo ``audio``
  (``audio/webm;codecs=opus``, ≤ 1 MiB, ≤ 15 s) → ``202 {"turno", "modo"}``. Outro tipo → ``415``;
  grande/longo → ``413``; mais de 20 por minuto do mesmo dispositivo → ``429``. O modo (``pc`` /
  ``nuvem``) sai da §6.1 neste instante e não muda no meio do turno.
- ``GET /v1/turno/{id}``: ``{"turno","modo","estado","fim"}``; turno de outro dispositivo → ``404``.
- ``GET /v1/turno/{id}/audio``: ``audio/ogg;codecs=opus`` em streaming enquanto gera; ``410``
  depois de 60 s do fim (arquivo apagado).

O trabalho fica em :mod:`ayanami.turnos`; ``turno.texto``/``turno.fim`` saem pelo SSE.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota
from ayanami.turnos import AUDIO_MAX_BYTES, AudioExpirado, AudioInvalido, AudioLongo, turnos_de

router = APIRouter()

TEXTO_MAX = 4000
MIME_AUDIO = "audio/webm"


async def _corpo(request: Request) -> tuple[str | None, bytes | None, str]:
    tipo = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if tipo == "application/json":
        try:
            dados = await request.json()
        except ValueError as e:
            raise ErroApi(422, "invalido", "JSON inválido") from e
        texto = dados.get("texto") if isinstance(dados, dict) else None
        if not isinstance(texto, str) or not texto.strip() or len(texto) > TEXTO_MAX:
            raise ErroApi(422, "invalido", f"texto de 1 a {TEXTO_MAX} caracteres")
        return texto.strip(), None, ""
    if tipo == "multipart/form-data":
        form = await request.form()
        arquivo: Any = form.get("audio")
        if arquivo is None or isinstance(arquivo, str):
            raise ErroApi(422, "invalido", "falta o campo audio")
        mime = (arquivo.content_type or "").lower()
        if mime.split(";")[0].strip() != MIME_AUDIO:
            raise ErroApi(415, "tipo_nao_suportado", "áudio só em audio/webm;codecs=opus")
        webm = await arquivo.read(AUDIO_MAX_BYTES + 1)
        if len(webm) > AUDIO_MAX_BYTES:
            raise ErroApi(413, "corpo_grande", "áudio acima de 1 MiB")
        if not webm:
            raise ErroApi(422, "invalido", "áudio vazio")
        return None, webm, mime
    raise ErroApi(415, "tipo_nao_suportado", "use JSON com texto ou multipart com audio")


@router.post("/v1/turno", status_code=202)
async def criar_turno(
    request: Request,
    disp: Annotated[Dispositivo, Depends(exigir_rota("POST", "/v1/turno"))],
) -> JSONResponse:
    svc = turnos_de(request.app.state.ctx)
    texto, webm, mime = await _corpo(request)
    svc.contar(disp)
    pcm = None
    if webm is not None:
        try:
            pcm = await svc.preparar_audio(webm)
        except AudioLongo as e:
            raise ErroApi(413, "audio_longo", "áudio acima de 15 s ou de 1 MiB") from e
        except AudioInvalido as e:
            raise ErroApi(415, "audio_invalido", "o áudio não decodificou") from e
    t = await svc.iniciar(disp, texto=texto, webm=webm, pcm=pcm, mime=mime or "audio/webm")
    return JSONResponse({"turno": t.id, "modo": t.modo}, status_code=202)


@router.get("/v1/turno/{id}")
async def ver_turno(
    request: Request,
    id: str,  # noqa: A002 - nome da rota na spec
    disp: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/turno/{id}"))],
) -> dict:
    t = turnos_de(request.app.state.ctx).obter(id, disp)
    if t is None:
        raise ErroApi(404, "nao_encontrado", "turno não encontrado")
    return t.para_json()


@router.get("/v1/turno/{id}/audio")
async def audio_turno(
    request: Request,
    id: str,  # noqa: A002
    disp: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/turno/{id}/audio"))],
) -> StreamingResponse:
    try:
        fluxo = turnos_de(request.app.state.ctx).audio(id, disp)
    except AudioExpirado as e:
        raise ErroApi(410, "expirado", "o áudio deste turno já foi apagado") from e
    if fluxo is None:
        raise ErroApi(404, "nao_encontrado", "turno não encontrado")
    return StreamingResponse(fluxo, media_type="audio/ogg;codecs=opus",
                             headers={"Cache-Control": "no-store"})
