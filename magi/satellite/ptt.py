"""Apertar pra falar (R1.3, R1.4, R1.7; design §3.3; spike S2).

Duas fontes alimentam a mesma máquina de estados (``PushToTalk``):

- **Teclado:** atalho global do KDE (KGlobalAccel, dentro do KWin), componente
  ``magi-satellite``, ação ``push_to_talk``, tecla padrão **Pause**. Sinais
  ``globalShortcutPressed``/``globalShortcutReleased``; ``Repeated`` é ignorado.
- **DualSense:** ``python-evdev`` no nó "DualSense Wireless Controller" (054c:0ce6), **sem grab**
  (o jogo e a Steam continuam vendo os botões). **PS + Share** segurados juntos = pressionado;
  soltar qualquer um = soltar. O nó ``eventN`` muda a cada reconexão: é redescoberto por
  vendor/product + nome em ``/sys/class/input``. Leitura via ACL ``uaccess`` (sem grupo ``input``).
  Conferir ao vivo se segurar PS + Share dispara algum atalho da Steam (chords/overlay do botão PS).

CUIDADO (S2): o KGlobalAccel roda dentro do KWin e lê **sempre 4 inteiros** de cada ``(ai)``;
um ``a(ai)`` mal formado derruba a sessão. Toda tecla vai por ``qkeyseq()`` e só se usam as
chamadas validadas no spike (``doRegister``, ``setShortcutKeys``, ``setInactive``).

Config (``[satellite]``, tudo opcional)::

    ptt_keyboard = true     # false desliga o atalho de teclado
    ptt_key = "Pause"       # Pause, ScrollLock, Menu, F1..F35, com Meta+/Ctrl+/Alt+/Shift+
    ptt_dualsense = true    # false desliga o PS + Share do DualSense
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
from evdev import ecodes

from magi.common.contracts import MAX_RECORDING_MS
from magi.satellite.vad import Endpointer, SpeechDetector

log = logging.getLogger(__name__)

# --- KGlobalAccel (mesmas chamadas e tipos de spikes/s2_ptt.py) ---
KGA_SERVICE = "org.kde.kglobalaccel"
KGA_PATH = "/kglobalaccel"
KGA_IFACE = "org.kde.KGlobalAccel"
COMP_IFACE = "org.kde.kglobalaccel.Component"
COMPONENT = "magi-satellite"
COMPONENT_FRIENDLY = "Magui satélite"
ACTION = "push_to_talk"
ACTION_FRIENDLY = "Apertar pra falar"
ACTION_ID = [COMPONENT, ACTION, COMPONENT_FRIENDLY, ACTION_FRIENDLY]
SET_PRESENT = 2  # KGlobalAccel::SetShortcutFlag
NO_AUTOLOADING = 4

QT_MODS = {"shift": 0x02000000, "ctrl": 0x04000000, "alt": 0x08000000, "meta": 0x10000000}
QT_KEYS = {f"f{n}": 0x01000030 + n - 1 for n in range(1, 36)}
QT_KEYS.update({"pause": 0x01000008, "scrolllock": 0x01000026, "menu": 0x01000055})
DEFAULT_PTT_KEY = "Pause"

# --- DualSense ---
DUALSENSE_ID = (0x054C, 0x0CE6)
DUALSENSE_NAME = "DualSense Wireless Controller"
DUALSENSE_COMBO = frozenset({ecodes.BTN_MODE, ecodes.BTN_SELECT})  # PS + Share
RETRY_S = 3.0


def parse_key(text: str) -> int:
    """``"Pause"`` / ``"Meta+Ctrl+F12"`` → inteiro do Qt (tecla | modificadores)."""
    *mods, key = (p.strip().lower() for p in text.split("+"))
    try:
        value = QT_KEYS[key]
        for mod in mods:
            value |= QT_MODS[mod]
    except KeyError as e:
        raise ValueError(f"tecla de PTT desconhecida: {text!r}") from e
    return value


def qkeyseq(key: int) -> list[list[int]]:
    """``QKeySequence`` no D-Bus: struct ``(ai)`` com EXATAMENTE 4 inteiros (S2: menos derruba o KWin)."""
    seq = [[int(key), 0, 0, 0]]
    assert all(len(k) == 4 for k in seq)
    return seq


def component_path(name: str = COMPONENT) -> str:
    return "/component/" + "".join(c if c.isalnum() else "_" for c in name)


@dataclass(frozen=True, slots=True)
class PttSettings:
    keyboard: bool = True
    key: str = DEFAULT_PTT_KEY
    dualsense: bool = True

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any]) -> PttSettings:
        sec = raw.get("satellite") or {}
        if not isinstance(sec, Mapping):
            raise ValueError("[satellite] deve ser uma tabela")
        s = cls(keyboard=bool(sec.get("ptt_keyboard", True)), key=str(sec.get("ptt_key", DEFAULT_PTT_KEY)),
                dualsense=bool(sec.get("ptt_dualsense", True)))
        parse_key(s.key)  # valida cedo
        return s


class PttSource(StrEnum):
    KEYBOARD = "keyboard"
    DUALSENSE = "dualsense"


class PushToTalk:
    """Máquina de estados única: pressionado enquanto **alguma** fonte estiver segurando."""

    def __init__(self) -> None:
        self._held: set[PttSource] = set()

    @property
    def pressed(self) -> bool:
        return bool(self._held)

    def set(self, source: PttSource, down: bool) -> None:
        was = self.pressed
        if down:
            self._held.add(source)
        else:
            self._held.discard(source)
        if was != self.pressed:
            log.info("atalho %s (%s)", "pressionado" if self.pressed else "solto", source.value)


class _AlwaysVoiced:
    """VAD falso para o PTT sem Silero: tudo conta como fala (só o limite de 15 s encerra)."""

    def process(self, block: np.ndarray) -> float:
        return 1.0

    def reset(self) -> None:
        pass


def ptt_endpointer(vad: SpeechDetector | None) -> Endpointer:
    """Endpointer do PTT: o fim é soltar o atalho; o VAD só mede o tom. Mantém o teto de 15 s."""
    return Endpointer(vad or _AlwaysVoiced(), silence_ms=MAX_RECORDING_MS, max_ms=MAX_RECORDING_MS,
                      no_speech_ms=None)


# --- teclado: KGlobalAccel ---


class KeyboardPtt:
    """Atalho global do KDE. ``bus`` é um ``dbus_next.aio.MessageBus`` conectado (falso nos testes)."""

    def __init__(self, ptt: PushToTalk, key: str = DEFAULT_PTT_KEY, bus: Any = None) -> None:
        self.ptt = ptt
        self.key = parse_key(key)
        self.bus = bus

    async def _call(self, path: str, iface: str, member: str, signature: str = "", body: list | None = None):
        from dbus_next import Message, MessageType

        reply = await self.bus.call(Message(destination=KGA_SERVICE, path=path, interface=iface,
                                            member=member, signature=signature, body=body or []))
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f"{member}: {reply.error_name}: {reply.body}")
        return reply.body

    def on_message(self, msg: Any) -> None:
        from dbus_next import MessageType

        if (msg.message_type != MessageType.SIGNAL or msg.interface != COMP_IFACE
                or list(msg.body[:2]) != [COMPONENT, ACTION]):
            return
        if msg.member == "globalShortcutPressed":
            self.ptt.set(PttSource.KEYBOARD, True)
        elif msg.member == "globalShortcutReleased":
            self.ptt.set(PttSource.KEYBOARD, False)
        # globalShortcutRepeated (autorrepetição) é ignorado

    async def register(self) -> list:
        from dbus_next import Message

        self.bus.add_message_handler(self.on_message)
        await self.bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                                    interface="org.freedesktop.DBus", member="AddMatch", signature="s",
                                    body=[f"type='signal',interface='{COMP_IFACE}',path='{component_path()}'"]))
        await self._call(KGA_PATH, KGA_IFACE, "doRegister", "as", [ACTION_ID])
        (applied,) = await self._call(KGA_PATH, KGA_IFACE, "setShortcutKeys", "asa(ai)u",
                                      [ACTION_ID, [qkeyseq(self.key)], SET_PRESENT | NO_AUTOLOADING])
        if not applied:
            log.warning("atalho de PTT não aplicado (tecla ocupada por outro atalho do KDE?)")
        return applied

    async def deactivate(self) -> None:
        """Ao sair: ``setInactive`` (o atalho continua registrado; não usar ``unregister``)."""
        self.ptt.set(PttSource.KEYBOARD, False)
        try:
            await self._call(KGA_PATH, KGA_IFACE, "setInactive", "as", [ACTION_ID])
        except Exception as e:  # noqa: BLE001 - saída: só registra
            log.debug("setInactive: %s", e)

    async def run(self) -> None:
        try:
            if self.bus is None:
                from dbus_next.aio import MessageBus

                self.bus = await MessageBus().connect()
            await self.register()
        except Exception as e:  # noqa: BLE001 - sem sessão KDE o satélite segue sem o atalho
            log.error("KGlobalAccel indisponível, PTT do teclado desligado: %s", e)
            return
        log.info("atalho de PTT do teclado ativo (%s/%s)", COMPONENT, ACTION)
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.shield(self.deactivate())


# --- DualSense: evdev ---


def find_dualsense(sys_root: Path = Path("/sys/class/input")) -> str | None:
    """Nó ``/dev/input/eventN`` dos botões do DualSense (muda a cada reconexão)."""
    for node in sorted(sys_root.glob("event*")):
        dev = node / "device"
        try:
            ids = tuple(int((dev / "id" / f).read_text(), 16) for f in ("vendor", "product"))
            name = (dev / "name").read_text().strip()
        except (OSError, ValueError):
            continue
        if ids == DUALSENSE_ID and name == DUALSENSE_NAME:
            return f"/dev/input/{node.name}"
    return None


def _open_device(path: str) -> Any:
    import evdev

    return evdev.InputDevice(path)


class DualSensePtt:
    """PS + Share segurados juntos. Sem controle (ou desconectado), tenta de novo a cada ``retry_s``."""

    def __init__(self, ptt: PushToTalk, *, find: Callable[[], str | None] = find_dualsense,
                 open_device: Callable[[str], Any] = _open_device, retry_s: float = RETRY_S) -> None:
        self.ptt = ptt
        self.find = find
        self.open_device = open_device
        self.retry_s = retry_s
        self.held: set[int] = set()
        self._missing_logged = False

    def handle(self, ev: Any) -> None:
        if ev.type != ecodes.EV_KEY or ev.code not in DUALSENSE_COMBO:
            return
        if ev.value:  # 1 = apertou, 2 = repetição
            self.held.add(ev.code)
        else:
            self.held.discard(ev.code)
        self.ptt.set(PttSource.DUALSENSE, self.held == DUALSENSE_COMBO)

    async def read_once(self) -> None:
        """Acha o nó, lê até desconectar. Nunca usa ``grab()``."""
        node = self.find()
        if node is None:
            if not self._missing_logged:
                log.info("DualSense não encontrado; tentando de novo a cada %.0f s", self.retry_s)
                self._missing_logged = True
            return
        try:
            dev = self.open_device(node)
        except OSError as e:
            log.warning("DualSense em %s sem leitura: %s", node, e)
            return
        self._missing_logged = False
        log.info("DualSense em %s (PS + Share = apertar pra falar)", node)
        try:
            async for ev in dev.async_read_loop():
                self.handle(ev)
        except OSError as e:
            log.info("DualSense desconectado: %s", e)
        finally:
            self.held.clear()
            self.ptt.set(PttSource.DUALSENSE, False)
            dev.close()

    async def run(self) -> None:
        while True:
            await self.read_once()
            await asyncio.sleep(self.retry_s)


def start_sources(ptt: PushToTalk, settings: PttSettings) -> list[asyncio.Task[None]]:
    """Sobe as fontes ligadas na config. Fontes indisponíveis só registram no log."""
    tasks = []
    if settings.keyboard:
        tasks.append(asyncio.create_task(KeyboardPtt(ptt, settings.key).run(), name="ptt-keyboard"))
    if settings.dualsense:
        tasks.append(asyncio.create_task(DualSensePtt(ptt).run(), name="ptt-dualsense"))
    return tasks
