"""WebSocket dos nós ``pc``/``casa`` e long-poll (dono: Y2.2; spec §1.3, §2.2, design §4.1).

``/ws``: ``Authorization: Bearer`` (só cabeçalho). Token inválido/revogado → ``401``; tipo que não
é ``pc``/``casa`` → ``403`` (resposta HTTP de recusa do upgrade). Aceita e espera o 1º frame
``ola`` em ≤ 5 s (relógio injetado) — sem ele, ou com outro tipo de frame, fecha com ``4003``.
Depois cada frame vai ao :class:`~ayanami.hub.Hub` (receptor do elo: ``erro`` em inválido, ``1008``
com 10 inválidos em 60 s). Fechamentos do hub: ``4001`` revogado, ``4002`` outra conexão do mesmo
dispositivo (a nova vence).

Um ``GET /ws`` HTTP comum (sem upgrade) autentica pela linha de ``ESCOPO_DE_ROTA`` e responde
``426``; a rota WebSocket tem ``methods`` vazio para a tabela da Y2.1 continuar batendo.

``/v1/longpoll``: recaída do ``EloCliente`` (spec §2.2). ``GET ?desde=<seq>&espera=25`` devolve
``{"envelopes":[…],"ate":seq}`` (vazio após ``espera``); ``POST {"envelopes":[…]}`` (≤ 20) devolve
``{"respostas":[…]}``. Uma conexão em long-poll conta como a conexão ativa do dispositivo.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request, WebSocket
from fastapi.responses import JSONResponse

from ayanami.api.auth import ESCOPO_DE_ROTA as _ROTAS
from ayanami.api.auth import ErroApi, checar, exigir_rota, token_do_cabecalho
from ayanami.hub import (
    FECHA_SEM_OLA,
    LONGPOLL_FILA,
    OLA_PRAZO_S,
    CanalLongpoll,
    Hub,
    No,
    esperar_com_prazo,
    hub_de,
)
from magi.elo.mensagens import MAX_TEXTO_BYTES, EloError, Tipo, decode

log = logging.getLogger("ayanami.api.nos")

router = APIRouter()

LONGPOLL_MAX_ENVIO = 20
LONGPOLL_ESPERA_MAX = 25


class CanalWs:
    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self._trava = asyncio.Lock()

    async def enviar(self, texto: str) -> None:
        async with self._trava:
            await self.ws.send_text(texto)

    async def fechar(self, codigo: int) -> None:
        async with self._trava:
            await self.ws.close(code=codigo)


async def _recusar(ws: WebSocket, status: int, codigo: str, msg: str) -> None:
    if "websocket.http.response" in ws.scope.get("extensions", {}):
        await ws.send_denial_response(JSONResponse({"erro": codigo, "msg": msg}, status_code=status))
    else:  # servidor sem a extensão: fecha antes do accept (o cliente vê 403)
        await ws.close(code=4001 if status == 401 else 4003)


def _ola_valido(texto: Any, tipo: str) -> bool:
    if not isinstance(texto, str):
        return False
    try:
        env = decode(texto)
    except EloError:
        return False
    corpo = env.corpo
    return env.t is Tipo.OLA and getattr(corpo, "tipo", None) == tipo and corpo.token is None  # type: ignore[union-attr]


@router.websocket("/ws")
async def ws_nos(ws: WebSocket) -> None:
    ctx = ws.app.state.ctx
    token = token_do_cabecalho(ws)  # type: ignore[arg-type]
    disp = await asyncio.to_thread(ctx.auth.verificar, token) if token else None
    if disp is None:
        await _recusar(ws, 401, "nao_autorizado", "token ausente, inválido ou revogado")
        return
    try:
        checar(disp, _ROTAS[("GET", "/ws")])  # type: ignore[arg-type]
    except ErroApi as e:
        await _recusar(ws, e.status, e.codigo, e.msg)
        return
    hub = hub_de(ctx)
    await ws.accept()
    try:
        msg = await esperar_com_prazo(ctx.relogio, ws.receive(), OLA_PRAZO_S)
    except TimeoutError:
        log.info("ws_sem_ola", extra={"dispositivo": disp.nome})
        await ws.close(code=FECHA_SEM_OLA)
        return
    primeiro = msg.get("text")
    if msg.get("type") != "websocket.receive" or not _ola_valido(primeiro, disp.tipo):
        await ws.close(code=FECHA_SEM_OLA)
        return
    canal = CanalWs(ws)
    no = await hub.registrar(disp, canal, "ws")
    log.info("ws_conectado", extra={"dispositivo": disp.nome})
    try:
        texto: Any = primeiro
        while True:
            if texto is not None:
                if not await _trata(hub, no, canal, texto):
                    return
            try:
                msg = await ws.receive()
            except RuntimeError:  # já fechada por outro caminho (4001/4002)
                return
            if msg.get("type") == "websocket.disconnect" or no.fechado:
                return
            texto = msg.get("text")
            if texto is None and msg.get("bytes") is not None:
                log.debug("ws_quadro_binario_ignorado")  # quadros de áudio: Y6.x
    finally:
        hub.remover(no)
        log.info("ws_desconectado", extra={"dispositivo": disp.nome})


async def _trata(hub: Hub, no: No, canal: CanalWs, texto: str) -> bool:
    respostas, fechar = await hub.receber(no, texto)
    try:
        for r in respostas:
            await canal.enviar(r)
        if fechar is not None:
            await canal.fechar(fechar)
            return False
    except RuntimeError:
        return False
    return not no.fechado


# --------------------------------------------------------------------------- long-poll


@router.get("/ws", status_code=426)
def ws_sem_upgrade(_disp: Annotated[Any, Depends(exigir_rota("GET", "/ws"))]) -> None:
    raise ErroApi(426, "upgrade", "use WebSocket nesta rota", {"Upgrade": "websocket"})


for _r in router.routes:  # a rota WS não entra na tabela (GET, /ws) — quem entra é a HTTP acima
    if _r.path == "/ws" and not hasattr(_r, "methods"):
        _r.methods = set()  # type: ignore[attr-defined]


async def _no_longpoll(hub: Hub, disp: Any) -> tuple[No, CanalLongpoll]:
    canal = hub.longpolls.get(disp.id)
    no = hub.ativo(disp.id)
    if canal is None or canal.fechado_com is not None or no is None or no.canal is not canal:
        canal = CanalLongpoll()
        hub.longpolls[disp.id] = canal
        no = await hub.registrar(disp, canal, "longpoll")
    canal.ultimo_get = hub.relogio.monotonico()
    return no, canal


@router.get("/v1/longpoll")
async def longpoll_ler(
    request: Request,
    disp: Annotated[Any, Depends(exigir_rota("GET", "/v1/longpoll"))],
    desde: Annotated[int, Query(ge=0)] = 0,
    espera: Annotated[int, Query(ge=0, le=LONGPOLL_ESPERA_MAX)] = LONGPOLL_ESPERA_MAX,
) -> dict:
    ctx = request.app.state.ctx
    hub = hub_de(ctx)
    no, canal = await _no_longpoll(hub, disp)
    await hub.marcar_visto(no)
    if not canal.desde(desde) and espera > 0:
        canal.novo.clear()
        try:
            await esperar_com_prazo(ctx.relogio, canal.novo.wait(), float(espera))
        except TimeoutError:
            pass
    itens = canal.desde(desde)[:LONGPOLL_FILA]
    return {"envelopes": [json.loads(t) for _, t in itens], "ate": itens[-1][0] if itens else desde}


@router.post("/v1/longpoll")
async def longpoll_mandar(
    request: Request,
    envelopes: Annotated[list[dict], Body(embed=True, max_length=LONGPOLL_MAX_ENVIO)],
    disp: Annotated[Any, Depends(exigir_rota("POST", "/v1/longpoll"))],
) -> dict:
    hub = hub_de(request.app.state.ctx)
    no, _ = await _no_longpoll(hub, disp)
    respostas: list[dict] = []
    for d in envelopes:
        texto = json.dumps(d, ensure_ascii=False)
        if len(texto.encode()) > MAX_TEXTO_BYTES:
            texto = texto[: MAX_TEXTO_BYTES + 1]  # o receptor responde erro "tamanho"
        saida, fechar = await hub.receber(no, texto)
        respostas.extend(json.loads(r) for r in saida)
        if fechar is not None:
            await hub.fechar_dispositivo(disp.id, fechar)
            break
    return {"respostas": respostas}
