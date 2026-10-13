"""Servidor ``ayanami-voz`` (dono: Y3.5; spec §5.4, DS1).

``ayanami voz --port 8741`` (só rede Docker):

- ``POST /falar`` ``{"texto": 1..600, "voz": "pf_dora", "velocidade": 0.8..1.3}`` → ``200`` PCM
  s16le mono 24 kHz em streaming (``X-Taxa: 24000``); texto > 600 caracteres ou corpo > 16 KiB →
  ``413``; resto inválido → ``422``; modelo carregando há > 20 s → ``503`` (``Retry-After``).
- ``GET /saude`` → ``{"carregado": bool}``.

O modelo vem de ``$AYANAMI_MODELOS/kokoro/<[voz] modelo>`` + ``voices-v1.0.bin`` ao lado; carga
na 1ª fala e descarga após ``[voz] descarregar_apos_s`` ocioso (:class:`ayanami.voz.motor.Gerenciador`).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ayanami.config import CAMINHO_PADRAO, Voz
from ayanami.voz.motor import Carregando, Gerenciador, carregador_kokoro

log = logging.getLogger(__name__)

PORTA = 8741
MAX_TEXTO = 600
MAX_CORPO = 16 * 1024
VELOCIDADE = (0.8, 1.3)


def _erro(status: int, detalhe: str) -> JSONResponse:
    return JSONResponse({"detail": detalhe}, status_code=status)


def _validar(dados: Any, voz_padrao: str) -> tuple[str, str, float] | JSONResponse:
    if not isinstance(dados, dict):
        return _erro(422, "corpo deve ser um objeto JSON")
    sobra = set(dados) - {"texto", "voz", "velocidade"}
    if sobra:
        return _erro(422, f"campos desconhecidos: {sorted(sobra)}")
    texto = dados.get("texto")
    if not isinstance(texto, str) or not texto.strip():
        return _erro(422, "texto: 1..600 caracteres")
    if len(texto) > MAX_TEXTO:
        return _erro(413, f"texto passa de {MAX_TEXTO} caracteres")
    voz = dados.get("voz", voz_padrao)
    if not isinstance(voz, str) or not voz or not voz.replace("_", "").isalnum():
        return _erro(422, "voz inválida")
    vel = dados.get("velocidade", 1.0)
    if isinstance(vel, bool) or not isinstance(vel, int | float):
        return _erro(422, "velocidade: número 0.8..1.3")
    if not VELOCIDADE[0] <= float(vel) <= VELOCIDADE[1]:
        return _erro(422, "velocidade: 0.8..1.3")
    return texto, voz, float(vel)


def criar_app(ger: Gerenciador, *, voz_padrao: str = "pf_dora", vigiar: bool = True) -> FastAPI:
    @contextlib.asynccontextmanager
    async def ciclo(_app: FastAPI) -> AsyncIterator[None]:
        tarefa = asyncio.create_task(ger.vigiar()) if vigiar else None
        try:
            yield
        finally:
            if tarefa is not None:
                tarefa.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tarefa

    app = FastAPI(title="ayanami-voz", lifespan=ciclo, docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.ger = ger

    @app.get("/saude")
    async def saude() -> dict[str, bool]:
        return {"carregado": ger.carregado}

    @app.post("/falar")
    async def falar(request: Request) -> Response:
        tam = request.headers.get("content-length")
        if tam is not None and tam.isdigit() and int(tam) > MAX_CORPO:
            return _erro(413, "corpo grande demais")
        corpo = await request.body()
        if len(corpo) > MAX_CORPO:
            return _erro(413, "corpo grande demais")
        try:
            dados = json.loads(corpo)
        except (ValueError, UnicodeDecodeError):
            return _erro(422, "JSON inválido")
        val = _validar(dados, voz_padrao)
        if isinstance(val, JSONResponse):
            return val
        texto, voz, vel = val
        try:
            motor = await ger.obter()
        except Carregando as e:
            return JSONResponse({"detail": str(e)}, status_code=503, headers={"Retry-After": "5"})
        except Exception:
            log.exception("voz: modelo indisponível")
            return _erro(503, "modelo indisponível")

        pedacos = motor.falar(texto, voz, vel).__aiter__()
        try:
            primeiro = await pedacos.__anext__()
        except StopAsyncIteration:
            primeiro = b""
        except Exception:
            ger.liberar()
            log.exception("voz: falha na síntese")
            return _erro(500, "falha na síntese")

        async def corrente() -> AsyncIterator[bytes]:
            try:
                if primeiro:
                    yield primeiro
                async for p in pedacos:
                    yield p
            finally:
                ger.liberar()

        return StreamingResponse(corrente(), media_type="application/octet-stream",
                                 headers={"X-Taxa": str(motor.taxa)})

    return app


def dir_modelos(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get("AYANAMI_MODELOS", "/modelos")) / "kokoro"


def ler_voz(caminho: Path) -> Voz:
    """``[voz]`` do ``ayanami.toml``; sem arquivo, os padrões da §9.2."""
    if not caminho.exists():
        log.warning("voz: %s não existe; usando os padrões de [voz]", caminho)
        return Voz()
    from ayanami.config import ler

    return ler(caminho).voz


def montar(cfg: Voz, modelos: Path, **kw: Any) -> FastAPI:
    ger = Gerenciador(carregador_kokoro(modelos, cfg.modelo),
                      descarregar_apos_s=cfg.descarregar_apos_s, **kw)
    return criar_app(ger, voz_padrao=cfg.voz)


def cli(args: list[str]) -> int | None:
    p = argparse.ArgumentParser(prog="ayanami voz", description="servidor de TTS Kokoro")
    p.add_argument("--port", type=int, default=PORTA)
    p.add_argument("--host", default="0.0.0.0")  # só rede Docker (expose, sem ports)
    p.add_argument("--config", type=Path, default=CAMINHO_PADRAO)
    a = p.parse_args(args)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import uvicorn

    uvicorn.run(montar(ler_voz(a.config), dir_modelos()), host=a.host, port=a.port,
                log_level="info", access_log=False)
    return 0
