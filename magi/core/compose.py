"""Resposta curta e completa (3.6, R12.3, §6).

Ponto único que transforma uma resposta em fala + HUD:

- a fala tem no máximo 2 frases, cortadas em fim de frase (nunca no meio), sem markdown, emojis,
  URLs nem itens de lista: URL nunca é lida em voz alta;
- a resposta completa vai como ``subtitle`` (``SubtitleMsg.full``);
- links (``[título](url)`` ou URL solta) e itens de lista viram ``card``\\s, sem repetição, até 5.

Usado pelo agente (``magi.agent.graph``), pelas ferramentas que resumem texto longo e pelo
núcleo antes de falar (``TurnMachine._deliver`` e ``announce``), então ações locais e avisos
proativos passam pelas mesmas regras.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from magi.common.contracts import ActionResult, CardLevel, CardMsg, SubtitleMsg

SPEECH_MAX_SENTENCES = 2
MAX_CARDS = 5
CARD_TITLE_MAX = 80
SAY_SEE_HUD = "Deixei na tela."

_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]*[^\s<>\"')\].,;:!?]")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+(.*\S)\s*$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*")
_QUOTE = re.compile(r"^\s*>+\s?")
_RULE = re.compile(r"^\s*(?:[-*_]\s*){3,}$")
_FENCE = re.compile(r"```.*?(?:```|$)", re.DOTALL)
_EMPHASIS = re.compile(r"(\*\*|__|\*|~~|`)(?=\S)(.+?)(?<=\S)\1")
_UNDERSCORE = re.compile(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)")
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff\U00002b00-\U00002bff"
    "\ufe0f\u200d\u20e3]+"
)
_DANGLING = re.compile(r"\s+([,.;:!?…])")
_EMPTY_PARENS = re.compile(r"\(\s*\)|\[\s*\]")
# Fim de frase: pontuação seguida de espaço; abreviações comuns não cortam.
_SENTENCE_END = re.compile(r"(?<=[.!?…])[\"')\]»]*\s+")
_ABBREV = re.compile(r"(?:^|\s)(?:sr|sra|srta|dr|dra|prof|ex|etc|vs|obs|pág|núm|nº|av|p\.ex|aprox)\.$", re.I)


def _strip_inline(text: str) -> str:
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _EMPHASIS.sub(r"\2", text)
    text = _UNDERSCORE.sub(r"\1", text)
    text = _EMOJI.sub("", text)
    text = _EMPTY_PARENS.sub("", text)
    return text


def plain(text: str) -> str:
    """Texto sem markdown, emojis e URLs, mantendo linhas e listas (para a legenda)."""
    lines = []
    for line in _FENCE.sub("", text).splitlines():
        if _RULE.match(line):
            continue
        line = _QUOTE.sub("", _HEADING.sub("", line))
        if m := _LIST_ITEM.match(line):
            line = "- " + _strip_inline(m.group(1)).strip()
        else:
            line = _strip_inline(line)
        # URL removida no fim da linha deixa separadores soltos ("- Wiki — <url>").
        lines.append(_DANGLING.sub(r"\1", " ".join(line.split())).rstrip(" —–·|"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def clean_speech(text: str) -> str:
    """Texto para falar: sem markdown, emojis, URLs e itens de lista, numa linha só."""
    kept = []
    for line in _FENCE.sub("", text).splitlines():
        if _LIST_ITEM.match(line) or _RULE.match(line):
            continue
        line = _strip_inline(_QUOTE.sub("", _HEADING.sub("", line))).strip()
        if line:
            kept.append(line)
    # Linha solta sem pontuação (ex.: título) vira frase própria, sem grudar na próxima.
    kept = [k if k[-1] in ".!?…:;," or i == len(kept) - 1 else k + "." for i, k in enumerate(kept)]
    out = " ".join(" ".join(kept).split())
    out = _DANGLING.sub(r"\1", out)
    return out[:-1] + "." if out.endswith(":") else out


def sentences(text: str) -> list[str]:
    """Frases de ``text`` (já numa linha), sem cortar em abreviações como "Sr."."""
    out: list[str] = []
    start = 0
    for m in _SENTENCE_END.finditer(text):
        piece = text[start : m.start()].strip()
        if _ABBREV.search(piece):
            continue
        if piece:
            out.append(text[start : m.end()].strip())
        start = m.end()
    if rest := text[start:].strip():
        out.append(rest)
    return out


def short_speech(text: str, max_sentences: int = SPEECH_MAX_SENTENCES) -> str:
    """Fala curta (R12.3): texto limpo, no máximo ``max_sentences`` frases inteiras."""
    return " ".join(sentences(clean_speech(text))[:max_sentences])


def _card_key(card: CardMsg) -> str:
    return card.url.rstrip("/").lower() if card.url else " ".join(card.title.lower().split())


def _title(text: str) -> str:
    text = " ".join(text.split()).strip(" -:·")
    return text if len(text) <= CARD_TITLE_MAX else text[: CARD_TITLE_MAX - 1].rstrip() + "…"


def _host(url: str) -> str:
    host = urlsplit(url).hostname or url
    return host.removeprefix("www.")


def extract_cards(text: str) -> list[CardMsg]:
    """Cards dos links e itens de lista de ``text`` (na ordem em que aparecem)."""
    cards: list[CardMsg] = []
    for line in _FENCE.sub("", text).splitlines():
        item = _LIST_ITEM.match(line)
        links = [(t, u) for t, u in _MD_LINK.findall(line)]
        rest = _MD_LINK.sub("", line)
        links += [("", u) for u in _URL.findall(rest)]
        if item and not links:
            if title := _title(plain(item.group(1))):
                cards.append(CardMsg(CardLevel.NORMAL, title))
            continue
        for title, url in links:
            if url.startswith("www."):
                url = "https://" + url
            label = title or (plain(item.group(1)) if item else "") or _host(url)
            cards.append(CardMsg(CardLevel.LINK, _title(plain(label)) or url, url))
    return cards


def merge_cards(*groups: Iterable[CardMsg], limit: int = MAX_CARDS) -> tuple[CardMsg, ...]:
    """Junta cards sem repetir (mesma URL, ou mesmo título sem URL), até ``limit``."""
    seen: set[str] = set()
    out: list[CardMsg] = []
    for card in (c for g in groups for c in g):
        key = _card_key(card)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(card)
        if len(out) >= limit:
            break
    return tuple(out)


def compose(result: ActionResult) -> ActionResult:
    """Aplica as regras de fala curta/legenda completa/cards a um ``ActionResult``.

    Idempotente. ``speech`` vazia continua vazia (não falar). Se a fala original só tinha
    URL/lista, a fala vira "Deixei na tela." e o conteúdo vai para a legenda e os cards.
    """
    original = result.speech or ""
    speech = short_speech(original) if original else ""
    full = result.full_text
    if full is None and original and " ".join(original.split()) != speech:
        full = original
    if original and not speech:
        speech = SAY_SEE_HUD
    cards = merge_cards(result.cards, extract_cards(full or ""), extract_cards(original))
    if (speech, full, cards) == (result.speech, result.full_text, result.cards):
        return result
    return dataclasses.replace(result, speech=speech, full_text=full, cards=cards)


def subtitle(result: ActionResult) -> SubtitleMsg | None:
    """Legenda do HUD: fala curta em ``text`` e a resposta completa (sem markdown) em ``full``."""
    if not (result.speech or result.full_text):
        return None
    full = plain(result.full_text) if result.full_text else None
    return SubtitleMsg(result.speech, full or None)
