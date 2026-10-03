"""Perfil e estilo (tarefa 4.2; R11.1, R11.4): sinais locais, 1×/dia, limite, vocab do STT, custo."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from magi.agent.prompt import PROFILE_MAX_TOKENS, estimate_tokens, profile_section
from magi.common.contracts import (
    STT_HINT_MAX_TOKENS,
    ChatReply,
    Game,
    PcmFormat,
    ProfileRepo,
    ProviderTask,
    Transcript,
    TurnRecord,
    VocabRepo,
    VocabTerm,
)
from magi.core.stt import HintedStt
from magi.memory import migrate as mig
from magi.memory.profile import (
    InMemoryProfileRepo,
    InMemoryVocabRepo,
    PgProfileRepo,
    PgVocabRepo,
    ProfileUpdater,
    agent_chat,
    extract_stats,
)
from magi.providers.registry import Registry
from tests.providers.conftest import SECRETS, FakeBudget, make_config
from tests.providers.test_registry import FakeBackend

T0 = datetime(2026, 9, 26, 21, 0, tzinfo=UTC)

CASUAL = [
    "mano abre o elden ring aí",
    "suave, tlgd, bota uma música no pique",
    "que bagui doido mano kkk",
    "porra, morri de novo no elden ring",
    "vc sabe se o hollow knight tá em promo?",
    "bora jogar hades, tô no pique",
]
FORMAL = ["Por favor, poderia abrir o navegador?", "Obrigado, senhora."]


class FakeTurns:
    def __init__(self) -> None:
        self.rows: list[TurnRecord] = []

    def add_week(self, start: datetime, texts: list[str], per_day: int = 5) -> None:
        for day in range(7):
            for i in range(per_day):
                at = start + timedelta(days=day, minutes=10 * i)
                self.rows.append(TurnRecord("pc", "", texts[(day * per_day + i) % len(texts)], at))

    async def recent(self, limit: int = 20) -> list[TurnRecord]:
        return sorted(self.rows, key=lambda t: t.at, reverse=True)[:limit]


class Catalog:
    def all(self) -> list[Game]:
        return [Game(1245620, "ELDEN RING"), Game(367520, "Hollow Knight"), Game(1145360, "Hades"),
                Game(1, "Stardew Valley")]


class Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


class RecordingChat:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[list, bool]] = []

    async def chat(self, messages, *, tools=(), json_mode=False, personal):
        self.calls.append((list(messages), personal))
        return ChatReply(text=self.text)


def _updater(turns, clock, **kw) -> ProfileUpdater:
    profiles = InMemoryProfileRepo(now=clock)
    vocab = InMemoryVocabRepo()
    return ProfileUpdater(turns, profiles, vocab=vocab, catalog=Catalog(), now=clock, tz=UTC, **kw)


def test_extract_stats_casual_vs_formal():
    turns = [TurnRecord("pc", "", t, T0) for t in CASUAL]
    s = extract_stats(turns, catalog=Catalog(), tz=UTC)
    assert s.formality == "bem casual" and s.reply_pref == "curtas" and s.period == "noite"
    slang = dict(s.slang)
    assert slang["mano"] == 2 and slang["pique"] == 2 and "tlgd" in slang and "bagui" in slang
    assert dict(s.games)["ELDEN RING"] == 2 and "Stardew Valley" not in dict(s.games)
    assert s.swears_per_turn > 0
    f = extract_stats([TurnRecord("pc", "", t, T0) for t in FORMAL], tz=UTC)
    assert f.formality == "formal" and not f.slang


async def test_profile_changes_after_a_week_within_limit():
    turns, clock = FakeTurns(), Clock(T0)
    turns.add_week(T0 - timedelta(days=7), FORMAL)
    up = _updater(turns, clock)
    assert await up.maybe_update()
    first = up.current()
    assert first and "formal" in first

    clock.t = T0 + timedelta(days=7, hours=1)  # uma semana de turnos casuais depois
    turns.add_week(T0 + timedelta(hours=1), CASUAL * 30)
    assert await up.maybe_update()
    second = up.current()
    assert second != first and "bem casual" in second and "mano" in second and "ELDEN RING" in second
    assert estimate_tokens(second) <= PROFILE_MAX_TOKENS
    assert profile_section(second).endswith(second)  # cabe inteiro na seção do prompt


async def test_model_profile_is_personal_and_hard_cut():
    turns, clock = FakeTurns(), Clock(T0)
    turns.add_week(T0 - timedelta(days=7), CASUAL)
    chat = RecordingChat("Fala: mano " * 400)  # modelo ignorou o limite
    up = _updater(turns, clock, chat=lambda: chat)
    assert await up.maybe_update()
    messages, personal = chat.calls[0]
    assert personal is True
    assert "mano" in messages[1].content and "gírias/abreviações" in messages[1].content
    assert estimate_tokens(up.current()) <= PROFILE_MAX_TOKENS and up.current().endswith("…")


async def test_does_not_run_without_new_turns_or_before_24h():
    turns, clock = FakeTurns(), Clock(T0)
    up = _updater(turns, clock)
    assert not await up.maybe_update()  # sem turnos
    turns.add_week(T0 - timedelta(days=7), CASUAL)
    assert await up.maybe_update()
    clock.t = T0 + timedelta(hours=23)
    turns.add_week(T0 + timedelta(minutes=1), CASUAL)
    assert not await up.maybe_update()  # menos de 24 h
    clock.t = T0 + timedelta(days=3)
    turns.rows = [t for t in turns.rows if t.at <= T0]
    assert not await up.maybe_update()  # passou 1 dia, mas nenhum turno novo
    turns.rows.append(TurnRecord("pc", "", "mano", T0 + timedelta(days=2)))
    assert not await up.maybe_update()  # turnos novos abaixo do mínimo


async def test_stt_hint_gets_slang_and_game_names():
    turns, clock = FakeTurns(), Clock(T0)
    turns.add_week(T0 - timedelta(days=7), CASUAL)
    up = _updater(turns, clock)
    await up.maybe_update()
    kinds = {(t.term, t.kind) for t in await up.vocab.all()}
    assert {("mano", "slang"), ("tlgd", "slang"), ("ELDEN RING", "name"), ("Hades", "name")} <= kinds

    class Stt:
        name, model, free_tier = "fake", "x", False
        hints: list[str] = []

        async def transcribe(self, audio, fmt, *, hint="", language="pt", personal):
            self.hints.append(hint)
            return Transcript.raw("oi")

    for i in range(300):  # muito vocabulário: a dica continua no limite
        await up.vocab.upsert(VocabTerm(f"termo{i}", "slang", 0.5))
    stt = HintedStt(Stt(), catalog=Catalog(), vocab=up.vocab)
    hint = await stt.build_hint()
    assert "mano" in hint and "tlgd" in hint and "ELDEN RING" in hint
    assert estimate_tokens(hint) <= STT_HINT_MAX_TOKENS + 10  # heurísticas do STT e do prompt diferem pouco
    await stt.transcribe(b"\0\0", PcmFormat(), personal=True)
    assert "mano" in Stt.hints[0]


async def test_cost_goes_through_budget_and_paid_provider():
    turns, clock = FakeTurns(), Clock(T0)
    turns.add_week(T0 - timedelta(days=7), CASUAL)
    log: list[str] = []
    budget = FakeBudget(log)
    cfg = make_config()
    reg = Registry(cfg, budget, backends={"openai": lambda c: FakeBackend(c, log)}, get_secret=SECRETS.get)
    up = _updater(turns, clock, chat=agent_chat(reg))
    assert await up.maybe_update()
    assert f"ensure:{ProviderTask.AGENT}" in log
    assert [u.task for u in budget.recorded] == [ProviderTask.AGENT]
    assert up.current() == "ok"  # texto do backend falso

    # teto estourado: nada é cobrado e o perfil sai dos sinais locais
    budget.blocked, budget.recorded = True, []
    clock.t = T0 + timedelta(days=2)
    turns.add_week(T0 + timedelta(hours=1), CASUAL)
    assert await up.maybe_update()
    assert budget.recorded == [] and up.current().startswith("Fala: Fala bem casual")


@pytest.fixture
async def conn():
    name = f"test_profile_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    c = None
    try:
        with psycopg.connect(mig.dsn_from_env()) as m:
            mig.migrate(m, schema=name, memories_dim=8, news_dim=2)
        c = await psycopg.AsyncConnection.connect(mig.dsn_from_env(), autocommit=True)
        await c.execute("SELECT set_config('search_path', %s, false)", [f'"{name}", public'])
        yield c
    finally:
        if c is not None:
            await c.close()
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


@pytest.mark.db
async def test_pg_repos(conn):
    profiles, vocab = PgProfileRepo(conn), PgVocabRepo(conn)
    assert isinstance(profiles, ProfileRepo) and isinstance(vocab, VocabRepo)
    assert await profiles.get() is None
    p1 = await profiles.put("Fala: casual.")
    p2 = await profiles.put("Fala: bem casual.")
    assert (await profiles.get()).body == "Fala: bem casual." and p2.updated_at >= p1.updated_at
    await vocab.upsert(VocabTerm("mano", "slang", 1.2))
    await vocab.upsert(VocabTerm("mano", "slang", 2.0))
    await vocab.upsert(VocabTerm("Hades", "name", 1.6))
    assert [t.term for t in await vocab.all()] == ["mano", "Hades"]
    assert await vocab.all("name") == [VocabTerm("Hades", "name", pytest.approx(1.6))]
