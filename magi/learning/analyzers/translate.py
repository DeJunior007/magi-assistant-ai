"""Translate (TRA-001; spec §5): traduz o trecho para ``translate_to`` (PT-BR; texto já em
português vai para o inglês). ``note`` só para trecho ≤ 3 palavras, ≤ 100 caracteres; para frase,
``note = null``. Trecho até 400 caracteres."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from magi.learning.analyzers import (
    TRANSLATE_NOTE_MAX_WORDS,
    Analyzer,
    clip,
    ensure_available,
    optional_str,
    require_str,
    word_count,
)
from magi.learning.contracts import ActionKind, ActionRequest

NOTE_MAX = 100

SCHEMA: dict = {
    "title": "translate",
    "type": "object",
    "properties": {
        "translation": {"type": "string"},
        "note": {"type": ["string", "null"], "maxLength": NOTE_MAX},
    },
    "required": ["translation", "note"],
    "additionalProperties": False,
}


def prepare(request: ActionRequest) -> dict[str, str]:
    ensure_available(request)
    return {}


def validate(raw: Mapping[str, Any], request: ActionRequest) -> dict:
    translation = require_str(raw, "translation", "translate")
    note = optional_str(raw, "note", "translate")
    if note is not None:
        note = (
            clip(note, NOTE_MAX) if word_count(request.selection.text) <= TRANSLATE_NOTE_MAX_WORDS else None
        )
    return {"translation": translation, "note": note}


ANALYZER = Analyzer(ActionKind.TRANSLATE, SCHEMA, validate, prepare)
