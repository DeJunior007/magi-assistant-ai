"""Ações de sistema: volume do sink padrão (pulsectl) e cor/brilho do RGB (OpenRGB) — R6.2–R6.4.

O volume mexe só no sink padrão (não em fluxos de apps), então não precisa do arquivo de
recuperação do S1. pulsectl e o socket do OpenRGB são bloqueantes: rodam em ``asyncio.to_thread``.
O cliente do OpenRGB é o ``hud/orgb.py`` (só stdlib, compartilhado com o HUD), carregado pelo caminho.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import struct
import unicodedata
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from magi.common.contracts import ActionHandler, ActionRequest, ActionResult, IntentId, SlotName

log = logging.getLogger(__name__)

ORGB_PATH = Path(__file__).resolve().parents[3] / "hud" / "orgb.py"
CLIENT_NAME = "Magi"
DEFAULT_STEP = 10

SAY_RGB_DOWN = "RGB indisponível."
SAY_SOUND_DOWN = "Não achei a saída de som."

#: Cores por nome (PT, sem acento). Tons ajustados para LED (roxo/laranja/amarelo).
COLORS: dict[str, tuple[int, int, int]] = {
    "azul": (0, 0, 255),
    "vermelho": (255, 0, 0),
    "verde": (0, 255, 0),
    "roxo": (150, 0, 255),
    "rosa": (255, 20, 147),
    "laranja": (255, 80, 0),
    "amarelo": (255, 190, 0),
    "branco": (255, 255, 255),
    "ciano": (0, 255, 255),
}
_ALIASES = {"vermelha": "vermelho", "roxa": "roxo", "amarela": "amarelo", "branca": "branco",
            "lilas": "roxo", "violeta": "roxo", "pink": "rosa", "azul claro": "ciano"}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def parse_color(text: str) -> tuple[tuple[int, int, int], str] | None:
    """``"#rrggbb"`` ou nome em PT → ((r, g, b), nome falável). ``None`` se não reconhecer."""
    t = _fold(text)
    if t.startswith("#") and len(t) == 7:
        try:
            rgb = (int(t[1:3], 16), int(t[3:5], 16), int(t[5:7], 16))
        except ValueError:
            return None
        name = next((n for n, c in COLORS.items() if c == rgb), "")
        return rgb, name
    t = _ALIASES.get(t, t)
    if t in COLORS:
        return COLORS[t], t
    for word in t.split():  # "cor azul", "deixa azul"
        word = _ALIASES.get(word, word)
        if word in COLORS:
            return COLORS[word], word
    return None


def _percent(text: str) -> int | None:
    t = text.strip().rstrip("%").strip()
    try:
        return int(round(float(t.replace(",", "."))))
    except ValueError:
        return None


# ---------------------------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------------------------


def _default_pulse() -> Any:
    import pulsectl

    return pulsectl.Pulse(CLIENT_NAME)


class VolumeActions:
    """``volume.set`` (``"30"``, ``"+10"``, ``"-10"``; ``"+"``/``"-"`` = um passo), ``volume.mute``
    e ``volume.unmute``. Subir o volume com o sink mudo também desmuta."""

    intents = frozenset({IntentId.VOLUME_SET, IntentId.VOLUME_MUTE, IntentId.VOLUME_UNMUTE})

    def __init__(self, pulse_factory: Callable[[], Any] | None = None, step: int = DEFAULT_STEP) -> None:
        self._pulse_factory = pulse_factory or _default_pulse
        self._step = step

    async def run(self, req: ActionRequest) -> ActionResult:
        iid = req.intent.id
        if iid == IntentId.VOLUME_SET:
            slot = req.intent.slot(SlotName.VOLUME)
            raw = (slot.value if slot else "").strip()
            if not raw:
                return ActionResult(ok=False, speech="Quanto de volume?")
            relative = raw[0] in "+-"
            n = (self._step if raw == "+" else -self._step) if raw in "+-" else _percent(raw)
            if n is None:
                return ActionResult(ok=False, speech="Não entendi o volume.")
            op = ("rel" if relative else "abs", n)
        else:
            op = ("mute", iid == IntentId.VOLUME_MUTE)
        try:
            return await asyncio.to_thread(self._apply, op)
        except Exception:  # pulsectl.PulseError e afins
            log.exception("volume: falhou")
            return ActionResult(ok=False, speech=SAY_SOUND_DOWN)

    def _apply(self, op: tuple[str, Any]) -> ActionResult:
        kind, arg = op
        with self._pulse_factory() as pulse:
            sink = pulse.get_sink_by_name(pulse.server_info().default_sink_name)
            if kind == "mute":
                if bool(sink.mute) == arg:
                    say = "Já está no mudo." if arg else "O som já está ligado."
                    return ActionResult(ok=True, speech=say)
                pulse.mute(sink, arg)
                return ActionResult(ok=True, speech="Mutado." if arg else "Som de volta.")
            cur = round(sink.volume.value_flat * 100)
            target = max(0, min(100, cur + arg if kind == "rel" else arg))
            pulse.volume_set_all_chans(sink, target / 100)
            if sink.mute and target > 0:
                pulse.mute(sink, False)
            return ActionResult(ok=True, speech=f"Volume em {target}.")


# ---------------------------------------------------------------------------------------------
# RGB
# ---------------------------------------------------------------------------------------------


def load_orgb(path: Path = ORGB_PATH) -> ModuleType:
    """Carrega ``hud/orgb.py`` (o HUD não é pacote)."""
    spec = importlib.util.spec_from_file_location("magi_hud_orgb", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RgbActions:
    """``rgb.color`` (slot ``color``: ``#rrggbb`` ou nome) e ``rgb.brightness`` (0–100)."""

    intents = frozenset({IntentId.RGB_COLOR, IntentId.RGB_BRIGHTNESS})

    def __init__(self, host: str = "127.0.0.1", port: int = 6742, board_only: bool = False,
                 orgb: ModuleType | None = None) -> None:
        self._host, self._port, self._board_only = host, port, board_only
        self._orgb = orgb

    def _mod(self) -> ModuleType:
        if self._orgb is None:
            self._orgb = load_orgb()
        return self._orgb

    async def run(self, req: ActionRequest) -> ActionResult:
        if req.intent.id == IntentId.RGB_COLOR:
            slot = req.intent.slot(SlotName.COLOR)
            parsed = None
            if slot:
                for cand in (slot.value, slot.display, slot.raw):
                    if cand and (parsed := parse_color(cand)):
                        break
            if parsed is None:
                return ActionResult(ok=False, speech="Não conheço essa cor.")
            rgb, name = parsed
            fn, arg = "set_color", rgb
            ok_say = f"RGB {name}." if name else "Cor aplicada."
        else:
            slot = req.intent.slot(SlotName.BRIGHTNESS)
            pct = _percent(slot.value) if slot else None
            if pct is None:
                return ActionResult(ok=False, speech="Quanto de brilho?")
            pct = max(0, min(100, pct))
            fn, arg = "set_brightness", pct
            ok_say = f"Brilho em {pct}%."
        try:
            mod = self._mod()
            done = await asyncio.to_thread(getattr(mod, fn), arg, self._board_only,
                                           self._host, self._port, 1.0, CLIENT_NAME)
        except (OSError, ConnectionError, struct.error, IndexError, ValueError):
            log.warning("OpenRGB não respondeu", exc_info=True)
            return ActionResult(ok=False, speech=SAY_RGB_DOWN)
        if not done:
            say = "Escolhe uma cor primeiro." if fn == "set_brightness" else "Nenhum RGB aceitou a cor."
            return ActionResult(ok=False, speech=say)
        return ActionResult(ok=True, speech=ok_say)


def handlers(pulse_factory: Callable[[], Any] | None = None, rgb_host: str = "127.0.0.1",
             rgb_port: int = 6742, rgb_board_only: bool = False,
             orgb: ModuleType | None = None) -> list[ActionHandler]:
    """Handlers de volume e RGB para o ``Registry``."""
    return [VolumeActions(pulse_factory), RgbActions(rgb_host, rgb_port, rgb_board_only, orgb)]
