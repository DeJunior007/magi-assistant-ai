"""Log de acesso da API (dono: Y2.1; spec §2.3, R10.1).

Uma linha por requisição no logger ``ayanami.api.acesso``: método, rota (o molde da rota, sem
query string), status, dispositivo (id), ms e tamanhos de entrada/saída. **Nunca** corpo,
cabeçalhos, token nem áudio.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("ayanami.api.acesso")


class LogAcesso:
    def __init__(self, app: Any, relogio: Any) -> None:
        self.app = app
        self.relogio = relogio

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inicio = self.relogio.monotonico()
        entrada = 0
        saida = 0
        status = 500

        async def receive_contado() -> dict:
            nonlocal entrada
            msg = await receive()
            if msg["type"] == "http.request":
                entrada += len(msg.get("body", b""))
            return msg

        async def send_contado(msg: dict) -> None:
            nonlocal saida, status
            if msg["type"] == "http.response.start":
                status = msg["status"]
            elif msg["type"] == "http.response.body":
                saida += len(msg.get("body", b""))
            await send(msg)

        try:
            await self.app(scope, receive_contado, send_contado)
        finally:
            log.info(json.dumps(linha(scope, status, entrada, saida, self.relogio.monotonico() - inicio)))


def linha(scope: dict, status: int, entrada: int, saida: int, segundos: float) -> dict:
    rota = scope.get("route")
    estado = scope.get("state") or {}
    disp = estado.get("dispositivo")
    return {
        "metodo": scope.get("method"),
        "rota": getattr(rota, "path", None) or scope.get("path"),
        "status": status,
        "dispositivo": getattr(disp, "id", None),
        "ms": round(segundos * 1000, 1),
        "entrada": entrada,
        "saida": saida,
    }
