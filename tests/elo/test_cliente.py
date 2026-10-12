"""``EloCliente`` (Y2.4): reconexão com jitter, recaída em long-poll, 401, ``bate``, reenvio e despacho.

Rede falsa: ``Conexao`` em memória, ``httpx.MockTransport`` e um servidor ``websockets`` em
``127.0.0.1:0``. Relógio e ``dormir`` falsos (o tempo anda só quando o cliente dorme).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from http import HTTPStatus

import httpx
import pytest

from magi.elo.cliente import (
    ConexaoFechada,
    EloCliente,
    TokenRevogado,
    espera_reconexao,
)
from magi.elo.ids import novo_id
from magi.elo.mensagens import (
    Acao,
    AcaoOk,
    AcaoPedido,
    AcaoResultado,
    Ack,
    Confirma,
    Envelope,
    Ola,
    Tipo,
    TipoDispositivo,
    decode,
    encode,
    responder,
)
from magi.elo.quadros import Quadro, QuadroTipo, encode_quadro

BASE = "https://ayanami.exemplo.ts.net"
TOKEN = "ayn_casa_falso"


class Tempo:
    def __init__(self) -> None:
        self.t = 1000.0
        self.dormidas: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def dormir(self, s: float) -> None:
        self.dormidas.append(s)
        self.t += s
        await asyncio.sleep(0)


class ConexaoFalsa:
    """Lado servidor em memória: responde ``ack`` ao ``ola`` e guarda (instante, frame) enviados."""

    def __init__(self, tempo: Tempo, *, ack: bool = True) -> None:
        self.tempo = tempo
        self.ack = ack
        self.enviados: list[tuple[float, str | bytes]] = []
        self.entrada: asyncio.Queue[str | bytes | Exception] = asyncio.Queue()
        self.conectado = asyncio.Event()
        self.fechada = False

    async def enviar(self, dado: str | bytes) -> None:
        self.enviados.append((self.tempo(), dado))
        if isinstance(dado, str):
            env = decode(dado)
            if env.t is Tipo.OLA and self.ack:
                self.entrada.put_nowait(encode(responder(env, Tipo.ACK, Ack(), "ayanami")))
                self.conectado.set()

    async def receber(self) -> str | bytes:
        item = await self.entrada.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def fechar(self) -> None:
        self.fechada = True

    def textos(self, tipo: Tipo) -> list[tuple[float, Envelope]]:
        out = []
        for t, d in self.enviados:
            if isinstance(d, str):
                env = decode(d)
                if env.t is tipo:
                    out.append((t, env))
        return out


def _ola() -> Ola:
    return Ola(tipo=TipoDispositivo("casa"), versao="0.0.0-teste", caps=("acao", "estado"))


def _cliente(tempo: Tempo, conectar, **kw) -> EloCliente:  # noqa: ANN001
    return EloCliente(
        BASE,
        TOKEN,
        "casa",
        _ola,
        relogio=tempo,
        dormir=tempo.dormir,
        rng=random.Random(7),
        conectar=conectar,
        **kw,
    )


async def _ate(cond, passos: int = 2000) -> None:  # noqa: ANN001
    for _ in range(passos):
        if cond():
            return
        await asyncio.sleep(0)
    raise AssertionError("condição não chegou")


# --- reconexão --------------------------------------------------------------------------------


def test_espera_reconexao_1_2_4_ate_60_com_jitter() -> None:
    rng = random.Random(42)
    bases = [1, 2, 4, 8, 16, 32, 60, 60, 60]
    esperas = [espera_reconexao(n, rng) for n in range(1, len(bases) + 1)]
    for e, b in zip(esperas, bases, strict=True):
        assert 0.8 * b <= e <= 1.2 * b
    assert len({round(e / b, 6) for e, b in zip(esperas, bases, strict=True)}) > 1  # jitter de fato
    rng2 = random.Random(42)
    assert esperas == [espera_reconexao(n, rng2) for n in range(1, len(bases) + 1)]


async def test_rodar_espera_sequencia_de_reconexao_sem_longpoll() -> None:
    tempo = Tempo()
    tentativas: list[tuple[str, dict]] = []

    async def conectar(url, cab):  # noqa: ANN001, ANN202
        tentativas.append((url, dict(cab)))
        if len(tentativas) >= 8:
            cli.parar()
        raise OSError("recusada")

    cli = _cliente(tempo, conectar)  # sem http: nunca cai no long-poll
    await cli.rodar()
    assert tentativas[0] == (
        "wss://ayanami.exemplo.ts.net/ws",
        {"Authorization": f"Bearer {TOKEN}"},
    )
    rng = random.Random(7)
    esperado = [espera_reconexao(n, rng) for n in range(1, 8)]
    assert tempo.dormidas == pytest.approx(esperado)
    for e, b in zip(tempo.dormidas, [1, 2, 4, 8, 16, 32, 60], strict=True):
        assert 0.8 * b <= e <= 1.2 * b


async def test_conexao_boa_zera_a_espera() -> None:
    tempo = Tempo()
    chamadas: list[int] = []

    async def conectar(url, cab):  # noqa: ANN001, ANN202
        chamadas.append(1)
        if len(chamadas) in (1, 2):
            raise OSError
        if len(chamadas) == 4:
            cli.parar()
            raise OSError
        c = ConexaoFalsa(tempo)

        async def derruba() -> None:
            await c.conectado.wait()
            c.entrada.put_nowait(ConexaoFechada(1006))

        asyncio.get_running_loop().create_task(derruba())
        return c

    cli = _cliente(tempo, conectar)
    await cli.rodar()
    # falhou 2× (1 s, 2 s), conectou e caiu: volta a 1 s ± 20%
    assert len(tempo.dormidas) >= 3
    assert 0.8 <= tempo.dormidas[0] <= 1.2
    assert 1.6 <= tempo.dormidas[1] <= 2.4
    assert 0.8 <= tempo.dormidas[-1] <= 1.2


async def test_tres_falhas_de_ws_caem_no_longpoll() -> None:
    tempo = Tempo()
    tentativas: list[str] = []
    pedidos: list[httpx.Request] = []

    async def conectar(url, cab):  # noqa: ANN001, ANN202
        tentativas.append(url)
        raise OSError

    def servidor(req: httpx.Request) -> httpx.Response:
        pedidos.append(req)
        assert req.headers["authorization"] == f"Bearer {TOKEN}"
        if req.method == "POST":
            envs = json.loads(req.content)["envelopes"]
            ola = decode(json.dumps(envs[0]))
            ack = json.loads(encode(responder(ola, Tipo.ACK, Ack(), "ayanami")))
            return httpx.Response(200, json={"respostas": [ack]})
        gets = [p for p in pedidos if p.method == "GET"]
        if len(gets) >= 3:
            cli.parar()
        return httpx.Response(200, json={"envelopes": [], "ate": 41 + len(gets)})

    http = httpx.AsyncClient(transport=httpx.MockTransport(servidor))
    cli = _cliente(tempo, conectar, http=http)
    await cli.rodar()
    await http.aclose()
    assert len(tentativas) == 3
    assert {p.url.path for p in pedidos} == {"/v1/longpoll"}
    posts = [p for p in pedidos if p.method == "POST"]
    assert decode(json.dumps(json.loads(posts[0].content)["envelopes"][0])).t is Tipo.OLA
    assert cli.modo is None
    gets = [p for p in pedidos if p.method == "GET"]
    assert gets[0].url.params["espera"] == "25"
    assert gets[0].url.params["desde"] == "0"
    assert gets[1].url.params["desde"] == "42"


async def test_401_para_e_loga(caplog: pytest.LogCaptureFixture) -> None:
    tempo = Tempo()
    tentativas: list[str] = []

    async def conectar(url, cab):  # noqa: ANN001, ANN202
        tentativas.append(url)
        raise TokenRevogado

    cli = _cliente(tempo, conectar)
    with caplog.at_level(logging.WARNING, logger="magi.elo.cliente"):
        await asyncio.wait_for(cli.rodar(), 1)
    assert tentativas == ["wss://ayanami.exemplo.ts.net/ws"]
    assert cli.revogado
    assert tempo.dormidas == []
    assert "ayanami_token_revogado" in caplog.text


async def test_ws_fechada_com_4001_para() -> None:
    tempo = Tempo()
    conexoes: list[ConexaoFalsa] = []

    async def conectar(url, cab):  # noqa: ANN001, ANN202
        c = ConexaoFalsa(tempo)
        conexoes.append(c)

        async def revoga() -> None:
            await c.conectado.wait()
            c.entrada.put_nowait(ConexaoFechada(4001))

        asyncio.get_running_loop().create_task(revoga())
        return c

    cli = _cliente(tempo, conectar)
    await asyncio.wait_for(cli.rodar(), 1)
    assert len(conexoes) == 1 and cli.revogado and conexoes[0].fechada


async def test_401_no_longpoll_para() -> None:
    tempo = Tempo()

    async def conectar(url, cab):  # noqa: ANN001, ANN202
        raise OSError

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"erro": "token"}))
    )
    cli = _cliente(tempo, conectar, http=http)
    await asyncio.wait_for(cli.rodar(), 1)
    await http.aclose()
    assert cli.revogado


# --- sessão -----------------------------------------------------------------------------------


async def _sessao(tempo: Tempo, **kw) -> tuple[EloCliente, ConexaoFalsa, asyncio.Task]:  # noqa: ANN003
    con = ConexaoFalsa(tempo)

    async def conectar(url, cab):  # noqa: ANN001, ANN202
        return con

    cli = _cliente(tempo, conectar, **kw)
    tarefa = asyncio.get_running_loop().create_task(cli.rodar())
    await con.conectado.wait()
    await _ate(lambda: cli.modo == "ws" and not cli._pendentes)
    return cli, con, tarefa


async def test_bate_a_cada_10_s() -> None:
    tempo = Tempo()
    cli, con, tarefa = await _sessao(tempo, custos=lambda: 1.25)
    await _ate(lambda: len(con.textos(Tipo.BATE)) >= 5, 20000)
    cli.parar()
    await tarefa
    bates = con.textos(Tipo.BATE)
    ola_t = con.textos(Tipo.OLA)[0][0]
    instantes = [t for t, _ in bates]
    assert instantes[0] == pytest.approx(ola_t + 10)
    assert [b - a for a, b in zip(instantes, instantes[1:], strict=False)] == pytest.approx(
        [10.0] * (len(bates) - 1)
    )
    assert [e.corpo.seq for _, e in bates] == list(range(len(bates)))
    assert bates[0][1].corpo.custos_mes_usd == 1.25


async def test_envelope_sem_resposta_reenviado_3x_com_mesmo_id() -> None:
    tempo = Tempo()
    cli, con, tarefa = await _sessao(tempo)
    env = Envelope(
        t=Tipo.CONFIRMA, corpo=Confirma(pedido=novo_id(), descricao="?"), de="casa", para="ayanami"
    )
    t0 = tempo()
    with pytest.raises(TimeoutError):
        await cli.enviar_env(env)
    enviados = [(t, e) for t, e in con.textos(Tipo.CONFIRMA) if e.id == env.id]
    assert len(enviados) == 4  # original + 3 reenvios
    assert [t - t0 for t, _ in enviados] == pytest.approx([0, 10, 20, 30])
    cli.parar()
    await tarefa


async def test_resposta_resolve_o_envio() -> None:
    tempo = Tempo()
    cli, con, tarefa = await _sessao(tempo)
    env = Envelope(t=Tipo.CONFIRMA, corpo=Confirma(pedido=novo_id()), de="casa", para="ayanami")
    resposta = responder(env, Tipo.ACK, Ack(), "ayanami")
    con.entrada.put_nowait(encode(resposta))  # chega antes do 1º reenvio
    assert await cli.enviar_env(env) == resposta
    assert len([e for _, e in con.textos(Tipo.CONFIRMA) if e.id == env.id]) == 1
    cli.parar()
    await tarefa


async def test_despacho_por_tipo_idempotente_e_quadros() -> None:
    tempo = Tempo()
    chamadas: list[str] = []
    quadros: list[Quadro] = []

    def acao(env: Envelope) -> AcaoOk:
        chamadas.append(env.id)
        return AcaoOk(resultado=AcaoResultado(ok=True, fala="feito"))

    con = ConexaoFalsa(tempo)

    async def conectar(url, cab):  # noqa: ANN001, ANN202
        return con

    cli = _cliente(tempo, conectar)
    cli.on(Tipo.ACAO, acao)
    cli.on_quadro(quadros.append)
    tarefa = asyncio.get_running_loop().create_task(cli.rodar())
    await con.conectado.wait()
    pedido = Envelope(
        t=Tipo.ACAO, corpo=Acao(pedido=AcaoPedido(intent="tv.mute"), origem="pwa"), de="ayanami", para="casa"
    )
    for _ in range(3):
        con.entrada.put_nowait(encode(pedido))
    q = Quadro(tipo=QuadroTipo.AUDIO_OUT, turno=novo_id(), pcm=b"\x00\x01" * 4)
    con.entrada.put_nowait(encode_quadro(q))
    con.entrada.put_nowait("{lixo")
    await _ate(lambda: len(con.textos(Tipo.ERRO)) == 1)
    cli.parar()
    await tarefa
    assert chamadas == [pedido.id]
    oks = con.textos(Tipo.ACAO_OK)
    assert len(oks) == 3 and {e.resp for _, e in oks} == {pedido.id}
    assert len({e.id for _, e in oks}) == 1  # mesma resposta do cache
    assert oks[0][1].corpo.resultado.fala == "feito"
    assert quadros == [q]
    assert con.textos(Tipo.ERRO)[0][1].corpo.codigo == "invalido"


async def test_tipo_sem_handler_que_pede_resposta_recebe_ack() -> None:
    tempo = Tempo()
    cli, con, tarefa = await _sessao(tempo)
    env = Envelope(t=Tipo.CONFIRMA, corpo=Confirma(pedido=novo_id()), de="ayanami", para="casa")
    con.entrada.put_nowait(encode(env))
    await _ate(lambda: len(con.textos(Tipo.ACK)) == 1)
    assert con.textos(Tipo.ACK)[0][1].resp == env.id
    cli.parar()
    await tarefa


async def test_enviar_quadro_e_sem_conexao() -> None:
    tempo = Tempo()
    cli = _cliente(tempo, None)
    with pytest.raises(ConexaoFechada):
        await cli.enviar(Tipo.ACK, Ack())
    cli, con, tarefa = await _sessao(tempo)
    q = Quadro(tipo=QuadroTipo.AUDIO_FIM, turno=novo_id())
    await cli.enviar_quadro(q)
    assert con.enviados[-1][1] == encode_quadro(q)
    cli.parar()
    await tarefa


# --- servidor WS falso local (websockets em 127.0.0.1:0) ---------------------------------------


async def test_servidor_ws_local_ola_ack_bate() -> None:
    from websockets.asyncio.server import serve

    recebidos: list[Envelope] = []
    cabecalhos: list[str | None] = []

    async def handler(ws) -> None:  # noqa: ANN001
        cabecalhos.append(ws.request.headers.get("Authorization"))
        async for raw in ws:
            env = decode(raw)
            recebidos.append(env)
            if env.t is Tipo.OLA:
                await ws.send(encode(responder(env, Tipo.ACK, Ack(), "ayanami")))
            if env.t is Tipo.BATE:
                cli.parar()
                await ws.close()
                return

    async with serve(handler, "127.0.0.1", 0) as srv:
        porta = srv.sockets[0].getsockname()[1]
        cli = EloCliente(f"http://127.0.0.1:{porta}", TOKEN, "casa", _ola, batimento_s=0.02)
        await asyncio.wait_for(cli.rodar(), 5)
    assert cabecalhos == [f"Bearer {TOKEN}"]
    assert [e.t for e in recebidos] == [Tipo.OLA, Tipo.BATE]


async def test_servidor_ws_local_401() -> None:
    from websockets.asyncio.server import serve

    def recusa(conn, req):  # noqa: ANN001, ANN202
        return conn.respond(HTTPStatus.UNAUTHORIZED, "token\n")

    async def handler(ws) -> None:  # noqa: ANN001
        raise AssertionError("não devia abrir")

    async with serve(handler, "127.0.0.1", 0, process_request=recusa) as srv:
        porta = srv.sockets[0].getsockname()[1]
        cli = EloCliente(f"http://127.0.0.1:{porta}", TOKEN, "casa", _ola)
        await asyncio.wait_for(cli.rodar(), 5)
    assert cli.revogado
