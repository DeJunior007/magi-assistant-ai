"""Contrato da casa (CA-Y30, parte do contrato): ``Capacidades.pode``, ``ResTv``, ``DriverFalso``,
registro preguiçoso, log sem segredo e a entrada ``magi-casa``."""

from __future__ import annotations

import subprocess
import sys

import pytest

from magi.casa import drivers
from magi.casa.driver import (
    Cap,
    Capacidades,
    ContextoDriver,
    Key,
    Motivo,
    ResTv,
    TvConfig,
    TvDriver,
    cap_necessaria,
)
from magi.casa.falso import DriverFalso, RelogioFalso
from magi.elo.mensagens import EstadoTv

# (método, kwargs, cap exigida) — os 11 métodos com cap do TvDriver
CHAMADAS = [
    ("power", {"on": True}, Cap.POWER_ON),
    ("power", {"on": False}, Cap.POWER_OFF),
    ("volume", {"step": 3}, Cap.VOL_STEP),
    ("volume", {"set_to": 20}, Cap.VOL_SET),
    ("mute", {"on": None}, Cap.MUTE),
    ("channel", {"step": 1}, Cap.CHANNEL),
    ("input", {"nome": "hdmi2"}, Cap.INPUT),
    ("app", {"app_id": "netflix"}, Cap.APP),
    ("key", {"key": Key.OK}, Cap.KEY),
    ("text", {"s": "duna"}, Cap.TEXT),
]


def test_capacidades_pode_com_caps_e_emula():
    c = Capacidades(caps=frozenset({Cap.VOL_STEP, Cap.KEY}), emula=frozenset({Cap.VOL_SET}))
    assert c.pode(Cap.VOL_STEP) and c.pode(Cap.KEY)
    assert c.pode(Cap.VOL_SET)  # emulada
    assert not c.pode(Cap.TEXT)
    assert c.anunciadas() == ("vol_step", "vol_set", "key")  # ordem da Cap, já com as emuladas
    assert Capacidades(caps=frozenset()).vol_max == 100


def test_restv_padroes_e_imutavel():
    r = ResTv(True)
    assert (r.ok, r.motivo, r.detalhe, r.emulado, r.estado) == (True, None, "", False, None)
    with pytest.raises(AttributeError):
        r.ok = False  # type: ignore[misc]
    assert Motivo.NAO_SUPORTADO.value == "nao_suportado"
    assert len(Cap) == 11 and len(Motivo) == 16 and len(Key) == 17


def test_cap_necessaria_por_metodo():
    for metodo, kw, cap in CHAMADAS:
        sel = {k: v for k, v in kw.items() if k in ("on", "step", "set_to")}
        assert cap_necessaria(metodo, **sel) == cap
    assert cap_necessaria("state") is Cap.STATE
    assert cap_necessaria("conectar") is None


@pytest.mark.parametrize(("metodo", "kw", "cap"), CHAMADAS)
async def test_driver_sem_cap_responde_nao_suportado_sem_consultar_script(metodo, kw, cap):
    chamado = []
    drv = DriverFalso(
        Capacidades(caps=frozenset(set(Cap) - {cap}), emula=frozenset({cap})),
        {metodo: lambda c: chamado.append(c) or ResTv(True)},
    )
    r = await getattr(drv, metodo)(**kw)
    assert r.ok is False and r.motivo is Motivo.NAO_SUPORTADO
    assert chamado == []  # driver não emula, mesmo com a cap em ``emula``
    assert drv.metodos() == [metodo]


@pytest.mark.parametrize(("metodo", "kw", "cap"), CHAMADAS)
async def test_driver_com_cap_responde_do_script(metodo, kw, cap):
    falha = ResTv(False, Motivo.OFFLINE, "sem resposta")
    drv = DriverFalso(Capacidades(caps=frozenset({cap})), {metodo: falha})
    assert await getattr(drv, metodo)(**kw) is falha
    assert kw.items() <= drv.de(metodo)[0].args.items()


async def test_falso_sequencia_excecao_async_e_relogio(relogio: RelogioFalso):
    caps = Capacidades(caps=frozenset(Cap))

    async def tarde(chamada):
        await relogio.dormir(0.08)
        return ResTv(True, detalhe=f"t={chamada.t}")

    drv = DriverFalso(
        caps,
        {
            "key": [ResTv(True), ResTv(False, Motivo.TEMPO_ESGOTADO)],
            "power": TimeoutError("rede"),
            "app": tarde,
            "state": EstadoTv(id="sala", nome="TV da sala", driver="falso", online=True, volume=30),
        },
        relogio=relogio,
    )
    assert (await drv.key(Key.UP)).ok
    relogio.avancar(0.5)
    assert (await drv.key(Key.UP)).motivo is Motivo.TEMPO_ESGOTADO
    assert (await drv.key(Key.UP)).motivo is Motivo.TEMPO_ESGOTADO  # a última se repete
    with pytest.raises(TimeoutError):
        await drv.power(True)
    assert (await drv.app("netflix")).detalhe == "t=1000.5"
    assert relogio() == pytest.approx(1000.58)
    assert (await drv.state()).volume == 30
    assert [c.t for c in drv.de("key")] == [1000.0, 1000.5, 1000.5]
    assert (await drv.conectar()).ok and await drv.fechar() is None
    assert isinstance(drv, TvDriver)


async def test_registro_preguicoso_modulo_ausente_nao_suportado(monkeypatch):
    monkeypatch.setitem(drivers.DRIVERS, "samsung", drivers.Registro("magi.casa.drivers._nao_existe", "C1.2"))
    tv = TvConfig(id="sala", nome="TV da sala", driver="samsung")
    drv = drivers.criar_driver(tv, ContextoDriver())
    assert isinstance(drv, TvDriver)
    for metodo, kw, _cap in CHAMADAS:
        r = await getattr(drv, metodo)(**kw)
        assert r.motivo is Motivo.NAO_SUPORTADO and "dono: C1.2" in r.detalhe
    assert (await drv.conectar()).motivo is Motivo.NAO_SUPORTADO
    assert (await drv.state()).online is False
    assert set(drivers.DRIVERS) == {"samsung", "roku", "androidtv"}


def test_importar_contrato_e_registro_nao_puxa_biblioteca_de_tv():
    codigo = (
        "import sys, magi.casa.driver, magi.casa.drivers, magi.casa.falso;"
        "pesadas = {'samsungtvws','rokuecp','androidtvremote2','zeroconf','async_upnp_client',"
        "'wakeonlan','aiohttp','yaml'};"
        "print(sorted(pesadas & {m.split('.')[0] for m in sys.modules}))"
    )
    saida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=True)
    assert saida.stdout.strip() == "[]"


def test_log_json_sem_segredo(log_casa):
    from magi.casa import log

    log.evento(
        "acao",
        tv="sala",
        driver="samsung",
        acao="tv.text",
        ok=True,
        ms=120,
        origem="local",
        token="ayn_SEGREDO123456",
        texto="minha senha secreta",
        codigo="4F2A",
        cert="-----BEGIN CERTIFICATE-----abc",
        detalhe="falhou com Bearer abcdef123 e sk-proj-XYZ123456",
    )
    try:
        raise ConnectionError("token=ayn_OUTRO999999 recusado")
    except ConnectionError:
        log.evento("erro", tv="sala", exc=True)
    texto = log_casa.texto
    for proibido in ("SEGREDO", "secreta", "4F2A", "BEGIN", "abcdef123", "XYZ123", "OUTRO999"):
        assert proibido not in texto
    l1, l2 = log_casa.linhas()
    assert l1["evento"] == "acao" and l1["tv"] == "sala" and l1["ok"] is True and l1["ms"] == 120
    assert l1["origem"] == "local" and l1["texto_len"] == 19 and l1["nivel"] == "INFO"
    assert {"ts", "driver", "acao"} <= set(l1)
    assert l2["erro"] == "ConnectionError"


def test_magi_casa_help_lista_subcomandos(capsys):
    from magi.casa.__main__ import main

    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    saida = capsys.readouterr().out
    for sub in ("servir", "descobrir", "nomear", "parear", "esquecer", "estado", "testar"):
        assert sub in saida


def test_magi_casa_stubs_apontam_o_dono(capsys, monkeypatch):
    from magi.casa import servir as servir_mod
    from magi.casa.__main__ import main

    chamado = []
    monkeypatch.setattr(servir_mod, "servir", lambda args: chamado.append(args) or 0)
    assert main([]) == 0 and chamado == [[]]  # servir é o padrão (C1.1c); nunca sobe de verdade aqui
    assert main(["testar", "sala", "tv.power_on"]) == 2
    assert "dono: C1.5" in capsys.readouterr().err
