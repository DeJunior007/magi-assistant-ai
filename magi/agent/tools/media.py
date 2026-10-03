"""Ferramentas de mídia do agente: ``close_game``, ``rgb``, ``spotify_play``, ``spotify_control`` e
``spotify_pick`` (3.5, R5.3, R6.3, R7, R8).

Como em ``system.py``, só traduzem argumentos em intents da fase 1; quem executa são as ações de
``magi/core/actions`` e ``magi/core/music``. Tocar por nome passa pelo ``play_query`` da 2.2, que
já chama ``MusicSignals.mark_picked`` (``on_play``) — os sinais de música valem também aqui.

``close_game`` é perigosa, mas a frase de confirmação é a do handler ("Fechar Hades? Diz
confirma."): o pedido vai ao registro sem ``confirmed`` e o handler devolve ``needs_confirmation``
com o ``on_confirm`` certo (jogo resolvido, ``force``). ``spotify_pick`` só entra se algum handler
tratar ``music.pick`` (escolha por gosto, 2.5); sem ele, a ficha (3.9) mostra o limite.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from magi.agent.tools.base import SAY_CONFIRM, ActionTool, Mapped, ToolArgsError, arg_int, arg_str
from magi.common.contracts import (
    ActionRegistry,
    ActionRequest,
    ActionResult,
    Expression,
    Intent,
    IntentId,
    Slot,
    SlotName,
    ToolSpec,
    TurnContext,
)

# -- close_game --------------------------------------------------------------------------------

CLOSE_GAME_SPEC = ToolSpec(
    name="close_game",
    description=(
        "Fecha o jogo aberto (ou o jogo citado). Sempre pede confirmação ao usuário antes; "
        "force=true mata o processo à força."
    ),
    parameters={
        "type": "object",
        "properties": {
            "game": {"type": "string", "description": "Nome do jogo; omitido = o jogo aberto"},
            "appid": {"type": "integer", "description": "Appid da Steam, se souber"},
            "force": {"type": "boolean", "description": "Forçar (SIGKILL)"},
        },
    },
)


def map_close_game(args: Mapping[str, Any]) -> Mapped:
    name = arg_str(args, "game")
    appid = arg_int(args, "appid")
    slots: tuple[Slot, ...] = ()
    if appid is not None or name:
        value = str(appid) if appid is not None else name
        slots = (Slot(SlotName.GAME.value, value, raw=name, display=name),)
    extra = {"force": True} if args.get("force") is True else {}
    return Mapped(IntentId.GAME_CLOSE.value, slots, extra)


class CloseGameTool(ActionTool):
    """``close_game``: pergunta pelo handler (frase dele), nunca executa sem "confirma"."""

    def __init__(self, registry: ActionRegistry) -> None:
        super().__init__(CLOSE_GAME_SPEC, map_close_game, registry, danger=True)

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        try:
            m = self.mapper(args)
        except ToolArgsError as e:
            return ActionResult(ok=False, speech=str(e), expression=Expression.CONFUSED)
        intent = Intent(id=m.intent_id, slots=m.slots, danger=True)
        req = ActionRequest(intent=intent, ctx=ctx, text=text, args=dict(m.args))
        result = await self.registry.run(req)  # confirmed=False: o handler só pergunta
        if result.needs_confirmation or not result.ok:
            return result
        # Handler que não perguntou: não confia; devolve a confirmação genérica.
        return ActionResult(ok=True, speech=SAY_CONFIRM, needs_confirmation=True, dangerous=True,
                            on_confirm=ActionRequest(intent=intent, ctx=ctx, text=text,
                                                     args=dict(m.args), confirmed=True))


# -- rgb ---------------------------------------------------------------------------------------

RGB_SPEC = ToolSpec(
    name="rgb",
    description=(
        "Iluminação RGB do PC: color muda a cor (nome em português, ex. 'azul', ou hex '#ff8800'); "
        "brightness define o brilho (0-100). Pode mandar os dois."
    ),
    parameters={
        "type": "object",
        "properties": {
            "color": {"type": "string", "description": "Nome da cor ou #rrggbb"},
            "brightness": {"type": "integer", "minimum": 0, "maximum": 100},
        },
    },
)

_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _color_slot(raw: str) -> Slot:
    value = ("#" + raw.lstrip("#")).lower() if _HEX.match(raw) else raw
    return Slot(SlotName.COLOR.value, value, raw=raw, display=raw)


def map_rgb(args: Mapping[str, Any]) -> list[Mapped]:
    out: list[Mapped] = []
    color = arg_str(args, "color")
    if color:
        out.append(Mapped(IntentId.RGB_COLOR.value, (_color_slot(color),)))
    level = arg_int(args, "brightness")
    if level is not None:
        if not 0 <= level <= 100:
            raise ToolArgsError("Brilho vai de 0 a 100.")
        out.append(Mapped(IntentId.RGB_BRIGHTNESS.value, (Slot(SlotName.BRIGHTNESS.value, str(level)),)))
    if not out:
        raise ToolArgsError("Qual cor ou brilho?")
    return out


class RgbTool(ActionTool):
    """``rgb``: cor e/ou brilho, cada um uma ação do registro (cor primeiro)."""

    def __init__(self, registry: ActionRegistry) -> None:
        super().__init__(RGB_SPEC, lambda a: map_rgb(a)[0], registry)

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        try:
            steps = map_rgb(args)
        except ToolArgsError as e:
            return ActionResult(ok=False, speech=str(e), expression=Expression.CONFUSED)
        results: list[ActionResult] = []
        for m in steps:
            req = ActionRequest(intent=Intent(id=m.intent_id, slots=m.slots), ctx=ctx, text=text)
            res = await self.registry.run(req)
            results.append(res)
            if not res.ok:
                break
        if len(results) == 1:
            return results[0]
        speech = " ".join(r.speech for r in results if r.speech)
        return ActionResult(ok=all(r.ok for r in results), speech=speech,
                            expression=results[-1].expression)


# -- spotify_play ------------------------------------------------------------------------------

#: Prefixo que o ``parse_query`` da 2.2 reconhece para cada tipo.
_KIND_PREFIX = {"track": "a musica", "album": "o album", "playlist": "a playlist", "artist": "o artista"}

SPOTIFY_PLAY_SPEC = ToolSpec(
    name="spotify_play",
    description=(
        "Toca no Spotify pelo nome: faixa, álbum, playlist ou artista. kind diz o tipo se souber; "
        "artist ajuda a achar faixa/álbum. Para retomar, pausar etc. use spotify_control."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Nome da faixa, álbum, playlist ou artista"},
            "kind": {"type": "string", "enum": list(_KIND_PREFIX)},
            "artist": {"type": "string", "description": "Artista da faixa/álbum, se souber"},
        },
        "required": ["query"],
    },
)


def map_spotify_play(args: Mapping[str, Any]) -> Mapped:
    query = arg_str(args, "query")
    if not query:
        raise ToolArgsError("Tocar o quê?")
    kind = arg_str(args, "kind").lower()
    artist = arg_str(args, "artist")
    text = query
    if artist and kind != "artist" and artist.lower() not in query.lower():
        text = f"{query} de {artist}"
    if kind in _KIND_PREFIX:
        text = f"{_KIND_PREFIX[kind]} {text}"
    return Mapped(IntentId.MUSIC_PLAY.value, (Slot(SlotName.QUERY.value, text, raw=query, display=query),))


# -- spotify_control ---------------------------------------------------------------------------

_CONTROL = {
    "open": IntentId.MUSIC_OPEN,
    "play": IntentId.MUSIC_PLAY,
    "pause": IntentId.MUSIC_PAUSE,
    "next": IntentId.MUSIC_NEXT,
    "previous": IntentId.MUSIC_PREVIOUS,
    "volume": IntentId.MUSIC_VOLUME,
    "like": IntentId.MUSIC_LIKE,
    "never": IntentId.MUSIC_NEVER,
}

SPOTIFY_CONTROL_SPEC = ToolSpec(
    name="spotify_control",
    description=(
        "Controla o Spotify: open, play (retomar), pause, next, previous; volume com level (0-100) "
        "ou delta (ex. 10/-10); like = 'essa é boa'; never = 'nunca mais toca essa'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(_CONTROL)},
            "level": {"type": "integer", "minimum": 0, "maximum": 100},
            "delta": {"type": "integer"},
        },
        "required": ["action"],
    },
)


def map_spotify_control(args: Mapping[str, Any]) -> Mapped:
    action = arg_str(args, "action").lower()
    intent = _CONTROL.get(action)
    if intent is None:
        raise ToolArgsError("Não entendi o que fazer no Spotify.")
    if intent is not IntentId.MUSIC_VOLUME:
        return Mapped(intent.value)
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
    return Mapped(intent.value, (Slot(SlotName.VOLUME.value, value),))


# -- spotify_pick ------------------------------------------------------------------------------

SPOTIFY_PICK_SPEC = ToolSpec(
    name="spotify_pick",
    description="Escolhe e toca uma música pelo gosto do usuário ('coloca uma boa').",
    parameters={"type": "object", "properties": {}},
)


def map_spotify_pick(args: Mapping[str, Any]) -> Mapped:
    return Mapped(IntentId.MUSIC_PICK.value)


def media_tools(registry: ActionRegistry) -> list[ActionTool]:
    """Ferramentas de mídia sobre o registro de ações; ``spotify_pick`` só com handler de
    ``music.pick`` registrado (2.5)."""
    tools: list[ActionTool] = [
        CloseGameTool(registry),
        RgbTool(registry),
        ActionTool(SPOTIFY_PLAY_SPEC, map_spotify_play, registry),
        ActionTool(SPOTIFY_CONTROL_SPEC, map_spotify_control, registry),
    ]
    if registry.handles(IntentId.MUSIC_PICK.value):
        tools.append(ActionTool(SPOTIFY_PICK_SPEC, map_spotify_pick, registry))
    return tools
