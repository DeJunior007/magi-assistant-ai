"""Emulação honesta do ``Executor`` (spec §10.7; C1.1b): volume, mudo e power que alterna.

CA-Y31, CA-Y32, CA-Y33. Só ``DriverFalso`` e relógio falso (nenhum ``sleep`` real).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from magi.casa.config import CasaConfig
from magi.casa.driver import Cap, Capacidades, EstadoTv, Key, Motivo, ResTv, TvConfig
from magi.casa.emula import Executor
from magi.casa.falso import DriverFalso, RelogioFalso
from magi.common.contracts import ActionRequest, Intent, Slot, TurnContext, WakeSource

BASE = frozenset(Cap) - {Cap.VOL_SET, Cap.VOL_STEP}


def pedido(intent: str, **slots: str) -> ActionRequest:
    ctx = TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime(2026, 10, 12, tzinfo=UTC))
    return ActionRequest(
        intent=Intent(id=intent, slots=tuple(Slot(name=k, value=v) for k, v in slots.items())), ctx=ctx
    )


def estado(**kw) -> EstadoTv:
    return EstadoTv(**{"id": "sala", "nome": "sala", "driver": "falso", "online": True, **kw})


def montar(relogio: RelogioFalso, drv: DriverFalso, *, zerar: int = 50, dormir=None) -> Executor:
    tv = TvConfig(id="sala", nome="TV da sala", driver=drv.nome, zerar_passos=zerar)
    return Executor(CasaConfig(tvs=(tv,)), {"sala": drv}, relogio=relogio, dormir=dormir or relogio.dormir)


def teclas(drv: DriverFalso) -> list[Key]:
    return [c.args["key"] for c in drv.de("key")]


def intervalos(drv: DriverFalso) -> set[float]:
    ts = [c.t for c in drv.de("key")]
    return {round(b - a, 3) for a, b in zip(ts, ts[1:], strict=False)}


# --- CA-Y31: volume com estado --------------------------------------------------------------
async def test_set_to_com_estado_desce_e_corrige(relogio):
    caps = Capacidades(BASE, emula=frozenset({Cap.VOL_SET}))
    drv = DriverFalso(
        caps, {"state": [estado(volume=30), estado(volume=21), estado(volume=20)]}, relogio=relogio
    )
    res = await montar(relogio, drv).rodar(pedido("tv.volume", volume="20"))
    assert res.ok and res.emulado and res.estado.volume == 20
    assert teclas(drv) == [Key.VOL_DOWN] * 11  # 10 + 1 de correção
    assert intervalos(drv) == {0.08}
    assert len(drv.de("state")) == 3  # lê, relê, confere


async def test_correcao_limitada_a_3_teclas(relogio):
    caps = Capacidades(BASE, emula=frozenset({Cap.VOL_SET}))
    drv = DriverFalso(caps, {"state": [estado(volume=30), estado(volume=26)]}, relogio=relogio)
    res = await montar(relogio, drv).rodar(pedido("tv.volume", volume="20"))
    assert res.ok and teclas(drv) == [Key.VOL_DOWN] * 10  # 6 de diferença: não corrige


async def test_delta_acima_de_60_e_nao_suportado(relogio):
    caps = Capacidades(BASE, emula=frozenset({Cap.VOL_SET}))
    drv = DriverFalso(caps, {"state": estado(volume=10)}, relogio=relogio)
    res = await montar(relogio, drv).rodar(pedido("tv.volume", volume="80"))
    assert res.motivo is Motivo.NAO_SUPORTADO and "acima" in res.detalhe and teclas(drv) == []


async def test_vol_max_do_android_tv_converte_passos(relogio):
    caps = Capacidades(BASE | {Cap.VOL_STEP}, vol_max=50, emula=frozenset({Cap.VOL_SET}))
    drv = DriverFalso(caps, {"state": estado(volume=30)}, relogio=relogio, nome="androidtv")
    res = await montar(relogio, drv).rodar(pedido("tv.volume", volume="20"))
    assert res.ok and [c.args["step"] for c in drv.de("volume")] == [-1] * 5  # 1 tecla = 2 pontos


async def test_emulacao_com_prazo_do_android_tv(relogio):
    async def lenta(_c):
        await relogio.dormir(0.05)
        return ResTv(True)

    caps = Capacidades(BASE, vol_max=100, emula=frozenset({Cap.VOL_SET}))
    drv = DriverFalso(caps, {"state": estado(volume=0), "key": lenta}, relogio=relogio, nome="androidtv")
    res = await montar(relogio, drv).rodar(pedido("tv.volume", volume="60"))  # 60 × 130 ms > 4,8 s
    assert res.motivo is Motivo.TEMPO_ESGOTADO and res.emulado
    assert len(teclas(drv)) < 60


# --- CA-Y32: volume sem estado --------------------------------------------------------------
async def test_set_to_sem_estado_zera_e_sobe(relogio):
    caps = Capacidades(BASE - {Cap.STATE}, emula=frozenset({Cap.VOL_SET}))
    drv = DriverFalso(caps, relogio=relogio, nome="samsung")
    t0 = relogio()
    res = await montar(relogio, drv).rodar(pedido("tv.volume", volume="20"))
    assert res.ok and res.emulado
    assert teclas(drv) == [Key.VOL_DOWN] * 50 + [Key.VOL_UP] * 20
    assert intervalos(drv) == {0.08} and relogio() - t0 <= 8.0


async def test_zerar_passos_por_tv(relogio):
    caps = Capacidades(BASE - {Cap.STATE}, emula=frozenset({Cap.VOL_SET}))
    drv = DriverFalso(caps, relogio=relogio)
    assert (await montar(relogio, drv, zerar=30).rodar(pedido("tv.volume", volume="10"))).ok
    assert teclas(drv) == [Key.VOL_DOWN] * 30 + [Key.VOL_UP] * 10


async def test_sem_estado_acima_de_50_nao_envia_nada(relogio):
    caps = Capacidades(BASE - {Cap.STATE}, emula=frozenset({Cap.VOL_SET}))
    drv = DriverFalso(caps, relogio=relogio)
    res = await montar(relogio, drv).rodar(pedido("tv.volume", volume="60"))
    assert res.motivo is Motivo.NAO_SUPORTADO and res.detalhe == "acima do que dá para emular"
    assert drv.chamadas == []


async def test_vol_set_sem_emula_e_nao_suportado(relogio):
    drv = DriverFalso(Capacidades(BASE), relogio=relogio)
    res = await montar(relogio, drv).rodar(pedido("tv.volume", volume="20"))
    assert res.motivo is Motivo.NAO_SUPORTADO and teclas(drv) == []


async def test_nova_acao_aborta_a_sequencia(relogio):
    async def dormir(s: float) -> None:
        await relogio.dormir(s)
        await asyncio.sleep(0)  # cede a vez (sem esperar de verdade)

    caps = Capacidades(BASE - {Cap.STATE}, emula=frozenset({Cap.VOL_SET}))
    drv = DriverFalso(caps, relogio=relogio)
    ex = montar(relogio, drv, dormir=dormir)
    primeira = asyncio.create_task(ex.rodar(pedido("tv.volume", volume="20")))
    for _ in range(5):
        await asyncio.sleep(0)
    segunda = await ex.rodar(pedido("tv.app", app="netflix"))
    res = await primeira
    assert segunda.ok
    assert not res.ok and res.motivo is Motivo.OCUPADA and res.emulado
    assert 0 < len(teclas(drv)) < 70
    assert drv.metodos()[-1] == "app"


async def test_step_emulado_com_teclas_preso_em_30(relogio):
    caps = Capacidades(BASE, emula=frozenset({Cap.VOL_STEP}))
    drv = DriverFalso(caps, relogio=relogio)
    assert (await montar(relogio, drv).rodar(pedido("tv.volume", volume="+40"))).ok
    assert teclas(drv) == [Key.VOL_UP] * 30


@pytest.mark.parametrize(("valor", "step"), [("+3", 3), ("-8", -8), ("+0", 1), ("-99", -30)])
async def test_step_nativo(relogio, valor, step):
    drv = DriverFalso(Capacidades(frozenset(Cap)), relogio=relogio)
    assert (await montar(relogio, drv).rodar(pedido("tv.volume", volume=valor))).ok
    assert drv.de("volume")[0].args == {"step": step, "set_to": None}


async def test_volume_sem_valor_ou_invalido(relogio):
    drv = DriverFalso(Capacidades(frozenset(Cap)), relogio=relogio)
    ex = montar(relogio, drv)
    assert (await ex.rodar(pedido("tv.volume"))).motivo is Motivo.NAO_SUPORTADO
    assert (await ex.rodar(pedido("tv.volume", volume="alto"))).motivo is Motivo.NAO_SUPORTADO
    assert drv.chamadas == []


# --- CA-Y33: mudo --------------------------------------------------------------------------
async def test_mudo_com_estado_igual_nao_manda_tecla(relogio):
    drv = DriverFalso(Capacidades(frozenset(Cap)), {"state": estado(mudo=True)}, relogio=relogio)
    res = await montar(relogio, drv).rodar(pedido("tv.mute"))
    assert res.ok and drv.de("mute") == []


async def test_mudo_desconhecido_alterna_uma_vez(relogio):
    drv = DriverFalso(Capacidades(frozenset(Cap)), relogio=relogio, nome="roku")
    res = await montar(relogio, drv).rodar(pedido("tv.mute"))
    assert res.ok and res.emulado and res.detalhe == "alternado"
    assert [c.args["on"] for c in drv.de("mute")] == [None]


async def test_mudo_conhecido_e_diferente_explicito_ou_alterna(relogio):
    drv = DriverFalso(Capacidades(frozenset(Cap)), {"state": estado(mudo=True)}, relogio=relogio)
    assert (await montar(relogio, drv).rodar(pedido("tv.unmute"))).ok
    assert [c.args["on"] for c in drv.de("mute")] == [False]
    roku = DriverFalso(
        Capacidades(frozenset(Cap)),
        {"state": estado(mudo=False), "mute": [ResTv(False, Motivo.NAO_SUPORTADO), ResTv(True)]},
        relogio=relogio,
    )
    res = await montar(relogio, roku).rodar(pedido("tv.mute"))
    assert res.ok and res.emulado and res.detalhe == ""
    assert [c.args["on"] for c in roku.de("mute")] == [True, None]


async def test_mudo_por_tecla_quando_so_emula(relogio):
    caps = Capacidades(frozenset(Cap) - {Cap.MUTE}, emula=frozenset({Cap.MUTE}))
    drv = DriverFalso(caps, relogio=relogio)
    res = await montar(relogio, drv).rodar(pedido("tv.mute"))
    assert res.detalhe == "alternado" and teclas(drv) == [Key.MUTE]


# --- power que alterna ---------------------------------------------------------------------
async def test_power_alternado_so_com_estado_conhecido(relogio):
    caps = Capacidades(
        frozenset(Cap) - {Cap.POWER_ON, Cap.POWER_OFF}, emula=frozenset({Cap.POWER_ON, Cap.POWER_OFF})
    )
    drv = DriverFalso(caps, relogio=relogio)
    ex = montar(relogio, drv)
    res = await ex.rodar(pedido("tv.power_on"))
    assert res.motivo is Motivo.NAO_SUPORTADO and res.detalhe == "estado desconhecido" and teclas(drv) == []
    drv.script["state"] = estado(ligada=True)
    assert (await ex.rodar(pedido("tv.power_on"))).ok and teclas(drv) == []
    drv.script["state"] = [estado(ligada=False), estado(ligada=False), estado(ligada=True)]
    res = await ex.rodar(pedido("tv.power_on"))
    assert res.ok and res.emulado and teclas(drv) == [Key.POWER]
