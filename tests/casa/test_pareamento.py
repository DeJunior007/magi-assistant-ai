# ruff: noqa: F811 - fixtures importadas de outros módulos de teste
"""Pareamento por driver, ``esquecer`` e CLI ``descobrir``/``nomear``/``parear`` (C1.5; CA-Y48).

Nunca TV real: Samsung contra a WS falsa da C1.2 em ``127.0.0.1:0``, Android TV com o
``AndroidTVRemote`` falso da C1.4, Roku com sondas falsas; o código do ``parear`` vem de entrada
simulada (no lugar do ``getpass``)."""

from __future__ import annotations

import functools
import stat
import tomllib

import pytest

from magi.casa import cli, pareamento, servir
from magi.casa import config as cfg_mod
from magi.casa.config import CasaConfig
from magi.casa.descoberta import MDNS_ATV, ST_ROKU, ST_SAMSUNG, Anuncio, Descobridor
from magi.casa.driver import Cap, Capacidades, ContextoDriver, Motivo, TvConfig
from magi.casa.drivers.androidtv import caminhos_cert
from magi.casa.falso import DriverFalso
from tests.casa.drivers.test_androidtv import RemotoFalso, _gerar_falso
from tests.casa.drivers.test_samsung import Keyring, fazer, tv_falsa  # noqa: F401 - fixture
from tests.casa.test_descoberta import SAMSUNG_JSON, SondasFalsas, fonte, roku_info, sem_udp  # noqa: F401

TODAS = Capacidades(caps=frozenset(Cap), entradas=("hdmi1", "hdmi2"), apps=("netflix",))


def _modo(p) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def _tv(driver="androidtv", tv_id="sala", ip="127.0.0.1"):
    return TvConfig(id=tv_id, nome=f"TV {tv_id}", driver=driver, ip=ip)


# --- Samsung ---------------------------------------------------------------------------------
async def test_samsung_token_vai_ao_keyring_e_ao_arquivo_0600(tv_falsa, relogio, tmp_path, log_casa):
    tv_falsa.token_novo = "tok-pareado-999"
    kr = Keyring()
    drv = fazer(tv_falsa, relogio, tmp_path, keyring=kr)
    res = await pareamento.parear(drv.tv, drv.ctx, None, driver_samsung=drv, prazo_s=2.0)
    assert res.ok
    assert kr.valores == {"casa.sala.samsung": "tok-pareado-999"}
    arq = tmp_path / "pareamentos" / "sala.samsung.token"
    assert arq.read_text() == "tok-pareado-999" and _modo(arq) == 0o600
    assert _modo(tmp_path / "pareamentos") == 0o700
    assert tv_falsa.conexoes[0].get("token") is None  # abriu sem token ("Permitir" na TV)
    assert "tok-pareado-999" not in log_casa.texto


async def test_samsung_recusado_vira_acesso_negado_sem_gravar(tv_falsa, relogio, tmp_path):
    tv_falsa.modo_ws = "negado"
    kr = Keyring()
    drv = fazer(tv_falsa, relogio, tmp_path, keyring=kr)
    res = await pareamento.parear_samsung(drv.tv, drv.ctx, driver=drv, prazo_s=2.0)
    assert res.motivo is Motivo.ACESSO_NEGADO and kr.valores == {}
    assert not (tmp_path / "pareamentos" / "sala.samsung.token").exists()


async def test_samsung_sem_resposta_no_prazo_vira_tempo_esgotado(tv_falsa, relogio, tmp_path):
    tv_falsa.modo_ws = "mudo"
    drv = fazer(tv_falsa, relogio, tmp_path)
    res = await pareamento.parear_samsung(drv.tv, drv.ctx, driver=drv, prazo_s=0.05)
    assert res.motivo is Motivo.TEMPO_ESGOTADO


# --- Android TV ------------------------------------------------------------------------------
async def test_androidtv_codigo_errado_3x_aborta_sem_gravar(tmp_path, log_casa):
    d = tmp_path / "par"
    r = RemotoFalso()

    async def errado() -> str:
        return "ffffff"

    res = await pareamento.parear(
        _tv(),
        ContextoDriver(dir_pareamento=d),
        errado,
        fabrica_atv=lambda c, k, h: r,
        gerar_cert=_gerar_falso,
    )
    assert res.motivo is Motivo.ACESSO_NEGADO and r.pareamentos == 3
    assert list(d.iterdir()) == []
    assert "ffffff" not in log_casa.texto


async def test_androidtv_codigo_certo_grava_crt_key_0600(tmp_path):
    d = tmp_path / "par"
    res = await pareamento.parear(
        _tv(),
        ContextoDriver(dir_pareamento=d),
        _codigo("A1B2C3"),
        fabrica_atv=lambda c, k, h: RemotoFalso(),
        gerar_cert=_gerar_falso,
    )
    crt, key = caminhos_cert("sala", d)
    assert res.ok and _modo(crt) == 0o600 and _modo(key) == 0o600 and _modo(d) == 0o700


def _codigo(c):
    async def f() -> str:
        return c

    return f


# --- Roku ------------------------------------------------------------------------------------
async def test_roku_so_le_device_info(tmp_path):
    ctx = ContextoDriver(dir_pareamento=tmp_path / "p")
    ok = await pareamento.parear(
        _tv("roku", ip="10.0.0.3"), ctx, None, sondas=SondasFalsas(roku={"10.0.0.3": {}})
    )
    fora = await pareamento.parear(_tv("roku", ip="10.0.0.4"), ctx, None, sondas=SondasFalsas())
    assert ok.ok and fora.motivo is Motivo.OFFLINE


# --- arquivo aberto na subida ------------------------------------------------------------------
async def test_arquivo_0644_na_subida_recusa_com_permissao_aberta(log_casa):
    d = pareamento.preparar_dir()
    (d / "sala.samsung.token").write_text("x")
    (d / "sala.samsung.token").chmod(0o644)
    assert await servir.servir_async(cfg=CasaConfig(), porta=0) == 1
    assert any(x["evento"] == "permissao_aberta" for x in log_casa.linhas())


# --- esquecer ----------------------------------------------------------------------------------
def test_esquecer_apaga_token_cert_keyring_e_entrada(capsys):
    cfg_mod.salvar(
        CasaConfig(padrao="sala", tvs=(_tv("samsung"), _tv("roku", tv_id="quarto", ip="10.0.0.3")))
    )
    d = pareamento.preparar_dir()
    for n in ("sala.samsung.token", "sala.atv.crt", "sala.atv.key"):
        (d / n).write_text("x")
    kr = Keyring({"casa.sala.samsung": "t"})

    def apagar(nome):
        return kr.valores.pop(nome, None) is not None

    assert cli.esquecer(["TV sala"], apagar_segredo=apagar) == 0
    assert list(d.iterdir()) == [] and kr.valores == {}
    cfg = cfg_mod.ler()
    assert [t.id for t in cfg.tvs] == ["quarto"] and cfg.padrao == ""
    assert "casa.toml" in capsys.readouterr().out


# --- CLI descobrir → nomear → parear -----------------------------------------------------------
def _descobridor():
    return Descobridor(
        ssdp=fonte(Anuncio("ssdp", "10.0.0.40", ST_SAMSUNG[0]), Anuncio("ssdp", "10.0.0.52", ST_ROKU)),
        mdns=fonte(Anuncio("mdns", "10.0.0.52", MDNS_ATV, "TCL")),
        sondas=SondasFalsas(
            roku={"10.0.0.52": roku_info()},
            samsung={"10.0.0.40": SAMSUNG_JSON},
            arp={"10.0.0.52": "9c:00:00:00:00:52"},
        ),
    )


def test_cli_descobrir_nomear_e_driver_forcado(capsys):
    assert cli.descobrir(["--segundos", "0.1"], descobridor=_descobridor()) == 0
    saida = capsys.readouterr().out
    assert "samsung:uuid:abc" in saida and "androidtv:9c:00:00:00:00:52" in saida and "já nomeada?" in saida
    assert cli.nomear(["samsung:uuid:abc", "sala", "TV da sala", "--padrao", "--apelido", "tv grande"]) == 0
    assert cli.nomear(["10.0.0.52", "quarto", "--driver", "roku"]) == 0
    dados = tomllib.loads(cfg_mod.caminho_casa().read_text())
    assert dados["casa"]["padrao"] == "sala"
    sala, quarto = dados["tv"]
    assert (sala["driver"], sala["ip"], sala["mac"], sala["apelidos"]) == (
        "samsung",
        "10.0.0.40",
        "a4:30:7a:00:00:02",
        ["tv grande"],
    )
    assert (quarto["driver"], quarto["chave"], quarto["nome"]) == (
        "roku",
        "androidtv:9c:00:00:00:00:52",
        "quarto",
    )
    # a próxima descoberta mostra as duas como nomeadas
    cli.descobrir([], descobridor=_descobridor())
    assert "não" not in capsys.readouterr().out.split("já nomeada?")[1]


def test_cli_nomear_sem_descoberta_avisa(capsys):
    assert cli.nomear(["1", "sala"]) == 2
    assert "descobrir" in capsys.readouterr().err


def test_cli_parear_androidtv_com_codigo_simulado(capsys):
    cfg_mod.salvar(CasaConfig(tvs=(_tv("androidtv", "quarto"),)))
    lidos = []

    def ler_codigo(prompt):
        lidos.append(prompt)
        return "A1B2C3"

    par = functools.partial(
        pareamento.parear, fabrica_atv=lambda c, k, h: RemotoFalso(), gerar_cert=_gerar_falso
    )
    assert cli.parear(["TV quarto"], pareador=par, ler_codigo=ler_codigo) == 0
    assert lidos == ["Código mostrado na TV: "]
    crt, key = caminhos_cert("quarto")
    assert _modo(crt) == 0o600 and _modo(key) == 0o600
    out = capsys.readouterr()
    assert "pareada" in out.out and "A1B2C3" not in out.out + out.err


def test_cli_parear_tv_inexistente(capsys):
    assert cli.parear(["nada"]) == 2


def test_cli_testar_e_estado_com_driver_falso(capsys):
    cfg_mod.salvar(CasaConfig(tvs=(_tv("roku", "quarto"),)))
    drv = DriverFalso(TODAS)
    assert cli.testar(["quarto", "volume", "volume=+2"], fabrica_driver=lambda t, c: drv) == 0
    assert "ok=True" in capsys.readouterr().out
    assert drv.de("volume")
    assert cli.estado(["--sondar"], fabrica_driver=lambda t, c: DriverFalso(TODAS, tv_id=t.id)) == 0
    assert "quarto" in capsys.readouterr().out
    assert cli.testar(["quarto", "volume", "xx"]) == 2


@pytest.mark.parametrize("sub", ["descobrir", "nomear", "parear", "esquecer", "estado", "testar"])
def test_subcomandos_tem_ajuda(sub, capsys):
    with pytest.raises(SystemExit) as e:
        getattr(cli, sub)(["--help"])
    assert e.value.code == 0
