"""Improve (IMP-001..003; spec §5): reescreve a frase do Pedro mais natural/correta.

Contexto = a frase inteira que contém a seleção (``<sentence>``). ``original`` é sempre essa frase
(o balão mostra o que o Pedro disse, não a versão do modelo). ``kind = none`` ⇒
``improved == original``; ``why`` ≤ 240 caracteres (cortado).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from magi.learning.analyzers import Analyzer, clip, ensure_available, require_str, sentence_around
from magi.learning.contracts import ActionKind, ActionRequest
from magi.learning.model import ModelInvalid

KINDS = ("grammar", "naturalness", "both", "none")
WHY_MAX = 240

SCHEMA: dict = {
    "title": "improve",
    "type": "object",
    "properties": {
        "original": {"type": "string"},
        "improved": {"type": "string"},
        "kind": {"type": "string", "enum": list(KINDS)},
        "why": {"type": "string", "maxLength": WHY_MAX},
    },
    "required": ["original", "improved", "kind", "why"],
    "additionalProperties": False,
}


def sentence_of(request: ActionRequest) -> str:
    msg = ensure_available(request)
    sel = request.selection
    return sentence_around(msg.text, sel.start, sel.end)


def prepare(request: ActionRequest) -> dict[str, str]:
    return {"sentence": sentence_of(request)}


def validate(raw: Mapping[str, Any], request: ActionRequest) -> dict:
    require_str(raw, "original", "improve")
    improved = require_str(raw, "improved", "improve")
    kind = require_str(raw, "kind", "improve").lower()
    if kind not in KINDS:
        raise ModelInvalid(f"improve: kind fora do enum: {kind!r}")
    why = clip(require_str(raw, "why", "improve"), WHY_MAX)
    original = sentence_of(request)
    if kind == "none" or improved == original:
        kind, improved = "none", original
    return {"original": original, "improved": improved, "kind": kind, "why": why}


ANALYZER = Analyzer(ActionKind.IMPROVE, SCHEMA, validate, prepare)
