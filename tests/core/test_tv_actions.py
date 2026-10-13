"""C2.2: ``TvActions`` contra uma casa falsa em TCP ``127.0.0.1:0`` (CA-Y52, CA-Y53; spec §10.2, §13)."""

from __future__ import annotations

import asyncio
import re
import shutil
import socket
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from magi.common.config import CasaConfig, ConfigError
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    EventType,
    Intent,
    IntentId,
    PlaybackDone,
    RouteKind,
    RouteResult,
    Slot,
    SlotName,
    TurnContext,
    TurnState,
    WakeSource,
)
from magi.core.actions import Registry
from magi.core.actions.tv import (
    ARG_ESCOLHA,
    SAY_CASA_OFF,
    SAY_TV_MOTIVO,
    SAY_TV_NO_RESPONSE,
    SAY_TV_OK,
    SAY_TV_REDE,
    TvActions,
)
from magi.core.hud_client import HudServer
from magi.core.router import CasaCatalogo
from magi.core.service import CoreService
from magi.core.tts import Phrases
from magi.core.turn import TurnDeps
from magi.elo.mensagens import (
    AcaoOk,
    AcaoPedido,
    AcaoResultado,
    AppInfo,
    Envelope,
    Erro,
    Estado,
    EstadoTv,
    Ola,
    Tipo,
    TipoDispositivo,
    TvInfo,
    decode,
    encode,
    responder,
)

TOKEN = "token-falso-de-teste"
SALA = TvInfo(id="sala", nome="TV da sala", driver="samsung", apelidos=("sala",), padrao=False)
QUARTO = TvInfo(id="quarto", nome="TV do quarto", driver="roku", apelidos=("quarto", "tcl"),
                entradas=("hdmi1", "videogame=hdmi3"))
YOUTUBE = AppInfo(id="youtube", nome="YouTube", apelidos=("iutubi",))


def _ok(_p: AcaoPedido) -> AcaoResultado:
    return AcaoResultado(ok=True, dados={"tv": "sala"})


class CasaFalsa:
    """Elo local da §10.2: ``ola`` com token, ``acao`` → ``acao_ok``, ``estado`` → ``estado``."""

    def __init__(self, resposta: Callable[[AcaoPedido], AcaoResultado] = _ok, *, muda: bool = False) -> None:
        self.resposta, self.muda = resposta, muda
        self.tvs: tuple[TvInfo, ...] = (SALA, QUARTO)
        self.pedidos: list[AcaoPedido] = []
        self.conexoes = 0
        self._ws: list[asyncio.StreamWriter] = []
        self.port = 0

    async def __aenter__(self) -> CasaFalsa:
        self.server = await asyncio.start_server(self._conn, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_: object) -> None:
        self.fecha_todas()
        self.server.close()

    def fecha_todas(self) -> None:  # "ocioso > 10 min → casa fecha"
        for w in self._ws:
            w.close()
        self._ws.clear()

    async def _manda(self, w: asyncio.StreamWriter, env: Envelope) -> None:
        w.write((encode(env) + "\n").encode())
        await w.drain()

    async def _conn(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        self.conexoes += 1
        ola = decode(await r.readline())
        assert ola.t is Tipo.OLA and isinstance(ola.corpo, Ola) and ola.corpo.tipo is TipoDispositivo.PC
        if ola.corpo.token != TOKEN:
            await self._manda(w, responder(ola, Tipo.ERRO, Erro(codigo="nao_autorizado"), "casa"))
            w.close()
            return
        corpo = Ola(tipo=TipoDispositivo.CASA, versao="teste", tvs=self.tvs, apps=(YOUTUBE,))
        await self._manda(w, responder(ola, Tipo.OLA, corpo, "casa"))
        self._ws.append(w)
        try:
            while line := await r.readline():
                env = decode(line)
                if env.t is Tipo.ACAO:
                    self.pedidos.append(env.corpo.pedido)
                    if not self.muda:
                        res = self.resposta(env.corpo.pedido)
                        await self._manda(w, responder(env, Tipo.ACAO_OK, AcaoOk(resultado=res), "casa"))
                elif env.t is Tipo.ESTADO:
                    tvs = (EstadoTv(id="sala", nome="TV da sala", driver="samsung", online=True, ligada=True,
                                    app="youtube", volume=12),
                           EstadoTv(id="quarto", nome="TV do quarto", driver="roku", online=False))
                    await self._manda(w, responder(env, Tipo.ESTADO, Estado(tvs=tvs), "casa"))
        except (ConnectionError, OSError):
            pass


def _ctx() -> TurnContext:
    return TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC))


def _req(intent: IntentId, *slots: Slot, confirmed: bool = False) -> ActionRequest:
    return ActionRequest(intent=Intent(id=intent, slots=slots, danger=intent == IntentId.TV_POWER_OFF),
                         ctx=_ctx(), text="", confirmed=confirmed)


@pytest.fixture
def token(tmp_path: Path) -> Path:
    p = tmp_path / "casa.token"
    p.write_text(TOKEN + "\n")
    return p


def _tv(port: int, token: Path, **kw: object) -> TvActions:
    kw.setdefault("timeout_s", 1.0)
    kw.setdefault("casa_toml", token.parent / "casa.toml")
    return TvActions("127.0.0.1", port, token, **kw)  # type: ignore[arg-type]


def _porta_fechada() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# -- casa fora do ar -------------------------------------------------------------------------


async def test_casa_recusando_conexao_diz_fora_do_ar(token: Path) -> None:
    tv = _tv(_porta_fechada(), token)
    res = await tv.run(_req(IntentId.TV_POWER_ON))
    assert not res.ok and res.speech == SAY_CASA_OFF


async def test_sem_token_nem_tenta_conectar(tmp_path: Path) -> None:
    async with CasaFalsa() as casa:
        tv = _tv(casa.port, tmp_path / "nao-existe.token")
        res = await tv.run(_req(IntentId.TV_MUTE))
        assert res.speech == SAY_CASA_OFF and casa.conexoes == 0


async def test_token_errado_vira_fora_do_ar(tmp_path: Path) -> None:
    errado = tmp_path / "casa.token"
    errado.write_text("outro")
    async with CasaFalsa() as casa:
        res = await _tv(casa.port, errado).run(_req(IntentId.TV_MUTE))
        assert res.speech == SAY_CASA_OFF and casa.pedidos == []


async def test_registry_sem_casa_nunca_levanta(token: Path) -> None:
    reg = Registry([_tv(_porta_fechada(), token)])
    for intent in TvActions.intents:
        res = await reg.run(_req(intent, confirmed=True))
        assert res.speech == SAY_CASA_OFF


async def test_casa_muda_vira_tv_nao_respondeu(token: Path) -> None:
    async with CasaFalsa(muda=True) as casa:
        res = await _tv(casa.port, token, timeout_s=0.05).run(_req(IntentId.TV_MUTE))
        assert not res.ok and res.speech == SAY_TV_NO_RESPONSE


# -- acao → frase (CA-Y53) ------------------------------------------------------------------


@pytest.mark.parametrize("motivo", sorted(SAY_TV_MOTIVO))
async def test_cada_motivo_vira_a_frase(token: Path, motivo: str) -> None:
    async with CasaFalsa(lambda _p: AcaoResultado(ok=False, motivo=motivo, dados={"tv": "sala"})) as casa:
        res = await _tv(casa.port, token).run(_req(IntentId.TV_MUTE))
        assert not res.ok and res.speech == SAY_TV_MOTIVO[motivo].format(nome="TV da sala")


async def test_rede_desligada_depende_do_driver(token: Path) -> None:
    async with CasaFalsa(lambda p: AcaoResultado(ok=False, motivo="rede_desligada",
                                                 dados={"tv": dict(p.slots).get("tv", "sala")})) as casa:
        tv = _tv(casa.port, token)
        sala = await tv.run(_req(IntentId.TV_POWER_ON))
        quarto = await tv.run(_req(IntentId.TV_POWER_ON, Slot(SlotName.TV.value, "quarto")))
    assert sala.speech == SAY_TV_REDE[""].format(nome="TV da sala")
    assert quarto.speech == SAY_TV_REDE["roku"].format(nome="TV do quarto")


async def test_sucesso_e_slots_viajam(token: Path) -> None:
    async with CasaFalsa() as casa:
        tv = _tv(casa.port, token)
        on = await tv.run(_req(IntentId.TV_POWER_ON, Slot(SlotName.TV.value, "sala")))
        passo = await tv.run(_req(IntentId.TV_VOLUME, Slot(SlotName.VOLUME.value, "+3")))
        absoluto = await tv.run(_req(IntentId.TV_VOLUME, Slot(SlotName.VOLUME.value, "20")))
        app = await tv.run(_req(IntentId.TV_APP, Slot(SlotName.APP.value, "youtube", display="YouTube")))
        assert casa.conexoes == 1  # uma conexão só
    assert on.ok and on.speech == SAY_TV_OK[IntentId.TV_POWER_ON]
    assert passo.speech == "Ok." and absoluto.speech == SAY_TV_OK[IntentId.TV_VOLUME]
    assert app.speech == "Abrindo YouTube na TV."
    assert casa.pedidos[0].intent == "tv.power_on" and casa.pedidos[0].slots == (("tv", "sala"),)


async def test_desligar_pede_confirmacao_antes_da_casa(token: Path) -> None:
    async with CasaFalsa() as casa:
        tv = _tv(casa.port, token)
        res = await tv.run(_req(IntentId.TV_POWER_OFF))
        assert res.needs_confirmation and res.dangerous and casa.pedidos == []
        assert res.on_confirm is not None and res.on_confirm.confirmed
        done = await tv.run(res.on_confirm)
    assert done.ok and done.speech == "TV desligada." and casa.pedidos[0].confirmed


async def test_reabre_quando_a_casa_fecha_por_ocio(token: Path) -> None:
    async with CasaFalsa() as casa:
        tv = _tv(casa.port, token)
        assert (await tv.run(_req(IntentId.TV_MUTE))).ok
        casa.fecha_todas()
        await asyncio.sleep(0.02)
        assert (await tv.run(_req(IntentId.TV_MUTE))).ok
        assert casa.conexoes == 2
        await tv.aclose()


async def test_ola_alimenta_o_catalogo_do_roteador(token: Path) -> None:
    (token.parent / "casa.toml").write_text('[[tv]]\nid = "sala"\nentradas = { console = "hdmi2" }\n')
    vistos: list[CasaCatalogo] = []
    async with CasaFalsa() as casa:
        tv = _tv(casa.port, token, ao_catalogo=vistos.append)
        await tv.aquecer()
        ok, estados = await tv.estado()
    assert vistos and vistos[-1].tvs == (SALA, QUARTO) and vistos[-1].apps == (YOUTUBE,)
    assert vistos[-1].entradas == {"console": "hdmi2", "videogame": "hdmi3"}
    assert ok and [e.id for e in estados] == ["sala", "quarto"]


async def test_todas_as_frases_tv_estao_no_phrases_yaml() -> None:
    from magi.core.actions import tv as mod

    phrases = Phrases.load()
    textos = [v for k, v in vars(mod).items() if k.startswith("SAY_") and isinstance(v, str)]
    textos += [x for k, v in vars(mod).items() if k.startswith("SAY_") and isinstance(v, dict)
               for x in v.values()]
    faltam = [t for t in textos if not phrases.cacheable(re.sub(r"\{\w+\}", "X", t))]
    assert len(textos) > 20 and faltam == []


def test_casa_config() -> None:
    assert CasaConfig.from_raw(None) == CasaConfig()
    c = CasaConfig.from_raw({"ligado": False, "endereco": "100.64.0.5:10761", "timeout_s": 3})
    got = (c.ligado, c.host, c.port, c.timeout_s, c.timeout_longo_s)
    assert got == (False, "100.64.0.5", 10761, 3.0, 10.0)
    with pytest.raises(ConfigError):
        CasaConfig.from_raw({"endereco": "sem-porta"})


# -- "qual TV?" (CA-Y52) ---------------------------------------------------------------------


def _ambigua(p: AcaoPedido) -> AcaoResultado:
    if "tv" not in dict(p.slots):
        return AcaoResultado(ok=False, motivo="tv_ambigua")
    return AcaoResultado(ok=True, dados={"tv": dict(p.slots)["tv"]})


async def test_tv_ambigua_pergunta_e_resposta_curta_resolve(token: Path) -> None:
    async with CasaFalsa(_ambigua) as casa:
        tv = _tv(casa.port, token)
        res = await tv.run(_req(IntentId.TV_MUTE))
        assert res.speech == "Mais de uma TV: sala ou quarto?" and res.needs_confirmation
        assert res.on_confirm is not None
        escolha = res.on_confirm.args[ARG_ESCOLHA]
        assert escolha("sei lá") is None
        req = escolha("a do quarto")
        assert req is not None and req.intent.slot(SlotName.TV).value == "quarto"
        assert ARG_ESCOLHA not in req.args
        done = await tv.run(req)
    assert done.ok and casa.pedidos[-1].slots == (("tv", "quarto"),)


# -- no turno: pergunta e resposta curta no turno seguinte ----------------------------------


class _Roteador:
    def route(self, text: str, ctx: TurnContext) -> RouteResult:
        if "tv" in text.lower():
            return RouteResult(RouteKind.LOCAL, text, 95, Intent(IntentId.TV_MUTE))
        return RouteResult(RouteKind.AGENT, text)


@dataclass
class _Ag:
    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        return ActionResult(ok=True, speech="agente")


async def test_turno_pergunta_qual_tv_e_resposta_curta_executa(token: Path) -> None:
    from tests.core.test_turn_states import (
        AL,
        SP,
        TH,
        FakeCorrector,
        FakeSpeaker,
        FakeStt,
        Hud,
        L,
        S,
        Sat,
        _until,
    )

    d = Path(tempfile.mkdtemp(prefix="magi-tv-"))
    async with CasaFalsa(_ambigua) as casa:
        tv = _tv(casa.port, token)
        spk = FakeSpeaker()
        deps = TurnDeps(stt=FakeStt(), corrector=FakeCorrector(), router=_Roteador(), actions=Registry([tv]),
                        agent=_Ag(), speaker=spk)
        hud_server = HudServer(d / "hud.sock")
        await hud_server.start()
        service = CoreService(deps, hud_server, port=0)
        await service.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(hud_server.path))
            await _until(lambda: hud_server.clients == 1)
            sat = await Sat.connect(service.port)
            await _until(lambda: service.machine("pc") is not None)
            hud = Hud(reader, writer)
            await sat.wake()
            await sat.speak("muta a tv")
            assert (await hud.states(3))[:2] == [L, TH]
            await sat.hear()
            assert spk.said[-1] == "Mais de uma TV: sala ou quarto?"
            await sat.send(PlaybackDone())
            assert await hud.state() == AL
            assert service.machine("pc").state is TurnState.CONFIRMING
            await sat.expect(EventType.LISTEN)
            await sat.speak("a da sala")
            assert await hud.states(2) == [TH, SP]
            await sat.hear()
            assert spk.said[-1] == "TV no mudo."
            assert casa.pedidos[-1].slots == (("tv", "sala"),)
            await sat.send(PlaybackDone())
            assert await hud.state() in (S, L)
            await sat.close()
            writer.close()
        finally:
            await service.stop()
            await hud_server.stop()
            await tv.aclose()
            shutil.rmtree(d, ignore_errors=True)
