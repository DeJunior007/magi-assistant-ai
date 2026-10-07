"""Ferramenta ``steam_game`` do agente: horas e conquistas de um jogo, lidas do disco da Steam.

``steam_game(game?)``: sem ``game``, o jogo aberto agora. Responde quanto tempo ele jogou, quantas
conquistas tem, as últimas desbloqueadas e as que faltam (só as não secretas; secretas entram na
conta, sem nome, para não dar spoiler). Tudo local (``magi.core.steam_local``): sem rede, sem chave
e sem IA. A fala é curta; a lista vai para a legenda completa do HUD.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from magi.agent.tools.base import arg_str
from magi.common.contracts import ActionResult, Expression, ToolSpec, TurnContext
from magi.core.steam_local import GameStats, SteamLocal, ago

STEAM_GAME_SPEC = ToolSpec(
    name="steam_game",
    description=(
        "Horas jogadas e conquistas da Steam de um jogo instalado (lido do PC, sem pesquisar): "
        "quanto tempo ele tem, quantas conquistas, as últimas e as que faltam. game: nome do jogo; "
        "vazio = o jogo aberto agora."
    ),
    parameters={
        "type": "object",
        "properties": {"game": {"type": "string", "description": "Nome do jogo; vazio = o aberto agora"}},
    },
)

LIST_MAX = 8
SAY_WHICH = "Qual jogo? Não tem nenhum aberto agora."
SAY_NOT_FOUND = "Não achei {game} entre os jogos instalados da Steam."
SAY_NO_DATA = "A Steam ainda não tem horas nem conquistas de {game} neste PC."


def describe(st: GameStats, now: float | None = None) -> tuple[str, str]:
    """(fala curta, texto completo) a partir das estatísticas do jogo."""
    now = time.time() if now is None else now
    name = st.name or f"App {st.appid}"
    bits = []
    if st.minutes is not None:
        bits.append(f"{st.minutes / 60:.0f} horas" if st.minutes >= 60 else f"{st.minutes} minutos")
    if st.achievements:
        bits.append(f"{len(st.unlocked)} de {len(st.achievements)} conquistas")
    speech = f"{name}: " + " e ".join(bits) + "."
    last = st.last_unlock
    if last is not None and last.unlocked_at:
        speech += f" A última foi {last.name}, {ago(now - last.unlocked_at)}."
    lines = [st.summary(now) or "sem dados"]
    if st.unlocked:
        lines.append("\nÚltimas conquistas:")
        lines += [f"- {a.name}: {a.desc}" for a in st.unlocked[:LIST_MAX]]
    visible = [a for a in st.locked if not a.hidden]
    secret = len(st.locked) - len(visible)
    if visible:
        lines.append("\nFaltam:")
        lines += [f"- {a.name}: {a.desc}" for a in visible[:LIST_MAX]]
        if len(visible) > LIST_MAX:
            lines.append(f"- … e mais {len(visible) - LIST_MAX}")
    if secret:
        lines.append(f"\n{secret} secretas ainda bloqueadas (sem spoiler).")
    return speech, "\n".join(lines)


class SteamGameTool:
    spec = STEAM_GAME_SPEC
    danger = False

    def __init__(self, steam: SteamLocal, game: Callable[[], Any] | None = None) -> None:
        self.steam = steam
        self._game = game  # () -> RunningGame | None

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        asked = arg_str(args, "game")
        if asked:
            found = self.steam.find(asked)
            if found is None:
                return ActionResult(ok=False, speech=SAY_NOT_FOUND.format(game=asked),
                                    expression=Expression.CONFUSED)
            appid, name = found
        else:
            g = self._game() if self._game is not None else None
            if g is None or not getattr(g, "appid", None):
                return ActionResult(ok=False, speech=SAY_WHICH, expression=Expression.CONFUSED)
            appid, name = int(g.appid), str(g.name)
        st = self.steam.stats(appid, name)
        if st.minutes is None and not st.achievements:
            return ActionResult(ok=True, speech=SAY_NO_DATA.format(game=name))
        speech, full = describe(st)
        return ActionResult(ok=True, speech=speech, full_text=full)
