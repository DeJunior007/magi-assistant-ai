"""Tema da sessão do Learning Mode (tarefa LM1.8; design §5.1; spec §10.1; LM-013, LM-014).

``TopicBuilder.build(requested) -> TopicContext``: snapshot do assunto no momento da escolha, a
partir só de fontes que o núcleo já mantém. **Nada de LLM nem rede**:

- ``free``: sem bloco.
- ``interview``: ``prompts/topics/interview.md`` (P14: vaga genérica de engenharia de software,
  ``interview_role`` opcional).
- ``game``: jogo aberto do ``GameWatcher`` (nome, minutos desde ``since``) + horas/conquistas da
  Steam pelo mesmo caminho do ``SteamGameTool`` (``steam.stats`` + ``describe``). Sem jogo aberto
  (P12): o último jogo fechado há menos de 6 h ("you were playing …"); sem nenhum → ``free`` com
  ``detail = "no game detected"``.
- ``news``: até 5 itens das últimas 24 h do ``NewsRepo`` do Rádio Ayanami, **só leitura** (nunca
  ``mark_delivered``), com o filtro de spoiler do rádio (``present``); sem item → ``free`` com
  ``detail = "no news today"``.

O bloco é cortado em ``BLOCK_MAX`` caracteres. O tema é assunto, não roteiro (PRN-002).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from magi.learning.contracts import Topic, TopicContext

__all__ = [
    "BLOCK_MAX",
    "DEFAULT_ROLE",
    "LABELS",
    "LAST_GAME_S",
    "NEWS_MAX",
    "NO_GAME",
    "NO_NEWS",
    "TopicBuilder",
    "clip",
]

log = logging.getLogger(__name__)

TOPICS_DIR = Path(__file__).parent / "prompts" / "topics"
BLOCK_MAX = 1500
LAST_GAME_S = 6 * 3600  # P12: último jogo fechado nas últimas 6 h
NEWS_MAX = 5
NEWS_WINDOW = timedelta(hours=24)
NEWS_SCAN = 30  # itens lidos do repo antes do filtro de 24 h
NO_GAME = "no game detected"
NO_NEWS = "no news today"
DEFAULT_ROLE = ("a general software engineering role (backend/Python, systems design, "
                "trade-offs) at mid/senior level")

LABELS: dict[Topic, str] = {
    Topic.FREE: "FREE TALK",
    Topic.INTERVIEW: "TECH INTERVIEW",
    Topic.GAME: "THE GAME I'M PLAYING",
    Topic.NEWS: "TODAY'S NEWS",
}


@cache
def _template(name: str) -> str:
    return (TOPICS_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def clip(text: str | None, limit: int = BLOCK_MAX) -> str | None:
    """Bloco limpo e cortado em ``limit`` caracteres (``None`` se vazio)."""
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ctx(topic: Topic, requested: Topic, block: str | None = None,
         detail: str | None = None) -> TopicContext:
    return TopicContext(topic=topic, requested=requested, label=LABELS[topic], block=clip(block),
                        detail=detail)


class TopicBuilder:
    """Monta o ``TopicContext`` de um tema pedido (spec §10.1 item 3).

    ``game``: ``GameWatcher`` (``running()``, ``subscribe``); ``steam``: ``SteamLocal``
    (``stats(appid, name)``); ``news``: ``NewsRepo`` (``undelivered``/``delivered_recent``).
    Qualquer um ``None`` = fonte indisponível (cai no fallback do tema).
    """

    def __init__(
        self,
        *,
        game: Any = None,
        steam: Any = None,
        news: Any = None,
        interview_role: str | None = None,
        clock: Callable[[], float] = time.time,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.game = game
        self.steam = steam
        self.news = news
        self.interview_role = (interview_role or "").strip() or None
        self.clock = clock
        self.now = now or (lambda: datetime.now(UTC))
        self._last_closed: tuple[Any, float] | None = None
        subscribe = getattr(game, "subscribe", None)
        if callable(subscribe):
            subscribe(self.on_game)

    def on_game(self, event: Any) -> None:
        """Ouvinte do ``GameWatcher``: lembra o último jogo fechado (P12)."""
        if getattr(event, "kind", None) == "closed":
            self._last_closed = (event.game, float(event.at))

    async def build(self, requested: Topic | str) -> TopicContext:
        requested = Topic(requested)
        try:
            if requested is Topic.INTERVIEW:
                return self._interview()
            if requested is Topic.GAME:
                return self._game()
            if requested is Topic.NEWS:
                return await self._news()
        except Exception:
            log.exception("learning: falha ao montar o tema %s; conversa livre", requested.value)
            detail = NO_GAME if requested is Topic.GAME else NO_NEWS if requested is Topic.NEWS else None
            return _ctx(Topic.FREE, requested, detail=detail)
        return _ctx(Topic.FREE, requested)

    # -- temas ------------------------------------------------------------------------------------

    def _interview(self) -> TopicContext:
        block = _template("interview").replace("{role}", self.interview_role or DEFAULT_ROLE)
        return _ctx(Topic.INTERVIEW, Topic.INTERVIEW, block)

    def _game(self) -> TopicContext:
        now = self.clock()
        running = self.game.running() if self.game is not None else None
        if running is not None:
            minutes = int(max(now - float(running.since), 0) // 60)
            status = f"He is playing {running.name} right now (for about {minutes} minutes this session)."
            game = running
        elif self._last_closed is not None and now - self._last_closed[1] <= LAST_GAME_S:
            game, at = self._last_closed
            ago = int(max(now - at, 0) // 60)
            status = f"No game is open now; you were playing {game.name} (closed about {ago} minutes ago)."
        else:
            return _ctx(Topic.FREE, Topic.GAME, detail=NO_GAME)
        block = _template("game").replace("{status}", status).replace("{stats}", self._stats(game))
        return _ctx(Topic.GAME, Topic.GAME, block)

    def _stats(self, game: Any) -> str:
        appid = getattr(game, "appid", None)
        if self.steam is None or not appid:
            return ""
        try:
            from magi.agent.tools.steam import describe

            st = self.steam.stats(int(appid), str(game.name))
            if st.minutes is None and not st.achievements:
                return ""
            speech, _ = describe(st, self.clock())
            return f"Steam stats (data): {speech}"
        except Exception:
            log.warning("learning: estatística da Steam indisponível", exc_info=True)
            return ""

    async def _news(self) -> TopicContext:
        if self.news is None:
            return _ctx(Topic.FREE, Topic.NEWS, detail=NO_NEWS)
        items = await self._recent_items()
        if not items:
            return _ctx(Topic.FREE, Topic.NEWS, detail=NO_NEWS)
        lines = (await self._lines(items))[:NEWS_MAX]
        if not lines:
            return _ctx(Topic.FREE, Topic.NEWS, detail=NO_NEWS)
        block = _template("news").replace("{items}", "\n".join(lines))
        return _ctx(Topic.NEWS, Topic.NEWS, block)

    async def _recent_items(self) -> list[Any]:
        """Itens das últimas 24 h (não entregues e já entregues), sem marcar nada."""
        from magi.agent.tools.news import WHATS_NEW_LEVELS

        found: list[Any] = []
        undelivered = getattr(self.news, "undelivered", None)
        if callable(undelivered):
            found += await undelivered(WHATS_NEW_LEVELS, limit=NEWS_SCAN)
        recent = getattr(self.news, "delivered_recent", None)
        if callable(recent):
            found += await recent(NEWS_SCAN)
        since = self.now() - NEWS_WINDOW
        seen: set[Any] = set()
        out: list[Any] = []
        for item in found:
            key = item.id if item.id is not None else item.title
            when = item.first_seen
            if key in seen or when is None or when < since:
                continue
            seen.add(key)
            out.append(item)
        return out

    async def _lines(self, items: Sequence[Any]) -> list[str]:
        """Título + 1 frase de cada item, já pelo filtro de spoiler do rádio."""
        from magi.news.spoiler import Display, present

        shown = await present(self.news, items, self.now())
        lines = []
        for s in shown:
            if s.mode is Display.HIDDEN:  # spoiler possível: fica fora do assunto
                continue
            title = " ".join(str(s.title).split())
            if not title:
                continue
            first = " ".join(str(s.summary).split()).split(". ")[0].strip()
            lines.append(f"- {title}" + (f": {first.rstrip('.')}." if first else ""))
        return lines
