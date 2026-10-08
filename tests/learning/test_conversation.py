"""LM1.3 / CA-05: conversa do Learning Mode no núcleo (spec §4, §6, §10; LM-001..LM-004).

- ``lm_say`` gera duas ``lm_msg`` (Pedro ``text`` + Condessa) e passa por ``TurnPipeline.respond``.
- Voz: depois da entrega, ``heard`` vai em ``text`` e ``final`` em ``text_final``.
- ``speak_replies``; fora do modo nada é gravado/publicado; ``[learning] enabled = false`` não
  muda nada no núcleo.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from wyoming.event import Event, async_write_event

from magi.common.config import parse_config
from magi.common.contracts import (
    ActionResult,
    AudioEnd,
    AudioEndReason,
    HudMessage,
    LmCfgMsg,
    LmModeMsg,
    LmMsgMsg,
    LmSayMsg,
    LmSessionMsg,
    PcmFormat,
    RouteKind,
    RouteResult,
    SatelliteHello,
    SatelliteLink,
    SubtitleMsg,
    ToneMetadata,
    Transcript,
    TurnContext,
    WakeEvent,
    WakeSource,
)
from magi.common.events import audio_chunk, audio_start, decode_hud, to_event
from magi.core.hud_client import HudServer
from magi.core.service import CoreService, _install_learning
from magi.core.turn import TurnDeps, TurnPipeline
from magi.learning.config import LearningConfig
from magi.learning.contracts import Author, Source
from magi.learning.repo import JsonlRepo
from magi.learning.wiring import LearningWiring, install

T = 3.0

# ---------------------------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------------------------


class FakeAgent:
    def __init__(self) -> None:
        self.asked: list[tuple[str, TurnContext]] = []

    async def answer(self, text: str, ctx: TurnContext) -> ActionResult:
        self.asked.append((text, ctx))
        return ActionResult(ok=True, speech="Oh, where did you go?")


class FakeRouter:
    def route(self, text: str, ctx: TurnContext) -> RouteResult:
        return RouteResult(RouteKind.AGENT, text)


class FakeStt:
    name = model = "fake"
    free_tier = False

    async def transcribe(self, audio: bytes, fmt: PcmFormat, *, hint: str = "", language: str = "pt",
                         personal: bool) -> Transcript:
        return Transcript.raw(audio.decode("utf-8").strip())


class FakeCorrector:
    """Simula o Corrector "consertando" a gramática: o Improve precisa do ``heard`` (LM-002)."""

    async def apply(self, transcript: Transcript) -> Transcript:
        return transcript.with_final(transcript.heard.replace("have went", "went"))


class FakeSpeaker:
    def __init__(self) -> None:
        self.said: list[str] = []

    async def say(self, text: str, link: SatelliteLink, *, personal: bool) -> None:
        self.said.append(text)

        async def pcm():
            yield b"\x01\x00" * 100

        await link.play(pcm(), PcmFormat())


class SinkHud:
    """``HudSink`` em memória (sem socket)."""

    def __init__(self) -> None:
        self.sent: list[HudMessage] = []
        self.on_learning = None

    async def send(self, msg: HudMessage) -> None:
        self.sent.append(msg)

    def of(self, kind: type) -> list:
        return [m for m in self.sent if isinstance(m, kind)]


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 7, 20, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _cfg(**kw) -> LearningConfig:
    return LearningConfig(storage="jsonl", **kw)


def _rows(root: Path) -> list[dict]:
    out = []
    for f in sorted(root.glob("LS-*.jsonl")):
        out += [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
    return out


@pytest.fixture
def text_rig(tmp_path):
    def make(*, speak=None, clock=None, **cfg) -> tuple[LearningWiring, SinkHud, FakeAgent]:
        agent = FakeAgent()
        pipeline = TurnPipeline(TurnDeps(router=FakeRouter(), agent=agent))
        hud = SinkHud()
        w = install(_cfg(**cfg), hud, pipeline, repo=JsonlRepo(tmp_path), speak=speak,
                    clock=clock or Clock(), start=False)
        assert w is not None
        return w, hud, agent

    return make


# ---------------------------------------------------------------------------------------------
# Texto (CA-05, LM-001)
# ---------------------------------------------------------------------------------------------


async def test_lm_say_gera_duas_lm_msg(text_rig, tmp_path) -> None:
    w, hud, agent = text_rig()
    await hud.on_learning(LmModeMsg(True))
    assert hud.of(LmModeMsg) == [LmModeMsg(True)]
    (sess,) = hud.of(LmSessionMsg)
    assert sess.id.startswith("LS-") and sess.level == "B2"

    await hud.on_learning(LmSayMsg("Yesterday I have went to the park"))
    await w.wait_idle()

    you, condessa = hud.of(LmMsgMsg)
    assert (you.author, you.source) == (Author.YOU, Source.TEXT)
    assert you.text == "Yesterday I have went to the park"
    assert you.text_final is None and not you.speaking
    assert (condessa.author, condessa.text) == (Author.CONDESSA, "Oh, where did you go?")
    assert condessa.id > you.id
    # passou pelo mesmo TurnPipeline.respond (sem STT), texto cru
    (asked, ctx), = agent.asked
    assert asked == "Yesterday I have went to the park" and ctx.satellite == "learning"
    # gravadas no repositório da sessão
    msgs = await w.repo.recent_messages(sess.id)
    assert [(m.author, m.text) for m in msgs] == [(Author.YOU, you.text), (Author.CONDESSA, condessa.text)]


async def test_lm_say_vazio_ou_longo_e_recusado(text_rig) -> None:
    w, hud, agent = text_rig()
    await w.set_mode(True)
    await hud.on_learning(LmSayMsg("   "))
    await hud.on_learning(LmSayMsg("a" * 2001))
    await w.wait_idle()
    assert hud.of(LmMsgMsg) == [] and agent.asked == []


async def test_speak_replies_liga_e_desliga(text_rig) -> None:
    spoken: list[str] = []

    async def speak(result: ActionResult) -> bool:
        spoken.append(result.speech)
        return True

    w, hud, _ = text_rig(speak=speak)
    await w.set_mode(True)
    await hud.on_learning(LmSayMsg("hello"))
    await w.wait_idle()
    assert spoken == ["Oh, where did you go?"]
    assert hud.of(LmMsgMsg)[-1].speaking is True

    await hud.on_learning(LmCfgMsg(speak_replies=False))
    await hud.on_learning(LmSayMsg("hello again"))
    await w.wait_idle()
    assert spoken == ["Oh, where did you go?"]  # não foi ao TTS
    last = hud.of(LmMsgMsg)[-1]
    assert last.author is Author.CONDESSA and last.speaking is False


async def test_speak_replies_false_no_config(text_rig) -> None:
    called = []

    async def speak(result: ActionResult) -> bool:
        called.append(result)
        return True

    w, hud, _ = text_rig(speak=speak, speak_replies=False)
    await w.set_mode(True)
    await hud.on_learning(LmSayMsg("hi"))
    await w.wait_idle()
    assert called == [] and len(hud.of(LmMsgMsg)) == 2


async def test_fora_do_modo_lm_say_e_voz_nao_fazem_nada(text_rig, tmp_path) -> None:
    w, hud, agent = text_rig()
    await hud.on_learning(LmSayMsg("hello"))
    w.on_turn(Transcript.raw("hello"), TurnContext("pc", WakeSource.WAKE, datetime.now(UTC)),
              ActionResult(ok=True, speech="Hi."))
    await w.wait_idle()
    assert hud.sent == [] and agent.asked == []
    assert _rows(tmp_path) == []


# ---------------------------------------------------------------------------------------------
# Modo: botão, retomada, inatividade, desligamento (spec §10)
# ---------------------------------------------------------------------------------------------


async def test_modo_off_fecha_sessao_com_button(text_rig) -> None:
    w, hud, _ = text_rig()
    await hud.on_learning(LmModeMsg(True))
    sid = w.session.id
    await hud.on_learning(LmModeMsg(False))
    assert hud.sent[-1] == LmModeMsg(False) and not w.session.active
    assert (await w.repo.get_session(sid)).end_reason == "button"


async def test_retomada_reenvia_historico(text_rig) -> None:
    w, hud, _ = text_rig()
    await w.set_mode(True)
    await hud.on_learning(LmSayMsg("hello"))
    await w.wait_idle()
    hud.sent.clear()
    await w.set_mode(True)  # gamerhud reiniciado pede de novo: confirma e recarrega
    assert isinstance(hud.sent[0], LmModeMsg) and isinstance(hud.sent[1], LmSessionMsg)
    assert hud.sent[1].n_msgs == 2
    assert [m.text for m in hud.of(LmMsgMsg)] == ["hello", "Oh, where did you go?"]


async def test_inatividade_fecha_e_confirma_off(text_rig) -> None:
    clock = Clock()
    w, hud, _ = text_rig(clock=clock, idle_end_min=20)
    await w.set_mode(True)
    sid = w.session.id
    clock.now += timedelta(minutes=19)
    assert await w.check_idle() is False
    clock.now += timedelta(minutes=1)
    assert await w.check_idle() is True
    assert hud.sent[-1] == LmModeMsg(False)
    assert (await w.repo.get_session(sid)).end_reason == "idle"


async def test_desligamento_fecha_com_shutdown(text_rig) -> None:
    w, _, _ = text_rig()
    await w.set_mode(True)
    sid = w.session.id
    await w.aclose()
    assert (await w.repo.get_session(sid)).end_reason == "shutdown"


async def test_set_mode_por_voz_usa_motivo(text_rig) -> None:
    w, _, _ = text_rig()
    await w.set_mode(True)
    sid = w.session.id
    await w.set_mode(False, "voice")
    await w.set_mode(False, "voice")  # já desligado: só confirma
    assert (await w.repo.get_session(sid)).end_reason == "voice"


# ---------------------------------------------------------------------------------------------
# Voz pelo núcleo de verdade (satélite e HUD por socket) — CA-05
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def sock_dir():
    d = Path(tempfile.mkdtemp(prefix="magi-lm-"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


class Rig:
    def __init__(self, service, hud_server, sat_writer, hud_reader, hud_writer, wiring, speaker):
        self.service, self.hud_server = service, hud_server
        self.sat_writer, self.hud_reader, self.hud_writer = sat_writer, hud_reader, hud_writer
        self.wiring, self.speaker = wiring, speaker
        self.seen: list[HudMessage] = []

    async def say(self, text: str) -> None:
        for msg in (WakeEvent(source=WakeSource.WAKE, satellite="pc", score=0.9), audio_start(),
                    audio_chunk(text.encode("utf-8")),
                    AudioEnd(reason=AudioEndReason.VAD, tone=ToneMetadata(-20.0, 4.0, 1200))):
            event = msg if isinstance(msg, Event) else to_event(msg)
            await async_write_event(event, self.sat_writer)

    async def until(self, cond, timeout: float = T) -> None:
        async with asyncio.timeout(timeout):
            while not cond(self.seen):
                line = await self.hud_reader.readline()
                assert line, "HUD desconectado"
                self.seen.append(decode_hud(line))


async def _wait(cond, timeout: float = T) -> None:
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.005)


@pytest.fixture
async def make_voice_rig(sock_dir, tmp_path):
    rigs: list[Rig] = []

    async def make(*, learning: LearningConfig | None) -> Rig:
        speaker = FakeSpeaker()
        deps = TurnDeps(stt=FakeStt(), corrector=FakeCorrector(), router=FakeRouter(),
                        agent=FakeAgent(), speaker=speaker)
        hud_server = HudServer(sock_dir / "hud.sock")
        await hud_server.start()
        service = CoreService(deps, hud_server, port=0)
        await service.start()
        wiring = install(learning, hud_server, service.pipeline, repo=JsonlRepo(tmp_path),
                         start=False) if learning is not None else None
        reader, writer = await asyncio.open_unix_connection(str(hud_server.path))
        await _wait(lambda: hud_server.clients == 1)
        _, sat_writer = await asyncio.open_connection("127.0.0.1", service.port)
        await async_write_event(to_event(SatelliteHello(satellite="pc")), sat_writer)
        await _wait(lambda: service.machine("pc") is not None)
        rig = Rig(service, hud_server, sat_writer, reader, writer, wiring, speaker)
        rigs.append(rig)
        return rig

    yield make
    for rig in rigs:
        rig.sat_writer.close()
        rig.hud_writer.close()
        if rig.wiring is not None:
            await rig.wiring.aclose()
        await rig.service.stop()
        await rig.hud_server.stop()


def _lm_msgs(seen: list[HudMessage]) -> list[LmMsgMsg]:
    return [m for m in seen if isinstance(m, LmMsgMsg)]


async def test_voz_grava_heard_em_text_e_final_em_text_final(make_voice_rig, tmp_path) -> None:
    rig = await make_voice_rig(learning=_cfg())
    await rig.wiring.set_mode(True)
    await rig.say("yesterday I have went home")
    await rig.until(lambda seen: len(_lm_msgs(seen)) >= 2)

    you, condessa = _lm_msgs(rig.seen)
    assert (you.author, you.source) == (Author.YOU, Source.VOICE)
    assert you.text == "yesterday I have went home"  # heard (antes do Corrector)
    assert you.text_final == "yesterday I went home"  # final
    assert (condessa.author, condessa.text) == (Author.CONDESSA, "Oh, where did you go?")
    assert condessa.speaking is True
    # gancho depois da entrega: legenda e TTS já saíram antes das lm_msg
    sub = next(i for i, m in enumerate(rig.seen) if isinstance(m, SubtitleMsg))
    assert sub < rig.seen.index(you)
    assert rig.speaker.said == ["Oh, where did you go?"]
    # gravado: heard em text, final em text_final
    (row,) = [r for r in _rows(tmp_path) if r.get("kind") == "msg" and r["msg"]["author"] == "you"]
    assert row["msg"]["text"] == "yesterday I have went home" and row["text_final"] == "yesterday I went home"


async def test_voz_sem_correcao_nao_manda_text_final(make_voice_rig) -> None:
    rig = await make_voice_rig(learning=_cfg())
    await rig.wiring.set_mode(True)
    await rig.say("I went home")
    await rig.until(lambda seen: len(_lm_msgs(seen)) >= 2)
    you = _lm_msgs(rig.seen)[0]
    assert you.text == "I went home" and you.text_final is None


async def test_voz_fora_do_modo_nao_publica_nem_grava(make_voice_rig, tmp_path) -> None:
    rig = await make_voice_rig(learning=_cfg())
    await rig.say("I have went home")
    await rig.until(lambda seen: any(isinstance(m, SubtitleMsg) for m in seen))
    await _wait(lambda: rig.speaker.said != [])
    await rig.wiring.wait_idle()
    assert _lm_msgs(rig.seen) == [] and _rows(tmp_path) == []


# ---------------------------------------------------------------------------------------------
# [learning] enabled = false: nada muda
# ---------------------------------------------------------------------------------------------


def test_enabled_false_nao_instala_nada() -> None:
    pipeline = TurnPipeline(TurnDeps())
    hud = SinkHud()
    assert install(LearningConfig(enabled=False), hud, pipeline) is None
    assert hud.on_learning is None and pipeline.deps.learning is None
    config = parse_config({"learning": {"enabled": False}})
    assert install(config, hud, pipeline) is None
    assert hud.on_learning is None and pipeline.deps.learning is None


async def test_enabled_false_no_servico_nada_muda(sock_dir) -> None:
    hud_server = HudServer(sock_dir / "h.sock")
    service = CoreService(TurnDeps(), hud_server, port=0)
    before = service.pipeline.deps
    snapshot = {f: getattr(before, f) for f in before.__slots__}
    config = parse_config({"learning": {"enabled": False}})
    assert _install_learning(config, None, hud_server, service) is None
    assert hud_server.on_learning is None
    assert {f: getattr(service.pipeline.deps, f) for f in before.__slots__} == snapshot


async def test_enabled_false_turno_de_voz_sem_lm(make_voice_rig) -> None:
    """Com o Learning desligado o turno de voz segue igual: legenda e fala, nenhuma ``lm_*``."""
    off = await make_voice_rig(learning=LearningConfig(enabled=False, storage="jsonl"))
    assert off.wiring is None and off.service.pipeline.deps.learning is None
    assert off.hud_server.on_learning is None
    await off.say("I have went home")
    await off.until(lambda seen: any(isinstance(m, SubtitleMsg) for m in seen))
    await _wait(lambda: off.speaker.said == ["Oh, where did you go?"])
    assert not any(m.T.startswith("lm_") for m in off.seen)


# ---------------------------------------------------------------------------------------------
# Extra B do LM4.1: no texto, a lm_msg da Condessa sai junto com o começo da fala
# ---------------------------------------------------------------------------------------------


def _trace(w: LearningWiring, hud: SinkHud, events: list[str]) -> None:
    """Registra as escritas no repositório e os envios ao HUD na ordem em que acontecem."""
    add = w.repo.add_message

    async def add_message(*a, **kw):
        m = await add(*a, **kw)
        events.append(f"db:{m.author.value}")
        return m

    send = hud.send

    async def hud_send(msg) -> None:
        if isinstance(msg, LmMsgMsg):
            events.append(f"lm_msg:{msg.author.value}:{msg.speaking}")
        await send(msg)

    w.repo.add_message = add_message  # type: ignore[method-assign]
    hud.send = hud_send  # type: ignore[method-assign]


async def test_lm_say_resposta_publicada_no_comeco_da_fala(text_rig) -> None:
    """A resposta é gravada **antes** da fala; a ``lm_msg`` (``speaking = true``) sai logo que a
    fala começa, sem escrita no banco no meio — o HUD a revela acompanhando a legenda (spec §4,
    LM-003) em vez de mostrá-la inteira no fim."""
    events: list[str] = []

    async def speak(result: ActionResult) -> bool:
        events.append("speak")
        return True

    w, hud, _ = text_rig(speak=speak)
    _trace(w, hud, events)
    await w.set_mode(True)
    await hud.on_learning(LmSayMsg("I have went home"))
    await w.wait_idle()
    assert events == ["db:you", "lm_msg:you:False", "db:condessa", "speak", "lm_msg:condessa:True"]
    her = hud.of(LmMsgMsg)[-1]
    assert her.author is Author.CONDESSA and her.speaking is True and her.text == "Oh, where did you go?"
    assert [m.text for m in await w.repo.recent_messages(w.session.id)][-1] == her.text


@pytest.mark.parametrize("outcome", ["ocupado", "erro"])
async def test_lm_say_fala_que_nao_comecou_vai_inteira(text_rig, outcome) -> None:
    """Satélite ocupado (``False``) ou erro no TTS: a mensagem vai com ``speaking = false``."""

    async def speak(result: ActionResult) -> bool:
        if outcome == "erro":
            raise RuntimeError("tts caiu")
        return False

    w, hud, _ = text_rig(speak=speak)
    await w.set_mode(True)
    await hud.on_learning(LmSayMsg("hello"))
    await w.wait_idle()
    you, her = hud.of(LmMsgMsg)
    assert her.author is Author.CONDESSA and her.speaking is False


# ---------------------------------------------------------------------------------------------
# Extra A do LM4.1: o serviço monta o LearningEngine (ações + observações)
# ---------------------------------------------------------------------------------------------


def _learning_config(tmp_path: Path, tasks: dict | None = None, **learning) -> object:
    return parse_config({
        "learning": {"enabled": True, "storage": "jsonl", **learning},
        "providers": {"fake": {"kind": "fake"}},
        "tasks": tasks if tasks is not None else {
            "learning_actions": {"provider": "fake", "model": "acoes", "timeout_s": 8},
            "learning_observe": {"provider": "fake", "model": "obs", "timeout_s": 20},
        },
    })


def _jsonl_here(monkeypatch, root: Path) -> None:
    """O ``install`` do serviço não passa ``jsonl_dir``: o histórico do teste fica em ``root``."""
    monkeypatch.setattr("magi.learning.wiring.make_repo", lambda cfg, **kw: JsonlRepo(root))


class _Core:
    """O que ``_install_learning`` usa do ``Core``: orçamento, provedores e repositórios."""

    def __init__(self, conn=None) -> None:
        from magi.core.budget import MonthlyBudget

        class Costs:
            async def add(self, usage, at) -> int:
                return 1

            async def month_total(self, year: int, month: int) -> float:
                return 0.0

        self.budget = MonthlyBudget(Costs(), cap_usd=5.0, prices={})
        self.providers = None
        self.repos = type("Repos", (), {"conn": conn, "turns": None})()


async def test_servico_monta_o_engine_com_observacao(sock_dir, tmp_path, monkeypatch) -> None:
    from magi.common.contracts import TurnState

    _jsonl_here(monkeypatch, tmp_path)
    hud_server = HudServer(sock_dir / "h.sock")
    service = CoreService(TurnDeps(), hud_server, port=0)
    w = _install_learning(_learning_config(tmp_path), _Core(), hud_server, service)
    try:
        assert isinstance(w, LearningWiring) and w.engine is not None
        eng = w.engine
        assert eng.model.model == "acoes"
        assert eng.observe_model is not None and eng.observe_model.model == "obs"
        assert eng.timeout_s == 10.0 and eng.observe_timeout_s == 22.0  # timeout_s + folga de 2 s
        assert eng.budget is not None and eng.budget.observe_daily_max == 200
        assert eng.options is not None and eng.options.level == "B2"
        assert eng.repo is w.repo and eng.on_observed is not None
        assert eng.gate is not None and eng.gate() is True  # sem satélite conectado
        service._machines = {"pc": type("M", (), {"state": TurnState.SPEAKING})()}  # noqa: SLF001
        assert eng.gate() is False  # gate lê o estado dos satélites conectados
    finally:
        if w is not None:
            await w.aclose()


async def test_servico_sem_modelo_segue_sem_engine(sock_dir, tmp_path, monkeypatch) -> None:
    _jsonl_here(monkeypatch, tmp_path)
    hud_server = HudServer(sock_dir / "h.sock")
    service = CoreService(TurnDeps(), hud_server, port=0)
    # sem [tasks] learning_actions: o modo liga, as ações respondem erro como antes
    w = _install_learning(_learning_config(tmp_path, tasks={}), _Core(), hud_server, service)
    assert isinstance(w, LearningWiring) and w.engine is None
    await w.aclose()
    # sem núcleo montado (sem config de provedores): idem
    w = _install_learning(_learning_config(tmp_path), None, hud_server, service)
    assert isinstance(w, LearningWiring) and w.engine is None
    await w.aclose()
    # observe = false: engine só de ações
    w = _install_learning(_learning_config(tmp_path, observe=False), _Core(), hud_server, service)
    assert w is not None and w.engine is not None and w.engine.observe_model is None
    await w.aclose()


async def test_servico_usa_repos_conn(sock_dir, monkeypatch) -> None:
    """A conexão vem de ``repos.conn`` (LM1.4), não do ``_conn`` privado do repositório de turnos."""
    seen = {}

    def fake_install(config, hud, pipeline, **kw):
        seen.update(kw)
        return None

    monkeypatch.setattr("magi.learning.wiring.install", fake_install)
    hud_server = HudServer(sock_dir / "h.sock")
    service = CoreService(TurnDeps(), hud_server, port=0)
    conn = object()
    _install_learning(parse_config({}), _Core(conn=conn), hud_server, service)
    assert seen["conn"] is conn and callable(seen["engine_factory"])
