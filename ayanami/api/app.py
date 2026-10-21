"""Aplicação FastAPI da Ayanami (dono: Y2.1 → Y5.1; spec §2, design §4.1).

- :func:`criar_app` monta a app com tudo injetado (config, banco, relógio, segredos, gerador do
  código de pareamento) e inclui os roteadores da lista fixa :data:`ROTEADORES` — cada módulo de
  ``ayanami.api`` expõe ``router``.
- ``/app`` (PWA estático): :func:`montar_pwa_se_houver` chama ``montar_pwa(app)`` de
  ``ayanami.pwa_estatico`` (P1.1) por import preguiçoso; módulo ausente ou diretório
  ``ayanami/pwa/`` inexistente → não monta e loga ``pwa_ausente``, sem erro.
- :func:`app_de_producao` lê ``/etc/ayanami/ayanami.toml``, os segredos e abre o pool; o
  ``uvicorn ayanami.api:app`` do Compose chega aqui pelo ``__getattr__`` de ``ayanami.api``.

Depois da Y2.1 só a Y5.1 (``/mcp``) mexe neste arquivo. Ponto de entrada para ela: montar o
``MCPServer`` com ``app.mount("/mcp", …)`` (o cliente usa ``/mcp/`` com barra; spike S3) e
registrar ``mcp.session_manager.run`` em ``app.state.ctx.ciclo`` — o lifespan da app entra em todos
os gerenciadores dessa lista (fábricas ``() -> AsyncContextManager``) na ordem e sai na ordem
inversa.
"""

from __future__ import annotations

import importlib
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ayanami.api.auth import Autenticador, ErroApi
from ayanami.api.limites import LimiteCorpo, Limites
from ayanami.api.logs import LogAcesso
from ayanami.config import AyanamiConfig, Segredos
from ayanami.db import Db
from ayanami.relogio import RelogioReal

log = logging.getLogger("ayanami.api")

ROTEADORES = (
    "saude", "dispositivos", "nos", "eventos", "turno", "confirma", "casa", "feed",
    "tarefas", "push", "noticias", "custos", "backup",
)
PWA_DIR = Path(__file__).resolve().parent.parent / "pwa"


def _codigo_6() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


@dataclass
class Contexto:
    """O que as rotas usam (``request.app.state.ctx``)."""

    cfg: AyanamiConfig
    db: Db
    relogio: Any
    segredos: Segredos | None
    auth: Autenticador
    limites: Limites
    gerar_codigo: Callable[[], str] = _codigo_6
    extras: dict[str, Any] = field(default_factory=dict)  # Y2.2+: hub etc.
    # fábricas de gerenciadores de contexto assíncronos que vivem junto com a app (Y5.1: MCP)
    ciclo: list[Callable[[], AbstractAsyncContextManager[Any]]] = field(default_factory=list)


@asynccontextmanager
async def _vida(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as pilha:
        for fabrica in list(app.state.ctx.ciclo):
            await pilha.enter_async_context(fabrica())
        yield


def criar_app(
    cfg: AyanamiConfig,
    db: Db,
    relogio: Any = None,
    *,
    segredos: Segredos | None = None,
    gerar_codigo: Callable[[], str] | None = None,
    pwa_dir: Path | None = None,
) -> FastAPI:
    relogio = relogio or RelogioReal()
    app = FastAPI(title="Ayanami", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=_vida)
    app.state.ctx = Contexto(
        cfg=cfg, db=db, relogio=relogio, segredos=segredos,
        auth=Autenticador(db, relogio), limites=Limites(relogio),
        gerar_codigo=gerar_codigo or _codigo_6,
    )
    _tratadores(app)
    for nome in ROTEADORES:
        app.include_router(importlib.import_module(f"ayanami.api.{nome}").router)
    app.state.pwa_montado = montar_pwa_se_houver(app, PWA_DIR if pwa_dir is None else pwa_dir)
    importlib.import_module("ayanami.mcp_server").montar(app)  # mount("/mcp") + lifespan (Y5.1)
    app.add_middleware(LimiteCorpo)
    app.add_middleware(LogAcesso, relogio=relogio)
    return app


def montar_pwa_se_houver(app: FastAPI, pwa_dir: Path) -> bool:
    try:
        modulo = importlib.import_module("ayanami.pwa_estatico")
    except ModuleNotFoundError as e:
        if e.name not in ("ayanami.pwa_estatico", "ayanami"):
            raise
        log.info("pwa_ausente (sem ayanami.pwa_estatico; dono: P1.1)")
        return False
    if not pwa_dir.is_dir():
        log.info("pwa_ausente (sem o diretório %s)", pwa_dir.name)
        return False
    modulo.montar_pwa(app)
    return True


def _erro(status: int, codigo: str, msg: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"erro": codigo, "msg": msg}, status_code=status, headers=headers)


_CODIGO_HTTP = {400: "pedido_invalido", 401: "nao_autorizado", 403: "proibido", 404: "nao_encontrado",
                405: "metodo_nao_permitido", 413: "corpo_grande", 501: "nao_implementado"}


def _tratadores(app: FastAPI) -> None:
    @app.exception_handler(ErroApi)
    async def _erro_api(_: Request, e: ErroApi) -> JSONResponse:
        return _erro(e.status, e.codigo, e.msg, e.headers)

    @app.exception_handler(RequestValidationError)
    async def _invalido(_: Request, e: RequestValidationError) -> JSONResponse:
        campos = sorted({".".join(str(p) for p in err.get("loc", ())[1:]) for err in e.errors()})
        return _erro(422, "invalido", "corpo inválido: " + ", ".join(c for c in campos if c)[:200])

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        codigo = _CODIGO_HTTP.get(e.status_code, "erro")
        msg = e.detail if isinstance(e.detail, str) else codigo
        return _erro(e.status_code, codigo, msg, getattr(e, "headers", None))


def app_de_producao() -> FastAPI:
    from ayanami import config as cfgmod
    from ayanami.db import abrir_pool, dsn_padrao

    cfg = cfgmod.ler(cfgmod.CAMINHO_PADRAO)
    segredos = cfgmod.ler_segredos(cfg)
    if segredos.faltando:
        log.warning("segredos faltando: %s", ", ".join(segredos.faltando))
    app = criar_app(cfg, abrir_pool(dsn_padrao()), RelogioReal(), segredos=segredos)
    app.state.ctx.extras["fila_producao"] = True  # eventos para o celular deferem push.enviar
    return app
