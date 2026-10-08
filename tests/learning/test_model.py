"""Modelo e orçamento do Learning Mode (tarefa LM3.1; CA-04, parte de CA-13, LM-006, ENG-002).

Nada de rede nem chave real: o chat é um backend falso injetado no ``Registry`` e o orçamento é o
``MonthlyBudget`` de verdade sobre um ``CostsRepo`` em memória.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

import pytest

from magi.common.config import Config, ConfigError, parse_config
from magi.common.contracts import ChatReply, ProviderError, Usage
from magi.core.budget import MonthlyBudget, Price
from magi.learning.budget import TZ, LearningBudget, LearningCostTask
from magi.learning.model import (
    FakeModel,
    LearningModel,
    ModelBudget,
    ModelFailure,
    ModelInvalid,
    ModelTimeout,
    OpenAIModel,
    build_model,
    parse_json_object,
)
from magi.providers.registry import Registry

NOW = datetime(2026, 10, 7, 21, 0, tzinfo=TZ)
SCHEMA = {"title": "improve", "type": "object"}


class MemCosts:
    """``CostsRepo`` em memória."""

    def __init__(self, preset: float = 0.0) -> None:
        self.rows: list[Usage] = []
        self.preset = preset

    async def add(self, usage: Usage, at: datetime) -> int:
        self.rows.append(usage)
        return len(self.rows)

    async def month_total(self, year: int, month: int) -> float:
        return self.preset + sum(u.usd for u in self.rows)


def _budget(
    cap: float = 5.0, spent: float = 0.0, *, daily: int = 200, now: Any = None
) -> tuple[LearningBudget, MemCosts]:
    repo = MemCosts(spent)
    clock = now or (lambda: NOW)
    core = MonthlyBudget(
        repo, cap_usd=cap, prices={("openai", "*"): Price(input=1.0, output=4.0)}, now=clock
    )
    return LearningBudget(core, observe_daily_max=daily, now=clock), repo


class FakeBackend:
    """Backend de chat falso: guarda o contexto e devolve JSON fixo com consumo."""

    calls: list[Any] = []
    schemas: list[dict | None] = []  # json_schema de cada chamada (None = JSON simples)
    reply_text = '{"kind": "fix", "corrected": "I went"}'
    error: BaseException | None = None
    schema_error: BaseException | None = None  # levantado só nas chamadas com json_schema
    delay_s = 0.0

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    async def chat(
        self, key: Any, ctx: Any, messages: Any, tools: Any, json_mode: bool, *, json_schema: Any = None
    ) -> ChatReply:
        FakeBackend.calls.append((key, ctx, list(messages), json_mode))
        FakeBackend.schemas.append(json_schema)
        if FakeBackend.delay_s:
            await asyncio.sleep(FakeBackend.delay_s)
        if FakeBackend.error is not None:
            raise FakeBackend.error
        if json_schema is not None and FakeBackend.schema_error is not None:
            raise FakeBackend.schema_error
        return ChatReply(text=FakeBackend.reply_text, usage=ctx.usage(1000, 500))


@pytest.fixture(autouse=True)
def _reset_backend() -> None:
    FakeBackend.calls = []
    FakeBackend.schemas = []
    FakeBackend.schema_error = None
    FakeBackend.reply_text = '{"kind": "fix", "corrected": "I went"}'
    FakeBackend.error = None
    FakeBackend.delay_s = 0.0


def _config(actions: dict, observe: dict | None = None) -> Config:
    tasks = {"learning_actions": actions}
    if observe is not None:
        tasks["learning_observe"] = observe
    return parse_config({
        "providers": {"openai": {"keys": ["openai-test"]}, "fake": {"kind": "fake"}},
        "tasks": tasks,
    })


def _registry(cfg: Config) -> Registry:
    budget, _ = _budget()
    return Registry(cfg, budget, backends={"openai": FakeBackend}, get_secret=lambda _n: "not-a-real-key")


# -- CA-04: o config escolhe o modelo -----------------------------------------------------------


async def test_ca04_config_troca_modelo_sem_codigo(tmp_path: Any) -> None:
    fixtures = tmp_path / "fx.json"
    fixtures.write_text(json.dumps({"improve:I have went": {"kind": "fix", "corrected": "I went"}}))
    budget, repo = _budget()

    fake_cfg = _config({"provider": "fake", "model": "gravado", "fixtures": str(fixtures)})
    m1 = build_model(fake_cfg, "learning_actions", budget=budget)
    assert isinstance(m1, FakeModel) and isinstance(m1, LearningModel)
    assert (await m1.complete("sys", "I have went", SCHEMA))[0] == {"kind": "fix", "corrected": "I went"}
    assert FakeBackend.calls == []

    oa_cfg = _config(
        {"provider": "openai", "model": "gpt-5.4-mini", "reasoning_effort": "none", "timeout_s": 8}
    )
    m2 = build_model(oa_cfg, "learning_actions", budget=budget, registry=_registry(oa_cfg))
    assert isinstance(m2, OpenAIModel) and isinstance(m2, LearningModel)
    data, cost = await m2.complete("sys", "I have went", SCHEMA)
    assert data == {"kind": "fix", "corrected": "I went"}
    _key, ctx, messages, json_mode = FakeBackend.calls[-1]
    assert (ctx.model, ctx.task) == ("gpt-5.4-mini", "learning_actions")
    assert ctx.options["reasoning_effort"] == "none"
    assert json_mode and messages[0].role == "system" and "JSON" in messages[0].content
    assert FakeBackend.schemas[-1] is SCHEMA  # saída estruturada, e o schema segue no prompt
    assert json.dumps(SCHEMA, separators=(",", ":")) in messages[0].content
    assert messages[1].content == "I have went"
    assert cost == pytest.approx((1000 * 1.0 + 500 * 4.0) / 1e6)

    other = _config({"provider": "openai", "model": "gpt-outro"})
    m3 = build_model(other, "learning_actions", budget=budget, registry=_registry(other))
    await m3.complete("sys", "x", SCHEMA)
    assert FakeBackend.calls[-1][1].model == "gpt-outro"
    assert FakeBackend.calls[-1][1].options["timeout_s"] == 8.0  # padrão da spec §2


async def test_build_model_observe_e_erros() -> None:
    budget, _ = _budget()
    cfg = _config({"provider": "fake", "model": "a"}, {"provider": "openai", "model": "obs-model"})
    obs = build_model(cfg, "learning_observe", budget=budget, registry=_registry(cfg))
    assert isinstance(obs, OpenAIModel) and obs.label is LearningCostTask.OBSERVE and obs.timeout_s == 20.0
    with pytest.raises(ConfigError):
        build_model(cfg, "learning_observe", budget=budget)  # openai sem registro
    with pytest.raises(ConfigError):
        build_model(_config({"provider": "fake", "model": "a"}), "learning_observe", budget=budget)
    with pytest.raises(ValueError):
        build_model(cfg, "agent", budget=budget)


# -- CA-13 (parte): teto estourado recusa sem chamar o modelo; custo em costs ----------------


async def test_ca13_teto_estourado_recusa_sem_chamada() -> None:
    budget, repo = _budget(cap=5.0, spent=5.0)
    chat_calls: list[Any] = []

    class Chat:
        async def chat(
            self, messages: Any, *, json_mode: bool = False, json_schema: Any = None, personal: bool
        ) -> ChatReply:
            chat_calls.append(messages)
            return ChatReply(text="{}")

    m = OpenAIModel(Chat(), budget, label="learning_actions", model="gpt-5.4-mini")
    with pytest.raises(ModelBudget) as ei:
        await m.complete("sys", "I have went", SCHEMA)
    assert ei.value.code == "budget"
    assert chat_calls == [] and repo.rows == []

    fake = FakeModel({"*": {"ok": 1}}, budget=budget)
    with pytest.raises(ModelBudget):
        await fake.complete("sys", "u", SCHEMA)
    assert fake.calls == []
    assert not await budget.allowed(LearningCostTask.OBSERVE)


async def test_custo_gravado_com_rotulos_learning() -> None:
    budget, repo = _budget()
    oa = {"provider": "openai", "model": "gpt-5.4-mini"}
    cfg = _config(oa, oa)
    reg = _registry(cfg)
    for name in ("learning_actions", "learning_observe"):
        await build_model(cfg, name, budget=budget, registry=reg).complete("s", "u", SCHEMA)
    assert [str(u.task) for u in repo.rows] == ["learning_actions", "learning_observe"]
    assert all(u.provider == "openai" and u.model == "gpt-5.4-mini" and u.usd > 0 for u in repo.rows)
    assert (await budget.status()).spent_usd == pytest.approx(2 * 0.003)

    fake = FakeModel({"*": {"a": 1}}, cost_usd=0.25, budget=budget, label="learning_observe")
    assert (await fake.complete("s", "u", SCHEMA)) == ({"a": 1}, 0.25)
    assert str(repo.rows[-1].task) == "learning_observe" and repo.rows[-1].usd == 0.25


async def test_limite_diario_de_observacoes_e_virada_do_dia() -> None:
    now = [NOW]
    budget, _ = _budget(daily=2, now=lambda: now[0])
    fake = FakeModel({"*": {}}, budget=budget, label="learning_observe")
    await fake.complete("s", "1", SCHEMA)
    await fake.complete("s", "2", SCHEMA)
    with pytest.raises(ModelBudget):
        await fake.complete("s", "3", SCHEMA)
    assert await budget.allowed("learning_actions")  # ações não contam no limite diário
    now[0] = NOW + timedelta(days=1)
    await fake.complete("s", "4", SCHEMA)
    assert budget.observe_today == 1


# -- falhas (LM-007) ------------------------------------------------------------------------------


async def test_openai_falhas_viram_codigos() -> None:
    budget, repo = _budget()
    cfg = _config({"provider": "openai", "model": "m", "timeout_s": 0.05})
    m = build_model(cfg, "learning_actions", budget=budget, registry=_registry(cfg))

    FakeBackend.reply_text = "não é json"
    with pytest.raises(ModelInvalid) as ei:
        await m.complete("s", "u", SCHEMA)
    assert ei.value.code == "invalid" and len(repo.rows) == 1  # a chamada custou mesmo inválida

    FakeBackend.error = ProviderError("openai: 500")
    with pytest.raises(ModelFailure) as ef:
        await m.complete("s", "u", SCHEMA)
    assert ef.value.code == "model"

    FakeBackend.error = None
    FakeBackend.delay_s = 1.0
    with pytest.raises(ModelTimeout) as et:
        await m.complete("s", "u", SCHEMA)
    assert et.value.code == "timeout"


async def test_openai_schema_recusado_cai_em_json_simples() -> None:
    budget, _ = _budget()
    cfg = _config({"provider": "openai", "model": "qwen-local"})
    m = build_model(cfg, "learning_actions", budget=budget, registry=_registry(cfg))
    FakeBackend.schema_error = ProviderError("openai: HTTP 400: Invalid schema for response_format 'improve'")
    data, _ = await m.complete("sys", "I have went", SCHEMA)
    assert data == {"kind": "fix", "corrected": "I went"}
    assert FakeBackend.schemas == [SCHEMA, None]
    assert all(c[3] for c in FakeBackend.calls)  # json_mode nas duas
    # Recusa lembrada: a próxima chamada já vai sem schema.
    await m.complete("sys", "x", SCHEMA)
    assert FakeBackend.schemas[-1] is None and len(FakeBackend.schemas) == 3


async def test_openai_erro_400_comum_nao_desliga_schema() -> None:
    budget, _ = _budget()
    cfg = _config({"provider": "openai", "model": "gpt-5.4-mini"})
    m = build_model(cfg, "learning_actions", budget=budget, registry=_registry(cfg))
    FakeBackend.schema_error = ProviderError("openai: HTTP 400: context length exceeded")
    with pytest.raises(ModelFailure):
        await m.complete("sys", "x", SCHEMA)
    assert FakeBackend.schemas == [SCHEMA] and m.structured


async def test_fake_model_chaves_e_respostas() -> None:
    boom = ModelTimeout("x")
    fake = FakeModel({
        "improve:exato": {"k": "exato"},
        "so o user": {"k": "user"},
        "improve:*": {"k": "title"},
        "explain:cru": '```json\n{"k": "cru"}\n```',
        "explain:erro": boom,
    })
    assert (await fake.complete("s", "exato", SCHEMA))[0] == {"k": "exato"}
    assert (await fake.complete("s", "so o user", {"title": "x"}))[0] == {"k": "user"}
    assert (await fake.complete("s", "outra", SCHEMA))[0] == {"k": "title"}
    assert (await fake.complete("s", "cru", {"title": "explain"}))[0] == {"k": "cru"}
    with pytest.raises(ModelTimeout):
        await fake.complete("s", "erro", {"title": "explain"})
    with pytest.raises(ModelFailure):
        await fake.complete("s", "nada", {"title": "translate"})
    assert len(fake.calls) == 6 and fake.calls[0] == ("s", "exato", SCHEMA)


def test_parse_json_object() -> None:
    assert parse_json_object(' {"a": 1} ') == {"a": 1}
    for bad in ("[1, 2]", "oi", ""):
        with pytest.raises(ModelInvalid):
            parse_json_object(bad)
