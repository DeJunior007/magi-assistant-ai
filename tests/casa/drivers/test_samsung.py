"""Driver Samsung (C1.2; CA-Y40, CA-Y41) contra REST + WebSocket falsos em ``127.0.0.1:0``.

Nunca TV real: a ``samsungtvws`` fala com um ``aiohttp`` local (WS sem TLS); ``send_magic_packet`` e
keyring são injetados; relógio e ``dormir`` falsos (nada de espera real além de I/O local).
"""

from __future__ import annotations

import base64
import json
import socket
import stat

import pytest
from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

from magi.casa import apps as casa_apps
from magi.casa.driver import Cap, ContextoDriver, Key, Motivo, TvConfig
from magi.casa.drivers import criar_driver, samsung
from magi.casa.drivers.samsung import SamsungDriver

MAC = "aa:bb:cc:dd:ee:ff"
BROADCAST = "192.168.50.255"


class TvFalsa:
    """REST ``/api/v2/`` + WS ``/api/v2/channels/samsung.remote.control``."""

    def __init__(self) -> None:
        self.power_state: str | None = "standby"
        self.rest_vivo = True  # False: ``fazer`` aponta a REST para uma porta recusada
        self.modo_ws = "ok"  # "ok" | "negado" | "401" | "mudo"
        self.token_novo: str | None = None
        self.frames: list[dict] = []
        self.conexoes: list[dict] = []
        self.rest_chamadas = 0

    def teclas(self) -> list[str]:
        return [
            f["params"]["DataOfCmd"]
            for f in self.frames
            if f.get("method") == "ms.remote.control" and f["params"].get("TypeOfRemote") == "SendRemoteKey"
        ]

    async def rest(self, req: web.Request) -> web.StreamResponse:
        self.rest_chamadas += 1
        dev: dict = {"name": "[TV] Sala", "modelName": "QN55"}
        if self.power_state is not None:
            dev["PowerState"] = self.power_state
        return web.json_response({"device": dev, "id": "uuid:falso"})

    async def ws(self, req: web.Request) -> web.StreamResponse:
        self.conexoes.append(dict(req.query))
        if self.modo_ws == "401":
            return web.Response(status=401)
        w = web.WebSocketResponse()
        await w.prepare(req)
        if self.modo_ws == "negado":
            await w.send_str(json.dumps({"event": "ms.channel.unauthorized"}))
        elif self.modo_ws == "ok":
            data = {"id": "x"}
            if self.token_novo:
                data["token"] = self.token_novo
            await w.send_str(json.dumps({"event": "ms.channel.connect", "data": data}))
        async for msg in w:
            if msg.type != WSMsgType.TEXT:
                break
            f = json.loads(msg.data)
            self.frames.append(f)
            p = f.get("params", {})
            if p.get("DataOfCmd") == "KEY_POWER":
                self.power_state = "on" if self.power_state == "standby" else "standby"
        return w


@pytest.fixture
async def tv_falsa():
    tv = TvFalsa()
    app = web.Application()
    app.router.add_get("/api/v2/", tv.rest)
    app.router.add_get("/api/v2/channels/samsung.remote.control", tv.ws)
    srv = TestServer(app, host="127.0.0.1", port=0)
    await srv.start_server()
    tv.porta = srv.port
    yield tv
    await srv.close()


def porta_recusada() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Keyring:
    def __init__(self, valores: dict[str, str] | None = None) -> None:
        self.valores = dict(valores or {})

    def ler(self, nome: str) -> str | None:
        return self.valores.get(nome)

    def gravar(self, nome: str, valor: str) -> None:
        self.valores[nome] = valor


class Wol:
    def __init__(self, ao_enviar=None) -> None:
        self.envios: list[tuple] = []
        self.ao_enviar = ao_enviar

    def __call__(self, *macs: str, ip_address: str, port: int) -> None:
        self.envios.append((macs, ip_address, port))
        if self.ao_enviar:
            self.ao_enviar(len(self.envios))


def fazer(
    tv_falsa,
    relogio,
    tmp_path,
    *,
    ano=2021,
    mac=MAC,
    wss="servidor",
    rest="servidor",
    keyring=None,
    wol=None,
) -> SamsungDriver:
    tv = TvConfig(id="sala", nome="Sala", driver="samsung", ip="127.0.0.1", mac=mac, ano=ano)
    ctx = ContextoDriver(
        broadcast=BROADCAST,
        apps=casa_apps.carregar(),
        dir_pareamento=tmp_path / "pareamentos",
        relogio=relogio,
    )
    p_srv = tv_falsa.porta
    portas = {
        8002: p_srv if wss == "servidor" else porta_recusada(),
        8001: p_srv if rest == "servidor" and tv_falsa.rest_vivo else porta_recusada(),
    }
    kr = keyring or Keyring()
    return SamsungDriver(
        tv,
        ctx,
        portas=portas,
        tls=False,
        dormir=relogio.dormir,
        enviar_wol=wol or Wol(),
        ler_segredo=kr.ler,
        gravar_segredo=kr.gravar,
    )


# --- CA-Y40 ------------------------------------------------------------------------------------
async def test_ligar_em_standby_manda_key_power_e_confirma_pela_rest(tv_falsa, relogio, tmp_path):
    d = fazer(tv_falsa, relogio, tmp_path)
    try:
        res = await d.power(True)
    finally:
        await d.fechar()
    assert res.ok and res.estado is not None and res.estado.ligada is True
    assert tv_falsa.teclas() == ["KEY_POWER"]
    assert tv_falsa.conexoes[0]["name"] == base64.b64encode(b"Condessa").decode()


async def test_ligar_ja_ligada_nao_manda_nada(tv_falsa, relogio, tmp_path):
    tv_falsa.power_state = "on"
    d = fazer(tv_falsa, relogio, tmp_path)
    res = await d.power(True)
    await d.fechar()
    assert res.ok and tv_falsa.teclas() == []


async def test_8002_recusada_com_ano_2017_recai_para_8001(tv_falsa, relogio, tmp_path):
    # a 8001 lógica aponta para o servidor (REST e WS ws://); a 8002 recusa
    d = fazer(tv_falsa, relogio, tmp_path, ano=2017, wss="recusa")
    res = await d.key(Key.HOME)
    await d.fechar()
    assert res.ok, res
    assert d.porta_ws == 8001
    assert tv_falsa.teclas() == ["KEY_HOME"]


async def test_8002_recusada_com_ano_desconhecido_recai(tv_falsa, relogio, tmp_path):
    d = fazer(tv_falsa, relogio, tmp_path, ano=None, wss="recusa")
    res = await d.conectar()
    await d.fechar()
    assert res.ok and d.porta_ws == 8001


async def test_8002_recusada_com_ano_2021_nao_tenta_8001(tv_falsa, relogio, tmp_path):
    d = fazer(tv_falsa, relogio, tmp_path, ano=2021, wss="recusa")
    res = await d.key(Key.HOME)
    await d.fechar()
    assert not res.ok and res.motivo is Motivo.OFFLINE
    assert tv_falsa.conexoes == []


# --- CA-Y41 ------------------------------------------------------------------------------------
async def test_wol_tres_vezes_ao_broadcast_e_rede_desligada(tv_falsa, relogio, tmp_path):
    tv_falsa.rest_vivo = False
    wol = Wol()
    d = fazer(tv_falsa, relogio, tmp_path, wol=wol)
    t0 = relogio()
    res = await d.power(True)
    await d.fechar()
    assert wol.envios == [((MAC,), BROADCAST, 9)] * 3
    assert relogio.dormidas[:2] == [0.1, 0.1]
    assert not res.ok and res.motivo is Motivo.REDE_DESLIGADA
    assert relogio() - t0 <= 8.5
    assert tv_falsa.teclas() == []


async def test_wol_e_depois_standby_manda_key_power(tv_falsa, relogio, tmp_path):
    tv_falsa.rest_vivo = False

    def acorda(n: int) -> None:
        if n == 3:  # placa de rede acordou em standby
            d._portas[8001] = tv_falsa.porta

    d = fazer(tv_falsa, relogio, tmp_path, wol=Wol(acorda))
    res = await d.power(True)
    await d.fechar()
    assert res.ok and res.estado.ligada is True
    assert tv_falsa.teclas() == ["KEY_POWER"]


async def test_ligar_sem_resposta_e_sem_mac(tv_falsa, relogio, tmp_path):
    tv_falsa.rest_vivo = False
    wol = Wol()
    d = fazer(tv_falsa, relogio, tmp_path, mac="", wol=wol)
    res = await d.power(True)
    await d.fechar()
    assert res.motivo is Motivo.SEM_MAC and wol.envios == []


async def test_desligar_em_standby_nao_manda_key_power(tv_falsa, relogio, tmp_path):
    d = fazer(tv_falsa, relogio, tmp_path)
    res = await d.power(False)
    await d.fechar()
    assert res.ok and tv_falsa.teclas() == [] and tv_falsa.conexoes == []


async def test_desligar_ligada_manda_key_power_e_confirma(tv_falsa, relogio, tmp_path):
    tv_falsa.power_state = "on"
    d = fazer(tv_falsa, relogio, tmp_path)
    res = await d.power(False)
    await d.fechar()
    assert res.ok and res.estado.ligada is False
    assert tv_falsa.teclas() == ["KEY_POWER"]


async def test_desligar_sem_resposta_nao_manda_nada(tv_falsa, relogio, tmp_path):
    tv_falsa.rest_vivo = False
    d = fazer(tv_falsa, relogio, tmp_path)
    res = await d.power(False)
    await d.fechar()
    assert not res.ok and res.motivo is Motivo.OFFLINE and tv_falsa.conexoes == []


async def test_rest_sem_power_state_conta_como_ligada(tv_falsa, relogio, tmp_path):
    tv_falsa.power_state = None
    d = fazer(tv_falsa, relogio, tmp_path)
    est = await d.state()
    await d.fechar()
    assert est.online and est.ligada is True and est.driver == "samsung" and est.id == "sala"


async def test_estado_sem_resposta(tv_falsa, relogio, tmp_path):
    tv_falsa.rest_vivo = False
    d = fazer(tv_falsa, relogio, tmp_path)
    est = await d.state()
    await d.fechar()
    assert est.online is False and est.ligada is None


# --- acesso, erros ------------------------------------------------------------------------------
async def test_permitir_recusado_vira_acesso_negado(tv_falsa, relogio, tmp_path):
    tv_falsa.modo_ws = "negado"
    d = fazer(tv_falsa, relogio, tmp_path)
    res = await d.key(Key.OK)
    await d.fechar()
    assert res.motivo is Motivo.ACESSO_NEGADO and "Permitir" in res.detalhe


async def test_401_vira_acesso_negado(tv_falsa, relogio, tmp_path):
    tv_falsa.modo_ws = "401"
    d = fazer(tv_falsa, relogio, tmp_path)
    res = await d.conectar()
    await d.fechar()
    assert res.motivo is Motivo.ACESSO_NEGADO


async def test_tempo_esgotado_na_conexao(tv_falsa, relogio, tmp_path, monkeypatch):
    monkeypatch.setattr(samsung, "T_CONECTAR", 0.05)
    tv_falsa.modo_ws = "mudo"
    d = fazer(tv_falsa, relogio, tmp_path)
    res = await d.key(Key.OK)
    await d.fechar()
    assert res.motivo is Motivo.TEMPO_ESGOTADO


async def test_excecao_inesperada_vira_erro_driver(tv_falsa, relogio, tmp_path, monkeypatch, log_casa):
    d = fazer(tv_falsa, relogio, tmp_path)

    async def explode():
        raise RuntimeError("bug")

    monkeypatch.setattr(d, "_rest", explode)
    res = await d.power(True)
    est = await d.state()
    await d.fechar()
    assert res.motivo is Motivo.ERRO_DRIVER and est.online is False
    assert any(x["evento"] == "samsung_erro" for x in log_casa.linhas()) or "samsung_erro" in log_casa.texto


# --- token ---------------------------------------------------------------------------------------
async def test_token_novo_vai_ao_keyring_e_ao_arquivo_0600(tv_falsa, relogio, tmp_path, log_casa):
    tv_falsa.token_novo = "tok-segredo-123"
    kr = Keyring()
    d = fazer(tv_falsa, relogio, tmp_path, keyring=kr)
    assert (await d.conectar()).ok
    await d.fechar()
    assert kr.valores == {"casa.sala.samsung": "tok-segredo-123"}
    arq = tmp_path / "pareamentos" / "sala.samsung.token"
    assert arq.read_text() == "tok-segredo-123"
    assert stat.S_IMODE(arq.stat().st_mode) == 0o600
    assert "tok-segredo-123" not in log_casa.texto


async def test_keyring_ganha_do_arquivo(tv_falsa, relogio, tmp_path):
    (tmp_path / "pareamentos").mkdir()
    (tmp_path / "pareamentos" / "sala.samsung.token").write_text("do-arquivo")
    d = fazer(tv_falsa, relogio, tmp_path, keyring=Keyring({"casa.sala.samsung": "do-keyring"}))
    assert (await d.conectar()).ok
    await d.fechar()
    assert tv_falsa.conexoes[0]["token"] == "do-keyring"


async def test_sem_keyring_recai_no_arquivo(tv_falsa, relogio, tmp_path):
    (tmp_path / "pareamentos").mkdir()
    (tmp_path / "pareamentos" / "sala.samsung.token").write_text("do-arquivo\n")
    d = fazer(tv_falsa, relogio, tmp_path)
    assert (await d.conectar()).ok
    await d.fechar()
    assert tv_falsa.conexoes[0]["token"] == "do-arquivo"


async def test_token_nao_vai_na_8001(tv_falsa, relogio, tmp_path):
    d = fazer(
        tv_falsa, relogio, tmp_path, ano=2016, wss="recusa", keyring=Keyring({"casa.sala.samsung": "kk"})
    )
    assert (await d.conectar()).ok
    await d.fechar()
    assert "token" not in tv_falsa.conexoes[0]


# --- comandos ------------------------------------------------------------------------------------
async def test_comandos_mapeados(tv_falsa, relogio, tmp_path, log_casa):
    d = fazer(tv_falsa, relogio, tmp_path)
    assert (await d.input("hdmi2")).ok
    assert (await d.volume(step=-3)).ok
    assert (await d.channel(1)).ok
    assert (await d.mute(None)).ok
    assert (await d.key(Key.BACK)).ok
    assert (await d.app("netflix")).ok
    assert (await d.text("senha da wifi")).ok
    nao = [
        await d.input("tv"),
        await d.volume(set_to=20),
        await d.mute(True),
        await d.app("app-que-nao-existe"),
    ]
    await d.fechar()
    assert tv_falsa.teclas() == [
        "KEY_HDMI2",
        "KEY_VOLDOWN",
        "KEY_VOLDOWN",
        "KEY_VOLDOWN",
        "KEY_CHUP",
        "KEY_MUTE",
        "KEY_RETURN",
    ]
    launch = [f for f in tv_falsa.frames if f["params"].get("event") == "ed.apps.launch"]
    assert launch[0]["params"]["data"]["appId"] == "3201907018807"
    texto = [f for f in tv_falsa.frames if f["params"].get("TypeOfRemote") == "SendInputString"]
    assert base64.b64decode(texto[0]["params"]["Cmd"]).decode() == "senha da wifi"
    assert [r.motivo for r in nao] == [
        Motivo.ENTRADA_DESCONHECIDA,
        Motivo.NAO_SUPORTADO,
        Motivo.NAO_SUPORTADO,
        Motivo.APP_DESCONHECIDO,
    ]
    assert "senha da wifi" not in log_casa.texto
    assert len(tv_falsa.conexoes) == 1  # uma conexão reaproveitada


async def test_reconecta_se_a_conexao_caiu(tv_falsa, relogio, tmp_path):
    d = fazer(tv_falsa, relogio, tmp_path)
    assert (await d.key(Key.UP)).ok
    assert d._remote is not None and d._remote.connection is not None
    await d._remote.connection.close()
    assert (await d.key(Key.DOWN)).ok
    await d.fechar()
    assert tv_falsa.teclas() == ["KEY_UP", "KEY_DOWN"]
    assert len(tv_falsa.conexoes) == 2


def test_capacidades_e_fabrica_pelo_registro():
    ctx = ContextoDriver(apps=casa_apps.carregar())
    d = criar_driver(TvConfig(id="sala", nome="Sala", driver="samsung", ip="10.0.0.2"), ctx)
    assert isinstance(d, SamsungDriver) and d.nome == "samsung"
    c = d.capacidades
    assert c.pode(Cap.VOL_SET) and Cap.VOL_SET not in c.caps
    assert {Cap.POWER_ON, Cap.POWER_OFF, Cap.INPUT, Cap.APP, Cap.TEXT, Cap.STATE} <= c.caps
    assert c.entradas == ("hdmi1", "hdmi2", "hdmi3", "hdmi4")
    assert "netflix" in c.apps
