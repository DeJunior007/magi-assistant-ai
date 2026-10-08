"""Vocabulary (VOC-001, VOC-002; spec §5): ficha do termo selecionado (1 a 4 palavras).

``term``, ``meaning``, ``in_context``, ``pos``, ``cefr``, ``examples`` (1–3), ``synonyms`` (0–4).
``pos``/``cefr`` podem vir ``null``; CEFR fora de A1..C2 vira ``null``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from magi.learning.analyzers import (
    Analyzer,
    clip,
    ensure_available,
    optional_str,
    require_str,
    str_list,
)
from magi.learning.contracts import ActionKind, ActionRequest
from magi.learning.model import ModelInvalid

CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
EXAMPLES_MAX = 3
SYNONYMS_MAX = 4
MEANING_MAX = 200
IN_CONTEXT_MAX = 200
EXAMPLE_MAX = 160
TERM_MAX = 60
POS_MAX = 24
SYNONYM_MAX = 40

SCHEMA: dict = {
    "title": "vocabulary",
    "type": "object",
    "properties": {
        "term": {"type": "string"},
        "meaning": {"type": "string", "maxLength": MEANING_MAX},
        "in_context": {"type": "string", "maxLength": IN_CONTEXT_MAX},
        "pos": {"type": ["string", "null"]},
        "cefr": {"type": ["string", "null"], "enum": [*CEFR_LEVELS, None]},
        "examples": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": EXAMPLES_MAX},
        "synonyms": {"type": "array", "items": {"type": "string"}, "maxItems": SYNONYMS_MAX},
    },
    "required": ["term", "meaning", "in_context", "pos", "cefr", "examples", "synonyms"],
    "additionalProperties": False,
}


def prepare(request: ActionRequest) -> dict[str, str]:
    ensure_available(request)
    return {}


def validate(raw: Mapping[str, Any], request: ActionRequest) -> dict:
    term = clip(require_str(raw, "term", "vocabulary"), TERM_MAX)
    meaning = clip(require_str(raw, "meaning", "vocabulary"), MEANING_MAX)
    in_context = clip(require_str(raw, "in_context", "vocabulary"), IN_CONTEXT_MAX)
    pos = optional_str(raw, "pos", "vocabulary")
    cefr = optional_str(raw, "cefr", "vocabulary")
    cefr = cefr.upper() if cefr and cefr.upper() in CEFR_LEVELS else None
    examples = str_list(raw, "examples", "vocabulary", required=True)
    if not examples:
        raise ModelInvalid("vocabulary: 'examples' precisa de ao menos 1 frase")
    synonyms = str_list(raw, "synonyms", "vocabulary", required=False)
    seen: set[str] = set()
    uniq = [s for s in synonyms if not (s.lower() in seen or seen.add(s.lower()))]
    return {
        "term": term,
        "meaning": meaning,
        "in_context": in_context,
        "pos": clip(pos.lower(), POS_MAX) if pos else None,
        "cefr": cefr,
        "examples": [clip(e, EXAMPLE_MAX) for e in examples[:EXAMPLES_MAX]],
        "synonyms": [clip(s, SYNONYM_MAX) for s in uniq[:SYNONYMS_MAX]],
    }


ANALYZER = Analyzer(ActionKind.VOCABULARY, SCHEMA, validate, prepare)
