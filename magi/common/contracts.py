"""Contratos entre os módulos da Magui (tarefa 1.0, R22.1).

Este arquivo é a única coisa que uma tarefa precisa ler para falar com módulos de outras tarefas.
Só tipos, constantes, enums e protocolos: nada de I/O aqui.

Mapa rápido
-----------
- Constantes: rede, socket do HUD, formato de áudio, tempos e limiares padrão.
- Turno: ``TurnState`` + ``TRANSITIONS`` / ``can_transition`` / ``check_transition`` (§3.1).
- Protocolo satélite <-> núcleo (Wyoming + eventos ``magi-*``, §3 e §5): ``SatelliteHello``,
  ``WakeEvent``, ``MouthEvent``, ``PlaybackDone``, ``SatelliteStatus``, ``ListenRequest``,
  ``StopPlayback``, ``AudioEnd`` (fim da gravação com ``ToneMetadata``). O áudio em si usa
  ``wyoming.audio.AudioStart``/``AudioChunk``. Conversão em ``magi.common.events``:
  ``to_event(msg) -> wyoming Event`` e ``from_event(event) -> msg``.
- Núcleo: ``Transcript``, ``Slot``, ``Intent``, ``RouteResult``, ``TurnContext``,
  ``ActionRequest``, ``ActionResult``, ids canônicos em ``IntentId`` e ``SlotName``.
- HUD (§6): ``StateMsg``, ``SubtitleMsg``, ``MouthMsg``, ``MoodMsg``, ``VoteMsg``, ``CardMsg``,
  ``CmdMsg``, ``DetailMsg``. JSON de uma linha via ``magi.common.events.encode_hud`` /
  ``decode_hud`` (ou ``msg.to_json()``).
- Provedores (§4.7): ``SttProvider``, ``TtsProvider``, ``ChatProvider``, ``VisionProvider``,
  ``EmbeddingProvider``, ``SearchProvider``, ``ProviderRegistry``, ``KeyPool``, ``Budget``.
- Repositórios (§7): ``TurnsRepo``, ``CorrectionsRepo``, ``VocabRepo``, ``ProfileRepo``,
  ``MemoriesRepo``, ``HelpLogRepo``, ``MoodEventsRepo``, ``CostsRepo``, ``MusicSignalsRepo``,
  ``TasteRepo``, ``NewsRepo``.
- Serviços do núcleo: ``SatelliteLink``, ``Speaker``, ``Router``, ``Corrector``, ``GameCatalog``,
  ``Agent``, ``ActionHandler``, ``ActionRegistry``, ``HudSink``.

Convenções
----------
- Datas/horas são ``datetime`` com fuso (UTC). Tempos curtos em milissegundos (``*_ms``).
- Tudo que faz I/O é ``async``. Dataclasses são imutáveis (``frozen``); use
  ``dataclasses.replace`` para derivar.
- Chaves JSON em ``snake_case``. Campos opcionais ``None`` são omitidos no fio.
- Mudança incompatível aqui exige atualizar ``magi/common/events.py`` e os testes da tarefa 1.0.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

# ---------------------------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------------------------

#: Endereço do servidor Wyoming do núcleo. Só loopback no MVP (R22.1, RNF de privacidade).
WYOMING_HOST = "127.0.0.1"
#: Porta Wyoming do núcleo. Não usa 10700 para não colidir com o ``wyoming-satellite`` padrão.
WYOMING_PORT = 10750

#: Formato de captura do satélite (§5): 16 kHz, 16 bits (2 bytes), mono, PCM little-endian.
AUDIO_RATE = 16_000
AUDIO_WIDTH = 2
AUDIO_CHANNELS = 1
#: Bloco de captura: 80 ms = 1280 amostras = 2560 bytes (§5, entrada do openWakeWord).
CHUNK_MS = 80
CHUNK_SAMPLES = AUDIO_RATE * CHUNK_MS // 1000
CHUNK_BYTES = CHUNK_SAMPLES * AUDIO_WIDTH * AUDIO_CHANNELS

#: Intervalo de ``magi-mouth`` durante a reprodução (§5, R17.2: ≥ 15/s).
MOUTH_INTERVAL_MS = 50
#: Faixas da boca no HUD (§5): nível < 0,15 -> "—", < 0,5 -> "o", resto -> "O".
MOUTH_CLOSED_BELOW = 0.15
MOUTH_HALF_BELOW = 0.5

#: Fim de fala por VAD e duração máxima da gravação por "Ei Magui" (R1.5).
VAD_SILENCE_MS = 700
MAX_RECORDING_MS = 15_000
#: Janela para dizer "confirma" (R5.4).
CONFIRM_TIMEOUT_MS = 8_000
#: Volume dos sink-inputs de Spotify e jogo durante a fala (§5, R12.4).
DUCK_LEVEL = 0.30
#: Limiares padrão do roteador, 0..100 (§4.2). A config pode sobrescrever.
ROUTER_EXECUTE_SCORE = 88.0
ROUTER_ASK_SCORE = 72.0
#: Vocabulário de dica da transcrição (R3.2).
STT_HINT_MAX_TOKENS = 200
#: Escala do termômetro de humor (R13.3).
MOOD_MIN = 0
MOOD_MAX = 4
#: Até quantas memórias entram no contexto do agente (R11.2).
MEMORY_TOP_K = 5
#: Teto mensal padrão em dólares (R16).
DEFAULT_MONTHLY_CAP_USD = 5.0


def hud_socket_path(env: Mapping[str, str] | None = None) -> Path:
    """Caminho do socket Unix do HUD: ``$XDG_RUNTIME_DIR/magi/hud.sock`` (§6).

    Sem ``XDG_RUNTIME_DIR``, usa ``/run/user/<uid>``. Não cria o diretório. O núcleo é o
    servidor do socket; o HUD conecta como cliente (tarefa 1.15).
    """
    env = os.environ if env is None else env
    base = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "magi" / "hud.sock"


@dataclass(frozen=True, slots=True)
class PcmFormat:
    """Formato de áudio PCM cru (R22.1). ``width`` em bytes por amostra."""

    rate: int = AUDIO_RATE
    width: int = AUDIO_WIDTH
    channels: int = AUDIO_CHANNELS

    def bytes_for_ms(self, ms: int) -> int:
        """Número de bytes para ``ms`` milissegundos neste formato."""
        return self.rate * ms // 1000 * self.width * self.channels


#: Formato de captura do satélite (§5). O áudio de voz (TTS) declara o próprio formato no
#: ``audio-start`` que o núcleo envia; o satélite toca no formato anunciado.
CAPTURE_FORMAT = PcmFormat()


# ---------------------------------------------------------------------------------------------
# Estados do turno (§3.1)
# ---------------------------------------------------------------------------------------------


class TurnState(StrEnum):
    """Estados do núcleo por satélite (§3.1, R1.2, R5.4, R12.5)."""

    SLEEPING = "sleeping"
    LISTENING = "listening"
    THINKING = "thinking"
    CONFIRMING = "confirming"
    SPEAKING = "speaking"
    FOLLOWUP = "followup"  # janela de continuação após a resposta (1.20)


_S = TurnState

#: Transições permitidas (§3.1). Regras:
#: - sleeping -> listening (wake/atalho) ou speaking (aviso proativo, R15.1/R19.5);
#: - listening -> thinking (fim da gravação);
#: - thinking -> speaking (resposta), confirming (ação perigosa/"você quis dizer X?", R5.3/R4.2)
#:   ou listening (nova ativação);
#: - confirming -> thinking (chegou a resposta falada), speaking (cancelado por tempo, R5.4)
#:   ou listening (nova ativação);
#: - speaking -> sleeping (playback-done), listening (interrupção, R12.5) ou confirming
#:   (terminou de falar a pergunta "diz confirma") ou followup (janela de continuação, 1.20);
#: - thinking -> followup (resposta sem fala);
#: - followup -> thinking (falou na janela), sleeping (silêncio/dispensa) ou listening (ativação);
#: - qualquer estado acordado -> sleeping (erro, cancelamento, satélite desconectado, §9).
#: Transição para o mesmo estado é inválida (ex.: wake durante listening é ignorado).
TRANSITIONS: Mapping[TurnState, frozenset[TurnState]] = {
    _S.SLEEPING: frozenset({_S.LISTENING, _S.SPEAKING}),
    _S.LISTENING: frozenset({_S.THINKING, _S.SLEEPING}),
    _S.THINKING: frozenset({_S.SPEAKING, _S.CONFIRMING, _S.LISTENING, _S.SLEEPING, _S.FOLLOWUP}),
    _S.CONFIRMING: frozenset({_S.THINKING, _S.SPEAKING, _S.LISTENING, _S.SLEEPING}),
    _S.SPEAKING: frozenset({_S.SLEEPING, _S.LISTENING, _S.CONFIRMING, _S.FOLLOWUP}),
    _S.FOLLOWUP: frozenset({_S.THINKING, _S.SLEEPING, _S.LISTENING}),
}


class InvalidTransition(ValueError):
    """Transição de estado fora de ``TRANSITIONS`` (§3.1)."""

    def __init__(self, src: TurnState, dst: TurnState) -> None:
        super().__init__(f"transição inválida: {src} -> {dst}")
        self.src = src
        self.dst = dst


def can_transition(src: TurnState, dst: TurnState) -> bool:
    """True se ``src -> dst`` é permitida (§3.1)."""
    return dst in TRANSITIONS[src]


def check_transition(src: TurnState, dst: TurnState) -> TurnState:
    """Devolve ``dst`` ou levanta ``InvalidTransition`` (§3.1)."""
    if not can_transition(src, dst):
        raise InvalidTransition(src, dst)
    return dst


# ---------------------------------------------------------------------------------------------
# Protocolo satélite <-> núcleo (Wyoming + magi-*, §3, §5)
# ---------------------------------------------------------------------------------------------


class EventType(StrEnum):
    """Tipos de evento no fio Wyoming (§3, R22.1). Os de áudio são os do próprio Wyoming.

    Sequência de um turno (satélite -> núcleo): ``magi-hello`` (uma vez, ao conectar),
    ``magi-wake``, ``audio-start``, ``audio-chunk``..., ``audio-stop`` (com ``reason`` e ``tone``).
    Resposta (núcleo -> satélite, na mesma conexão, R22.3): ``audio-start``, ``audio-chunk``...,
    ``audio-stop``; durante a reprodução o satélite manda ``magi-mouth`` (~20/s) e, ao terminar
    de tocar tudo, ``playback-done``. Se a reprodução for interrompida por wake/atalho (R12.5), o
    satélite corta o som e manda só o novo ``magi-wake`` (sem ``playback-done``).
    Escuta curta sem "Ei Magui" (R5.4): núcleo manda ``magi-listen``; o satélite responde direto
    com ``audio-start``... ``audio-stop`` (``reason=no_speech`` se ninguém falar no prazo).
    """

    # Wyoming padrão
    AUDIO_START = "audio-start"
    AUDIO_CHUNK = "audio-chunk"
    AUDIO_STOP = "audio-stop"
    # satélite -> núcleo
    HELLO = "magi-hello"
    WAKE = "magi-wake"
    MOUTH = "magi-mouth"
    PLAYBACK_DONE = "playback-done"
    STATUS = "magi-status"
    # núcleo -> satélite
    LISTEN = "magi-listen"
    STOP_PLAYBACK = "magi-stop"


class WakeSource(StrEnum):
    """Origem da ativação (R1.2, R1.3, R1.7)."""

    WAKE = "wake"  # "Ei Magui"
    PTT = "ptt"  # atalho de apertar pra falar (teclado ou DualSense)


class AudioEndReason(StrEnum):
    """Por que a gravação terminou (R1.4, R1.5)."""

    VAD = "vad"  # 700 ms de silêncio
    PTT_RELEASE = "ptt_release"  # atalho solto
    MAX_LENGTH = "max_length"  # 15 s
    NO_SPEECH = "no_speech"  # ninguém falou (ex.: escuta de confirmação expirou)
    CANCELLED = "cancelled"  # cancelada pelo satélite (ex.: entrou em call)


@dataclass(frozen=True, slots=True)
class SatelliteHello:
    """``magi-hello``: identificação do satélite, primeiro evento da conexão (R22.2, R22.3).

    ``satellite`` é o id estável (ex.: ``"pc"``) gravado em ``turns.satellite``.
    ``capabilities`` usa os valores ``"wake"``, ``"ptt"``, ``"playback"``.
    """

    satellite: str
    name: str = ""
    version: str = ""
    capabilities: tuple[str, ...] = ("wake", "ptt", "playback")


@dataclass(frozen=True, slots=True)
class WakeEvent:
    """``magi-wake``: ativação por "Ei Magui" ou atalho (R1.2, R1.3, R12.5, R22.3).

    ``score`` é a confiança do wake word (0..1); ``None`` para atalho.
    """

    source: WakeSource
    satellite: str
    score: float | None = None
    timestamp: int | None = None  # ms, relógio do satélite


@dataclass(frozen=True, slots=True)
class MouthEvent:
    """``magi-mouth``: nível RMS normalizado 0..1 do áudio tocado, a cada 50 ms (§5, R17.2).

    Valores fora de 0..1 são saturados na construção.
    """

    level: float
    satellite: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", min(1.0, max(0.0, float(self.level))))


@dataclass(frozen=True, slots=True)
class PlaybackDone:
    """``playback-done``: o satélite terminou de tocar toda a fala (§3, R12.4). Não é enviado
    quando a fala é interrompida (R12.5)."""

    satellite: str = ""


@dataclass(frozen=True, slots=True)
class SatelliteStatus:
    """``magi-status``: estado do satélite, enviado quando muda (R2.1, R2.2, R15.2).

    ``in_call``: há chamada ativa no Discord (avisos só na tela).
    ``wake_enabled``: detecção de "Ei Magui" ligada.
    """

    satellite: str
    in_call: bool = False
    wake_enabled: bool = True


@dataclass(frozen=True, slots=True)
class ListenRequest:
    """``magi-listen``: núcleo pede uma escuta curta sem wake word (R5.4, §3.1 ``confirming``).

    O satélite grava com VAD e encerra com ``no_speech`` se ninguém falar em ``timeout_ms``
    (prazo só para começar a falar; a gravação segue até o fim pelo VAD, teto de 15 s).
    ``reason``: ``"confirm"`` (R5.4) ou ``"followup"`` (janela de continuação, 1.20). Nenhuma
    escuta pedida pelo núcleo toca bip: o HUD mostra o rosto em ``listening``.
    """

    timeout_ms: int = CONFIRM_TIMEOUT_MS
    reason: str = "confirm"


@dataclass(frozen=True, slots=True)
class StopPlayback:
    """``magi-stop``: núcleo manda o satélite parar de tocar agora (R12.5). Sem ``playback-done``."""


@dataclass(frozen=True, slots=True)
class ToneMetadata:
    """Medidas locais de tom do turno, para o humor (R13.3, §5). Só números, nunca áudio.

    ``energy_db``: RMS médio dos blocos com voz, em dBFS (≤ 0).
    ``speech_rate``: taxa de fala estimada em sílabas por segundo.
    ``duration_ms``: duração total com voz.
    """

    energy_db: float
    speech_rate: float
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class AudioEnd:
    """``audio-stop`` com os extras da Magui (R1.4, R1.5, R13.3).

    Do satélite: ``reason`` e ``tone`` preenchidos. Do núcleo (fim da fala TTS): ambos ``None``.
    """

    timestamp: int | None = None
    reason: AudioEndReason | None = None
    tone: ToneMetadata | None = None


#: Mensagens que o satélite envia ao núcleo (além de AudioStart/AudioChunk do wyoming).
SatelliteToCore = SatelliteHello | WakeEvent | MouthEvent | PlaybackDone | SatelliteStatus | AudioEnd
#: Mensagens que o núcleo envia ao satélite (além de AudioStart/AudioChunk do wyoming).
CoreToSatellite = ListenRequest | StopPlayback | AudioEnd


# ---------------------------------------------------------------------------------------------
# Turno: transcrição, roteamento, ações
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Transcript:
    """Resultado da transcrição (R3.1, R3.4, R3.5).

    ``heard``: texto cru do STT (``turns.text_heard``). ``final``: após correções
    (``turns.text_final``). Use ``Transcript.raw(texto)`` no STT e ``with_final`` nas correções.
    """

    heard: str
    final: str
    language: str = "pt"

    @classmethod
    def raw(cls, heard: str, language: str = "pt") -> Transcript:
        return cls(heard=heard, final=heard, language=language)

    def with_final(self, final: str) -> Transcript:
        return Transcript(heard=self.heard, final=final, language=self.language)

    @property
    def is_empty(self) -> bool:
        """True quando não há o que processar (R3.5: "não peguei, repete?")."""
        return not self.final.strip()


class SlotName(StrEnum):
    """Nomes canônicos de slot usados no ``intents.yaml`` e nas ações (§4.2, R4.4)."""

    GAME = "game"  # value = appid (str), display = nome do jogo
    VOLUME = "volume"  # value = "0".."100" ou "+10"/"-10"
    COLOR = "color"  # value = "#rrggbb"
    BRIGHTNESS = "brightness"  # value = "0".."100"
    DETAIL = "detail"  # value = DetailTarget
    ON_OFF = "on_off"  # value = "on" | "off"
    QUERY = "query"  # texto livre (música, artista, obra)
    AMOUNT = "amount"  # número decimal em texto, ex. "8"
    FRANCHISE = "franchise"  # nome da obra
    TEXT = "text"  # texto livre (ex.: correção "não, eu falei X")


@dataclass(frozen=True, slots=True)
class Slot:
    """Slot resolvido de uma intenção (§4.2, R4.4).

    ``value``: valor canônico (ex.: appid). ``raw``: trecho do texto. ``display``: forma falável
    (ex.: nome do jogo). ``score``: 0..100 da correspondência aproximada.
    """

    name: str
    value: str
    raw: str = ""
    display: str = ""
    score: float = 100.0


class IntentId(StrEnum):
    """Ids canônicos das intenções locais (R4-R8, R11, R13, R16, R19-R20).

    O roteador (1.8) usa estes ids no ``intents.yaml`` e cada ação registra os que atende.
    Ids novos entram aqui primeiro. ``Intent.id`` é ``str`` para aceitar extensões.
    """

    GAME_OPEN = "game.open"  # slot game (R5.1)
    GAME_CLOSE = "game.close"  # slot game opcional = jogo atual; perigosa (R5.3, R5.5)
    HUD_OPEN = "hud.open"  # R6.1
    HUD_CLOSE = "hud.close"
    HUD_IDLE_TOGGLE = "hud.idle_toggle"
    HUD_DETAIL = "hud.detail"  # slot detail
    HUD_RGB_SYNC = "hud.rgb_sync"  # slot on_off
    VOLUME_SET = "volume.set"  # slot volume (R6.2)
    VOLUME_MUTE = "volume.mute"
    VOLUME_UNMUTE = "volume.unmute"
    RGB_COLOR = "rgb.color"  # slot color (R6.3)
    RGB_BRIGHTNESS = "rgb.brightness"  # slot brightness
    SYSTEM_SHUTDOWN = "system.shutdown"  # perigosa (R5.3)
    SYSTEM_REBOOT = "system.reboot"  # perigosa
    MUSIC_OPEN = "music.open"  # R7.1
    MUSIC_PLAY = "music.play"  # sem slot: retomar; com slot query: buscar e tocar (R7.2)
    MUSIC_PAUSE = "music.pause"
    MUSIC_NEXT = "music.next"
    MUSIC_PREVIOUS = "music.previous"
    MUSIC_VOLUME = "music.volume"  # slot volume
    MUSIC_PICK = "music.pick"  # "coloca uma boa" (R8.1)
    MUSIC_LIKE = "music.like"  # "essa é boa" (R8.5)
    MUSIC_NEVER = "music.never"  # "nunca mais toca isso" (R8.5)
    CORRECTION = "correction.fix"  # "não, eu falei X", slot text (R3.3)
    MEMORY_FORGET = "memory.forget"  # "esquece isso" (R11.5)
    MOOD_SOFTER = "mood.softer"  # "pega leve" (R13.5)
    MOOD_HARDER = "mood.harder"  # "pode pegar pesado"
    BUDGET_SET_CAP = "budget.set_cap"  # slot amount (R16.2)
    NEWS_WHATS_NEW = "news.whats_new"  # "novidades?" (R20.3)
    NEWS_SPOILERS_OK = "news.spoilers_ok"  # slot franchise (R19.3)
    NEWS_DISLIKE = "news.dislike"  # "não curti" (R19.7)
    NEWS_MORE = "news.more"  # "mais disso"
    NEWS_DROP = "news.drop"  # obra largada, slot franchise (R19.8)
    CONFIRM_YES = "confirm.yes"  # "confirma" (R5.4)
    CONFIRM_NO = "confirm.no"  # "cancela"


@dataclass(frozen=True, slots=True)
class Intent:
    """Intenção local reconhecida (§4.2, R4.1). ``danger`` marca ação perigosa (R5.3).

    ``reply``: frase de resposta em cache do ``intents.yaml`` (pode ter ``{game}`` etc.).
    """

    id: str
    slots: tuple[Slot, ...] = ()
    danger: bool = False
    reply: str | None = None

    def slot(self, name: str) -> Slot | None:
        """Primeiro slot com esse nome, ou ``None``."""
        return next((s for s in self.slots if s.name == name), None)


class RouteKind(StrEnum):
    """Destino do texto (R4.1-R4.3)."""

    LOCAL = "local"  # nota ≥ limiar de execução: executa sem LLM
    ASK = "ask"  # entre os limiares: "você quis dizer X?"
    AGENT = "agent"  # abaixo: vai ao agente


@dataclass(frozen=True, slots=True)
class RouteResult:
    """Saída do roteador (§4.2, R4.1-R4.3). ``score`` 0..100 da melhor intenção.

    ``intent`` é obrigatório para ``local``/``ask`` e ``None`` para ``agent``.
    ``suggestion``: frase falável do "você quis dizer X?" (só ``ask``).
    """

    kind: RouteKind
    text: str
    score: float = 0.0
    intent: Intent | None = None
    suggestion: str | None = None

    def __post_init__(self) -> None:
        if self.kind is RouteKind.AGENT and self.intent is not None:
            raise ValueError("RouteResult agent não leva intent")
        if self.kind is not RouteKind.AGENT and self.intent is None:
            raise ValueError(f"RouteResult {self.kind} precisa de intent")


@dataclass(frozen=True, slots=True)
class TurnContext:
    """Contexto do turno corrente, passado a roteador, ações e agente (R13.3, R15.2, R22.3).

    ``satellite``: de onde veio o turno; a resposta volta para ele. ``turn_id`` é o id em
    ``turns`` (``None`` antes de gravar). ``previous_text``/``previous_at``: texto final e início
    do turno anterior do mesmo satélite (preenchidos pelo ``TurnMachine``; base do "não, eu falei
    X", R3.3). ``None`` no primeiro turno.
    """

    satellite: str
    source: WakeSource
    started_at: datetime
    turn_id: int | None = None
    tone: ToneMetadata | None = None
    mood: int = 2
    in_call: bool = False
    previous_text: str | None = None
    previous_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """Pedido de execução de uma ação local (R5-R8). Usado pelo núcleo e pelas ferramentas do
    agente (3.4/3.5), que montam um ``Intent`` com os ids de ``IntentId``.

    ``confirmed``: o usuário já disse "confirma" (R5.4). ``args``: extras da ação
    (ex.: ``{"force": True}`` para SIGKILL, R5.5).
    """

    intent: Intent
    ctx: TurnContext
    text: str = ""
    confirmed: bool = False
    args: Mapping[str, Any] = field(default_factory=dict)


class Expression(StrEnum):
    """Expressões do rosto no HUD (R17.1). Valor de ``StateMsg.v``."""

    SLEEPING = "sleeping"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    HAPPY = "happy"
    CONFUSED = "confused"
    ALERT = "alert"


#: Expressão padrão para cada estado do turno (R17.1). ``confirming`` mostra ``alert``.
STATE_EXPRESSION: Mapping[TurnState, Expression] = {
    TurnState.SLEEPING: Expression.SLEEPING,
    TurnState.LISTENING: Expression.LISTENING,
    TurnState.THINKING: Expression.THINKING,
    TurnState.CONFIRMING: Expression.ALERT,
    TurnState.SPEAKING: Expression.SPEAKING,
    TurnState.FOLLOWUP: Expression.LISTENING,
}


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Resultado de uma ação ou do agente (R5.3-R5.5, R12.3).

    ``speech``: fala curta (≤ 2 frases), vazia = não falar. ``full_text``: resposta completa para
    a legenda do HUD (``SubtitleMsg.full``). ``dangerous``: a ação é perigosa (mostra votação).
    ``needs_confirmation``: o núcleo fala ``speech``, entra em ``confirming`` e, se ouvir
    "confirma" em 8 s, executa ``on_confirm`` (obrigatório nesse caso; normalmente o mesmo
    pedido com ``confirmed=True``). ``cards``: links/cards para o HUD (R10.3).
    ``expression``: expressão sugerida ao falar (ex.: ``confused`` quando não achou).
    ``redo_text``: refazer o turno com este texto (correção, R3.3). O ``TurnPipeline`` trata uma
    vez só: roteia e executa o texto e junta a fala desta resposta à do turno refeito; o
    resultado final mantém ``redo_text`` como o texto efetivo do turno.
    """

    ok: bool
    speech: str = ""
    full_text: str | None = None
    needs_confirmation: bool = False
    dangerous: bool = False
    on_confirm: ActionRequest | None = None
    cards: tuple[CardMsg, ...] = ()
    expression: Expression | None = None
    redo_text: str | None = None

    def __post_init__(self) -> None:
        if self.needs_confirmation and self.on_confirm is None:
            raise ValueError("needs_confirmation exige on_confirm")


# ---------------------------------------------------------------------------------------------
# Mensagens do HUD (§6): JSON de uma linha, campo "t" = tipo
# ---------------------------------------------------------------------------------------------


def _dump(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class _HudMsg:
    """Base das mensagens do HUD: ``to_dict``/``to_json`` (sem ``\\n``)."""

    __slots__ = ()
    T: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - sobrescrito
        raise NotImplementedError

    def to_json(self) -> str:
        """Uma linha JSON, sem quebra de linha no fim (§6)."""
        return _dump(self.to_dict())


@dataclass(frozen=True, slots=True)
class StateMsg(_HudMsg):
    """núcleo -> HUD ``{"t":"state","v":"listening"}``: expressão do rosto (R1.2, R17.1)."""

    T: ClassVar[str] = "state"
    v: Expression

    def to_dict(self) -> dict[str, Any]:
        return {"t": self.T, "v": self.v.value}


@dataclass(frozen=True, slots=True)
class SubtitleMsg(_HudMsg):
    """núcleo -> HUD ``{"t":"subtitle","text":"…","full":"…"}``: legenda e resposta completa
    (R12.3, R17.5). ``full`` omitido quando ``None``."""

    T: ClassVar[str] = "subtitle"
    text: str
    full: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"t": self.T, "text": self.text}
        if self.full is not None:
            d["full"] = self.full
        return d


@dataclass(frozen=True, slots=True)
class MouthMsg(_HudMsg):
    """satélite -> núcleo -> HUD ``{"t":"mouth","v":0.42}``: nível da boca 0..1 (R17.2)."""

    T: ClassVar[str] = "mouth"
    v: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "v", min(1.0, max(0.0, float(self.v))))

    def to_dict(self) -> dict[str, Any]:
        return {"t": self.T, "v": round(self.v, 3)}


@dataclass(frozen=True, slots=True)
class MoodMsg(_HudMsg):
    """núcleo -> HUD ``{"t":"mood","v":2}``: termômetro de humor 0..4 (R13.7)."""

    T: ClassVar[str] = "mood"
    v: int

    def __post_init__(self) -> None:
        if not isinstance(self.v, int) or isinstance(self.v, bool) or not MOOD_MIN <= self.v <= MOOD_MAX:
            raise ValueError(f"humor fora de {MOOD_MIN}..{MOOD_MAX}: {self.v!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"t": self.T, "v": self.v}


class Verdict(StrEnum):
    """Estado da votação dos MAGI (R5.3)."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class VoteMsg(_HudMsg):
    """núcleo -> HUD ``{"t":"vote","verdict":"pending","label":"…"}``: votação de ação perigosa
    (R5.3, R5.4). ``label`` (opcional) descreve a ação, ex. "Fechar Elden Ring"."""

    T: ClassVar[str] = "vote"
    verdict: Verdict
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"t": self.T, "verdict": self.verdict.value}
        if self.label is not None:
            d["label"] = self.label
        return d


class CardLevel(StrEnum):
    """Nível do card no HUD (R19.4-R19.6, R10.3). ``link`` = fonte de pesquisa/novidade."""

    BOMBA = "bomba"
    ALTA = "alta"
    NORMAL = "normal"
    LINK = "link"


@dataclass(frozen=True, slots=True)
class CardMsg(_HudMsg):
    """núcleo -> HUD ``{"t":"card","level":"alta","title":"…","url":"…"}``: card de notícia ou
    link de fonte (R10.3, R19.5, R19.6, R20.1). ``source`` opcional (nome da fonte)."""

    T: ClassVar[str] = "card"
    level: CardLevel
    title: str
    url: str = ""
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"t": self.T, "level": self.level.value, "title": self.title, "url": self.url}
        if self.source is not None:
            d["source"] = self.source
        return d


class HudCommand(StrEnum):
    """Comandos HUD -> núcleo (§6)."""

    PUSH_TO_TALK = "push_to_talk"


@dataclass(frozen=True, slots=True)
class CmdMsg(_HudMsg):
    """HUD -> núcleo ``{"t":"cmd","name":"push_to_talk"}`` (§6, futuro: clicar no rosto).
    ``args`` omitido quando vazio. ``name`` é ``str`` para aceitar comandos novos."""

    T: ClassVar[str] = "cmd"
    name: str
    args: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"t": self.T, "name": str(self.name)}
        if self.args:
            d["args"] = dict(self.args)
        return d


class DetailTarget(StrEnum):
    """Painel de detalhes do HUD (R6.1). ``none`` fecha o detalhe."""

    CPU = "cpu"
    GPU = "gpu"
    MEMORY = "memory"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class DetailMsg(_HudMsg):
    """núcleo -> HUD ``{"t":"detail","v":"cpu"}``: abre o detalhe de CPU/GPU/memória (R6.1, §6)."""

    T: ClassVar[str] = "detail"
    v: DetailTarget

    def to_dict(self) -> dict[str, Any]:
        return {"t": self.T, "v": self.v.value}


HudMessage = StateMsg | SubtitleMsg | MouthMsg | MoodMsg | VoteMsg | CardMsg | CmdMsg | DetailMsg


# ---------------------------------------------------------------------------------------------
# Provedores (§4.7, R21) e custo (§4.6, R16)
# ---------------------------------------------------------------------------------------------


class ProviderTask(StrEnum):
    """Tarefas atendidas por provedores configuráveis (R21.1)."""

    STT = "stt"
    TTS = "tts"
    AGENT = "agent"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    SEARCH = "search"
    NEWS = "news"


#: Tarefas bloqueadas com o teto estourado (R16.4). STT e TTS registram custo mas não bloqueiam.
BUDGET_BLOCKED_TASKS: frozenset[ProviderTask] = frozenset(
    {ProviderTask.AGENT, ProviderTask.VISION, ProviderTask.SEARCH}
)


class ProviderError(RuntimeError):
    """Falha de provedor (R21). Base das demais."""


class PersonalDataRefused(ProviderError):
    """Provedor em cota gratuita recusou chamada com ``personal=True`` (R21.5)."""


class QuotaExhausted(ProviderError):
    """Cota gratuita acabou; quem chamou deve adiar, sem cair para pago (R18.6)."""


class NoKeyAvailable(ProviderError):
    """Todas as chaves do provedor estão em espera (R21.3)."""


class BudgetExceeded(ProviderError):
    """Teto mensal atingido para uma tarefa bloqueável (R16.4)."""


@dataclass(frozen=True, slots=True)
class Usage:
    """Consumo de uma chamada paga (R16.1, tabela ``costs``).

    Unidades por tarefa: tokens (agent/vision/news/embeddings/search), segundos de áudio (stt),
    caracteres (tts).
    """

    provider: str
    task: ProviderTask
    model: str
    input_units: float = 0.0
    output_units: float = 0.0
    usd: float = 0.0


@dataclass(frozen=True, slots=True)
class ApiKey:
    """Chave lida do keyring (R21.2, R21.4). ``name`` é o nome no keyring; o segredo não aparece
    em ``repr``."""

    provider: str
    name: str
    secret: str = field(repr=False)


@runtime_checkable
class KeyPool(Protocol):
    """Rodízio de chaves de um provedor (R21.2, R21.3, §4.7).

    Em 429/401/403 a chave fica em espera 60 s, dobrando até 1 h; sucesso zera a espera.
    """

    provider: str

    def acquire(self) -> ApiKey:
        """Próxima chave disponível, em rodízio. Levanta ``NoKeyAvailable``."""
        ...

    def mark_ok(self, key: ApiKey) -> None: ...

    def mark_failed(self, key: ApiKey, status: int) -> None:
        """Registra falha HTTP; 429/401/403 colocam a chave em espera."""
        ...

    def available(self) -> int:
        """Quantas chaves estão fora de espera agora."""
        ...


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    """Gasto do mês corrente (R16.1-R16.5). ``fraction`` = spent/cap."""

    spent_usd: float
    cap_usd: float

    @property
    def fraction(self) -> float:
        return self.spent_usd / self.cap_usd if self.cap_usd > 0 else 1.0


@runtime_checkable
class Budget(Protocol):
    """Orçamento mensal (R16, §4.6). Quem chama provedores não fala com o Budget: o registro de
    provedores (3.1) chama ``ensure_allowed`` antes e ``record`` depois de cada chamada paga."""

    async def ensure_allowed(self, task: ProviderTask) -> None:
        """Levanta ``BudgetExceeded`` se o teto foi atingido e ``task`` é bloqueável (R16.4)."""
        ...

    async def record(self, usage: Usage) -> None:
        """Grava em ``costs`` (R16.1)."""
        ...

    async def status(self) -> BudgetStatus:
        """Gasto do mês corrente; o mês vira sozinho no dia 1 (R16.5)."""
        ...

    async def set_cap(self, usd: float) -> None:
        """Ajuste do teto por voz/config (R16.2)."""
        ...


class Provider(Protocol):
    """Base de provedor por tarefa (R21.1, R21.5).

    ``free_tier``: em cota gratuita; chamadas com ``personal=True`` levantam
    ``PersonalDataRefused``. ``personal`` é obrigatório em toda chamada: ``True`` quando o
    conteúdo tem memória, voz, humor ou capturas.
    """

    name: str
    model: str
    free_tier: bool


@runtime_checkable
class SttProvider(Provider, Protocol):
    """Transcrição (R3.1, R3.2). Áudio só em memória, nunca em disco (R3.6)."""

    async def transcribe(
        self, audio: bytes, fmt: PcmFormat, *, hint: str = "", language: str = "pt", personal: bool
    ) -> Transcript:
        """``hint``: vocabulário de dica (≤ 200 tokens). Devolve ``Transcript.raw``.
        Texto vazio é retorno válido; falha levanta ``ProviderError``."""
        ...


@runtime_checkable
class TtsProvider(Provider, Protocol):
    """TTS em streaming com voz feminina (R12.1)."""

    output_format: PcmFormat

    def synthesize(self, text: str | AsyncIterable[str], *, personal: bool) -> AsyncIterator[bytes]:
        """PCM em ``output_format``, em pedaços, conforme chega. ``text`` pode ser um fluxo."""
        ...


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Ferramenta oferecida ao modelo (R9-R14). ``parameters``: JSON Schema do objeto de args."""

    name: str
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Chamada de ferramenta pedida pelo modelo (R9-R14)."""

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Mensagem de conversa (R11.3). ``tool_call_id`` só em ``role="tool"``; ``tool_calls`` só em
    ``assistant``."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChatReply:
    """Resposta do modelo (R12.3). ``usage`` já foi registrado pelo registro de provedores."""

    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage | None = None


@runtime_checkable
class ChatProvider(Provider, Protocol):
    """Modelo de chat para o agente (R9-R14) e a classificação de notícias (R19.1)."""

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] = (),
        json_mode: bool = False,
        personal: bool,
    ) -> ChatReply: ...


@runtime_checkable
class VisionProvider(Provider, Protocol):
    """Pergunta sobre uma captura de tela (R9). Captura é sempre ``personal=True`` (R21.5)."""

    async def ask(
        self, question: str, image: bytes, *, mime: str = "image/png", personal: bool
    ) -> ChatReply: ...


@runtime_checkable
class EmbeddingProvider(Provider, Protocol):
    """Embeddings (R11.2, R18.3). ``dimensions`` segue o modelo configurado (§7)."""

    dimensions: int

    async def embed(self, texts: Sequence[str], *, personal: bool) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class SearchSource:
    """Fonte citada pela pesquisa (R10.3)."""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Resposta da pesquisa com fontes (R10.1, R10.3)."""

    answer: str
    sources: tuple[SearchSource, ...] = ()
    usage: Usage | None = None


@runtime_checkable
class SearchProvider(Provider, Protocol):
    """Pesquisa externa (R10). Recebe só a pergunta reescrita, sem memória/humor (R10.2)."""

    async def search(self, query: str, *, personal: bool) -> SearchResult: ...


@runtime_checkable
class ProviderRegistry(Protocol):
    """Provedor configurado por tarefa (R21.1). Os objetos devolvidos já aplicam KeyPool,
    bloqueio de ``personal`` em cota gratuita e Budget. Releitura da config troca os provedores."""

    def stt(self) -> SttProvider: ...

    def tts(self) -> TtsProvider: ...

    def chat(self, task: ProviderTask = ProviderTask.AGENT) -> ChatProvider:
        """``task`` é ``agent`` ou ``news``."""
        ...

    def vision(self) -> VisionProvider: ...

    def embeddings(self, task: ProviderTask = ProviderTask.EMBEDDINGS) -> EmbeddingProvider:
        """``task`` é ``embeddings`` (memórias) ou ``news`` (agrupamento, R18.3)."""
        ...

    def search(self) -> SearchProvider: ...


# ---------------------------------------------------------------------------------------------
# Registros do banco (§7) e repositórios
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """Linha de ``turns`` (R11.6, R22.3)."""

    satellite: str
    text_heard: str
    text_final: str
    at: datetime
    intent: str | None = None
    routed_local: bool = False
    reply: str = ""
    mood: int | None = None
    cost_usd: float = 0.0
    id: int | None = None


@runtime_checkable
class TurnsRepo(Protocol):
    """Histórico local de turnos, consultável e apagável (R11.6)."""

    async def add(self, turn: TurnRecord) -> int: ...

    async def last(self, satellite: str | None = None) -> TurnRecord | None: ...

    async def recent(self, limit: int = 20) -> list[TurnRecord]: ...

    async def delete(self, turn_id: int) -> None: ...

    async def delete_all(self) -> int: ...


@dataclass(frozen=True, slots=True)
class Correction:
    """Par ouvido -> certo (R3.3, R3.4)."""

    heard: str
    correct: str
    uses: int = 0
    created_at: datetime | None = None
    id: int | None = None


@runtime_checkable
class CorrectionsRepo(Protocol):
    """Correções salvas (R3.3, R3.4)."""

    async def add(self, heard: str, correct: str) -> Correction:
        """Cria ou atualiza o par para o mesmo ``heard``."""
        ...

    async def all(self) -> list[Correction]: ...

    async def bump(self, correction_id: int) -> None:
        """Incrementa ``uses``."""
        ...

    async def delete(self, correction_id: int) -> None: ...


@dataclass(frozen=True, slots=True)
class VocabTerm:
    """Termo de vocabulário (R3.2, R11.4). ``kind``: ``slang`` | ``name`` | ``nickname``."""

    term: str
    kind: str
    weight: float = 1.0


@runtime_checkable
class VocabRepo(Protocol):
    """Gírias, nomes e apelidos para a dica do STT (R3.2, R11.4)."""

    async def all(self, kind: str | None = None) -> list[VocabTerm]: ...

    async def upsert(self, term: VocabTerm) -> None: ...


@dataclass(frozen=True, slots=True)
class Profile:
    """Perfil compacto, ≤ 300 tokens (R11.1)."""

    body: str
    updated_at: datetime


@runtime_checkable
class ProfileRepo(Protocol):
    """Perfil único (``profile.id = 1``), atualizado no máximo 1×/dia (R11.1, R11.4)."""

    async def get(self) -> Profile | None: ...

    async def put(self, body: str) -> Profile: ...


@dataclass(frozen=True, slots=True)
class Memory:
    """Memória com embedding (R11.2, R11.5). ``score``: similaridade na busca (0..1)."""

    kind: str
    body: str
    turn_id: int | None = None
    created_at: datetime | None = None
    id: int | None = None
    score: float | None = None


@runtime_checkable
class MemoriesRepo(Protocol):
    """Memórias pessoais (R11.2, R11.5)."""

    async def add(self, memory: Memory, embedding: Sequence[float]) -> int: ...

    async def search(self, embedding: Sequence[float], limit: int = MEMORY_TOP_K) -> list[Memory]: ...

    async def delete_by_turn(self, turn_id: int) -> int:
        """Apaga as memórias do turno ("esquece isso"); devolve quantas."""
        ...

    async def delete(self, memory_id: int) -> None: ...


class HelpStep(IntEnum):
    """Degraus da ajuda no jogo (R14.1)."""

    HINT = 1
    DIRECT = 2
    SOLUTION = 3


@dataclass(frozen=True, slots=True)
class HelpEntry:
    """Linha de ``help_log`` (R14.3)."""

    game_appid: int
    topic: str
    step: HelpStep
    at: datetime
    id: int | None = None


@runtime_checkable
class HelpLogRepo(Protocol):
    """Histórico de ajuda por jogo e trecho (R14.3-R14.5)."""

    async def add(self, entry: HelpEntry) -> int: ...

    async def last_step(self, game_appid: int, topic: str) -> HelpStep | None: ...

    async def topics(self, game_appid: int) -> list[str]:
        """Tópicos canônicos já usados no jogo (para casar o trecho)."""
        ...

    async def count_since(self, game_appid: int, topic: str, since: datetime) -> int: ...


@dataclass(frozen=True, slots=True)
class MoodEvent:
    """Sinal de humor (R13.3, R13.5). ``signal`` ex.: ``energy``, ``words``, ``explicit``."""

    signal: str
    value: float
    at: datetime


@runtime_checkable
class MoodEventsRepo(Protocol):
    """Sinais de humor (R13.3-R13.5)."""

    async def add(self, event: MoodEvent) -> None: ...

    async def since(self, at: datetime) -> list[MoodEvent]: ...


@runtime_checkable
class CostsRepo(Protocol):
    """Custos por chamada (R16.1, R16.5, tabela ``costs``)."""

    async def add(self, usage: Usage, at: datetime) -> int: ...

    async def month_total(self, year: int, month: int) -> float: ...


class MusicSignalValue(IntEnum):
    """Valores de ``music_signals.signal`` (R8.3-R8.5)."""

    SKIPPED = -1  # pulada < 30 s
    FINISHED = 1  # ouvida até o fim
    LIKED = 2  # "essa é boa"
    NEVER = -99  # "nunca mais toca isso"


@dataclass(frozen=True, slots=True)
class MusicSignal:
    """Sinal de gosto por faixa e contexto (R8.3-R8.5). ``context``: horário, jogo, pedido."""

    track_uri: str
    artist: str
    signal: MusicSignalValue
    at: datetime
    context: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class MusicSignalsRepo(Protocol):
    """Sinais de música (R8.3-R8.5)."""

    async def add(self, signal: MusicSignal) -> None: ...

    async def banned_tracks(self) -> set[str]:
        """URIs com ``NEVER``: nunca escolher de novo (R8.5)."""
        ...

    async def recent(self, limit: int = 100) -> list[MusicSignal]: ...


@dataclass(frozen=True, slots=True)
class TasteEntry:
    """Peso de gosto por artista/gênero (R8.1, R8.2)."""

    artist: str
    genre: str
    weight: float


@runtime_checkable
class TasteRepo(Protocol):
    """Perfil de gosto musical (R8.1, R8.2)."""

    async def upsert(self, entries: Sequence[TasteEntry]) -> None: ...

    async def top(self, limit: int = 50, genre: str | None = None) -> list[TasteEntry]: ...

    async def adjust(self, artist: str, delta: float) -> None: ...


class NewsLevel(StrEnum):
    """Nível de entrega de uma notícia (R19.4)."""

    BOMBA = "bomba"
    ALTA = "alta"
    NORMAL = "normal"
    GUARDADA = "guardada"


@dataclass(frozen=True, slots=True)
class NewsSource:
    """Fonte de notícias (R18.1, R18.4). ``kind``: ``rss``|``steam``|``anilist``|``reddit``|
    ``scrape``. ``trust`` 1..3."""

    name: str
    kind: str
    url: str
    trust: int
    id: int | None = None


@dataclass(frozen=True, slots=True)
class NewsRaw:
    """Notícia crua coletada (R18.1, R18.2). ``url`` é único (deduplicação)."""

    source_id: int
    url: str
    title: str
    body: str = ""
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    id: int | None = None


@dataclass(frozen=True, slots=True)
class NewsItem:
    """Fato agrupado de várias fontes (R18.3-R19.6). ``spoiler``: saída da classificação
    (obra, trecho, manchete segura). ``level`` ``None`` até pontuar."""

    title: str
    summary: str = ""
    first_seen: datetime | None = None
    sources: int = 1
    max_trust: int = 1
    franchise: str | None = None
    kind: str | None = None
    spoiler: Mapping[str, Any] | None = None
    priority: float | None = None
    level: NewsLevel | None = None
    delivered_at: datetime | None = None
    id: int | None = None

    @property
    def is_rumor(self) -> bool:
        """Só fontes de confiança 1 (R18.4)."""
        return self.max_trust <= 1


@dataclass(frozen=True, slots=True)
class FranchisePref:
    """Preferência por obra (R19.3, R19.7, R19.8)."""

    franchise: str
    weight: float = 1.0
    dropped: bool = False
    spoilers_ok: bool = False


@dataclass(frozen=True, slots=True)
class Progress:
    """Progresso numa obra (R19.1). ``kind``: ``episode``|``hours``|``achievements``."""

    franchise: str
    kind: str
    value: float
    updated_at: datetime


@runtime_checkable
class NewsRepo(Protocol):
    """Tabelas de notícias do §7 (R18-R20). Entrega: o ``magi-news`` grava ``level`` nos itens; o
    núcleo consulta ``undelivered`` e marca ``mark_delivered`` (não há socket entre os dois)."""

    async def sources(self) -> list[NewsSource]: ...

    async def upsert_source(self, source: NewsSource) -> int: ...

    async def add_raw(self, raw: NewsRaw) -> int | None:
        """``None`` se a URL já existe (R18.1)."""
        ...

    async def ungrouped_raw(self, limit: int = 200) -> list[NewsRaw]: ...

    async def add_item(self, item: NewsItem, embedding: Sequence[float], raw_ids: Sequence[int]) -> int: ...

    async def attach_raw(self, item_id: int, raw_id: int) -> None: ...

    async def similar_items(
        self, embedding: Sequence[float], since: datetime, min_cosine: float, limit: int = 5
    ) -> list[tuple[NewsItem, float]]: ...

    async def update_item(self, item: NewsItem) -> None:
        """Grava classificação, prioridade e nível (exige ``item.id``)."""
        ...

    async def unclassified(self, limit: int = 50) -> list[NewsItem]: ...

    async def undelivered(self, levels: Sequence[NewsLevel], limit: int = 5) -> list[NewsItem]: ...

    async def mark_delivered(self, item_id: int, at: datetime) -> None: ...

    async def search_items(
        self, *, franchise: str | None = None, embedding: Sequence[float] | None = None, limit: int = 5
    ) -> list[NewsItem]:
        """Para perguntas sobre novidades (R20.1)."""
        ...

    async def franchise_prefs(self) -> list[FranchisePref]: ...

    async def set_franchise_pref(self, pref: FranchisePref) -> None: ...

    async def progress(self, franchise: str) -> list[Progress]: ...

    async def set_progress(self, progress: Progress) -> None: ...

    async def add_feedback(self, item_id: int, signal: int, at: datetime) -> None: ...


# ---------------------------------------------------------------------------------------------
# Serviços do núcleo
# ---------------------------------------------------------------------------------------------


@runtime_checkable
class SatelliteLink(Protocol):
    """Conexão do núcleo com um satélite (R22.1, R22.3). Implementada pelo servidor Wyoming (1.4)."""

    hello: SatelliteHello

    async def send(self, msg: CoreToSatellite) -> None: ...

    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
        """Envia ``audio-start``, ``audio-chunk``... e ``audio-stop``. Volta ao fim do envio,
        não da reprodução (essa termina com ``playback-done``)."""
        ...


@runtime_checkable
class Speaker(Protocol):
    """Fala no satélite: cache de frases curtas ou TTS em streaming (R12.1, R12.2, 1.12)."""

    async def say(self, text: str, link: SatelliteLink, *, personal: bool) -> None: ...


@runtime_checkable
class Corrector(Protocol):
    """Aplica correções salvas ao texto antes do roteador (R3.4)."""

    async def apply(self, transcript: Transcript) -> Transcript: ...


@runtime_checkable
class Router(Protocol):
    """Roteador local (R4, §4.2). Recebe o texto já corrigido."""

    def route(self, text: str, ctx: TurnContext) -> RouteResult: ...


@dataclass(frozen=True, slots=True)
class Game:
    """Jogo instalado da Steam (R5.1, R15.5). ``aliases``: apelidos aprendidos."""

    appid: int
    name: str
    install_dir: str = ""
    aliases: tuple[str, ...] = ()


@runtime_checkable
class GameCatalog(Protocol):
    """Jogos instalados e busca aproximada (R4.4, R5.1, R5.2, tarefa 1.7)."""

    def all(self) -> list[Game]: ...

    def get(self, appid: int) -> Game | None: ...

    def find(self, name: str, limit: int = 3) -> list[tuple[Game, float]]:
        """Candidatos por nota 0..100, maior primeiro."""
        ...

    async def add_alias(self, appid: int, alias: str) -> None: ...


@runtime_checkable
class Agent(Protocol):
    """Agente LangGraph (R9-R14, 3.4). Devolve fala curta + texto completo."""

    async def answer(self, text: str, ctx: TurnContext) -> ActionResult: ...


@runtime_checkable
class ActionHandler(Protocol):
    """Executor de ações locais (R5-R8). ``intents``: ids de ``IntentId`` que atende.

    Ação perigosa sem ``req.confirmed`` devolve ``needs_confirmation=True``, ``dangerous=True``
    e ``on_confirm`` (R5.3). Erros esperados viram ``ActionResult(ok=False, speech=...)``.
    """

    intents: frozenset[str]

    async def run(self, req: ActionRequest) -> ActionResult: ...


@runtime_checkable
class ActionRegistry(Protocol):
    """Despacho de ``ActionRequest`` para o handler do ``intent.id`` (R5-R8)."""

    def register(self, handler: ActionHandler) -> None: ...

    def handles(self, intent_id: str) -> bool: ...

    async def run(self, req: ActionRequest) -> ActionResult: ...


@runtime_checkable
class HudSink(Protocol):
    """Saída para o HUD (§6, R17). Não levanta se o HUD estiver fechado: descarta."""

    async def send(self, msg: HudMessage) -> None: ...


#: Callback do núcleo para comandos vindos do HUD (§6).
HudCommandHandler = Callable[[CmdMsg], Awaitable[None]]
