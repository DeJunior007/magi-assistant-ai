"""Rotas ``/v1/tarefas*`` e ``/v1/fila`` (dono: Y3.1 → Y3.6 só o ramo ``stt`` do ``POST``; spec §2.2,
§4.3).

O ``App`` da fila vem de ``ctx.extras["fila"]`` (testes: ``InMemoryConnector``); sem ele, o de
produção (:func:`ayanami.fila.app_aberto`, conector aberto no 1º uso).

Ramo ``stt`` (Y3.6, spec §5.5): ``POST /v1/tarefas`` em ``multipart/form-data`` com ``tipo=stt``
grava o áudio (≤ 200 MB) em ``<dados>/tmp/`` (``ctx.extras["dados"]``, padrão ``/dados``) em
fluxo e cria a tarefa com ``params={"arquivo": "<nome>"}``; o JSON segue com 256 KiB e recusa
``stt``.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from python_multipart.multipart import MultipartParser, parse_options_header

from ayanami import tarefas as tf
from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota, iso_z
from ayanami.api.limites import CORPO_PADRAO
from ayanami.deps import DADOS_PADRAO

router = APIRouter()


class TarefaInCorpo(BaseModel):
    tipo: Literal["pesquisa", "resumo", "lembrete", "monitor", "stt"]
    titulo: str = Field(min_length=1, max_length=120)
    params: dict[str, Any] = Field(default_factory=dict)
    chave: str | None = Field(default=None, min_length=1, max_length=128)
    pessoal: bool = False
    avisar: bool = True


def _app_fila(request: Request) -> Any:
    return request.app.state.ctx.extras.get("fila")


def _uuid(texto: str) -> UUID:
    try:
        return UUID(texto)
    except ValueError as e:
        raise ErroApi(404, "nao_encontrado", "tarefa não existe") from e


@router.get("/v1/tarefas")
def listar(
    request: Request,
    _: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/tarefas"))],
    estado: str | None = None,
    n: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    if estado is not None and estado not in tf.ESTADO_DO_JOB.values():
        raise ErroApi(422, "invalido", "estado desconhecido")
    lista = tf.listar_tarefas(request.app.state.ctx.db, estado, n)
    return JSONResponse({"tarefas": [t.para_json() for t in lista]})


@router.post("/v1/tarefas")
async def criar(request: Request,
                disp: Annotated[Dispositivo, Depends(exigir_rota("POST", "/v1/tarefas"))]) -> JSONResponse:
    ctx = request.app.state.ctx
    if request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        return await _criar_stt(request, disp)  # Y3.6
    bruto = await _ler_json(request)
    try:
        corpo = TarefaInCorpo.model_validate_json(bruto)
    except ValidationError as e:
        raise RequestValidationError(e.errors()) from e
    if corpo.tipo == "stt":
        raise ErroApi(422, "invalido", "stt só por multipart (campo arquivo)")
    t = tf.TarefaIn(tipo=corpo.tipo, titulo=corpo.titulo, params=corpo.params, chave=corpo.chave,
                    pessoal=corpo.pessoal, avisar=corpo.avisar)
    try:
        tarefa, criada = await tf.criar_tarefa(ctx.db, t, disp.id, app=_app_fila(request),
                                               relogio=ctx.relogio)
    except tf.TarefaInvalida as e:
        raise ErroApi(422, "invalido", str(e)) from e
    return JSONResponse(tarefa.para_json(), status_code=201 if criada else 200)


async def _ler_json(request: Request) -> bytes:
    """Corpo JSON até ``CORPO_PADRAO`` (a rota aceita até 200 MB só no multipart do ``stt``)."""
    if int(request.headers.get("content-length") or 0) > CORPO_PADRAO:
        raise ErroApi(413, "corpo_grande", "corpo maior que o limite da rota")
    partes: list[bytes] = []
    n = 0
    async for pedaco in request.stream():
        n += len(pedaco)
        if n > CORPO_PADRAO:
            raise ErroApi(413, "corpo_grande", "corpo maior que o limite da rota")
        partes.append(pedaco)
    return b"".join(partes)


# --------------------------------------------------------------------------- ramo stt (Y3.6)

STT_MAX_BYTES = 200 * 1000 * 1000  # spec §5.5: ≤ 200 MB de áudio
_FOLGA_MULTIPART = 64 * 1024  # cabeçalhos e campos de texto do formulário
_MAX_CAMPO = 4096
_EXT_OK = re.compile(r"^[a-z0-9]{1,8}$")


class _UploadGrande(Exception):
    pass


def _pasta_tmp(request: Request) -> Path:
    return Path(request.app.state.ctx.extras.get("dados") or DADOS_PADRAO) / "tmp"


def _extensao(nome: str) -> str:
    ext = Path(nome).suffix.lower().lstrip(".")
    return ext if _EXT_OK.match(ext) else "bin"


def _booleano(campos: dict[str, str], nome: str, padrao: bool) -> bool:
    v = campos.get(nome)
    if v is None:
        return padrao
    if v.lower() in ("1", "true", "sim", "on"):
        return True
    if v.lower() in ("0", "false", "nao", "não", "off"):
        return False
    raise ErroApi(422, "invalido", f"{nome}: booleano")


async def _receber_multipart(request: Request, pasta: Path) -> tuple[dict[str, str], Path | None]:
    """Lê o multipart em fluxo: campos de texto em memória, ``arquivo`` direto para ``pasta``
    (``<uuid>.<ext>``). Passou de :data:`STT_MAX_BYTES` → :class:`_UploadGrande` (parcial apagado)."""
    ctype, opcoes = parse_options_header(request.headers.get("content-type", ""))
    fronteira = opcoes.get(b"boundary")
    if not fronteira:
        raise ErroApi(422, "invalido", "multipart sem boundary")
    campos: dict[str, str] = {}
    pendente: list[tuple[str, Any]] = []
    atual: dict[str, Any] = {}
    cab: dict[str, bytes] = {}
    nome_cab = bytearray()
    valor_cab = bytearray()

    def inicio() -> None:
        atual.clear()
        cab.clear()

    def campo_cab(dados: bytes, a: int, b: int) -> None:
        nome_cab.extend(dados[a:b])

    def valor(dados: bytes, a: int, b: int) -> None:
        valor_cab.extend(dados[a:b])

    def fim_cab() -> None:
        cab[bytes(nome_cab).lower().decode("latin-1")] = bytes(valor_cab)
        nome_cab.clear()
        valor_cab.clear()

    def cab_pronto() -> None:
        _, disp_op = parse_options_header(cab.get("content-disposition", b""))
        atual["nome"] = disp_op.get(b"name", b"").decode("utf-8", "replace")
        fn = disp_op.get(b"filename")
        atual["arquivo"] = fn.decode("utf-8", "replace") if fn is not None else None
        atual["buf"] = bytearray()
        pendente.append(("inicio", dict(atual)))

    def dados_parte(dados: bytes, a: int, b: int) -> None:
        pendente.append(("dados", bytes(dados[a:b])))

    def fim_parte() -> None:
        pendente.append(("fim", None))

    parser = MultipartParser(fronteira, {
        "on_part_begin": inicio, "on_header_field": campo_cab, "on_header_value": valor,
        "on_header_end": fim_cab, "on_headers_finished": cab_pronto, "on_part_data": dados_parte,
        "on_part_end": fim_parte,
    })
    destino: Path | None = None
    fh: Any = None
    parte: dict[str, Any] | None = None
    escritos = 0
    try:
        async for pedaco in request.stream():
            parser.write(pedaco)
            for tipo, x in pendente:
                if tipo == "inicio":
                    parte = x
                    if parte["nome"] == "arquivo" and parte["arquivo"] is not None:
                        if destino is not None:
                            raise ErroApi(422, "invalido", "um arquivo só")
                        pasta.mkdir(parents=True, exist_ok=True)
                        destino = pasta / f"{uuid4().hex}.{_extensao(parte['arquivo'])}"
                        fh = await asyncio.to_thread(open, destino, "xb")
                elif tipo == "dados" and parte is not None:
                    if fh is not None and parte["nome"] == "arquivo" and parte["arquivo"] is not None:
                        escritos += len(x)
                        if escritos > STT_MAX_BYTES:
                            raise _UploadGrande
                        await asyncio.to_thread(fh.write, x)
                    else:
                        parte["buf"].extend(x)
                        if len(parte["buf"]) > _MAX_CAMPO:
                            raise ErroApi(422, "invalido", f"{parte['nome']}: campo grande demais")
                elif tipo == "fim" and parte is not None:
                    if parte["arquivo"] is None:
                        campos[parte["nome"]] = bytes(parte["buf"]).decode("utf-8", "replace")
                    elif fh is not None:
                        await asyncio.to_thread(fh.close)
                        fh = None
                    parte = None
            pendente.clear()
        parser.finalize()
    except BaseException:
        if fh is not None:
            fh.close()
        if destino is not None:
            destino.unlink(missing_ok=True)
        raise
    if fh is not None:  # corpo cortado antes do fim da parte
        fh.close()
        destino.unlink(missing_ok=True)  # type: ignore[union-attr]
        raise ErroApi(422, "invalido", "multipart incompleto")
    return campos, destino


async def _criar_stt(request: Request, disp: Dispositivo) -> JSONResponse:
    """``POST /v1/tarefas`` multipart: ``tipo=stt``, ``titulo``, ``arquivo`` (≤ 200 MB, para
    ``/dados/tmp/``), opcionais ``chave``/``pessoal``/``avisar``. O arquivo some se a tarefa não
    for criada (erro, ou a chave já tinha tarefa viva)."""
    ctx = request.app.state.ctx
    if int(request.headers.get("content-length") or 0) > STT_MAX_BYTES + _FOLGA_MULTIPART:
        raise ErroApi(413, "corpo_grande", "áudio maior que 200 MB")
    try:
        campos, audio = await _receber_multipart(request, _pasta_tmp(request))
    except _UploadGrande as e:
        raise ErroApi(413, "corpo_grande", "áudio maior que 200 MB") from e
    usado = False
    try:
        if campos.get("tipo") != "stt":
            raise ErroApi(422, "invalido", "multipart só para tipo=stt")
        if audio is None:
            raise ErroApi(422, "invalido", "arquivo: obrigatório")
        if audio.stat().st_size == 0:
            raise ErroApi(422, "invalido", "arquivo: vazio")
        t = tf.TarefaIn(tipo="stt", titulo=campos.get("titulo", ""), params={"arquivo": audio.name},
                        chave=campos.get("chave") or None,
                        pessoal=_booleano(campos, "pessoal", False),
                        avisar=_booleano(campos, "avisar", True))
        try:
            tarefa, criada = await tf.criar_tarefa(ctx.db, t, disp.id, app=_app_fila(request),
                                                   relogio=ctx.relogio)
        except tf.TarefaInvalida as e:
            raise ErroApi(422, "invalido", str(e)) from e
        usado = criada
        return JSONResponse(tarefa.para_json(), status_code=201 if criada else 200)
    finally:
        if audio is not None and not usado:
            audio.unlink(missing_ok=True)


@router.get("/v1/tarefas/{id}")
def ver(request: Request, id: str,
        _: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/tarefas/{id}"))]) -> JSONResponse:
    t = tf.obter_tarefa(request.app.state.ctx.db, _uuid(id))
    if t is None:
        raise ErroApi(404, "nao_encontrado", "tarefa não existe")
    return JSONResponse(t.para_json())


@router.delete("/v1/tarefas/{id}")
async def cancelar(
    request: Request, id: str,
    _: Annotated[Dispositivo, Depends(exigir_rota("DELETE", "/v1/tarefas/{id}"))],
) -> JSONResponse:
    ctx = request.app.state.ctx
    try:
        estado = await tf.cancelar_tarefa(ctx.db, _uuid(id), app=_app_fila(request),
                                          relogio=ctx.relogio)
    except tf.TarefaNaoEncontrada as e:
        raise ErroApi(404, "nao_encontrado", "tarefa não existe") from e
    except tf.JaTerminou as e:
        raise ErroApi(409, "ja_terminou", f"a tarefa já terminou ({e.estado})") from e
    return JSONResponse({"estado": estado}, status_code=202)


def _resumo_fila(db: Any) -> dict[str, Any]:
    saida: dict[str, Any] = {"contagem": {}, "lentas": [], "falhas": []}
    with db.connection() as conn:
        if conn.execute("SELECT to_regclass('procrastinate_jobs')").fetchone()[0] is None:
            return saida
        for fila, status, n in conn.execute(
            "SELECT queue_name, status::text, count(*) FROM procrastinate_jobs GROUP BY 1, 2"
        ).fetchall():
            saida["contagem"].setdefault(fila, {})[status] = n
        for jid, nome, fila, desde in conn.execute(
            "SELECT j.id, j.task_name, j.queue_name, max(e.at) FROM procrastinate_jobs j"
            " JOIN procrastinate_events e ON e.job_id = j.id AND e.type::text = 'started'"
            " WHERE j.status = 'doing' GROUP BY 1, 2, 3 ORDER BY 4 ASC LIMIT 10"
        ).fetchall():
            saida["lentas"].append({"job": jid, "tarefa": nome, "fila": fila, "desde": iso_z(desde)})
        for jid, nome, fila, quando, tentativas in conn.execute(
            "SELECT j.id, j.task_name, j.queue_name, max(e.at), j.attempts FROM procrastinate_jobs j"
            " JOIN procrastinate_events e ON e.job_id = j.id AND e.type::text = 'failed'"
            " WHERE j.status = 'failed' GROUP BY 1, 2, 3, 5 ORDER BY 4 DESC LIMIT 10"
        ).fetchall():
            saida["falhas"].append({"job": jid, "tarefa": nome, "fila": fila,
                                    "quando": iso_z(quando), "tentativas": tentativas})
        if not conn.autocommit:
            conn.rollback()
    return saida


@router.get("/v1/fila")
async def ver_fila(request: Request,
                   _: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/fila"))]) -> JSONResponse:
    return JSONResponse(await asyncio.to_thread(_resumo_fila, request.app.state.ctx.db))
