"""Limites gerais da API (dono: Y2.1; spec §2.3).

- :class:`Janela`: N eventos por janela deslizante de 60 s por chave, relógio injetado
  (``monotonico``); estourou → ``ErroApi(429)`` com ``Retry-After`` em segundos inteiros.
- :class:`Limites`: 60 req/min por dispositivo (exceto ``/ws``, ``/v1/eventos``,
  ``/v1/longpoll``) e 5 tentativas/min por IP no ``/v1/pareamento/trocar``.
- :class:`LimiteCorpo`: middleware ASGI que recusa corpo grande com ``413`` — 256 KiB por padrão,
  1 MiB em ``/v1/turno``, 2 GiB em ``/v1/backup/pc`` — pelo ``Content-Length`` e, sem ele, contando
  os bytes que chegam.
"""

from __future__ import annotations

import json
import math
import threading
from collections import deque
from typing import Any

from ayanami.api.auth import Dispositivo, ErroApi

POR_MINUTO = 60
JANELA_S = 60.0
ISENTAS = ("/ws", "/v1/eventos", "/v1/longpoll")
TROCAR_POR_MINUTO = 5

KIB = 1024
MIB = 1024 * KIB
GIB = 1024 * MIB
CORPO_PADRAO = 256 * KIB
CORPO_POR_ROTA = {"/v1/turno": 1 * MIB, "/v1/backup/pc": 2 * GIB}


class Janela:
    def __init__(self, relogio: Any, maximo: int, janela_s: float = JANELA_S) -> None:
        self.relogio = relogio
        self.maximo = maximo
        self.janela_s = janela_s
        self._marcas: dict[Any, deque[float]] = {}
        self._trava = threading.Lock()

    def contar(self, chave: Any, codigo: str = "muitas_requisicoes") -> None:
        agora = self.relogio.monotonico()
        with self._trava:
            fila = self._marcas.setdefault(chave, deque())
            while fila and agora - fila[0] >= self.janela_s:
                fila.popleft()
            if len(fila) >= self.maximo:
                espera = max(1, math.ceil(self.janela_s - (agora - fila[0])))
                raise ErroApi(429, codigo, "limite de requisições; tente de novo depois",
                              {"Retry-After": str(espera)})
            fila.append(agora)


class Limites:
    def __init__(self, relogio: Any) -> None:
        self.dispositivo = Janela(relogio, POR_MINUTO)
        self.trocar_ip = Janela(relogio, TROCAR_POR_MINUTO)

    def por_dispositivo(self, request: Any, disp: Dispositivo) -> None:
        if request.url.path in ISENTAS:
            return
        self.dispositivo.contar(disp.id)

    def por_ip(self, request: Any) -> None:
        ip = request.client.host if request.client else "?"
        self.trocar_ip.contar(ip, "muitas_tentativas")


def limite_de_corpo(caminho: str) -> int:
    return CORPO_POR_ROTA.get(caminho, CORPO_PADRAO)


_RESPOSTA_413 = json.dumps({"erro": "corpo_grande", "msg": "corpo maior que o limite da rota"}).encode()


class LimiteCorpo:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limite = limite_de_corpo(scope.get("path", ""))
        for nome, valor in scope.get("headers", []):
            if nome == b"content-length":
                try:
                    if int(valor) > limite:
                        await _responder_413(send)
                        return
                except ValueError:
                    pass
        recebido = 0
        estourou = False
        respondeu = False

        async def receive_contado() -> dict:
            nonlocal recebido, estourou
            if estourou:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                recebido += len(msg.get("body", b""))
                if recebido > limite:
                    estourou = True
                    return {"type": "http.disconnect"}
            return msg

        async def send_trocado(msg: dict) -> None:
            # estourou no meio da leitura: a resposta do app (400/500 de corpo cortado) vira 413
            nonlocal respondeu
            if not estourou:
                await send(msg)
            elif not respondeu and msg["type"] == "http.response.start":
                respondeu = True
                await _responder_413(send)

        await self.app(scope, receive_contado, send_trocado)


async def _responder_413(send: Any) -> None:
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(_RESPOSTA_413)).encode())]})
    await send({"type": "http.response.body", "body": _RESPOSTA_413})
