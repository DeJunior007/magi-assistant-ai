"""Tarefa 1.19: núcleo montado a partir da config, com provedores, banco e ações falsos.

Nada real é aberto ou mudado (regra 8): launcher, processos, HUD/gamerhud, Pulse, OpenRGB e
D-Bus são falsos; cache e dados vão para diretórios temporários.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from wyoming.event import Event, async_read_event, async_write_event

from magi.common.config import Config, parse_config
from magi.common.contracts import (
    ActionResult,
    AudioEnd,
    AudioEndReason,
    EventType,
    Intent,
    IntentId,
    PcmFormat,
    PlaybackDone,
    RouteKind,
    RouteResult,
    SatelliteHello,
    SubtitleMsg,
    Transcript,
    TurnContext,
    TurnState,
    WakeEvent,
    WakeSource,
)
from magi.common.events import audio_chunk, audio_start, decode_hud, to_event
from magi.core import actions
from magi.core.actions import games, hud, spotify_mpris, system
from magi.core.assemble import (
    Core,
    MemoryCorrectionsRepo,
    NullBudget,
    Repos,
    assemble,
    default_handlers,
)
from magi.core.budget import MonthlyBudget
from magi.core.catalog import MemoryAliasStore, SteamCatalog
from magi.core.corrections import handlers as correction_handlers
from magi.core.hud_client import HudServer
from magi.core.service import CoreService
from magi.core.turn import SAY_NOT_HEARD, SAY_UNAVAILABLE, TurnDeps, TurnPipeline

T = 5.0
VOICE = PcmFormat(rate=22_050)

# ---------------------------------------------------------------------------------------------
# Provedores, banco e catálogo falsos
# ---------------------------------------------------------------------------------------------


class FakeStt:
    """O satélite falso manda o texto "falado" como PCM (UTF-8)."""

    name, model, free_tier = "fake", "fake", False

    def __init__(self) -> None:
        self.hints: list[str] = []

    async def transcribe(self, audio, fmt, *, hint="", language="pt", personal):
        self.hints.append(hint)
        return Transcript.raw(audio.decode("utf-8").strip())


class FakeTts:
    name, model, free_tier = "fake", "fake", False
    output_format = VOICE
    voice = "v"

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def synthesize(self, text, *, personal) -> AsyncIterator[bytes]:
        self.texts.append(text)
        yield b"\x01\x00" * 200


class FakePool:
    def __init__(self, n: int) -> None:
        self.n = n

    def available(self) -> int:
        return self.n


class FakeEmb:
    dimensions = 8


class FakeProviders:
    def __init__(self, config: Config, budget, keys: int = 1) -> None:
        self.config = config
        self.budget = budget
        self.keys = keys
        self._stt, self._tts = FakeStt(), FakeTts()

    def pool(self, provider: str) -> FakePool:
        return FakePool(self.keys)

    def stt(self) -> FakeStt:
        return self._stt

    def tts(self) -> FakeTts:
        return self._tts

    def embeddings(self, task) -> FakeEmb:
        return FakeEmb()


class FakeCosts:
    def __init__(self) -> None:
        self.added: list = []

    async def add(self, usage, at) -> int:
        self.added.append(usage)
        return len(self.added)

    async def month_total(self, year: int, month: int) -> float:
        return 0.0


class FakeDb:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.dims: tuple | None = None
        self.corrections = MemoryCorrectionsRepo()
        self.closed = False

    async def __call__(self, config: Config, memories_dim, news_dim) -> Repos:
        if self.fail:
            raise OSError("connection refused")
        self.dims = (memories_dim, news_dim)

        async def close() -> None:
            self.closed = True

        return Repos(self.corrections, FakeCosts(), close)


def _manifest(appid: int, name: str) -> str:
    return (
        f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n'
        f'\t"StateFlags"\t\t"4"\n\t"installdir"\t\t"{name}"\n}}\n'
    )


GAMES = {588650: "Dead Cells", 1145360: "Hades", 367520: "Hollow Knight"}


class Launched(list):
    def __call__(self, argv) -> None:
        self.append(list(argv))


def fake_handlers(launched: Launched, tmp: Path):
    """Ações reais com efeitos falsos."""

    def boom(*a, **k):
        raise AssertionError("efeito real chamado no teste")

    def make(catalog, hud_sink, corrections):
        return [
            *games.handlers(
                catalog, launcher=launched, wrapper=tmp / "sem-wrapper", table=games.ProcFs(tmp), killer=boom
            ),
            *hud.handlers(hud_sink, settings_path=tmp / "hud.json", runner=boom),
            *system.handlers(pulse_factory=boom, orgb=object()),  # type: ignore[arg-type]
            *spotify_mpris.handlers(spotify_mpris.SpotifyMpris(bus_factory=boom, launcher=boom)),
            *(correction_handlers(corrections) if corrections else []),
        ]

    return make


# ---------------------------------------------------------------------------------------------
# Satélite e HUD falsos
# ---------------------------------------------------------------------------------------------


class Sat:
    def __init__(self, reader, writer) -> None:
        self.reader, self.writer = reader, writer

    @classmethod
    async def connect(cls, port: int) -> Sat:
        sat = cls(*await asyncio.open_connection("127.0.0.1", port))
        await sat.send(SatelliteHello(satellite="pc"))
        return sat

    async def send(self, msg) -> None:
        await async_write_event(msg if isinstance(msg, Event) else to_event(msg), self.writer)

    async def say(self, text: str) -> None:
        """Ativa, fala e espera a resposta inteira; devolve a fala recebida (em blocos)."""
        await self.send(WakeEvent(source=WakeSource.WAKE, satellite="pc"))
        await self.send(audio_start())
        await self.send(audio_chunk(text.encode("utf-8")))
        await self.send(AudioEnd(reason=AudioEndReason.VAD))

    async def hear(self) -> int:
        """Recebe uma fala inteira e confirma o fim da reprodução."""
        ev = await asyncio.wait_for(async_read_event(self.reader), T)
        assert ev is not None and ev.type == EventType.AUDIO_START, ev
        chunks = 0
        while (ev := await asyncio.wait_for(async_read_event(self.reader), T)).type == EventType.AUDIO_CHUNK:
            chunks += 1
        assert ev.type == EventType.AUDIO_STOP
        await self.send(PlaybackDone(satellite="pc"))
        return chunks


async def _until(cond, timeout: float = T) -> None:
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.005)


class Rig:
    def __init__(self, core: Core, service: CoreService, hud_server: HudServer, sat: Sat, hud_reader) -> None:
        self.core, self.service, self.hud_server, self.sat = core, service, hud_server, sat
        self.hud_reader = hud_reader
        self.subtitles: list[SubtitleMsg] = []

    @property
    def state(self) -> TurnState:
        m = self.service.machine("pc")
        assert m is not None
        return m.state

    async def subtitle(self) -> SubtitleMsg:
        while True:
            line = await asyncio.wait_for(self.hud_reader.readline(), T)
            assert line
            msg = decode_hud(line)
            if isinstance(msg, SubtitleMsg):
                self.subtitles.append(msg)
                return msg


@pytest.fixture
def tmp():
    d = Path(tempfile.mkdtemp(prefix="magi-"))  # curto: socket Unix tem limite de tamanho
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_config(tmp: Path) -> Config:
    return parse_config(
        {
            "providers": {"fake": {"keys": ["fake-1"]}},
            "tasks": {
                "stt": {"provider": "fake", "model": "m"},
                "tts": {"provider": "fake", "model": "m", "voice": "v"},
                "embeddings": {"provider": "fake", "model": "e"},
            },
            "paths": {"data_dir": str(tmp / "data"), "cache_dir": str(tmp / "cache")},
            "database": {"dsn": "postgresql://magi:x@127.0.0.1:1/magi"},
        }
    )


def make_catalog(tmp: Path) -> SteamCatalog:
    apps = tmp / "Steam" / "steamapps"
    apps.mkdir(parents=True)
    for appid, name in GAMES.items():
        (apps / f"appmanifest_{appid}.acf").write_text(_manifest(appid, name))
    return SteamCatalog(tmp / "Steam", aliases=MemoryAliasStore())


@pytest.fixture
async def rig_factory(tmp: Path):
    made: list[Rig] = []

    async def make(*, keys: int = 1, db: FakeDb | None = None, launched: Launched | None = None) -> Rig:
        hud_server = HudServer(tmp / "hud.sock")
        core = await assemble(
            make_config(tmp),
            hud_server,
            providers=lambda cfg, budget: FakeProviders(cfg, budget, keys),
            open_db=db if db is not None else FakeDb(),
            catalog=make_catalog(tmp),
            handlers=fake_handlers(launched if launched is not None else Launched(), tmp),
            agent=None,  # agente nulo
        )
        await hud_server.start()
        service = CoreService(core.deps, hud_server, port=0)
        await service.start()
        reader, writer = await asyncio.open_unix_connection(str(hud_server.path))
        await _until(lambda: hud_server.clients == 1)
        sat = await Sat.connect(service.port)
        await _until(lambda: service.machine("pc") is not None)
        rig = Rig(core, service, hud_server, sat, reader)
        rig.hud_writer = writer  # guardar: o GC fecharia a conexão
        made.append(rig)
        return rig

    yield make
    for rig in made:
        rig.sat.writer.close()
        rig.hud_writer.close()
        await rig.service.stop()
        await rig.hud_server.stop()
        await rig.core.aclose()


# ---------------------------------------------------------------------------------------------
# Ponta a ponta
# ---------------------------------------------------------------------------------------------


async def test_abre_jogo_de_ponta_a_ponta(rig_factory) -> None:
    launched, db = Launched(), FakeDb()
    rig = await rig_factory(launched=launched, db=db)
    assert isinstance(rig.core.budget.inner, MonthlyBudget)
    assert db.dims == (8, None)  # dimensão dos embeddings da config

    await rig.sat.say("abre o dedi cels")
    assert await rig.sat.hear() >= 1
    sub = await rig.subtitle()
    assert "Dead Cells" in sub.text
    assert launched == [["steam", "steam://rungameid/588650"]]
    await _until(lambda: rig.state is TurnState.SLEEPING)
    # a dica do STT leva os nomes dos jogos
    assert "Dead Cells" in rig.core.deps.stt.inner.hints[0]  # type: ignore[union-attr]


async def test_pergunta_vai_ao_agente_nulo(rig_factory) -> None:
    rig = await rig_factory()
    await rig.sat.say("qual é a capital da frança")
    await rig.sat.hear()
    assert (await rig.subtitle()).text == SAY_UNAVAILABLE


async def test_nao_eu_falei_refaz_o_turno(rig_factory) -> None:
    launched, db = Launched(), FakeDb()
    rig = await rig_factory(launched=launched, db=db)

    await rig.sat.say("abre o radis")
    await rig.sat.hear()
    first = await rig.subtitle()
    assert not launched, first

    await rig.sat.say("não, eu falei Hades")
    await rig.sat.hear()
    sub = await rig.subtitle()
    assert sub.text.startswith("Anotado.") and "Hades" in sub.text
    assert launched == [["steam", "steam://rungameid/1145360"]]
    assert [(c.heard, c.correct.casefold()) for c in await db.corrections.all()] == [("radis", "hades")]
    machine = rig.service.machine("pc")
    assert machine is not None and machine._last_text.casefold() == "abre o hades"  # noqa: SLF001

    # próxima vez a correção vale antes do roteador
    await rig.sat.say("abre o radis")
    await rig.sat.hear()
    await rig.subtitle()
    assert len(launched) == 2


# ---------------------------------------------------------------------------------------------
# Degradação
# ---------------------------------------------------------------------------------------------


async def test_sem_chave_e_sem_banco_degrada_com_aviso_unico(rig_factory, caplog) -> None:
    caplog.set_level(logging.WARNING, "magi.core.assemble")
    rig = await rig_factory(keys=0, db=FakeDb(fail=True))
    core = rig.core
    assert core.deps.stt is None and core.deps.speaker is None
    assert isinstance(core.budget.inner, NullBudget)
    assert core.corrections is not None  # correções só em memória
    warns = [r.getMessage() for r in caplog.records]
    assert sum("Postgres indisponível" in w for w in warns) == 1
    assert any(w.startswith("STT: sem chave") for w in warns)
    assert any(w.startswith("TTS: sem chave") for w in warns)
    assert all("x@" not in w for w in warns)  # senha do DSN não vai para o log

    await rig.sat.say("abre o dedi cels")
    assert (await rig.subtitle()).text == SAY_NOT_HEARD  # sem STT, só legenda
    await _until(lambda: rig.state is TurnState.SLEEPING)


async def test_provedores_quebrados_nao_derrubam(tmp: Path) -> None:
    def broken(cfg, budget):
        raise RuntimeError("config ruim")

    core = await assemble(
        make_config(tmp), hud_sink=_NullSink(), providers=broken, open_db=None, catalog=make_catalog(tmp)
    )
    assert core.providers is None and core.deps.router is not None and core.deps.actions is not None
    assert any("provedores indisponíveis" in w for w in core.warnings)
    await core.aclose()


class _NullSink:
    async def send(self, msg) -> None:
        return None


def test_acoes_padrao_cobrem_os_modulos(tmp: Path) -> None:
    from magi.core.corrections import Corrections

    corr = Corrections(MemoryCorrectionsRepo())
    reg = actions.Registry(default_handlers(make_catalog(tmp), _NullSink(), corr))
    for iid in (
        IntentId.GAME_OPEN,
        IntentId.GAME_CLOSE,
        IntentId.HUD_OPEN,
        IntentId.VOLUME_SET,
        IntentId.RGB_COLOR,
        IntentId.MUSIC_PLAY,
        IntentId.CORRECTION,
    ):
        assert reg.handles(iid), iid


# ---------------------------------------------------------------------------------------------
# redo_text e previous_text no turno
# ---------------------------------------------------------------------------------------------

CTX = TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime(2026, 1, 1, tzinfo=UTC))


async def test_redo_e_tratado_uma_vez() -> None:
    seen: list[str] = []

    class Router:
        def route(self, text, ctx):
            seen.append(text)
            return RouteResult(RouteKind.LOCAL, text, 99, Intent(IntentId.CORRECTION))

    class Fix:
        intents = frozenset({IntentId.CORRECTION.value})

        async def run(self, req):
            return ActionResult(ok=True, speech=f"R{len(seen)}.", redo_text=req.text + "!")

    pipe = TurnPipeline(TurnDeps(router=Router(), actions=actions.Registry([Fix()])))
    res = await pipe.respond(Transcript.raw("x"), CTX)
    assert seen == ["x", "x!"]
    assert res.speech == "R1. R2." and res.redo_text == "x!"


async def test_agente_padrao_com_chave(tmp: Path) -> None:
    cfg = make_config(tmp)
    cfg.tasks["agent"] = cfg.tasks["stt"]
    core = await assemble(
        cfg,
        _NullSink(),
        providers=lambda c, b: FakeProviders(c, b),
        open_db=None,
        catalog=make_catalog(tmp),
        handlers=fake_handlers(Launched(), tmp),
    )
    from magi.agent.graph import GraphAgent

    assert isinstance(core.deps.agent, GraphAgent)
    # 3.9: ficha ligada ao registro e ao agente; magi.help responde local.
    assert core.deps.actions.handles(IntentId.HELP)
    assert "self_info" in core.self_model.tool_names() and core.self_model.agent_ready
    assert core.self_model.registry is core.deps.actions
    await core.aclose()


async def test_entrega_de_noticias_ligada_com_banco(tmp: Path) -> None:
    class NewsDb(FakeDb):
        async def __call__(self, config, memories_dim, news_dim) -> Repos:
            repos = await super().__call__(config, memories_dim, news_dim)
            repos.news = object()
            return repos

    def no_providers(cfg, budget):
        raise RuntimeError("sem provedores")

    catalog = make_catalog(tmp)
    raw = make_config(tmp).raw | {"news": {"delivery": {"max_per_hour": 1, "poll_s": 3600}}}
    core = await assemble(parse_config(raw), hud_sink=_NullSink(), providers=no_providers, open_db=NewsDb(),
                          catalog=catalog, agent=None)
    assert core.news is not None and core.news.cfg.max_per_hour == 1
    core.start_proactive(lambda: [])
    await core.aclose()
    sem_banco = await assemble(make_config(tmp), hud_sink=_NullSink(), providers=no_providers, open_db=None,
                               catalog=catalog, agent=None)
    assert sem_banco.news is None
    await sem_banco.aclose()
