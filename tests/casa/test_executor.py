"""``Executor`` (C1.1b): intent → método, escolha da TV, confirmação, ligar e timeouts.

CA-Y30, CA-Y34, CA-Y35 (caminho local), CA-Y45, CA-Y52. Só ``DriverFalso`` e relógio falso.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from magi.casa.config import CasaConfig
from magi.casa.driver import Cap, Capacidades, EstadoTv, Key, Motivo, ResTv, TvConfig
from magi.casa.emula import INTENTS, Executor, Prazos, candidatos
from magi.casa.falso import DriverFalso, RelogioFalso
from magi.common.contracts import ActionRequest, Intent, Slot, TurnContext, WakeSource

TODAS = Capacidades(frozenset(Cap), entradas=("hdmi1", "hdmi2"), apps=("netflix",))


def pedido(intent: str, *, confirmed: bool = False, args: dict | None = None, **slots: str) -> ActionRequest:
    ctx = TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime(2026, 10, 12, tzinfo=UTC))
    sl = tuple(Slot(name=k, value=v) for k, v in slots.items())
    return ActionRequest(intent=Intent(id=intent, slots=sl), ctx=ctx, confirmed=confirmed, args=args or {})


def estado(tv: str = "sala", **kw) -> EstadoTv:
    base = {"id": tv, "nome": tv, "driver": "falso", "online": True}
    base.update(kw)
    return EstadoTv(**base)


def montar(relogio: RelogioFalso, drivers: dict, *, padrao: str = "", tvs=None, **kw) -> Executor:
    tvs = tvs or tuple(TvConfig(id=i, nome=f"TV {i}", driver="falso") for i in drivers)
    cfg = CasaConfig(padrao=padrao, tvs=tuple(tvs))
    return Executor(cfg, drivers, relogio=relogio, dormir=relogio.dormir, **kw)


# --- CA-Y30: tabela dos 11 métodos ----------------------------------------------------------
CASOS = [
    ("tv.power_on", {}, {}, "power"),
    ("tv.power_off", {}, {}, "power"),
    ("tv.volume", {"volume": "+3"}, {}, "volume"),
    ("tv.volume", {"volume": "20"}, {}, "volume"),
    ("tv.mute", {}, {}, "mute"),
    ("tv.unmute", {}, {}, "mute"),
    ("tv.channel", {}, {"step": 1}, "channel"),
    ("tv.input", {"input": "hdmi2"}, {}, "input"),
    ("tv.app", {"app": "netflix"}, {}, "app"),
    ("tv.key", {}, {"key": "home"}, "key"),
    ("tv.text", {}, {"texto": "oi"}, "text"),
]


@pytest.mark.parametrize(("intent", "slots", "args", "metodo"), CASOS)
async def test_nunca_ok_quando_o_driver_falha(relogio, intent, slots, args, metodo):
    falha = ResTv(False, Motivo.OFFLINE, "caiu")
    st = estado(mudo=intent == "tv.unmute", volume=10)
    drv = DriverFalso(TODAS, {metodo: falha, "state": st}, relogio=relogio)
    ex = montar(relogio, {"sala": drv})
    res = await ex.rodar(pedido(intent, confirmed=True, args=args, **slots))
    assert not res.ok and res.motivo is Motivo.OFFLINE
    assert metodo in drv.metodos()
    assert INTENTS[intent] == metodo


async def test_tabela_cobre_os_metodos_do_driver():
    assert set(INTENTS.values()) == {
        "power",
        "volume",
        "mute",
        "channel",
        "input",
        "app",
        "key",
        "text",
        "state",
    }  # conectar/fechar: reabertura depois de timeout (CA-Y45)


async def test_state_e_conectar_falhando(relogio):
    drv = DriverFalso(TODAS, {"state": RuntimeError("boom")}, relogio=relogio)
    ex = montar(relogio, {"sala": drv})
    res = await ex.rodar(pedido("tv.state"))
    assert not res.ok


@pytest.mark.parametrize(
    ("intent", "slots", "args", "cap"),
    [
        ("tv.input", {"input": "hdmi1"}, {}, Cap.INPUT),
        ("tv.app", {"app": "netflix"}, {}, Cap.APP),
        ("tv.channel", {}, {"step": -1}, Cap.CHANNEL),
        ("tv.key", {}, {"key": "ok"}, Cap.KEY),
        ("tv.text", {}, {"texto": "a"}, Cap.TEXT),
        ("tv.power_on", {}, {}, Cap.POWER_ON),
        ("tv.volume", {"volume": "+2"}, {}, Cap.VOL_STEP),
        ("tv.volume", {"volume": "30"}, {}, Cap.VOL_SET),
        ("tv.mute", {}, {}, Cap.MUTE),
    ],
)
async def test_cap_ausente_sem_emulacao_e_nao_suportado(relogio, intent, slots, args, cap):
    caps = Capacidades(frozenset(Cap) - {cap})
    drv = DriverFalso(caps, relogio=relogio)
    res = await montar(relogio, {"sala": drv}).rodar(pedido(intent, args=args, **slots))
    assert res.motivo is Motivo.NAO_SUPORTADO and not res.ok
    assert [m for m in drv.metodos() if m != "state"] == []


async def test_input_nao_emula_e_resolve_apelido(relogio):
    drv = DriverFalso(TODAS, relogio=relogio)
    tv = TvConfig(id="sala", nome="TV da sala", driver="falso", entradas={"videogame": "hdmi2"})
    ex = montar(relogio, {"sala": drv}, tvs=(tv,))
    assert (await ex.rodar(pedido("tv.input", input="videogame"))).ok
    assert drv.de("input")[0].args["nome"] == "hdmi2"
    res = await ex.rodar(pedido("tv.input", input="cabo"))
    assert res.motivo is Motivo.ENTRADA_DESCONHECIDA


async def test_tecla_invalida_e_intent_desconhecido(relogio):
    drv = DriverFalso(TODAS, relogio=relogio)
    ex = montar(relogio, {"sala": drv})
    assert (await ex.rodar(pedido("tv.key", args={"key": "xyz"}))).motivo is Motivo.NAO_SUPORTADO
    assert (await ex.rodar(pedido("tv.dancar"))).motivo is Motivo.NAO_SUPORTADO
    assert (await ex.rodar(pedido("tv.key", args={"key": Key.BACK.value}))).ok


async def test_excecao_do_driver_vira_erro_driver(relogio, log_casa):
    drv = DriverFalso(TODAS, {"app": RuntimeError("token=abc123 vazou")}, relogio=relogio)
    res = await montar(relogio, {"sala": drv}).rodar(pedido("tv.app", app="netflix"))
    assert res.motivo is Motivo.ERRO_DRIVER
    assert "abc123" not in log_casa.texto


async def test_log_acao(relogio, log_casa):
    drv = DriverFalso(TODAS, relogio=relogio)
    await montar(relogio, {"sala": drv}).rodar(pedido("tv.app", app="netflix"), origem="ayanami")
    linha = [x for x in log_casa.linhas() if x["evento"] == "acao"][-1]
    assert linha["tv"] == "sala" and linha["acao"] == "tv.app" and linha["ok"] is True
    assert linha["origem"] == "ayanami" and "ms" in linha


# --- CA-Y35: confirmação -------------------------------------------------------------------
async def test_power_off_sem_confirmacao_nao_chama_driver(relogio):
    drv = DriverFalso(TODAS, relogio=relogio)
    ex = montar(relogio, {"sala": drv})
    res = await ex.rodar(pedido("tv.power_off"))
    assert res.motivo is Motivo.PRECISA_CONFIRMAR and drv.chamadas == []
    res = await ex.rodar(pedido("tv.power_off", confirmed=True))
    assert res.ok and drv.de("power")[0].args == {"on": False}


# --- CA-Y34: ligar -------------------------------------------------------------------------
async def test_ligar_confirma_no_terceiro_poll(relogio):
    off = estado(ligada=False)
    drv = DriverFalso(TODAS, {"state": [off, off, estado(ligada=True)]}, relogio=relogio)
    ex = montar(relogio, {"sala": drv})
    t0 = relogio()
    res = await ex.rodar(pedido("tv.power_on"))
    assert res.ok and res.estado.ligada is True
    assert len(drv.de("state")) == 3
    assert relogio() - t0 == pytest.approx(1.5) and relogio() - t0 < 8
    assert relogio.dormidas == [0.5, 0.5, 0.5]


async def test_ligar_que_nunca_confirma_e_standby_profundo(relogio):
    drv = DriverFalso(TODAS, {"state": estado(ligada=False)}, relogio=relogio)
    res = await montar(relogio, {"sala": drv}).rodar(pedido("tv.power_on"))
    assert not res.ok and res.motivo is Motivo.STANDBY_PROFUNDO  # "ok" do power não é "pronto"
    assert len(drv.de("state")) == 16 and sum(relogio.dormidas) == pytest.approx(8.0)


async def test_ligar_sem_mac_e_sem_rede(relogio):
    drv = DriverFalso(TODAS, {"state": estado(online=False)}, relogio=relogio, nome="samsung")
    tv = TvConfig(id="sala", nome="TV da sala", driver="samsung", mac="")
    res = await montar(relogio, {"sala": drv}, tvs=(tv,)).rodar(pedido("tv.power_on"))
    assert res.motivo is Motivo.SEM_MAC
    tv2 = TvConfig(id="sala", nome="TV da sala", driver="samsung", mac="aa:bb:cc:dd:ee:ff")
    res = await montar(relogio, {"sala": drv}, tvs=(tv2,)).rodar(pedido("tv.power_on"))
    assert res.motivo is Motivo.REDE_DESLIGADA


async def test_ligar_motivo_do_driver_passa_e_roku_confirma_sozinho(relogio):
    drv = DriverFalso(TODAS, {"power": ResTv(False, Motivo.ACESSO_NEGADO)}, relogio=relogio, nome="roku")
    ex = montar(relogio, {"sala": drv})
    assert (await ex.rodar(pedido("tv.power_on"))).motivo is Motivo.ACESSO_NEGADO
    drv.script["power"] = ResTv(True)
    assert (await ex.rodar(pedido("tv.power_on"))).ok
    assert drv.de("state") == []


# --- CA-Y45: timeouts ----------------------------------------------------------------------
@pytest.mark.parametrize(("nome", "limite"), [("samsung", 2.0), ("roku", 1.5), ("androidtv", 2.0)])
async def test_timeout_no_limite_de_cada_driver(relogio, nome, limite):
    async def dorme(_c):
        await relogio.dormir(limite + 0.01)
        return ResTv(True)

    drv = DriverFalso(TODAS, {"app": dorme}, relogio=relogio, nome=nome)
    ex = montar(relogio, {"sala": drv})
    res = await ex.rodar(pedido("tv.app", app="netflix"))
    assert res.motivo is Motivo.TEMPO_ESGOTADO and str(limite).rstrip("0").rstrip(".") in res.detalhe
    assert drv.metodos()[-1] == "fechar"  # conexão descartada
    drv.script["app"] = ResTv(True)
    assert (await ex.rodar(pedido("tv.app", app="netflix"))).ok
    assert drv.metodos()[-2:] == ["conectar", "app"]  # reaberta na seguinte
    assert (await ex.rodar(pedido("tv.app", app="netflix"))).ok
    assert drv.metodos()[-1] == "app" and drv.metodos().count("conectar") == 1


async def test_timeout_dentro_do_limite_passa(relogio):
    async def quase(_c):
        await relogio.dormir(1.9)
        return ResTv(True)

    drv = DriverFalso(TODAS, {"app": quase}, relogio=relogio, nome="samsung")
    assert (await montar(relogio, {"sala": drv}).rodar(pedido("tv.app", app="x"))).ok


async def test_timeout_real_do_wait_for(relogio):
    nunca = asyncio.Event()

    async def trava(_c):
        await nunca.wait()

    drv = DriverFalso(TODAS, {"key": trava}, relogio=relogio)
    curto = Prazos(conectar=0.01, simples=0.01, ligar=0.01, sondagem=0.01, emulacao=0.01)
    ex = montar(relogio, {"sala": drv}, prazos={"falso": curto})
    res = await ex.rodar(pedido("tv.key", args={"key": "ok"}))
    assert res.motivo is Motivo.TEMPO_ESGOTADO


async def test_reconexao_falhando_devolve_o_motivo(relogio):
    async def dorme(_c):
        await relogio.dormir(5)

    drv = DriverFalso(TODAS, {"app": dorme, "conectar": ResTv(False, Motivo.NAO_PAREADO)}, relogio=relogio)
    ex = montar(relogio, {"sala": drv})
    assert (await ex.rodar(pedido("tv.app", app="x"))).motivo is Motivo.TEMPO_ESGOTADO
    assert (await ex.rodar(pedido("tv.app", app="x"))).motivo is Motivo.NAO_PAREADO
    assert (await ex.rodar(pedido("tv.app", app="x"))).motivo is Motivo.NAO_PAREADO  # tenta de novo


# --- CA-Y52: escolha da TV (§13.3) ---------------------------------------------------------
def _duas(relogio):
    sala = TvConfig(id="sala", nome="TV da sala", driver="falso", apelidos=("tv grande",))
    quarto = TvConfig(id="quarto", nome="TV do quarto", driver="falso")
    ds = {"sala": DriverFalso(TODAS, relogio=relogio), "quarto": DriverFalso(TODAS, relogio=relogio)}
    return (sala, quarto), ds


async def test_regra1_slot_tv_por_id_nome_ou_apelido(relogio):
    tvs, ds = _duas(relogio)
    ex = montar(relogio, ds, tvs=tvs, padrao="quarto")
    for v in ("sala", "TV da Sala", "tv grande"):
        await ex.rodar(pedido("tv.app", app="netflix", tv=v))
    assert len(ds["sala"].de("app")) == 3 and ds["quarto"].chamadas == []
    res = await ex.rodar(pedido("tv.app", app="netflix", tv="cozinha"))
    assert res.motivo is Motivo.TV_DESCONHECIDA


async def test_regra2_padrao(relogio):
    tvs, ds = _duas(relogio)
    ex = montar(relogio, ds, tvs=tvs, padrao="quarto")
    ex.estados["sala"] = estado("sala", ligada=True)
    assert (await ex.rodar(pedido("tv.app", app="netflix"))).ok
    assert ds["quarto"].de("app") and not ds["sala"].chamadas


async def test_regra3_unica_tv(relogio):
    drv = DriverFalso(TODAS, relogio=relogio)
    tv = TvConfig(id="sala", nome="TV da sala", driver="falso")
    ex = Executor(CasaConfig(padrao="", tvs=(tv,)), {"sala": drv}, relogio=relogio, dormir=relogio.dormir)
    assert (await ex.rodar(pedido("tv.app", app="netflix"))).ok
    assert drv.de("app")


async def test_regra4_unica_ligada_menos_para_ligar(relogio):
    tvs, ds = _duas(relogio)
    ex = montar(relogio, ds, tvs=tvs)
    ex.estados["quarto"] = estado("quarto", ligada=True)
    ex.estados["sala"] = estado("sala", ligada=False)
    assert (await ex.rodar(pedido("tv.app", app="netflix"))).ok
    assert ds["quarto"].de("app")
    res = await ex.rodar(pedido("tv.power_on"))  # ligar não usa "só uma ligada"
    assert res.motivo is Motivo.TV_AMBIGUA and set(candidatos(res)) == {"sala", "quarto"}


async def test_regra5_ambigua_com_candidatos(relogio):
    tvs, ds = _duas(relogio)
    ex = montar(relogio, ds, tvs=tvs)
    res = await ex.rodar(pedido("tv.mute"))
    assert res.motivo is Motivo.TV_AMBIGUA and candidatos(res) == ("sala", "quarto")
    ex.estados["sala"] = estado("sala", ligada=True)
    ex.estados["quarto"] = estado("quarto", ligada=True)
    res = await ex.rodar(pedido("tv.mute"))
    assert candidatos(res) == ("sala", "quarto")
    assert not ds["sala"].chamadas and not ds["quarto"].chamadas
    assert candidatos(ResTv(True)) == ()


async def test_sem_tv_configurada(relogio):
    ex = Executor(CasaConfig(), {}, relogio=relogio, dormir=relogio.dormir)
    assert (await ex.rodar(pedido("tv.mute"))).motivo is Motivo.TV_DESCONHECIDA
