"""Mensagens ``lm_*`` no socket do HUD (LM1.2, spec §6, design §9, CA-18)."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hud import hud_bridge
from magi.common.contracts import (
    LM_TEXT_MAX_BYTES,
    CmdMsg,
    Expression,
    LearningHudMsg,
    LmActionMsg,
    LmCfgMsg,
    LmModeMsg,
    LmMsgMsg,
    LmObsMsg,
    LmResultMsg,
    LmSavedMsg,
    LmSaveMsg,
    LmSayMsg,
    LmSessionMsg,
    LmSummaryMsg,
    LmTopicMsg,
    StateMsg,
    SubtitleMsg,
    clip_lm_text,
)
from magi.common.events import _HUD_DECODERS, HudDecodeError, decode_hud, encode_hud_line
from magi.core.hud_client import HudServer
from magi.learning import contracts as c

T = 3.0
AT = datetime(2026, 10, 7, 21, 30, tzinfo=UTC)
SID = "LS-20261007-01"


def _summary() -> c.SessionSummary:
    return c.SessionSummary(
        session_id=SID, n=1, started_at=AT, ended_at=AT, duration_s=600, end_reason="button",
        n_msgs=8, n_you=4, obs_count=2, practiced=["past simple"], new_words=["nevertheless"],
        saved=["nevertheless"], more_practiced=0, more_words=0, topics=["free"],
    )


def _samples() -> list[LearningHudMsg]:
    result = c.ActionResult(
        id="ACT-0123abcd", kind=c.ActionKind.TRANSLATE, ok=True, data={"translation": "oi"},
        error=None, cached=False, ms=420, cost_usd=0.0001,
    )
    obs = c.Observation(
        id=7, session_id=SID, message_id=3, category=c.ObsCategory.GRAMMAR,
        rule_key="grammar.past_simple.irregular", label="went → gone", span="have went",
        suggestion="have gone",
    )
    return [
        LmModeMsg(on=True),
        LmModeMsg(on=False),
        LmSessionMsg(SID, AT, "B2", "CONVERSATION", c.Topic.FREE, n_msgs=3, obs_count=1),
        LmSayMsg("I have went to the store"),
        LmMsgMsg(3, c.Author.YOU, c.Source.VOICE, "I have went", AT, text_final="I have gone"),
        LmMsgMsg(4, c.Author.CONDESSA, c.Source.TEXT, "Nice!", AT, speaking=True),
        LmActionMsg("ACT-0123abcd", c.ActionKind.EXPLAIN, 3, 0, 6),
        LmResultMsg(result),
        LmObsMsg((obs,)),
        LmObsMsg(()),
        LmCfgMsg(speak_replies=False),
        LmCfgMsg(mic_muted=True, speak_replies=True),
        LmTopicMsg(c.Topic.GAME),
        LmTopicMsg(c.Topic.FREE, requested=c.Topic.GAME, label="FREE TALK", detail="no game detected"),
        LmSaveMsg("ACT-0123abcd", on=True),
        LmSavedMsg("nevertheless", saved=True, id=12),
        LmSavedMsg("nevertheless", saved=False),
        LmSummaryMsg(_summary()),
    ]


# -- contratos e decoders ----------------------------------------------------------------------


def test_all_spec_types_registered():
    spec = {"lm_mode", "lm_session", "lm_say", "lm_msg", "lm_action", "lm_result", "lm_obs",
            "lm_cfg", "lm_topic", "lm_save", "lm_saved", "lm_summary"}
    assert {m.T for m in _samples()} == spec
    assert spec <= set(_HUD_DECODERS)
    assert spec <= set(hud_bridge._MIN_DECODERS)
    assert "lm_hello" not in _HUD_DECODERS  # LM0.2 = (b): sem lm_hello


@pytest.mark.parametrize("msg", _samples(), ids=lambda m: m.T)
def test_round_trip(msg):
    line = encode_hud_line(msg)
    assert line.endswith(b"\n") and line.count(b"\n") == 1
    assert decode_hud(line) == msg
    d = json.loads(line)
    assert d["t"] == msg.T
    # O HUD (decoder do contrato e o mínimo) entrega o mesmo dict.
    assert hud_bridge._decode_magi(line) == msg.to_dict()
    assert hud_bridge._decode_min(line) == msg.to_dict()


def test_result_and_summary_are_domain_json():
    r = _samples()[7]
    assert isinstance(r, LmResultMsg)
    d = r.to_dict()
    assert d.pop("t") == "lm_result" and d == r.result.to_dict()
    s = LmSummaryMsg(_summary()).to_dict()
    assert s.pop("t") == "lm_summary" and c.SessionSummary.from_dict(s) == _summary()


@pytest.mark.parametrize(
    "line",
    [
        '{"t":"lm_mode"}',
        '{"t":"lm_mode","on":1}',
        '{"t":"lm_say"}',
        '{"t":"lm_msg","id":1,"author":"bot","source":"text","text":"x","at":"2026-10-07T00:00:00+00:00"}',
        '{"t":"lm_msg","id":1,"author":"you","source":"text","text":"x","at":"ontem"}',
        '{"t":"lm_action","id":"a","kind":"ask","message_id":1,"start":0,"end":2}',
        '{"t":"lm_action","id":"a","kind":"explain","message_id":1,"start":3,"end":3}',
        '{"t":"lm_result","id":"a"}',
        '{"t":"lm_obs","items":[1]}',
        '{"t":"lm_topic","topic":"music"}',
        '{"t":"lm_save","action_id":"a"}',
        '{"t":"lm_saved","norm":"x","saved":"yes"}',
        '{"t":"lm_summary","session_id":"x"}',
        '{"t":"lm_hello"}',
    ],
)
def test_invalid_lines_raise(line):
    with pytest.raises(HudDecodeError):
        decode_hud(line)


@pytest.mark.parametrize("cls", [LmSayMsg, LmMsgMsg])
@pytest.mark.parametrize("char", ["a", "ç", "語", "\x01", '"'])
def test_text_capped_at_16k(cls, char):
    big = char * (70 * 1024)
    msg = LmSayMsg(big) if cls is LmSayMsg else LmMsgMsg(1, c.Author.CONDESSA, c.Source.TEXT, big, AT)
    assert len(json.dumps(msg.text, ensure_ascii=False).encode()) <= LM_TEXT_MAX_BYTES
    assert big.startswith(msg.text) and len(msg.text) > 1000
    line = encode_hud_line(msg)
    assert len(line) < hud_bridge.MAX_LINE  # cabe na linha de 64 KiB dos dois lados
    assert decode_hud(line) == msg


def test_text_final_capped_and_short_text_untouched():
    m = LmMsgMsg(1, c.Author.YOU, c.Source.VOICE, "hi", AT, text_final="x" * 40_000)
    assert m.text == "hi"
    assert len(m.text_final or "") == LM_TEXT_MAX_BYTES - 2
    assert clip_lm_text("olá") == "olá"


# -- HudServer: filtro por modo (CA-18) --------------------------------------------------------


@pytest.fixture
def sock_dir():
    d = Path(tempfile.mkdtemp(prefix="magi-"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


async def _until(cond, timeout: float = T) -> None:
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.01)


class Client:
    """Cliente "antigo" do socket: lê linhas cruas, sem nada de Learning (sem ``lm_hello``)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader, self.writer = reader, writer
        self.lines: list[dict] = []
        self.task = asyncio.create_task(self._read())

    @classmethod
    async def open(cls, server: HudServer) -> Client:
        n = server.clients
        reader, writer = await asyncio.open_unix_connection(str(server.path))
        await _until(lambda: server.clients == n + 1)
        return cls(reader, writer)

    async def _read(self) -> None:
        while line := await self.reader.readline():
            self.lines.append(json.loads(line))

    def types(self) -> list[str]:
        return [d["t"] for d in self.lines]

    async def close(self) -> None:
        self.writer.close()
        self.task.cancel()


async def _flush(server: HudServer, *clients: Client) -> None:
    """Marcador: manda um ``subtitle`` e espera todos os clientes o receberem."""
    mark = SubtitleMsg(f"mark-{id(object())}")
    await server.send(mark)
    await _until(lambda: all(cl.lines and cl.lines[-1] == mark.to_dict() for cl in clients))


async def test_outside_mode_no_lm_is_published(sock_dir):
    server = HudServer(sock_dir / "hud.sock")
    await server.start()
    try:
        cl = await Client.open(server)
        await server.send(StateMsg(Expression.LISTENING))
        for m in _samples():
            if not isinstance(m, LmModeMsg):
                await server.send(m)
        await server.send(SubtitleMsg("oi"))
        await _flush(server, cl)
        assert not server.learning
        assert not any(t.startswith("lm_") for t in cl.types())
        assert cl.types()[:2] == ["state", "subtitle"]  # mesmas mensagens de antes
        await cl.close()
    finally:
        await server.stop()


async def test_mode_on_publishes_and_summary_only_after_close(sock_dir):
    server = HudServer(sock_dir / "hud.sock")
    await server.start()
    try:
        cl = await Client.open(server)
        msg = LmMsgMsg(1, c.Author.YOU, c.Source.TEXT, "hello", AT)
        summary = LmSummaryMsg(_summary())
        await server.send(LmModeMsg(on=True))
        await server.send(msg)
        await server.send(summary)  # no modo: descartado (só depois do lm_mode off)
        await server.send(LmModeMsg(on=False))
        await server.send(msg)  # fora do modo: descartado
        await server.send(summary)  # logo após o fechamento: passa
        await server.send(summary)  # só uma vez
        await _flush(server, cl)
        assert cl.types()[:-1] == ["lm_mode", "lm_msg", "lm_mode", "lm_summary"]
        assert cl.lines[0]["on"] is True and cl.lines[2]["on"] is False
        await cl.close()
    finally:
        await server.stop()


async def test_late_client_gets_mode_on_and_all_clients_get_lm(sock_dir):
    server = HudServer(sock_dir / "hud.sock")
    await server.start()
    try:
        old = await Client.open(server)
        await server.send(StateMsg(Expression.LISTENING))
        await server.send(LmModeMsg(on=True))
        late = await Client.open(server)
        await _until(lambda: len(late.lines) >= 2)
        assert late.types()[:2] == ["state", "lm_mode"]
        await server.send(LmSessionMsg(SID, AT, "B2", "CONVERSATION", c.Topic.FREE))
        await _flush(server, old, late)
        assert "lm_session" in old.types() and "lm_session" in late.types()
        await server.send(LmModeMsg(on=False))
        after = await Client.open(server)
        await _flush(server, after)
        assert after.types() == ["state", "subtitle"]  # modo desligado: sem replay de lm_mode
        for cl in (old, late, after):
            await cl.close()
    finally:
        await server.stop()


async def test_inbound_lm_goes_to_on_learning_and_bad_lines_keep_connection(sock_dir):
    got: list[LearningHudMsg] = []
    cmds: list[CmdMsg] = []

    async def on_learning(msg: LearningHudMsg) -> None:
        got.append(msg)

    async def on_command(msg: CmdMsg) -> None:
        cmds.append(msg)

    server = HudServer(sock_dir / "hud.sock", on_command=on_command, on_learning=on_learning)
    await server.start()
    try:
        cl = await Client.open(server)
        cl.writer.write(b'{"t":"lm_hello"}\n{"t":"lm_zzz","x":1}\n')
        cl.writer.write(encode_hud_line(LmSayMsg("hello there")))
        cl.writer.write(encode_hud_line(LmModeMsg(on=True)))
        cl.writer.write(encode_hud_line(CmdMsg("push_to_talk")))
        await cl.writer.drain()
        await _until(lambda: len(got) == 2 and len(cmds) == 1)
        assert got == [LmSayMsg("hello there"), LmModeMsg(on=True)]
        assert server.clients == 1
        await cl.close()
    finally:
        await server.stop()


@pytest.mark.parametrize("decode", [hud_bridge._decode_magi, hud_bridge._decode_min])
def test_bridge_decoders_reject_unknown_lm(decode):
    # ``HudBridge.feed_line`` captura ``DecodeError`` e segue (LM0.2): tipo novo não derruba o HUD.
    with pytest.raises(hud_bridge.DecodeError):
        decode('{"t":"lm_hello"}')
    assert decode(LmModeMsg(on=True).to_json()) == {"t": "lm_mode", "on": True}
