"""Texto de uma matéria pela URL, para o "conta mais dessa" do modo rádio.

Baixa a página e junta os parágrafos do corpo: o ``<article>`` (ou ``<main>``) quando existe,
senão a página toda, sem menu, rodapé, barras laterais, scripts e formulários. Parágrafo curto
(legenda, botão, "leia também") fica de fora. Erro de rede ou página sem texto devolve ``""``.
"""

from __future__ import annotations

import logging
import re

import httpx
from selectolax.parser import HTMLParser, Node

from magi.news.sources import USER_AGENT

log = logging.getLogger(__name__)

TIMEOUT_S = 6.0
MAX_CHARS = 6000
MIN_PARAGRAPH = 60
MIN_BLOCK = 400
_NOISE = "script, style, noscript, nav, header, footer, aside, form, figure, iframe, svg, button"
_WS_RE = re.compile(r"\s+")


def article_text(html: str, limit: int = MAX_CHARS) -> str:
    """Parágrafos do corpo da matéria, até ``limit`` caracteres: do ``<article>``/``<main>`` com
    mais texto (há páginas com vários, ex.: boxes de oferta); se nenhum passa de ``MIN_BLOCK``,
    da página toda."""
    if not html:
        return ""
    tree = HTMLParser(html)
    for node in tree.css(_NOISE):
        node.decompose()
    blocks = [*tree.css("article"), *tree.css("main")]
    best = max((_paragraphs(r, limit) for r in blocks), key=len, default="")
    if len(best) >= MIN_BLOCK or tree.body is None:
        return best
    body = _paragraphs(tree.body, limit)  # página sem <article> útil: a página toda (sem o ruído)
    return body if len(body) > len(best) else best


def _paragraphs(root: Node, limit: int) -> str:
    parts: list[str] = []
    size = 0
    for p in root.css("p"):
        text = _WS_RE.sub(" ", p.text(separator=" ")).strip()
        if len(text) < MIN_PARAGRAPH:
            continue
        parts.append(text)
        size += len(text) + 1
        if size >= limit:
            break
    return "\n".join(parts)[:limit]


async def fetch_article(url: str, client: httpx.AsyncClient | None = None) -> str:
    """Texto da matéria em ``url``; ``""`` em erro."""
    try:
        if client is None:
            async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT_S) as own:
                resp = await own.get(url, headers={"User-Agent": USER_AGENT})
        else:
            resp = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001 - aprofundar é opcional
        log.warning("matéria indisponível (%s): %s", type(e).__name__, url)
        return ""
    return article_text(resp.text)
