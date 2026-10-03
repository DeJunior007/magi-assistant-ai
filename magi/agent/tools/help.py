"""Ferramenta ``game_help`` do agente: ajuda no jogo em degraus (4.5, R14).

``game_help(question, topic?, want_solution?)``: o modelo passa a pergunta e, se puder, o resumo
canônico do trecho ("boss da lua"). O ``HelpTracker`` casa o trecho com os pedidos anteriores do
mesmo jogo e escolhe o degrau: 1º pedido → pista; de novo no mesmo trecho (ou travado) → dica
direta; 3º, ou "manda a solução"/"fala logo" → solução. A resposta vem da pesquisa com fontes
(mesma da ferramenta ``search``: só a pergunta e o nome do jogo vão ao provedor), curta, com as
fontes como cards no HUD. Sem jogo aberto (e sem ``game`` nos argumentos), pede o contexto.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from magi.agent.tools.base import arg_str
from magi.agent.tools.search import SearchTool, clean_question, source_cards, spoken_summary
from magi.common.contracts import ActionResult, Expression, HelpStep, ToolSpec, TurnContext
from magi.memory.help import HelpDecision, HelpTracker, game_key

GAME_HELP_SPEC = ToolSpec(
    name="game_help",
    description=(
        "Ajuda no jogo aberto (travou num chefe, puzzle, missão, onde ir). Dá a ajuda em degraus "
        "(pista, dica direta, solução) e lembra o que já foi dado no mesmo trecho; use em vez de "
        "search para dúvidas do jogo. question: a dúvida, autocontida, sem dados pessoais. topic: "
        "resumo curto do trecho (ex.: 'boss da lua'). want_solution: true se ele pediu a resposta "
        "direto ('manda a solução', 'fala logo'). game: só se não houver jogo aberto e ele disser qual."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Dúvida autocontida, sem dados pessoais"},
            "topic": {"type": "string", "description": "Resumo curto do trecho, ex.: 'boss da lua'"},
            "want_solution": {"type": "boolean", "description": "Pediu a solução direto"},
            "game": {"type": "string", "description": "Nome do jogo, se nenhum estiver aberto"},
        },
        "required": ["question"],
    },
)

STEP_LABEL: dict[HelpStep, str] = {
    HelpStep.HINT: "Pista",
    HelpStep.DIRECT: "Dica direta",
    HelpStep.SOLUTION: "Solução",
}

_STEP_ASK: dict[HelpStep, str] = {
    HelpStep.HINT: (
        "dê só uma pista vaga, que aponte a direção sem revelar a solução nem spoilers, em 1 ou 2 frases"
    ),
    HelpStep.DIRECT: (
        "dê uma dica direta (o que fazer ou onde ir), sem o passo a passo completo nem spoilers da "
        "história, em até 2 frases"
    ),
    HelpStep.SOLUTION: "dê a solução completa e objetiva, em passos resumidos, em até 4 frases",
}

HELP_PROMPT = (
    "Jogo: {game}. Um jogador pediu ajuda: {question} Com base em guias e fontes atuais da web, "
    "{ask}. Responda em português do Brasil, sem markdown. Se não houver informação confiável, diga isso."
)

SAY_WHICH_GAME = "Não vi jogo aberto. Qual jogo e em que parte você está?"
SAY_WHAT = "Ajuda com qual parte do jogo?"
SAY_NO_SEARCH = "Não consegui pesquisar agora; vou no que eu sei, sem confirmar."
SAY_NO_SOURCE = "Não achei guia que confirme isso; vou no que eu sei, sem confirmar."
SAY_BUDGET = "Bati no teto de gasto do mês, então não pesquisei; vou no que eu sei."

#: "manda a solução", "fala logo", "me dá a resposta", "pode dar spoiler".
_WANTS_SOLUTION = re.compile(
    r"\b(manda|me\s+d[aá]|d[aá]|quero|fala|diz|mostra)\s+(logo\s+)?(a\s+)?(solu[cç][aã]o|resposta)\b"
    r"|\bfala\s+logo\b|\bdiz\s+logo\b|\bpode\s+(dar\s+)?spoiler|\bpasso\s+a\s+passo\b",
    re.IGNORECASE,
)


def wants_solution(*texts: str) -> bool:
    return any(t and _WANTS_SOLUTION.search(t) for t in texts)


def _bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().casefold() in {"true", "1", "sim", "yes"}
    return bool(v)


def _step_note(d: HelpDecision) -> str:
    """Contexto para o modelo (vai no ``full_text`` do resultado da ferramenta)."""
    note = f"{STEP_LABEL[d.step]} sobre \"{d.topic}\" ({d.reason})"
    if d.stuck and d.stuck_minutes:
        note += f"; ele está nesse trecho há {d.stuck_minutes} min"
    return note + "."


class GameHelpTool:
    """``game_help``: degrau pelo ``HelpTracker`` + resposta da pesquisa com fontes."""

    spec = GAME_HELP_SPEC
    danger = False

    def __init__(
        self,
        tracker: HelpTracker,
        game: Callable[[], Any],
        search: SearchTool | None = None,
        *,
        private_terms: Sequence[str] = (),
    ) -> None:
        self.tracker = tracker
        self._game = game  # () -> RunningGame | None (name, appid, since)
        self._search = search
        self._private = tuple(t for t in private_terms if t and t.strip())

    @property
    def name(self) -> str:
        return self.spec.name

    def _resolve(self, args: Mapping[str, Any]) -> tuple[str, int, datetime | None] | None:
        g = self._game()
        if g is not None:
            since = datetime.fromtimestamp(float(g.since), UTC) if getattr(g, "since", None) else None
            return g.name, game_key(getattr(g, "appid", None), g.name), since
        name = arg_str(args, "game")
        if not name:
            return None
        return name, game_key(None, name), None

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        question = clean_question(arg_str(args, "question"), self._private)
        if not question:
            return ActionResult(ok=False, speech=SAY_WHAT, expression=Expression.CONFUSED)
        game = self._resolve(args)
        if game is None:
            return ActionResult(ok=False, speech=SAY_WHICH_GAME, expression=Expression.CONFUSED)
        name, appid, since = game
        topic = clean_question(arg_str(args, "topic"), self._private) or question
        want = _bool(args.get("want_solution")) or wants_solution(question, text)
        d = await self.tracker.decide(appid, topic, session_start=since, want_solution=want)
        await self.tracker.record(d)
        return await self._answer(d, name, question)

    async def _answer(self, d: HelpDecision, game: str, question: str) -> ActionResult:
        label, note = STEP_LABEL[d.step], _step_note(d)
        if self._search is None:
            return ActionResult(ok=True, speech=SAY_NO_SEARCH, full_text=note)
        prompt = HELP_PROMPT.format(game=game, question=question, ask=_STEP_ASK[d.step])
        res, budget_hit = await self._search.lookup(prompt)
        if res is None:
            return ActionResult(ok=True, speech=SAY_BUDGET if budget_hit else SAY_NO_SEARCH, full_text=note)
        cards = source_cards(res)
        if not cards:
            return ActionResult(ok=True, speech=SAY_NO_SOURCE, full_text=note)
        sentences = 4 if d.step is HelpStep.SOLUTION else 2
        answer = spoken_summary(res.answer, sentences) or "Achei estes guias."
        sources = "\n".join(f"- {c.title} — {c.url}" for c in cards)
        full = f"{label}: {answer}\n\nFontes:\n{sources}"
        return ActionResult(ok=True, speech=spoken_summary(answer), full_text=full, cards=cards)


def help_tools(
    tracker: HelpTracker | None,
    game: Callable[[], Any] | None,
    search: SearchTool | None = None,
    *,
    private_terms: Sequence[str] = (),
) -> list[GameHelpTool]:
    """``[GameHelpTool]`` com rastreador e jogo; sem eles, nada."""
    if tracker is None or game is None:
        return []
    return [GameHelpTool(tracker, game, search, private_terms=private_terms)]
