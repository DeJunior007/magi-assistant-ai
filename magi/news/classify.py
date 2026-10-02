"""Passo 3 do ``magi-news``: classificar itens agrupados (design §8, R18.6, R19.1).

Em lotes (uma chamada de chat por lote, ``json_mode=True``, ``personal=False``, provedor da tarefa
``news``), cada item ainda sem ``kind`` recebe franquia canônica, tipo, spoiler (sim/não e de quê),
tamanho do fato 0–1 e manchete segura em português. Prompt fixo (``prompts/classify.md``) + até 6
exemplos tirados do retorno recente do usuário (``news_feedback``); sem retorno, os exemplos fixos
do próprio prompt.

Gravação: ``franchise`` e ``kind`` nas colunas; o resto em ``spoiler`` (jsonb), porque
``news_items`` não tem coluna de tamanho: ``{"has": bool, "of": str|None, "safe_title": str,
"size": float}`` (veja ``Classification.from_item``).

Cota esgotada (``QuotaExhausted``) para sem erro e deixa o resto pendente para a próxima execução.
Resposta inválida (JSON quebrado ou item fora do esquema) é registrada e o item é pulado; ele
continua pendente.
"""

from __future__ import annotations

import json
import logging
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any

from magi.common.contracts import ChatMessage, ChatProvider, NewsItem, NewsRepo, QuotaExhausted
from magi.news.cluster import lead

log = logging.getLogger(__name__)

KINDS = ("anuncio", "data", "trailer", "temporada", "rumor", "review", "outro")
BATCH_SIZE = 10
MAX_ITEMS = 100
MAX_EXAMPLES = 6
PROMPT_PATH = Path(__file__).parent / "prompts" / "classify.md"
EXAMPLES_MARK = "<!-- exemplos -->"

#: Esquema de cada objeto em ``{"itens": [...]}`` (validado por ``parse_entry``).
ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "franquia", "tipo", "spoiler", "spoiler_de", "tamanho", "manchete_segura"],
    "properties": {
        "id": {"type": "integer"},
        "franquia": {"type": ["string", "null"]},
        "tipo": {"enum": list(KINDS)},
        "spoiler": {"type": "boolean"},
        "spoiler_de": {"type": ["string", "null"]},
        "tamanho": {"type": "number", "minimum": 0, "maximum": 1},
        "manchete_segura": {"type": "string", "minLength": 1},
    },
}


class InvalidEntry(ValueError):
    """Objeto da resposta fora do esquema."""


@dataclass(frozen=True, slots=True)
class Classification:
    franchise: str | None
    kind: str
    spoiler: bool
    spoiler_of: str | None
    size: float
    safe_title: str

    def spoiler_json(self) -> dict[str, Any]:
        return {"has": self.spoiler, "of": self.spoiler_of, "safe_title": self.safe_title, "size": self.size}

    def apply(self, item: NewsItem) -> NewsItem:
        return replace(item, franchise=self.franchise, kind=self.kind, spoiler=self.spoiler_json())

    @classmethod
    def from_item(cls, item: NewsItem) -> Classification | None:
        sp = item.spoiler or {}
        if item.kind is None or "safe_title" not in sp:
            return None
        return cls(item.franchise, item.kind, bool(sp.get("has")), sp.get("of"),
                   float(sp.get("size", 0.0)), str(sp["safe_title"]))

    def to_entry(self, item_id: int) -> dict[str, Any]:
        return {"id": item_id, "franquia": self.franchise, "tipo": self.kind, "spoiler": self.spoiler,
                "spoiler_de": self.spoiler_of, "tamanho": self.size, "manchete_segura": self.safe_title}


@dataclass(slots=True)
class ClassifyReport:
    classified: int = 0
    invalid: int = 0  # itens pulados por resposta inválida (continuam pendentes)
    deferred: int = 0  # itens deixados para a próxima execução (cota esgotada)
    quota_exhausted: bool = False

    def summary(self) -> str:
        s = f"{self.classified} classificados, {self.invalid} inválidos"
        if self.quota_exhausted:
            s += f", cota esgotada ({self.deferred} pendentes)"
        return s


def _norm_kind(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    s = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _opt_str(entry: Mapping[str, Any], key: str) -> str | None:
    v = entry.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise InvalidEntry(f"{key} não é texto")
    return v.strip() or None


def parse_entry(entry: Any) -> tuple[int, Classification]:
    """Valida um objeto da resposta contra ``ITEM_SCHEMA``."""
    if not isinstance(entry, Mapping):
        raise InvalidEntry("não é objeto")
    missing = [k for k in ITEM_SCHEMA["required"] if k not in entry]
    if missing:
        raise InvalidEntry(f"faltam {missing}")
    item_id = entry["id"]
    if isinstance(item_id, bool) or not isinstance(item_id, int):
        raise InvalidEntry("id não é inteiro")
    kind = _norm_kind(entry["tipo"])
    if kind not in KINDS:
        raise InvalidEntry(f"tipo inválido: {entry['tipo']!r}")
    spoiler = entry["spoiler"]
    if not isinstance(spoiler, bool):
        raise InvalidEntry("spoiler não é booleano")
    size = entry["tamanho"]
    if isinstance(size, bool) or not isinstance(size, int | float) or not 0 <= size <= 1:
        raise InvalidEntry(f"tamanho fora de 0-1: {size!r}")
    safe = _opt_str(entry, "manchete_segura")
    if safe is None:
        raise InvalidEntry("manchete_segura vazia")
    return item_id, Classification(
        franchise=_opt_str(entry, "franquia"),
        kind=kind,
        spoiler=spoiler,
        spoiler_of=_opt_str(entry, "spoiler_de") if spoiler else None,
        size=float(size),
        safe_title=safe,
    )


def item_input(item: NewsItem, item_id: int | None = None) -> dict[str, Any]:
    return {"id": item.id if item_id is None else item_id, "titulo": item.title,
            "resumo": lead(item.summary)}


@cache
def _prompt_parts() -> tuple[str, str]:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    head, _, fixed = text.partition(EXAMPLES_MARK)
    return head.strip(), fixed.strip()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def build_system_prompt(examples: Sequence[tuple[NewsItem, int]] = ()) -> str:
    """Prompt fixo + exemplos: os do retorno do usuário (até 6), senão os fixos de referência."""
    head, fixed = _prompt_parts()
    lines = []
    for n, (item, _signal) in enumerate(examples[:MAX_EXAMPLES], 1):
        c = Classification.from_item(item)
        if c is None:
            continue
        lines.append(f"Entrada: {_dumps(item_input(item, n))}\nSaída: {_dumps(c.to_entry(n))}")
    body = "\n\n".join(lines) if lines else fixed
    return f"{head}\n\nExemplos:\n\n{body}\n"


async def _examples(repo: Any) -> list[tuple[NewsItem, int]]:
    get = getattr(repo, "recent_feedback", None)
    if get is None:
        return []
    return list(await get(MAX_EXAMPLES))


async def classify_pending(
    repo: NewsRepo,
    chat: ChatProvider,
    *,
    batch_size: int = BATCH_SIZE,
    max_items: int = MAX_ITEMS,
) -> ClassifyReport:
    """Classifica até ``max_items`` itens pendentes. Cota esgotada e respostas inválidas não
    levantam erro."""
    report = ClassifyReport()
    pending = await repo.unclassified(limit=max_items)
    if not pending:
        return report
    system = ChatMessage(role="system", content=build_system_prompt(await _examples(repo)))
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        user = ChatMessage(role="user", content=_dumps({"itens": [item_input(i) for i in batch]}))
        try:
            reply = await chat.chat([system, user], json_mode=True, personal=False)
        except QuotaExhausted as exc:
            report.quota_exhausted = True
            report.deferred = len(pending) - start
            log.warning("cota de classificação esgotada (%s); %d itens ficam para depois",
                        exc, report.deferred)
            break
        by_id = {i.id: i for i in batch}
        done: set[int] = set()
        for entry in _entries(reply.text):
            try:
                item_id, c = parse_entry(entry)
            except InvalidEntry as exc:
                log.warning("classificação inválida %r: %s", entry, exc)
                continue
            item = by_id.get(item_id)
            if item is None or item_id in done:
                log.warning("classificação de item fora do lote ou repetido: %s", item_id)
                continue
            await repo.update_item(c.apply(item))
            done.add(item_id)
        report.classified += len(done)
        missed = len(batch) - len(done)
        if missed:
            report.invalid += missed
            log.warning("%d itens do lote sem classificação válida; ficam pendentes", missed)
    return report


def _entries(text: str) -> list[Any]:
    text = (text or "").strip()
    if text.startswith("```"):  # cerca de código, apesar do json_mode
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        log.warning("resposta da classificação não é JSON (%s): %.200r", exc, text)
        return []
    if isinstance(data, Mapping):
        data = data.get("itens")
    if not isinstance(data, list):
        log.warning("resposta da classificação sem lista 'itens': %.200r", text)
        return []
    return data
