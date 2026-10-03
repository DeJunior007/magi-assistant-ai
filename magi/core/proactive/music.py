"""Sugestão de música ao abrir um jogo (tarefa 5.4; R15.3–R15.6).

:class:`MusicSuggester` ouve o ``GameWatcher`` (1.21) e, num ``opened``, classifica o jogo pelas
tags de usuário, gêneros e categorias da Steam (:func:`classify`, R15.5):

- **competitivo** (tags PvP/Competitive/eSports/Battle Royale/MOBA…, ou categoria PvP num jogo
  sem "Single-player") e **imersivo** (RPG, Story Rich, horror, narrativa, exploração, mundo
  aberto) → nunca sugere (R15.4); essas classes vencem as casuais;
- **casual** (casual, arcade, corrida, plataforma, esporte, roguelike/lite) → pode sugerir;
- sem tags conhecidas → não sugere (R15.6: na dúvida, calado).

Mesmo casual, só sugere se: ainda não sugeriu nesta sessão de jogo (R15.3), passou o intervalo
global (``interval_s``, 3 h), o usuário não recusou há pouco (``decline_s``, 12 h), não há música
tocando no Spotify (MPRIS, só leitura) e não há call no Discord (a pergunta não teria resposta).

A sugestão é uma fala curta da persona entregue pelo ``ProactiveSink`` com um
:class:`~magi.core.proactive.sink.Offer`: o satélite abre a escuta curta de confirmação depois da
fala (``TurnMachine.announce(offer=...)``). "sim/bora/pode" (intenção ``confirm.yes``) chama o
``MusicPicker``, que já lê o jogo aberto do ``GameWatcher`` (``wish_for`` com as tags, R15.5);
"não" registra a recusa; silêncio só volta a dormir.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Any

from magi.common.contracts import ActionResult, Expression
from magi.core.proactive.sink import Offer, Outcome, Priority, ProactiveSink

log = logging.getLogger(__name__)

__all__ = ["GameClass", "MusicSuggester", "classify"]

INTERVAL_S = 3 * 3600.0
DECLINE_S = 12 * 3600.0
KIND = "music"


class GameClass(StrEnum):
    CASUAL = "casual"
    IMMERSIVE = "immersive"
    COMPETITIVE = "competitive"
    UNKNOWN = "unknown"


COMPETITIVE_TAGS = frozenset(
    {
        "pvp",
        "competitive",
        "esports",
        "battle royale",
        "moba",
        "hero shooter",
        "tactical shooter",
        "arena shooter",
    }
)
PVP_CATEGORIES = frozenset({"pvp", "online pvp", "lan pvp", "online competitive"})
IMMERSIVE_TAGS = frozenset(
    {
        "rpg",
        "jrpg",
        "action rpg",
        "crpg",
        "party-based rpg",
        "story rich",
        "narrative",
        "interactive fiction",
        "visual novel",
        "choices matter",
        "horror",
        "survival horror",
        "psychological horror",
    }
)
# Fracos: só tornam o jogo imersivo se não houver tag casual (Forza Horizon = racing + open world).
WEAK_IMMERSIVE_TAGS = frozenset({"exploration", "open world"})
CASUAL_TAGS = frozenset(
    {
        "casual",
        "arcade",
        "racing",
        "driving",
        "platformer",
        "2d platformer",
        "3d platformer",
        "precision platformer",
        "sports",
        "roguelike",
        "roguelite",
        "action roguelike",
    }
)


def _low(xs: Iterable[str]) -> set[str]:
    return {x.strip().casefold() for x in xs}


def classify(game: Any) -> GameClass:
    """Classe do jogo (``RunningGame``: ``tags``, ``genres``, ``categories``) para a sugestão."""
    tags = _low((*game.tags, *game.genres))
    cats = _low(game.categories)
    if tags & COMPETITIVE_TAGS or (cats & PVP_CATEGORIES and "single-player" not in cats):
        return GameClass.COMPETITIVE
    if tags & IMMERSIVE_TAGS:
        return GameClass.IMMERSIVE
    if tags & CASUAL_TAGS:
        return GameClass.CASUAL
    if tags & WEAK_IMMERSIVE_TAGS:
        return GameClass.IMMERSIVE
    return GameClass.UNKNOWN


def suggestion(name: str) -> str:
    return f"Quer um som pra acompanhar o {name}?"


class MusicSuggester:
    """``on_game`` é o ouvinte do ``GameWatcher.subscribe``. ``picker``: ``MusicPicker`` (``pick``);
    ``player``: ``SpotifyMpris`` (``state()``), ``None`` = não confere."""

    def __init__(
        self,
        sink: ProactiveSink,
        picker: Any,
        player: Any = None,
        *,
        interval_s: float = INTERVAL_S,
        decline_s: float = DECLINE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sink = sink
        self.picker = picker
        self.player = player
        self.interval_s = interval_s
        self.decline_s = decline_s
        self._clock = clock
        self._last_at: float | None = None
        self._declined_at: float | None = None
        self._session: str | None = None  # chave do jogo já sugerido nesta sessão

    async def on_game(self, event: Any) -> bool:
        """Trata um ``GameEvent``; ``True`` se a sugestão foi entregue."""
        game = event.game
        if event.kind == "closed":
            if self._session == game.key:
                self._session = None
            return False
        why = await self._skip(game)
        if why is not None:
            log.info("sem sugestão de música para %s: %s", game.name, why)
            return False
        self._session = game.key
        self._last_at = self._clock()
        offer = Offer(accept=self._accept, decline=self._decline)
        out = await self.sink.deliver(
            KIND, suggestion(game.name), None, Priority.VOICE, expression=Expression.HAPPY, offer=offer
        )
        log.info("sugestão de música para %s (%s)", game.name, "voz" if out is Outcome.QUEUED else "tela")
        return True

    async def _skip(self, game: Any) -> str | None:
        cls = classify(game)
        if cls is not GameClass.CASUAL:
            return f"jogo {cls}"
        if self._session == game.key:
            return "já sugeri nesta sessão"
        now = self._clock()
        if self._last_at is not None and now - self._last_at < self.interval_s:
            return "sugeri há pouco"
        if self._declined_at is not None and now - self._declined_at < self.decline_s:
            return "recusou há pouco"
        if self.sink.in_call():
            return "em call"
        if await self._playing():
            return "já tem música tocando"
        return None

    async def _playing(self) -> bool:
        if self.player is None:
            return False
        try:
            return bool((await self.player.state()).playing)
        except Exception:  # Spotify fechado ou D-Bus fora: nada tocando
            return False

    async def _accept(self) -> ActionResult:
        return await self.picker.pick()

    def _decline(self) -> None:
        self._declined_at = self._clock()
        log.info("sugestão de música recusada")
