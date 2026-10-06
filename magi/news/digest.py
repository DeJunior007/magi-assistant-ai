"""Resumo extrativo, sem LLM, de vários textos sobre a mesma notícia ("conta mais dessa").

O modelo só narra o resultado, então o que vai para ele é curto (``MAX_CHARS``) em vez das
matérias inteiras. Passos:

1. separa os textos em frases (descarta as curtas demais e as que parecem menu/legenda/chamada);
2. dá nota a cada frase pela frequência das palavras de conteúdo no conjunto (palavra que várias
   fontes repetem é o assunto) mais um bônus pelas palavras da manchete; frase do começo de um
   texto ganha um pouco (o lide costuma estar lá);
3. escolhe as melhores sem repetir a mesma informação (frase muito parecida com uma já escolhida,
   por Jaccard das palavras, é pulada) até ``MAX_SENTENCES`` ou ``MAX_CHARS``;
4. devolve na ordem em que apareceram, primeiro texto antes.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

MAX_SENTENCES = 8
MAX_CHARS = 1200
MIN_WORDS, MAX_WORDS = 6, 60
SIMILAR = 0.5
TITLE_BONUS = 1.5
LEAD_BONUS = 0.3

_SENT_RE = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ú0-9\"“'(])")
_WORD_RE = re.compile(r"[a-z0-9]+")
_JUNK_RE = re.compile(
    r"(leia (tamb[eé]m|mais)|read more|click here|clique aqui|newsletter|inscreva|subscribe|"
    r"cookies|publicidade|advertisement|compartilh|share this|siga( o| a)? |follow us)",
    re.I,
)
STOPWORDS = frozenset(
    """
    a o as os um uma uns umas de da do das dos em na no nas nos por pela pelo pelas pelos para pra
    com sem sobre entre ate apos e ou mas que se ja nao sim mais menos muito muita muitos muitas
    ser foi era sao esta estao tem ter tinha teve vai vao sera seu sua seus suas ele ela eles elas
    isso isto esse essa este esta aquele aquela como quando onde qual quais tambem ainda so pois
    the a an of to in on at for with by from and or but is are was were be been being it its this
    that these those as has have had will would can could not no new also about after into than
    """.split()
)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(_fold(text)) if w not in STOPWORDS and len(w) > 2]


def sentences(text: str) -> list[str]:
    """Frases úteis de um texto (parágrafos separados por linha também quebram)."""
    out: list[str] = []
    for para in text.splitlines():
        for s in _SENT_RE.split(para.strip()):
            s = " ".join(s.split())
            n = len(s.split())
            if MIN_WORDS <= n <= MAX_WORDS and not _JUNK_RE.search(s):
                out.append(s)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def digest(texts: Sequence[str], title: str = "", *, max_sentences: int = MAX_SENTENCES,
           max_chars: int = MAX_CHARS) -> str:
    """As frases mais informativas de ``texts`` sobre a notícia ``title``, sem repetição."""
    cands: list[tuple[int, int, str, list[str]]] = []  # (texto, posição, frase, palavras)
    for t, text in enumerate(texts):
        for i, s in enumerate(sentences(text)):
            if words := _words(s):
                cands.append((t, i, s, words))
    if not cands:
        return ""
    freq = Counter(w for *_, words in cands for w in set(words))
    top = max(freq.values())
    title_words = set(_words(title))

    def score(c: tuple[int, int, str, list[str]]) -> float:
        _, i, _, words = c
        base = sum(freq[w] / top for w in set(words)) / len(set(words)) ** 0.5
        bonus = TITLE_BONUS * len(title_words & set(words)) / max(len(title_words), 1)
        return base + bonus + (LEAD_BONUS if i < 2 else 0.0)

    picked: list[tuple[int, int, str, set[str]]] = []
    size = 0
    for t, i, s, words in sorted(cands, key=score, reverse=True):
        bag = set(words)
        if any(_jaccard(bag, other) >= SIMILAR for *_, other in picked):
            continue
        if size + len(s) > max_chars and picked:
            continue
        picked.append((t, i, s, bag))
        size += len(s) + 1
        if len(picked) >= max_sentences:
            break
    picked.sort(key=lambda p: (p[0], p[1]))
    return " ".join(s for _, _, s, _ in picked)
