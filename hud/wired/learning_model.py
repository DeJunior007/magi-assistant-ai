"""Estado da tela learning (LM1.6; design §4.1, §5, §9; spec §4, §6, §7, §10) — puro, sem Qt.

O ``hud_bridge`` entrega **todo** ``lm_*`` vindo do núcleo a ``LearningModel.feed(msg, now)``
(``lm_mode``, ``lm_session``, ``lm_msg``, ``lm_result`` por ``id``, ``lm_obs``, ``lm_topic``,
``lm_saved``, ``lm_summary``); o ``gamerhud`` repassa também ``state``/``speech``/``subtitle``/
``mouth`` (``on_state``/``on_speech``/``on_subtitle``/``on_mouth``). As telas só leem daqui:
LM2.2, LM3.4, LM3.5, LM4.3 e LM4.6 não precisam mexer neste arquivo.

- **Mensagens:** únicas por ``id`` (reenvio na reconexão substitui, não duplica), em ordem de
  ``id``, no máximo ``MAX_MESSAGES`` (as 200 últimas, como a recarga da spec §10). ``lm_session``
  com outro ``id`` começa o histórico do zero.
- **Rolagem:** ``scroll`` em px lógicos a partir do fim (0 = acompanhando a última mensagem);
  mensagem nova volta a acompanhar.
- **Mensagem em fala (LM-003, spec §4.5):** ``lm_msg`` da Condessa com ``speaking = true`` é
  revelada palavra a palavra pela **mesma** lógica da legenda (``speech_caption.SpeechCaption``,
  alimentada com os mesmos ``state``/``speech``/``subtitle``/``mouth``): a mensagem mostra tantas
  palavras quanto a legenda já revelou. Se ela chega com a fala em andamento, segue a fala; se
  chega em ``thinking``, fica oculta até a fala começar (no máximo ``SPEECH_WAIT_S``); se a fala já
  acabou (ou nunca vem), aparece inteira. No primeiro ``state`` fora da fala, fica inteira e
  selecionável (``speaking_id`` volta a ``None``).
- Os campos de ``LearningInfo`` (LM1.5) continuam aqui com os mesmos nomes e padrões
  (``LearningInfo`` = ``LearningModel`` em ``learning_screen``).
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

try:  # o HUD põe ``hud/`` no sys.path (gamerhud e testes)
    from speech_caption import SpeechCaption
except ImportError:  # pragma: no cover - importado como pacote ``hud.wired``
    from hud.speech_caption import SpeechCaption  # type: ignore[no-redef]

MAX_MESSAGES = 200       # histórico na tela (= recarga do banco na reconexão, spec §10)
SPEECH_WAIT_S = 3.0      # lm_msg "em fala" chegou antes da fala: espera o speaking até isso
WAVE_N = 48              # barras da onda de áudio (grupo ``input``)
TEXT_MAX = 2000          # lm_say: vazio ou maior que isso é recusado na UI (spec §4.2)
_WORD = re.compile(r"\S+")


@dataclass(frozen=True, slots=True)
class LmMessage:
    """Uma mensagem do histórico (``lm_msg``). Serve como ``MessageLike`` de ``learning_text``."""

    id: int
    author: str          # "you" | "condessa"
    source: str          # "voice" | "text"
    text: str
    at: str = ""
    text_final: str | None = None


def word_end(text: str, n: int) -> int:
    """Offset do fim da ``n``-ésima palavra (``\\S+``) de ``text``; ``n`` ≤ 0 → 0."""
    if n <= 0:
        return 0
    end = 0
    for i, m in enumerate(_WORD.finditer(text), 1):
        end = m.end()
        if i >= n:
            break
    return end


def session_no(session_id: str | None) -> int | None:
    """``LS-20261007-03`` → 3."""
    if not session_id:
        return None
    tail = session_id.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else None


@dataclass
class LearningModel:
    """Estado do Learning Mode visto pelo HUD. ``feed`` e ``on_*`` devolvem os grupos da
    ``LearningScreen`` afetados (para quem quiser invalidar só eles)."""

    # --- campos de LearningInfo (LM1.5), mesmos nomes e padrões
    session_active: bool = True
    session_no: int = 1
    language: str = "ENGLISH"
    level: str = "B2"
    mode: str = "CONVERSATION"
    action_running: bool = False
    connected: bool = True
    speak_replies: bool = True   # SPEAKING ● ACTIVE/OFF
    muted: bool = False          # LISTENING ● READY/MUTED
    magi_open: bool = True       # MAGI SYSTEM aberto ou recolhido a uma linha
    log: str | None = None       # linha do rodapé
    # --- LM1.6
    mode_on: bool = False                     # último lm_mode confirmado pelo núcleo
    session: dict[str, Any] = field(default_factory=dict)    # último lm_session
    messages: list[LmMessage] = field(default_factory=list)  # em ordem de id
    results: dict[str, dict[str, Any]] = field(default_factory=dict)  # lm_result por id da ação
    pending_actions: set[str] = field(default_factory=set)   # lm_action enviados sem resultado
    obs_items: list[dict[str, Any]] = field(default_factory=list)
    obs_count: int = 0
    topic: dict[str, Any] = field(default_factory=dict)      # último lm_topic (confirmação)
    saved: dict[str, dict[str, Any]] = field(default_factory=dict)  # lm_saved por norm
    summary: dict[str, Any] | None = None    # último lm_summary
    summary_at: float | None = None          # instante (monotônico) em que ele chegou
    state: str = "sleeping"                  # expressão do núcleo (spec §7)
    mouth: float = 0.0
    scroll: float = 0.0                      # px lógicos a partir do fim (0 = acompanhando)
    speaking_id: int | None = None           # mensagem da Condessa sendo revelada
    msg_version: int = 0                     # muda quando a lista de mensagens muda
    clock: Callable[[], float] = field(default=time.monotonic, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.caption = SpeechCaption()
        self.wave: deque[float] = deque([0.0] * WAVE_N, maxlen=WAVE_N)
        self._pending_until: float | None = None  # em fala, esperando o speaking começar

    # ================================================================ lm_* (núcleo → UI)

    def feed(self, msg: dict[str, Any], now: float | None = None) -> set[str]:
        """Aplica uma mensagem ``lm_*`` já decodificada. Tipo desconhecido ou só UI → núcleo:
        ignorado (conjunto vazio)."""
        now = self.clock() if now is None else now
        fn = getattr(self, "_on_" + str(msg.get("t", "")), None)
        if fn is None:
            return set()
        try:
            return fn(msg, now)
        except (KeyError, TypeError, ValueError):
            return set()  # campo faltando/errado (decoder mínimo não valida lm_*): ignora

    def _on_lm_mode(self, m: dict[str, Any], now: float) -> set[str]:
        on = bool(m["on"])
        self.mode_on = self.session_active = on
        if on:
            self.summary = self.summary_at = None  # cartão LAST SESSION some ao voltar (LM4.6)
        else:
            self._finish_speech()
            self.pending_actions.clear()
            self.action_running = False
        return {"header", "condessa", "history", "input", "footer"}

    def _on_lm_session(self, m: dict[str, Any], now: float) -> set[str]:
        sid = str(m["id"])
        if self.session.get("id") not in (None, sid):
            self._reset_session()
        self.session = dict(m)
        self.mode_on = self.session_active = True
        no = session_no(sid)
        if no is not None:
            self.session_no = no
        if m.get("level"):
            self.level = str(m["level"]).upper()
        if m.get("track"):
            self.mode = str(m["track"]).upper()
        if "obs_count" in m:
            self.obs_count = int(m["obs_count"])
        return {"header", "condessa", "system", "obs", "topic", "history"}

    def _reset_session(self) -> None:
        self.messages = []
        self.results.clear()
        self.pending_actions.clear()
        self.obs_items = []
        self.obs_count = 0
        self.topic = {}
        self.scroll = 0.0
        self.action_running = False
        self._finish_speech()
        self.msg_version += 1

    def _on_lm_msg(self, m: dict[str, Any], now: float) -> set[str]:
        msg = LmMessage(id=int(m["id"]), author=str(m["author"]), source=str(m.get("source", "text")),
                        text=str(m["text"]), at=str(m.get("at", "")),
                        text_final=m.get("text_final"))
        ids = [x.id for x in self.messages]
        if msg.id in ids:
            self.messages[ids.index(msg.id)] = msg
        else:
            self.messages.append(msg)
            if ids and msg.id < ids[-1]:
                self.messages.sort(key=lambda x: x.id)
            del self.messages[:-MAX_MESSAGES]
        self.msg_version += 1
        self.scroll = 0.0  # mensagem nova: volta a acompanhar o fim
        if m.get("speaking") and msg.author == "condessa":
            self.speaking_id = msg.id
            if self.caption.speaking:
                self._pending_until = None            # a fala já está tocando: segue ela
            elif self.state == "thinking":
                self._pending_until = now + SPEECH_WAIT_S  # a fala vem logo: oculta até lá
            else:
                self._finish_speech()                 # a fala já acabou: inteira
        elif self.speaking_id == msg.id:
            self._finish_speech()
        return {"history"}

    def _on_lm_result(self, m: dict[str, Any], now: float) -> set[str]:
        aid = str(m["id"])
        self.results[aid] = {k: v for k, v in m.items() if k != "t"}
        self.pending_actions.discard(aid)
        self.action_running = bool(self.pending_actions)
        return {"overlay", "condessa"}

    def _on_lm_obs(self, m: dict[str, Any], now: float) -> set[str]:
        self.obs_items = list(m.get("items") or [])
        self.obs_count = int(m.get("count", len(self.obs_items)))
        return {"obs"}

    def _on_lm_topic(self, m: dict[str, Any], now: float) -> set[str]:
        self.topic = {k: v for k, v in m.items() if k != "t"}
        return {"topic"}

    def _on_lm_saved(self, m: dict[str, Any], now: float) -> set[str]:
        self.saved[str(m["norm"])] = {"saved": bool(m["saved"]), "id": m.get("id"), "at": now}
        return {"overlay"}

    def _on_lm_summary(self, m: dict[str, Any], now: float) -> set[str]:
        self.summary = {k: v for k, v in m.items() if k != "t"}
        self.summary_at = now
        return set()  # o cartão vive no painel e na espera (LM4.6)

    # ================================================================ UI → núcleo (estado local)

    def begin_action(self, action_id: str) -> None:
        """``lm_action`` enviado: ``ANALYZING`` até o ``lm_result`` com esse ``id``."""
        self.pending_actions.add(action_id)
        self.action_running = True

    def set_connected(self, up: bool) -> set[str]:
        self.connected = bool(up)
        if not up:
            self.caption = SpeechCaption()
            self._finish_speech()
            self.state = "sleeping"
            self.wave.extend([0.0] * WAVE_N)
        return {"input", "footer", "condessa"}

    # ================================================================ estado / fala / boca

    def on_state(self, expr: str, now: float | None = None, speaking: bool | None = None) -> set[str]:
        """Expressão do núcleo. ``speaking`` (opcional) = o HUD considera a resposta em fala (o
        ``TurnPhase`` conta happy/confused/alert durante a resposta como fala)."""
        now = self.clock() if now is None else now
        self.state = expr
        sp = (expr == "speaking") if speaking is None else bool(speaking)
        self.caption.on_state("speaking" if sp else expr, now)
        out = {"condessa", "input"}
        if self.speaking_id is not None:
            if self.caption.speaking:
                self._pending_until = None
            elif self._pending_until is None or expr != "thinking":
                self._finish_speech()
            out.add("history")
        if not self.caption.speaking:
            self.mouth = 0.0
            self.wave.extend([0.0] * WAVE_N)
        return out

    def on_speech(self, text: str, dur: float | None, now: float | None = None) -> set[str]:
        self.caption.on_speech(text, dur, self.clock() if now is None else now)
        return {"history"} if self.speaking_id is not None else set()

    def on_subtitle(self, text: str, now: float | None = None) -> set[str]:
        self.caption.on_subtitle(text, self.clock() if now is None else now)
        return {"history"} if self.speaking_id is not None else set()

    def on_mouth(self, level: float, now: float | None = None) -> set[str]:
        now = self.clock() if now is None else now
        self.mouth = max(0.0, min(1.0, float(level)))
        self.wave.append(self.mouth)
        self.caption.on_mouth(now)
        return {"input"}

    def _finish_speech(self) -> None:
        self.speaking_id = None
        self._pending_until = None

    def revealed_end(self, msg: LmMessage, now: float | None = None) -> int | None:
        """Até onde ``msg.text`` aparece agora (offset); ``None`` = inteira."""
        if msg.id != self.speaking_id:
            return None
        now = self.clock() if now is None else now
        if self._pending_until is not None:
            if now < self._pending_until:
                return 0
            self._finish_speech()
            return None
        if not self.caption.speaking:
            self._finish_speech()
            return None
        n = len(_WORD.findall(self.caption.text(now)))
        end = word_end(msg.text, n)
        return None if end >= len(msg.text.rstrip()) else end

    def speaking_reveal(self, now: float | None = None) -> int | None:
        """``revealed_end`` da mensagem em fala (``None`` = nenhuma em fala ou já inteira)."""
        if self.speaking_id is None:
            return None
        for m in reversed(self.messages):
            if m.id == self.speaking_id:
                return self.revealed_end(m, now)
        return None

    def deadline(self, now: float | None = None) -> float | None:
        """Próximo instante em que a revelação muda (``None`` = parada)."""
        if self.speaking_id is None:
            return None
        now = self.clock() if now is None else now
        if self._pending_until is not None:
            return self._pending_until
        return self.caption.deadline(now)

    # ================================================================ rolagem

    def scroll_by(self, dy: float, max_scroll: float) -> bool:
        """Rola ``dy`` px lógicos para trás (positivo = mensagens antigas). Muda algo?"""
        new = max(0.0, min(max(0.0, max_scroll), self.scroll + dy))
        if new == self.scroll:
            return False
        self.scroll = new
        return True

    # ================================================================ leitura

    def message(self, message_id: int) -> LmMessage | None:
        for m in self.messages:
            if m.id == message_id:
                return m
        return None

    def wave_key(self, steps: int = 6) -> tuple[int, ...]:
        return tuple(round(v * steps) for v in self.wave)

    def history_key(self, now: float | None = None) -> tuple:
        return (self.msg_version, round(self.scroll, 1), self.speaking_id, self.speaking_reveal(now))


def check_say(text: str) -> str | None:
    """Texto digitado pronto para ``lm_say`` (aparado) ou ``None`` se vazio/longo demais."""
    t = text.strip()
    return t if t and len(t) <= TEXT_MAX else None


__all__ = ["LearningModel", "LmMessage", "MAX_MESSAGES", "SPEECH_WAIT_S", "TEXT_MAX", "check_say",
           "session_no", "word_end"]
