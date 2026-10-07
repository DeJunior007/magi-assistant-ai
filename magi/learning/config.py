"""Leitura tipada da seção ``[learning]`` e das tarefas ``[tasks] learning_*`` (tarefa LM0.1;
spec §2, ENG-002, LM-008, LM-009).

Tudo tem padrão: sem ``[learning]`` no config o modo funciona com os valores da spec §2. As
tarefas de LLM são opcionais aqui; quem chama decide o que fazer sem elas (ENG-002: o roteamento
do modelo muda só no config).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from magi.common.config import Config, ConfigError, TaskConfig
from magi.learning.contracts import Topic

#: Níveis aceitos no rótulo ``B2 · CONVERSATION`` (UI-002, LM-009).
LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
#: Idioma das explicações de Improve/Explain/Vocabulary (LM-008, P5).
EXPLAIN_LANGUAGES = ("en", "pt-br")
#: Backends do repositório (P4).
STORAGES = ("postgres", "jsonl")
#: Nomes das tarefas de LLM do Learning Mode em ``[tasks]``.
TASK_ACTIONS = "learning_actions"
TASK_OBSERVE = "learning_observe"
#: Prazo padrão de cada tarefa quando ``timeout_s`` falta (spec §2).
DEFAULT_TIMEOUTS_S = {TASK_ACTIONS: 8.0, TASK_OBSERVE: 20.0}


@dataclass(frozen=True)
class LearningConfig:
    """Seção ``[learning]`` (spec §2). Nível e trilha são manuais no MVP (LM-009); o idioma das
    explicações segue LM-008 (Translate sempre em ``translate_to``)."""

    enabled: bool = True
    level: str = "B2"
    track: str = "CONVERSATION"
    explain_language: str = "en"
    translate_to: str = "pt-br"
    speak_replies: bool = True
    idle_end_min: int = 20
    observe: bool = True
    observe_daily_max: int = 200
    storage: str = "postgres"
    default_topic: Topic = Topic.FREE
    topic_picker_s: int = 10
    summary_show_s: int = 60

    @property
    def level_label(self) -> str:
        """Rótulo do topo da tela, ex. ``"B2 · CONVERSATION"`` (UI-002, LM-009)."""
        return f"{self.level} · {self.track}"


@dataclass(frozen=True)
class LearningTask:
    """Uma tarefa ``[tasks] learning_*`` tipada (ENG-002): provedor, modelo, prazo e esforço."""

    name: str
    provider: str
    model: str
    timeout_s: float
    reasoning_effort: str | None
    task: TaskConfig


@dataclass(frozen=True)
class LearningTasks:
    """``learning_actions`` (ações do menu) e ``learning_observe`` (background); ``None`` se a
    tarefa não está no config (ENG-002)."""

    actions: LearningTask | None
    observe: LearningTask | None


def _bool(sec: dict[str, Any], key: str, default: bool) -> bool:
    v = sec.get(key, default)
    if not isinstance(v, bool):
        raise ConfigError(f"learning.{key} deve ser true ou false")
    return v


def _int(sec: dict[str, Any], key: str, default: int, minimum: int) -> int:
    v = sec.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ConfigError(f"learning.{key} deve ser um inteiro >= {minimum}")
    return v


def _choice(sec: dict[str, Any], key: str, default: str, allowed: tuple[str, ...]) -> str:
    v = sec.get(key, default)
    if isinstance(v, str):
        v = v.strip()
        v = v.upper() if allowed is LEVELS else v.lower()
    if v not in allowed:
        raise ConfigError(f"learning.{key} deve ser um de {', '.join(allowed)}: {v!r}")
    return v


def _str(sec: dict[str, Any], key: str, default: str) -> str:
    v = sec.get(key, default)
    if not isinstance(v, str) or not v.strip():
        raise ConfigError(f"learning.{key} deve ser um texto não vazio")
    return v.strip()


def parse_learning(raw: dict[str, Any]) -> LearningConfig:
    """``LearningConfig`` a partir do dicionário do TOML inteiro (lê só ``[learning]``)."""
    sec = raw.get("learning") or {}
    if not isinstance(sec, dict):
        raise ConfigError("learning deve ser uma tabela")
    d = LearningConfig()
    topic = _choice(sec, "default_topic", d.default_topic.value, tuple(t.value for t in Topic))
    return LearningConfig(
        enabled=_bool(sec, "enabled", d.enabled),
        level=_choice(sec, "level", d.level, LEVELS),
        track=_str(sec, "track", d.track).upper(),
        explain_language=_choice(sec, "explain_language", d.explain_language, EXPLAIN_LANGUAGES),
        translate_to=_str(sec, "translate_to", d.translate_to).lower(),
        speak_replies=_bool(sec, "speak_replies", d.speak_replies),
        idle_end_min=_int(sec, "idle_end_min", d.idle_end_min, 1),
        observe=_bool(sec, "observe", d.observe),
        observe_daily_max=_int(sec, "observe_daily_max", d.observe_daily_max, 0),
        storage=_choice(sec, "storage", d.storage, STORAGES),
        default_topic=Topic(topic),
        topic_picker_s=_int(sec, "topic_picker_s", d.topic_picker_s, 1),
        summary_show_s=_int(sec, "summary_show_s", d.summary_show_s, 1),
    )


def _task(config: Config, name: str) -> LearningTask | None:
    t = config.tasks.get(name)
    if t is None:
        return None
    raw_timeout = t.options.get("timeout_s", DEFAULT_TIMEOUTS_S[name])
    try:
        timeout_s = float(raw_timeout)
    except (TypeError, ValueError):
        raise ConfigError(f"tasks.{name}.timeout_s deve ser um número") from None
    if timeout_s <= 0:
        raise ConfigError(f"tasks.{name}.timeout_s deve ser maior que zero")
    effort = t.options.get("reasoning_effort")
    return LearningTask(
        name=name,
        provider=t.provider,
        model=t.model,
        timeout_s=timeout_s,
        reasoning_effort=str(effort) if effort is not None else None,
        task=t,
    )


def learning_config(config: Config) -> LearningConfig:
    """Seção ``[learning]`` do ``Config`` já carregado."""
    return parse_learning(config.raw)


def learning_tasks(config: Config) -> LearningTasks:
    """Tarefas ``[tasks] learning_actions`` e ``learning_observe`` tipadas (ENG-002)."""
    return LearningTasks(actions=_task(config, TASK_ACTIONS), observe=_task(config, TASK_OBSERVE))
