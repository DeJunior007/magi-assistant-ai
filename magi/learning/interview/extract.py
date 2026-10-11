"""Extração do ``JobProfile`` a partir da vaga (dona: **LI1.1**; spec §2–§3, R2.2, R2.5, R7.1).

``extract(post, model)`` faz uma chamada ao modelo com o prompt ``prompts/interview/extract.md`` e
o schema da spec §2, dentro do prazo de 20 s, e confere a resposta antes de virar ``JobProfile``:

- ``evidence`` normalizada (minúsculas, espaços simples) precisa estar no texto normalizado da
  vaga, senão o requisito cai (o modelo não inventa requisito, R7.1);
- ``stack`` minúscula, sem duplicata, ≤ 12; ``seniority`` fora do enum → ``UNKNOWN``;
- sem ``title`` → ``ModelInvalid``; qualquer outra resposta fora do contrato também.

``build_job_model(config, budget=…, registry=…)`` escolhe ``[tasks] learning_job`` ou, sem ela,
``learning_actions`` (D8), sobre o ``build_model`` existente.
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
from pathlib import Path
from typing import Any

from magi.common.config import Config, ConfigError, TaskConfig
from magi.learning.config import TASK_ACTIONS, TASK_JOB
from magi.learning.interview.contracts import (
    EVIDENCE_MAX,
    EXTRACT_TIMEOUT_S,
    REMOTES,
    REQ_KINDS,
    REQUIREMENTS_MAX,
    RESPONSIBILITIES_MAX,
    STACK_MAX,
    JobPost,
    JobProfile,
    Requirement,
    Seniority,
)
from magi.learning.model import (
    LearningModel,
    ModelError,
    ModelFailure,
    ModelInvalid,
    ModelTimeout,
    build_model,
)

PROMPT = Path(__file__).parent.parent / "prompts" / "interview" / "extract.md"
__all__ = ["PROMPT", "SCHEMA", "TASK_JOB", "build_job_model", "extract", "profile_of"]

_NULLABLE = {"type": ["string", "null"]}
_STRINGS = {"type": "array", "items": {"type": "string"}}

#: Schema da extração (spec §2, "Schema da extração"); ``title`` é a chave do ``FakeModel``.
SCHEMA: dict[str, Any] = {
    "title": "job_profile",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title", "company", "seniority", "language", "stack", "requirements",
        "responsibilities", "domain", "remote",
    ],
    "properties": {
        "title": {"type": "string"},
        "company": _NULLABLE,
        "seniority": {"type": "string", "enum": [s.value for s in Seniority]},
        "language": {"type": "string"},
        "stack": _STRINGS,
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "kind", "skill", "evidence"],
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": list(REQ_KINDS)},
                    "skill": _NULLABLE,
                    "evidence": {"type": "string"},
                },
            },
        },
        "responsibilities": _STRINGS,
        "domain": _NULLABLE,
        "remote": {"type": ["string", "null"], "enum": [*REMOTES, None]},
    },
}

_SPACES = re.compile(r"\s+")


def _flat(text: str) -> str:
    """Minúsculas e espaços simples (comparação de ``evidence``, spec §2)."""
    return _SPACES.sub(" ", text).strip().lower()


def _opt(v: Any) -> str | None:
    """Texto curto opcional: vazio, não texto ou "null"/"none" viram ``None``."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s if s and s.lower() not in ("null", "none", "n/a", "unknown") else None


def _strings(v: Any) -> list[str]:
    return [s.strip() for s in v if isinstance(s, str) and s.strip()] if isinstance(v, list) else []


def _seniority(v: Any) -> Seniority:
    try:
        return Seniority(str(v).strip().lower())
    except ValueError:
        return Seniority.UNKNOWN


def _stack(v: Any) -> tuple[str, ...]:
    out: list[str] = []
    for s in _strings(v):
        s = _SPACES.sub(" ", s.lower())
        if s not in out:
            out.append(s)
    return tuple(out[:STACK_MAX])


def _requirements(v: Any, haystack: str) -> tuple[Requirement, ...]:
    """Requisitos com ``evidence`` achada na vaga; ``must`` primeiro, ≤ 14."""
    kept: list[Requirement] = []
    for item in v if isinstance(v, list) else []:
        if not isinstance(item, dict):
            continue
        text = _opt(item.get("text"))
        evidence = _SPACES.sub(" ", str(item.get("evidence") or "")).strip()[:EVIDENCE_MAX].strip()
        if text is None or not evidence or _flat(evidence) not in haystack:
            continue  # requisito sem trecho literal da vaga = inventado (CA-02)
        kind = str(item.get("kind") or "").strip().lower()
        skill = _opt(item.get("skill"))
        kept.append(Requirement(
            text=text,
            kind=kind if kind in REQ_KINDS else "nice",
            skill=skill.lower() if skill else None,
            evidence=evidence,
        ))
    kept.sort(key=lambda r: r.kind != "must")  # estável: mantém a ordem da vaga
    return tuple(kept[:REQUIREMENTS_MAX])


def profile_of(data: dict[str, Any], post: JobPost) -> JobProfile:
    """``JobProfile`` da resposta do modelo, com a pós-checagem da spec §2. ``ModelInvalid`` se a
    resposta não serve (sem título ou fora do contrato)."""
    title = _opt(data.get("title"))
    if title is None:
        raise ModelInvalid("perfil da vaga sem title")
    remote = (_opt(data.get("remote")) or "").lower()
    try:
        return JobProfile(
            title=title,
            company=_opt(data.get("company")),
            seniority=_seniority(data.get("seniority")),
            language=(_opt(data.get("language")) or "en").lower(),
            stack=_stack(data.get("stack")),
            requirements=_requirements(data.get("requirements"), _flat(post.text)),
            responsibilities=tuple(_strings(data.get("responsibilities"))[:RESPONSIBILITIES_MAX]),
            domain=_opt(data.get("domain")),
            remote=remote if remote in REMOTES else None,
        )
    except (ValueError, TypeError) as e:
        raise ModelInvalid(f"perfil da vaga fora do contrato: {e}") from e


def _user(post: JobPost) -> str:
    """A vaga como dado dentro de ``<job_post>`` (a tag não pode ser fechada pelo texto)."""
    body = re.sub(r"</?\s*job_post\s*>", "", post.text, flags=re.IGNORECASE)
    return f"<job_post>\n{body}\n</job_post>"


async def extract(
    post: JobPost, model: LearningModel, *, timeout_s: float = EXTRACT_TIMEOUT_S
) -> JobProfile:
    """Uma chamada ao modelo (schema da spec §2) + pós-checagem de ``evidence``/stack/senioridade.
    Erros viram ``ModelError`` (``timeout|budget|model|invalid``)."""
    system = PROMPT.read_text(encoding="utf-8")
    try:
        data, _cost = await asyncio.wait_for(model.complete(system, _user(post), SCHEMA), timeout_s)
    except TimeoutError as e:
        raise ModelTimeout(f"extração da vaga sem resposta em {timeout_s:g} s") from e
    except ModelError:
        raise
    except Exception as e:  # noqa: BLE001 - qualquer falha do modelo vira ModelError (LM-007)
        raise ModelFailure(f"extração da vaga: {e}") from e
    if not isinstance(data, dict):
        raise ModelInvalid("resposta da extração não é um objeto")
    return profile_of(data, post)


def build_job_model(config: Config, **kwargs: Any) -> LearningModel:
    """Modelo da tarefa ``learning_job`` ou, sem ela, de ``learning_actions`` (D8).

    Usa o ``build_model`` existente (``kwargs``: ``budget``, ``registry``) com a tarefa escolhida
    no lugar de ``learning_actions``; sem ``timeout_s`` explícito o prazo é o da extração (20 s),
    não os 8 s das ações. O custo sai com o rótulo ``learning_actions`` (o ``LearningCostTask``
    não tem rótulo próprio da vaga)."""
    task = config.tasks.get(TASK_JOB) or config.tasks.get(TASK_ACTIONS)
    if task is None:
        raise ConfigError(f"nem '{TASK_JOB}' nem '{TASK_ACTIONS}' configuradas em [tasks]")
    options = {"timeout_s": EXTRACT_TIMEOUT_S, **task.options}
    chosen = TaskConfig(name=TASK_ACTIONS, provider=task.provider, model=task.model, options=options)
    derived = dataclasses.replace(config, tasks={**config.tasks, TASK_ACTIONS: chosen})
    return build_model(derived, TASK_ACTIONS, **kwargs)
