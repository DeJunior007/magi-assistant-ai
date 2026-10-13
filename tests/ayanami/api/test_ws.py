"""Y2.2: ``/ws`` dos nós contra a app de verdade em ``127.0.0.1:0`` (uvicorn no loop do teste).

Clientes: ``websockets`` cru e o ``EloCliente`` real (Y2.4). Relógio manual: ``dormir`` só volta
quando o teste avança o tempo (prazo do ``ola``, reenvio do hub, varredura de revogação).
CA-Y7 (revogar fecha com 4001 e o REST dá 401), CA-Y5 pela WS (mesmo ``acao`` 3× → 1 execução),
4002 na 2ª WS, 4003 sem ``ola`` em 5 s, 1008 por abuso, 401/403 no upgrade, long-poll.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from ayanami.api.auth import marcar_revogado
from ayanami.hub import hub_de
from magi.elo.cliente import EloCliente
from magi.elo.mensagens import (
    Acao,
    AcaoOk,
    AcaoPedido,
    AcaoResultado,
    Bate,
    Envelope,
    Ola,
    Tipo,
    TipoDispositivo,
    decode,
    encode,
)

pytestmark = pytest.mark.pg


class RelogioManual:
    def __init__(self) -> None:
        self._agora = datetime(2026, 10, 12, 21, 0, tzinfo=UTC)
        self._mono = 1000.0
        self.esperas: list[tuple[float, asyncio.Future[None]]] = []

    def agora(self) -> datetime:
        return self._agora

    def monotonico(self) -> float:
        return self._mono

    async def dormir(self, s: float) -> None:
        item = (self._mono + max(0.0, s), asyncio.get_running_loop().create_future())
        self.esperas.append(item)
        try:
            await item[1]
        finally:
            self.esperas.remove(item)

    def avancar(self, s: float) -> None:
        self._mono += s
        self._agora += timedelta(seconds=s)
        for fim, fut in list(self.esperas):
            if fim <= self._mono + 1e-9 and not fut.done():
                fut.set_result(None)


async def ate(cond, limite: float = 3.0) -> None:
    for _ in range(int(limite / 0.005)):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condição não chegou")


@pytest.fixture
def relogio() -> RelogioManual:
    return RelogioManual()


@pytest.fixture
async def servidor(app):
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="warning",
                                        ws_ping_interval=None))
    tarefa = asyncio.ensure_future(srv.serve())
    await ate(lambda: srv.started)
    porta = srv.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{porta}"
    finally:
        srv.should_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(tarefa, 5)


def _ws(base: str, token: str):
    return connect(base.replace("http://", "ws://") + "/ws",
                   additional_headers={"Authorization": f"Bearer {token}"},
                   ping_interval=None, open_timeout=3)


def _ola(nome: str, tipo: TipoDispositivo) -> str:
    return encode(Envelope(t=Tipo.OLA, corpo=Ola(tipo=tipo, versao="t"), de=nome, para="ayanami"))


async def _conectado(base: str, token: str, nome: str, tipo=TipoDispositivo.PC):
    ws = await _ws(base, token).__aenter__()
    await ws.send(_ola(nome, tipo))
    r = decode(await asyncio.wait_for(ws.recv(), 3))
    assert r.t is Tipo.ACK
    return ws


async def _codigo_fechamento(ws) -> int | None:
    with pytest.raises(ConnectionClosed) as e:
        while True:
            await asyncio.wait_for(ws.recv(), 3)
    return e.value.rcvd.code if e.value.rcvd else None


async def test_upgrade_401_e_403(servidor, novo_token):
    with pytest.raises(InvalidStatus) as e:
        async with _ws(servidor, "ayn_pc_" + "A" * 43):
            pass
    assert e.value.response.status_code == 401
    with pytest.raises(InvalidStatus) as e:
        async with _ws(servidor, novo_token("celular-pedro", "celular")):
            pass
    assert e.value.response.status_code == 403
    async with httpx.AsyncClient(base_url=servidor) as c:
        r = await c.get("/ws", headers={"Authorization": f"Bearer {novo_token('pc-x', 'pc')}"})
    assert r.status_code == 426


async def test_ola_ack_visto_e_online(servidor, app, novo_token, db):
    ws = await _conectado(servidor, novo_token("pc-pedro", "pc"), "pc-pedro")
    hub = hub_de(app.state.ctx)
    assert hub.online("pc") and not hub.online("casa")
    with db.connection() as conn:
        visto = conn.execute("SELECT visto FROM dispositivos WHERE nome = 'pc-pedro'").fetchone()[0]
    assert visto is not None
    await ws.close()


async def test_segunda_ws_fecha_a_primeira_com_4002(servidor, novo_token):
    token = novo_token("pc-pedro", "pc")
    ws1 = await _conectado(servidor, token, "pc-pedro")
    ws2 = await _conectado(servidor, token, "pc-pedro")
    assert await _codigo_fechamento(ws1) == 4002
    await ws2.send(encode(Envelope(t=Tipo.BATE, corpo=Bate(seq=0), de="pc-pedro", para="ayanami")))
    await ws2.close()


async def test_casa_sem_ola_em_5s_fechada(servidor, novo_token, relogio):
    async with _ws(servidor, novo_token("casa-sala", "casa")) as ws:
        await ate(lambda: relogio.esperas)
        relogio.avancar(4.9)
        await asyncio.sleep(0.02)
        relogio.avancar(0.1)
        assert await _codigo_fechamento(ws) == 4003


async def test_primeiro_frame_que_nao_e_ola_fecha(servidor, novo_token):
    async with _ws(servidor, novo_token("casa-sala", "casa")) as ws:
        await ws.send(encode(Envelope(t=Tipo.BATE, corpo=Bate(seq=0), de="casa-sala", para="ayanami")))
        assert await _codigo_fechamento(ws) == 4003


async def test_dez_invalidos_fecham_com_1008(servidor, novo_token):
    ws = await _conectado(servidor, novo_token("pc-pedro", "pc"), "pc-pedro")
    for i in range(9):
        await ws.send("{lixo")
        r = decode(await asyncio.wait_for(ws.recv(), 3))
        assert r.t is Tipo.ERRO and r.corpo.codigo == "invalido", i
    await ws.send("{lixo")
    assert await _codigo_fechamento(ws) == 1008


async def test_ca_y7_revogar_fecha_4001_e_rest_401(servidor, novo_token):
    token = novo_token("pc-pedro", "pc")
    ws = await _conectado(servidor, token, "pc-pedro")
    async with httpx.AsyncClient(base_url=servidor, headers={"Authorization": f"Bearer {token}"}) as c:
        assert (await c.delete("/v1/dispositivo")).status_code == 204
        assert await _codigo_fechamento(ws) == 4001
        assert (await c.get("/v1/casa/estado")).status_code == 401


async def test_revogado_por_outro_processo_fecha_em_ate_5s(servidor, novo_token, db, relogio):
    ws = await _conectado(servidor, novo_token("casa-sala", "casa"), "casa-sala", TipoDispositivo.CASA)
    with db.connection() as conn:  # como o `ayanami dispositivo revogar` (outro processo)
        marcar_revogado(conn, "casa-sala", relogio.agora())
    await ate(lambda: relogio.esperas)
    relogio.avancar(2.5)
    assert await _codigo_fechamento(ws) == 4001


def _cliente_elo(base: str, token: str, nome: str, tipo: TipoDispositivo, relogio) -> EloCliente:
    return EloCliente(base, token, nome, lambda: Ola(tipo=tipo, versao="t", caps=("acao", "estado")),
                      relogio=relogio.monotonico, dormir=relogio.dormir, rng=random.Random(1))


async def test_ca_y5_mesma_acao_3x_uma_execucao(servidor, app, novo_token, relogio):
    casa = _cliente_elo(servidor, novo_token("casa-sala", "casa"), "casa-sala", TipoDispositivo.CASA, relogio)
    liberar = asyncio.Event()
    execucoes: list[str] = []

    async def acao(env: Envelope):
        execucoes.append(env.id)
        await liberar.wait()
        return AcaoOk(AcaoResultado(ok=True, fala="feito"))

    casa.on(Tipo.ACAO, acao)
    rodando = asyncio.ensure_future(casa.rodar())
    hub = hub_de(app.state.ctx)
    try:
        await ate(lambda: hub.online("casa"))
        env = Envelope(t=Tipo.ACAO, corpo=Acao(pedido=AcaoPedido(intent="tv.mute"), origem="pwa"),
                       de="ayanami", para="casa")
        enviados: list[str] = []
        no = hub.destino("casa")
        original = no.canal.enviar

        async def contar(texto: str) -> None:
            if decode(texto).t is Tipo.ACAO:
                enviados.append(texto)
            await original(texto)

        no.canal.enviar = contar
        pedido = asyncio.ensure_future(hub.enviar_e_esperar(env, 30))
        await ate(lambda: execucoes)
        for n in (2, 3):
            relogio.avancar(10)
            await ate(lambda n=n: len(enviados) == n)
        liberar.set()
        r = await asyncio.wait_for(pedido, 3)
        assert r.t is Tipo.ACAO_OK and r.resp == env.id and r.corpo.resultado.ok
        assert len(enviados) == 3 and len(set(enviados)) == 1  # mesmo envelope, mesmo id
        await asyncio.sleep(0.05)
        assert execucoes == [env.id]
    finally:
        casa.parar()
        rodando.cancel()
        await asyncio.gather(rodando, return_exceptions=True)


async def test_acao_pela_rota_com_elocliente(servidor, app, novo_token, relogio):
    casa = _cliente_elo(servidor, novo_token("casa-sala", "casa"), "casa-sala", TipoDispositivo.CASA, relogio)
    casa.on(Tipo.ACAO, lambda env: AcaoOk(AcaoResultado(ok=True)))
    rodando = asyncio.ensure_future(casa.rodar())
    cel = novo_token("celular-pedro", "celular")
    try:
        await ate(lambda: hub_de(app.state.ctx).online("casa"))
        async with httpx.AsyncClient(base_url=servidor, headers={"Authorization": f"Bearer {cel}"}) as c:
            r = await c.post("/v1/casa/acao", json={"tv": None, "pedido": {"intent": "tv.power_on"}})
            assert r.status_code == 200, r.text
            assert r.json()["fala"] == "Pronto, TV ligada."
            assert (await c.get("/v1/casa/estado")).json()["online"] is True
    finally:
        casa.parar()
        rodando.cancel()
        await asyncio.gather(rodando, return_exceptions=True)


async def test_longpoll_ola_e_entrega(servidor, app, novo_token, relogio):
    token = novo_token("pc-pedro", "pc")
    h = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=servidor, headers=h) as c:
        ola = json.loads(_ola("pc-pedro", TipoDispositivo.PC))
        r = await c.post("/v1/longpoll", json={"envelopes": [ola]})
        assert r.status_code == 200 and r.json()["respostas"][0]["t"] == "ack"
        hub = hub_de(app.state.ctx)
        assert hub.online("pc") and hub.destino("pc").modo == "longpoll"
        evento = Envelope(t=Tipo.ACAO, corpo=Acao(pedido=AcaoPedido(intent="tv.mute"), origem="pwa"),
                          de="ayanami", para="pc")
        assert await hub.enviar(evento)
        d = (await c.get("/v1/longpoll", params={"desde": 0, "espera": 0})).json()
        assert [e["id"] for e in d["envelopes"]] == [evento.id] and d["ate"] == 1
        vazio = asyncio.ensure_future(c.get("/v1/longpoll", params={"desde": 1}))
        await ate(lambda: len(relogio.esperas) >= 2)
        relogio.avancar(25)
        assert (await vazio).json() == {"envelopes": [], "ate": 1}
        muitos = {"envelopes": [{}] * 21}
        assert (await c.post("/v1/longpoll", json=muitos)).status_code == 422
