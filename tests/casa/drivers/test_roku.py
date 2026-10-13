"""C1.3 — driver Roku contra um servidor ECP falso em 127.0.0.1:0 (CA-Y42, CA-Y43). Sem Roku real."""

from __future__ import annotations

import logging

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from magi.casa.apps import AppCatalogo, AppEntrada
from magi.casa.driver import Cap, ContextoDriver, Key, Motivo, TvConfig
from magi.casa.drivers import criar_driver
from magi.casa.drivers.roku import DICA_ACESSO, RokuDriver
from magi.casa.falso import RelogioFalso


def _info(is_tv: bool, power_ctl: bool = False, modo: str = "PowerOn") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" ?><device-info>'
        f"<is-tv>{str(is_tv).lower()}</is-tv>"
        f"<supports-tv-power-control>{str(power_ctl).lower()}</supports-tv-power-control>"
        f"<power-mode>{modo}</power-mode></device-info>"
    )


APPS_XML = (
    '<?xml version="1.0" encoding="UTF-8" ?><apps>'
    '<app id="12" type="appl" version="1">Netflix</app>'
    '<app id="2213" type="appl" version="1">Roku Media Player</app>'
    '<app id="593099" type="appl" version="1">Apple TV</app></apps>'
)


class RokuFalso:
    def __init__(self) -> None:
        self.is_tv = True
        self.power_ctl = True
        self.modo = "PowerOn"
        self.posts: list[str] = []
        self.gets: list[str] = []
        self.status_post = 200
        self.liga_com_poweron = True
        self.app_ativo = '<app id="12" type="appl" version="1">Netflix</app>'

    def app(self) -> web.Application:
        a = web.Application()
        a.router.add_get("/query/device-info", self._device_info)
        a.router.add_get("/query/apps", self._apps)
        a.router.add_get("/query/active-app", self._ativo)
        a.router.add_post("/{rest:.*}", self._post)
        return a

    async def _device_info(self, req: web.Request) -> web.Response:
        self.gets.append(req.path)
        return web.Response(text=_info(self.is_tv, self.power_ctl, self.modo), content_type="text/xml")

    async def _apps(self, req: web.Request) -> web.Response:
        self.gets.append(req.path)
        return web.Response(text=APPS_XML, content_type="text/xml")

    async def _ativo(self, req: web.Request) -> web.Response:
        self.gets.append(req.path)
        x = f'<?xml version="1.0" encoding="UTF-8" ?><active-app>{self.app_ativo}</active-app>'
        return web.Response(text=x, content_type="text/xml")

    async def _post(self, req: web.Request) -> web.Response:
        self.posts.append(req.raw_path)
        if self.status_post != 200:
            return web.Response(status=self.status_post, text="Forbidden")
        if req.raw_path == "/keypress/PowerOn" and self.liga_com_poweron:
            self.modo = "PowerOn"
        if req.raw_path == "/keypress/PowerOff":
            self.modo = "DisplayOff"
        return web.Response(text="")


@pytest.fixture
async def roku():
    falso = RokuFalso()
    srv = TestServer(falso.app(), host="127.0.0.1", port=0)
    await srv.start_server()
    falso.porta = srv.port
    yield falso
    await srv.close()


CATALOGO = AppCatalogo(
    [
        AppEntrada("netflix", "Netflix", roku="12"),
        AppEntrada("plex", "Plex"),
        AppEntrada("appletv", "Apple TV", apelidos=("apple",)),
    ]
)


def _driver(roku: RokuFalso, relogio: RelogioFalso, *, mac: str = "", ip: str = "127.0.0.1", wol=None):
    tv = TvConfig(id="sala", nome="Sala", driver="roku", ip=ip, mac=mac)
    ctx = ContextoDriver(apps=CATALOGO, relogio=relogio, broadcast="10.0.0.255")
    return RokuDriver(tv, ctx, porta=getattr(roku, "porta", 9), dormir=relogio.dormir, wol=wol)


# --- CA-Y42 --------------------------------------------------------------------------------------
async def test_player_sem_vol_nem_input(roku, relogio):
    roku.is_tv, roku.power_ctl = False, False
    d = _driver(roku, relogio)
    r = await d.conectar()
    assert r.ok and r.estado is not None and r.estado.ligada is True
    caps = d.capacidades.caps
    assert caps == {Cap.KEY, Cap.APP, Cap.TEXT, Cap.STATE}
    assert Cap.VOL_STEP not in caps and Cap.INPUT not in caps
    assert (await d.volume(step=1)).motivo is Motivo.NAO_SUPORTADO
    assert (await d.input("hdmi1")).motivo is Motivo.NAO_SUPORTADO
    assert (await d.power(True)).motivo is Motivo.NAO_SUPORTADO
    assert roku.posts == []
    await d.fechar()


async def test_player_com_power_control(roku, relogio):
    roku.is_tv, roku.power_ctl = False, True
    d = _driver(roku, relogio)
    await d.conectar()
    assert {Cap.POWER_ON, Cap.POWER_OFF} <= d.capacidades.caps
    assert Cap.VOL_STEP not in d.capacidades.caps
    await d.fechar()


async def test_roku_tv_caps_completas_e_teclas(roku, relogio):
    d = _driver(roku, relogio)
    await d.conectar()
    c = d.capacidades
    assert c.caps >= {
        Cap.POWER_ON,
        Cap.POWER_OFF,
        Cap.VOL_STEP,
        Cap.MUTE,
        Cap.CHANNEL,
        Cap.INPUT,
        Cap.KEY,
        Cap.APP,
        Cap.TEXT,
        Cap.STATE,
    }
    assert c.pode(Cap.VOL_SET) and Cap.VOL_SET not in c.caps
    assert "hdmi2" in c.entradas and "netflix" in c.apps
    assert (await d.volume(step=-2)).ok
    assert (await d.mute(None)).ok
    assert (await d.mute(True)).motivo is Motivo.NAO_SUPORTADO
    assert (await d.channel(1)).ok
    assert (await d.input("hdmi2")).ok
    assert (await d.input("hdmi9")).motivo is Motivo.ENTRADA_DESCONHECIDA
    assert (await d.key(Key.OK)).ok
    assert (await d.volume(set_to=10)).motivo is Motivo.NAO_SUPORTADO
    assert roku.posts == [
        "/keypress/VolumeDown",
        "/keypress/VolumeDown",
        "/keypress/VolumeMute",
        "/keypress/ChannelUp",
        "/keypress/InputHDMI2",
        "/keypress/Select",
    ]
    await d.fechar()


async def test_keypress_403_acesso_negado_com_dica(roku, relogio):
    d = _driver(roku, relogio)
    await d.conectar()
    roku.status_post = 403
    r = await d.key(Key.HOME)
    assert r.ok is False and r.motivo is Motivo.ACESSO_NEGADO
    assert "Acesso à rede" in r.detalhe and r.detalhe == DICA_ACESSO
    r = await d.app("netflix")
    assert r.motivo is Motivo.ACESSO_NEGADO
    r = await d.power(True)
    assert r.motivo is Motivo.ACESSO_NEGADO
    await d.fechar()


async def test_app_com_id_do_catalogo_nao_busca(roku, relogio):
    d = _driver(roku, relogio)
    await d.conectar()
    assert (await d.app("netflix")).ok
    assert roku.posts == ["/launch/12"]
    assert "/query/apps" not in roku.gets
    await d.fechar()


async def test_app_sem_id_busca_por_nome_com_cache_24h(roku, relogio):
    d = _driver(roku, relogio)
    await d.conectar()
    assert (await d.app("appletv")).ok
    assert (await d.app("appletv")).ok
    assert roku.gets.count("/query/apps") == 1
    relogio.avancar(23 * 3600)
    assert (await d.app("appletv")).ok
    assert roku.gets.count("/query/apps") == 1
    relogio.avancar(3600 + 1)
    assert (await d.app("appletv")).ok
    assert roku.gets.count("/query/apps") == 2
    assert roku.posts == ["/launch/593099"] * 4
    r = await d.app("plex")
    assert r.ok is False and r.motivo is Motivo.APP_DESCONHECIDO
    await d.fechar()


# --- CA-Y43 --------------------------------------------------------------------------------------
async def test_text_lit_por_caractere_em_ordem(roku, relogio):
    d = _driver(roku, relogio)
    await d.conectar()
    r = await d.text("ab c")
    assert r.ok
    assert roku.posts == ["/keypress/Lit_a", "/keypress/Lit_b", "/keypress/Lit_%20", "/keypress/Lit_c"]
    assert relogio.dormidas == [0.03, 0.03, 0.03]
    await d.fechar()


async def test_text_acima_de_100_corta_e_loga_so_tamanho(roku, relogio, log_casa, caplog):
    caplog.set_level(logging.DEBUG)
    segredo = "zqxsecreto" * 15  # 150 caracteres
    d = _driver(roku, relogio)
    await d.conectar()
    r = await d.text(segredo)
    assert r.ok
    assert len(roku.posts) == 100
    linhas = [x for x in log_casa.linhas() if x.get("evento") == "roku_texto_cortado"]
    assert linhas and linhas[0]["tamanho"] == 150
    assert "zqxsecreto" not in log_casa.texto
    assert "zqxsecreto" not in caplog.text
    await d.fechar()


# --- ligar / estado / rede ----------------------------------------------------------------------
async def test_ligar_poweron_confirma_estado(roku, relogio):
    roku.modo = "DisplayOff"
    d = _driver(roku, relogio)
    await d.conectar()
    r = await d.power(True)
    assert r.ok and r.estado is not None and r.estado.ligada is True
    assert roku.posts == ["/keypress/PowerOn"]
    r = await d.power(False)
    assert r.ok and r.estado.ligada is False
    await d.fechar()


async def test_ligar_sem_confirmar_standby_profundo(roku, relogio):
    roku.modo, roku.liga_com_poweron = "Ready", False
    d = _driver(roku, relogio)
    await d.conectar()
    r = await d.power(True)
    assert r.ok is False and r.motivo is Motivo.STANDBY_PROFUNDO
    assert "Início rápido" in r.detalhe
    await d.fechar()


async def test_ligar_sem_resposta_wol_e_repete(roku, relogio):
    pacotes = []
    d = _driver(
        roku,
        relogio,
        mac="aa:bb:cc:dd:ee:ff",
        wol=lambda *m, ip_address, port: pacotes.append((m, ip_address, port)),
    )
    await d.conectar()
    porta_boa = roku.porta
    d._porta = 1  # nada escuta na porta 1: primeira tentativa falha
    d._roku = None
    orig = d._req
    chamadas = {"n": 0}

    async def req(uri, method="GET"):
        chamadas["n"] += 1
        if chamadas["n"] > 1 and d._porta == 1:
            d._porta, d._roku = porta_boa, None
        return await orig(uri, method)

    d._req = req
    roku.modo = "DisplayOff"
    r = await d.power(True)
    assert r.ok
    assert pacotes == [(("aa:bb:cc:dd:ee:ff",), "10.0.0.255", 9)]
    assert roku.posts == ["/keypress/PowerOn"]
    await d.fechar()


async def test_ligar_sem_resposta_sem_mac(relogio):
    tv = TvConfig(id="sala", nome="Sala", driver="roku", ip="127.0.0.1")
    d = RokuDriver(tv, ContextoDriver(relogio=relogio), porta=1, dormir=relogio.dormir)
    d.capacidades = type(d.capacidades)(frozenset({Cap.POWER_ON}))
    r = await d.power(True)
    assert r.motivo is Motivo.SEM_MAC
    await d.fechar()


async def test_offline_nao_levanta(relogio):
    tv = TvConfig(id="sala", nome="Sala", driver="roku", ip="127.0.0.1")
    d = RokuDriver(tv, ContextoDriver(relogio=relogio), porta=1, dormir=relogio.dormir)
    r = await d.conectar()
    assert r.ok is False and r.motivo is Motivo.OFFLINE
    est = await d.state()
    assert est.online is False and est.driver == "roku"
    assert (await d.key(Key.HOME)).motivo is Motivo.OFFLINE
    await d.fechar()


async def test_state_ligada_e_app_do_catalogo(roku, relogio):
    d = _driver(roku, relogio)
    est = await d.state()
    assert est.online and est.ligada is True and est.app == "netflix"
    roku.modo, roku.app_ativo = "Headless", "<app>Roku</app>"
    est = await d.state()
    assert est.ligada is False and est.app is None
    await d.fechar()


def test_registro_cria_o_driver_roku():
    tv = TvConfig(id="sala", nome="Sala", driver="roku", ip="10.0.0.5")
    d = criar_driver(tv, ContextoDriver())
    assert isinstance(d, RokuDriver) and d.nome == "roku"
