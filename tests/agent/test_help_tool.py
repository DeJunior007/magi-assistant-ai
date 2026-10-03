"""Ajuda no jogo em degraus (4.5, R14): ``HelpTracker`` + ferramenta ``game_help``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from magi.agent.prompt import GameContext, game_section
from magi.agent.tools.help import GameHelpTool, wants_solution
from magi.agent.tools.search import SearchTool
from magi.common.contracts import CardLevel, HelpStep, SearchResult, SearchSource, TurnContext, WakeSource
from magi.memory.help import HelpTracker, InMemoryHelpLogRepo, game_key
from tests.memory.fake_embed import vector

CTX = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC), mood=0)
T0 = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)
APPID = 1030300
_SYN = {"chefe": "boss", "chefão": "boss"}


async def fake_embed(texts: Sequence[str]) -> list[list[float]]:
    """Embeddings falsos determinísticos; "chefe" e "boss" viram a mesma palavra."""
    return [vector(" ".join(_SYN.get(w, w) for w in t.casefold().split())) for t in texts]


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, minutes: float) -> None:
        self.at += timedelta(minutes=minutes)


@dataclass
class Game:
    name: str = "Hollow Knight: Silksong"
    appid: int | None = APPID
    since: float = (T0 - timedelta(minutes=30)).timestamp()


class FakeSearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, *, personal: bool) -> SearchResult:
        assert personal is False
        self.queries.append(query)
        return SearchResult(
            answer="Olhe para cima da arena. Use o gancho nas plataformas. Depois ataque pelas costas.",
            sources=(SearchSource("Wiki", "https://wiki.example/lua"),),
        )


class FakeProviders:
    def __init__(self) -> None:
        self.s = FakeSearch()

    def search(self) -> FakeSearch:
        return self.s


GAME = Game()


def setup(game: Game | None = GAME, embed=fake_embed):
    clock = Clock(T0)
    repo = InMemoryHelpLogRepo()
    tracker = HelpTracker(repo, embed, now=clock)
    providers = FakeProviders()
    tool = GameHelpTool(tracker, lambda: game, SearchTool(providers))
    return tool, tracker, clock, providers.s, repo


async def ask(tool: GameHelpTool, question: str, topic: str = "", **kw):
    return await tool.run({"question": question, "topic": topic, **kw}, CTX, question)


async def test_second_request_same_part_starts_at_direct_hint():
    tool, tracker, clock, search, repo = setup()
    r1 = await ask(tool, "Como passo do boss da lua?", "boss da lua")
    assert r1.ok and r1.full_text.startswith("Pista:")
    assert "pista vaga" in search.queries[-1] and "Silksong" in search.queries[-1]
    assert r1.cards and r1.cards[0].level is CardLevel.LINK and "Fontes:" in r1.full_text
    clock.advance(5)
    r2 = await ask(tool, "Ainda não consegui o chefe da lua", "o chefe da lua")
    assert r2.full_text.startswith("Dica direta:")
    assert [e.topic for e in repo.rows] == ["boss da lua", "boss da lua"]
    assert [e.step for e in repo.rows] == [HelpStep.HINT, HelpStep.DIRECT]
    clock.advance(5)
    r3 = await ask(tool, "boss da lua de novo", "boss da lua")
    assert r3.full_text.startswith("Solução:") and "solução completa" in search.queries[-1]


async def test_ask_for_solution_skips_steps():
    tool, *_ , repo = setup()
    r = await ask(tool, "Manda a solução do puzzle do relógio", "puzzle do relógio")
    assert r.full_text.startswith("Solução:")
    assert repo.rows[-1].step is HelpStep.SOLUTION
    assert wants_solution("fala logo onde fica a chave") and not wants_solution("me dá uma dica")
    r = await ask(tool, "onde fica a chave", "chave da torre", want_solution=True)
    assert r.full_text.startswith("Solução:")


async def test_different_topic_restarts_at_hint():
    tool, tracker, clock, *_ = setup()
    await ask(tool, "Como passo do boss da lua?", "boss da lua")
    clock.advance(3)
    r = await ask(tool, "Onde acho o mapa da floresta?", "mapa da floresta")
    assert r.full_text.startswith("Pista:")
    assert set(tracker.current.values()) == {("mapa da floresta", HelpStep.HINT)}


async def test_stuck_by_time_in_same_session_but_not_after_restart():
    # Sessão de 3 h; pediu há 2,5 h (fora da janela de 2 h, mas na mesma sessão): travado.
    game = Game(since=(T0 - timedelta(hours=3)).timestamp())
    tool, tracker, clock, _, repo = setup(game)
    clock.at = T0 - timedelta(minutes=150)
    await ask(tool, "boss da lua", "boss da lua")
    clock.at = T0
    d = await tracker.decide(APPID, "o chefe da lua", session_start=T0 - timedelta(hours=3))
    assert d.step is HelpStep.DIRECT and d.stuck and d.stuck_minutes == 150
    assert "travado há 150 min" in d.reason
    # Jogo reaberto agora: o pedido antigo (2,5 h) não conta mais; recomeça na pista.
    d = await tracker.decide(APPID, "o chefe da lua", session_start=T0)
    assert d.step is HelpStep.HINT and not d.stuck


async def test_stuck_by_achievements_hook_starts_at_direct():
    clock = Clock(T0)

    async def idle(appid: int) -> float | None:
        return 90.0

    tracker = HelpTracker(InMemoryHelpLogRepo(), fake_embed, now=clock, achievements_idle=idle)
    d = await tracker.decide(APPID, "porta trancada", session_start=T0 - timedelta(minutes=80))
    assert d.step is HelpStep.DIRECT and d.stuck
    d = await tracker.decide(APPID, "porta trancada", session_start=T0 - timedelta(minutes=10))
    assert d.step is HelpStep.HINT


async def test_no_game_open_asks_for_context():
    tool, *_ , repo = setup(game=None)
    r = await ask(tool, "como passo do boss?")
    assert not r.ok and "Qual jogo" in r.speech and not repo.rows
    r = await ask(tool, "como passo do boss?", game="Hades")
    assert r.ok and repo.rows[-1].game_appid == game_key(None, "Hades") < 0


async def test_without_embeddings_falls_back_to_words():
    tool, *_ , repo = setup(embed=None)
    await ask(tool, "boss da lua", "boss da lua")
    r = await ask(tool, "boss lua", "o boss da lua")
    assert r.full_text.startswith("Dica direta:")


async def test_prompt_help_line_has_current_step():
    tool, tracker, *_ = setup()
    await ask(tool, "boss da lua", "boss da lua")
    ctx = tracker.annotate(GameContext(name="Silksong", session_minutes=30), APPID)
    text = game_section(ctx)
    assert "boss da lua" in text and "já deu pista" in text and "dica direta" in text
