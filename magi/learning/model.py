"""Modelo de linguagem do Learning Mode (tarefa LM3.1; ENG-002, LM-006, LM-007, spec §3, design §6).

``LearningModel`` é o protocolo que os analisadores (LM3.2) e o engine (LM3.3) usam:
``await model.complete(system, user, schema) -> (dados, custo_usd)``. Implementações:

- ``OpenAIModel``: chat dos providers atuais (``magi.providers``), modelo/prazo/esforço de
  ``[tasks] learning_actions`` ou ``learning_observe``; confere o teto **antes** da chamada e grava
  o custo em ``costs`` depois (``LearningBudget``).
- ``FakeModel``: respostas gravadas por chave, para testes (nenhuma chamada real).
- ``build_model(config, task_name, ...)``: escolhe a implementação só pelo config (CA-04).

Falhas viram ``ModelError`` com ``code`` em ``ACTION_ERRORS`` (``timeout`` | ``budget`` |
``model`` | ``invalid``), que o engine copia para ``ActionResult.error`` (LM-007).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from magi.common.config import Config, ConfigError
from magi.common.contracts import BudgetExceeded, ChatMessage, ChatReply, ProviderError, Usage
from magi.learning.budget import LearningBudget, LearningCostTask
from magi.learning.config import LearningTask, learning_tasks

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------
# Protocolo e erros
# ---------------------------------------------------------------------------------------------


@runtime_checkable
class LearningModel(Protocol):
    """Modelo do Learning Mode (spec §3). ``schema`` é o JSON Schema da saída (spec §5); a
    resposta é um objeto JSON já decodificado e o custo da chamada em USD."""

    async def complete(self, system: str, user: str, schema: dict) -> tuple[dict, float]: ...


class ModelError(Exception):
    """Falha de ``LearningModel.complete``; ``code`` é um de ``ACTION_ERRORS`` (LM-007)."""

    code = "model"


class ModelTimeout(ModelError):
    code = "timeout"


class ModelBudget(ModelError):
    """Teto estourado: a chamada foi recusada sem chegar ao modelo (LM-006, CA-13)."""

    code = "budget"


class ModelFailure(ModelError):
    code = "model"


class ModelInvalid(ModelError):
    """A resposta não é um objeto JSON (o engine tenta de novo uma vez, LM-007)."""

    code = "invalid"


def parse_json_object(text: str) -> dict:
    """Objeto JSON da resposta; tolera cerca de código ```json. ``ModelInvalid`` se não for."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        s = s.rsplit("```", 1)[0]
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise ModelInvalid(f"resposta não é JSON: {e}") from None
    if not isinstance(data, dict):
        raise ModelInvalid("resposta JSON não é um objeto")
    return data


def schema_instruction(schema: Mapping[str, Any]) -> str:
    """Linha final do system prompt pedindo JSON no schema (json_mode exige a palavra JSON)."""
    return (
        "Answer only with one JSON object that follows this JSON Schema, no prose:\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )


# ---------------------------------------------------------------------------------------------
# OpenAIModel
# ---------------------------------------------------------------------------------------------


class ChatLike(Protocol):
    """O que ``OpenAIModel`` usa do provedor (``magi.providers.registry.GuardedChat``)."""

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_mode: bool = False,
        json_schema: dict | None = None,
        personal: bool,
    ) -> ChatReply: ...


def schema_refused(e: ProviderError) -> bool:
    """Erro 400 do provedor recusando o schema da saída estruturada (``response_format`` /
    ``response_json_schema``): vale repetir com JSON simples."""
    msg = str(e).lower()
    return "400" in msg and ("schema" in msg or "response_format" in msg)


class _NoCoreBudget:
    """``Budget`` vazio para o ``GuardedChat`` do Learning Mode: o teto e o custo ficam com o
    ``LearningBudget`` (senão o custo seria gravado duas vezes)."""

    async def ensure_allowed(self, task: Any) -> None:
        return None

    async def record(self, usage: Usage) -> None:
        return None


class OpenAIModel:
    """``LearningModel`` sobre o chat dos providers atuais (ENG-002)."""

    def __init__(
        self,
        chat: ChatLike,
        budget: LearningBudget,
        *,
        label: LearningCostTask | str,
        model: str = "",
        timeout_s: float = 8.0,
    ) -> None:
        self.chat = chat
        self.budget = budget
        self.label = LearningCostTask(label)
        self.model = model
        self.timeout_s = timeout_s
        # Saída estruturada por JSON Schema (strict); desliga de vez se o provedor recusar o schema.
        self.structured = True

    def __repr__(self) -> str:
        return f"<OpenAIModel {self.label}: {self.model}>"

    async def complete(self, system: str, user: str, schema: dict) -> tuple[dict, float]:
        try:
            await self.budget.ensure_allowed(self.label)
        except BudgetExceeded as e:
            raise ModelBudget(str(e)) from e
        messages = [
            ChatMessage(role="system", content=f"{system.rstrip()}\n\n{schema_instruction(schema)}"),
            ChatMessage(role="user", content=user),
        ]
        try:
            reply = await self._ask(messages, schema)
        except TimeoutError as e:
            raise ModelTimeout(f"sem resposta em {self.timeout_s:g} s") from e
        except ProviderError as e:
            if isinstance(e.__cause__, TimeoutError):
                raise ModelTimeout(str(e)) from e
            raise ModelFailure(str(e)) from e
        cost = 0.0
        if reply.usage is not None:
            cost = await self.budget.record(reply.usage, self.label)
        return parse_json_object(reply.text), cost

    async def _ask(self, messages: list[ChatMessage], schema: dict) -> ChatReply:
        """Chama o chat com o schema como saída estruturada (o ``schema_instruction`` continua no
        prompt: ajuda modelos pequenos). Se o provedor recusar o schema (400), repete uma vez só
        com JSON simples e não tenta mais o schema neste modelo."""
        # A conversa do Pedro é dado pessoal: provedor em cota gratuita recusa (R21.5).
        if self.structured:
            try:
                return await asyncio.wait_for(
                    self.chat.chat(messages, json_mode=True, json_schema=schema, personal=True),
                    self.timeout_s,
                )
            except ProviderError as e:
                if not schema_refused(e):
                    raise
                log.warning("learning %s: schema recusado, seguindo com JSON simples (%s)", self.label, e)
                self.structured = False
        return await asyncio.wait_for(self.chat.chat(messages, json_mode=True, personal=True), self.timeout_s)


def openai_chat(config: Config, registry: Any, task: LearningTask, label: LearningCostTask) -> ChatLike:
    """``GuardedChat`` para uma tarefa ``[tasks] learning_*`` (chaves e backend do registro).

    O ``Registry.chat`` só atende ``ProviderTask`` (agent/news); aqui o contexto é montado com o
    modelo, as opções e o rótulo da tarefa do Learning Mode."""
    from magi.providers.base import CallCtx
    from magi.providers.registry import GuardedChat

    pcfg = config.providers[task.provider]
    options = dict(task.task.options)
    options["timeout_s"] = task.timeout_s
    ctx = CallCtx(provider=task.provider, task=label, model=task.model, options=options)  # type: ignore[arg-type]
    backend = registry._backend(pcfg)  # noqa: SLF001 - mesmo backend/cliente HTTP do núcleo
    return GuardedChat(backend, ctx, registry.pool(pcfg.name), _NoCoreBudget(), pcfg.free_tier)


# ---------------------------------------------------------------------------------------------
# FakeModel
# ---------------------------------------------------------------------------------------------


def fake_key(system: str, user: str, schema: Mapping[str, Any]) -> str:
    """Chave padrão do ``FakeModel``: ``"<title do schema>:<user>"`` (``title`` ausente = ``*``)."""
    return f"{schema.get('title', '*')}:{user}"


class FakeModel:
    """``LearningModel`` de teste: respostas gravadas por chave, sem rede (regra 7).

    Busca, em ordem: ``fake_key(...)``, o ``user`` puro, ``"<title>:*"`` e ``"*"``. O valor é um
    ``dict`` (resposta), um ``str`` (texto cru, decodificado como o modelo real) ou uma exceção
    (levantada). Com ``budget``, confere o teto e grava o custo como o ``OpenAIModel``.
    ``calls`` guarda ``(system, user, schema)`` de cada chamada que chegou ao "modelo".
    """

    def __init__(
        self,
        responses: Mapping[str, dict | str | BaseException] | None = None,
        *,
        cost_usd: float = 0.0,
        delay_s: float = 0.0,
        budget: LearningBudget | None = None,
        label: LearningCostTask | str = LearningCostTask.ACTIONS,
        model: str = "fake",
    ) -> None:
        self.responses: dict[str, dict | str | BaseException] = dict(responses or {})
        self.cost_usd = cost_usd
        self.delay_s = delay_s
        self.budget = budget
        self.label = LearningCostTask(label)
        self.model = model
        self.calls: list[tuple[str, str, dict]] = []

    @classmethod
    def from_file(cls, path: str | Path, **kwargs: Any) -> FakeModel:
        """Respostas de um JSON ``{chave: resposta}``."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: esperado um objeto JSON {{chave: resposta}}")
        return cls(data, **kwargs)

    def __repr__(self) -> str:
        return f"<FakeModel {self.label}: {self.model} ({len(self.responses)} respostas)>"

    def _lookup(self, system: str, user: str, schema: Mapping[str, Any]) -> dict | str | BaseException:
        title = schema.get("title", "*")
        for key in (fake_key(system, user, schema), user, f"{title}:*", "*"):
            if key in self.responses:
                return self.responses[key]
        raise ModelFailure(f"FakeModel: sem resposta gravada para {fake_key(system, user, schema)!r}")

    async def complete(self, system: str, user: str, schema: dict) -> tuple[dict, float]:
        if self.budget is not None:
            try:
                await self.budget.ensure_allowed(self.label)
            except BudgetExceeded as e:
                raise ModelBudget(str(e)) from e
        self.calls.append((system, user, schema))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        answer = self._lookup(system, user, schema)
        if isinstance(answer, BaseException):
            raise answer
        cost = self.cost_usd
        if self.budget is not None:
            usage = Usage(provider="fake", task=self.label, model=self.model, usd=self.cost_usd)  # type: ignore[arg-type]
            cost = await self.budget.record(usage, self.label)
        data = parse_json_object(answer) if isinstance(answer, str) else dict(answer)
        return data, cost


# ---------------------------------------------------------------------------------------------
# Escolha pelo config (ENG-002, CA-04)
# ---------------------------------------------------------------------------------------------

#: ``kind`` do provedor (``[providers.<p>] kind``, padrão = nome) que vira ``OpenAIModel``.
OPENAI_KINDS = ("openai",)
FAKE_KIND = "fake"


def build_model(
    config: Config,
    task_name: str,
    *,
    budget: LearningBudget,
    registry: Any = None,
) -> LearningModel:
    """``LearningModel`` da tarefa ``learning_actions``/``learning_observe`` lida do config.

    Trocar a linha ``[tasks] learning_*`` troca o modelo sem mudar código (CA-04). Provedor de
    ``kind = "fake"`` vira ``FakeModel`` (respostas do JSON em ``fixtures`` da tarefa, se houver).
    """
    label = LearningCostTask(task_name)
    tasks = learning_tasks(config)
    task = tasks.actions if label is LearningCostTask.ACTIONS else tasks.observe
    if task is None:
        raise ConfigError(f"tarefa '{task_name}' não configurada em [tasks]")
    pcfg = config.providers[task.provider]
    kind = str(pcfg.options.get("kind", pcfg.name))
    if kind == FAKE_KIND:
        fixtures = task.task.options.get("fixtures")
        kw: dict[str, Any] = {"budget": budget, "label": label, "model": task.model}
        return FakeModel.from_file(fixtures, **kw) if fixtures else FakeModel(**kw)
    if kind in OPENAI_KINDS:
        if registry is None:
            raise ConfigError(f"tasks.{task_name}: provedor '{kind}' precisa do registro de provedores")
        chat = openai_chat(config, registry, task, label)
        return OpenAIModel(chat, budget, label=label, model=task.model, timeout_s=task.timeout_s)
    raise ConfigError(
        f"tasks.{task_name}: provedor '{task.provider}' (kind '{kind}') sem LearningModel; "
        f"use um de {', '.join((*OPENAI_KINDS, FAKE_KIND))}"
    )
