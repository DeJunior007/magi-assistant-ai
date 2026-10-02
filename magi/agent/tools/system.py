"""Ferramentas de sistema do agente: ``open_game``, ``hud`` e ``volume`` (3.4, R5.1, R6.1, R6.2).

Só traduzem argumentos em intents da fase 1 (``game.open``, ``hud.*``, ``volume.*``); a
execução é das ações em ``magi/core/actions``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from magi.agent.tools.base import ActionTool, Mapped, ToolArgsError, arg_int, arg_str
from magi.common.contracts import (
    ActionRegistry,
    DetailTarget,
    IntentId,
    Slot,
    SlotName,
    ToolSpec,
)

# -- open_game ---------------------------------------------------------------------------------

OPEN_GAME_SPEC = ToolSpec(
    name="open_game",
    description="Abre um jogo da biblioteca Steam pelo nome (ou appid).",
    parameters={
        "type": "object",
        "properties": {
            "game": {"type": "string", "description": "Nome do jogo"},
            "appid": {"type": "integer", "description": "Appid da Steam, se souber"},
        },
    },
)


def map_open_game(args: Mapping[str, Any]) -> Mapped:
    name = arg_str(args, "game")
    appid = arg_int(args, "appid")
    if appid is None and not name:
        raise ToolArgsError("Qual jogo?")
    value = str(appid) if appid is not None else name
    slot = Slot(SlotName.GAME.value, value, raw=name, display=name)
    return Mapped(IntentId.GAME_OPEN.value, (slot,))


# -- hud ---------------------------------------------------------------------------------------

HUD_ACTIONS = ("open", "close", "idle", "full", "toggle_view", "detail", "rgb_sync")

HUD_SPEC = ToolSpec(
    name="hud",
    description=(
        "Controla o HUD: open/close; idle (modo ocioso), full (completo) ou toggle_view; "
        "detail mostra painel cpu/gpu/memory (none fecha); rgb_sync liga/desliga o RGB sincronizado."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(HUD_ACTIONS)},
            "detail": {"type": "string", "enum": [t.value for t in DetailTarget]},
            "on": {"type": "boolean", "description": "Para rgb_sync; omitido alterna"},
        },
        "required": ["action"],
    },
)


def map_hud(args: Mapping[str, Any]) -> Mapped:
    action = arg_str(args, "action").lower()
    match action:
        case "open":
            return Mapped(IntentId.HUD_OPEN.value)
        case "close":
            return Mapped(IntentId.HUD_CLOSE.value)
        case "idle" | "full":
            return Mapped(IntentId.HUD_IDLE_TOGGLE.value, args={"view": action})
        case "toggle_view":
            return Mapped(IntentId.HUD_IDLE_TOGGLE.value)
        case "detail":
            target = arg_str(args, "detail").lower()
            return Mapped(IntentId.HUD_DETAIL.value, (Slot(SlotName.DETAIL.value, target),))
        case "rgb_sync":
            on = args.get("on")
            slots = () if on is None else (Slot(SlotName.ON_OFF.value, "on" if on else "off"),)
            return Mapped(IntentId.HUD_RGB_SYNC.value, slots)
    raise ToolArgsError("Não entendi o que fazer com o HUD.")


# -- volume ------------------------------------------------------------------------------------

VOLUME_SPEC = ToolSpec(
    name="volume",
    description=(
        "Volume do sistema: level (0-100) define; delta (ex.: 10 ou -10) ajusta; "
        "mute true/false muda ou tira o mudo."
    ),
    parameters={
        "type": "object",
        "properties": {
            "level": {"type": "integer", "minimum": 0, "maximum": 100},
            "delta": {"type": "integer"},
            "mute": {"type": "boolean"},
        },
    },
)


def map_volume(args: Mapping[str, Any]) -> Mapped:
    mute = args.get("mute")
    if isinstance(mute, bool):
        return Mapped((IntentId.VOLUME_MUTE if mute else IntentId.VOLUME_UNMUTE).value)
    level = arg_int(args, "level")
    if level is not None:
        if not 0 <= level <= 100:
            raise ToolArgsError("Volume vai de 0 a 100.")
        value = str(level)
    else:
        delta = arg_int(args, "delta")
        if not delta:
            raise ToolArgsError("Quanto de volume?")
        value = f"{delta:+d}"
    return Mapped(IntentId.VOLUME_SET.value, (Slot(SlotName.VOLUME.value, value),))


def system_tools(registry: ActionRegistry) -> list[ActionTool]:
    """Ferramentas ``open_game``, ``hud`` e ``volume`` sobre o registro de ações do núcleo."""
    return [
        ActionTool(OPEN_GAME_SPEC, map_open_game, registry),
        ActionTool(HUD_SPEC, map_hud, registry),
        ActionTool(VOLUME_SPEC, map_volume, registry),
    ]
