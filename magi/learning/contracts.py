"""Contratos do Learning Mode (tarefa LM0.1; spec §1 e §3, ENG-002).

Este arquivo é a única coisa que uma tarefa do Learning Mode precisa ler para falar com módulos de
outras tarefas. Só tipos, constantes, enums e funções puras: nada de I/O aqui.

Mapa rápido
-----------
- IDs (spec §1): ``make_session_id`` / ``session_day_n`` (``LS-AAAAMMDD-NN``) e ``new_action_id``
  (``ACT-`` + 8 hex).
- Enums: ``Author``, ``Source``, ``ActionKind``, ``ObsCategory``, ``Topic``.
- Conversa e ações: ``LearningMessage``, ``Selection``, ``ActionRequest``, ``ActionResult``.
- Background: ``Observation``.
- Sessão: ``TopicContext`` (LM-013), ``SessionSummary`` (LM-011), ``SavedWord`` (LM-012).

Convenções
----------
- Datas/horas são ``datetime`` com fuso (UTC); no fio, ISO 8601.
- Dataclasses imutáveis (``frozen``); use ``dataclasses.replace`` para derivar.
- Chaves JSON em ``snake_case``. Campos opcionais ``None`` são omitidos no fio e voltam como
  ``None`` na leitura.
- Todo contrato tem ``to_dict``/``to_json`` e ``from_dict``/``from_json`` (ida e volta exata).
"""

from __future__ import annotations

import json
import re
import secrets
import types
import typing
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Self

# ---------------------------------------------------------------------------------------------
# IDs (spec §1)
# ---------------------------------------------------------------------------------------------

#: ``LS-20261007-01``: data local do início + número da sessão no dia (2 dígitos ou mais).
SESSION_ID_RE = re.compile(r"^LS-(\d{8})-(\d{2,})$")
#: ``ACT-1f9a02c4``: uuid curto de 8 hex.
ACTION_ID_RE = re.compile(r"^ACT-[0-9a-f]{8}$")


def make_session_id(day: date, n: int) -> str:
    """ID da sessão ``n`` (1, 2, …) do dia ``day`` (spec §1)."""
    if n < 1:
        raise ValueError(f"número da sessão no dia deve ser >= 1: {n}")
    return f"LS-{day:%Y%m%d}-{n:02d}"


def session_day_n(session_id: str) -> int:
    """O ``NN`` de ``LS-…-NN`` (usado no cartão LAST SESSION, LM-011)."""
    m = SESSION_ID_RE.match(session_id)
    if m is None:
        raise ValueError(f"ID de sessão inválido: {session_id!r}")
    return int(m.group(2))


def new_action_id() -> str:
    """Novo ID de ação ``ACT-`` + 8 hex (spec §1)."""
    return f"ACT-{secrets.token_hex(4)}"


# ---------------------------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------------------------


class Author(StrEnum):
    """Quem escreveu a mensagem do histórico (CNV-001, LM-002)."""

    YOU = "you"
    CONDESSA = "condessa"


class Source(StrEnum):
    """Por onde a mensagem entrou: voz (texto ``heard`` do STT) ou digitada (LM-001, LM-002)."""

    VOICE = "voice"
    TEXT = "text"


class ActionKind(StrEnum):
    """Ações do menu de seleção (SEL-003). ``ASK`` (ASK-001) é FUTURE e não existe no MVP."""

    IMPROVE = "improve"
    EXPLAIN = "explain"
    TRANSLATE = "translate"
    VOCABULARY = "vocabulary"


class ObsCategory(StrEnum):
    """Grupos do drawer de observações (OBS-002)."""

    VOCABULARY = "vocabulary"
    GRAMMAR = "grammar"
    RECURRING = "recurring"


class Topic(StrEnum):
    """Tema da conversa escolhido no seletor ou por voz (LM-013, LM-014)."""

    FREE = "free"
    INTERVIEW = "interview"
    GAME = "game"
    NEWS = "news"


#: Rótulo de cada tema na UI e no ``TopicContext.label`` (LM-013, spec §10.1).
TOPIC_LABELS: dict[Topic, str] = {
    Topic.FREE: "FREE TALK",
    Topic.INTERVIEW: "TECH INTERVIEW",
    Topic.GAME: "THE GAME I'M PLAYING",
    Topic.NEWS: "TODAY'S NEWS",
}
#: Tamanho máximo do bloco de contexto do tema no prompt (LM-013).
TOPIC_BLOCK_MAX = 1500
#: Erros possíveis de ``ActionResult.error`` (LM-007).
ACTION_ERRORS = ("timeout", "budget", "model", "invalid")
#: Motivos de fim de sessão (LM-011).
END_REASONS = ("button", "voice", "idle", "shutdown")
#: Limites das listas do resumo (LM-011, spec §10.2).
SUMMARY_PRACTICED_MAX = 5
SUMMARY_WORDS_MAX = 8


# ---------------------------------------------------------------------------------------------
# Serialização JSON genérica (ida e volta)
# ---------------------------------------------------------------------------------------------


def _encode(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return value.to_dict()  # type: ignore[attr-defined]
    if isinstance(value, list):
        return [_encode(v) for v in value]
    return value


def _decode(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(tp)
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return _decode(args[0], value) if len(args) == 1 else value
    if origin is list:
        (inner,) = typing.get_args(tp)
        return [_decode(inner, v) for v in value]
    if origin is dict or tp is dict:
        return dict(value)
    if isinstance(tp, type):
        if issubclass(tp, StrEnum):
            return tp(value)
        if tp is datetime:
            return datetime.fromisoformat(value)
        if tp is float:
            return float(value)
        if is_dataclass(tp):
            return tp.from_dict(value)  # type: ignore[attr-defined]
    return value


class _Wire:
    """Base dos contratos: ``to_dict``/``to_json`` e ``from_dict``/``from_json``."""

    __slots__ = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):  # type: ignore[arg-type]
            v = getattr(self, f.name)
            if v is not None:
                out[f.name] = _encode(v)
        return out

    def to_json(self) -> str:
        """Uma linha JSON, sem quebra de linha no fim."""
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        hints = typing.get_type_hints(cls)
        kwargs: dict[str, Any] = {}
        for f in fields(cls):  # type: ignore[arg-type]
            tp = hints[f.name]
            if f.name not in data:
                if type(None) in typing.get_args(tp):
                    kwargs[f.name] = None
                    continue
                raise ValueError(f"{cls.__name__}: campo obrigatório ausente: {f.name}")
            kwargs[f.name] = _decode(tp, data[f.name])
        return cls(**kwargs)

    @classmethod
    def from_json(cls, line: str) -> Self:
        data = json.loads(line)
        if not isinstance(data, dict):
            raise ValueError(f"{cls.__name__}: JSON deve ser um objeto")
        return cls.from_dict(data)


# ---------------------------------------------------------------------------------------------
# Conversa e ações
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LearningMessage(_Wire):
    """Mensagem do histórico (CNV-001, LM-001, LM-002). ``text`` é o que aparece e é
    selecionável; para a voz do Pedro é o ``heard`` do STT, antes de qualquer correção."""

    id: int
    session_id: str
    author: Author
    source: Source
    text: str
    at: datetime


@dataclass(frozen=True, slots=True)
class Selection(_Wire):
    """Trecho selecionado de uma mensagem (SEL-001): ``[start, end)`` em caracteres de ``text``
    da mensagem; ``text`` = ``message.text[start:end]`` (conferido por ``matches``)."""

    message_id: int
    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.end:
            raise ValueError(f"seleção vazia ou invertida: [{self.start}, {self.end})")
        if len(self.text) != self.end - self.start:
            raise ValueError("Selection.text não tem o tamanho de [start, end)")

    def matches(self, message: LearningMessage) -> bool:
        """``True`` se a seleção é desta mensagem e o texto bate com o recorte."""
        return message.id == self.message_id and message.text[self.start : self.end] == self.text


@dataclass(frozen=True, slots=True)
class ActionRequest(_Wire):
    """Pedido de ação sobre a seleção (SEL-001, SEL-003; IMP-*, EXP-*, TRA-*, VOC-*).
    ``context`` = a mensagem selecionada + até 2 anteriores."""

    id: str
    kind: ActionKind
    selection: Selection
    context: list[LearningMessage]


@dataclass(frozen=True, slots=True)
class ActionResult(_Wire):
    """Resultado de uma ação (LM-006, LM-007). ``data`` segue o schema do ``kind`` (spec §5);
    ``error`` é um de ``ACTION_ERRORS`` quando ``ok`` é falso."""

    id: str
    kind: ActionKind
    ok: bool
    data: dict | None
    error: str | None
    cached: bool
    ms: int
    cost_usd: float


@dataclass(frozen=True, slots=True)
class Observation(_Wire):
    """Observação de background (CNV-003, ENG-001, OBS-002). ``rule_key`` é estável
    (ex. ``"grammar.past_simple.irregular"``) para correlacionar no futuro (MEM-002); ``label`` é
    o que a UI mostra; ``span`` é o trecho de origem."""

    id: int | None
    session_id: str
    message_id: int
    category: ObsCategory
    rule_key: str
    label: str
    span: str | None
    suggestion: str | None


# ---------------------------------------------------------------------------------------------
# Sessão: tema, resumo e palavras salvas
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TopicContext(_Wire):
    """Tema efetivo da sessão (LM-013, spec §10.1). ``topic`` pode ser ``FREE`` por falta de
    dados mesmo com outro ``requested``; ``detail`` diz o motivo (``"no game detected"`` |
    ``"no news today"``). ``block`` é o contexto do prompt (≤ ``TOPIC_BLOCK_MAX``), ``None`` em
    ``FREE``."""

    topic: Topic
    requested: Topic
    label: str
    block: str | None
    detail: str | None

    def __post_init__(self) -> None:
        if self.block is not None and len(self.block) > TOPIC_BLOCK_MAX:
            raise ValueError(f"TopicContext.block passa de {TOPIC_BLOCK_MAX} caracteres")


@dataclass(frozen=True, slots=True)
class SessionSummary(_Wire):
    """Resumo da sessão para o cartão LAST SESSION (LM-011, spec §10.2). ``n`` é o ``NN`` de
    ``LS-…-NN``; ``end_reason`` é um de ``END_REASONS``. ``practiced`` (≤ 5) e ``new_words``
    (≤ 8) já vêm cortados; ``more_*`` contam o que ficou de fora (``+N``). Sem nota nem streak."""

    session_id: str
    n: int
    started_at: datetime
    ended_at: datetime
    duration_s: int
    end_reason: str
    n_msgs: int
    n_you: int
    obs_count: int
    practiced: list[str]
    new_words: list[str]
    saved: list[str]
    more_practiced: int
    more_words: int
    topics: list[str]


@dataclass(frozen=True, slots=True)
class SavedWord(_Wire):
    """Palavra/expressão guardada pelo balão do Vocabulary (LM-012, spec §10.3). Chave lógica
    ``norm``; ``example`` é a frase de origem; ``removed_at`` marca a remoção (desfazer)."""

    id: int | None
    norm: str
    term: str
    meaning: str
    pos: str | None
    cefr: str | None
    example: str
    session_id: str
    message_id: int
    action_id: str
    saved_at: datetime
    removed_at: datetime | None
