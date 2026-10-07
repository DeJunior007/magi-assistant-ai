"""Testes dos contratos e da serialização (tarefa 1.0)."""

import io
import itertools
import json
from datetime import UTC, datetime

import pytest
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import Event, read_event, write_event

from magi.common import contracts as c
from magi.common import events as ev

# ---------------------------------------------------------------------------------------------
# Wyoming
# ---------------------------------------------------------------------------------------------

WIRE_MESSAGES = [
    c.SatelliteHello(satellite="pc", name="PC do Pedro", version="0.1.0"),
    c.SatelliteHello(satellite="sala", capabilities=("wake", "playback")),
    c.WakeEvent(source=c.WakeSource.WAKE, satellite="pc", score=0.87, timestamp=1234),
    c.WakeEvent(source=c.WakeSource.PTT, satellite="pc"),
    c.MouthEvent(level=0.42, satellite="pc"),
    c.MouthEvent(level=0.0),
    c.PlaybackDone(satellite="pc"),
    c.SatelliteStatus(satellite="pc", in_call=True, wake_enabled=False),
    c.ListenRequest(),
    c.ListenRequest(timeout_ms=5000, reason="ask"),
    c.StopPlayback(),
    c.AudioEnd(),
    c.AudioEnd(
        timestamp=900,
        reason=c.AudioEndReason.VAD,
        tone=c.ToneMetadata(energy_db=-23.5, speech_rate=4.2, duration_ms=1840),
    ),
    c.AudioEnd(reason=c.AudioEndReason.NO_SPEECH),
]


def _through_wire(event: Event) -> Event:
    buf = io.BytesIO()
    write_event(event, buf)
    buf.seek(0)
    out = read_event(buf)
    assert out is not None
    return out


@pytest.mark.parametrize("msg", WIRE_MESSAGES, ids=lambda m: type(m).__name__)
def test_wyoming_round_trip(msg):
    event = ev.to_event(msg)
    assert ev.from_event(event) == msg
    assert ev.from_event(_through_wire(event)) == msg


def test_every_event_type_has_a_decoder():
    for t in c.EventType:
        assert ev.is_known(Event(t.value)), t


def test_event_type_names():
    assert ev.to_event(c.WakeEvent(c.WakeSource.WAKE, "pc")).type == "magi-wake"
    assert ev.to_event(c.MouthEvent(0.1)).type == "magi-mouth"
    assert ev.to_event(c.PlaybackDone()).type == "playback-done"
    assert ev.to_event(c.AudioEnd()).type == "audio-stop"


def test_audio_end_is_compatible_with_wyoming_audio_stop():
    event = ev.to_event(c.AudioEnd(timestamp=10, reason=c.AudioEndReason.PTT_RELEASE))
    assert AudioStop.from_event(event).timestamp == 10
    plain = AudioStop(timestamp=5).event()
    assert ev.from_event(plain) == c.AudioEnd(timestamp=5)


def test_audio_start_and_chunk_round_trip():
    pcm = bytes(range(256)) * 10
    start = ev.from_event(_through_wire(ev.audio_start(timestamp=0)))
    assert isinstance(start, AudioStart)
    assert (start.rate, start.width, start.channels) == (16000, 2, 1)
    chunk = ev.from_event(_through_wire(ev.audio_chunk(pcm, timestamp=80)))
    assert isinstance(chunk, AudioChunk)
    assert chunk.audio == pcm and chunk.timestamp == 80


def test_split_chunks_80ms():
    pcm = b"\x01\x00" * (c.CHUNK_SAMPLES * 2 + 100)
    chunks = list(ev.split_chunks(pcm))
    assert [len(x) for x in chunks] == [c.CHUNK_BYTES, c.CHUNK_BYTES, 200]
    assert b"".join(chunks) == pcm


def test_audio_constants():
    assert c.CHUNK_SAMPLES == 1280
    assert c.CHUNK_BYTES == 2560
    assert c.CAPTURE_FORMAT.bytes_for_ms(80) == c.CHUNK_BYTES
    assert c.WYOMING_HOST == "127.0.0.1"


def test_unknown_and_invalid_events():
    with pytest.raises(ev.UnknownEvent):
        ev.from_event(Event("ping"))
    with pytest.raises(ev.EventDecodeError):
        ev.from_event(Event("magi-wake", {"source": "grito", "satellite": "pc"}))
    with pytest.raises(ev.EventDecodeError):
        ev.from_event(Event("magi-wake", {"source": "wake"}))
    with pytest.raises(ev.EventDecodeError):
        ev.from_event(Event("magi-mouth", {"level": "alto"}))
    with pytest.raises(ev.EventDecodeError):
        ev.from_event(Event("audio-start", {"rate": 16000}))
    with pytest.raises(TypeError):
        ev.to_event(c.StateMsg(c.Expression.HAPPY))  # mensagem de HUD não vai no Wyoming


def test_mouth_level_is_clamped():
    assert c.MouthEvent(1.7).level == 1.0
    assert c.MouthEvent(-0.2).level == 0.0
    assert c.MouthMsg(3).v == 1.0


# ---------------------------------------------------------------------------------------------
# HUD
# ---------------------------------------------------------------------------------------------

HUD_MESSAGES = [
    *(c.StateMsg(e) for e in c.Expression),
    c.SubtitleMsg(text="Abrindo Elden Ring."),
    c.SubtitleMsg(text="É o Miyazaki.", full="É o Miyazaki, diretor da FromSoftware.\nLinha 2"),
    c.SpeechMsg("Abrindo Elden Ring.", dur=1.84, i=0),
    c.SpeechMsg("Frase em streaming.", i=2),
    c.MouthMsg(0.42),
    *(c.MoodMsg(v) for v in range(c.MOOD_MIN, c.MOOD_MAX + 1)),
    *(c.VoteMsg(v) for v in c.Verdict),
    c.VoteMsg(c.Verdict.PENDING, label="Fechar Elden Ring"),
    c.CardMsg(c.CardLevel.ALTA, "Nova temporada de Frieren", "https://exemplo.com/a"),
    c.CardMsg(c.CardLevel.LINK, "Fonte", "https://exemplo.com/b", source="ANN"),
    c.CmdMsg(c.HudCommand.PUSH_TO_TALK),
    c.CmdMsg("detail_closed", args={"panel": "cpu"}),
    *(c.DetailMsg(t) for t in c.DetailTarget),
]


@pytest.mark.parametrize("msg", HUD_MESSAGES, ids=lambda m: type(m).__name__)
def test_hud_round_trip(msg):
    line = ev.encode_hud(msg)
    assert "\n" not in line
    assert ev.decode_hud(line) == msg
    raw = ev.encode_hud_line(msg)
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    assert ev.decode_hud(raw) == msg


def test_hud_wire_format_matches_design():
    assert json.loads(ev.encode_hud(c.StateMsg(c.Expression.LISTENING))) == {"t": "state", "v": "listening"}
    assert json.loads(ev.encode_hud(c.SubtitleMsg("a", "b"))) == {"t": "subtitle", "text": "a", "full": "b"}
    assert json.loads(ev.encode_hud(c.MouthMsg(0.42))) == {"t": "mouth", "v": 0.42}
    speech = c.SpeechMsg("Oi.", dur=1.23456, i=1)
    assert json.loads(ev.encode_hud(speech)) == {"t": "speech", "text": "Oi.", "dur": 1.235, "i": 1}
    assert json.loads(ev.encode_hud(c.SpeechMsg("Oi."))) == {"t": "speech", "text": "Oi.", "i": 0}
    assert json.loads(ev.encode_hud(c.MoodMsg(2))) == {"t": "mood", "v": 2}
    assert json.loads(ev.encode_hud(c.VoteMsg(c.Verdict.DENIED))) == {"t": "vote", "verdict": "denied"}
    card = c.CardMsg(c.CardLevel.ALTA, "T", "U")
    assert json.loads(ev.encode_hud(card)) == {"t": "card", "level": "alta", "title": "T", "url": "U"}
    assert json.loads(ev.encode_hud(c.CmdMsg("push_to_talk"))) == {"t": "cmd", "name": "push_to_talk"}
    assert json.loads(ev.encode_hud(c.DetailMsg(c.DetailTarget.GPU))) == {"t": "detail", "v": "gpu"}
    assert "ç" in ev.encode_hud(c.SubtitleMsg("ação"))  # UTF-8 legível, sem \\u


@pytest.mark.parametrize(
    "line",
    [
        "não é json",
        "[1, 2]",
        '{"v": "listening"}',
        '{"t": "dance"}',
        '{"t": "state", "v": "dancing"}',
        '{"t": "state"}',
        '{"t": "mood", "v": 7}',
        '{"t": "mood", "v": 2.5}',
        '{"t": "mouth", "v": true}',
        '{"t": "card", "level": "alta"}',
        '{"t": "vote", "verdict": "maybe"}',
        '{"t": "cmd", "name": 3}',
        '{"t": "speech"}',
        '{"t": "speech", "text": "a", "dur": "1"}',
        '{"t": "speech", "text": "a", "dur": -1}',
        '{"t": "speech", "text": "a", "i": 1.5}',
    ],
)
def test_hud_invalid_lines(line):
    with pytest.raises(ev.HudDecodeError):
        ev.decode_hud(line)


def test_mood_validation():
    with pytest.raises(ValueError):
        c.MoodMsg(5)
    with pytest.raises(ValueError):
        c.MoodMsg(-1)


# ---------------------------------------------------------------------------------------------
# Estados do turno
# ---------------------------------------------------------------------------------------------

VALID = [
    ("sleeping", "listening"),
    ("sleeping", "speaking"),
    ("listening", "thinking"),
    ("listening", "sleeping"),
    ("thinking", "speaking"),
    ("thinking", "confirming"),
    ("thinking", "listening"),
    ("thinking", "sleeping"),
    ("confirming", "thinking"),
    ("confirming", "speaking"),
    ("confirming", "listening"),
    ("confirming", "sleeping"),
    ("speaking", "sleeping"),
    ("speaking", "listening"),
    ("speaking", "confirming"),
    ("speaking", "followup"),  # 1.20: janela de continuação
    ("thinking", "followup"),
    ("followup", "thinking"),
    ("followup", "sleeping"),
    ("followup", "listening"),
]


@pytest.mark.parametrize(("src", "dst"), VALID)
def test_valid_transitions(src, dst):
    s, d = c.TurnState(src), c.TurnState(dst)
    assert c.can_transition(s, d)
    assert c.check_transition(s, d) is d


INVALID = [
    (a, b)
    for a, b in itertools.product(c.TurnState, repeat=2)
    if (a.value, b.value) not in VALID
]


@pytest.mark.parametrize(("src", "dst"), INVALID)
def test_invalid_transitions(src, dst):
    assert not c.can_transition(src, dst)
    with pytest.raises(c.InvalidTransition):
        c.check_transition(src, dst)


def test_happy_path_and_interruption():
    path = ["sleeping", "listening", "thinking", "confirming", "speaking", "sleeping"]
    path += ["listening", "thinking", "speaking", "listening"]  # R12.5: interrupção
    state = c.TurnState.SLEEPING
    for nxt in path[1:]:
        state = c.check_transition(state, c.TurnState(nxt))
    assert state is c.TurnState.LISTENING
    assert set(c.STATE_EXPRESSION) == set(c.TurnState)


# ---------------------------------------------------------------------------------------------
# Tipos do núcleo
# ---------------------------------------------------------------------------------------------


def _ctx():
    return c.TurnContext(satellite="pc", source=c.WakeSource.WAKE, started_at=datetime.now(UTC))


def test_route_result_rules():
    intent = c.Intent(c.IntentId.GAME_OPEN, slots=(c.Slot(c.SlotName.GAME, "1245620", display="Elden Ring"),))
    assert intent.slot("game").display == "Elden Ring"
    assert intent.slot("volume") is None
    c.RouteResult(c.RouteKind.LOCAL, "abre elden ring", 95.0, intent)
    c.RouteResult(c.RouteKind.ASK, "abre eldi rin", 80.0, intent, suggestion="Elden Ring")
    c.RouteResult(c.RouteKind.AGENT, "quem é o miyazaki?", 30.0)
    with pytest.raises(ValueError):
        c.RouteResult(c.RouteKind.AGENT, "x", 30.0, intent)
    with pytest.raises(ValueError):
        c.RouteResult(c.RouteKind.LOCAL, "x", 95.0)


def test_action_result_confirmation_needs_followup():
    req = c.ActionRequest(c.Intent(c.IntentId.GAME_CLOSE, danger=True), _ctx())
    with pytest.raises(ValueError):
        c.ActionResult(ok=True, needs_confirmation=True)
    res = c.ActionResult(
        ok=True,
        speech="Fecho o Elden Ring? Diz confirma.",
        needs_confirmation=True,
        dangerous=True,
        on_confirm=c.ActionRequest(req.intent, req.ctx, confirmed=True),
    )
    assert res.on_confirm.confirmed


def test_transcript():
    t = c.Transcript.raw("abre o eldi rin")
    assert t.final == t.heard
    t2 = t.with_final("abre o elden ring")
    assert t2.heard == "abre o eldi rin" and t2.final == "abre o elden ring"
    assert c.Transcript.raw("  ").is_empty


def test_protocols_are_structural():
    class Handler:
        intents = frozenset({c.IntentId.VOLUME_SET})

        async def run(self, req):
            return c.ActionResult(ok=True)

    class Sink:
        async def send(self, msg):
            return None

    assert isinstance(Handler(), c.ActionHandler)
    assert isinstance(Sink(), c.HudSink)
    assert not isinstance(Sink(), c.ActionHandler)


def test_api_key_hides_secret():
    key = c.ApiKey("openai", "openai-1", "sk-segredo")
    assert "sk-segredo" not in repr(key)


def test_budget_status_fraction():
    assert c.BudgetStatus(4.0, 5.0).fraction == pytest.approx(0.8)
    assert c.ProviderTask.STT not in c.BUDGET_BLOCKED_TASKS


def test_hud_socket_path():
    assert str(c.hud_socket_path({"XDG_RUNTIME_DIR": "/run/user/1000"})) == "/run/user/1000/magi/hud.sock"
