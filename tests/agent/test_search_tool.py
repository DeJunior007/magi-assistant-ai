"""Ferramenta ``search`` (3.8): pergunta limpa, fontes no HUD, reserva, orçamento e ficha."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest

from magi.agent.graph import GraphAgent
from magi.agent.self_model import SelfModel
from magi.agent.tools.search import (
    SAY_BUDGET,
    SAY_NO_SOURCE,
    SearchTool,
    clean_question,
    search_tools,
    spoken_summary,
)
from magi.common.config import parse_config
from magi.common.contracts import (
    BUDGET_BLOCKED_TASKS,
    BudgetExceeded,
    BudgetStatus,
    CardLevel,
    ChatReply,
    ProviderError,
    ProviderTask,
    SearchResult,
    SearchSource,
    ToolCall,
    TurnContext,
    Usage,
    WakeSource,
)
from magi.core.actions import Registry as ActionRegistry
from magi.core.assemble import default_agent
from magi.providers.registry import Registry

CTX = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC), mood=0)
SILKSONG = SearchResult(
    answer="**Silksong** saiu em 4 de setembro de 2025 [1]. A DLC Sea of Sorrow sai em 2026. Mais texto.",
    sources=(
        SearchSource("Team Cherry", "https://teamcherry.com.au/silksong"),
        SearchSource("Wiki", "https://hollowknight.wiki/Silksong"),
        SearchSource("Team Cherry de novo", "https://teamcherry.com.au/silksong"),
    ),
)


class FakeSearch:
    def __init__(self, result: SearchResult | Exception, delay: float = 0.0) -> None:
        self.result = result
        self.delay = delay
        self.queries: list[tuple[str, bool]] = []

    async def search(self, query: str, *, personal: bool) -> SearchResult:
        self.queries.append((query, personal))
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeProviders:
    def __init__(self, primary: FakeSearch, fallback: FakeSearch | None = None, chat=None) -> None:
        self.primary, self.fallback, self._chat = primary, fallback, chat

    def search(self) -> FakeSearch:
        return self.primary

    def search_fallback(self) -> FakeSearch | None:
        return self.fallback

    def chat(self, task: ProviderTask = ProviderTask.AGENT):
        return self._chat


class ScriptChat:
    name, model, free_tier = "fake", "fake-1", False

    def __init__(self, replies: list[ChatReply]) -> None:
        self.replies = replies
        self.seen: list = []

    async def chat(self, messages, *, tools=(), json_mode=False, personal):
        self.seen.append(list(messages))
        return self.replies.pop(0)


async def test_so_a_pergunta_vai_para_a_pesquisa_sem_dados_pessoais() -> None:
    fake = FakeSearch(SILKSONG)
    tool = SearchTool(FakeProviders(fake), private_terms=("Pedro",))
    texto_do_turno = "Pedro aqui, tô triste, qual a data da DLC do Silksong?"
    await tool.run({"question": "Pedro,  qual a data de lançamento da DLC de Silksong?"}, CTX, texto_do_turno)
    [(query, personal)] = fake.queries
    assert personal is False
    assert "qual a data de lançamento da DLC de Silksong?" in query
    assert "Pedro" not in query and "triste" not in query and "aqui" not in query
    assert clean_question("  pergunta   do  pedro  ", ["Pedro"]) == "pergunta do"


async def test_fontes_vao_como_cards_e_fala_curta() -> None:
    res = await SearchTool(FakeProviders(FakeSearch(SILKSONG))).run({"question": "Silksong DLC?"}, CTX)
    assert res.ok
    assert res.speech == "Silksong saiu em 4 de setembro de 2025. A DLC Sea of Sorrow sai em 2026."
    assert [(c.level, c.url) for c in res.cards] == [
        (CardLevel.LINK, "https://teamcherry.com.au/silksong"),
        (CardLevel.LINK, "https://hollowknight.wiki/Silksong"),
    ]
    assert "Fontes:" in res.full_text and "Team Cherry — https://teamcherry.com.au/silksong" in res.full_text
    assert spoken_summary("Um. Dois! Três?") == "Um. Dois!"


async def test_sem_fontes_diz_que_nao_confirmou() -> None:
    res = await SearchTool(FakeProviders(FakeSearch(SearchResult(answer="Talvez em 2027.")))).run(
        {"question": "x?"}, CTX
    )
    assert res.speech == SAY_NO_SOURCE and not res.cards and "2027" not in (res.full_text or "")


@pytest.mark.parametrize("falha", ["timeout", "erro"])
async def test_timeout_ou_erro_cai_para_a_reserva(falha: str, monkeypatch) -> None:
    monkeypatch.setattr("magi.agent.tools.search.SEARCH_TIMEOUT_S", 0.01)
    monkeypatch.setattr("magi.agent.tools.search.TIMEOUT_GRACE_S", 0.0)
    primary = FakeSearch(SILKSONG, delay=1) if falha == "timeout" else FakeSearch(ProviderError("429"))
    reserve = FakeSearch(SearchResult(answer="Sai em 2026.", sources=(SearchSource("T", "https://t.co"),)))
    res = await SearchTool(FakeProviders(primary, reserve)).run({"question": "q?"}, CTX)
    assert len(primary.queries) == 1 and len(reserve.queries) == 1
    assert res.ok and res.speech == "Sai em 2026." and res.cards[0].url == "https://t.co"


# -- com o registro real de provedores (orçamento e reserva de [tasks.search_fallback]) --------


class Budget:
    def __init__(self, blocked: bool) -> None:
        self.blocked = blocked
        self.recorded: list[Usage] = []

    async def ensure_allowed(self, task: ProviderTask) -> None:
        if self.blocked and task in BUDGET_BLOCKED_TASKS:
            raise BudgetExceeded("teto")

    async def record(self, usage: Usage) -> None:
        self.recorded.append(usage)

    async def status(self) -> BudgetStatus:
        return BudgetStatus(spent_usd=5.0, cap_usd=5.0)

    async def set_cap(self, usd: float) -> None:
        pass


class Backend:
    def __init__(self, result: SearchResult | Exception) -> None:
        self.result = result
        self.calls: list[str] = []

    async def search(self, key, ctx, query: str) -> SearchResult:
        self.calls.append(ctx.model)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _registry(budget: Budget, gemini: Backend, openai: Backend) -> Registry:
    cfg = parse_config(
        {
            "providers": {
                "openai": {"keys": ["openai-1"]},
                "gemini": {"keys": ["gemini-1"], "free_tier": True},
            },
            "tasks": {
                "agent": {"provider": "openai", "model": "chat-x"},
                "search": {"provider": "gemini", "model": "g-search", "timeout_s": 1},
                "search_fallback": {"provider": "openai", "model": "o-search"},
            },
        }
    )
    secrets = {"openai-1": "sk-um", "gemini-1": "g-um"}
    return Registry(
        cfg, budget, backends={"openai": lambda c: openai, "gemini": lambda c: gemini}, get_secret=secrets.get
    )


async def test_orcamento_esgotado_responde_honesto_sem_pesquisar_pago() -> None:
    gemini, openai = Backend(ProviderError("sem resposta em 8 s")), Backend(SILKSONG)
    res = await SearchTool(_registry(Budget(blocked=True), gemini, openai)).run({"question": "q?"}, CTX)
    assert gemini.calls == ["g-search"] and openai.calls == []  # a paga nem foi chamada
    assert res.speech == SAY_BUDGET and not res.ok


async def test_reserva_do_registro_conta_no_orcamento_como_search() -> None:
    budget = Budget(blocked=False)
    paid = SearchResult(answer="Ok.", sources=(SearchSource("T", "https://t.co"),),
                        usage=Usage(provider="openai", task=ProviderTask.SEARCH, model="o-search"))
    gemini, openai = Backend(ProviderError("falhou")), Backend(paid)
    reg = _registry(budget, gemini, openai)
    res = await SearchTool(reg).run({"question": "q?"}, CTX)
    assert res.ok and openai.calls == ["o-search"]
    assert [u.task for u in budget.recorded] == [ProviderTask.SEARCH]
    assert reg.search_fallback().task is ProviderTask.SEARCH


# -- no agente e na ficha ---------------------------------------------------------------------


async def test_agente_mostra_fontes_no_hud_e_ficha_lista_search() -> None:
    chat = ScriptChat([
        ChatReply(text="", tool_calls=(ToolCall("c1", "search", {"question": "data da DLC de Silksong"}),)),
        ChatReply(text="Silksong saiu em setembro de 2025; a DLC sai em 2026."),
    ])
    providers = FakeProviders(FakeSearch(SILKSONG), chat=chat)
    model = SelfModel()
    agent = default_agent(providers, ActionRegistry([]), model)
    assert isinstance(agent, GraphAgent)
    assert "search" in {s.name for s in model.tools}
    assert "pesquisar na internet" not in " ".join(model.gaps())
    res = await agent.answer("quando sai a DLC do Silksong?", CTX)
    assert [c.url for c in res.cards][0] == "https://teamcherry.com.au/silksong"
    assert "Fontes:" in res.full_text
    assert search_tools(None) == []


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("MAGI_LIVE"), reason="MAGI_LIVE=1 e chaves no keyring")
async def test_live_pergunta_recente_vem_com_fonte() -> None:  # pragma: no cover - rede e chaves
    cfg = parse_config(
        {
            "providers": {
                "openai": {"keys": ["openai-1"]},
                "gemini": {"keys": ["gemini-1"], "free_tier": True},
            },
            "tasks": {
                "agent": {"provider": "openai", "model": "gpt-5.4-mini"},
                "search": {"provider": "gemini", "model": "gemini-2.5-flash", "timeout_s": 8},
                "search_fallback": {"provider": "openai", "model": "gpt-5.4-mini", "timeout_s": 10},
            },
        }
    )
    budget = Budget(blocked=False)
    res = await SearchTool(Registry(cfg, budget)).run(
        {"question": "Qual a data de lançamento da DLC Sea of Sorrow de Hollow Knight Silksong?"}, CTX
    )
    print(res.speech, res.full_text, [u.model for u in budget.recorded], sep="\n")
    assert res.ok and res.cards
