"""Perguntas sobre novidades (6.12, R20.1-R20.3).

- Ferramenta ``news_query(topic?, days?)`` do agente: com ``topic`` ("o que saiu de novo do
  Silksong?"), busca no banco (``NewsRepo.search_items``, casamento tolerante por obra/manchete),
  filtra pelos últimos ``days`` (padrão 30) e responde com até 5 itens, maior prioridade e mais
  recentes primeiro. Sem nada guardado, cai para a pesquisa (3.8, ``SearchTool``) com fontes (R20.2).
  Sem ``topic``: as novidades ainda não vistas, como o "novidades?".
- Intent local ``news.whats_new`` ("novidades?", "tem novidade?"): modo rádio. Conta uma notícia
  por vez (bomba/alta/normal ainda não entregue), narrada em português pelo modelo da tarefa
  ``news`` (as fontes são quase todas em inglês), e pergunta "Quer ouvir outra?"; o "sim" volta
  aqui e conta a próxima. Só a notícia falada é marcada como entregue (R20.3), e a seguinte já é
  narrada em segundo plano enquanto esta toca. Sem modelo, fala a manchete.
- Intent local ``news.deeper`` ("conta mais dessa"): aprofunda a última notícia falada. O Python
  junta até 5 textos dela (páginas das fontes e o texto do feed), faz um resumo extrativo
  (``magi.news.digest``) e só esse resumo curto vai ao modelo, que narra em 5-7 frases.

Tudo o que é exibido ou falado vem de :class:`magi.news.spoiler.Shown` (via ``present``): nunca a
manchete, o resumo ou os links crus do item. A fala tem no máximo 2 frases; a lista com links vai
na legenda completa do HUD e os links como cards ``link``.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from magi.agent.tools.base import ToolArgsError, arg_int, arg_str
from magi.common.contracts import (
    ARG_DECLINED,
    ARG_QUIET,
    ActionRequest,
    ActionResult,
    CardLevel,
    CardMsg,
    ChatMessage,
    Expression,
    Intent,
    IntentId,
    NewsItem,
    NewsLevel,
    ToolSpec,
    TurnContext,
)
from magi.news.article import fetch_article
from magi.news.digest import digest
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

#: Modo rádio: quantas pendentes contar no "Tem N novidades" e o tempo máximo da narração.
RADIO_COUNT = 50
NARRATE_TIMEOUT_S = 6.0
SAY_ASK_MORE = "Quer ouvir outra?"
SAY_LAST = "Era isso por enquanto."
SAY_RADIO_DECLINED = "Beleza, depois tem mais."
ARG_NEXT = "next"
#: "Conta mais dessa": quantas fontes abrir e o mínimo de texto de uma página para não usar o feed.
DEEPER_SOURCES = 5
MIN_ARTICLE_CHARS = 400
DEEPER_TIMEOUT_S = 10.0
SAY_NO_LAST = "Ainda não te contei nenhuma notícia. Fala \"novidades\" que eu começo."
SAY_DEEPER_SPOILER = "Essa eu deixei escondida por spoiler. Se quiser, libera o spoiler dessa obra."
SAY_NO_MORE_INFO = "Não achei mais nada sobre essa além do que eu já falei."
DEEPER_PROMPT = (
    "Você é a Condessa, apresentadora de um programa de rádio de games e anime, falando com o Pedro "
    "em português do Brasil. Ele pediu para saber mais sobre a notícia abaixo. Com base só no resumo "
    "dado, conte em 5 a 7 frases curtas e naturais para falar em voz alta os detalhes que importam "
    "(o quê, quem, quando, onde, por quê). Traduza se precisar. Sem opinião, sem links, sem listas, "
    "sem markdown, sem cumprimentar e sem perguntar nada no fim."
)
#: Cumprimento que o modelo às vezes põe no começo, mesmo pedindo para não pôr.
_GREETING = re.compile(
    r"^(?:(?:olá|oi|e aí|fala|bom dia|boa tarde|boa noite|atenção)[,!]?\s*(?:pedro)?[,.!]\s*)+", re.I
)
NARRATE_PROMPT = (
    "Você é a Condessa, apresentadora de um programa de rádio de games e anime, falando com o Pedro "
    "em português do Brasil. Conte a notícia abaixo em 2 ou 3 frases curtas, naturais para falar em "
    "voz alta: traduza, diga o principal (o quê, de qual obra, quando) e nada além do que está no "
    "texto, sem opinião nem comentário seu. Sem links, sem listas, sem markdown, sem cumprimentar e "
    "sem perguntar nada no fim."
)


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
        self.chat: Any = None  # ChatProvider da tarefa ``news`` (narração do modo rádio)
        self._ahead: tuple[int, asyncio.Task[str]] | None = None  # próxima já em narração
        self.last: tuple[NewsItem, Shown] | None = None  # última notícia falada ("conta mais")

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

    async def radio(self, ctx: TurnContext, *, first: bool = True) -> ActionResult:
        """Uma notícia narrada e "Quer ouvir outra?" (o "sim" chama de novo com ``first=False``)."""
        if self.repo is None:
            return ActionResult(ok=False, speech=SAY_NO_DB)
        items = await self.repo.undelivered(WHATS_NEW_LEVELS, limit=RADIO_COUNT)
        if not items:
            return ActionResult(ok=True, speech=SAY_NOTHING if first else SAY_LAST)
        item, rest = items[0], items[1:]
        [shown] = await self._show([item])
        text = await self._narration(item, shown)
        if item.id is not None:
            await self.repo.mark_delivered(item.id, self.now())
        self.last = (item, shown)
        head = ""
        if first:
            n = len(items)
            head = "Tem uma novidade. " if n == 1 else f"Tem {n if n < RADIO_COUNT else 'várias'} novidades. "
        link = shown.links[0] if shown.links else ""
        cards = (CardMsg(level=CardLevel.LINK if link else _card_level(item), title=shown.title, url=link),)
        full = f"{shown.title}" + (f" — {link}" if link else "") + f"\n{text}"
        if not rest:
            return ActionResult(
                ok=True, speech=f"{head}{text} {SAY_LAST}", full_text=full, cards=cards, long_speech=True
            )
        self._narrate_ahead(rest[0])
        return _ask_more(ctx, f"{head}{text}", full, cards)

    async def deeper(self, ctx: TurnContext) -> ActionResult:
        """Mais detalhes da última notícia falada; no fim, volta ao rádio ("Quer ouvir outra?")."""
        if self.last is None:
            return ActionResult(ok=True, speech=SAY_NO_LAST, expression=Expression.CONFUSED)
        item, shown = self.last
        if shown.mode is not Display.ORIGINAL:
            return ActionResult(ok=True, speech=SAY_DEEPER_SPOILER)
        title = html.unescape(shown.title)
        try:
            async with asyncio.timeout(DEEPER_TIMEOUT_S):
                texts = await self._texts(item)
        except TimeoutError:
            texts = []
        summary = digest(texts, title) if texts else ""
        if not summary:
            return ActionResult(ok=True, speech=SAY_NO_MORE_INFO)
        text = await self._tell(DEEPER_PROMPT, [f"Manchete: {title}", f"Resumo: {summary}"], summary)
        full = f"{title}\n{text}"
        link = shown.links[0] if shown.links else ""
        cards = (CardMsg(level=CardLevel.LINK, title=shown.title, url=link),) if link else ()
        if self.repo is not None and await self.repo.undelivered(WHATS_NEW_LEVELS, limit=1):
            return _ask_more(ctx, text, full, cards)
        return ActionResult(ok=True, speech=text, full_text=full, cards=cards, long_speech=True)

    async def _texts(self, item: NewsItem) -> list[str]:
        """Até ``DEEPER_SOURCES`` textos da notícia: a página de cada fonte (em paralelo) ou, se a
        página não render texto (bloqueio, JavaScript), o texto do feed guardado."""
        item_sources = getattr(self.repo, "item_sources", None)
        if item.id is None or not callable(item_sources):
            return []
        sources = await item_sources(item.id, DEEPER_SOURCES)
        pages = await asyncio.gather(*(fetch_article(url) for url, _ in sources))
        texts = []
        for (_, body), page in zip(sources, pages, strict=True):
            text = page if len(page) >= MIN_ARTICLE_CHARS else html.unescape(body)
            if text.strip():
                texts.append(text)
        return texts

    async def _narration(self, item: NewsItem, shown: Shown) -> str:
        ahead, self._ahead = self._ahead, None
        if ahead is not None:
            if ahead[0] == item.id:
                try:
                    return await ahead[1]
                except Exception:  # noqa: BLE001 - narração é opcional
                    pass
            else:
                ahead[1].cancel()
        return await self._narrate(shown)

    def _narrate_ahead(self, item: NewsItem) -> None:
        if self.chat is None or item.id is None:
            return

        async def run() -> str:
            [shown] = await self._show([item])
            return await self._narrate(shown)

        self._ahead = (item.id, asyncio.create_task(run()))

    async def _narrate(self, shown: Shown) -> str:
        """Notícia contada em português (2-3 frases); sem modelo ou em erro, a manchete."""
        title, summary = html.unescape(shown.title), html.unescape(shown.summary or "")
        lines = [f"Obra: {shown.franchise}"] if shown.franchise else []
        lines.append(f"Manchete: {title}")
        if summary:
            lines.append(f"Resumo: {summary}")
        return await self._tell(NARRATE_PROMPT, lines, title)

    async def _tell(self, prompt: str, lines: Sequence[str], fallback: str) -> str:
        """Texto para falar, escrito pelo modelo da tarefa ``news``; sem modelo ou em erro,
        ``fallback`` (manchete ou resumo extrativo)."""
        fallback = _sentence(fallback)
        if self.chat is None:
            return fallback
        messages = [
            ChatMessage(role="system", content=prompt),
            ChatMessage(role="user", content="\n".join(lines)),
        ]
        try:
            async with asyncio.timeout(NARRATE_TIMEOUT_S):
                reply = await self.chat.chat(messages, personal=False)
        except Exception as e:  # noqa: BLE001
            log.warning("novidades: narração indisponível (%s); falando o texto pronto", type(e).__name__)
            return fallback
        text = _GREETING.sub("", " ".join((reply.text or "").split()))
        return _sentence(text[:1].upper() + text[1:]) if text else fallback

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


def _ask_more(ctx: TurnContext, text: str, full: str, cards: tuple[CardMsg, ...]) -> ActionResult:
    """Fala ``text`` e pergunta "Quer ouvir outra?"; o "sim" conta a próxima do rádio."""
    again = ActionRequest(
        intent=Intent(id=IntentId.NEWS_WHATS_NEW.value),
        ctx=ctx,
        confirmed=True,
        args={ARG_NEXT: True, ARG_DECLINED: SAY_RADIO_DECLINED, ARG_QUIET: True},
    )
    return ActionResult(
        ok=True,
        speech=f"{text} {SAY_ASK_MORE}",
        full_text=full,
        cards=cards,
        needs_confirmation=True,
        on_confirm=again,
        long_speech=True,
    )


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
    """``news.whats_new`` ("novidades?") para o ``Registry``: modo rádio (``NewsQuery.radio``)."""

    intents = frozenset({IntentId.NEWS_WHATS_NEW.value, IntentId.NEWS_DEEPER.value})

    def __init__(self, query: NewsQuery | None = None) -> None:
        self.query = query or NewsQuery()

    async def run(self, req: ActionRequest) -> ActionResult:
        if req.intent.id == IntentId.NEWS_DEEPER.value:
            return await self.query.deeper(req.ctx)
        return await self.query.radio(req.ctx, first=not req.args.get(ARG_NEXT))


def news_tools(query: NewsQuery) -> list[NewsQueryTool]:
    """``[NewsQueryTool]`` se houver banco de notícias; sem banco, a ficha mostra o limite."""
    return [NewsQueryTool(query)] if query.repo is not None else []
