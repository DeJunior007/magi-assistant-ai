"""Descoberta e TCL (C1.5; CA-Y46, CA-Y47). Respostas SSDP/mDNS injetadas: nenhum socket multicast
(o fixture ``sem_udp`` falha qualquer socket UDP aberto no teste)."""

from __future__ import annotations

import os
import socket
import tomllib

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from magi.casa import config as cfg_mod
from magi.casa import descoberta
from magi.casa.config import CasaConfig
from magi.casa.descoberta import MDNS_ATV, ST_ROKU, ST_SAMSUNG, Anuncio, Candidato, Descobridor, SondasHttp
from magi.casa.driver import TvConfig
from magi.casa.falso import RelogioFalso

ROKU_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<device-info><serial-number>X00ROKU1</serial-number><model-name>TCL 4K</model-name>
<user-device-name>Roku Quarto</user-device-name><wifi-mac>b0:ee:7b:00:00:01</wifi-mac></device-info>"""
SAMSUNG_JSON = {
    "id": "uuid:abc",
    "device": {
        "type": "Samsung SmartTV",
        "id": "uuid:abc",
        "modelName": "QN55Q60",
        "name": "[TV] Sala",
        "wifiMac": "A4:30:7A:00:00:02",
    },
}


@pytest.fixture(autouse=True)
def sem_udp(monkeypatch):
    original = socket.socket

    class Guarda(original):
        def __init__(self, family=-1, type=-1, *a, **kw):  # noqa: A002
            if type != -1 and (type & socket.SOCK_DGRAM) and family in (socket.AF_INET, socket.AF_INET6):
                raise AssertionError("socket UDP (multicast?) aberto no teste")
            super().__init__(family, type, *a, **kw)

    monkeypatch.setattr(socket, "socket", Guarda)

    async def proibida(segundos):
        raise AssertionError("fonte real chamada no teste")

    monkeypatch.setattr(descoberta, "ssdp_real", proibida)
    monkeypatch.setattr(descoberta, "mdns_real", proibida)


class SondasFalsas:
    def __init__(self, roku=None, samsung=None, atv=(), arp=None):
        self.r, self.s, self.a, self.arp = roku or {}, samsung or {}, set(atv), arp or {}

    async def roku(self, ip):
        return self.r.get(ip)

    async def samsung(self, ip):
        return self.s.get(ip)

    async def abre_atv(self, ip):
        return ip in self.a

    def mac(self, ip):
        return self.arp.get(ip, "")


def fonte(*anuncios):
    async def f(segundos):
        return list(anuncios)

    return f


def roku_info(serial="X00ROKU1"):
    return {"serial-number": serial, "model-name": "TCL 4K", "user-device-name": "Roku Quarto"}


def tres_tvs(ip_roku="192.168.0.30"):
    ssdp = fonte(
        Anuncio("ssdp", ip_roku, ST_ROKU),
        Anuncio("ssdp", "192.168.0.40", ST_SAMSUNG[0]),
        Anuncio("ssdp", "192.168.0.40", ST_SAMSUNG[1]),
    )
    mdns = fonte(Anuncio("mdns", "192.168.0.52", MDNS_ATV, "Google TV Quarto"))
    sondas = SondasFalsas(
        roku={ip_roku: roku_info()},
        samsung={"192.168.0.40": SAMSUNG_JSON},
        atv={"192.168.0.52"},
        arp={"192.168.0.52": "9c:00:00:00:00:03"},
    )
    return Descobridor(ssdp=ssdp, mdns=mdns, sondas=sondas)


# --- CA-Y46 -----------------------------------------------------------------------------------
async def test_tres_tvs_viram_tres_candidatos_com_chave_certa():
    cfg = CasaConfig(
        tvs=(TvConfig(id="sala", nome="TV da sala", driver="samsung", chave="samsung:uuid:abc"),)
    )
    cands = await tres_tvs().descobrir(0.1, cfg)
    por = {c.driver: c for c in cands}
    assert set(por) == {"roku", "samsung", "androidtv"}
    assert por["roku"].chave == "roku:X00ROKU1" and por["roku"].ip == "192.168.0.30"
    assert por["samsung"].chave == "samsung:uuid:abc" and por["samsung"].mac == "a4:30:7a:00:00:02"
    assert por["samsung"].nomeada == "sala" and por["roku"].nomeada == ""
    assert por["androidtv"].chave == "androidtv:9c:00:00:00:00:03"
    assert por["androidtv"].nome == "Google TV Quarto"


async def test_mesma_chave_em_ip_novo_atualiza_casa_toml_atomico(monkeypatch):
    cfg = CasaConfig(
        padrao="quarto",
        tvs=(
            TvConfig(
                id="quarto", nome="TV do quarto", driver="roku", chave="roku:X00ROKU1", ip="192.168.0.9"
            ),
        ),
    )
    cfg_mod.salvar(cfg)
    trocas = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (trocas.append((str(a), str(b))), real(a, b))[1])
    cands = await tres_tvs("192.168.0.31").descobrir(0.1, cfg)
    novo = descoberta.revalidar(cfg, cands)
    assert novo.tv("quarto").ip == "192.168.0.31"
    p = cfg_mod.caminho_casa()
    assert trocas and trocas[-1][1] == str(p)
    dados = tomllib.loads(p.read_text())
    assert dados["tv"][0]["ip"] == "192.168.0.31"
    assert [x.name for x in p.parent.iterdir() if x.name.endswith(".tmp")] == []
    # sem mudança → mesmo objeto, nada gravado
    trocas.clear()
    assert descoberta.revalidar(novo, cands) is novo and trocas == []


async def test_revalidacao_periodica_relê_dorme_descoberta_min_e_avisa(log_casa):
    cfg_mod.salvar(
        CasaConfig(
            descoberta_min=7,
            tvs=(
                TvConfig(id="sala", nome="Sala", driver="samsung", chave="samsung:uuid:abc", ip="10.0.0.1"),
            ),
        )
    )
    rel = RelogioFalso()
    dormidas, mudancas = [], []

    async def dormir(s):
        dormidas.append(s)
        await rel.dormir(s)

    await descoberta.revalidar_periodicamente(tres_tvs(), dormir=dormir, ao_mudar=mudancas.append, voltas=2)
    assert dormidas == [420.0, 420.0]
    assert len(mudancas) == 1 and mudancas[0].tv("sala").ip == "192.168.0.40"
    assert cfg_mod.ler().tv("sala").ip == "192.168.0.40"
    assert any(x["evento"] == "ip_atualizado" for x in log_casa.linhas())


async def test_samsung_que_nao_confirma_fica_de_fora():
    falso = {"device": {"type": "Outro", "id": "x"}}
    d = Descobridor(
        ssdp=fonte(Anuncio("ssdp", "10.0.0.5", ST_SAMSUNG[1])),
        mdns=fonte(),
        sondas=SondasFalsas(samsung={"10.0.0.5": falso}),
    )
    assert await d.descobrir(0.1) == []


async def test_fonte_com_defeito_nao_derruba_a_outra(log_casa):
    async def quebra(s):
        raise OSError("sem rede")

    d = Descobridor(
        ssdp=quebra,
        mdns=fonte(Anuncio("mdns", "10.0.0.6", MDNS_ATV, "TV")),
        sondas=SondasFalsas(atv={"10.0.0.6"}),
    )
    cands = await d.descobrir(0.1)
    assert [c.driver for c in cands] == ["androidtv"] and cands[0].chave == "androidtv:TV"
    assert any(x["evento"] == "descoberta_fonte_falhou" for x in log_casa.linhas())


# --- CA-Y47 -----------------------------------------------------------------------------------
async def test_tcl_com_8060_e_mdns_vira_androidtv_e_loga(log_casa):
    ip = "192.168.0.60"
    d = Descobridor(
        ssdp=fonte(Anuncio("ssdp", ip, ST_ROKU)),
        mdns=fonte(Anuncio("mdns", ip, MDNS_ATV, "TCL")),
        sondas=SondasFalsas(roku={ip: roku_info()}, arp={ip: "11:22:33:44:55:66"}),
    )
    cands = await d.descobrir(0.1)
    assert [(c.driver, c.chave) for c in cands] == [("androidtv", "androidtv:11:22:33:44:55:66")]
    assert any(x["evento"] == "tcl_dois_protocolos" for x in log_casa.linhas())


async def test_tcl_so_8060_vira_roku(log_casa):
    ip = "192.168.0.61"
    d = Descobridor(
        ssdp=fonte(Anuncio("ssdp", ip, ST_ROKU)), mdns=fonte(), sondas=SondasFalsas(roku={ip: roku_info()})
    )
    cands = await d.descobrir(0.1)
    assert [(c.driver, c.chave) for c in cands] == [("roku", "roku:X00ROKU1")]
    assert not any(x["evento"] == "tcl_dois_protocolos" for x in log_casa.linhas())


async def test_tcl_8060_e_6466_aberta_sem_mdns_vira_androidtv():
    ip = "192.168.0.62"
    d = Descobridor(
        ssdp=fonte(Anuncio("ssdp", ip, ST_ROKU)),
        mdns=fonte(),
        sondas=SondasFalsas(roku={ip: roku_info()}, atv={ip}),
    )
    assert [c.driver for c in await d.descobrir(0.1)] == ["androidtv"]


# --- confirmação por HTTP (servidor falso em 127.0.0.1:0) ---------------------------------------
async def test_sondas_http_confirmam_roku_samsung_e_arp(tmp_path):
    async def info(req):
        return web.Response(text=ROKU_XML, content_type="text/xml")

    async def api(req):
        return web.json_response(SAMSUNG_JSON)

    app = web.Application()
    app.router.add_get("/query/device-info", info)
    app.router.add_get("/api/v2/", api)
    srv = TestServer(app, host="127.0.0.1", port=0)
    await srv.start_server()
    arp = tmp_path / "arp"
    arp.write_text(
        "IP address       HW type     Flags       HW address            Mask     Device\n"
        "127.0.0.1        0x1         0x2         de:ad:be:ef:00:01     *        lo\n"
    )
    try:
        s = SondasHttp(portas={8060: srv.port, 8001: srv.port, 6466: srv.port}, arp=arp, timeout=1.0)
        assert (await s.roku("127.0.0.1"))["serial-number"] == "X00ROKU1"
        assert (await s.samsung("127.0.0.1"))["device"]["type"] == "Samsung SmartTV"
        assert await s.abre_atv("127.0.0.1") is True
        assert s.mac("127.0.0.1") == "de:ad:be:ef:00:01"
        assert s.mac("10.9.9.9") == ""
    finally:
        await srv.close()


def test_cache_de_descobertas_ida_e_volta():
    c = [Candidato("roku:1", "roku", "10.0.0.2", modelo="R")]
    descoberta.gravar_descobertas(c)
    assert descoberta.ler_descobertas() == c


async def test_servir_liga_estados_do_executor_a_sondagem():
    from magi.casa.driver import Cap, Capacidades
    from magi.casa.estado import EstadoCasa
    from magi.casa.falso import DriverFalso
    from magi.casa.servir import _ligar_estados

    drv = DriverFalso(Capacidades(caps=frozenset({Cap.STATE})), tv_id="sala", tv_nome="Sala")
    est = EstadoCasa({"sala": drv}, {"sala": ("Sala", "falso")}, gravar_arquivo=False)

    class Ex:
        estados: dict = {}

    ex = Ex()
    ex.estados = {}
    _ligar_estados(ex, est)
    assert ex.estados["sala"].online is False
    await est.sondar("sala")
    assert ex.estados["sala"].online is True
