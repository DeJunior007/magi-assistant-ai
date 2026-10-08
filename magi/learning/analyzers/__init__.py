"""Analisadores das ações do menu de seleção (tarefa LM3.2; spec §5, design §6, LM-008).

Cada analisador = prompt em ``magi/learning/prompts/<kind>.md`` + JSON Schema da saída + parser
tolerante. Uso pelo engine (LM3.3)::

    data, cost = await analyze(model, request, PromptOptions.from_config(cfg))

- ``analyze`` monta o system prompt (``PromptOptions``: nível e idiomas, LM-008) e a mensagem do
  usuário (o texto das mensagens **só** dentro de ``<conversation>``, como dado), chama
  ``LearningModel.complete`` e valida/corta a resposta no schema do ``kind`` (spec §5).
- Resposta fora do schema (campo obrigatório faltando, tipo errado, valor fora do enum) →
  ``ModelInvalid`` (``code = "invalid"``; o engine tenta de novo uma vez, LM-007). Campos extras
  são descartados e textos longos são cortados (parser tolerante).
- Pedido que o menu não deveria ter oferecido (Improve em mensagem da Condessa, Vocabulary com
  mais de 4 palavras, Translate acima de 400 caracteres, seleção fora do contexto) →
  ``ActionUnavailable`` **antes** de chamar o modelo (``action_available`` diz isso sem exceção).
- Erros do modelo (``ModelTimeout``/``ModelBudget``/``ModelFailure``) passam direto.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Template
from typing import Any

from magi.learning.contracts import ActionKind, ActionRequest, Author, LearningMessage, Selection
from magi.learning.model import LearningModel, ModelInvalid

#: Pasta dos prompts (``prompts/<kind>.md``).
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

#: Limites de disponibilidade do menu (spec §5).
VOCAB_MAX_WORDS = 4
TRANSLATE_MAX_CHARS = 400
#: ``note`` do Translate só para trechos de até 3 palavras (TRA-001).
TRANSLATE_NOTE_MAX_WORDS = 3

#: Nome do idioma das explicações no prompt (LM-008, P5).
LANGUAGE_NAMES = {
    "en": "simple British English",
    "pt-br": "simple Brazilian Portuguese",
    "en-gb": "British English",
}


class ActionUnavailable(ValueError):
    """A ação não vale para esta seleção (spec §5, "Disponibilidade no menu"); o modelo não é
    chamado. O menu já deveria ter desabilitado a ação."""


# ---------------------------------------------------------------------------------------------
# Opções do prompt
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromptOptions:
    """O que muda no system prompt: nível do Pedro e idiomas (LM-008, LM-009, spec §2)."""

    level: str = "B2"
    explain_language: str = "en"
    translate_to: str = "pt-br"

    @classmethod
    def from_config(cls, cfg: Any) -> PromptOptions:
        """De um ``LearningConfig`` (ou qualquer objeto com os mesmos atributos)."""
        return cls(
            level=getattr(cfg, "level", cls.level),
            explain_language=getattr(cfg, "explain_language", cls.explain_language),
            translate_to=getattr(cfg, "translate_to", cls.translate_to),
        )

    def variables(self) -> dict[str, str]:
        """Variáveis ``$nome`` dos prompts."""
        return {
            "level": self.level,
            "explain_language": LANGUAGE_NAMES.get(self.explain_language, self.explain_language),
            "translate_to": LANGUAGE_NAMES.get(self.translate_to, self.translate_to).removeprefix("simple "),
        }


@cache
def _prompt_template(kind: str) -> Template:
    return Template((PROMPTS_DIR / f"{kind}.md").read_text(encoding="utf-8"))


def load_prompt(kind: ActionKind | str, options: PromptOptions | None = None) -> str:
    """System prompt de ``prompts/<kind>.md`` com as variáveis de ``options``."""
    return _prompt_template(str(kind)).safe_substitute((options or PromptOptions()).variables()).strip()


# ---------------------------------------------------------------------------------------------
# Mensagem do usuário: <conversation> como dado
# ---------------------------------------------------------------------------------------------

_TAG_RE = re.compile(r"<(/?)(conversation|message|selection|sentence)\b", re.IGNORECASE)


def neutralize(text: str) -> str:
    """Impede que o texto feche/abra os blocos de dado (``</conversation>`` vira ``‹/conversation``)."""
    return _TAG_RE.sub(lambda m: f"‹{m.group(1)}{m.group(2)}", text)


def _attr(value: str) -> str:
    return value.replace('"', "'")


def selected_message(request: ActionRequest) -> LearningMessage:
    """A mensagem da seleção dentro de ``request.context`` (o recorte tem de bater)."""
    sel = request.selection
    for msg in request.context:
        if msg.id == sel.message_id:
            if not sel.matches(msg):
                raise ActionUnavailable("o texto da seleção não bate com a mensagem")
            return msg
    raise ActionUnavailable(f"mensagem {sel.message_id} da seleção fora do contexto")


def sentence_around(text: str, start: int, end: int) -> str:
    """A frase inteira que contém ``[start, end)`` (até ``. ! ?`` ou as pontas da mensagem)."""
    left = max(text.rfind(p, 0, start) for p in ".!?") + 1
    right_hits = [i for i in (text.find(p, end) for p in ".!?") if i != -1]
    right = min(right_hits) + 1 if right_hits else len(text)
    return text[left:right].strip()


def build_user(request: ActionRequest, extra: Mapping[str, str] | None = None) -> str:
    """Mensagem do usuário: contexto em ``<conversation>`` (cada ``<message>`` com autor e
    origem, a selecionada marcada) + ``<selection>`` + blocos extras (ex. ``<sentence>``)."""
    selected = selected_message(request)
    lines = ["<conversation>"]
    for msg in request.context:
        mark = ' selected="true"' if msg.id == selected.id else ""
        lines.append(
            f'<message id="{msg.id}" author="{msg.author.value}" source="{msg.source.value}"{mark}>'
            f"{neutralize(msg.text)}</message>"
        )
    lines.append("</conversation>")
    sel = request.selection
    lines.append(
        f'<selection message="{sel.message_id}" author="{_attr(selected.author.value)}" '
        f'source="{selected.source.value}">{neutralize(sel.text)}</selection>'
    )
    for tag, value in (extra or {}).items():
        lines.append(f"<{tag}>{neutralize(value)}</{tag}>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Validação e cortes (parser tolerante)
# ---------------------------------------------------------------------------------------------


def word_count(text: str) -> int:
    return len(text.split())


def clip(text: str, limit: int) -> str:
    """Corta ``text`` em ``limit`` caracteres, na última palavra inteira, com ``…`` no fim."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut and not text[limit - 1].isspace():
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def require_str(data: Mapping[str, Any], key: str, kind: str, *, allow_empty: bool = False) -> str:
    """Campo texto obrigatório; ausente, não texto ou vazio → ``ModelInvalid``."""
    value = data.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ModelInvalid(f"{kind}: campo '{key}' ausente ou não é texto")
    return value.strip()


def optional_str(data: Mapping[str, Any], key: str, kind: str) -> str | None:
    """Campo texto que pode ser ``null``/vazio (→ ``None``); outro tipo → ``ModelInvalid``."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ModelInvalid(f"{kind}: campo '{key}' não é texto")
    return value.strip() or None


def str_list(data: Mapping[str, Any], key: str, kind: str, *, required: bool) -> list[str]:
    """Lista de textos (itens vazios saem); ausente → ``[]`` se não obrigatória."""
    value = data.get(key)
    if value is None and not required:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ModelInvalid(f"{kind}: campo '{key}' não é lista de textos")
    return [v.strip() for v in value if v.strip()]


# ---------------------------------------------------------------------------------------------
# Analisador
# ---------------------------------------------------------------------------------------------

#: Valida/corta a resposta crua do modelo para o ``data`` do ``ActionResult``.
Validator = Callable[[Mapping[str, Any], ActionRequest], dict]
#: Confere a disponibilidade e devolve blocos extras da mensagem do usuário.
Preparer = Callable[[ActionRequest], Mapping[str, str]]


@dataclass(frozen=True, slots=True)
class Analyzer:
    """Uma ação do menu: ``kind``, JSON Schema (``title`` = ``kind``), validação e preparo."""

    kind: ActionKind
    schema: dict
    validate: Validator
    prepare: Preparer

    def system(self, options: PromptOptions | None = None) -> str:
        return load_prompt(self.kind, options)

    def user(self, request: ActionRequest) -> str:
        return build_user(request, self.prepare(request))

    async def run(
        self, model: LearningModel, request: ActionRequest, options: PromptOptions | None = None
    ) -> tuple[dict, float]:
        if request.kind is not self.kind:
            raise ValueError(f"analisador {self.kind} recebeu ação {request.kind}")
        user = self.user(request)  # confere a disponibilidade antes do modelo
        raw, cost = await model.complete(self.system(options), user, self.schema)
        if not isinstance(raw, Mapping):
            raise ModelInvalid(f"{self.kind}: resposta não é objeto")
        return self.validate(raw, request), cost


_MODULES = {
    ActionKind.IMPROVE: "magi.learning.analyzers.improve",
    ActionKind.EXPLAIN: "magi.learning.analyzers.explain",
    ActionKind.TRANSLATE: "magi.learning.analyzers.translate",
    ActionKind.VOCABULARY: "magi.learning.analyzers.vocabulary",
}


def get_analyzer(kind: ActionKind | str) -> Analyzer:
    """O analisador de ``kind`` (``ANALYZER`` do módulo ``analyzers/<kind>.py``)."""
    return importlib.import_module(_MODULES[ActionKind(kind)]).ANALYZER


async def analyze(
    model: LearningModel, request: ActionRequest, options: PromptOptions | None = None
) -> tuple[dict, float]:
    """Roda a ação ``request.kind``: ``(data validado, custo_usd)`` (spec §5, "Ciclo")."""
    return await get_analyzer(request.kind).run(model, request, options)


def action_available(kind: ActionKind | str, selection: Selection, author: Author | str) -> bool:
    """A ação vale para este trecho/autor? (spec §5, "Disponibilidade no menu"; P7, VOC-002)."""
    kind = ActionKind(kind)
    if not selection.text.strip():
        return False
    if kind is ActionKind.IMPROVE:
        return Author(author) is Author.YOU
    if kind is ActionKind.VOCABULARY:
        return 1 <= word_count(selection.text) <= VOCAB_MAX_WORDS
    if kind is ActionKind.TRANSLATE:
        return len(selection.text) <= TRANSLATE_MAX_CHARS
    return True


def ensure_available(request: ActionRequest) -> LearningMessage:
    """``ActionUnavailable`` se a ação não vale; devolve a mensagem selecionada."""
    msg = selected_message(request)
    if not action_available(request.kind, request.selection, msg.author):
        raise ActionUnavailable(f"{request.kind} indisponível para esta seleção")
    return msg


__all__ = [
    "LANGUAGE_NAMES",
    "PROMPTS_DIR",
    "TRANSLATE_MAX_CHARS",
    "TRANSLATE_NOTE_MAX_WORDS",
    "VOCAB_MAX_WORDS",
    "ActionUnavailable",
    "Analyzer",
    "PromptOptions",
    "action_available",
    "analyze",
    "build_user",
    "clip",
    "ensure_available",
    "get_analyzer",
    "load_prompt",
    "neutralize",
    "selected_message",
    "sentence_around",
]
