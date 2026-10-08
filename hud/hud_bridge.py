"""Ponte HUD <-> núcleo da Magui pelo socket Unix do §6 (tarefa 1.15).

O núcleo é o servidor de `$XDG_RUNTIME_DIR/magi/hud.sock`; o HUD é cliente. A ponte conecta,
reconecta sozinha com backoff (o HUD roda mesmo sem a Magui no ar), lê linhas JSON e emite um
sinal Qt por tipo de mensagem, além do sinal genérico `message(dict)`. No sentido contrário,
`send_cmd()` manda `{"t":"cmd",...}` ao núcleo.

    bridge = HudBridge()
    bridge.stateChanged.connect(face.set_state)
    bridge.mouth.connect(face.set_mouth_level)
    bridge.start()

Escolhas:

- `QLocalSocket` no laço de eventos do Qt, sem thread própria: o socket é não bloqueante e os
  sinais já nascem na thread da GUI (nada de fila entre threads). A `mouth` chega ~20 vezes por
  segundo; cada uma custa um `json.loads` e um `emit`, sem log por mensagem.
- Decodificação: em produção o `hud/` roda com o Python do sistema, sem o venv, e
  `magi.common.events` (que importa `wyoming`) pode não existir. Se o import funcionar, a ponte
  usa `decode_hud` (validação do contrato, tarefa 1.0); se não, usa `_decode_min`, um
  decodificador próprio com as mesmas regras (JSON de uma linha com campo `"t"`, campos e
  valores do contrato). Os dois devolvem o mesmo dict normalizado (o `to_dict()` do contrato),
  e é ele que vai nos sinais: `face`/`gamerhud` não dependem de `magi`.
- Linha inválida (JSON quebrado, tipo desconhecido, campo errado) é ignorada; a conexão segue.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket

log = logging.getLogger("magi.hud.bridge")

BACKOFF_START = 0.5  # s até a primeira nova tentativa
BACKOFF_MAX = 5.0  # s, teto do backoff (dobra a cada falha)
MAX_LINE = 64 * 1024  # linha maior que isso é descartada (proteção do buffer)

# Valores aceitos, espelhando magi/common/contracts.py (Expression, Verdict, CardLevel, DetailTarget).
EXPRESSIONS = frozenset({"sleeping", "listening", "thinking", "speaking", "happy", "confused", "alert"})
VERDICTS = frozenset({"pending", "approved", "denied"})
CARD_LEVELS = frozenset({"bomba", "alta", "normal", "link"})
DETAIL_TARGETS = frozenset({"cpu", "gpu", "memory", "none"})
MOOD_MIN, MOOD_MAX = 0, 4


class DecodeError(ValueError):
    """Linha que não é uma mensagem válida do HUD."""


def hud_socket_path(env: dict[str, str] | None = None) -> Path:
    """`$XDG_RUNTIME_DIR/magi/hud.sock` (ou `/run/user/<uid>`), igual ao contrato."""
    env = os.environ if env is None else env
    base = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "magi" / "hud.sock"


# ---------------------------------------------------------------------------------------------
# Decodificador mínimo (sem magi.common)
# ---------------------------------------------------------------------------------------------


def _field(d: dict[str, Any], key: str, kind: type | tuple[type, ...], default: Any = ...) -> Any:
    if key not in d or d[key] is None:
        if default is ...:
            raise DecodeError(f"campo ausente: {key}")
        return default
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, kind):
        raise DecodeError(f"campo {key} com tipo errado: {v!r}")
    return v


def _choice(d: dict[str, Any], key: str, allowed: frozenset[str]) -> str:
    v = _field(d, key, str)
    if v not in allowed:
        raise DecodeError(f"valor inválido em {key}: {v!r}")
    return v


def _opt(d: dict[str, Any], **items: Any) -> dict[str, Any]:
    d.update({k: v for k, v in items.items() if v is not None})
    return d


def _m_state(d: dict[str, Any]) -> dict[str, Any]:
    return {"t": "state", "v": _choice(d, "v", EXPRESSIONS)}


def _m_subtitle(d: dict[str, Any]) -> dict[str, Any]:
    return _opt({"t": "subtitle", "text": _field(d, "text", str)}, full=_field(d, "full", str, None))


def _m_speech(d: dict[str, Any]) -> dict[str, Any]:
    dur = _field(d, "dur", (int, float), None)
    i = _field(d, "i", int, 0)
    if (dur is not None and dur < 0) or i < 0:
        raise DecodeError(f"fala com dur/i negativo: {dur!r}/{i!r}")
    out = {"t": "speech", "text": _field(d, "text", str), "i": i}
    return _opt(out, dur=None if dur is None else round(float(dur), 3))


def _m_mouth(d: dict[str, Any]) -> dict[str, Any]:
    v = float(_field(d, "v", (int, float)))
    return {"t": "mouth", "v": round(min(1.0, max(0.0, v)), 3)}


def _m_mood(d: dict[str, Any]) -> dict[str, Any]:
    v = _field(d, "v", int)
    if not MOOD_MIN <= v <= MOOD_MAX:
        raise DecodeError(f"humor fora de {MOOD_MIN}..{MOOD_MAX}: {v!r}")
    return {"t": "mood", "v": v}


def _m_vote(d: dict[str, Any]) -> dict[str, Any]:
    out = {"t": "vote", "verdict": _choice(d, "verdict", VERDICTS)}
    return _opt(out, label=_field(d, "label", str, None))


def _m_card(d: dict[str, Any]) -> dict[str, Any]:
    out = {
        "t": "card",
        "level": _choice(d, "level", CARD_LEVELS),
        "title": _field(d, "title", str),
        "url": _field(d, "url", str, ""),
    }
    return _opt(out, source=_field(d, "source", str, None))


def _m_cmd(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"t": "cmd", "name": _field(d, "name", str)}
    args = _field(d, "args", dict, {})
    if args:
        out["args"] = dict(args)
    return out


def _m_detail(d: dict[str, Any]) -> dict[str, Any]:
    return {"t": "detail", "v": _choice(d, "v", DETAIL_TARGETS)}


def _m_lm(d: dict[str, Any]) -> dict[str, Any]:
    """`lm_*` do Learning Mode (LM1.2): sem validação de campos no mínimo; vai como veio."""
    return dict(d)


#: Tipos do Learning Mode (spec §6 do specs/learning-mode).
LM_TYPES = (
    "lm_mode", "lm_session", "lm_say", "lm_msg", "lm_action", "lm_result",
    "lm_obs", "lm_cfg", "lm_topic", "lm_save", "lm_saved", "lm_summary",
)

_MIN_DECODERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "state": _m_state,
    "subtitle": _m_subtitle,
    "speech": _m_speech,
    "mouth": _m_mouth,
    "mood": _m_mood,
    "vote": _m_vote,
    "card": _m_card,
    "cmd": _m_cmd,
    "detail": _m_detail,
    **dict.fromkeys(LM_TYPES, _m_lm),
}


def _decode_min(line: str | bytes) -> dict[str, Any]:
    """Decodificador próprio, compatível com `magi.common.events.decode_hud`."""
    try:
        d = json.loads(line)
    except (ValueError, UnicodeDecodeError) as e:
        raise DecodeError(f"JSON inválido: {e}") from e
    if not isinstance(d, dict) or not isinstance(d.get("t"), str):
        raise DecodeError("mensagem sem campo 't'")
    fn = _MIN_DECODERS.get(d["t"])
    if fn is None:
        raise DecodeError(f"tipo desconhecido: {d['t']!r}")
    return fn(d)


def _encode_min(name: str, args: dict[str, Any] | None) -> bytes:
    d: dict[str, Any] = {"t": "cmd", "name": str(name)}
    if args:
        d["args"] = dict(args)
    return (json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------------------------
# Decodificador do contrato (com magi.common, quando disponível)
# ---------------------------------------------------------------------------------------------

try:  # pragma: no branch - depende do ambiente
    from magi.common.contracts import CmdMsg as _CmdMsg
    from magi.common.contracts import hud_socket_path as _contract_path
    from magi.common.events import decode_hud as _decode_hud
    from magi.common.events import encode_hud_line as _encode_hud_line
except Exception:  # noqa: BLE001 - sem venv/wyoming, ou Python incompatível: usa o mínimo
    _decode_hud = None
    HAS_MAGI = False
else:
    HAS_MAGI = True
    hud_socket_path = _contract_path  # noqa: F811 - o contrato manda quando existe


def _decode_magi(line: str | bytes) -> dict[str, Any]:
    """`decode_hud` do contrato, devolvendo o dict normalizado (`to_dict()`)."""
    assert _decode_hud is not None
    try:
        return _decode_hud(line).to_dict()
    except Exception as e:  # HudDecodeError, ValueError...
        raise DecodeError(str(e)) from e


def _encode_magi(name: str, args: dict[str, Any] | None) -> bytes:
    return _encode_hud_line(_CmdMsg(name=str(name), args=dict(args or {})))


decode_line: Callable[[str | bytes], dict[str, Any]] = _decode_magi if HAS_MAGI else _decode_min
encode_cmd: Callable[[str, dict[str, Any] | None], bytes] = _encode_magi if HAS_MAGI else _encode_min


# ---------------------------------------------------------------------------------------------
# Ponte Qt
# ---------------------------------------------------------------------------------------------


class HudBridge(QObject):
    """Cliente do socket do HUD. Use só na thread da GUI (a do `QApplication`).

    Sinais (opcionais vazios viram `""`):
      message(dict)          toda mensagem válida, já normalizada
      stateChanged(str)      expressão do rosto: sleeping, listening, thinking, ...
      subtitle(str, str)     legenda curta e resposta completa
      speech(str, float, int) frase começando a tocar: texto, duração em s (-1 = sem) e índice
      mouth(float)           nível da boca 0..1 (~20/s enquanto fala)
      mood(int)              termômetro 0..4
      vote(str, str)         veredito (pending/approved/denied) e rótulo da ação
      card(dict)             {"level","title","url"[,"source"]}
      detail(str)            painel de detalhe: cpu, gpu, memory ou none (fecha)
      connectedChanged(bool) conectou/caiu
    """

    message = Signal(dict)
    stateChanged = Signal(str)
    subtitle = Signal(str, str)
    speech = Signal(str, float, int)
    mouth = Signal(float)
    mood = Signal(int)
    vote = Signal(str, str)
    card = Signal(dict)
    detail = Signal(str)
    connectedChanged = Signal(bool)

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        parent: QObject | None = None,
        *,
        backoff_start: float = BACKOFF_START,
        backoff_max: float = BACKOFF_MAX,
    ) -> None:
        super().__init__(parent)
        self.path = Path(path) if path is not None else hud_socket_path()
        self._backoff_start = backoff_start
        self._backoff_max = backoff_max
        self._delay = backoff_start
        self._running = False
        self._connected = False
        self._buf = bytearray()
        self._discarding = False  # dentro de uma linha longa demais, até o próximo \n

        self._sock = QLocalSocket(self)
        self._sock.connected.connect(self._on_connected)
        self._sock.disconnected.connect(self._on_disconnected)
        self._sock.errorOccurred.connect(self._on_error)
        self._sock.readyRead.connect(self._on_ready_read)

        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._try_connect)

        self._dispatch: dict[str, Callable[[dict[str, Any]], None]] = {
            "state": lambda m: self.stateChanged.emit(m["v"]),
            "subtitle": lambda m: self.subtitle.emit(m["text"], m.get("full") or ""),
            "speech": lambda m: self.speech.emit(m["text"], float(m.get("dur", -1.0)), int(m.get("i", 0))),
            "mouth": lambda m: self.mouth.emit(float(m["v"])),
            "mood": lambda m: self.mood.emit(int(m["v"])),
            "vote": lambda m: self.vote.emit(m["verdict"], m.get("label") or ""),
            "card": lambda m: self.card.emit({k: v for k, v in m.items() if k != "t"}),
            "detail": lambda m: self.detail.emit(m["v"]),
        }

    # -- API ------------------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """Começa a conectar (e a reconectar sempre que cair)."""
        if self._running:
            return
        self._running = True
        self._delay = self._backoff_start
        self._try_connect()

    def stop(self) -> None:
        """Fecha a conexão e para de reconectar."""
        self._running = False
        self._retry.stop()
        self._sock.abort()
        self._set_connected(False)

    def send_cmd(self, name: str, args: dict[str, Any] | None = None) -> bool:
        """Envia `{"t":"cmd","name":...}` ao núcleo. Falso se não estiver conectado."""
        if not self._connected:
            return False
        self._sock.write(encode_cmd(name, args))
        self._sock.flush()
        return True

    # -- conexão --------------------------------------------------------------------------

    def _try_connect(self) -> None:
        if not self._running or self._sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            return
        self._buf.clear()
        self._discarding = False
        self._sock.connectToServer(str(self.path))

    def _schedule_retry(self) -> None:
        if not self._running or self._retry.isActive():
            return
        self._retry.start(int(self._delay * 1000))
        self._delay = min(self._delay * 2, self._backoff_max)

    def _set_connected(self, value: bool) -> None:
        if value != self._connected:
            self._connected = value
            log.info("núcleo %s (%s)", "conectado" if value else "desconectado", self.path)
            self.connectedChanged.emit(value)

    def _on_connected(self) -> None:
        self._delay = self._backoff_start
        self._set_connected(True)

    def _on_disconnected(self) -> None:
        self._set_connected(False)
        self._schedule_retry()

    def _on_error(self, _err: QLocalSocket.LocalSocketError) -> None:
        # Falha ao conectar (sem servidor) ou erro com a conexão aberta: tenta de novo depois.
        if self._sock.state() != QLocalSocket.LocalSocketState.ConnectedState:
            self._set_connected(False)
            self._schedule_retry()

    # -- leitura --------------------------------------------------------------------------

    def _on_ready_read(self) -> None:
        self._buf += bytes(self._sock.readAll().data())
        while True:
            nl = self._buf.find(b"\n")
            if nl < 0:
                if len(self._buf) > MAX_LINE:
                    self._buf.clear()
                    self._discarding = True
                return
            line = bytes(self._buf[:nl])
            del self._buf[: nl + 1]
            if self._discarding:
                self._discarding = False
                continue
            if line.strip():
                self.feed_line(line)

    def feed_line(self, line: str | bytes) -> None:
        """Decodifica uma linha e emite os sinais. Linha inválida é ignorada."""
        try:
            msg = decode_line(line)
        except DecodeError as e:
            log.debug("linha ignorada: %s", e)
            return
        self.message.emit(msg)
        fn = self._dispatch.get(msg["t"])
        if fn is not None:
            fn(msg)
