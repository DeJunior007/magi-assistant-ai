"""Observação em background (tarefa LM4.1; spec §9, design §6, CNV-003, OBS-002, MEM-002).

Uma chamada por mensagem do Pedro, com a mensagem + até 2 anteriores de contexto (como dado, em
``<conversation>``), devolvendo ``{"items": [...]}`` com 0 a ``MAX_ITEMS`` observações de
``vocabulary`` ou ``grammar``. Mensagens da Condessa não geram observação.

- **Parser tolerante:** raiz que não é objeto ou ``items`` que não é lista → ``ModelInvalid`` (o
  engine tenta de novo uma vez). Item malformado (categoria fora do enum, ``rule_key`` inválido,
  ``label`` vazio) é **descartado**, não derruba o lote. Textos longos são cortados.
- **``recurring`` é derivado aqui, não vem do modelo** (``derive_recurring``): quando um
  ``rule_key`` de ``grammar`` aparece pela 2ª vez na sessão, cria-se uma observação ``recurring``
  com o ``label`` da família (``grammar.prepositions.at_on`` → família ``grammar.prepositions``,
  rótulo "Prepositions"), uma vez por família na sessão.
- ``distinct_count``: o ``count`` do ``lm_obs`` = itens distintos por (``category``, ``label``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from magi.learning.analyzers import PromptOptions, clip, load_prompt, neutralize
from magi.learning.contracts import Author, LearningMessage, ObsCategory, Observation
from magi.learning.model import LearningModel, ModelInvalid

KIND = "observe"
#: Observações por mensagem (spec §9 item 3).
MAX_ITEMS = 3
#: Mensagens anteriores de contexto (design §6).
CONTEXT_BEFORE = 2
#: Cortes dos campos (o drawer da UI é estreito).
LABEL_MAX = 40
SPAN_MAX = 120
SUGGESTION_MAX = 160
RULE_KEY_MAX = 80
#: Categorias que o modelo pode devolver (``recurring`` é só derivado).
MODEL_CATEGORIES = (ObsCategory.VOCABULARY.value, ObsCategory.GRAMMAR.value)
#: Ocorrência do mesmo ``rule_key`` de grammar que vira ``recurring`` (spec §9 item 4).
RECURRING_AT = 2

_RULE_KEY_RE = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")

SCHEMA: dict = {
    "title": KIND,
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "maxItems": MAX_ITEMS,
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(MODEL_CATEGORIES)},
                    "rule_key": {"type": "string"},
                    "label": {"type": "string", "maxLength": LABEL_MAX},
                    "span": {"type": ["string", "null"]},
                    "suggestion": {"type": ["string", "null"]},
                },
                "required": ["category", "rule_key", "label", "span", "suggestion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------------------------


def system(options: PromptOptions | None = None) -> str:
    return load_prompt(KIND, options)


def build_user(target: LearningMessage, context: Sequence[LearningMessage] = ()) -> str:
    """``<conversation>`` com até ``CONTEXT_BEFORE`` mensagens anteriores + a observada
    (marcada ``observe="true"``); o texto vai só como dado."""
    before = [m for m in context if m.id != target.id][-CONTEXT_BEFORE:]
    lines = ["<conversation>"]
    for msg in [*before, target]:
        mark = ' observe="true"' if msg.id == target.id else ""
        lines.append(
            f'<message id="{msg.id}" author="{msg.author.value}" source="{msg.source.value}"{mark}>'
            f"{neutralize(msg.text)}</message>"
        )
    lines.append("</conversation>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Validação (parser tolerante)
# ---------------------------------------------------------------------------------------------


def normalize_rule_key(value: Any) -> str | None:
    """``"Grammar.Past Simple"`` → ``"grammar.past_simple"``; inválido → ``None``."""
    if not isinstance(value, str):
        return None
    key = re.sub(r"[\s\-]+", "_", value.strip().lower())
    key = re.sub(r"\.+", ".", key).strip(".")
    if not key or len(key) > RULE_KEY_MAX or not _RULE_KEY_RE.match(key):
        return None
    return key


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return clip(value, limit)


def validate(raw: Mapping[str, Any], target: LearningMessage) -> list[Observation]:
    """Resposta crua → observações (sem ``id``) da mensagem ``target``."""
    if not isinstance(raw, Mapping):
        raise ModelInvalid("observe: resposta não é objeto")
    items = raw.get("items")
    if not isinstance(items, list):
        raise ModelInvalid("observe: campo 'items' ausente ou não é lista")
    out: list[Observation] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if len(out) >= MAX_ITEMS:
            break
        if not isinstance(item, Mapping):
            continue
        category = str(item.get("category", "")).strip().lower()
        if category not in MODEL_CATEGORIES:
            continue
        rule_key = normalize_rule_key(item.get("rule_key"))
        label = _text(item.get("label"), LABEL_MAX)
        if rule_key is None or label is None:
            continue
        if (category, rule_key) in seen:
            continue
        seen.add((category, rule_key))
        out.append(Observation(
            id=None,
            session_id=target.session_id,
            message_id=target.id,
            category=ObsCategory(category),
            rule_key=rule_key,
            label=label,
            span=_text(item.get("span"), SPAN_MAX),
            suggestion=_text(item.get("suggestion"), SUGGESTION_MAX),
        ))
    return out


async def observe(
    model: LearningModel,
    target: LearningMessage,
    context: Sequence[LearningMessage] = (),
    options: PromptOptions | None = None,
) -> tuple[list[Observation], float]:
    """Uma chamada de observação para a mensagem ``target`` do Pedro: ``(itens, custo_usd)``."""
    if target.author is not Author.YOU:
        return [], 0.0
    raw, cost = await model.complete(system(options), build_user(target, context), SCHEMA)
    return validate(raw, target), cost


# ---------------------------------------------------------------------------------------------
# recurring e contagem
# ---------------------------------------------------------------------------------------------


def family_key(rule_key: str) -> str:
    """Família de um ``rule_key``: os dois primeiros segmentos (``grammar.prepositions.at`` →
    ``grammar.prepositions``); com um segmento só, ele mesmo."""
    return ".".join(rule_key.split(".")[:2])


def family_label(rule_key: str) -> str:
    """Rótulo da família: ``grammar.past_simple.irregular`` → "Past simple"."""
    parts = family_key(rule_key).split(".")
    name = parts[-1].replace("_", " ").strip()
    return clip(name[:1].upper() + name[1:], LABEL_MAX) if name else rule_key


def derive_recurring(existing: Iterable[Observation], new: Iterable[Observation]) -> list[Observation]:
    """Observações ``recurring`` a criar depois de gravar ``new`` (spec §9 item 4).

    ``existing`` = o que a sessão já tinha **antes** de ``new``. Um ``rule_key`` de grammar que
    chega à ``RECURRING_AT``-ésima ocorrência cria uma ``recurring`` da família — uma vez por
    família na sessão. A ``recurring`` aponta para a mensagem/trecho da ocorrência que a criou."""
    counts: dict[str, int] = {}
    families: set[str] = set()
    for o in existing:
        if o.category is ObsCategory.GRAMMAR:
            counts[o.rule_key] = counts.get(o.rule_key, 0) + 1
        elif o.category is ObsCategory.RECURRING:
            families.add(family_key(o.rule_key))
    out: list[Observation] = []
    for o in new:
        if o.category is not ObsCategory.GRAMMAR:
            continue
        counts[o.rule_key] = counts.get(o.rule_key, 0) + 1
        fam = family_key(o.rule_key)
        if counts[o.rule_key] >= RECURRING_AT and fam not in families:
            families.add(fam)
            out.append(Observation(
                id=None,
                session_id=o.session_id,
                message_id=o.message_id,
                category=ObsCategory.RECURRING,
                rule_key=fam,
                label=family_label(o.rule_key),
                span=o.span,
                suggestion=None,
            ))
    return out


def distinct_count(items: Iterable[Observation]) -> int:
    """``count`` do ``lm_obs``: itens distintos por (``category``, ``label``) (spec §9 item 5)."""
    return len({(o.category, o.label.casefold()) for o in items})


__all__ = [
    "CONTEXT_BEFORE",
    "MAX_ITEMS",
    "RECURRING_AT",
    "SCHEMA",
    "build_user",
    "derive_recurring",
    "distinct_count",
    "family_key",
    "family_label",
    "normalize_rule_key",
    "observe",
    "system",
    "validate",
]
