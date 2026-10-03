"""Ferramenta ``search`` do agente: pesquisa na internet com fontes (3.8, R10, R16.4).

O modelo reescreve a pergunta (só a pergunta, autocontida); a ferramenta manda à tarefa ``search``
(Gemini com Google Search, cota gratuita) só esse texto, com ``personal=False`` — nada de memória,
humor, capturas ou o texto original do turno (R10.2). O nome do usuário, se aparecer, é removido.

Pelo S3 o grounding do Gemini tem latência instável: cada tentativa tem teto (``timeout_s`` da
tarefa, padrão 8 s). Em estouro, erro ou cota (429), cai para ``[tasks.search_fallback]`` (OpenAI +
``web_search``, paga), que passa pelo orçamento: com o teto estourado não pesquisa e diz isso.

A fala é curta (≤ 2 frases); as fontes (título + URL) vão como cards ``link`` e na legenda
completa do HUD (R10.3). Resposta sem fonte não é afirmada: diz que não confirmou.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from magi.agent.tools.base import arg_str
from magi.common.contracts import (
    ActionResult,
    BudgetExceeded,
    CardLevel,
    CardMsg,
    Expression,
    SearchResult,
    ToolSpec,
    TurnContext,
)
from magi.providers.base import SEARCH_TIMEOUT_S

log = logging.getLogger(__name__)

SEARCH_SPEC = ToolSpec(
    name="search",
    description=(
        "Pesquisa na internet (Google) fatos recentes ou que você não sabe: lançamentos, datas, "
        "notícias, preços. Use antes de dizer que não sabe; nunca invente. question: só a pergunta, "
        "reescrita para ficar autocontida e objetiva, SEM nada pessoal do usuário (nome, humor, "
        "memórias, o que está na tela)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Pergunta autocontida, sem dados pessoais"},
        },
        "required": ["question"],
    },
)

#: O que vai ao provedor: instrução fixa + a pergunta. Nada do contexto do turno.
SEARCH_PROMPT = (
    "Responda em português do Brasil, em no máximo 3 frases, sem markdown, com base em fontes "
    "atuais da web. Se não houver informação confiável, diga isso. Pergunta: {question}"
)

MAX_QUESTION_CHARS = 300
MAX_SOURCES = 5
#: Folga além do ``timeout_s`` do adaptador, para o erro dele (mais claro) chegar antes do corte.
TIMEOUT_GRACE_S = 0.5
FALLBACK_TASK = "search_fallback"

SAY_WHAT = "Pesquisar o quê?"
SAY_NO_SOURCE = "Pesquisei, mas não achei fonte que confirme isso."
SAY_BUDGET = "Bati no teto de gasto do mês, então não pesquisei."
SAY_FAILED = "A pesquisa não respondeu agora. Tenta de novo daqui a pouco."

_MD = re.compile(r"[*_`#>]+|\s*\[\d+(?:,\s*\d+)*\]")
_SENT_END = re.compile(r"(?<=[.!?…])\s+")


def clean_question(question: str, private_terms: Sequence[str] = ()) -> str:
    """Pergunta enviada à pesquisa: espaços normalizados, sem termos privados, com teto de tamanho."""
    q = question
    for term in private_terms:
        if term and term.strip():
            q = re.sub(rf"\b{re.escape(term.strip())}\b", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\s+", " ", q).strip(" ,;")
    return q[:MAX_QUESTION_CHARS].strip()


def spoken_summary(answer: str, max_sentences: int = 2) -> str:
    """Resumo para a fala: sem markdown/citações ``[1]``, no máximo ``max_sentences`` frases."""
    text = re.sub(r"\s+", " ", _MD.sub("", answer)).strip()
    parts = [p for p in _SENT_END.split(text) if p]
    return " ".join(parts[:max_sentences])


def _cards(res: SearchResult) -> tuple[CardMsg, ...]:
    seen: set[str] = set()
    out: list[CardMsg] = []
    for s in res.sources:
        if not s.url or s.url in seen:
            continue
        seen.add(s.url)
        out.append(CardMsg(level=CardLevel.LINK, title=s.title or s.url, url=s.url))
        if len(out) >= MAX_SOURCES:
            break
    return tuple(out)


def _timeout(providers: Any, task: str) -> float:
    """``timeout_s`` de ``[tasks.<task>]`` (padrão 8 s, como no adaptador)."""
    tasks = getattr(getattr(providers, "config", None), "tasks", None)
    tcfg = tasks.get(task) if isinstance(tasks, Mapping) else None
    try:
        return float((getattr(tcfg, "options", None) or {}).get("timeout_s", SEARCH_TIMEOUT_S))
    except (TypeError, ValueError):
        return SEARCH_TIMEOUT_S


class SearchTool:
    """``search(question)``: Gemini com Google Search; reserva paga opcional; fontes no HUD."""

    spec = SEARCH_SPEC
    danger = False

    def __init__(self, providers: Any, *, private_terms: Sequence[str] = ()) -> None:
        self._providers = providers
        self._private = tuple(t for t in private_terms if t and t.strip())

    @property
    def name(self) -> str:
        return self.spec.name

    def _attempts(self) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = [("search", self._providers.search)]
        fallback = getattr(self._providers, "search_fallback", None)
        if callable(fallback):
            out.append((FALLBACK_TASK, fallback))
        return out

    async def _search(self, query: str) -> tuple[SearchResult | None, bool]:
        """(resultado, bateu no teto). Tenta a pesquisa e, se falhar, a reserva."""
        budget_hit = False
        for task, get in self._attempts():
            try:
                provider = get()
                if provider is None:
                    continue
                limit = _timeout(self._providers, task) + TIMEOUT_GRACE_S
                res = await asyncio.wait_for(provider.search(query, personal=False), limit)
            except BudgetExceeded:
                log.info("pesquisa (%s): teto do orçamento, não pesquisa", task)
                budget_hit = True
                continue
            except TimeoutError:
                log.warning("pesquisa (%s): sem resposta no prazo", task)
                continue
            except Exception as e:  # erro do provedor, 429 em todas as chaves, config
                log.warning("pesquisa (%s) falhou: %s", task, e)
                continue
            if res.answer.strip() or res.sources:
                return res, budget_hit
            log.warning("pesquisa (%s): resposta vazia", task)
        return None, budget_hit

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        question = clean_question(arg_str(args, "question"), self._private)
        if not question:
            return ActionResult(ok=False, speech=SAY_WHAT, expression=Expression.CONFUSED)
        res, budget_hit = await self._search(SEARCH_PROMPT.format(question=question))
        if res is None:
            if budget_hit:
                return ActionResult(ok=False, speech=SAY_BUDGET)
            return ActionResult(ok=False, speech=SAY_FAILED, expression=Expression.CONFUSED)
        cards = _cards(res)
        if not cards:
            return ActionResult(ok=True, speech=SAY_NO_SOURCE, expression=Expression.CONFUSED)
        speech = spoken_summary(res.answer) or "Achei estas fontes."
        sources = "\n".join(f"- {c.title} — {c.url}" for c in cards)
        full = f"{spoken_summary(res.answer, 6) or speech}\n\nFontes:\n{sources}"
        return ActionResult(ok=True, speech=speech, full_text=full, cards=cards)


def search_tools(providers: Any, *, private_terms: Sequence[str] = ()) -> list[SearchTool]:
    """``[SearchTool]`` se houver provedores com a tarefa ``search`` configurada; senão nada (a
    ficha da 3.9 mostra "pesquisar na internet" como limite)."""
    if providers is None or not callable(getattr(providers, "search", None)):
        return []
    config = getattr(providers, "config", None)
    tasks = getattr(config, "tasks", None)
    if tasks is not None and "search" not in tasks:
        return []
    return [SearchTool(providers, private_terms=private_terms)]
