"""Filtro de referências forçadas (Conselho da Condessa, ata 2026-10-07-referencias).

A regra das referências mora na persona falada; isto é a rede de segurança para o tique antigo de
colar "NERV"/"EVA" no fim de qualquer resposta ("bug de NERV", "lenda nível EVA").

- ``TERMS``: vocabulário do Evangelion/HUD (palavra inteira, sem caixa). A Ayanami não entra.
- ``PATTERN``: o molde "<clima|nível|bug|...> de NERV/EVA/MAGI".
- **Liberação:** termo que aparece no contexto (fala do Pedro, 2 últimas trocas, jogo aberto,
  memórias) não é filtrado — aí a conversa é sobre Evangelion.
- **Corte:** com 2+ frases e o termo só na última, tira a última; com 1 frase e o termo depois
  da última vírgula/travessão/ponto e vírgula, tira esse trecho. Outro caso: passa e só loga.
  Nunca regera.
- **Streaming:** ``spoken_sentence`` decide frase a frase antes do áudio (a 1ª frase só perde a
  cauda; as seguintes que só existem pelo termo não são faladas).
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar

log = logging.getLogger(__name__)

TERMS = re.compile(
    r"(?<!\w)(nerv|eva|evangelion|magi|melchior|balthasar|casper|anjos?|angels?|seele|lcl|"
    r"instrumentalidade|terceiro impacto|shinji|misato|gendo)(?!\w)",
    re.IGNORECASE,
)
PATTERN = re.compile(
    r"(?<!\w)(clima|n[ií]vel|bug|drama|vibe|modo|pulso|sincronia)\s+(?:(?:de|da|do)\s+)?(nerv|eva|magi)(?!\w)",
    re.IGNORECASE,
)
_TAIL = re.compile(r"^(.*)[,;—–]\s*([^,;—–]*)$", re.S)
_SENT = re.compile(r"(?<=[.!?…])\s+")

#: Contexto do turno (texto do Pedro, últimas trocas, jogo, memórias): o que libera os termos.
REF_CONTEXT: ContextVar[str] = ContextVar("magi_ref_context", default="")


def _terms(text: str) -> set[str]:
    return {m.group(1).lower() for m in TERMS.finditer(text)} | {
        m.group(2).lower() for m in PATTERN.finditer(text)
    }


def forced(sentence: str, context: str) -> set[str]:
    """Termos proibidos em ``sentence`` que não vieram do ``context``."""
    allowed = _terms(context)
    return {t for t in _terms(sentence) if t not in allowed}


def _cut_tail(sentence: str, context: str) -> str | None:
    """Tira a cauda depois da última vírgula/travessão se só ela tem o termo; None se não der."""
    m = _TAIL.match(sentence.strip())
    if not m or not forced(m.group(2), context) or forced(m.group(1), context):
        return None
    head = m.group(1).rstrip(" ,;—–")
    return head + "." if head and head[-1] not in ".!?…" else head


def clean(text: str, context: str = "") -> str:
    """Resposta final sem a referência forçada (regras do corte acima)."""
    if not text or not forced(text, context):
        return text
    sentences = [s for s in _SENT.split(text.strip()) if s]
    only_last = forced(sentences[-1], context) and not forced(" ".join(sentences[:-1]), context)
    if len(sentences) >= 2 and only_last:
        log.info("referência cortada (frase final): %s", sentences[-1])
        return " ".join(sentences[:-1])
    if len(sentences) == 1 and (cut := _cut_tail(sentences[0], context)):
        log.info("referência cortada (cauda): %s", sentences[0])
        return cut
    log.info("referência forçada no meio da frase (passou): %s", text[:160])
    return text


def spoken_sentence(sentence: str, index: int, context: str = "") -> str | None:
    """Frase do streaming antes do áudio: a mesma, a 1ª sem a cauda, ou None (não falar)."""
    if not forced(sentence, context):
        return sentence
    if index == 0:
        cut = _cut_tail(sentence, context)
        if cut:
            log.info("referência cortada (cauda, streaming): %s", sentence)
            return cut
        log.info("referência forçada no meio da frase (passou): %s", sentence[:160])
        return sentence
    log.info("referência cortada (frase, streaming): %s", sentence)
    return None
