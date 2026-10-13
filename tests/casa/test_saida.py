"""Saída da casa à Ayanami (C1.6; spec §10.3, CA-Y35 caminho WS, CA-Y39).

Ayanami falsa: servidor ``websockets`` em ``127.0.0.1:0``. Rede/reconexão são do ``EloCliente``
(Y2.4); aqui o que é da casa: token, ``ola`` com TVs, ``estado``, ``acao`` remota no ``Executor``,
401 sem derrubar a API local e o driver recriado quando o IP muda. Nada de TV real nem sleep real
acima de 50 ms.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import replace
from http import HTTPStatus

import pytest
from websockets.asyncio.server import serve

from magi.casa import saida as saida_mod
from magi.casa.config import CasaConfig, caminho_token_ayanami, caminho_token_local
from magi.casa.driver import Cap, Capacidades, ContextoDriver, Motivo, ResTv, TvConfig
from magi.casa.emula import Executor
from magi.casa.estado import EstadoCasa
from magi.casa.falso import DriverFalso
from magi.casa.local import resultado_de_res
from magi.casa.saida import SaidaAyanami, ler_token
from magi.casa.servir import servir_async, trocar_drivers
from magi.elo.mensagens import (
    Acao,
    AcaoPedido,
    Ack,
    Envelope,
    Estado,
    EstadoTv,
    Ola,
    Tipo,
    TipoDispositivo,
    decode,
    encode,
    responder,
)

TOKEN = "ayn_casa_falso"
TODAS = Capacidades(frozenset(Cap), entradas=("hdmi1",), apps=("netflix",))
SALA = TvConfig(id="sala", nome="TV da sala", driver="falso", ip="10.0.0.5")


class AyanamiFalsa:
    """WS falso: guarda o que chega, responde ``ack`` ao ``ola``; ``recusar`` = código HTTP."""

    def __init__(
        self, *, recusar_apos: int | None = None, status: HTTPStatus = HTTPStatus.SERVICE_UNAVAILABLE
    ):
        self.recebidos: asyncio.Queue[Envelope] = asyncio.Queue()
        self.cabecalhos: list[str | None] = []
        self.conexoes = 0
        self.recusar_apos = recusar_apos
        self.status = status
        self.ws = None
        self.fechar_apos_ack = False

    def _processa(self, conn, req):  # noqa: ANN001, ANN202
        self.conexoes += 1
        if self.recusar_apos is not None and self.conexoes > self.recusar_apos:
            return conn.respond(self.status, "nao\n")
        return None

    async def _handler(self, ws) -> None:  # noqa: ANN001
        self.ws = ws
        self.cabecalhos.append(ws.request.headers.get("Authorization"))
        async for raw in ws:
            env = decode(raw)
            await self.recebidos.put(env)
            if env.t is Tipo.OLA:
                await ws.send(encode(responder(env, Tipo.ACK, Ack(), "ayanami")))
                if self.fechar_apos_ack:
                    await ws.close()
                    return

    async def proximo(self, tipo: Tipo, prazo: float = 3.0) -> Envelope:
        async def _busca() -> Envelope:
            while True:
                env = await self.recebidos.get()
                if env.t is tipo:
                    return env

        return await asyncio.wait_for(_busca(), prazo)

    def servir(self):  # noqa: ANN201
        return serve(self._handler, "127.0.0.1", 0, process_request=self._processa)


async def _dorme_curto(s: float) -> None:
    await asyncio.sleep(min(s, 0.01))


def _montar(relogio, **kw):  # noqa: ANN001, ANN003
    drv = DriverFalso(TODAS, relogio=relogio, tv_id="sala", tv_nome="TV da sala")
    cfg = CasaConfig(tvs=(SALA,))
    ex = Executor(cfg, {"sala": drv}, relogio=relogio, dormir=relogio.dormir)
    estado = EstadoCasa({"sala": drv}, {"sala": ("TV da sala", "falso")}, gravar_arquivo=False)

    def catalogo():
        from magi.casa.config import tv_info

        return (tv_info(SALA, drv.capacidades, padrao=True),), ()

    return drv, ex, estado, catalogo


def _saida(porta: int, ex, estado, catalogo, **kw) -> SaidaAyanami:  # noqa: ANN001, ANN003
    return SaidaAyanami(
        f"http://127.0.0.1:{porta}", TOKEN, ex, estado, catalogo, versao="0-teste", rng=random.Random(3), **kw
    )


# --- token -------------------------------------------------------------------------------------


def test_ler_token_arquivo_keyring_e_permissao(log_casa):
    p = caminho_token_ayanami()
    assert ler_token(keyring_get=lambda nome: None) is None
    assert (
        ler_token(keyring_get=lambda nome: "do-keyring" if nome == saida_mod.SEGREDO else None)
        == "do-keyring"
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("do-arquivo\n")
    os.chmod(p, 0o600)
    assert ler_token(keyring_get=lambda nome: "do-keyring") == "do-arquivo"
    os.chmod(p, 0o644)
    assert ler_token(keyring_get=lambda nome: "do-keyring") is None
    assert "do-arquivo" not in log_casa.texto
    assert any(x["evento"] == "permissao_aberta" for x in log_casa.linhas())


def test_candidatos_vao_em_dados():
    r = resultado_de_res(ResTv(False, Motivo.TV_AMBIGUA, "sala,quarto"), None)
    assert r.dados["candidatos"] == ["sala", "quarto"]
    assert "candidatos" not in resultado_de_res(ResTv(True), "sala").dados


# --- ola, bate, estado, acao (CA-Y39, CA-Y35 pela WS) ---------------------------------------------


async def test_ola_com_tvs_sem_token_bate_e_estado(relogio):
    drv, ex, estado, catalogo = _montar(relogio)
    ay = AyanamiFalsa()
    async with ay.servir() as srv:
        porta = srv.sockets[0].getsockname()[1]
        s = _saida(porta, ex, estado, catalogo, batimento_s=0.02, periodo_estado_s=0.03)
        t = asyncio.create_task(s.rodar())
        ola = await ay.proximo(Tipo.OLA)
        assert isinstance(ola.corpo, Ola) and ola.corpo.tipo is TipoDispositivo.CASA
        assert ola.corpo.token is None and [tv.id for tv in ola.corpo.tvs] == ["sala"]
        assert ay.cabecalhos == [f"Bearer {TOKEN}"]
        assert (await ay.proximo(Tipo.BATE)).corpo.seq == 0
        # periódico
        assert (await ay.proximo(Tipo.ESTADO)).corpo.tvs[0].id == "sala"
        # a cada mudança
        await estado.atualizar(EstadoTv("sala", "TV da sala", "falso", True, ligada=True, app="netflix"))
        for _ in range(20):
            env = await ay.proximo(Tipo.ESTADO)
            if env.corpo.tvs[0].app == "netflix":
                break
        else:
            raise AssertionError("estado da mudança não chegou")
        s.parar()
        await ay.ws.close()
        await asyncio.wait_for(t, 3)


async def test_acao_remota_power_off_sem_confirmar_e_estado_pedido(relogio, log_casa):
    drv, ex, estado, catalogo = _montar(relogio)
    ay = AyanamiFalsa()
    async with ay.servir() as srv:
        porta = srv.sockets[0].getsockname()[1]
        s = _saida(porta, ex, estado, catalogo)
        t = asyncio.create_task(s.rodar())
        await ay.proximo(Tipo.OLA)
        pedido = AcaoPedido(intent="tv.power_off", slots=(("tv", "sala"),), confirmed=False)
        acao = Envelope(t=Tipo.ACAO, corpo=Acao(pedido=pedido, origem="pwa"), de="celular-x", para="casa")
        await ay.ws.send(encode(acao))
        r = await ay.proximo(Tipo.ACAO_OK)
        assert r.resp == acao.id
        assert not r.corpo.resultado.ok and r.corpo.resultado.precisa_confirmar
        assert r.corpo.resultado.motivo == Motivo.PRECISA_CONFIRMAR.value
        assert "power" not in drv.metodos()
        # reenvio da mesma acao (reconexão) não roda 2×
        await ay.ws.send(encode(acao))
        pedir = Envelope(t=Tipo.ESTADO, corpo=Estado(tvs=()), de="ayanami", para="casa")
        await ay.ws.send(encode(pedir))
        e = await ay.proximo(Tipo.ESTADO)
        assert e.resp == pedir.id and e.corpo.tvs[0].id == "sala"
        s.parar()
        await ay.ws.close()
        await asyncio.wait_for(t, 3)
    acoes = [x for x in log_casa.linhas() if x["evento"] == "acao" and x.get("origem") == "ayanami"]
    assert acoes and acoes[0]["motivo"] == "precisa_confirmar"
    assert TOKEN not in log_casa.texto


async def test_queda_reconecta_1_2_4_com_jitter(relogio, caplog):
    caplog.set_level(logging.INFO, logger="magi.elo.cliente")
    _drv, ex, estado, catalogo = _montar(relogio)
    ay = AyanamiFalsa(recusar_apos=1)
    ay.fechar_apos_ack = True
    async with ay.servir() as srv:
        porta = srv.sockets[0].getsockname()[1]
        s = _saida(porta, ex, estado, catalogo, dormir=_dorme_curto)
        t = asyncio.create_task(s.rodar())
        for _ in range(500):
            esperas = [r.espera_s for r in caplog.records if r.getMessage() == "elo_reconecta"]
            if len(esperas) >= 8:
                break
            await asyncio.sleep(0.01)
        s.parar()
        await asyncio.wait_for(t, 3)
    falhas = [r.falhas for r in caplog.records if r.getMessage() == "elo_reconecta"][:8]
    assert falhas == [0, 1, 2, 3, 4, 5, 6, 7]  # 1ª sessão chegou ao ack; depois só falhas
    for f, e in zip(falhas, esperas[:8], strict=True):
        alvo = min(60.0, 2 ** (max(1, f) - 1))
        assert alvo * 0.8 - 0.01 <= e <= alvo * 1.2 + 0.01, (f, e)
    assert max(esperas) <= 60 * 1.2


async def test_401_para_e_api_local_segue(tmp_path, log_casa):
    ay = AyanamiFalsa(recusar_apos=0, status=HTTPStatus.UNAUTHORIZED)
    tok = caminho_token_ayanami()
    tok.parent.mkdir(parents=True, exist_ok=True)
    tok.write_text(TOKEN + "\n")
    os.chmod(tok, 0o600)
    async with ay.servir() as srv:
        porta_ay = srv.sockets[0].getsockname()[1]
        cfg = CasaConfig(ayanami=f"http://127.0.0.1:{porta_ay}")
        parar = asyncio.Event()
        pronto: asyncio.Future = asyncio.get_running_loop().create_future()
        t = asyncio.create_task(
            servir_async(cfg=cfg, porta=0, parar=parar, pronto=lambda h, p: pronto.set_result(p))
        )
        porta = await asyncio.wait_for(pronto, 2)
        for _ in range(300):
            if any(x["evento"] == "ayanami_token_revogado" for x in log_casa.linhas()):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("não logou ayanami_token_revogado")
        assert ay.conexoes == 1
        r, w = await asyncio.open_connection("127.0.0.1", porta)
        ola = Envelope(
            t=Tipo.OLA,
            corpo=Ola(tipo=TipoDispositivo.PC, versao="t", token=caminho_token_local().read_text().strip()),
            de="pc",
            para="casa",
        )
        w.write(encode(ola).encode() + b"\n")
        await w.drain()
        resp = decode(await asyncio.wait_for(r.readline(), 2))
        assert resp.t is Tipo.OLA and resp.corpo.tipo is TipoDispositivo.CASA
        w.close()
        await asyncio.sleep(0.01)
        assert ay.conexoes == 1  # parou de reconectar
        parar.set()
        assert await asyncio.wait_for(t, 3) == 0
    assert TOKEN not in log_casa.texto


async def test_sem_token_nao_conecta(log_casa, monkeypatch):
    import magi.casa.servir as servir_mod

    monkeypatch.setattr(servir_mod, "ler_token", lambda *a, **k: None)
    parar = asyncio.Event()
    pronto: asyncio.Future = asyncio.get_running_loop().create_future()
    cfg = CasaConfig(ayanami="http://127.0.0.1:9")
    t = asyncio.create_task(
        servir_async(cfg=cfg, porta=0, parar=parar, pronto=lambda h, p: pronto.set_result(p))
    )
    await asyncio.wait_for(pronto, 2)
    parar.set()
    assert await asyncio.wait_for(t, 3) == 0
    assert any(x["evento"] == "ayanami_sem_token" for x in log_casa.linhas())


# --- IP novo → driver novo (sobra da C1.5) ------------------------------------------------------


async def test_ip_novo_recria_o_driver(relogio, log_casa):
    criados: list[TvConfig] = []

    def fabrica(tv: TvConfig, ctx: ContextoDriver) -> DriverFalso:
        criados.append(tv)
        return DriverFalso(TODAS, relogio=relogio, tv_id=tv.id)

    quarto = TvConfig(id="quarto", nome="Quarto", driver="falso", ip="10.0.0.6")
    atual = CasaConfig(tvs=(SALA, quarto))
    ctx = ContextoDriver(broadcast=atual.broadcast, apps=None, dir_pareamento=None)  # type: ignore[arg-type]
    drivers = {tv.id: fabrica(tv, ctx) for tv in atual.tvs}
    velho = drivers["sala"]
    ex = Executor(atual, drivers, relogio=relogio, dormir=relogio.dormir)
    estado = EstadoCasa(
        drivers, {"sala": ("Sala", "falso"), "quarto": ("Quarto", "falso")}, gravar_arquivo=False
    )
    novo = replace(atual, tvs=(replace(SALA, ip="10.0.0.99"), quarto))
    trocados = await trocar_drivers(novo, atual, drivers, estado, ex, ctx, fabrica)
    assert trocados == ["sala"]
    assert criados[-1].ip == "10.0.0.99" and len(criados) == 3
    assert drivers["sala"] is not velho and ex.drivers["sala"] is drivers["sala"]
    assert estado.drivers["sala"] is drivers["sala"]
    assert "fechar" in velho.metodos() and "conectar" in drivers["sala"].metodos()
    assert ex.cfg is novo
    assert await trocar_drivers(novo, novo, drivers, estado, ex, ctx, fabrica) == []
    assert any(x["evento"] == "driver_recriado" for x in log_casa.linhas())


@pytest.fixture(autouse=True)
def _sem_keyring(monkeypatch):
    """Nunca o keyring real: sem arquivo, ``ler_token`` cai aqui."""
    import magi.common.secrets as segredos

    monkeypatch.setattr(segredos, "get_secret", lambda nome: None)
