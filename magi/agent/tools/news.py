"""Perguntas sobre novidades (6.12, R20.1-R20.3).

- Ferramenta ``news_query(topic?, days?)`` do agente: com ``topic`` ("o que saiu de novo do
  Silksong?"), busca no banco (``NewsRepo.search_items``, casamento tolerante por obra/manchete),
  filtra pelos últimos ``days`` (padrão 30) e responde com até 5 itens, maior prioridade e mais
  recentes primeiro. Sem nada guardado, cai para a pesquisa (3.8, ``SearchTool``) com fontes (R20.2).
  Sem ``topic``: as novidades ainda não vistas, como o "novidades?".
- Intent local ``news.whats_new`` ("novidades?", "tem novidade?"): resposta rápida sem LLM com os
  itens de nível bomba/alta/normal ainda não entregues (no máximo 5), marcados como entregues (R20.3).

Tudo o que é exibido ou falado vem de :class:`magi.news.spoiler.Shown` (via ``present``): nunca a
manchete, o resumo ou os links crus do item. A fala tem no máximo 2 frases; a lista com links vai
na legenda completa do HUD e os links como cards ``link``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from magi.agent.tools.base import ToolArgsError, arg_int, arg_str
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    CardLevel,
    CardMsg,
    Expression,
    IntentId,
    NewsItem,
    NewsLevel,
    ToolSpec,
    TurnContext,
)
from magi.news.spoiler import Display, Shown, norm, present

log = logging.getLogger(__name__)

MAX_ITEMS = 5
DEFAULT_DAYS = 30
MAX_DAYS = 365
#: Candidatos pedidos ao banco antes do filtro de data.
FETCH = 30
WHATS_NEW_LEVELS = (NewsLevel.BOMBA, NewsLevel.ALTA, NewsLevel.NORMAL)

NEWS_SPEC = ToolSpec(
    name="news_query",
    description=(
        "Novidades guardadas de jogos e anime (notícias já coletadas, com anti-spoiler). Use para "
        "'o que saiu de novo de X?', 'novidades de X', 'tem novidade?'. topic: nome da obra/franquia "
        "(vazio = novidades gerais ainda não vistas). days: janela em dias (padrão 30). Se não houver "
        "nada guardado, a própria ferramenta pesquisa na internet."
    ),
    parameters={
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Obra ou franquia; vazio = geral"},
            "days": {"type": "integer", "description": "Últimos N dias (padrão 30)"},
        },
    },
)

SAY_NO_DB = "Sem o banco de notícias, não tenho novidades guardadas."
SAY_NOTHING = "Nada de novo por enquanto."
SAY_NOTHING_TOPIC = "Não tenho nada guardado sobre {topic}."
SEARCH_QUESTION = "Quais as novidades mais recentes sobre {topic}?"


def topic_matches(item: NewsItem, topic: str) -> bool:
    """Casamento tolerante: toda palavra de ``norm(topic)`` aparece inteira na obra ou na manchete
    normalizadas (mesma regra do ``PgNewsRepo.search_items``)."""
    words = norm(topic).split()
    hay = f" {norm(f'{item.franchise or ""} {item.title}')} "
    return bool(words) and all(f" {w} " in hay for w in words)


def _rank(items: Sequence[NewsItem]) -> list[NewsItem]:
    """Maior prioridade, depois mais recente."""
    oldest = datetime.min.replace(tzinfo=UTC)

    def key(i: NewsItem) -> tuple[float, datetime]:
        seen = i.first_seen or oldest
        return (i.priority if i.priority is not None else -1.0,
                seen if seen.tzinfo else seen.replace(tzinfo=UTC))

    return sorted(items, key=key, reverse=True)


def _card_level(item: NewsItem) -> CardLevel:
    try:
        return CardLevel(item.level.value) if item.level is not None else CardLevel.NORMAL
    except ValueError:
        return CardLevel.NORMAL


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?", "…")) else f"{text}."


def render(shown: Sequence[Shown], items: Sequence[NewsItem], topic: str = "") -> ActionResult:
    """Fala curta (≤ 2 frases) + lista com links (legenda) + cards. Só usa ``Shown``."""
    n = len(shown)
    about = f" de {topic}" if topic else ""
    head = f"Tem uma novidade{about}" if n == 1 else f"Tem {n} novidades{about}"
    lead = shown[0].title
    speech = f"{head}: {_sentence(lead)}" if n == 1 else f"{head}. A principal: {_sentence(lead)}"
    lines: list[str] = []
    cards: list[CardMsg] = []
    for s, item in zip(shown, items, strict=True):
        link = s.links[0] if s.links else ""
        lines.append(f"- {s.title}" + (f" — {link}" if link else ""))
        if s.summary and s.mode is Display.ORIGINAL:
            lines.append(f"  {s.summary}")
        cards.append(CardMsg(level=CardLevel.LINK if link else _card_level(item), title=s.title, url=link))
    full = f"{head}:\n" + "\n".join(lines)
    return ActionResult(ok=True, speech=speech, full_text=full, cards=tuple(cards))


class NewsQuery:
    """Consulta comum à ferramenta e ao intent local. ``repo``: ``NewsRepo`` (``None`` = sem banco);
    ``search``: ``SearchTool`` (3.8) para o fallback; ``now``: relógio (testes)."""

    def __init__(
        self,
        repo: Any = None,
        search: Any = None,
        *,
        now: Callable[[], datetime] | None = None,
        store: Any = None,
    ) -> None:
        self.repo = repo
        self.search = search
        self.now = now or (lambda: datetime.now(UTC))
        self.store = store

    async def _show(self, items: Sequence[NewsItem]) -> list[Shown]:
        ids = [i.id for i in items if i.id is not None]
        links: dict[int, Sequence[str]] = {}
        item_links = getattr(self.repo, "item_links", None)
        if ids and callable(item_links):
            try:
                links = dict(await item_links(ids))
            except Exception as e:
                log.warning("novidades: links indisponíveis: %s", e)
        return await present(self.repo, items, self.now(), links=links, store=self.store)

    async def whats_new(self, limit: int = MAX_ITEMS, *, mark: bool = True) -> ActionResult:
        """Itens bomba/alta/normal ainda não entregues (R20.3); marca como entregues."""
        if self.repo is None:
            return ActionResult(ok=False, speech=SAY_NO_DB)
        items = (await self.repo.undelivered(WHATS_NEW_LEVELS, limit=min(limit, MAX_ITEMS)))[:MAX_ITEMS]
        if not items:
            return ActionResult(ok=True, speech=SAY_NOTHING)
        shown = await self._show(items)
        if mark:
            at = self.now()
            for i in items:
                if i.id is not None:
                    await self.repo.mark_delivered(i.id, at)
        return render(shown, items)

    async def about(self, topic: str, days: int, ctx: TurnContext) -> ActionResult:
        """Novidades de uma obra (R20.1); sem nada guardado, pesquisa (R20.2)."""
        items: list[NewsItem] = []
        if self.repo is not None:
            try:
                found = await self.repo.search_items(franchise=topic, limit=FETCH)
            except Exception as e:
                log.warning("novidades: busca no banco falhou: %s", e)
                found = []
            since = self.now() - timedelta(days=days)
            items = [
                i for i in found
                if topic_matches(i, topic) and (i.first_seen is None or _aware(i.first_seen) >= since)
            ]
        items = _rank(items)[:MAX_ITEMS]
        if items:
            return render(await self._show(items), items, topic)
        if self.search is not None:
            return await self.search.run({"question": SEARCH_QUESTION.format(topic=topic)}, ctx)
        if self.repo is None:
            return ActionResult(ok=False, speech=SAY_NO_DB)
        say = SAY_NOTHING_TOPIC.format(topic=topic)
        return ActionResult(ok=True, speech=say, expression=Expression.CONFUSED)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class NewsQueryTool:
    """Ferramenta ``news_query(topic?, days?)`` do agente."""

    spec = NEWS_SPEC
    danger = False

    def __init__(self, query: NewsQuery) -> None:
        self.query = query

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        topic = arg_str(args, "topic")
        try:
            days = arg_int(args, "days")
        except ToolArgsError as e:
            return ActionResult(ok=False, speech=str(e), expression=Expression.CONFUSED)
        days = DEFAULT_DAYS if days is None or days <= 0 else min(days, MAX_DAYS)
        if not topic:
            return await self.query.whats_new()
        return await self.query.about(topic, days, ctx)


class WhatsNewHandler:
    """``news.whats_new`` ("novidades?") para o ``Registry``: resposta local, sem LLM."""

    intents = frozenset({IntentId.NEWS_WHATS_NEW.value})

    def __init__(self, query: NewsQuery | None = None) -> None:
        self.query = query or NewsQuery()

    async def run(self, req: ActionRequest) -> ActionResult:
        return await self.query.whats_new()


def news_tools(query: NewsQuery) -> list[NewsQueryTool]:
    """``[NewsQueryTool]`` se houver banco de notícias; sem banco, a ficha mostra o limite."""
    return [NewsQueryTool(query)] if query.repo is not None else []
