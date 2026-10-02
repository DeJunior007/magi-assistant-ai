"""Testes do ``MonthlyBudget`` (tarefa 3.2, R16.1-R16.5) com repo e relógio falsos."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from magi.common.config import ConfigError, load_config
from magi.common.contracts import Budget, BudgetExceeded, ProviderTask, Usage
from magi.core.budget import TZ, CapStateFile, MonthlyBudget, Price, parse_prices


class FakeRepo:
    def __init__(self) -> None:
        self.rows: list[tuple[Usage, datetime]] = []

    async def add(self, usage: Usage, at: datetime) -> int:
        self.rows.append((usage, at))
        return len(self.rows)

    async def month_total(self, year: int, month: int) -> float:
        return sum(
            u.usd for u, at in self.rows if (at.astimezone(TZ).year, at.astimezone(TZ).month) == (year, month)
        )


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


PRICES = {
    ("openai", "agent-m"): Price(input=2.0, output=8.0),  # USD por 1M tokens
    ("openai", "stt-m"): Price(input=0.006, per=60),  # USD por minuto (unidades em segundos)
    ("gemini", "*"): Price(input=1.0),
}


def agent(inp: float = 0, out: float = 0) -> Usage:
    return Usage(
        provider="openai", task=ProviderTask.AGENT, model="agent-m", input_units=inp, output_units=out
    )


def make(tmp_path, cap=1.0, clock=None, repo=None, warns=None):
    clock = clock or Clock(datetime(2026, 10, 15, 12, tzinfo=TZ))
    return MonthlyBudget(
        repo or FakeRepo(),
        cap_usd=cap,
        prices=PRICES,
        state=CapStateFile(tmp_path / "budget_state.json"),
        on_warn=(warns.append if warns is not None else None),
        now=clock,
    )


async def test_price_and_record(tmp_path):
    repo = FakeRepo()
    b = make(tmp_path, repo=repo)
    assert isinstance(b, Budget)
    await b.record(agent(100_000, 50_000))  # 0.2 + 0.4
    stt = Usage(provider="openai", task=ProviderTask.STT, model="stt-m", input_units=120)
    await b.record(stt)  # 2 min * 0.006
    await b.record(Usage(provider="gemini", task=ProviderTask.SEARCH, model="x", input_units=1e6))
    await b.record(Usage(provider="nenhum", task=ProviderTask.TTS, model="y", input_units=99))
    await b.record(Usage(provider="nenhum", task=ProviderTask.AGENT, model="y", usd=0.05))
    usds = [round(u.usd, 6) for u, _ in repo.rows]
    assert usds == [0.6, 0.012, 1.0, 0.0, 0.05]
    assert all(at.tzinfo is not None for _, at in repo.rows)
    st = await b.status()
    assert st.spent_usd == pytest.approx(1.662) and st.cap_usd == 1.0


async def test_warn_once_at_80(tmp_path):
    warns = []
    b = make(tmp_path, cap=1.0, warns=warns)
    await b.record(agent(out=90_000))  # 0.72
    assert warns == []
    await b.record(agent(out=10_000))  # 0.80
    await b.record(agent(out=10_000))  # 0.88
    assert len(warns) == 1 and warns[0].fraction == pytest.approx(0.8)  # disparou em 80%, não em 88%
    # outro processo (mesmo estado) não repete o aviso
    b2 = make(tmp_path, cap=1.0, warns=warns)
    await b2.record(agent(out=1_000))
    assert len(warns) == 1


async def test_async_warn_callback(tmp_path):
    got = []

    async def on_warn(st):
        got.append(st)

    b = make(tmp_path, cap=0.1)
    b.on_warn = on_warn
    await b.record(agent(out=12_500))  # 0.1
    assert len(got) == 1


async def test_block_at_100_only_blocked_tasks(tmp_path):
    b = make(tmp_path, cap=0.5)
    await b.ensure_allowed(ProviderTask.AGENT)
    await b.record(agent(out=62_500))  # 0.5
    for task in (ProviderTask.AGENT, ProviderTask.VISION, ProviderTask.SEARCH):
        with pytest.raises(BudgetExceeded):
            await b.ensure_allowed(task)
    for task in (ProviderTask.STT, ProviderTask.TTS, ProviderTask.EMBEDDINGS, ProviderTask.NEWS):
        await b.ensure_allowed(task)


async def test_month_rollover(tmp_path):
    clock = Clock(datetime(2026, 10, 31, 23, 30, tzinfo=TZ))
    b = make(tmp_path, cap=0.5, clock=clock)
    await b.record(agent(out=62_500))
    with pytest.raises(BudgetExceeded):
        await b.ensure_allowed(ProviderTask.AGENT)
    # 02:30 UTC de 1/11 ainda é 31/10 em São Paulo
    clock.at = datetime(2026, 11, 1, 2, 30, tzinfo=UTC)
    with pytest.raises(BudgetExceeded):
        await b.ensure_allowed(ProviderTask.AGENT)
    clock.at = datetime(2026, 11, 1, 0, 1, tzinfo=TZ)
    await b.ensure_allowed(ProviderTask.AGENT)
    assert (await b.status()).spent_usd == 0


async def test_warn_again_next_month(tmp_path):
    warns = []
    clock = Clock(datetime(2026, 10, 20, tzinfo=TZ))
    b = make(tmp_path, cap=0.1, clock=clock, warns=warns)
    await b.record(agent(out=12_500))
    clock.at = datetime(2026, 11, 2, tzinfo=TZ)
    await b.record(agent(out=12_500))
    assert len(warns) == 2


async def test_set_cap_unblocks_and_persists(tmp_path):
    warns = []
    repo = FakeRepo()
    b = make(tmp_path, cap=0.5, repo=repo, warns=warns)
    await b.record(agent(out=62_500))  # 0.5 -> aviso + bloqueio
    assert len(warns) == 1
    await b.set_cap(8)
    await b.ensure_allowed(ProviderTask.AGENT)
    assert (await b.status()).cap_usd == 8
    # reinício: o teto por voz continua
    b2 = make(tmp_path, cap=0.5, repo=repo)
    assert b2.cap_usd == 8
    # novo teto: novo aviso ao chegar a 80% dele
    await b.record(agent(out=750_000))  # +6.0 -> 6.5/8
    assert len(warns) == 2
    with pytest.raises(ValueError):
        await b.set_cap(-1)


async def test_config_change_overrides_voice_cap(tmp_path):
    b = make(tmp_path, cap=5)
    await b.set_cap(8)
    assert make(tmp_path, cap=5).cap_usd == 8
    b3 = make(tmp_path, cap=6)  # usuário editou monthly_usd depois do ajuste
    assert b3.cap_usd == 6
    assert make(tmp_path, cap=5).cap_usd == 5  # o ajuste por voz foi descartado


async def test_repo_failure_does_not_raise(tmp_path):
    class Broken(FakeRepo):
        async def add(self, usage, at):
            raise RuntimeError("db fora")

    b = make(tmp_path, cap=0.5, repo=Broken())
    await b.record(agent(out=62_500))
    with pytest.raises(BudgetExceeded):
        await b.ensure_allowed(ProviderTask.AGENT)


def test_from_config_and_parse_prices(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[paths]\ndata_dir = "{tmp_path}"\n[budget]\nmonthly_usd = 3.0\n'
        '[budget.prices.openai."m-1"]\ninput = 1.5\noutput = 6\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_path)
    b = MonthlyBudget.from_config(cfg, FakeRepo())
    assert b.cap_usd == 3.0
    assert b.price_usd(Usage("openai", ProviderTask.AGENT, "m-1", 1e6, 1e6)) == 7.5
    with pytest.raises(ConfigError):
        parse_prices({"budget": {"prices": {"openai": {"m": {"per": 0}}}}})
    with pytest.raises(ConfigError):
        parse_prices({"budget": {"prices": {"openai": {"m": {"input": -1}}}}})


def test_corrupt_state_is_ignored(tmp_path):
    (tmp_path / "budget_state.json").write_text("{nope", encoding="utf-8")
    assert make(tmp_path, cap=2).cap_usd == 2
