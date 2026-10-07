"""Conversão dos contratos para o fio (tarefa 1.0, R22.1).

Wyoming (satélite <-> núcleo, TCP ``WYOMING_HOST:WYOMING_PORT``):

- ``to_event(msg) -> wyoming.event.Event`` para os tipos de ``contracts`` (``WakeEvent``,
  ``AudioEnd``...). Escreva com ``wyoming.event.async_write_event``.
- ``from_event(event)`` devolve o contrato correspondente; para ``audio-start``/``audio-chunk``
  devolve ``wyoming.audio.AudioStart``/``AudioChunk``. Levanta ``UnknownEvent`` para tipos
  desconhecidos e ``EventDecodeError`` para dados inválidos.
- ``audio_start``/``audio_chunk``/``split_chunks``: atalhos para mandar PCM.

HUD (socket Unix, JSON por linha, §6):

- ``encode_hud(msg) -> str`` (uma linha, sem ``\\n``), ``encode_hud_line(msg) -> bytes``
  (com ``\\n``), ``decode_hud(linha) -> mensagem``; erro levanta ``HudDecodeError``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from wyoming.audio import AudioChunk, AudioStart
from wyoming.event import Event

from magi.common.contracts import (
    CAPTURE_FORMAT,
    CHUNK_MS,
    CONFIRM_TIMEOUT_MS,
    AudioEnd,
    AudioEndReason,
    CardLevel,
    CardMsg,
    CmdMsg,
    CoreToSatellite,
    DetailMsg,
    DetailTarget,
    EventType,
    Expression,
    HudMessage,
    ListenRequest,
    MoodMsg,
    MouthEvent,
    MouthMsg,
    PcmFormat,
    PlaybackDone,
    SatelliteHello,
    SatelliteStatus,
    SatelliteToCore,
    SpeechMsg,
    StateMsg,
    StopPlayback,
    SubtitleMsg,
    ToneMetadata,
    Verdict,
    VoteMsg,
    WakeEvent,
    WakeSource,
)

#: Tudo que ``from_event`` pode devolver.
WireMessage = SatelliteToCore | CoreToSatellite | AudioStart | AudioChunk


class EventDecodeError(ValueError):
    """Evento Wyoming com dados inválidos (R22.1)."""


class UnknownEvent(EventDecodeError):
    """Tipo de evento que a Magui não usa (R22.1). ``event_type`` guarda o tipo recebido."""

    def __init__(self, event_type: str) -> None:
        super().__init__(f"evento desconhecido: {event_type!r}")
        self.event_type = event_type


class HudDecodeError(ValueError):
    """Linha do socket do HUD inválida ou de tipo desconhecido (§6)."""


# ---------------------------------------------------------------------------------------------
# Wyoming
# ---------------------------------------------------------------------------------------------


def _without_none(d: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _tone_to_dict(tone: ToneMetadata) -> dict[str, Any]:
    return {"energy_db": tone.energy_db, "speech_rate": tone.speech_rate, "duration_ms": tone.duration_ms}


def to_event(msg: SatelliteToCore | CoreToSatellite) -> Event:
    """Converte um contrato em ``wyoming.event.Event`` (R22.1)."""
    match msg:
        case SatelliteHello():
            data = {
                "satellite": msg.satellite,
                "name": msg.name,
                "version": msg.version,
                "capabilities": list(msg.capabilities),
            }
            return Event(EventType.HELLO.value, data)
        case WakeEvent():
            data = _without_none(
                {
                    "source": msg.source.value,
                    "satellite": msg.satellite,
                    "score": msg.score,
                    "timestamp": msg.timestamp,
                }
            )
            return Event(EventType.WAKE.value, data)
        case MouthEvent():
            return Event(EventType.MOUTH.value, {"level": msg.level, "satellite": msg.satellite})
        case PlaybackDone():
            return Event(EventType.PLAYBACK_DONE.value, {"satellite": msg.satellite})
        case SatelliteStatus():
            data = {"satellite": msg.satellite, "in_call": msg.in_call, "wake_enabled": msg.wake_enabled}
            return Event(EventType.STATUS.value, data)
        case ListenRequest():
            return Event(EventType.LISTEN.value, {"timeout_ms": msg.timeout_ms, "reason": msg.reason})
        case StopPlayback():
            return Event(EventType.STOP_PLAYBACK.value, {})
        case AudioEnd():
            # Compatível com wyoming.audio.AudioStop: "timestamp" sempre presente.
            data: dict[str, Any] = {"timestamp": msg.timestamp}
            if msg.reason is not None:
                data["reason"] = msg.reason.value
            if msg.tone is not None:
                data["tone"] = _tone_to_dict(msg.tone)
            return Event(EventType.AUDIO_STOP.value, data)
    raise TypeError(f"não é um evento da Magui: {msg!r}")


def _get(data: Mapping[str, Any], key: str, kind: type | tuple[type, ...], default: Any = ...) -> Any:
    if key not in data or data[key] is None:
        if default is ...:
            raise EventDecodeError(f"campo obrigatório ausente: {key!r}")
        return default
    value = data[key]
    if isinstance(value, bool) and bool not in (kind if isinstance(kind, tuple) else (kind,)):
        raise EventDecodeError(f"tipo inválido em {key!r}: {value!r}")
    if not isinstance(value, kind):
        raise EventDecodeError(f"tipo inválido em {key!r}: {value!r}")
    return value


def _enum(cls: Callable[[Any], Any], value: Any) -> Any:
    try:
        return cls(value)
    except ValueError as e:
        raise EventDecodeError(str(e)) from e


_NUM = (int, float)


def _hello(d: Mapping[str, Any]) -> SatelliteHello:
    caps = _get(d, "capabilities", list, ())
    return SatelliteHello(
        satellite=_get(d, "satellite", str),
        name=_get(d, "name", str, ""),
        version=_get(d, "version", str, ""),
        capabilities=tuple(str(c) for c in caps),
    )


def _wake(d: Mapping[str, Any]) -> WakeEvent:
    score = _get(d, "score", _NUM, None)
    return WakeEvent(
        source=_enum(WakeSource, _get(d, "source", str)),
        satellite=_get(d, "satellite", str),
        score=None if score is None else float(score),
        timestamp=_get(d, "timestamp", int, None),
    )


def _mouth(d: Mapping[str, Any]) -> MouthEvent:
    return MouthEvent(level=float(_get(d, "level", _NUM)), satellite=_get(d, "satellite", str, ""))


def _status(d: Mapping[str, Any]) -> SatelliteStatus:
    return SatelliteStatus(
        satellite=_get(d, "satellite", str),
        in_call=_get(d, "in_call", bool, False),
        wake_enabled=_get(d, "wake_enabled", bool, True),
    )


def _listen(d: Mapping[str, Any]) -> ListenRequest:
    return ListenRequest(
        timeout_ms=_get(d, "timeout_ms", int, CONFIRM_TIMEOUT_MS),
        reason=_get(d, "reason", str, "confirm"),
    )


def _audio_end(d: Mapping[str, Any]) -> AudioEnd:
    reason = _get(d, "reason", str, None)
    tone_d = _get(d, "tone", dict, None)
    tone = None
    if tone_d is not None:
        tone = ToneMetadata(
            energy_db=float(_get(tone_d, "energy_db", _NUM)),
            speech_rate=float(_get(tone_d, "speech_rate", _NUM)),
            duration_ms=_get(tone_d, "duration_ms", int, 0),
        )
    return AudioEnd(
        timestamp=_get(d, "timestamp", int, None),
        reason=None if reason is None else _enum(AudioEndReason, reason),
        tone=tone,
    )


def _wyoming(cls: Any) -> Callable[[Event], Any]:
    def decode(event: Event) -> Any:
        try:
            return cls.from_event(event)
        except (KeyError, TypeError) as e:
            raise EventDecodeError(f"{event.type}: {e}") from e

    return decode


_DECODERS: dict[str, Callable[[Event], WireMessage]] = {
    EventType.HELLO.value: lambda e: _hello(e.data),
    EventType.WAKE.value: lambda e: _wake(e.data),
    EventType.MOUTH.value: lambda e: _mouth(e.data),
    EventType.PLAYBACK_DONE.value: lambda e: PlaybackDone(satellite=_get(e.data, "satellite", str, "")),
    EventType.STATUS.value: lambda e: _status(e.data),
    EventType.LISTEN.value: lambda e: _listen(e.data),
    EventType.STOP_PLAYBACK.value: lambda e: StopPlayback(),
    EventType.AUDIO_STOP.value: lambda e: _audio_end(e.data),
    EventType.AUDIO_START.value: _wyoming(AudioStart),
    EventType.AUDIO_CHUNK.value: _wyoming(AudioChunk),
}


def is_known(event: Event) -> bool:
    """True se ``from_event`` sabe decodificar este tipo."""
    return event.type in _DECODERS


def from_event(event: Event) -> WireMessage:
    """Converte ``wyoming.event.Event`` no contrato correspondente (R22.1)."""
    decoder = _DECODERS.get(event.type)
    if decoder is None:
        raise UnknownEvent(event.type)
    if not isinstance(event.data, Mapping):
        raise EventDecodeError(f"{event.type}: data não é objeto")
    return decoder(event)


def audio_start(fmt: PcmFormat = CAPTURE_FORMAT, timestamp: int | None = None) -> Event:
    """Evento ``audio-start`` no formato dado (§5)."""
    return AudioStart(rate=fmt.rate, width=fmt.width, channels=fmt.channels, timestamp=timestamp).event()


def audio_chunk(pcm: bytes, fmt: PcmFormat = CAPTURE_FORMAT, timestamp: int | None = None) -> Event:
    """Evento ``audio-chunk`` com PCM cru no payload (§5)."""
    return AudioChunk(
        rate=fmt.rate, width=fmt.width, channels=fmt.channels, audio=pcm, timestamp=timestamp
    ).event()


def split_chunks(pcm: bytes, fmt: PcmFormat = CAPTURE_FORMAT, chunk_ms: int = CHUNK_MS) -> Iterator[bytes]:
    """Fatia PCM em blocos de ``chunk_ms`` (o último pode ser menor), alinhados à amostra."""
    size = max(fmt.bytes_for_ms(chunk_ms), fmt.width * fmt.channels)
    for i in range(0, len(pcm), size):
        yield pcm[i : i + size]


# ---------------------------------------------------------------------------------------------
# HUD (§6)
# ---------------------------------------------------------------------------------------------


def encode_hud(msg: HudMessage) -> str:
    """Mensagem do HUD como uma linha JSON, sem ``\\n`` (§6)."""
    return msg.to_json()


def encode_hud_line(msg: HudMessage) -> bytes:
    """Mensagem do HUD pronta para o socket: UTF-8 com ``\\n`` no fim (§6)."""
    return (msg.to_json() + "\n").encode("utf-8")


def _h(d: Mapping[str, Any], key: str, kind: type | tuple[type, ...], default: Any = ...) -> Any:
    try:
        return _get(d, key, kind, default)
    except EventDecodeError as e:
        raise HudDecodeError(str(e)) from e


def _hud_state(d: Mapping[str, Any]) -> StateMsg:
    return StateMsg(Expression(_h(d, "v", str)))


def _hud_subtitle(d: Mapping[str, Any]) -> SubtitleMsg:
    return SubtitleMsg(text=_h(d, "text", str), full=_h(d, "full", str, None))


def _hud_speech(d: Mapping[str, Any]) -> SpeechMsg:
    dur = _h(d, "dur", _NUM, None)
    i = _h(d, "i", int, 0)
    if (dur is not None and dur < 0) or i < 0:
        raise HudDecodeError(f"fala com dur/i negativo: {dur!r}/{i!r}")
    return SpeechMsg(text=_h(d, "text", str), dur=None if dur is None else float(dur), i=i)


def _hud_mouth(d: Mapping[str, Any]) -> MouthMsg:
    return MouthMsg(float(_h(d, "v", _NUM)))


def _hud_mood(d: Mapping[str, Any]) -> MoodMsg:
    return MoodMsg(_h(d, "v", int))


def _hud_vote(d: Mapping[str, Any]) -> VoteMsg:
    return VoteMsg(verdict=Verdict(_h(d, "verdict", str)), label=_h(d, "label", str, None))


def _hud_card(d: Mapping[str, Any]) -> CardMsg:
    return CardMsg(
        level=CardLevel(_h(d, "level", str)),
        title=_h(d, "title", str),
        url=_h(d, "url", str, ""),
        source=_h(d, "source", str, None),
    )


def _hud_cmd(d: Mapping[str, Any]) -> CmdMsg:
    return CmdMsg(name=_h(d, "name", str), args=dict(_h(d, "args", dict, {})))


def _hud_detail(d: Mapping[str, Any]) -> DetailMsg:
    return DetailMsg(DetailTarget(_h(d, "v", str)))


_HUD_DECODERS: dict[str, Callable[[Mapping[str, Any]], HudMessage]] = {
    StateMsg.T: _hud_state,
    SubtitleMsg.T: _hud_subtitle,
    SpeechMsg.T: _hud_speech,
    MouthMsg.T: _hud_mouth,
    MoodMsg.T: _hud_mood,
    VoteMsg.T: _hud_vote,
    CardMsg.T: _hud_card,
    CmdMsg.T: _hud_cmd,
    DetailMsg.T: _hud_detail,
}


def decode_hud(line: str | bytes) -> HudMessage:
    """Lê uma linha JSON do socket do HUD (§6). Aceita ``\\n`` no fim."""
    try:
        d = json.loads(line)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HudDecodeError(f"JSON inválido: {e}") from e
    if not isinstance(d, dict) or not isinstance(d.get("t"), str):
        raise HudDecodeError("mensagem sem campo 't'")
    decoder = _HUD_DECODERS.get(d["t"])
    if decoder is None:
        raise HudDecodeError(f"tipo desconhecido: {d['t']!r}")
    try:
        return decoder(d)
    except HudDecodeError:
        raise
    except (ValueError, TypeError) as e:
        raise HudDecodeError(f"{d['t']}: {e}") from e
