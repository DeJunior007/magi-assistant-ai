"""Falsos compartilhados: orçamento, relógio e keyring (nada de rede nem keyring real)."""

from __future__ import annotations

import pytest

from magi.common.config import Config, parse_config
from magi.common.contracts import BUDGET_BLOCKED_TASKS, BudgetExceeded, BudgetStatus, ProviderTask, Usage


class FakeBudget:
    """Budget falso: registra a ordem das chamadas em ``log`` (compartilhado com o backend)."""

    def __init__(self, log: list[str] | None = None) -> None:
        self.log = log if log is not None else []
        self.blocked = False
        self.recorded: list[Usage] = []

    async def ensure_allowed(self, task: ProviderTask) -> None:
        self.log.append(f"ensure:{task}")
        if self.blocked and task in BUDGET_BLOCKED_TASKS:
            raise BudgetExceeded("teto")

    async def record(self, usage: Usage) -> None:
        self.log.append(f"record:{usage.task}")
        self.recorded.append(usage)

    async def status(self) -> BudgetStatus:
        return BudgetStatus(spent_usd=0.0, cap_usd=5.0)

    async def set_cap(self, usd: float) -> None:
        pass


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


SECRETS = {
    "openai-1": "sk-um",
    "openai-2": "sk-dois",
    "openai-3": "sk-tres",
    "gemini-1": "g-um",
    "gemini-2": "g-dois",
}


def make_config(**overrides: dict) -> Config:
    data = {
        "providers": {
            "openai": {"keys": ["openai-1", "openai-2"]},
            "gemini": {"keys": ["gemini-1", "gemini-2"], "free_tier": True},
        },
        "tasks": {
            "stt": {"provider": "openai", "model": "stt-x"},
            "tts": {"provider": "openai", "model": "tts-x", "voice": "nova"},
            "agent": {"provider": "openai", "model": "chat-x"},
            "vision": {"provider": "openai", "model": "vis-x"},
            "embeddings": {"provider": "openai", "model": "emb-x", "dimensions": 8},
            "search": {"provider": "gemini", "model": "search-x"},
            "news": {"provider": "gemini", "model": "news-x", "embedding_model": "gemb-x"},
        },
    }
    for k, v in overrides.items():
        data[k] = v
    return parse_config(data)


@pytest.fixture
def budget() -> FakeBudget:
    return FakeBudget()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def get_secret():
    return SECRETS.get


@pytest.fixture(name="make_config")
def make_config_fixture():
    return make_config
