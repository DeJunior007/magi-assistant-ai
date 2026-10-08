"""Explain (EXP-001; spec §5): explica o trecho no contexto; ``answer`` de 1 a 4 frases,
≤ 400 caracteres (cortado)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from magi.learning.analyzers import Analyzer, clip, ensure_available, require_str
from magi.learning.contracts import ActionKind, ActionRequest

ANSWER_MAX = 400
ANSWER_MAX_SENTENCES = 4
QUESTION_MAX = 160

SCHEMA: dict = {
    "title": "explain",
    "type": "object",
    "properties": {
        "question": {"type": "string", "maxLength": QUESTION_MAX},
        "answer": {"type": "string", "maxLength": ANSWER_MAX},
    },
    "required": ["question", "answer"],
    "additionalProperties": False,
}

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(" ".join(text.split())) if s]


def prepare(request: ActionRequest) -> dict[str, str]:
    ensure_available(request)
    return {}


def validate(raw: Mapping[str, Any], request: ActionRequest) -> dict:
    question = clip(require_str(raw, "question", "explain"), QUESTION_MAX)
    answer = " ".join(sentences(require_str(raw, "answer", "explain"))[:ANSWER_MAX_SENTENCES])
    return {"question": question, "answer": clip(answer, ANSWER_MAX)}


ANALYZER = Analyzer(ActionKind.EXPLAIN, SCHEMA, validate, prepare)
